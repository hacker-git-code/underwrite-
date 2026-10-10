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
# Per-endpoint limits as reported by GET /account/endpoints for this account.
_limiters = {
    "/company/enrich": RateLimiter(rate=15, per=60.0),
    "/web/search/live": RateLimiter(rate=10, per=60.0),
    "/web/enrich/live": RateLimiter(rate=10, per=60.0),
}

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
        _limiters[path].acquire()
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


def _usd(v: Any) -> str:
    try:
        return f"{float(v):,.0f} USD"
    except (TypeError, ValueError):
        return str(v)


def _pct(v: Any) -> str:
    try:
        return f"{float(v):+.1f}%"
    except (TypeError, ValueError):
        return "n/a"


def render_company(company: dict) -> str:
    """Render the facts that matter for diligence as 'Label: value' lines, so claims can quote a whole line.
    (The raw record is thousands of lines, mostly executives' past employment, which is noise here.)"""
    b = company.get("basic_info") or {}
    hc = company.get("headcount") or {}
    fu = company.get("funding") or {}
    lo = company.get("locations") or {}
    tx = company.get("taxonomy") or {}
    rv = (company.get("revenue") or {}).get("estimated") or {}
    fo = company.get("followers") or {}
    hi = company.get("hiring") or {}
    pe = company.get("people") or {}
    g = hc.get("growth_percent") or {}

    lines = [
        ("Company name", b.get("name")),
        ("Website", b.get("website")),
        ("Description", b.get("description")),
        ("Company type", b.get("company_type")),
        ("Status", b.get("status")),
        ("Year founded", b.get("year_founded")),
        ("Headquarters", lo.get("headquarters")),
        ("Office addresses", "; ".join(a.strip(", ") for a in (lo.get("all_office_addresses") or [])[:6])),
        ("Industry", tx.get("professional_network_industry")),
        ("Categories", ", ".join((tx.get("categories") or [])[:10])),
        ("Employee count", hc.get("total")),
        ("Employee count range", b.get("employee_count_range")),
        ("Headcount growth", f"6 months {_pct(g.get('six_months'))}, 1 year {_pct(g.get('yoy'))}, "
                             f"2 years {_pct(g.get('two_years'))}" if g else None),
        ("Largest headcount country", hc.get("largest_headcount_country")),
        ("Total funding raised", _usd(fu.get("total_investment_usd")) if fu.get("total_investment_usd") else None),
        ("Number of funding rounds", fu.get("num_funding_rounds")),
        ("Last funding round", " ".join(str(x) for x in (
            fu.get("last_round_type"),
            _usd(fu.get("last_round_amount_usd")) if fu.get("last_round_amount_usd") else "",
            f"on {fu.get('last_fundraise_date')}" if fu.get("last_fundraise_date") else "") if x) or None),
        ("Investors", ", ".join((fu.get("investors") or [])[:25])),
        ("Acquired by", ", ".join(str(x) for x in fu.get("acquired_by") or [])),
        ("Estimated annual revenue", f"{_usd(rv['lower_bound_usd'])} to {_usd(rv['upper_bound_usd'])}"
                                      if rv.get("lower_bound_usd") and rv.get("upper_bound_usd") else None),
        ("Social media followers", f"{fo['count']:,} ({_pct(fo.get('yoy_percent'))} year over year)" if fo.get("count") else None),
        ("Open job postings", hi.get("openings_count")),
    ]
    out = [f"{k}: {v}" for k, v in lines if v not in (None, "", [])]

    for m in sorted(fu.get("milestones") or [], key=lambda m: str(m.get("funding_date") or m.get("date") or "")):
        date = str(m.get("funding_date") or m.get("date") or "")[:10]
        lead = m.get("lead_investors") or ""
        lead = lead if isinstance(lead, str) else ", ".join(map(str, lead))
        out.append(f"Funding round: {m.get('round_type')} on {date}"
                   + (f", {_usd(m['amount_usd'])}" if m.get("amount_usd") else "")
                   + (f", led by {lead}" if lead else ""))

    seen: set[str] = set()
    for label, group in (("Founder", "founders"), ("Executive", "cxos"), ("Decision maker", "decision_makers")):
        for p in (pe.get(group) or [])[:8]:
            bp = p.get("basic_profile") or {}
            name = bp.get("name")
            if name and name not in seen:
                seen.add(name)
                out.append(f"{label}: {name}, {bp.get('headline') or bp.get('current_title') or ''}".rstrip(", "))
    return "\n".join(out)
