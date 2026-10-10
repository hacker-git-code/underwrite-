"""Eval harness: run a prompt version over the dataset and score it.

Two kinds of score:
- fact accuracy / precision against hand-checked ground truth (evals/dataset.json)
- trust metrics the agent reports about itself (grounding, support, coverage, conflicts, cost)
"""

from __future__ import annotations

import json
import re
import time
import unicodedata
from pathlib import Path

from rich.table import Table

from .config import settings
from .obs import console, emit
from .pipeline import run_batch


def load_dataset(split: str = "all") -> list[dict]:
    data = json.loads((settings.evals_dir / "dataset.json").read_text(encoding="utf-8"))["companies"]
    return [c for c in data if split == "all" or c["split"] == split]


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s).strip().lower()


def _as_text(v) -> str:
    if v is None:
        return ""
    return ", ".join(map(str, v)) if isinstance(v, list) else str(v)


def score_facts(fact_sheet: dict, gold: dict) -> dict:
    """Per gold field: score in [0,1], whether the agent answered at all, and what it said."""
    out = {}
    for field, truth in gold.items():
        pred = _fold(_as_text(fact_sheet.get(field)))
        answered = pred not in ("", "null", "none", "unknown", "n/a")
        if not answered:
            s = 0.0
        elif field == "founded_year":
            years = re.findall(r"(?:19|20)\d\d", pred)
            s = 1.0 if years and years[0] == truth else 0.0
        elif field == "hq_city":
            s = 1.0 if any(_fold(a) in pred for a in truth) else 0.0
        elif field == "founders":
            s = sum(_fold(n).split()[-1] in pred for n in truth) / len(truth)
        elif field == "ceo":
            s = 1.0 if _fold(truth).split()[-1] in pred else 0.0
        else:
            s = 1.0 if _fold(str(truth)) in pred else 0.0
        out[field] = {"score": s, "answered": answered, "pred": _as_text(fact_sheet.get(field))}
    return out


def summarize(rows: list[dict]) -> dict:
    done = [r for r in rows if r["phase"] == "done"]
    n = len(done) or 1
    fields = [f for r in done for f in r["facts"].values()]
    answered = [f for f in fields if f["answered"]]

    def avg(key: str) -> float:
        return round(sum(r["metrics"].get(key, 0) for r in done) / n, 3)

    return {
        "companies": len(rows),
        "completed": len(done),
        "fact_accuracy": round(sum(f["score"] for f in fields) / (len(fields) or 1), 3),
        "fact_precision": round(sum(f["score"] for f in answered) / (len(answered) or 1), 3),
        "supported_rate": avg("supported_rate"),
        "grounded_rate": avg("grounded_rate"),
        "unsupported_per_memo": avg("unsupported"),
        "coverage": avg("coverage"),
        "must_coverage": avg("must_coverage"),
        "conflicts_per_memo": avg("conflicts"),
        "invalid_citations_per_memo": avg("invalid_citations"),
        "recoveries": sum(r["metrics"].get("recoveries", 0) for r in done),
        "usd_per_memo": round(sum(r["usage"].get("llm_usd", 0) for r in done) / n, 4),
        "credits_per_memo": round(sum(r["usage"].get("crust_credits", 0) for r in done) / n, 2),
        "seconds_per_memo": avg("duration_s"),
    }


def run_eval(version: str, split: str = "all", limit: int | None = None, resume_id: str | None = None,
             mode: str | None = None) -> Path:
    """Score `version` on the dataset. With resume_id, continue that interrupted eval run: finished companies
    are skipped (their saved state is reused), unfinished ones pick up at their last checkpoint."""
    items = load_dataset(split)[:limit] if limit else load_dataset(split)
    if resume_id:  # keep the mode the interrupted run was started with
        manifest = settings.runs_dir / resume_id / "manifest.json"
        if manifest.exists():
            mode = json.loads(manifest.read_text(encoding="utf-8")).get("mode", "pipeline")
    mode = mode or settings.mode
    tag = version if mode == "pipeline" else f"{version}-agent"
    run_id = resume_id or f"eval-{tag}-{split}-{time.strftime('%Y%m%d-%H%M%S')}"
    emit("eval", f"eval {run_id}: {len(items)} companies, prompts {version}" + (" (resumed)" if resume_id else ""))
    states = run_batch([(c["company"], c["domain"]) for c in items], run_id, version, mode)
    rows = []
    for item, st in zip(items, states):
        rows.append({
            "company": item["company"],
            "split": item["split"],
            "phase": st.phase,
            "error": st.error,
            "facts": score_facts(st.memo.fact_sheet if st.memo else {}, item["gold"]),
            "metrics": st.metrics,
            "usage": st.usage,
            "trace_ids": st.trace_ids,
        })
    result = {"run_id": run_id, "version": version, "mode": mode, "split": split, "created": time.time(), "rows": rows,
              "summary": {s: summarize([r for r in rows if s == "all" or r["split"] == s]) for s in ("all", "train", "test")}}
    path = settings.runs_dir / run_id / "eval.json"
    path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print_eval(result)
    return path


