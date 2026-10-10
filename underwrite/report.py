"""Render a company's memo as a paper dossier, styled after a 1970s VC evaluation form.

Page 1  evaluation form: typed labels, hand-written answers, red source numbers, a VERIFIED stamp
Page 2  typed memorandum: the full analysis, every sentence carrying its sources
Page 3  appendix: sources, which claims each one supports, rejected claims, the agent's run log

Everything shown comes from verified claims. LLM output and web text are treated as untrusted:
all of it is HTML-escaped, and no model-written link or markup is ever rendered.
"""

from __future__ import annotations

import datetime as dt
import html
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlparse

from .models import Claim, CompanyState

CITE = re.compile(r"\[(C\d+)\]")
FONTS = ("https://fonts.googleapis.com/css2?family=Caveat:wght@500;700&family=Courier+Prime:ital,wght@0,400;0,700;1,400"
         "&family=Special+Elite&display=swap")
HTML_TO_IMAGE = "https://cdn.jsdelivr.net/npm/html-to-image@1.11.11/dist/html-to-image.js"

CSS = r"""
:root{--desk:#d9d4c7;--paper:#fbf7ec;--ink:#1f2b6e;--red:#b8322a;--type:#262421;--rule:#6b6760;--faint:#cfc8b6}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--desk:#24221f}}
*{box-sizing:border-box}
html,body{margin:0;background:var(--desk);color:var(--type)}
body{font:15px/1.5 "Courier Prime","Courier New",monospace;padding:72px 16px 48px}
.toolbar{position:fixed;top:0;left:0;right:0;z-index:5;display:flex;gap:8px;align-items:center;justify-content:center;
  flex-wrap:wrap;padding:10px 16px;background:rgba(30,28,25,.88);backdrop-filter:blur(6px);font:13px system-ui,sans-serif;color:#eee}
.toolbar b{margin-right:auto;letter-spacing:.08em}
.toolbar a,.toolbar button{font:inherit;color:#1e1c19;background:#f3eddc;border:0;border-radius:6px;padding:7px 12px;cursor:pointer;text-decoration:none}
.toolbar a:hover,.toolbar button:hover{background:#fff}
.sheet{position:relative;width:min(816px,100%);min-height:1056px;margin:0 auto 36px;padding:56px 60px 64px;
  background-color:var(--paper);
  background-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='220' height='220'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='.85' numOctaves='3' stitchTiles='stitch'/><feColorMatrix values='0 0 0 0 .45  0 0 0 0 .38  0 0 0 0 .25  0 0 0 .07 0'/></filter><rect width='100%' height='100%' filter='url(%23n)'/></svg>"),
    radial-gradient(ellipse at 18% 8%,rgba(255,255,255,.55),transparent 55%),
    radial-gradient(ellipse at 90% 100%,rgba(160,130,70,.10),transparent 60%);
  box-shadow:0 1px 2px rgba(0,0,0,.15),0 12px 28px rgba(0,0,0,.18)}
.sheet:nth-of-type(odd){transform:rotate(-.25deg)} .sheet:nth-of-type(even){transform:rotate(.3deg)}
.hand{font-family:Caveat,"Segoe Print","Bradley Hand",cursive;color:var(--ink);font-weight:500;font-size:23px;line-height:1.15;
  text-transform:uppercase;letter-spacing:.02em}
.red{color:var(--red)}
.typed{font-family:"Special Elite","Courier Prime",monospace}
.title{text-align:center;font-size:15px;letter-spacing:.06em;margin:0 0 30px;text-decoration:underline;text-underline-offset:4px}
.cc{position:absolute;top:26px;right:48px;transform:rotate(-8deg);font-size:21px;text-align:center;line-height:1}
.row{display:flex;align-items:flex-end;gap:10px;margin:0 0 13px;flex-wrap:wrap}
.lbl{font-family:"Special Elite",monospace;font-size:14px;white-space:nowrap}
.line{flex:1 1 180px;min-width:140px;border-bottom:1px solid var(--rule);padding:0 6px 1px;min-height:30px}
.line.short{flex:0 1 150px;min-width:110px}
.sec{margin-top:20px;border-top:3px double var(--rule)}
.sec>.lbl{display:inline-block;margin-top:3px;text-decoration:underline;text-underline-offset:3px}
.ruled{padding:4px 8px 0 28px;min-height:62px;background-position:0 4px;
  background-image:repeating-linear-gradient(to bottom,transparent 0,transparent 29px,var(--faint) 29px,var(--faint) 30px);
  line-height:30px}
.ruled .hand{line-height:30px}
table.ops{border-collapse:collapse;margin:8px 0 0 28px;width:calc(100% - 28px)}
.ops td{padding:2px 6px 2px 0;vertical-align:bottom}
.ops td:first-child{font-family:"Special Elite",monospace;font-size:14px;width:36%;padding-left:20px}
.ops td:last-child{border-bottom:1px solid var(--rule)}
a.cite{display:inline-block;min-width:19px;height:19px;padding:0 4px;margin:0 1px;border:1.6px solid var(--red);border-radius:50%;
  font:700 12px/16px Caveat,cursive;color:var(--red);text-align:center;text-decoration:none;vertical-align:super;transform:rotate(-6deg)}
.stamp-row{text-align:right;margin:14px 8px 0}
.stamp{display:inline-block;transform:rotate(-7deg);border:3px solid var(--red);border-radius:6px;padding:6px 14px;
  color:var(--red);font:700 17px/1.15 "Special Elite",monospace;text-align:center;letter-spacing:.12em;opacity:.78;mix-blend-mode:multiply;
  box-shadow:inset 0 0 0 2px var(--paper),inset 0 0 0 4px var(--red)}
.stamp small{display:block;font-size:11px;letter-spacing:.08em}
.margin-note{border-left:2px solid var(--red);padding:2px 0 2px 10px;margin:6px 0 0 28px;font-size:21px}
.circled{display:inline-block;border:2px solid var(--ink);border-radius:50%;padding:0 12px;transform:rotate(-3deg)}
.footer{position:absolute;left:60px;right:60px;bottom:26px;font-size:11px;color:#77736a;display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap}
.memo h1{font:400 26px "Special Elite",monospace;letter-spacing:.3em;margin:0 0 18px}
.memo .hdr{display:grid;grid-template-columns:90px 1fr;gap:2px 10px;margin-bottom:12px}
.memo .hdr b{font-weight:700}
.memo hr{border:0;border-top:2px solid var(--type);margin:14px 0 18px}
.memo h2{font:700 15px "Courier Prime",monospace;text-transform:uppercase;letter-spacing:.08em;margin:22px 0 6px}
.memo p,.memo li{margin:0 0 9px;text-align:left}
.memo ul{padding-left:22px;margin:0 0 10px}
.sig{margin-top:30px;font-size:30px}
.appendix ol{padding-left:24px}.appendix li{margin-bottom:12px;word-break:break-word}
.appendix .src{font-weight:700;color:var(--ink)}.appendix .via{font-size:12px;color:#6d685e}
.appendix .claims{list-style:none;padding-left:4px;margin:4px 0 0;font-size:13.5px}
.appendix .claims li{margin:2px 0}
.ok{color:#1d6b3a;font-weight:700}.part{color:#9a5b00;font-weight:700}
.strike{text-decoration:line-through;text-decoration-color:var(--red);text-decoration-thickness:2px;color:#5d5a52}
.log{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:6px 18px;margin:8px 0 16px}
.log div{border-bottom:1px dotted var(--rule)}
@media (max-width:640px){body{padding:64px 8px 24px}.sheet{padding:40px 22px 64px;min-height:0}.cc{right:16px;top:12px}
  .footer{left:22px;right:22px}.hand{font-size:21px}.toolbar b{display:none}}
@media print{@page{size:letter;margin:0}
  html,body{background:none;padding:0}.toolbar{display:none}
  .sheet{transform:none!important;box-shadow:none;margin:0;background-image:none;width:8.5in;min-height:11in;page-break-after:always;break-after:page}
  *{-webkit-print-color-adjust:exact;print-color-adjust:exact}}
"""

