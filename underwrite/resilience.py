"""Retries, rate limiting, and (opt-in) fault injection."""

from __future__ import annotations

import random
import threading
import time
from collections.abc import Callable
from typing import TypeVar

from .config import settings
from .obs import emit

T = TypeVar("T")


class Retryable(Exception):
    """A failure worth retrying (429, 5xx, timeout, malformed output)."""

    def __init__(self, msg: str, retry_after: float | None = None):
        super().__init__(msg)
        self.retry_after = retry_after


class Fatal(Exception):
    """A failure retrying won't fix (bad key, no credits, model access denied)."""


class InjectedFault(Retryable):
    """A fault injected on purpose by chaos mode, so recovery paths can be demoed."""


def chaos_hit(point: str, what: str) -> bool:
    """With probability settings.chaos, report (and log) an injected fault at this call site."""
    if settings.chaos > 0 and random.random() < settings.chaos:
        emit("inject", f"chaos: {what} at {point}", point=point)
        return True
    return False


def chaos(point: str, what: str = "429 rate limited") -> None:
    """Raise an injected, retryable fault at this call site (see chaos_hit)."""
    if chaos_hit(point, what):
        raise InjectedFault(f"[injected] {what} at {point}", retry_after=1.0)


def with_retries(
    fn: Callable[[], T],
    *,
    what: str,
    attempts: int = 4,
    base_delay: float = 2.0,
    max_delay: float = 30.0,
) -> T:
    """Call fn, retrying Retryable failures with exponential backoff + jitter (honours Retry-After)."""
    for attempt in range(1, attempts + 1):
        try:
            result = fn()
        except Retryable as e:
            if attempt == attempts:
                emit("fail", f"{what}: gave up after {attempts} attempts ({e})", what=what)
                raise
            delay = e.retry_after or min(base_delay * 2 ** (attempt - 1), max_delay)
            delay += random.uniform(0, 0.5)
            emit("recover", f"{what}: {e} -> retry {attempt}/{attempts - 1} in {delay:.1f}s", what=what)
            time.sleep(delay)
        else:
            if attempt > 1:
                emit("recover", f"{what}: succeeded on attempt {attempt}", what=what, recovered=True)
            return result
    raise AssertionError("unreachable")


class RateLimiter:
    """Token bucket: at most `rate` calls per `per` seconds, bursting up to `rate`."""

    def __init__(self, rate: int, per: float):
        self.capacity = rate
        self.tokens = float(rate)
        self.fill_rate = rate / per
        self.updated = time.monotonic()
        self.lock = threading.Lock()

    def acquire(self) -> None:
        while True:
            with self.lock:
                now = time.monotonic()
                self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.fill_rate)
                self.updated = now
                if self.tokens >= 1:
                    self.tokens -= 1
                    return
                wait = (1 - self.tokens) / self.fill_rate
            time.sleep(wait)
