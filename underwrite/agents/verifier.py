"""Verifier: three independent checks before a claim may appear in a memo.

1. Grounding (deterministic): the quoted text must actually occur in the cited source.
2. Support (separate LLM judge): the source text around the quote must support the claim.
3. Consistency (deterministic): verified values for the same fact must agree across sources.
"""

from __future__ import annotations

import re

import neatlogs
from rapidfuzz import fuzz

from .. import llm
from ..models import Claim, CompanyState, Conflict, Judgements
from ..obs import emit

QUOTE_MIN_SCORE = 90.0
CONTEXT_CHARS = 400
JUDGE_BATCH = 25


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


@neatlogs.span(kind="GUARDRAIL", name="quote_grounding")
def check_grounding(state: CompanyState, claims: list[Claim]) -> dict[str, str]:
    """Mark claims whose quote is (fuzzily) present in the cited evidence. Returns claim_id -> context."""
    by_id = {e.id: e for e in state.evidence}
    contexts: dict[str, str] = {}
    for c in claims:
        ev = by_id.get(c.evidence_id)
        quote = _norm(c.quote)
        if ev is None or len(quote) < 4:
            c.quote_found, c.quote_score = False, 0.0
            continue
        text = _norm(ev.text)
        idx = text.lower().find(quote.lower())
        if idx != -1:
            score, start, end = 100.0, idx, idx + len(quote)
        else:
            al = fuzz.partial_ratio_alignment(quote.lower(), text.lower())
            score, start, end = al.score, al.dest_start, al.dest_end
        c.quote_score = round(score, 1)
        c.quote_found = score >= QUOTE_MIN_SCORE
        if c.quote_found:
            contexts[c.id] = text[max(0, start - CONTEXT_CHARS) : end + CONTEXT_CHARS]
    grounded = sum(c.quote_found for c in claims)
    emit("verify", f"grounding: {grounded}/{len(claims)} quotes found in their cited source")
    return contexts


def _judge(state: CompanyState, claims: list[Claim], contexts: dict[str, str]) -> None:
    for i in range(0, len(claims), JUDGE_BATCH):
        batch = claims[i : i + JUDGE_BATCH]
        items = "\n\n".join(
            f"{c.id}\nclaim: {c.statement}\nquote: {c.quote}\nsource [{c.evidence_id}] text: ...{contexts[c.id]}..."
            for c in batch
        )
        out = llm.run_prompt("verifier", {"company": state.company, "items": items}, Judgements,
                             role="fast", effort="low", version=state.prompts_version)
        verdicts = {j.claim_id: j for j in out.judgements}
        for c in batch:
            j = verdicts.get(c.id)
            if j:
                c.support, c.reason = j.support, j.reason[:300]


# ---- consistency ------------------------------------------------------------------

_MULT = {"k": 1e3, "thousand": 1e3, "m": 1e6, "mn": 1e6, "million": 1e6, "b": 1e9, "bn": 1e9, "billion": 1e9}


def _number(v: str) -> float | None:
    m = re.search(r"(\d[\d,]*\.?\d*)\s*(k|thousand|mn|m|million|bn|b|billion)?\b", v.lower().replace("$", ""))
    if not m:
        return None
    n = float(m.group(1).replace(",", ""))
    return n * _MULT.get(m.group(2) or "", 1)


def _same(field: str, a: str, b: str) -> bool:
    if field == "founded_year":
        ya, yb = re.search(r"(19|20)\d\d", a), re.search(r"(19|20)\d\d", b)
        return not (ya and yb) or ya.group() == yb.group()
    if field in ("headcount", "total_funding_usd"):
        na, nb = _number(a), _number(b)
        if not na or not nb:
            return True
        tolerance = 0.30 if field == "headcount" else 0.25
        return abs(na - nb) / max(na, nb) <= tolerance
    if field in ("hq_city", "ceo"):
        na, nb = _norm(a).lower(), _norm(b).lower()
        return na in nb or nb in na or (field == "ceo" and na.split()[-1:] == nb.split()[-1:])
    return True


def find_conflicts(state: CompanyState) -> list[Conflict]:
    """Cluster verified values per fact; more than one cluster is a conflict. Only new ones are announced."""
    src = {e.id: e for e in state.evidence}
    known = {(x.field, tuple(sorted(x.values))) for x in state.conflicts}
    conflicts: list[Conflict] = []
    usable = [c for c in state.claims if c.support in ("supported", "partial") and c.field and c.value]
    for field in ("founded_year", "headcount", "total_funding_usd", "hq_city", "ceo"):
        clusters: list[list[Claim]] = []
        for c in (c for c in usable if c.field == field):
            home = next((cl for cl in clusters if _same(field, cl[0].value, c.value)), None)
            if home is None:
                clusters.append([c])
            else:
                home.append(c)
        if len(clusters) < 2:
            continue
        values = [cl[0].value for cl in clusters]
        note = f"{field}: " + " vs ".join(
            f"'{cl[0].value}' ({', '.join(sorted({src[c.evidence_id].via for c in cl}))})" for cl in clusters
        )
        conflict = Conflict(field=field, claims=[c.id for cl in clusters for c in cl], values=values, note=note)
        conflicts.append(conflict)
        if (field, tuple(sorted(values))) not in known:
            emit("conflict", note, field=field)
    return conflicts


@neatlogs.span(kind="AGENT", name="verifier", role="independent fact-checker", goal="reject claims the sources don't support")
def verify(state: CompanyState, claims: list[Claim]) -> None:
    contexts = check_grounding(state, claims)
    for c in claims:
        if not c.quote_found:
            c.support, c.reason = "unsupported", f"quote not found in cited source (match {c.quote_score:.0f}%)"
    to_judge = [c for c in claims if c.quote_found]
    if to_judge:
        _judge(state, to_judge, contexts)
    s = sum(c.support == "supported" for c in claims)
    p = sum(c.support == "partial" for c in claims)
    emit("verify", f"judge: {s} supported, {p} partial, {len(claims) - s - p} rejected of {len(claims)}")
    state.conflicts = find_conflicts(state)