SCRIPT = r"""
function savePng(){
  const el=document.getElementById('page1'); const btn=document.getElementById('pngbtn'); btn.textContent='Rendering…';
  htmlToImage.toPng(el,{pixelRatio:2,backgroundColor:'#fbf7ec',style:{transform:'none',margin:'0'}}).then(url=>{
    const a=document.createElement('a'); a.href=url; a.download=document.body.dataset.slug+'-evaluation-form.png'; a.click();
    btn.textContent='Download page 1 (PNG)';
  }).catch(()=>{btn.textContent='PNG failed: use PDF'});
}
"""


def esc(s: object) -> str:
    return html.escape(str(s), quote=True)


def _safe_url(url: str | None) -> str | None:
    if not url:
        return None
    p = urlparse(url)
    return url if p.scheme in ("http", "https") and p.netloc else None


class Citations:
    """Numbers sources in order of first use, and renders red circled citation marks."""

    def __init__(self, state: CompanyState):
        self.claims = {c.id: c for c in state.claims}
        self.evidence = {e.id: e for e in state.evidence}
        self.usable = {c.id for c in state.claims if c.support in ("supported", "partial")}
        self.order: dict[str, int] = {}

    def number(self, evidence_id: str) -> int:
        if evidence_id not in self.order:
            self.order[evidence_id] = len(self.order) + 1
        return self.order[evidence_id]

    def mark(self, claim_ids: list[str]) -> str:
        out, seen = [], set()
        for cid in claim_ids:
            c = self.claims.get(cid)
            if not c or cid not in self.usable:
                continue
            n = self.number(c.evidence_id)
            if n in seen:
                continue
            seen.add(n)
            tip = esc(f"{c.statement}  —  “{c.quote}”")
            out.append(f'<a class="cite" href="#src{n}" title="{tip}">{n}</a>')
        return "".join(out)

    def for_field(self, field: str, value: object) -> str:
        """Cite the verified claim that backs a fact-sheet value."""
        cands = [c for c in self.claims.values() if c.field == field and c.id in self.usable]
        if not cands:
            return ""
        want = set(re.findall(r"[a-z0-9]+", str(value).lower()))

        def overlap(c: Claim) -> int:
            return len(want & set(re.findall(r"[a-z0-9]+", f"{c.value} {c.statement}".lower())))

        best = max(cands, key=lambda c: (overlap(c), c.support == "supported"))
        return self.mark([best.id])


