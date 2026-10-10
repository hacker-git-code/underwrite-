"""Observability: neatlogs tracing plus a human-readable event stream.

Every notable step goes three places: the terminal (for the operator / demo),
the run's events.jsonl (so a run can be audited after the fact), and neatlogs
(as a log span inside the active trace, so the Coach can find it later).
"""

from __future__ import annotations

import contextvars
import json
import time
from pathlib import Path
from typing import Any

import neatlogs
from rich.console import Console

from .config import settings

console = Console(highlight=False)

_initialized = False
_sink: contextvars.ContextVar[Path | None] = contextvars.ContextVar("uw_event_sink", default=None)
_counters: contextvars.ContextVar[dict | None] = contextvars.ContextVar("uw_counters", default=None)

STYLE = {
    "plan": "cyan",
    "crust": "magenta",
    "web": "blue",
    "extract": "white",
    "verify": "green",
    "conflict": "bold yellow",
    "recover": "bold yellow",
    "inject": "red",
    "fail": "bold red",
    "memo": "bold green",
    "coach": "bold cyan",
    "agent": "bold cyan",
    "skeptic": "bold magenta",
    "eval": "bold white",
    "info": "dim",
}


def setup(tags: list[str] | None = None) -> None:
    """Initialise neatlogs once per process. Safe to call when no key is set (spans just aren't exported)."""
    global _initialized
    if _initialized:
        return
    neatlogs.init(
        api_key=settings.neatlogs_api_key or None,
        workflow_name="underwrite",
        instrumentations=["openai", "anthropic"],
        tags=["underwrite", *(tags or [])],
    )
    _initialized = True


def bind_run(events_path: Path) -> tuple[contextvars.Token, contextvars.Token]:
    events_path.parent.mkdir(parents=True, exist_ok=True)
    return _sink.set(events_path), _counters.set({})


def unbind_run(tokens: tuple[contextvars.Token, contextvars.Token]) -> None:
    _sink.reset(tokens[0])
    _counters.reset(tokens[1])


def counters() -> dict:
    return dict(_counters.get() or {})


def emit(kind: str, msg: str, **data: Any) -> None:
    """Record one event. `kind` is a short tag like 'crust', 'recover', 'verify'."""
    style = STYLE.get(kind, "white")
    console.print(f"[{style}]\\[{kind:<8}][/{style}] {msg}")

    c = _counters.get()
    if c is not None:
        c[kind] = c.get(kind, 0) + 1

    sink = _sink.get()
    if sink is not None:
        with sink.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"t": time.time(), "kind": kind, "msg": msg, **data}, default=str) + "\n")

    if kind in ("recover", "inject", "fail", "conflict"):
        neatlogs.log(
            "{kind}: {msg}",
            level="warning" if kind != "fail" else "error",
            kind=kind,
            msg=msg,
            **{k: v for k, v in data.items() if isinstance(v, (str, int, float, bool))},
        )


def current_trace_id() -> str | None:
    """The OpenTelemetry trace id of the active span, as neatlogs shows it."""
    try:
        from opentelemetry import trace

        ctx = trace.get_current_span().get_span_context()
        return format(ctx.trace_id, "032x") if ctx and ctx.trace_id else None
    except Exception:
        return None


def set_attrs(**attrs: Any) -> None:
    """Attach attributes (e.g. final metrics) to the active neatlogs span."""
    try:
        from opentelemetry import trace

        span = trace.get_current_span()
        for k, v in attrs.items():
            if isinstance(v, (str, int, float, bool)):
                span.set_attribute(f"underwrite.{k}", v)
    except Exception:
        pass
