"""Analyst: a tool-using agent that investigates a company until every question is answered or shown unanswerable.

The model chooses every action: which source to pull, what to search, which page to read, what to record. The code
around it enforces what makes it safe to leave alone:
- every claim is checked against its cited source the moment it is recorded, and the agent is told immediately
  when a quote doesn't match, so it has to correct itself;
- search/read/step budgets, shown to the agent after every action;
- `finish` is refused while important questions are still open and budget remains;
- old page text is removed from the conversation (context management) once its facts are recorded;
- the whole conversation is checkpointed after every step, so a crash resumes mid-investigation.
"""

from __future__ import annotations

import json

import neatlogs

from .. import llm, prompts
from ..config import settings
from ..models import FACT_FIELDS, Claim, CompanyState, Question
from ..obs import emit
from ..resilience import Fatal, Retryable
from ..tools import crustdata
from . import researcher
from .verifier import ground

QUOTE_MAX = 300


def _fn(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {"type": "function", "function": {"name": name, "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required}}}


S = {"type": "string"}
TOOLS = [
    _fn("company_profile", "Get the company's structured record from the Crustdata database: founding year, HQ, "
        "headcount and growth, funding rounds and investors, founders and executives. Cheap; call it first.", {}, []),
    _fn("web_search", "Search the web. Returns results as evidence blocks [E#] with title, URL and snippet. "
        "Uses one search from the budget.", {"query": S}, ["query"]),
    _fn("read_page", "Read a web page in full. Returns its text as an evidence block [E#]. Uses one page read "
        "from the budget. Record the page's facts right away: old page text is removed from your context later.",
        {"url": S}, ["url"]),
    _fn("record_claim", "Record one fact, backed by an exact quote copied from one evidence block. The quote is "
        "checked against that block immediately; you are told if it is accepted or rejected.",
        {"question_id": S, "field": {"type": "string", "enum": [*FACT_FIELDS, "none"]}, "statement": S,
         "value": S, "evidence_id": S, "quote": S},
        ["question_id", "field", "statement", "evidence_id", "quote"]),
    _fn("update_question", "Mark a question answered (needs at least one accepted claim) or unanswerable "
        "(explain what you tried).", {"question_id": S, "status": {"type": "string", "enum": ["answered", "unanswerable"]},
                                      "note": S}, ["question_id", "status", "note"]),
    _fn("add_question", "Add a research question you discovered is important (e.g. an acquisition, a lawsuit).",
        {"topic": S, "question": S, "priority": {"type": "integer", "enum": [1, 2, 3]}}, ["topic", "question", "priority"]),
    _fn("finish", "End the investigation with a short summary of what you found and what is still uncertain.",
        {"summary": S}, ["summary"]),
]


class Toolbox:
    """Executes the agent's tool calls against the company state."""

    def __init__(self, state: CompanyState):
        self.state = state
        self.finished = False
        self.summary = ""
        self.pending_reject = False

    # -- budget / status ------------------------------------------------------------
    def searches_left(self) -> int:
        return max(0, settings.max_searches - len(self.state.searched))

    def reads_left(self) -> int:
        return max(0, settings.max_fetches - len(self.state.fetched))

    def steps_left(self) -> int:
        return max(0, settings.max_steps - (self.state.agent_steps - self.state.round_start_step))

    def open_questions(self) -> list[Question]:
        st = self.state.question_status
        return [q for q in self.state.plan.questions if st.get(q.id, {}).get("status", "open") == "open"]

    def status_line(self) -> str:
        accepted = sum(1 for c in self.state.claims if c.quote_found)
        opens = ", ".join(f"{q.id}(p{q.priority})" for q in self.open_questions()) or "none"
        return (f"\n\n[status] steps left {self.steps_left()} · searches left {self.searches_left()} · "
                f"page reads left {self.reads_left()} · claims accepted {accepted} · open questions: {opens}")

    # -- tools ------------------------------------------------------------------------
    def run(self, name: str, args: dict) -> str:
        self.state.tool_counts[name] = self.state.tool_counts.get(name, 0) + 1
        fn = getattr(self, f"t_{name}", None)
        if fn is None:
            return f"Unknown tool '{name}'."
        try:
            return fn(**args)
        except TypeError as e:
            return f"Bad arguments for {name}: {e}"

    @neatlogs.span(kind="TOOL", tool_name="company_profile")
    def t_company_profile(self) -> str:
        existing = next((e for e in self.state.evidence if e.kind == "crustdata"), None)
        if existing is None:
            try:
                record = crustdata.enrich_company(domain=self.state.domain,
                                                  name=None if self.state.domain else self.state.company)
            except (Fatal, Retryable) as e:
                emit("recover", f"Crustdata profile unavailable ({e}); agent told to use the web instead")
                return f"The company database is unavailable right now ({e}). Use web_search instead."
            if not record:
                return "No record for this company in the database. Use web_search."
            name = (record.get("basic_info") or {}).get("name") or self.state.company
            existing = researcher._add(self.state, kind="crustdata", via="crustdata", text=crustdata.render_company(record),
                                       url=f"crustdata://company/{record.get('crustdata_company_id', '')}",
                                       title=f"Crustdata company record: {name}")
            emit("crust", f"company record: {len(existing.text.splitlines())} fields")
        return f"[{existing.id}] {existing.title}\n{existing.text}"

    @neatlogs.span(kind="TOOL", tool_name="web_search")
    def t_web_search(self, query: str) -> str:
        if self.searches_left() <= 0:
            return "Search budget used up. Work with the evidence you have, or finish."
        if query.lower() in (s.lower() for s in self.state.searched):
            return "You already ran this search. Try a different query."
        results, via = researcher._search(query)
        self.state.searched.append(query)
        emit("web", f"search ({via}) '{query}' -> {len(results)} results")
        lines = []
        for r in results[:6]:
            ev = researcher._add(self.state, kind="snippet", url=r["url"], title=r.get("title", ""),
                                 text=r.get("snippet", ""), via=via)
            lines.append(f"[{ev.id}] {r.get('title', '')} | {r['url']}\n    {r.get('snippet', '')}")
        return "\n".join(lines) or "No results."

    @neatlogs.span(kind="TOOL", tool_name="read_page")
    def t_read_page(self, url: str) -> str:
        known = next((e for e in self.state.evidence if e.kind == "page" and e.url == url), None)
        if known:
            return f"[{known.id}] {known.title} | {known.url}\n{known.text}"
        if self.reads_left() <= 0:
            return "Page-read budget used up. Use the snippets you have, or finish."
        if any(s in researcher._host(url) for s in researcher.SKIP_HOSTS):
            return "That site blocks automated reading (login wall). Pick another source."
        pages = researcher._fetch([url])
        self.state.fetched.append(url)
        page = next((p for p in pages if p.get("content")), None)
        if not page:
            return "Could not read that page (empty or blocked). Try another result."
        ev = researcher._add(self.state, kind="page", url=url, title=page.get("title", ""),
                             text=page["content"][: settings.page_chars], via=page.get("via", "crustdata-web"))
        emit("web", f"read {url[:80]} -> {ev.id} ({len(ev.text)} chars)")
        return f"[{ev.id}] {ev.title} | {url}\n{ev.text}"

    @neatlogs.span(kind="GUARDRAIL", name="record_claim")
    def t_record_claim(self, question_id: str, field: str, statement: str, evidence_id: str, quote: str,
                       value: str | None = None) -> str:
        st = self.state
        st.claim_attempts += 1
        ev = next((e for e in st.evidence if e.id == evidence_id), None)
        if ev is None:
            st.rejected_in_loop += 1
            return f"REJECTED: there is no evidence block {evidence_id}. Cite the [E#] the quote came from."
        if len(quote) > QUOTE_MAX:
            st.rejected_in_loop += 1
            return f"REJECTED: quote is {len(quote)} chars; keep it under {QUOTE_MAX} and to the point."
        found, score, near = ground(quote, ev.text)
        if not found:
            st.rejected_in_loop += 1
            self.pending_reject = True
            emit("verify", f"claim rejected in-loop: quote not in {evidence_id} (match {score:.0f}%) — agent must fix it")
            return (f"REJECTED: that quote does not appear in {evidence_id} (closest match {score:.0f}%). "
                    f"Copy the exact words from the source text; the closest passage is: \"{near[:220]}\"")
        if any(c.evidence_id == evidence_id and c.quote.strip().lower() == quote.strip().lower() for c in st.claims):
            return "Already recorded (same quote and source)."
        cid = f"C{len(st.claims) + 1}"
        st.claims.append(Claim(id=cid, round=st.round, question_id=question_id,
                               field=field if field in FACT_FIELDS else None, statement=statement, value=value,
                               evidence_id=evidence_id, quote=quote, quote_found=True, quote_score=score))
        if self.pending_reject:  # the previous attempt was rejected and the agent fixed it
            st.self_corrections += 1
            self.pending_reject = False
            emit("verify", f"self-corrected: {cid} accepted after the agent fixed a rejected claim")
        emit("extract", f"{cid} [{question_id}] {statement[:90]}")
        return f"ACCEPTED as {cid} (quote found in {evidence_id}). An independent checker will review it later."

    def t_update_question(self, question_id: str, status: str, note: str) -> str:
        if question_id not in {q.id for q in self.state.plan.questions}:
            return f"Unknown question {question_id}."
        if status == "answered" and not any(c.question_id == question_id for c in self.state.claims):
            return f"Can't mark {question_id} answered: no accepted claim for it yet. Record one first."
        self.state.question_status[question_id] = {"status": status, "note": note[:300]}
        emit("plan", f"{question_id} -> {status}: {note[:80]}")
        return f"{question_id} marked {status}."

    def t_add_question(self, topic: str, question: str, priority: int = 2) -> str:
        qid = f"q{len(self.state.plan.questions) + 1}"
        self.state.plan.questions.append(Question(id=qid, topic=topic, question=question, priority=int(priority)))
        emit("plan", f"agent added {qid} (p{priority}): {question[:80]}")
        return f"Added {qid}."

    def t_finish(self, summary: str) -> str:
        must = [q.id for q in self.open_questions() if q.priority == 1]
        if must and self.steps_left() > 3 and (self.searches_left() or self.reads_left()):
            return (f"Not yet: priority-1 questions {', '.join(must)} are still open. Answer them, or mark them "
                    "unanswerable with what you tried.")
        self.finished, self.summary = True, summary
        return "Investigation closed."


def _compact(messages: list[dict], keep: int) -> int:
    """Context management: replace the text of all but the last `keep` long evidence results with a stub."""
    long_idx = [i for i, m in enumerate(messages)
                if m.get("role") == "tool" and m.get("content", "").startswith("[E") and len(m["content"]) > 900]
    removed = 0
    for i in long_idx[:-keep] if keep else long_idx:
        content = messages[i]["content"]
        if not content.endswith("<removed>"):
            eid = content[1:content.index("]")]
            messages[i]["content"] = (f"[{eid}] (page text removed from context to save space; its claims are "
                                      f"recorded. Call read_page/company_profile again to re-read it.) <removed>")
            removed += 1
    return removed


def _questions_block(state: CompanyState) -> str:
    return "\n".join(f"- {q.id} (priority {q.priority}, {q.topic}): {q.question}" for q in state.plan.questions)


@neatlogs.span(kind="AGENT", name="analyst", role="research analyst", goal="answer every diligence question with sourced claims")
def investigate(state: CompanyState, save, tasks: str | None = None) -> str:
    """Run (or resume) the analyst's tool loop for the current round. Returns the analyst's closing summary."""
    box = Toolbox(state)
    if not state.agent_messages:
        system, user = prompts.load("analyst", state.prompts_version)
        variables = {"company": state.company, "domain": state.domain or "unknown", "fields": ", ".join(FACT_FIELDS),
                     "questions": _questions_block(state), "max_steps": settings.max_steps,
                     "max_searches": settings.max_searches, "max_reads": settings.max_fetches}
        state.agent_messages = [{"role": "system", "content": prompts.render(system, variables)},
                                {"role": "user", "content": prompts.render(user, variables) + box.status_line()}]
        state.round_start_step = state.agent_steps
    elif tasks:
        state.round_start_step = state.agent_steps
        state.agent_messages.append({"role": "user", "content": tasks + box.status_line()})
    save()

    nudges = 0
    while box.steps_left() > 0 and not box.finished:
        if _compact(state.agent_messages, settings.keep_pages):
            emit("info", "context compacted: older page text replaced with stubs")
        msg, model = llm.chat("agent", state.agent_messages, TOOLS, effort="low")
        state.agent_messages.append(msg)
        state.agent_steps += 1
        calls = msg.get("tool_calls") or []
        if not calls:
            nudges += 1
            if nudges > 2:
                emit("info", "analyst stopped calling tools; closing the round")
                break
            state.agent_messages.append({"role": "user", "content": "Use a tool to continue, or call finish." + box.status_line()})
            save()
            continue
        nudges = 0
        for i, call in enumerate(calls):
            name = call["function"]["name"]
            try:
                args = json.loads(call["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args, result = None, "Your arguments were not valid JSON. Try again."
            if args is not None:
                shown = ", ".join(f"{k}={str(v)[:60]!r}" for k, v in args.items() if k != "quote")
                emit("agent", f"step {state.agent_steps} ({model.split(':')[-1]}) -> {name}({shown})")
                result = box.run(name, args)
            if i == len(calls) - 1:
                result += box.status_line()
            state.agent_messages.append({"role": "tool", "tool_call_id": call["id"], "content": result})
        save()

    if not box.finished:
        emit("agent", f"round {state.round} ended on budget after {state.agent_steps - state.round_start_step} steps")
    return box.summary
