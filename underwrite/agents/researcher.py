"""Researcher: gathers evidence within a fixed budget. Crustdata first; keyless fallbacks if it fails."""

from __future__ import annotations

from urllib.parse import urlparse

import neatlogs

from ..config import settings
from ..models import CompanyState, Evidence
from ..obs import emit
from ..resilience import Fatal, Retryable
from ..tools import crustdata, web

SKIP_HOSTS = (
    "linkedin.com",
    "facebook.com",
    "instagram.com",
    "twitter.com",
    "x.com",
    "youtube.com",
    "tiktok.com",
    "glassdoor.",
    "pinterest.",
    "reddit.com",
)


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").removeprefix("www.")


def _next_id(state: CompanyState) -> str:
    return f"E{len(state.evidence) + 1}"


def _add(state: CompanyState, **kw) -> Evidence:
    ev = Evidence(id=_next_id(state), round=state.round, **kw)
    state.evidence.append(ev)
    return ev


def _search(query: str) -> tuple[list[dict], str]:
    try:
        return crustdata.web_search(query), "crustdata-web"
    except (Fatal, Retryable) as e:
        emit("recover", f"Crustdata search failed ({e}); falling back to DuckDuckGo", query=query)
        try:
            return web.search(query), "ddg"
        except Retryable as e2:
            emit("fail", f"search failed on both providers: {e2}", query=query)
            return [], "none"


def _fetch(urls: list[str]) -> list[dict]:
    pages: list[dict] = []
    try:
        pages = crustdata.web_fetch(urls)
    except (Fatal, Retryable) as e:
        emit("recover", f"Crustdata fetch failed ({e}); fetching {len(urls)} pages directly")
    got = {p["url"] for p in pages if p.get("success") and p.get("content")}
    missing = [u for u in urls if u not in got]
    if pages and missing:
        emit("recover", f"{len(missing)} pages empty via Crustdata; retrying them directly")
    for u in missing:
        try:
            page = web.fetch(u)
        except Retryable as e:
            emit("fail", f"could not fetch {u[:70]}: {e}")
            continue
        page["via"] = "direct"
        pages = [p for p in pages if p.get("url") != u] + [page]
    return pages


@neatlogs.span(kind="AGENT", name="researcher", role="researcher", goal="collect source evidence within budget")
def research(state: CompanyState, queries: list[tuple[str, str]]) -> list[Evidence]:
    before = len(state.evidence)

    if not any(e.kind == "crustdata" for e in state.evidence):
        try:
            record = crustdata.enrich_company(domain=state.domain, name=None if state.domain else state.company)
        except (Fatal, Retryable) as e:
            emit("recover", f"Crustdata enrichment unavailable ({e}); continuing with web sources only")
            record = None
        if record:
            text = crustdata.render_company(record)
            name = (record.get("basic_info") or {}).get("name") or state.company
            _add(state, kind="crustdata", url=f"crustdata://company/{record.get('crustdata_company_id', '')}",
                 title=f"Crustdata company record: {name}", text=text, via="crustdata")
            emit("crust", f"company record: {len(text.splitlines())} fields")
        else:
            emit("crust", "no Crustdata match for this company")

    budget = max(0, settings.max_searches - len(state.searched))
    candidates: list[tuple[str, str]] = []  # (url, question_id)
    company_host = (state.domain or "").removeprefix("www.")
    for qid, query in queries[:budget]:
        results, via = _search(query)
        state.searched.append(query)
        emit("web", f"search ({via}) '{query}' -> {len(results)} results")
        for r in results[:3]:
            if r.get("snippet"):
                _add(state, kind="snippet", url=r["url"], title=r.get("title", ""), text=r["snippet"], via=via,
                     question_ids=[qid])
        ranked = sorted(
            (r for r in results if not any(s in _host(r["url"]) for s in SKIP_HOSTS)),
            key=lambda r: 0 if company_host and company_host in _host(r["url"]) else 1,
        )
        for r in ranked[:2]:
            if r["url"] not in state.fetched and r["url"] not in {u for u, _ in candidates}:
                candidates.append((r["url"], qid))

    fetch_budget = max(0, settings.max_fetches - len(state.fetched))
    to_fetch = candidates[:fetch_budget]
    for i in range(0, len(to_fetch), 10):
        batch = to_fetch[i : i + 10]
        qid_by_url = dict(batch)
        for page in _fetch([u for u, _ in batch]):
            url = page.get("url", "")
            state.fetched.append(url)
            content = (page.get("content") or "").strip()
            if not content:
                continue
            _add(state, kind="page", url=url, title=page.get("title", ""), text=content[: settings.page_chars],
                 via=page.get("via", "crustdata-web"), question_ids=[qid_by_url.get(url, "")])

    new = state.evidence[before:]
    emit("web", f"round {state.round}: +{len(new)} evidence ({sum(e.kind == 'page' for e in new)} pages)")
    return new
