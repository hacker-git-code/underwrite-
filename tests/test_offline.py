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


SKEPTIC_CALLS = {"n": 0}


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
    elif "skeptic on a venture-capital" in system:
        SKEPTIC_CALLS["n"] += 1
        out = ({"verdict": "needs_work", "objections": [{"question_id": "q3", "issue": "No check for lawsuits.",
                                                        "action": "Search for litigation news."}]}
               if SKEPTIC_CALLS["n"] == 1 else {"verdict": "ready", "objections": []})
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
        st = pipeline.run_company("Acme AI", "acme.ai", "test-run", "v1", "pipeline")
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
        assert "sources disagree" in html and "headcount" in html and "VERIFIED" in html
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
            st = pipeline.run_company("Acme AI", "acme.ai", "crash-run", "v1", "pipeline")
            assert st.phase == "extracted" and "power cut" in st.error
            st = pipeline.run_company("Acme AI", "acme.ai", "crash-run", "v1", "pipeline")
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
            st = pipeline.run_company("Acme AI", "acme.ai", "chaos-run", "v1", "pipeline")
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




def test_ssrf_blocked():
    from underwrite.tools.web import UnsafeURL, check_public

    for bad in ("http://169.254.169.254/latest/meta-data/", "http://127.0.0.1:8000/", "http://localhost/",
                "http://10.0.0.5/", "file:///etc/passwd", "javascript:alert(1)"):
        try:
            check_public(bad)
        except UnsafeURL:
            continue
        raise AssertionError(f"should block {bad}")


def test_report_escapes_untrusted_html():
    from underwrite.models import Claim, CompanyState, Evidence, MemoOut
    from underwrite.report import write_report

    with tempfile.TemporaryDirectory() as d:
        st = CompanyState(run_id="x", company="Evil <Co>", domain="evil.example", prompts_version="v1", phase="done")
        st.evidence = [Evidence(id="E1", kind="page", url="javascript:alert(1)", title="<img src=x onerror=alert(1)>",
                                text="Founded 2020.", via="direct")]
        st.claims = [Claim(id="C1", question_id="q1", field="founded_year", statement="Founded <b>2020</b>",
                           value="2020", evidence_id="E1", quote="Founded 2020", support="supported")]
        st.memo = MemoOut(recommendation="<script>alert(1)</script>", confidence="low",
                          memo_markdown="## Summary\nHi <script>alert(2)</script> [link](javascript:alert(3)) [C1].",
                          fact_sheet={"founded_year": "2020"})
        settings_pdf = __import__("underwrite.report", fromlist=["export_pdf"])
        settings_pdf.export_pdf = lambda p: None  # no browser needed for this test
        out = write_report(st, Path(d)).read_text(encoding="utf-8")
        body = out.split("</head>", 1)[1]
        assert "<script>alert" not in body and "<img src=x" not in body
        assert 'href="javascript:' not in body
        assert "&lt;script&gt;" in body


