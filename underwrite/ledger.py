"""Per-company spend ledger: LLM tokens and dollars, Crustdata credits, cache hits."""

from __future__ import annotations

import contextvars
from dataclasses import asdict, dataclass, field

# USD per 1M tokens (input, output). List prices; Bedrock global endpoints price at parity.
PRICES = {
    "claude-opus-5-5": (4.00, 20.00),
    "claude-opus-5": (5.00, 25.00),
    "claude-opus-4-8": (5.00, 25.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-haiku-4-5": (1.00, 5.00),
}


def price_for(model: str) -> tuple[float, float]:
    bare = model.split("anthropic.")[-1]
    for key, p in PRICES.items():
        if bare.startswith(key):
            return p
    return (5.00, 25.00)  # unknown model: assume Opus-tier so estimates err high


@dataclass
class Ledger:
    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    llm_usd: float = 0.0
    by_model: dict = field(default_factory=dict)
    crust_calls: int = 0
    crust_credits: float = 0.0
    cache_hits: int = 0
    fallback_calls: int = 0

    def add_llm(self, model: str, input_tokens: int, output_tokens: int) -> None:
        pin, pout = price_for(model)
        usd = input_tokens / 1e6 * pin + output_tokens / 1e6 * pout
        self.llm_calls += 1
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.llm_usd += usd
        m = self.by_model.setdefault(model, {"calls": 0, "in": 0, "out": 0, "usd": 0.0})
        m["calls"] += 1
        m["in"] += input_tokens
        m["out"] += output_tokens
        m["usd"] += usd

    def to_dict(self) -> dict:
        d = asdict(self)
        d["llm_usd"] = round(self.llm_usd, 5)
        return d


_current: contextvars.ContextVar[Ledger] = contextvars.ContextVar("uw_ledger", default=Ledger())


def current() -> Ledger:
    return _current.get()


def bind(ledger: Ledger) -> contextvars.Token:
    return _current.set(ledger)


def unbind(token: contextvars.Token) -> None:
    _current.reset(token)
