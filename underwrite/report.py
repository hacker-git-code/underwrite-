"""Render a company's memo as Markdown and as a self-contained HTML page with live citations."""

from __future__ import annotations

import html
import re
from pathlib import Path

import markdown as md

from .models import CompanyState

CSS = """
:root{--bg:#fbfaf7;--fg:#1d1d1b;--mut:#6b6a66;--card:#fff;--line:#e6e3dc;--acc:#2f5bd3;
--ok:#1f7a4a;--warn:#a26200;--bad:#b3261e;--chip:#f1efe9}
@media (prefers-color-scheme:dark){:root{--bg:#141413;--fg:#ecebe6;--mut:#9b9a94;--card:#1d1d1b;
--line:#33322f;--acc:#8fb0ff;--ok:#5cc28c;--warn:#e0a640;--bad:#ff8a80;--chip:#262624}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,sans-serif}
main{max-width:860px;margin:0 auto;padding:32px 16px 80px}
h1{font-size:30px;margin:0 0 4px}h2{font-size:19px;margin:28px 0 8px;border-bottom:1px solid var(--line);padding-bottom:4px}
.sub{color:var(--mut);margin:0 0 20px}.rec{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--acc);
padding:14px 16px;border-radius:8px;margin:16px 0}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:8px;margin:16px 0}
.stat{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px 12px}
.stat b{display:block;font-size:20px}.stat span{color:var(--mut);font-size:12px;text-transform:uppercase;letter-spacing:.04em}
a{color:var(--acc)}sup a{text-decoration:none;font-size:11px;padding:0 2px}
.conf{background:var(--card);border:1px solid var(--warn);border-radius:8px;padding:10px 14px;margin:8px 0}
table{border-collapse:collapse;width:100%;font-size:14px}td,th{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}
.chip{display:inline-block;font-size:11px;padding:1px 7px;border-radius:99px;background:var(--chip);margin-right:4px}
.supported{color:var(--ok)}.partial{color:var(--warn)}.unsupported{color:var(--bad)}
details{margin:8px 0}summary{cursor:pointer;color:var(--mut)}.src{word-break:break-all;font-size:13px}
.q{color:var(--mut);font-style:italic}footer{color:var(--mut);font-size:13px;margin-top:32px}
"""


def _numbering(state: CompanyState) -> dict[str, int]:
    """Number sources in order of first citation in the memo."""
    claims = {c.id: c for c in state.claims}
    order: dict[str, int] = {}
    for cid in re.findall(r"\[(C\d+)\]", state.memo.memo_markdown if state.memo else ""):
        c = claims.get(cid)
        if c and c.evidence_id not in order:
            order[c.evidence_id] = len(order) + 1
    return order


def write_report(state: CompanyState, out_dir: Path) -> Path:
    claims = {c.id: c for c in state.claims}
    ev = {e.id: e for e in state.evidence}
    num = _numbering(state)
    memo = state.memo
    m, u = state.metrics, state.usage

    def cite(match: re.Match) -> str:
        c = claims.get(match.group(1))
        if not c:
            return ""
        n = num.get(c.evidence_id, "?")
        title = html.escape(f"{c.statement} — quote: “{c.quote}”", quote=True)
        return f'<sup><a href="#src{n}" title="{title}" class="{c.support}">[{n}]</a></sup>'

    body_md = memo.memo_markdown if memo else "_No memo was produced._"
    (out_dir / "memo.md").write_text(f"# {state.company}\n\n**{memo.recommendation if memo else ''}**\n\n{body_md}\n",
                                     encoding="utf-8")
    body = md.markdown(body_md, extensions=["tables"])
    body = re.sub(r"\[(C\d+)\]", cite, body)

    sources = []
    for eid, n in sorted(num.items(), key=lambda x: x[1]):
        e = ev[eid]
        used = [c for c in state.claims if c.evidence_id == eid and c.support in ("supported", "partial")]
        link = (f'<a href="{html.escape(e.url)}">{html.escape(e.title or e.url)}</a>' if e.kind != "crustdata"
                else f"{html.escape(e.title)} <span class='chip'>Crustdata API</span>")
        quotes = "".join(f"<li><span class='{c.support}'>{c.support}</span> · {html.escape(c.statement)}"
                         f"<br><span class='q'>“{html.escape(c.quote)}”</span></li>" for c in used[:6])
        sources.append(f"<li id='src{n}' class='src'>{link} <span class='chip'>via {e.via}</span>"
                       f"<details><summary>{len(used)} verified claims from this source</summary><ul>{quotes}</ul></details></li>")

    conflicts = "".join(f"<div class='conf'>⚠ {html.escape(x.note)}</div>" for x in state.conflicts) or "<p>None found.</p>"

    rejected = [c for c in state.claims if c.support == "unsupported"]
    rejected_rows = "".join(
        f"<tr><td>{html.escape(c.statement)}</td><td>{html.escape(c.reason)}</td></tr>" for c in rejected[:40]
    )
    facts = memo.fact_sheet if memo else {}
    fact_rows = "".join(
        f"<tr><th>{html.escape(k.replace('_', ' '))}</th><td>{html.escape(', '.join(v) if isinstance(v, list) else str(v))}</td></tr>"
        for k, v in facts.items() if v not in (None, "", [])
    )

    stats = [
        (m.get("claims", 0), "claims extracted"),
        (f"{m.get('supported_rate', 0):.0%}", "fully supported"),
        (m.get("unsupported", 0), "rejected"),
        (m.get("conflicts", 0), "conflicts"),
        (f"{m.get('coverage', 0):.0%}", "questions answered"),
        (m.get("recoveries", 0), "recoveries"),
        (f"${u.get('llm_usd', 0):.3f}", "LLM cost"),
        (f"{u.get('crust_credits', 0):g}", "Crustdata credits"),
        (f"{m.get('duration_s', 0):.0f}s", "run time"),
    ]
    stats_html = "".join(f"<div class='stat'><b>{v}</b><span>{k}</span></div>" for v, k in stats)
    trace = ", ".join(state.trace_ids) or "not exported"

    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(state.company)} · Underwrite memo</title>
<style>{CSS}</style></head><body><main>
<h1>{html.escape(state.company)}</h1>
<p class="sub">{html.escape(state.domain or '')} · first-pass diligence memo · prompts {state.prompts_version} · confidence {memo.confidence if memo else 'n/a'}</p>
<div class="rec"><b>Recommendation:</b> {html.escape(memo.recommendation if memo else 'n/a')}</div>
<div class="stats">{stats_html}</div>
{body}
<h2>Conflicts between sources</h2>{conflicts}
<h2>Fact sheet</h2><table>{fact_rows}</table>
<h2>Sources</h2><ol>{''.join(sources)}</ol>
<h2>Rejected claims</h2><details><summary>{len(rejected)} claims were extracted but failed verification and were kept out of the memo</summary>
<table><tr><th>Claim</th><th>Why rejected</th></tr>{rejected_rows}</table></details>
<footer>Generated by Underwrite · run {html.escape(state.run_id)} · neatlogs trace {html.escape(trace)}</footer>
</main></body></html>"""
    path = out_dir / "memo.html"
    path.write_text(page, encoding="utf-8")
    return path
