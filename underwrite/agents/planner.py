"""Planner: company -> research questions with search queries; Replanner: unanswered questions -> new queries."""

from __future__ import annotations

import datetime as dt

import neatlogs

from .. import llm
from ..models import CompanyState, Plan, Question, Replan
from ..obs import emit


@neatlogs.span(kind="AGENT", name="planner", role="research planner", goal="turn a company into a research plan")
def plan(state: CompanyState) -> Plan:
    p = llm.run_prompt(
        "planner",
        {"company": state.company, "domain": state.domain or "unknown", "today": dt.date.today().isoformat()},
        Plan,
        role="smart",
        effort="low",
        version=state.prompts_version,
    )
    seen: set[str] = set()
    questions: list[Question] = []
    for i, q in enumerate(p.questions[:10], start=1):
        qid = q.id if q.id and q.id not in seen else f"q{i}"
        seen.add(qid)
        questions.append(q.model_copy(update={"id": qid, "queries": [x for x in q.queries if x.strip()][:2]}))
    emit("plan", f"{len(questions)} questions, {sum(len(q.queries) for q in questions)} queries for {state.company}")
    return Plan(questions=questions)


@neatlogs.span(kind="AGENT", name="replanner", role="gap filler", goal="find new queries for unanswered questions")
def replan(state: CompanyState, gaps: list[Question]) -> list[tuple[str, str]]:
    r = llm.run_prompt(
        "replanner",
        {
            "company": state.company,
            "domain": state.domain or "unknown",
            "gaps": "\n".join(f"- {q.id}: {q.question}" for q in gaps),
            "tried": "\n".join(f"- {s}" for s in state.searched) or "(none)",
        },
        Replan,
        role="fast",
        effort="low",
        version=state.prompts_version,
    )
    valid = {q.id for q in gaps}
    tried = {s.lower() for s in state.searched}
    out = []
    for item in r.queries:
        qid, query = str(item.get("question_id", "")), str(item.get("query", "")).strip()
        if qid in valid and query and query.lower() not in tried:
            out.append((qid, query))
    emit("plan", f"round {state.round}: {len(out)} new queries for {len(gaps)} unanswered questions")
    return out