def _call(name: str, **args) -> dict:
    _call.n = getattr(_call, "n", 0) + 1
    return {"id": f"call{_call.n}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


def fake_chat(role, messages, tools, *, effort=None, max_tokens=4096):
    """A scripted analyst: makes a mistake, gets rejected, fixes it, tries to quit early, and is sent back."""
    tool_msgs = [m["content"] for m in messages if m["role"] == "tool"]
    last = tool_msgs[-1] if tool_msgs else ""
    step = sum(1 for m in messages if m["role"] == "assistant")
    page_url = next((u for t in tool_msgs for u in re.findall(r"\| (https://\S+)", t)), None)
    page_id = next((re.match(r"\[(E\d+)\]", t).group(1) for t in tool_msgs if "founded in 2019 by" in t), None)
    if "skeptic reviewed your work" in messages[-1].get("content", "") or (messages[-1]["role"] == "user" and step > 3):
        calls = [_call("update_question", question_id="q3", status="unanswerable", note="no litigation found"),
                 _call("finish", summary="addressed the skeptic")]
    elif step == 0:
        calls = [_call("company_profile")]
    elif step == 1:
        calls = [_call("web_search", query="acme ai founders")]
    elif step == 2:
        calls = [_call("read_page", url=page_url)]
    elif step == 3:  # wrong quote: must be rejected
        calls = [_call("record_claim", question_id="q2", field="founders", statement="Founded by Jane Doe.",
                       value="Jane Doe", evidence_id=page_id, quote="Jane Doe started it alone in a garage")]
    elif step == 4:
        assert last.startswith("REJECTED"), last
        calls = [_call("record_claim", question_id="q2", field="founders", statement="Founded by Jane Doe and John Roe.",
                       value="Jane Doe, John Roe", evidence_id=page_id, quote="founded in 2019 by Jane Doe and John Roe"),
                 _call("record_claim", question_id="q1", field="founded_year", statement="Founded in 2019.", value="2019",
                       evidence_id="E1", quote="Year founded: 2019"),
                 _call("record_claim", question_id="q2", field="headcount", statement="18 employees.", value="18",
                       evidence_id="E1", quote="Employee count: 18"),
                 _call("record_claim", question_id="q2", field="headcount", statement="Team of 50.", value="50",
                       evidence_id=page_id, quote="now has a team of 50 people")]
    elif step == 5:
        calls = [_call("update_question", question_id="q1", status="answered", note="2019"),
                 _call("update_question", question_id="q2", status="answered", note="founders"),
                 _call("finish", summary="done early")]  # q3 is p2 so this is allowed
    else:
        calls = [_call("finish", summary="done")]
    return {"role": "assistant", "content": "", "tool_calls": calls}, "fake:agent"


def test_agent_mode_end_to_end():
    with tempfile.TemporaryDirectory() as d:
        setup_fakes(Path(d))
        SKEPTIC_CALLS["n"] = 0
        llm.chat = fake_chat
        st = pipeline.run_company("Acme AI", "acme.ai", "agent-run", "v1", "agent")
        assert st.phase == "done", st.error
        assert st.mode == "agent" and st.agent_steps >= 6
        assert st.rejected_in_loop == 1 and st.self_corrections == 1, (st.rejected_in_loop, st.self_corrections)
        assert st.round == 2 and len(st.reviews) == 2 and st.reviews[0].verdict == "needs_work"
        assert any(c.field == "headcount" for c in st.conflicts), "18 vs 50 headcount should be flagged"
        assert st.question_status["q3"]["status"] == "unanswerable"
        m = st.metrics
        assert m["skeptic_objections"] == 1 and m["tool_calls"]["record_claim"] == 5
        assert all(c.support != "unchecked" for c in st.claims), "every accepted claim must be judged"


def test_agent_finish_refused_while_priority_questions_open():
    from underwrite.agents.analyst import Toolbox
    from underwrite.models import CompanyState, Plan, Question

    st = CompanyState(run_id="x", company="A", prompts_version="v1", mode="agent",
                      plan=Plan(questions=[Question(id="q1", topic="t", question="?", priority=1)]))
    st.question_status = {"q1": {"status": "open"}}
    box = Toolbox(st)
    assert box.t_finish("bye").startswith("Not yet") and not box.finished
    assert "no accepted claim" in box.t_update_question("q1", "answered", "x")
    box.t_update_question("q1", "unanswerable", "tried 3 searches")
    assert box.t_finish("bye") == "Investigation closed." and box.finished


def test_context_compaction():
    from underwrite.agents.analyst import _compact

    msgs = [{"role": "tool", "tool_call_id": str(i), "content": f"[E{i}] page\n" + "x" * 2000} for i in range(1, 5)]
    assert _compact(msgs, keep=2) == 2
    assert msgs[0]["content"].endswith("<removed>") and msgs[1]["content"].endswith("<removed>")
    assert len(msgs[3]["content"]) > 2000


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS {name}")
