"""Coach: improves the agent from its own traces.

1. Collect failures from the latest eval of the base version (train split only).
2. Ask neatlogs, over its MCP server, what it saw: detections, triage fixes, and the
   span trees of the worst traces.
3. Have Claude propose revised prompt files, each change tied to the evidence behind it.
4. Write them as a new prompt version, evaluate it, and keep it only if the numbers improve.
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
from pathlib import Path

import neatlogs
from pydantic import BaseModel, Field

from . import evals, llm, prompts
from .config import settings
from .models import CompanyState
from .obs import console, emit

ALIASES = {
    "query": ["query", "q", "text", "search", "search_query"],
    "trace_id": ["trace_id", "traceId", "id", "trace"],
    "limit": ["limit", "top_k", "k", "max_results", "page_size"],
    "triage_id": ["triage_id", "id"],
    "workflow_name": ["workflow_name"],
}

PIPELINE = """\
Underwrite researches one company per run:
- planner (smart model): company -> 8-10 research questions with web search queries. Vars: company, domain, today.
- researcher (code, no prompt): Crustdata company record + web search + page fetch within a budget.
- extractor (fast model): evidence blocks -> atomic claims {question_id, field, statement, value, evidence_id, quote}.
  Vars: company, questions, evidence, fields.
- verifier: code checks the quote really occurs in the cited evidence (fuzzy match >= 90%); claims failing that are
  rejected with no LLM call. Then the verifier prompt (fast model) judges supported/partial/unsupported from the
  source text around the quote. Vars: company, items.
- replanner (fast model): unanswered questions -> new queries for a 2nd research round. Vars: company, domain, gaps, tried.
- writer (smart model): verified claims -> cited memo + fact sheet (scored against ground truth).
  Vars: company, domain, claims, conflicts, gaps, fields.
