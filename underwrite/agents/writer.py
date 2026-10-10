"""Writer: verified claims -> cited memo + fact sheet. Citations to anything unverified are stripped."""

from __future__ import annotations

import re

import neatlogs

from .. import llm
from ..models import FACT_FIELDS, CompanyState, MemoOut
from ..obs import emit

CITE = re.compile(r"\[(C\d+)\]")


def gaps(state: CompanyState) -> list:
    answered = {c.question_id for c in state.claims if c.support in ("supported", "partial")}
    return [q for q in state.plan.questions if q.id not in answered]


@neatlogs.span(kind="AGENT", name="writer", role="analyst", goal="write a memo using only verified claims")
def write(state: CompanyState) -> MemoOut:
    usable = [c for c in state.claims if c.support in ("supported", "partial")]
    src = {e.id: e for e in state.evidence}
    claims_text = "\n".join(
        f"{c.id} | {c.support} | {c.statement} | "
        f"{'Crustdata' if src[c.evidence_id].kind == 'crustdata' else src[c.evidence_id].url}"
        for c in usable
    )
    conflicts_text = "\n".join(f"- {x.note} (claims {', '.join(x.claims)})" for x in state.conflicts) or "(none)"
    gaps_text = "\n".join(f"- {q.question}" for q in gaps(state)) or "(none)"

    memo = llm.run_prompt(
        "writer",
        {
            "company": state.company,
            "domain": state.domain or "unknown domain",
            "claims": claims_text or "(no verified claims)",
            "conflicts": conflicts_text,
            "gaps": gaps_text,
            "fields": ", ".join(FACT_FIELDS),
        },
        MemoOut,
        role="smart",
        effort="medium",
        version=state.prompts_version,
    )

    valid = {c.id for c in usable}
    cited = CITE.findall(memo.memo_markdown)
    invalid = sorted({c for c in cited if c not in valid}, key=lambda x: int(x[1:]))
    if invalid:
        memo.memo_markdown = CITE.sub(lambda m: m.group(0) if m.group(1) in valid else "", memo.memo_markdown)
        emit("verify", f"stripped {len(invalid)} citations to unverified claims: {', '.join(invalid[:8])}")
    state.invalid_citations = invalid
    emit("memo", f"memo written: {len(set(cited) & valid)} distinct verified claims cited, "
                 f"recommendation: {memo.recommendation[:90]}")
    return memo
