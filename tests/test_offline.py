"""Offline end-to-end test: fake LLM + fake tools, real pipeline/verifier/report/eval code.

Run: uv run python tests/test_offline.py   (or: uv run pytest tests)
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from underwrite import llm, pipeline  # noqa: E402
from underwrite.config import settings  # noqa: E402
from underwrite.evals import score_facts  # noqa: E402
from underwrite.tools import crustdata  # noqa: E402

RECORD = {
    "crustdata_company_id": 42,
    "basic_info": {"name": "Acme AI", "primary_domain": "acme.ai", "year_founded": 2019},
    "headcount": {"total": 18},
    "locations": {"headquarters": "San Francisco, California, United States"},
}
PAGE = ("Acme AI was founded in 2019 by Jane Doe and John Roe. The company is headquartered in San Francisco. "
        "Acme AI now has a team of 50 people. Jane Doe is the CEO.")


def fake_complete(role, system, user, *, effort=None, max_tokens=16000):
    if "research planner" in system:
        out = {"questions": [
            {"id": "q1", "topic": "founding", "question": "When was it founded?", "queries": ["acme ai founded"], "priority": 1},
            {"id": "q2", "topic": "team", "question": "Who founded it?", "queries": ["acme ai founders"], "priority": 1},
            {"id": "q3", "topic": "risks", "question": "Any lawsuits?", "queries": ["acme ai lawsuit"], "priority": 2},
        ]}
    elif "fill gaps" in system:
        out = {"queries": [{"question_id": "q3", "query": "acme ai controversy"}]}
    elif "extract factual claims" in system:
        ids = re.findall(r"^\[(E\d+)\] (\w+)", user, flags=re.M)
        crust = next((i for i, k in ids if k == "crustdata"), None)
        page = next((i for i, k in ids if k == "page"), None)
        claims = []
        if crust:
            claims += [
                {"question_id": "q1", "field": "founded_year", "statement": "Founded in 2019.", "value": "2019",
                 "evidence_id": crust, "quote": "Year founded: 2019"},
                {"question_id": "q2", "field": "headcount", "statement": "Has 18 employees.", "value": "18",
                 "evidence_id": crust, "quote": "Employee count: 18"},
            ]
        if page:
            claims += [
                {"question_id": "q2", "field": "founders", "statement": "Founded by Jane Doe and John Roe.",
                 "value": "Jane Doe, John Roe", "evidence_id": page, "quote": "founded in 2019 by Jane Doe and John Roe"},
                {"question_id": "q2", "field": "headcount", "statement": "Team of 50.", "value": "50",
                 "evidence_id": page, "quote": "now has a team of 50 people"},
                {"question_id": "q3", "field": None, "statement": "Acme raised $1B from aliens.", "value": None,
                 "evidence_id": page, "quote": "raised a billion dollars from aliens"},
            ]
        out = {"claims": claims}
    elif "independent fact-checker" in system:
        out = {"judgements": [{"claim_id": cid, "support": "supported", "reason": "stated in source"}
                              for cid in re.findall(r"^(C\d+)$", user, flags=re.M)]}
    elif "venture-capital analyst" in system:
        cids = re.findall(r"^(C\d+) \|", user, flags=re.M)
        out = {"recommendation": "Dig deeper: small team, conflicting headcount.", "confidence": "medium",
               "memo_markdown": "## Summary\nAcme AI was founded in 2019 " + "".join(f"[{c}]" for c in cids[:2])
               + ". Bogus [C99].\n\n## Team\nFounders are Jane Doe and John Roe.",
               "fact_sheet": {"founded_year": "2019", "founders": ["Jane Doe", "John Roe"], "hq_city": None}}
    elif "repair" in system:
        broken = user.split("Broken output:\n", 1)[1]
        raise AssertionError(f"repair should not be needed in this test: {broken[:80]}")
    else:
        raise AssertionError(f"unexpected prompt: {system[:80]}")
    return json.dumps(out), "fake-model"


def setup_fakes(tmp: Path):
    settings.runs_dir = tmp / "runs"
    settings.cache_dir = tmp / "cache"
    settings.crustdata_api_key = "test"
    llm.complete = fake_complete
    crustdata.enrich_company = lambda domain=None, name=None: RECORD
    crustdata.web_search = lambda q: [{"title": "Acme AI story", "url": f"https://news.example.com/{abs(hash(q))}", "snippet": "Acme AI startup"}]
    crustdata.web_fetch = lambda urls: [{"url": u, "title": "Acme AI story", "content": PAGE, "success": True} for u in urls]


def test_pipeline_end_to_end():
    with tempfile.TemporaryDirectory() as d:
        setup_fakes(Path(d))
        st = pipeline.run_company("Acme AI", "acme.ai", "test-run", "v1")
        assert st.phase == "done", st.error
        by_stmt = {c.statement: c for c in st.claims}
        # fabricated quote is rejected deterministically, without the judge
        alien = by_stmt["Acme raised $1B from aliens."]
        assert alien.support == "unsupported" and not alien.quote_found
        # crustdata (18) vs website (50) headcount disagreement is flagged
        assert any(c.field == "headcount" for c in st.conflicts), st.conflicts
        # citation to a claim that doesn't exist is stripped from the memo
        assert "C99" in st.invalid_citations and "[C99]" not in st.memo.memo_markdown
        assert st.round == 2, "unanswered priority-2 question should trigger a second research round"
        html = (Path(d) / "runs" / "test-run" / "acme-ai" / "memo.html").read_text(encoding="utf-8")
        assert "Conflicts between sources" in html and "headcount" in html
        m = st.metrics
        assert m["claims"] >= 5 and 0 < m["supported_rate"] < 1 and m["conflicts"] >= 1


def test_resume_after_crash():
    with tempfile.TemporaryDirectory() as d:
        setup_fakes(Path(d))
        real = pipeline.verifier.verify
        calls = {"n": 0}

        def crash_once(state, claims):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("simulated crash (power cut)")
            return real(state, claims)

        pipeline.verifier.verify = crash_once
        try:
            st = pipeline.run_company("Acme AI", "acme.ai", "crash-run", "v1")
            assert st.phase == "extracted" and "power cut" in st.error
            st = pipeline.run_company("Acme AI", "acme.ai", "crash-run", "v1")
            assert st.phase == "done" and st.error is None
        finally:
            pipeline.verifier.verify = real


def test_chaos_recovers():
    with tempfile.TemporaryDirectory() as d:
        setup_fakes(Path(d))
        import underwrite.resilience as r

        settings.chaos = 1.0
        hits = {"n": 0}
        real_hit = r.chaos_hit

        def first_two(point, what):  # inject exactly two faults, then behave
            hits["n"] += 1
            return hits["n"] <= 2 and real_hit(point, what)

        r.chaos_hit = first_two
        llm.chaos_hit = first_two
        repaired = {"n": 0}
        last = {"out": None}

        def complete_with_repair(role, system, user, **kw):
            if "repair" in system:  # a faithful repairer: restores the untruncated output
                repaired["n"] += 1
                return last["out"]
            last["out"] = fake_complete(role, system, user, **kw)
            return last["out"]

        llm.complete = complete_with_repair
        try:
            st = pipeline.run_company("Acme AI", "acme.ai", "chaos-run", "v1")
            assert st.phase == "done", st.error
            assert repaired["n"] == 2, "both truncated JSON outputs should be repaired"
            assert st.metrics["injected_faults"] == 2 and st.metrics["recoveries"] >= 2
        finally:
            settings.chaos = 0.0
            r.chaos_hit = real_hit
            llm.chaos_hit = real_hit
            llm.complete = fake_complete


def test_fact_scoring():
    gold = {"founded_year": "2019", "hq_city": ["San Francisco"], "founders": ["Karri Saarinen", "Tuomas Artman"],
            "ceo": "Karri Saarinen"}
    s = score_facts({"founded_year": "Founded 2019", "hq_city": None, "founders": ["Karri Saarinen"],
                     "ceo": "Karri Saarinen (CEO)"}, gold)
    assert s["founded_year"]["score"] == 1 and s["hq_city"]["score"] == 0 and not s["hq_city"]["answered"]
    assert s["founders"]["score"] == 0.5 and s["ceo"]["score"] == 1


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS {name}")