Every prompt file is '<system>\\n---USER---\\n<user template>' with {{var}} placeholders. Outputs must be JSON.
"""


class Change(BaseModel):
    prompt: str
    why: str
    evidence: str = ""


class CoachOut(BaseModel):
    diagnosis: list[str]
    changes: list[Change]
    files: dict[str, str] = Field(default_factory=dict)


# ---- neatlogs MCP ---------------------------------------------------------------


def _fit_args(schema: dict, **wanted) -> dict:
    props = (schema or {}).get("properties", {}) or {}
    args = {}
    for key, value in wanted.items():
        for name in ALIASES.get(key, [key]):
            if name in props:
                args[name] = value
                break
    return args


async def _ask_neatlogs(trace_ids: list[str]) -> dict[str, str]:
    from mcp import Client
    from mcp.client.streamable_http import streamable_http_client
    from mcp.shared._httpx_utils import create_mcp_http_client

    http = create_mcp_http_client(headers={"Authorization": f"Bearer {settings.neatlogs_api_key}"})
    found: dict[str, str] = {}
    async with Client(streamable_http_client(settings.neatlogs_mcp_url, http_client=http)) as client:
        tools = {t.name: getattr(t, "input_schema", None) or getattr(t, "inputSchema", None) or {}
                 for t in (await client.list_tools()).tools}
        emit("coach", f"neatlogs MCP connected: {len(tools)} tools ({', '.join(sorted(tools)[:8])}...)")

        async def call(name: str, key: str, **wanted) -> None:
            if name not in tools:
                return
            try:
                res = await client.call_tool(name, _fit_args(tools[name], **wanted))
                text = "\n".join(getattr(c, "text", "") for c in res.content)
                found[key] = text[:6000]
                emit("coach", f"neatlogs {name}{' ' + str(wanted) if wanted else ''}: {len(text)} chars")
            except Exception as e:
                emit("recover", f"neatlogs {name} failed ({type(e).__name__}: {e}); continuing without it")

        await call("whoami", "whoami")
        await call("list_detections", "detections")
        await call("triage_list", "triage")
        for tid in re.findall(r'"(?:id|fix_id|triage_id)"\s*:\s*"([^"]+)"', found.get("triage", ""))[:3]:
            await call("triage_get", f"triage:{tid}", triage_id=tid)
        await call("search_traces", "search:unsupported", query="unsupported quote not found in cited source",
                   limit=5, workflow_name="underwrite")
        await call("search_traces", "search:recover", query="invalid JSON repairing fallback", limit=5,
                   workflow_name="underwrite")
        for tid in trace_ids[:3]:
            await call("get_trace_context", f"trace:{tid}", trace_id=tid)
    return found


def ask_neatlogs(trace_ids: list[str]) -> dict[str, str]:
    if not settings.neatlogs_api_key:
        emit("recover", "NEATLOGS_API_KEY not set; coaching from local eval evidence only")
        return {}
    try:
        return asyncio.run(_ask_neatlogs(trace_ids))
    except Exception as e:
        emit("recover", f"neatlogs MCP unavailable ({type(e).__name__}: {e}); coaching from local evidence only")
        return {}


# ---- local evidence --------------------------------------------------------------


def local_failures(eval_path: Path) -> tuple[dict, list[str]]:
    data = json.loads(eval_path.read_text(encoding="utf-8"))
    rows = [r for r in data["rows"] if r["split"] == "train"]
    wrong, rejected, gaps, recoveries = [], [], [], {}
    worst: list[tuple[float, str]] = []
    for r in rows:
        for field, f in r["facts"].items():
            if f["score"] < 1:
                wrong.append(f"{r['company']}.{field}: agent said {f['pred']!r} (score {f['score']:.2f})")
        state_path = settings.runs_dir / data["run_id"] / re.sub(r"[^a-z0-9]+", "-", r["company"].lower()).strip("-") / "state.json"
        if state_path.exists():
            st = CompanyState.model_validate_json(state_path.read_text(encoding="utf-8"))
            for c in st.claims:
                if c.support == "unsupported" and len(rejected) < 30:
                    rejected.append(f"{r['company']} {c.id}: {c.statement!r} quote={c.quote[:120]!r} -> {c.reason}")
            answered = {c.question_id for c in st.claims if c.support in ("supported", "partial")}
            for q in (st.plan.questions if st.plan else []):
                if q.id not in answered and len(gaps) < 20:
                    gaps.append(f"{r['company']}: {q.question} (queries: {q.queries})")
            ev_path = state_path.parent / "events.jsonl"
            if ev_path.exists():
                for line in ev_path.read_text(encoding="utf-8").splitlines():
                    e = json.loads(line)
                    if e["kind"] in ("recover", "fail"):
                        k = re.sub(r"\d+", "N", e["msg"])[:90]
                        recoveries[k] = recoveries.get(k, 0) + 1
        m = r.get("metrics") or {}
        worst.append((m.get("supported_rate", 0) + m.get("coverage", 0), (r.get("trace_ids") or [""])[0]))
    trace_ids = [t for _, t in sorted(worst) if t]
    return {
        "summary_train": data["summary"]["train"],
        "wrong_facts": wrong,
        "rejected_claims": rejected,
        "unanswered_questions": gaps,
        "recoveries": dict(sorted(recoveries.items(), key=lambda x: -x[1])[:15]),
    }, trace_ids


# ---- the coaching step ------------------------------------------------------------


def _placeholders(text: str) -> set[str]:
    return set(re.findall(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}", text))


def next_version() -> str:
    nums = [int(v[1:]) for v in prompts.versions() if v[1:].isdigit()]
    return f"v{max(nums, default=0) + 1}"


@neatlogs.span(kind="AGENT", name="coach", role="agent engineer", goal="improve the agent's prompts from its traces")
def coach(base: str, run_eval: bool = True, split: str = "all") -> dict:
    eval_path = evals.latest_eval(base)
    if eval_path is None:
        emit("coach", f"no eval found for {base}; running one first")
        eval_path = evals.run_eval(base, split)
    emit("coach", f"baseline: {eval_path.parent.name}")

    failures, worst_traces = local_failures(eval_path)
    emit("coach", f"local evidence: {len(failures['wrong_facts'])} wrong facts, {len(failures['rejected_claims'])} "
                  f"rejected claims, {len(failures['unanswered_questions'])} unanswered questions")
    from_neatlogs = ask_neatlogs(worst_traces)

    base_dir = settings.prompts_dir / base
    current = {p.stem: p.read_text(encoding="utf-8") for p in sorted(base_dir.glob("*.md")) if p.stem in prompts.NAMES}
    files_text = "\n\n".join(f"=== {name}.md ===\n{text}" for name, text in current.items())

    out = _propose(files_text, failures, from_neatlogs)

    accepted_files: dict[str, str] = {}
    for name, text in out.files.items():
        name = name.removesuffix(".md")
        if name not in current:
            emit("coach", f"ignoring proposed file '{name}' (not a known prompt)")
        elif prompts.SPLIT not in text:
            emit("coach", f"rejecting {name}: missing {prompts.SPLIT}")
        elif _placeholders(text) != _placeholders(current[name]):
            emit("coach", f"rejecting {name}: placeholders changed {_placeholders(current[name])} -> {_placeholders(text)}")
        elif text.strip() != current[name].strip():
            accepted_files[name] = text.strip() + "\n"
    if not accepted_files:
        emit("coach", "no valid prompt changes proposed; nothing to evaluate")
        return {"base": base, "new": None, "decision": "no-change", "diagnosis": out.diagnosis}

    new = next_version()
    new_dir = settings.prompts_dir / new
    shutil.copytree(base_dir, new_dir)
    for leftover in ("COACH_NOTES.md", "coach_report.json"):
        (new_dir / leftover).unlink(missing_ok=True)
    for name, text in accepted_files.items():
        (new_dir / f"{name}.md").write_text(text, encoding="utf-8")
    emit("coach", f"wrote prompts/{new}: changed {', '.join(sorted(accepted_files))}")

    report = {
        "base": base,
        "new": new,
        "baseline_eval": str(eval_path.relative_to(settings.runs_dir)),
        "neatlogs_sources": sorted(from_neatlogs),
        "diagnosis": out.diagnosis,
        "changes": [c.model_dump() for c in out.changes if c.prompt.removesuffix(".md") in accepted_files],
        "decision": "pending-eval",
    }
    if run_eval:
        new_eval = evals.run_eval(new, split)
        report["new_eval"] = str(new_eval.relative_to(settings.runs_dir))
        report["train"] = evals.compare(eval_path, new_eval, "train")
        report["test"] = evals.compare(eval_path, new_eval, "test")
        report["decision"] = decide(report["train"])
        emit("coach", f"decision: {report['decision']} prompts {new}")
    _write_notes(new_dir, report)
    return report


def decide(train: dict) -> str:
    """Keep the new version only if it is better on what it was optimised for, at a sane cost."""
    def d(k: str) -> float:
        return train.get(k, {}).get("delta", 0)

    quality = d("fact_accuracy") + d("supported_rate") + d("coverage") + 0.5 * d("fact_precision")
    cost_before = train.get("usd_per_memo", {}).get("before", 0) or 1e-9
    cost_ok = d("usd_per_memo") / cost_before < 0.5
    return "accepted" if quality > 0 and cost_ok else "rejected"


def _propose(files_text: str, failures: dict, neat: dict) -> CoachOut:
    system = (
        "You are an expert AI agent engineer. You improve a due-diligence research agent by rewriting its prompt "
        "files. Base every change on the evidence given (eval failures and neatlogs traces/detections/triage) and "
        "cite that evidence. Keep every {{placeholder}} exactly as it is and keep the ---USER--- separator. Prefer a "
        "few targeted, high-leverage edits over rewriting everything. Never add facts about specific companies to "
        "the prompts (that would overfit the eval). Respond with only a JSON object."
    )
    neat_text = "\n\n".join(f"--- {k} ---\n{v}" for k, v in neat.items()) or "(neatlogs MCP was not reachable)"
    user = (
        f"{PIPELINE}\n\nCURRENT PROMPT FILES:\n{files_text}\n\n"
        f"EVAL FAILURES (train split):\n{json.dumps(failures, indent=2)[:30000]}\n\n"
        f"NEATLOGS (via MCP):\n{neat_text[:30000]}\n\n"
        'Return JSON: {"diagnosis": ["root cause 1", ...], "changes": [{"prompt": "extractor", "why": "...", '
        '"evidence": "which failures / trace / detection this addresses"}], "files": {"extractor": "<complete new '
        'file content, including ---USER--->"}}. Include in "files" only the prompts you changed.'
    )
    with neatlogs.trace("prompt.coach", kind="CHAIN", version="coach-1"):
        text, model = llm.complete("smart", system, user, effort="high", max_tokens=32000)
    try:
        return CoachOut.model_validate(llm._extract_json(text))
    except Exception as e:
        emit("recover", f"coach output was not valid JSON ({str(e)[:80]}); asking for a repair")
        fixed, _ = llm.complete("fast", "Fix this into valid JSON matching the requested shape. Output only JSON.",
                                f"Schema: {json.dumps(CoachOut.model_json_schema())}\n\nOutput:\n{text}", max_tokens=32000)
        return CoachOut.model_validate(llm._extract_json(fixed))


def _write_notes(new_dir: Path, report: dict) -> None:
    lines = [f"# Coach notes: {report['base']} -> {report['new']}", "",
             f"Decision: **{report['decision']}**  ", f"Baseline eval: `{report['baseline_eval']}`  ",
             f"neatlogs evidence used: {', '.join(report['neatlogs_sources']) or 'none (MCP unreachable)'}", "",
             "## Diagnosis", *[f"- {d}" for d in report["diagnosis"]], "", "## Changes"]
    for c in report["changes"]:
        lines += [f"### {c['prompt']}", c["why"], "", f"_Evidence:_ {c['evidence']}", ""]
    for split in ("train", "test"):
        if split in report:
            lines += [f"## Result ({split} split)", "", "| metric | before | after | change |", "|---|---|---|---|"]
            lines += [f"| {k} | {v['before']:g} | {v['after']:g} | {v['delta']:+.3g} |" for k, v in report[split].items()]
            lines.append("")
    (new_dir / "COACH_NOTES.md").write_text("\n".join(lines), encoding="utf-8")
    (new_dir / "coach_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    console.print(f"[bold]Coach notes:[/bold] {new_dir / 'COACH_NOTES.md'}")
