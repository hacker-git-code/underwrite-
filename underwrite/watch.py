"""Watch: notice when a researched company changes, and re-investigate only what changed.

For each company with a finished memo:
1. pull a fresh Crustdata record and diff it with the one the memo was built on
   (headcount moves, new funding, new rounds, executives joining or leaving, acquisition, status);
2. search news published since the memo;
3. if anything material changed, start a new agent run seeded with the previous evidence and verified claims,
   with one new priority-1 question, "what changed since <date>?", which the analyst investigates, the judge and
   skeptic check, and the writer folds into an updated dossier (changes flagged on page 1).
"""

from __future__ import annotations

import datetime as dt
import re
import time

import neatlogs

from . import ledger
from .config import settings
from .models import CompanyState, Question
from .obs import emit
from .pipeline import run_company, company_dir
from .resilience import Fatal, Retryable
from .tools import crustdata

NUMERIC = {"Employee count": 0.03, "Total funding raised": 0.0, "Number of funding rounds": 0.0}
TEXT = ["Last funding round", "Headquarters", "Status", "Acquired by", "Company type"]
PEOPLE = ("Founder", "Executive")


def _fields(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        label, sep, value = line.partition(": ")
        if sep and label not in out:
            out[label] = value.strip()
    return out


def _people(text: str) -> set[str]:
    return {line.split(": ", 1)[1].split(",")[0].strip() for line in text.splitlines()
            if line.split(": ", 1)[0] in PEOPLE and ": " in line}


def _rounds(text: str) -> set[str]:
    return {line for line in text.splitlines() if line.startswith("Funding round:")}


def _num(v: str) -> float | None:
    m = re.search(r"\d[\d,]*\.?\d*", v or "")
    return float(m.group().replace(",", "")) if m else None


def diff_records(old: str, new: str) -> list[str]:
    """Material differences between two rendered Crustdata records, as human-readable lines."""
    a, b = _fields(old), _fields(new)
    changes = []
    for label, tolerance in NUMERIC.items():
        x, y = _num(a.get(label, "")), _num(b.get(label, ""))
        if x is not None and y is not None and x != y and abs(y - x) / max(x, 1) > tolerance:
            changes.append(f"{label}: {a[label]} → {b[label]} ({(y - x) / max(x, 1):+.1%})")
    for label in TEXT:
        if a.get(label, "") != b.get(label, "") and (a.get(label) or b.get(label)):
            changes.append(f"{label}: {a.get(label) or 'none'} → {b.get(label) or 'none'}")
    for r in sorted(_rounds(new) - _rounds(old)):
        changes.append(f"new {r[0].lower()}{r[1:]}")
    joined, left = _people(new) - _people(old), _people(old) - _people(new)
    if joined:
        changes.append(f"new leadership listed: {', '.join(sorted(joined))}")
    if left:
        changes.append(f"no longer listed in leadership: {', '.join(sorted(left))}")
    return changes


def _latest_done() -> list[CompanyState]:
    from .site import _latest_states

    return [st for st, _ in _latest_states() if st.mode == "agent" or st.memo]


@neatlogs.span(kind="AGENT", name="watcher", role="portfolio monitor", goal="detect material changes and re-research them")
def check(state: CompanyState) -> tuple[list[str], list[dict], str]:
    """Returns (record changes, new headlines, fresh record text) for one company."""
    old_ev = next((e for e in state.evidence if e.kind == "crustdata"), None)
    record = crustdata.enrich_company(domain=state.domain, name=None if state.domain else state.company, fresh=True)
    new_text = crustdata.render_company(record) if record else ""
    changes = diff_records(old_ev.text, new_text) if (old_ev and new_text) else []
    seen = {e.url for e in state.evidence}
    first_word = state.company.split()[0].lower()
    try:
        news = crustdata.web_search(f"{state.company} news", sources=("news",), since=state.finished_at, fresh=True)
    except (Fatal, Retryable) as e:
        emit("recover", f"news search failed for {state.company} ({e}); checking the record only")
        news = []
    headlines = [n for n in news if n["url"] not in seen and first_word in (n["title"] + n["snippet"]).lower()][:5]
    return changes, headlines, new_text


def watch(limit: int | None = None) -> list[CompanyState]:
    run_id = f"watch-{time.strftime('%Y%m%d-%H%M%S')}"
    updated: list[CompanyState] = []
    companies = _latest_done()[:limit] if limit else _latest_done()
    emit("watch", f"{run_id}: checking {len(companies)} companies for changes")
    for old in companies:
        since = dt.datetime.fromtimestamp(old.finished_at or 0)
        led = ledger.Ledger()
        tok = ledger.bind(led)
        try:
            changes, headlines, new_text = check(old)
        except (Fatal, Retryable) as e:
            emit("fail", f"{old.company}: watch check failed ({e})")
            continue
        finally:
            ledger.unbind(tok)
        if not changes and not headlines:
            emit("watch", f"{old.company}: no material change since {since:%Y-%m-%d %H:%M}")
            continue
        for c in changes:
            emit("watch", f"{old.company}: CHANGED {c}")
        for h in headlines:
            emit("watch", f"{old.company}: news since last memo: {h['title'][:90]}")

        st = _seed(old, run_id, changes, headlines, new_text)
        st.usage = led.to_dict()  # the refresh + news search credits count toward this run
        path = company_dir(run_id, st.company) / "state.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(st.model_dump_json(indent=2), encoding="utf-8")
        updated.append(run_company(st.company, st.domain, run_id, st.prompts_version, "agent"))
    neatlogs.flush()
    return updated


def _seed(old: CompanyState, run_id: str, changes: list[str], headlines: list[dict], new_text: str) -> CompanyState:
    """A new agent run that starts from the previous evidence and verified claims, with one open question."""
    from .agents import researcher

    since = dt.datetime.fromtimestamp(old.finished_at or 0)
    st = old.model_copy(deep=True)
    st.run_id, st.mode, st.phase, st.round, st.tasks_round = run_id, "agent", "investigating", 1, 1
    st.memo, st.metrics, st.usage, st.trace_ids, st.error = None, {}, {}, [], None
    st.agent_messages, st.agent_steps, st.round_start_step, st.tool_counts = [], 0, 0, {}
    st.claim_attempts = st.rejected_in_loop = st.self_corrections = 0
    st.reviews, st.searched, st.fetched, st.invalid_citations = [], [], [], []
    st.claims = [c for c in st.claims if c.support in ("supported", "partial")]
    st.started_at, st.finished_at, st.active_s = time.time(), None, 0.0
    if new_text:
        researcher._add(st, kind="crustdata", via="crustdata", text=new_text, url="crustdata://company/refreshed",
                        title=f"Crustdata company record (refreshed {dt.date.today():%Y-%m-%d})")
    for h in headlines:
        researcher._add(st, kind="snippet", url=h["url"], title=h["title"], text=h["snippet"], via="crustdata-news")
    qid = f"q{len(st.plan.questions) + 1}"
    detail = "; ".join(changes + [f"headline: {h['title']}" for h in headlines])
    st.plan.questions.insert(0, Question(id=qid, topic="what changed", priority=1,
                                         question=f"What changed since {since:%Y-%m-%d}, and does it change the "
                                                  f"investment view? Signals: {detail[:600]}"))
    st.question_status = {q.id: ({"status": "answered", "note": "carried over from the previous memo"}
                                 if q.id != qid else {"status": "open"}) for q in st.plan.questions}
    st.watch = {"since": old.finished_at, "previous_run": old.run_id, "changes": changes,
                "headlines": [{"title": h["title"], "url": h["url"]} for h in headlines]}
    return st
