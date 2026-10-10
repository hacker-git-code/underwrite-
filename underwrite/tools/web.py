"""Keyless fallbacks used when Crustdata's web endpoints fail: DuckDuckGo search and direct fetch.

Direct fetch follows URLs that came from search results, i.e. from the open web. On a cloud VM that
is an SSRF risk (e.g. http://169.254.169.254/ would hand out instance credentials), so every
request, including each redirect hop, must resolve to a public IP address.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

import httpx
import neatlogs
import trafilatura

from .. import cache
from ..obs import emit
from ..resilience import Retryable, chaos, with_retries

UA = "Mozilla/5.0 (compatible; UnderwriteBot/0.1)"
MAX_BYTES = 3_000_000


class UnsafeURL(Exception):
    pass


def check_public(url: str) -> None:
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise UnsafeURL(f"not an http(s) URL: {url[:80]}")
    try:
        infos = socket.getaddrinfo(p.hostname, p.port or (443 if p.scheme == "https" else 80))
    except socket.gaierror as e:
        raise Retryable(f"DNS lookup failed for {p.hostname}") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise UnsafeURL(f"{p.hostname} resolves to non-public address {ip}")


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
    empty = {"url": url, "title": "", "content": "", "success": False}

    def call() -> dict:
        chaos("web.fetch", "page fetch timeout")
        hooks = {"request": [lambda req: check_public(str(req.url))]}  # runs for every redirect hop too
        try:
            with httpx.Client(timeout=20.0, follow_redirects=True, max_redirects=5, event_hooks=hooks,
                              headers={"user-agent": UA}) as client, client.stream("GET", url) as r:
                if r.status_code == 429 or r.status_code >= 500:
                    raise Retryable(f"HTTP {r.status_code}")
                if r.status_code >= 400:
                    return empty
                body = b""
                for chunk in r.iter_bytes():
                    body += chunk
                    if len(body) > MAX_BYTES:
                        break
        except (httpx.TimeoutException, httpx.TransportError) as e:
            raise Retryable(f"fetch {type(e).__name__}") from e
        page = body.decode(r.encoding or "utf-8", errors="replace")
        text = trafilatura.extract(page, include_comments=False, include_tables=True) or ""
        meta = trafilatura.extract_metadata(page)
        return {"url": url, "title": (meta.title if meta else "") or "", "content": text, "success": bool(text)}

    try:
        page = with_retries(call, what=f"fetch {url[:60]}", attempts=2, base_delay=1.0)
    except UnsafeURL as e:
        emit("fail", f"blocked unsafe URL ({e})")
        return empty
    cache.put("fetch", url, page)
    return page
