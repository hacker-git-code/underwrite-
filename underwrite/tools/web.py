"""Keyless fallbacks used when Crustdata's web endpoints fail: DuckDuckGo search and direct fetch."""

from __future__ import annotations

import httpx
import neatlogs
import trafilatura

from .. import cache
from ..resilience import Retryable, chaos, with_retries

UA = "Mozilla/5.0 (compatible; UnderwriteBot/0.1; +https://github.com/)"


@neatlogs.span(kind="TOOL", tool_name="ddg_search")
def search(query: str, max_results: int = 8) -> list[dict]:
    hit = cache.get("ddg", query)
    if hit is not None:
        return hit

    def call() -> list[dict]:
        from ddgs import DDGS

        try:
            rows = DDGS().text(query, max_results=max_results) or []
        except Exception as e:  # ddgs raises its own rate-limit / timeout types
            raise Retryable(f"ddg search failed: {type(e).__name__}") from e
        return [{"title": r.get("title", ""), "url": r.get("href", ""), "snippet": r.get("body", "")} for r in rows]

    results = with_retries(call, what="ddg search", attempts=3)
    cache.put("ddg", query, results)
    return results


@neatlogs.span(kind="TOOL", tool_name="direct_fetch")
def fetch(url: str) -> dict:
    hit = cache.get("fetch", url)
    if hit is not None:
        return hit

    def call() -> dict:
        chaos("web.fetch", "page fetch timeout")
        try:
            r = httpx.get(url, timeout=20.0, follow_redirects=True, headers={"user-agent": UA})
        except (httpx.TimeoutException, httpx.TransportError) as e:
            raise Retryable(f"fetch {type(e).__name__}") from e
        if r.status_code == 429 or r.status_code >= 500:
            raise Retryable(f"HTTP {r.status_code}")
        if r.status_code >= 400:
            return {"url": url, "title": "", "content": "", "success": False}
        text = trafilatura.extract(r.text, include_comments=False, include_tables=True) or ""
        meta = trafilatura.extract_metadata(r.text)
        return {"url": url, "title": (meta.title if meta else "") or "", "content": text, "success": bool(text)}

    page = with_retries(call, what=f"fetch {url[:60]}", attempts=2, base_delay=1.0)
    cache.put("fetch", url, page)
    return page