def _sections(markdown: str) -> dict[str, str]:
    out: dict[str, str] = {}
    current = "summary"
    for line in markdown.splitlines():
        m = re.match(r"^#{1,3}\s+(.*)", line)
        if m:
            current = m.group(1).strip().lower()
            out.setdefault(current, "")
        else:
            out[current] = (out.get(current, "") + "\n" + line).strip()
    return out


def _find(secs: dict[str, str], *keys: str) -> str:
    for k, v in secs.items():
        if any(key in k for key in keys):
            return v
    return ""


def _sentences(text: str, limit: int) -> tuple[str, list[str]]:
    """First sentences of a section up to ~limit chars (never cut mid-sentence), plus their citations."""
    text = re.sub(r"^\s*[-*]\s+", "", text, flags=re.M).replace("**", "")
    parts = re.split(r"(?<=[.!?])\s+", " ".join(text.split()))
    picked: list[str] = []
    for s in parts:
        if picked and len(" ".join(picked)) + len(s) > limit:
            break
        picked.append(s)
    chosen = " ".join(picked)
    return re.sub(r"\s*\[C\d+\]", "", chosen).strip(), CITE.findall(chosen)


def _render_md(markdown: str, cites: Citations) -> str:
    """Tiny, safe markdown: headings, bullets, paragraphs, bold. Everything else is escaped text."""
    out, para, items = [], [], []

    def inline(s: str) -> str:
        s = esc(s)
        s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
        s = re.sub(r"\s*((?:\[C\d+\])+)([.,;:]?)", lambda m: m.group(2) + cites.mark(CITE.findall(m.group(1))), s)
        return s

    def flush() -> None:
        if para:
            out.append(f"<p>{inline(' '.join(para))}</p>")
            para.clear()
        if items:
            out.append("<ul>" + "".join(f"<li>{inline(i)}</li>" for i in items) + "</ul>")
            items.clear()

    for line in markdown.splitlines():
        s = line.strip()
        if m := re.match(r"^#{1,4}\s+(.*)", s):
            flush()
            out.append(f"<h2>{esc(m.group(1))}</h2>")
        elif m := re.match(r"^[-*]\s+(.*)", s):
            if para:
                flush()
            items.append(m.group(1))
        elif not s:
            flush()
        else:
            if items:
                flush()
            para.append(s)
    flush()
    return "\n".join(out)


