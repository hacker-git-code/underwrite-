"""Crustdata API: company enrichment, live web search, live web fetch.

Docs: https://docs.crustdata.com (API version 2025-11-01). Rate limit is 15 req/min,
so every call goes through a shared token bucket and retries 429s with backoff.
"""

from __future__ import annotations

from typing import Any

import httpx
import neatlogs

from .. import cache, ledger
from ..config import settings
from ..obs import emit
from ..resilience import Fatal, RateLimiter, Retryable, chaos, with_retries

BASE = "https://api.crustdata.com"
_limiter = RateLimiter(rate=15, per=60.0)

ENRICH_FIELDS = [
    "basic_info",
    "headcount",
    "funding",
    "locations",
    "taxonomy",
    "people",
    "hiring",
    "revenue",
    "followers",
]


def _post(path: str, body: dict, *, credits: float, timeout: float = 60.0) -> Any:
    if not settings.crustdata_api_key:
        raise Fatal("CRUSTDATA_API_KEY is not set")

    hit = cache.get("crustdata", {"path": path, "body": body})
    if hit is not None:
        ledger.current().cache_hits += 1
        return hit

    def call() -> Any:
        chaos(f"crustdata{path}", "429 rate limited")
        _limiter.acquire()
        try:
            r = httpx.post(
                BASE + path,
                json=body,
                timeout=timeout,
                headers={
                    "authorization": f"Bearer {settings.crustdata_api_key}",
                    "content-type": "application/json",
                    "x-api-version": "2025-11-01",
                },
            )
        except (httpx.TimeoutException, httpx.TransportError) as e:
            raise Retryable(f"network error: {type(e).__name__}") from e
        if r.status_code == 429:
            ra = r.headers.get("retry-after")
            raise Retryable("429 rate limited", retry_after=float(ra) if ra and ra.isdigit() else None)
        if r.status_code >= 500:
            raise Retryable(f"HTTP {r.status_code}")
        if r.status_code in (401, 403):
            raise Fatal(f"Crustdata auth failed (HTTP {r.status_code}): {r.text[:200]}")
        if r.status_code == 402:
            raise Fatal("Crustdata: out of credits")
        if r.status_code >= 400:
            raise Fatal(f"Crustdata HTTP {r.status_code}: {r.text[:300]}")
        return r.json()

    data = with_retries(call, what=f"crustdata {path}")
    led = ledger.current()
    led.crust_calls += 1
    led.crust_credits += credits
    cache.put("crustdata", {"path": path, "body": body}, data)
    return data


@neatlogs.span(kind="TOOL", tool_name="crustdata_company_enrich")
def enrich_company(domain: str | None = None, name: str | None = None) -> dict | None:
    """Best match's company_data, or None if Crustdata has no match."""
    body: dict[str, Any] = {"fields": ENRICH_FIELDS}
    if domain:
        body |= {"domains": [domain], "exact_match": True}
    elif name:
        body |= {"names": [name]}
    else:
        raise ValueError("need a domain or a name")
    data = _post("/company/enrich", body, credits=2)
    entries = data if isinstance(data, list) else data.get("results") or data.get("data") or []
    for entry in entries:
        matches = entry.get("matches") or []
        if matches:
            best = max(matches, key=lambda m: m.get("confidence_score") or 0)
            return best.get("company_data")
    return None


@neatlogs.span(kind="TOOL", tool_name="crustdata_web_search")
def web_search(query: str) -> list[dict]:
    data = _post("/web/search/live", {"query": query, "sources": ["web"]}, credits=1)
    results = data.get("results") if isinstance(data, dict) else data
    return [
        {"title": r.get("title") or "", "url": r.get("url") or "", "snippet": r.get("snippet") or ""}
        for r in (results or [])
        if r.get("url")
    ]


@neatlogs.span(kind="TOOL", tool_name="crustdata_web_fetch")
def web_fetch(urls: list[str]) -> list[dict]:
    """Fetch up to 10 pages in one call. Returns [{url, title, content, success}]."""
    urls = urls[:10]
    data = _post("/web/enrich/live", {"urls": urls}, credits=len(urls), timeout=120.0)
    items = data if isinstance(data, list) else data.get("results") or data.get("data") or []
    out = []
    for it in items:
        out.append(
            {
                "url": it.get("url") or "",
                "title": it.get("title") or "",
                "content": it.get("content") or "",
                "success": bool(it.get("success", bool(it.get("content")))),
            }
        )
    emit("crust", f"fetched {sum(o['success'] for o in out)}/{len(urls)} pages via Crustdata")
    return out


def render_company(company: dict) -> str:
    """Flatten Crustdata JSON into 'path: value' lines so claims can quote exact lines."""
    lines: list[str] = []

    def walk(prefix: str, v: Any, depth: int = 0) -> None:
        if v is None or v == "" or v == [] or v == {}:
            return
        if isinstance(v, dict):
            for k, sub in v.items():
                walk(f"{prefix}.{k}" if prefix else k, sub, depth + 1)
        elif isinstance(v, list):
            if all(not isinstance(x, (dict, list)) for x in v):
                lines.append(f"{prefix}: {', '.join(str(x) for x in v[:25])}")
            else:
                for i, x in enumerate(v[:15]):
                    walk(f"{prefix}[{i}]", x, depth + 1)
        else:
            lines.append(f"{prefix}: {v}")

    walk("", company)
    return "\n".join(lines)
