"""Skeptic: an adversarial reviewer that decides whether the analyst's work is good enough to write up.

It sees only what an investment committee would see (questions, verified claims with their support level, conflicts,
what was rejected) and either signs off or sends the analyst back with specific, budget-feasible objections.
"""

from __future__ import annotations

import neatlogs

from .. import llm
from ..models import CompanyState, Review
from ..obs import emit


def _brief(state: CompanyState) -> dict[str, str]:
    src = {e.id: e for e in state.evidence}
    status = state.question_status
    questions = "\n".join(
        f"- {q.id} (p{q.priority}) [{status.get(q.id, {}).get('status', 'open')}] {q.question}"
        + (f" — note: {status[q.id]['note']}" if q.id in status and status[q.id].get("note") else "")
        for q in state.plan.questions)
    claims = "\n".join(
        f"- {c.id} [{c.question_id}] {c.support}: {c.statement} (source: "
        f"{'Crustdata' if src[c.evidence_id].kind == 'crustdata' else src[c.evidence_id].url})"
        for c in state.claims if c.support in ("supported", "partial"))
    rejected = "\n".join(f"- {c.statement} ({c.reason[:100]})" for c in state.claims if c.support == "unsupported")
    conflicts = "\n".join(f"- {c.note}" for c in state.conflicts)
    return {"company": state.company, "questions": questions, "claims": claims or "(none)",
            "rejected": rejected or "(none)", "conflicts": conflicts or "(none)"}


@neatlogs.span(kind="AGENT", name="skeptic", role="investment committee skeptic", goal="block weak or unsupported memos")
def review(state: CompanyState) -> Review:
    r = llm.run_prompt("skeptic", _brief(state), Review, role="smart", effort="low", version=state.prompts_version)
    r.objections = r.objections[:4]
    if r.verdict == "ready" or not r.objections:
        emit("skeptic", "signed off: the evidence is good enough to write the memo")
        r.verdict = "ready"
    else:
        for o in r.objections:
            emit("skeptic", f"objection [{o.question_id or '-'}]: {o.issue[:110]}")
    state.reviews.append(r)
    return r


def as_tasks(r: Review) -> str:
    lines = "\n".join(f"{i}. [{o.question_id or 'general'}] {o.issue} → {o.action}" for i, o in enumerate(r.objections, 1))
    return ("The investment-committee skeptic reviewed your work and is not satisfied yet. Address these objections "
            "with new evidence (record claims as before), update the questions, then call finish:\n" + lines)