def _action(recommendation: str) -> str:
    r = recommendation.lower()
    if r.startswith("pass") or " pass " in r[:30]:
        return "Pass"
    if "strong" in r[:40] or "pursue" in r[:40] or "invest" in r[:30]:
        return "Pursue"
    return "Dig deeper"


def _fmt(v: object) -> str:
    if v is None:
        return ""
    if isinstance(v, list):
        return ", ".join(map(str, v))
    return str(v)


def write_report(state: CompanyState, out_dir: Path) -> Path:
    memo = state.memo
    cites = Citations(state)
    facts = dict(memo.fact_sheet) if memo else {}
    secs = _sections(memo.memo_markdown) if memo else {}
    m, u = state.metrics or {}, state.usage or {}
    when = dt.datetime.fromtimestamp(state.finished_at or state.started_at or 0)
    slug = re.sub(r"[^a-z0-9]+", "-", state.company.lower()).strip("-")

    def fact(key: str) -> str:
        v = facts.get(key)
        return (esc(_fmt(v)) + cites.for_field(key, v)) if v not in (None, "", []) else ""

    def hand_block(keys: tuple[str, ...], limit: int, fallback: str = "") -> str:
        text, ids = _sentences(_find(secs, *keys), limit)
        if not text:
            return f'<span class="hand">{esc(fallback)}</span>' if fallback else ""
        return f'<span class="hand">{esc(text)}</span>{cites.mark(ids)}'

    hq = ", ".join(x for x in (_fmt(facts.get("hq_city")), _fmt(facts.get("hq_country"))) if x)
    hq_cite = cites.for_field("hq_city", facts.get("hq_city")) if hq else ""
    founders = facts.get("founders")
    mgmt = []
    if facts.get("ceo"):
        mgmt.append(f'<span class="hand">{esc(_fmt(facts["ceo"]))} — CEO</span>{cites.for_field("ceo", facts["ceo"])}')
    if founders:
        mgmt.append(f'<span class="hand">Founders: {esc(_fmt(founders))}</span>{cites.for_field("founders", founders)}')
    if facts.get("headcount"):
        mgmt.append(f'<span class="hand">Team size: {esc(_fmt(facts["headcount"]))}</span>'
                    f'{cites.for_field("headcount", facts["headcount"])}')

    conflicts = "".join(f'<div class="margin-note hand red">⚠ sources disagree — {esc(c.note)}</div>'
                        for c in state.conflicts)
    total = m.get("claims", 0)
    verified = sum(c.support in ("supported", "partial") for c in state.claims)
    rec = memo.recommendation if memo else "No memo produced"

    ops_rows = [
        ("Employees", "headcount"), ("Funding raised", "total_funding_usd"),
        ("Last round", "last_round"), ("Founded", "founded_year"),
    ]
    ops = "".join(f'<tr><td>{label}</td><td><span class="hand">{fact(key) or "—"}</span></td></tr>'
                  for label, key in ops_rows)

    page1 = f"""
<article class="sheet form" id="page1">
  <div class="cc hand red">cc: IC<br>{when.month}/{when.day}/{when:%y}</div>
  <h1 class="title typed">UNDERWRITE EVALUATION FORM</h1>
  <div class="row"><span class="lbl">Company</span><span class="line hand" style="font-size:28px">{esc(state.company)}</span>
    <span class="lbl">Date Rec'd</span><span class="line short hand">{when.month}/{when.day}/{when:%y}</span></div>
  <div class="row"><span class="lbl">Address</span><span class="line hand">{esc(hq) or '—'}{hq_cite}</span>
    <span class="lbl">Website</span><span class="line short hand" style="text-transform:none">{esc(state.domain or '—')}</span></div>
  <div class="row"><span class="lbl">Introduced By</span><span class="line hand">Underwrite agent</span>
    <span class="lbl">Founded</span><span class="line short hand">{fact('founded_year') or '—'}</span></div>
  <div class="sec"><span class="lbl">BUSINESS:</span><div class="ruled">{hand_block(("product", "business"), 230, _fmt(facts.get("business_model")))}</div></div>
  <div class="sec"><span class="lbl">FINANCING TO DATE:</span><div class="ruled"><span class="hand">{fact('total_funding_usd') or 'not verified'}</span>
    {f'<span class="hand"> · last round: {fact("last_round")}</span>' if facts.get("last_round") else ''}</div></div>
  <div class="sec"><span class="lbl">MARKET:</span><div class="ruled">{hand_block(("market", "competition"), 200, "not verified")}</div></div>
  <div class="sec"><span class="lbl">OPERATING STATISTICS:</span> <span class="lbl">(as of {when.month}/{when:%y})</span>
    <table class="ops">{ops}</table></div>
  <div class="sec"><span class="lbl">MANAGEMENT:</span><div class="ruled">{'<br>'.join(mgmt) or '<span class="hand">not verified</span>'}</div></div>
  <div class="sec"><span class="lbl">COMMENTS:</span><div class="ruled">{hand_block(("summary",), 300)}</div>{conflicts}</div>
  <div class="sec"><span class="lbl">RISKS:</span><div class="ruled">{hand_block(("risk", "red flag"), 220, "none verified")}</div></div>
  <div class="sec"></div>
  <div class="row"><span class="lbl">RECOMMENDATION</span><span class="line hand" style="font-size:20px">{esc(rec)}</span></div>
  <div class="row"><span class="lbl">ACTION TAKEN</span><span class="line hand"><span class="circled">{_action(rec)}</span></span>
    <span class="lbl">CONFIDENCE</span><span class="line short hand">{esc(memo.confidence if memo else '—')}</span></div>
  <div class="stamp-row"><div class="stamp">VERIFIED<small>{verified} OF {total} CLAIMS · {m.get('conflicts', 0)} CONFLICTS</small></div></div>
  <div class="footer typed"><span>FORM UW-1 · prompts {esc(state.prompts_version)}</span><span>run {esc(state.run_id)}</span></div>
</article>"""

    body = _render_md(memo.memo_markdown, cites) if memo else "<p>No memo was produced.</p>"
    page2 = f"""
<article class="sheet memo" id="page2">
  <h1>MEMORANDUM</h1>
  <div class="hdr"><b>TO:</b><span>Investment Committee</span><b>FROM:</b><span>Underwrite (autonomous diligence agent)</span>
    <b>DATE:</b><span>{when:%B} {when.day}, {when:%Y}</span><b>RE:</b><span>{esc(state.company)} ({esc(state.domain or 'n/a')}) — first-pass diligence</span></div>
  <hr>
  <p><b>Recommendation:</b> {esc(rec)} <i>(confidence: {esc(memo.confidence if memo else 'n/a')})</i></p>
  {body}
  <div class="sig hand">— Underwrite</div>
  <div class="footer typed"><span>Every factual sentence cites a source that passed verification (red circles → Appendix A)</span><span>page 2</span></div>
</article>"""

    src_items = []
    for eid, n in sorted(cites.order.items(), key=lambda x: x[1]):
        e = cites.evidence[eid]
        url = _safe_url(e.url)
        label = esc(e.title or e.url or "source")
        head = (f'<a class="src" href="{esc(url)}" rel="noopener noreferrer" target="_blank">{label}</a>' if url
                else f'<span class="src">{label}</span>')
        via = "Crustdata company database" if e.kind == "crustdata" else esc(urlparse(e.url or '').netloc)
        backed = [c for c in state.claims if c.evidence_id == eid and c.support in ("supported", "partial")]
        lines = "".join(
            f'<li><span class="{"ok" if c.support == "supported" else "part"}">{"✓" if c.support == "supported" else "~"}</span> '
            f'{esc(c.statement)}</li>' for c in backed[:8])
        src_items.append(f'<li id="src{n}">{head} <span class="via">· {via} · fetched via {esc(e.via)}</span>'
                         f'<ul class="claims">{lines}</ul></li>')

    rejected = [c for c in state.claims if c.support == "unsupported"]
    rej = "".join(f'<li><span class="strike">{esc(c.statement)}</span> <span class="hand red" style="font-size:18px">— {esc(c.reason[:120])}</span></li>'
                  for c in rejected[:15]) or "<li>None — every extracted claim passed.</li>"
    log = [
        ("Claims extracted", total), ("Verified", f"{verified} ({m.get('supported_rate', 0):.0%} fully)"),
        ("Rejected", len(rejected)), ("Conflicts flagged", m.get("conflicts", 0)),
        ("Research rounds", m.get("rounds", 1)), ("Recoveries", m.get("recoveries", 0)),
        ("Run time", f"{m.get('duration_s', 0):.0f}s"), ("Crustdata credits", f"{u.get('crust_credits', 0):g}"),
        ("LLM cost (list price)", f"${u.get('llm_usd', 0):.3f}"),
    ]
    page3 = f"""
<article class="sheet memo appendix" id="page3">
  <h1 style="font-size:18px;letter-spacing:.12em">APPENDIX A — SOURCES &amp; VERIFICATION</h1>
  <p>✓ quote found in the source and judged supporting by an independent checker · ~ partially supported</p>
  <ol>{''.join(src_items) or '<li>No sources cited.</li>'}</ol>
  <h2>Rejected claims (kept out of the memo)</h2><ul>{rej}</ul>
  <h2>Agent run log</h2><div class="log">{''.join(f'<div>{k}: <b>{esc(v)}</b></div>' for k, v in log)}</div>
  <p class="via">neatlogs trace: {esc(', '.join(state.trace_ids) or 'not exported')}</p>
  <div class="footer typed"><span>Generated by Underwrite · {when:%Y-%m-%d %H:%M}</span><span>page 3</span></div>
</article>"""

    pdf_name = "memo.pdf"
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(state.company)} · Underwrite memo</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="{FONTS}"><style>{CSS}</style>
<script src="{HTML_TO_IMAGE}" defer></script><script>{SCRIPT}</script></head>
<body data-slug="{esc(slug)}">
<div class="toolbar"><b>UNDERWRITE · {esc(state.company)}</b>
  <a href="{pdf_name}" download id="pdfbtn">Download PDF</a>
  <button id="pngbtn" onclick="savePng()">Download page 1 (PNG)</button>
  <button onclick="window.print()">Print</button></div>
{page1}{page2}{page3}
</body></html>"""
    path = out_dir / "memo.html"
    path.write_text(page, encoding="utf-8")
    (out_dir / "memo.md").write_text(
        f"# {state.company}\n\n**{rec}** (confidence: {memo.confidence if memo else 'n/a'})\n\n"
        + (memo.memo_markdown if memo else "") + "\n", encoding="utf-8")
    if export_pdf(path) is None:  # no headless browser here: let the reader's browser make the PDF
        path.write_text(page.replace(f'<a href="{pdf_name}" download id="pdfbtn">Download PDF</a>',
                                     '<button id="pdfbtn" onclick="window.print()">Save as PDF</button>'), encoding="utf-8")
    return path


def _browser() -> str | None:
    for name in ("msedge", "chrome", "google-chrome", "chromium", "chromium-browser"):
        if p := shutil.which(name):
            return p
    for p in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Google\Chrome\Application\chrome.exe"):
        if Path(p).exists():
            return p
    return None


def export_pdf(html_path: Path) -> Path | None:
    """Best effort: print the dossier to memo.pdf with a headless Edge/Chrome. Skipped if none is installed."""
    browser = _browser()
    if not browser:
        return None
    pdf = html_path.with_name("memo.pdf")
    try:
        subprocess.run(
            [browser, "--headless", "--disable-gpu", "--no-pdf-header-footer", "--virtual-time-budget=8000",
             f"--print-to-pdf={pdf}", html_path.resolve().as_uri()],
            timeout=90, capture_output=True, check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    return pdf if pdf.exists() else None
