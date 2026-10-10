"""Orchestrator: a resumable state machine per company.

    new -> planned -> researched -> extracted -> verified --(gaps & rounds left)--> researched ...
                                                         \\--> written -> done

State is saved after every phase, so a crash, a Ctrl-C or a dead laptop battery
costs at most one phase: `underwrite resume <run_id>` picks up where it stopped.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

import neatlogs

from . import ledger, obs
from .agents import extractor, planner, researcher, verifier, writer
from .config import settings
from .models import CompanyState
from .obs import emit


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60] or "company"


def company_dir(run_id: str, company: str) -> Path:
    return settings.runs_dir / run_id / slug(company)


def load_state(path: Path) -> CompanyState | None:
    if path.exists():
        return CompanyState.model_validate_json(path.read_text(encoding="utf-8"))
    return None


def compute_metrics(state: CompanyState, events_path: Path) -> dict:
    claims = state.claims
    n = len(claims) or 1
    supported = sum(c.support == "supported" for c in claims)
    partial = sum(c.support == "partial" for c in claims)
    grounded = sum(c.quote_found for c in claims)
    qs = state.plan.questions if state.plan else []
    answered = {c.question_id for c in claims if c.support in ("supported", "partial")}
    must = [q for q in qs if q.priority == 1]
    kinds: dict[str, int] = {}
    if events_path.exists():
        for line in events_path.read_text(encoding="utf-8").splitlines():
            k = json.loads(line).get("kind")
            kinds[k] = kinds.get(k, 0) + 1
    cited = set(writer.CITE.findall(state.memo.memo_markdown)) if state.memo else set()
    return {
        "claims": len(claims),
        "grounded_rate": round(grounded / n, 3),
        "supported_rate": round(supported / n, 3),
        "usable_rate": round((supported + partial) / n, 3),
        "unsupported": len(claims) - supported - partial,
        "coverage": round(len(answered & {q.id for q in qs}) / (len(qs) or 1), 3),
        "must_coverage": round(len(answered & {q.id for q in must}) / (len(must) or 1), 3),
        "conflicts": len(state.conflicts),
        "memo_citations": len(cited),
        "invalid_citations": len(state.invalid_citations),
        "evidence_pages": sum(e.kind == "page" for e in state.evidence),
        "crustdata_record": any(e.kind == "crustdata" for e in state.evidence),
        "rounds": state.round,
        "recoveries": kinds.get("recover", 0),
        "injected_faults": kinds.get("inject", 0),
        "failures": kinds.get("fail", 0),
        "duration_s": round((state.finished_at or time.time()) - (state.started_at or time.time()), 1),
    }


@neatlogs.span(kind="WORKFLOW", name="underwrite.company", capture_input=False)
def _run(state: CompanyState, path: Path, events_path: Path) -> CompanyState:
    tid = obs.current_trace_id()
    if tid and tid not in state.trace_ids:
        state.trace_ids.append(tid)

    def save() -> None:
        state.usage = ledger.current().to_dict()
        path.write_text(state.model_dump_json(indent=2), encoding="utf-8")

    while state.phase != "done":
        if state.phase == "new":
            state.plan = planner.plan(state)
            state.phase = "planned"
        elif state.phase == "planned":
            # Breadth first: every question's first query (most important questions first), then second queries.
            ordered = sorted(state.plan.questions, key=lambda q: q.priority)
            queries = [(q.id, q.queries[i]) for i in range(2) for q in ordered if len(q.queries) > i]
            researcher.research(state, queries, reserve=settings.reserve_searches)
            state.phase = "researched"
        elif state.phase == "researched":
            extractor.extract(state, [e for e in state.evidence if e.round == state.round])
            state.phase = "extracted"
        elif state.phase == "extracted":
            verifier.verify(state, [c for c in state.claims if c.round == state.round])
            state.phase = "verified"
        elif state.phase == "verified":
            open_qs = [q for q in writer.gaps(state) if q.priority <= 2]
            budget_left = len(state.searched) < settings.max_searches
            if open_qs and state.round < settings.max_rounds and budget_left:
                emit("plan", f"{len(open_qs)} priority questions unanswered -> research round {state.round + 1}")
                state.round += 1
                researcher.research(state, planner.replan(state, open_qs))
                state.phase = "researched"
            else:
                state.memo = writer.write(state)
                state.phase = "written"
        elif state.phase == "written":
            state.finished_at = time.time()
            state.metrics = compute_metrics(state, events_path)
            obs.set_attrs(**{k: v for k, v in state.metrics.items() if not isinstance(v, bool)},
                          prompts_version=state.prompts_version, cost_usd=state.usage.get("llm_usd", 0))
            from .report import write_report

            write_report(state, path.parent)
            state.phase = "done"
        save()
    return state


def run_company(company: str, domain: str | None, run_id: str, version: str | None = None) -> CompanyState:
    """Run (or resume) one company. Never raises for agent failures: they're recorded in the state."""
    out = company_dir(run_id, company)
    out.mkdir(parents=True, exist_ok=True)
    path, events_path = out / "state.json", out / "events.jsonl"
    state = load_state(path) or CompanyState(
        run_id=run_id, company=company, domain=domain, prompts_version=version or settings.prompts_version,
        started_at=time.time(),
    )
    if state.phase == "done":
        emit("info", f"{company}: already done, skipping")
        return state

    led = ledger.Ledger(**{k: v for k, v in (state.usage or {}).items() if k in ledger.Ledger.__dataclass_fields__})
    ltok, etok = ledger.bind(led), obs.bind_run(events_path)
    resumed = state.phase != "new"
    obs.console.rule(f"[bold]{company}[/bold] ({domain or 'no domain'}) · prompts {state.prompts_version}"
                     + (f" · resuming at '{state.phase}'" if resumed else ""))
    try:
        state.error = None
        with neatlogs.identify(session_id=run_id):
            _run(state, path, events_path)
        m = state.metrics
        emit("memo", f"done in {m['duration_s']}s · {m['claims']} claims · {m['supported_rate']:.0%} supported · "
                     f"{m['conflicts']} conflicts · ${state.usage.get('llm_usd', 0):.3f} LLM · "
                     f"{state.usage.get('crust_credits', 0):g} Crustdata credits · {m['recoveries']} recoveries")
    except Exception as e:  # keep the batch going; the saved phase lets `resume` continue later
        state.error = f"{type(e).__name__}: {e}"
        emit("fail", f"{company}: stopped at phase '{state.phase}': {state.error}")
        path.write_text(state.model_dump_json(indent=2), encoding="utf-8")
    finally:
        obs.unbind_run(etok)
        ledger.unbind(ltok)
    return state


def run_batch(companies: list[tuple[str, str | None]], run_id: str, version: str | None = None) -> list[CompanyState]:
    manifest = settings.runs_dir / run_id / "manifest.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps({"run_id": run_id, "version": version or settings.prompts_version,
                                    "companies": companies}, indent=2), encoding="utf-8")
    states: list[CompanyState] = []
    spent = 0.0
    for company, domain in companies:
        if spent >= settings.max_credits_per_run:
            emit("fail", f"credit cap reached ({spent:g} >= {settings.max_credits_per_run:g} Crustdata credits); "
                         f"skipping {company}. Raise UW_MAX_CREDITS_PER_RUN or resume later.")
            states.append(load_state(company_dir(run_id, company) / "state.json") or CompanyState(
                run_id=run_id, company=company, domain=domain, prompts_version=version or settings.prompts_version,
                error="skipped: credit cap"))
            continue
        st = run_company(company, domain, run_id, version)
        spent += float(st.usage.get("crust_credits", 0) or 0)
        states.append(st)
    neatlogs.flush()
    return states


def resume(run_id: str) -> list[CompanyState]:
    manifest = settings.runs_dir / run_id / "manifest.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    return run_batch([tuple(x) for x in data["companies"]], run_id, data.get("version"))
