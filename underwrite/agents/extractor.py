"""Extractor: evidence -> atomic claims, each pinned to one evidence block and a quote from it."""

from __future__ import annotations

import neatlogs

from .. import llm
from ..models import FACT_FIELDS, Claim, CompanyState, Evidence, Extraction
from ..obs import emit


def _questions_text(state: CompanyState) -> str:
    return "\n".join(f"{q.id} (priority {q.priority}, {q.topic}): {q.question}" for q in state.plan.questions)


def _evidence_text(evidence: list[Evidence]) -> str:
    blocks = []
    for e in evidence:
        src = e.url if e.kind != "crustdata" else "Crustdata company database"
        blocks.append(f"[{e.id}] {e.kind} | {e.title} | {src}\n{e.text}")
    return "\n\n".join(blocks)


@neatlogs.span(kind="AGENT", name="extractor", role="claim extractor", goal="turn evidence into cited atomic claims")
def extract(state: CompanyState, evidence: list[Evidence]) -> list[Claim]:
    if not evidence:
        emit("extract", "no new evidence to extract from")
        return []
    out = llm.run_prompt(
        "extractor",
        {
            "company": state.company,
            "questions": _questions_text(state),
            "evidence": _evidence_text(evidence),
            "fields": ", ".join(FACT_FIELDS),
        },
        Extraction,
        role="fast",
        effort="low",
        max_tokens=16000,
        version=state.prompts_version,
    )
    known = {e.id for e in state.evidence}
    claims: list[Claim] = []
    dropped = 0
    for c in out.claims:
        if c.evidence_id not in known:
            dropped += 1
            continue
        field = c.field if c.field in FACT_FIELDS else None
        claims.append(Claim(id=f"C{len(state.claims) + len(claims) + 1}", round=state.round,
                            **c.model_dump(exclude={"field"}), field=field))
    if dropped:
        emit("extract", f"dropped {dropped} claims citing evidence ids that don't exist")
    state.claims.extend(claims)
    emit("extract", f"{len(claims)} claims from {len(evidence)} evidence blocks")
    return claims
