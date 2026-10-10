"""Data shapes shared by the agents and persisted in each company's state.json."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

FACT_FIELDS = [
    "founded_year",
    "hq_city",
    "hq_country",
    "founders",
    "ceo",
    "total_funding_usd",
    "last_round",
    "headcount",
    "business_model",
]


# ---- LLM output schemas -------------------------------------------------------------


class Question(BaseModel):
    id: str
    topic: str
    question: str
    queries: list[str] = Field(default_factory=list)
    priority: int = 2  # 1 = must answer, 2 = should, 3 = nice to have


class Plan(BaseModel):
    questions: list[Question]


class Replan(BaseModel):
    queries: list[dict]  # [{"question_id": "...", "query": "..."}]


class ExtractedClaim(BaseModel):
    question_id: str
    field: str | None = None
    statement: str
    value: str | None = None
    evidence_id: str
    quote: str


class Extraction(BaseModel):
    claims: list[ExtractedClaim]


class Judgement(BaseModel):
    claim_id: str
    support: Literal["supported", "partial", "unsupported"]
    reason: str = ""


class Judgements(BaseModel):
    judgements: list[Judgement]


class MemoOut(BaseModel):
    recommendation: str
    confidence: Literal["low", "medium", "high"]
    memo_markdown: str
    fact_sheet: dict[str, str | list[str] | None] = Field(default_factory=dict)


# ---- persisted state ---------------------------------------------------------------


class Evidence(BaseModel):
    id: str
    kind: Literal["crustdata", "page", "snippet"]
    url: str | None = None
    title: str = ""
    text: str
    via: str  # crustdata | crustdata-web | ddg | direct
    question_ids: list[str] = Field(default_factory=list)
    round: int = 1


class Claim(ExtractedClaim):
    id: str
    round: int = 1
    quote_found: bool = False
    quote_score: float = 0.0
    support: Literal["supported", "partial", "unsupported", "unchecked"] = "unchecked"
    reason: str = ""


class Conflict(BaseModel):
    field: str
    claims: list[str]  # claim ids
    values: list[str]
    note: str


class CompanyState(BaseModel):
    run_id: str
    company: str
    domain: str | None = None
    prompts_version: str
    phase: str = "new"  # new -> planned -> researched -> extracted -> verified -> written -> done | failed
    round: int = 1
    plan: Plan | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    searched: list[str] = Field(default_factory=list)
    fetched: list[str] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)
    memo: MemoOut | None = None
    invalid_citations: list[str] = Field(default_factory=list)
    metrics: dict = Field(default_factory=dict)
    usage: dict = Field(default_factory=dict)
    trace_ids: list[str] = Field(default_factory=list)
    error: str | None = None
    started_at: float | None = None
    finished_at: float | None = None
