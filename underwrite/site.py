"""Build the static website in docs/ (served by GitHub Pages): memo gallery + eval scoreboard.

Re-run after every batch (the EC2 nightly job does): it picks the latest finished memo per company,
copies each dossier (HTML + PDF) into docs/memos/<slug>/, and rewrites docs/index.html.
"""

from __future__ import annotations

import datetime as dt
import html
import json
import shutil
from pathlib import Path

from . import prompts
from .config import ROOT, settings
from .evals import latest_eval
from .models import CompanyState
from .pipeline import slug

REPO = "https://github.com/hacker-git-code/underwrite-"


def esc(s: object) -> str:
    return html.escape(str(s), quote=True)


def _latest_states() -> list[tuple[CompanyState, Path]]:
    best: dict[str, tuple[CompanyState, Path]] = {}
    for p in settings.runs_dir.glob("*/*/state.json"):
        try:
            st = CompanyState.model_validate_json(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if st.phase != "done" or not (p.parent / "memo.html").exists():
            continue
        key = slug(st.company)
        if key not in best or (st.finished_at or 0) > (best[key][0].finished_at or 0):
            best[key] = (st, p.parent)
    return sorted(best.values(), key=lambda x: -(x[0].finished_at or 0))


def _scoreboard() -> str:
    rows = []
    for v, mode in [(v, m) for v in prompts.versions() for m in ("pipeline", "agent")]:
        path = latest_eval(v, mode)
        if not path:
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        status = ""
        notes = settings.prompts_dir / v / "coach_report.json"
        if notes.exists():
            status = json.loads(notes.read_text(encoding="utf-8")).get("decision", "")
        for split in ("test", "all"):
            s = data["summary"].get(split) or {}
            if not s.get("completed"):
                continue
            rows.append(
                f"<tr><td><b>{esc(mode)} {esc(v)}</b> {f'<span class=tag>{esc(status)}</span>' if status and mode == 'agent' else ''}</td><td>{split}</td>"
                f"<td>{s['completed']}/{s['companies']}</td><td>{s['fact_accuracy']:.0%}</td><td>{s['fact_precision']:.0%}</td>"
                f"<td>{s['supported_rate']:.0%}</td><td>{s['coverage']:.0%}</td><td>{s['unsupported_per_memo']:.1f}</td>"
                f"<td>${s['usd_per_memo']:.3f}</td><td>{s['credits_per_memo']:.0f}</td></tr>")
    if not rows:
        return "<p>No evaluation has been run yet.</p>"
    return ("<div class=scroll><table><tr><th>version</th><th>split</th><th>memos</th><th>fact accuracy</th>"
            "<th>fact precision</th><th>claims supported</th><th>questions answered</th><th>rejected / memo</th>"
            "<th>LLM $ / memo*</th><th>credits / memo</th></tr>" + "".join(rows) + "</table></div>"
            "<p class=small>Fact accuracy/precision: agent's fact sheet vs. hand-checked ground truth (founding year, HQ, "
            "founders, CEO). The Coach only sees failures from the <i>train</i> split; <i>test</i> is held out. "
            "*List-price equivalent; the runs themselves used free tiers.</p>")


CSS = """
:root{--desk:#e4dfd3;--paper:#fbf7ec;--ink:#1f2b6e;--red:#b8322a;--type:#262421;--mut:#6d685e;--line:#cfc8b6}
@media (prefers-color-scheme:dark){:root{--desk:#1f1d1a;--type:#262421}}
*{box-sizing:border-box}body{margin:0;background:var(--desk);color:var(--type);font:16px/1.55 "Courier Prime","Courier New",monospace}
main{max-width:1060px;margin:0 auto;padding:40px 16px 64px}
.sheet{background:var(--paper);box-shadow:0 1px 2px rgba(0,0,0,.15),0 10px 26px rgba(0,0,0,.16);padding:36px 40px;margin:0 0 28px}
h1{font:400 44px/1.1 "Special Elite",monospace;letter-spacing:.14em;margin:0}
h2{font:400 20px "Special Elite",monospace;letter-spacing:.08em;margin:0 0 14px;text-decoration:underline;text-underline-offset:4px}
.hand{font-family:Caveat,cursive;color:var(--ink);font-size:26px;line-height:1.15}
.tagline{margin:10px 0 18px}.small{font-size:13px;color:var(--mut)}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(135px,1fr));gap:10px;margin-top:18px}
.stats div{border-top:3px double #6b6760;padding-top:6px}.stats b{display:block;font:700 30px Caveat,cursive;color:var(--ink)}
.steps{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px;counter-reset:s;padding:0;list-style:none}
.steps li{border:1px dashed #9a958a;padding:10px 12px;counter-increment:s}
.steps li:before{content:counter(s);display:inline-block;width:24px;height:24px;border:1.6px solid var(--red);border-radius:50%;
  color:var(--red);font:700 15px/21px Caveat,cursive;text-align:center;margin-right:6px;transform:rotate(-6deg)}
.scroll{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:14px}
th,td{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;white-space:nowrap}
.tag{font-size:11px;border:1.5px solid var(--red);color:var(--red);padding:0 5px;border-radius:3px;text-transform:uppercase}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:18px}
.card{background:var(--paper);box-shadow:0 1px 2px rgba(0,0,0,.15),0 8px 18px rgba(0,0,0,.14);padding:18px 20px 16px;position:relative;
  background-image:repeating-linear-gradient(to bottom,transparent 0,transparent 27px,#d8d1bf 27px,#d8d1bf 28px);background-position:0 54px}
.card:nth-child(odd){transform:rotate(-.4deg)}.card:nth-child(even){transform:rotate(.35deg)}
.card h3{font:400 22px "Special Elite",monospace;margin:0 0 2px}.card .dom{font-size:13px;color:var(--mut);margin-bottom:10px}
.card .rec{font:500 21px/28px Caveat,cursive;color:var(--ink);min-height:84px;text-transform:uppercase}
.card .stamp{position:absolute;top:14px;right:14px;transform:rotate(-9deg);border:2.5px solid var(--red);color:var(--red);
  font:700 12px "Special Elite",monospace;padding:3px 7px;letter-spacing:.08em;opacity:.8}
.card .links{margin-top:10px;display:flex;gap:12px;font-size:14px;flex-wrap:wrap;align-items:baseline}.card .links a{white-space:nowrap}
a{color:var(--ink)}footer{text-align:center;font-size:13px;color:var(--mut)}
@media (max-width:600px){.sheet{padding:24px 18px}h1{font-size:32px}}
"""


def published_slugs(out: Path | None = None) -> set[str]:
    index = (out or ROOT / "docs") / "memos" / "index.json"
    return set(json.loads(index.read_text(encoding="utf-8"))) if index.exists() else set()


def build(out: Path | None = None) -> Path:
    """Merge this machine's finished memos into the published site (never drops memos made elsewhere)."""
    out = out or ROOT / "docs"
    memos_dir = out / "memos"
    memos_dir.mkdir(parents=True, exist_ok=True)
    (out / ".nojekyll").write_text("", encoding="utf-8")
    index_path = memos_dir / "index.json"
    index: dict[str, dict] = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {}

    for st, folder in _latest_states():
        s = slug(st.company)
        if index.get(s, {}).get("finished_at", 0) >= (st.finished_at or 0):
            continue
        dest = memos_dir / s
        dest.mkdir(exist_ok=True)
        shutil.copy(folder / "memo.html", dest / "index.html")
        has_pdf = (folder / "memo.pdf").exists()
        if has_pdf:
            shutil.copy(folder / "memo.pdf", dest / "memo.pdf")
        m = st.metrics or {}
        index[s] = {
            "company": st.company, "domain": st.domain, "finished_at": st.finished_at or 0,
            "prompts_version": st.prompts_version, "claims": m.get("claims", 0),
            "verified": sum(c.support in ("supported", "partial") for c in st.claims),
            "conflicts": m.get("conflicts", 0), "recoveries": m.get("recoveries", 0),
            "recommendation": st.memo.recommendation if st.memo else "", "has_pdf": has_pdf,
        }
    index_path.write_text(json.dumps(index, indent=2), encoding="utf-8")

    cards = []
    entries = sorted(index.items(), key=lambda kv: -kv[1]["finished_at"])
    totals = {k: sum(e[k] for _, e in entries) for k in ("claims", "verified", "conflicts", "recoveries")}
    totals["memos"] = len(entries)
    for s, e in entries:
        when = dt.datetime.fromtimestamp(e["finished_at"])
        rec = e["recommendation"]
        cards.append(
            f'<article class="card"><div class="stamp">VERIFIED {e["verified"]}/{e["claims"]}</div>'
            f'<h3>{esc(e["company"])}</h3><div class="dom">{esc(e["domain"] or "")} · {when:%Y-%m-%d} · prompts {esc(e["prompts_version"])}</div>'
            f'<div class="rec">{esc(rec[:150])}{"…" if len(rec) > 150 else ""}</div>'
            f'<div class="links"><a href="memos/{esc(s)}/">Open dossier →</a>'
            f'{f"<a href=memos/{esc(s)}/memo.pdf download>PDF</a>" if e["has_pdf"] else ""}'
            f'<span class="small">{e["conflicts"]} conflicts · {e["recoveries"]} recoveries</span></div></article>')

    scoreboard_path = out / "scoreboard.html"
    scoreboard = _scoreboard()
    if scoreboard.startswith("<p>No evaluation") and scoreboard_path.exists():
        scoreboard = scoreboard_path.read_text(encoding="utf-8")  # e.g. on the EC2 runner, which runs no evals
    else:
        scoreboard_path.write_text(scoreboard, encoding="utf-8")

    updated = dt.datetime.now(dt.timezone.utc)
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Underwrite · autonomous due diligence</title>
<meta name="description" content="An autonomous due-diligence agent that researches startups overnight, verifies every claim against its source, and improves itself from its own neatlogs traces.">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Caveat:wght@500;700&family=Courier+Prime:wght@400;700&family=Special+Elite&display=swap">
<style>{CSS}</style></head><body><main>
<section class="sheet">
  <h1>UNDERWRITE</h1>
  <p class="hand tagline">A due-diligence analyst you can leave running overnight.</p>
  <p>Give it a list of startups. It plans the research, pulls company data from Crustdata, reads the web, and writes an
  investment memo where <b>every fact links to the exact sentence it came from</b>. An independent checker throws out
  anything the sources don't support, and disagreements between sources are flagged in red. A Coach agent reads the
  agent's own <a href="https://neatlogs.com">neatlogs</a> traces and rewrites its prompts — and keeps a change only if the eval score improves.</p>
  <div class="stats">
    <div><b>{totals['memos']}</b>memos written</div><div><b>{totals['verified']}</b>claims verified</div>
    <div><b>{totals['claims'] - totals['verified']}</b>claims rejected</div><div><b>{totals['conflicts']}</b>source conflicts flagged</div>
    <div><b>{totals['recoveries']}</b>failures recovered</div><div><b>{updated:%d %b %H:%M}</b>last updated (UTC)</div>
  </div>
</section>
<section class="sheet"><h2>HOW IT WORKS</h2><ol class="steps">
  <li><b>Plan</b> — turns a company into 8–10 diligence questions with search queries.</li>
  <li><b>Research</b> — Crustdata company record + web search + page fetch, within a fixed budget.</li>
  <li><b>Extract</b> — atomic claims, each pinned to one source and a verbatim quote.</li>
  <li><b>Verify</b> — quote must exist in the source; an independent judge checks support; values are cross-checked.</li>
  <li><b>Fill gaps</b> — unanswered questions trigger a second research round.</li>
  <li><b>Write</b> — a cited memo and evaluation form, using verified claims only.</li>
  <li><b>Recover</b> — retries, model + data-source fallbacks, JSON repair, checkpoint/resume after a crash.</li>
  <li><b>Improve</b> — the Coach reads neatlogs traces, detections and triage fixes over MCP, rewrites prompts, re-runs the eval.</li>
</ol></section>
<section class="sheet"><h2>SCOREBOARD</h2>{scoreboard}</section>
<section><h2 style="margin-left:4px">MEMOS</h2><div class="grid">{''.join(cards) or '<p>No memos yet.</p>'}</div></section>
<footer><p>Built for <b>#neatHack</b> with neatlogs · Entire · cfo.ai · Crustdata ·
<a href="{REPO}">source on GitHub</a></p></footer>
</main></body></html>"""
    (out / "index.html").write_text(page, encoding="utf-8")
    return out / "index.html"
