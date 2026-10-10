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
    fact_sheet: dict[str, str | int | float | list[str] | None] = Field(default_factory=dict)


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


class Objection(BaseModel):
    question_id: str = ""
    issue: str
    action: str = ""


class Review(BaseModel):
    verdict: Literal["ready", "needs_work"]
    objections: list[Objection] = Field(default_factory=list)


class CompanyState(BaseModel):
    run_id: str
    company: str
    domain: str | None = None
    prompts_version: str
    # "agent": analyst tool loop + skeptic review. "pipeline": the original fixed plan->search->extract->verify flow.
    mode: Literal["agent", "pipeline"] = "pipeline"
    # pipeline: new -> planned -> researched -> extracted -> verified -> written -> done
    # agent:    new -> planned -> investigating -> judging -> reviewing -> (investigating ...) -> writing -> written -> done
    phase: str = "new"
    round: int = 1
    question_status: dict[str, dict] = Field(default_factory=dict)  # qid -> {"status": open|answered|unanswerable, "note"}
    agent_messages: list[dict] = Field(default_factory=list)  # the analyst's conversation, checkpointed every step
    agent_steps: int = 0
    round_start_step: int = 0
    tasks_round: int = 1  # last round whose skeptic objections were handed to the analyst
    tool_counts: dict[str, int] = Field(default_factory=dict)
    claim_attempts: int = 0
    rejected_in_loop: int = 0
    self_corrections: int = 0
    reviews: list[Review] = Field(default_factory=list)
    active_s: float = 0.0  # time actually spent working (excludes time the process was not running)
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