def rescore(path: Path) -> dict:
    """Re-grade a finished eval against the current dataset (e.g. after fixing a ground-truth error) using the
    memos it already produced. Nothing is re-run."""
    from .models import CompanyState
    from .pipeline import company_dir

    result = json.loads(path.read_text(encoding="utf-8"))
    gold = {c["company"]: c["gold"] for c in load_dataset("all")}
    for row in result["rows"]:
        sp = company_dir(result["run_id"], row["company"]) / "state.json"
        if sp.exists() and row["company"] in gold:
            st = CompanyState.model_validate_json(sp.read_text(encoding="utf-8"))
            row["facts"] = score_facts(st.memo.fact_sheet if st.memo else {}, gold[row["company"]])
    result["summary"] = {s: summarize([r for r in result["rows"] if s == "all" or r["split"] == s])
                         for s in ("all", "train", "test")}
    result["rescored"] = time.time()
    path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def print_eval(result: dict) -> None:
    t = Table(title=f"eval {result['run_id']}")
    for col in ("company", "split", "facts", "supported", "grounded", "coverage", "conflicts", "$", "credits", "status"):
        t.add_column(col)
    for r in result["rows"]:
        facts = r["facts"]
        fa = sum(f["score"] for f in facts.values()) / (len(facts) or 1)
        m, u = r["metrics"] or {}, r["usage"] or {}
        t.add_row(r["company"], r["split"], f"{fa:.0%}", f"{m.get('supported_rate', 0):.0%}",
                  f"{m.get('grounded_rate', 0):.0%}", f"{m.get('coverage', 0):.0%}", str(m.get("conflicts", "")),
                  f"{u.get('llm_usd', 0):.3f}", f"{u.get('crust_credits', 0):g}", r["phase"] if not r["error"] else "error")
    console.print(t)
    console.print_json(data=result["summary"]["all"])


def label(result: dict) -> str:
    return f"{result.get('mode', 'pipeline')}:{result['version']}"


def latest_eval(version: str, mode: str | None = None) -> Path | None:
    """Latest finished eval of `version` in `mode` (evals from before modes existed count as pipeline)."""
    mode = mode or settings.mode
    found = []
    for p in settings.runs_dir.glob(f"eval-{version}-*/eval.json"):
        data = json.loads(p.read_text(encoding="utf-8"))
        if data.get("version") == version and data.get("mode", "pipeline") == mode:
            found.append(p)
    return max(found, key=lambda p: p.stat().st_mtime) if found else None


HIGHER_IS_BETTER = {"fact_accuracy", "fact_precision", "supported_rate", "grounded_rate", "coverage", "must_coverage",
                    "completed"}
LOWER_IS_BETTER = {"unsupported_per_memo", "invalid_citations_per_memo", "usd_per_memo", "credits_per_memo",
                   "seconds_per_memo"}


def compare(a: Path, b: Path, split: str = "test") -> dict:
    ra, rb = json.loads(a.read_text(encoding="utf-8")), json.loads(b.read_text(encoding="utf-8"))
    sa, sb = ra["summary"][split], rb["summary"][split]
    t = Table(title=f"{label(ra)} -> {label(rb)} ({split} split)")
    for col in ("metric", label(ra), label(rb), "change"):
        t.add_column(col)
    out = {}
    for k in sa:
        va, vb = sa[k], sb.get(k)
        if not isinstance(va, (int, float)) or not isinstance(vb, (int, float)):
            continue
        d = vb - va
        better = (k in HIGHER_IS_BETTER and d > 0) or (k in LOWER_IS_BETTER and d < 0)
        worse = (k in HIGHER_IS_BETTER and d < 0) or (k in LOWER_IS_BETTER and d > 0)
        style = "green" if better else "red" if worse else "dim"
        t.add_row(k, f"{va:g}", f"{vb:g}", f"[{style}]{d:+.3g}[/{style}]")
        out[k] = {"before": va, "after": vb, "delta": d}
    console.print(t)
    return out
