"""Underwrite Live: anyone can ask the agents to research a company from their browser.

One job runs at a time (a memo takes ~5 minutes and the model and data APIs are rate-limited); visitors see their
place in the queue, then the agents' trail live as it happens. Companies researched in the last 30 days open
instantly. Limits protect the free credits: a few new memos per visitor per day, a daily cap for the whole site,
and the Crustdata balance floor. Interrupted jobs resume from their last checkpoint when the server restarts.

Run: `underwrite serve` (behind Caddy/HTTPS on the EC2 box, see deploy/).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import threading
import time
import uuid
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse

from . import obs
from .config import ROOT, settings
from .models import CompanyState
from .pipeline import company_dir, run_company, slug

UI = Path(__file__).parent / "webui"
STORE = settings.runs_dir / "web"
JOBS_PATH = STORE / "jobs.json"
PER_VISITOR = int(os.environ.get("UW_WEB_PER_VISITOR", "2"))
DAILY_CAP = int(os.environ.get("UW_WEB_DAILY_CAP", "25"))
MAX_QUEUE = int(os.environ.get("UW_WEB_MAX_QUEUE", "8"))
FRESH_DAYS = 30
SALT = os.environ.get("UW_WEB_SALT", "underwrite-live")
COMPANY_RE = re.compile(r"^[\w .,&'()+-]{2,60}$")
DOMAIN_RE = re.compile(r"^(?=.{4,80}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}$")

_lock = threading.Lock()
_wake = threading.Event()


# --- jobs ------------------------------------------------------------------------------------------------------

def _load() -> list[dict]:
    if JOBS_PATH.exists():
        try:
            return json.loads(JOBS_PATH.read_text(encoding="utf-8"))
        except ValueError:
            return []
    return []


_jobs: list[dict] = _load()


def _save() -> None:
    STORE.mkdir(parents=True, exist_ok=True)
    tmp = JOBS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(_jobs, indent=1), encoding="utf-8")
    tmp.replace(JOBS_PATH)


def _today(ts: float) -> bool:
    return time.strftime("%Y-%m-%d", time.gmtime(ts)) == time.strftime("%Y-%m-%d", time.gmtime())


def _job(jid: str) -> dict:
    j = next((x for x in _jobs if x["id"] == jid), None)
    if not j:
        raise HTTPException(404, "no such job")
    return j


def _state(j: dict) -> CompanyState | None:
    p = company_dir(j["run_id"], j["company"]) / "state.json"
    if p.exists():
        try:
            return CompanyState.model_validate_json(p.read_text(encoding="utf-8"))
        except ValueError:
            return None
    return None


def _worker() -> None:
    """Run queued jobs one at a time, forever. A job left 'running' by a restart resumes from its checkpoint."""
    with _lock:
        for j in _jobs:
            if j["status"] == "running":
                j["status"] = "queued"
        _save()
    while True:
        with _lock:
            j = next((x for x in sorted(_jobs, key=lambda x: x["created"]) if x["status"] == "queued"), None)
            if j:
                j["status"], j["started"] = "running", time.time()
                _save()
        if not j:
            _wake.wait(30)
            _wake.clear()
            continue
        try:
            st = run_company(j["company"], j["domain"], j["run_id"])
            ok = st.phase == "done" and (company_dir(j["run_id"], j["company"]) / "memo.html").exists()
            with _lock:
                j["status"] = "done" if ok else "failed"
                j["error"] = None if ok else (st.error or f"stopped at {st.phase}")
                j["finished"] = time.time()
                _save()
        except Exception as e:  # noqa: BLE001 - one bad job must not stop the queue
            with _lock:
                j["status"], j["error"], j["finished"] = "failed", f"{type(e).__name__}: {e}", time.time()
                _save()


# --- memos ------------------------------------------------------------------------------------------------------

_memo_cache: dict = {"t": 0.0, "items": {}}


def _memos() -> dict[str, dict]:
    """Every finished dossier this server can show: published ones (docs/memos) and ones written here."""
    if time.time() - _memo_cache["t"] < 20:
        return _memo_cache["items"]
    items: dict[str, dict] = {}
    index = ROOT / "docs" / "memos" / "index.json"
    if index.exists():
        for s, e in json.loads(index.read_text(encoding="utf-8")).items():
            if (ROOT / "docs" / "memos" / s / "index.html").exists():
                items[s] = {"slug": s, "company": e["company"], "domain": e.get("domain"), "finished_at": e["finished_at"],
                            "claims": e.get("claims", 0), "verified": e.get("verified", 0),
                            "conflicts": e.get("conflicts", 0), "recommendation": e.get("recommendation", ""),
                            "dir": str(ROOT / "docs" / "memos" / s), "html": "index.html"}
    for p in settings.runs_dir.glob("*/*/state.json"):
        if not (p.parent / "memo.html").exists():
            continue
        try:
            st = CompanyState.model_validate_json(p.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if st.phase != "done":
            continue
        s = slug(st.company)
        if s in items and items[s]["finished_at"] >= (st.finished_at or 0):
            continue
        items[s] = {"slug": s, "company": st.company, "domain": st.domain, "finished_at": st.finished_at or 0,
                    "claims": len(st.claims), "verified": sum(c.support in ("supported", "partial") for c in st.claims),
                    "conflicts": len(st.conflicts), "recommendation": st.memo.recommendation if st.memo else "",
                    "dir": str(p.parent), "html": "memo.html"}
    _memo_cache.update(t=time.time(), items=items)
    return items


# --- app --------------------------------------------------------------------------------------------------------

app = FastAPI(title="Underwrite Live", docs_url=None, redoc_url=None)


@app.on_event("startup")
def _startup() -> None:
    settings.mode = "agent"
    obs.setup(tags=["cmd:serve", f"prompts:{settings.prompts_version}", "mode:agent", "web"])
    threading.Thread(target=_worker, daemon=True, name="underwrite-worker").start()


def _visitor(request: Request) -> str:
    ip = request.client.host if request.client else "?"
    fwd = request.headers.get("x-forwarded-for")
    if fwd and ip in ("127.0.0.1", "::1"):  # behind our own reverse proxy
        ip = fwd.split(",")[0].strip()
    return hashlib.sha256(f"{SALT}|{ip}".encode()).hexdigest()[:16]


def _norm_domain(raw: str) -> str | None:
    d = (raw or "").strip().lower()
    d = re.sub(r"^[a-z]+://", "", d).split("/")[0].split("?")[0].split(":")[0]
    d = d.removeprefix("www.")
    if not d:
        return None
    if not DOMAIN_RE.match(d):
        raise HTTPException(400, "That website doesn't look right. Use something like linear.app")
    return d


@app.get("/")
def index():
    return FileResponse(UI / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/api/state")
def state(request: Request):
    me = _visitor(request)
    with _lock:
        today = [j for j in _jobs if _today(j["created"]) and not j.get("cached")]
        running = next((j for j in _jobs if j["status"] == "running"), None)
        queued = sum(1 for j in _jobs if j["status"] == "queued")
        mine = sum(1 for j in today if j["visitor"] == me)
    memos = sorted(_memos().values(), key=lambda m: -m["finished_at"])
    return {"running": {"company": running["company"], "id": running["id"]} if running else None, "queued": queued,
            "today": len(today), "daily_cap": DAILY_CAP, "left_for_you": max(0, PER_VISITOR - mine),
            "per_visitor": PER_VISITOR, "prompts": settings.prompts_version,
            "memos": [{k: m[k] for k in ("slug", "company", "domain", "finished_at", "claims", "verified", "conflicts",
                                         "recommendation")} for m in memos[:30]]}


@app.post("/api/research")
def research(request: Request, body: dict = Body(...)):
    company = re.sub(r"\s+", " ", str(body.get("company", ""))).strip()
    if not COMPANY_RE.match(company):
        raise HTTPException(400, "Type the company's name (2 to 60 letters).")
    domain = _norm_domain(str(body.get("domain", "")))
    s = slug(company)
    m = _memos().get(s)
    if m and time.time() - m["finished_at"] < FRESH_DAYS * 86400:
        return {"cached": True, "url": f"/memo/{s}/", "company": m["company"],
                "finished_at": m["finished_at"]}
    me = _visitor(request)
    with _lock:
        live = next((j for j in _jobs if j["slug"] == s and j["status"] in ("queued", "running")), None)
        if live:
            return {"job": live["id"], "joined": True}
        today = [j for j in _jobs if _today(j["created"]) and not j.get("cached")]
        if sum(1 for j in today if j["visitor"] == me) >= PER_VISITOR:
            raise HTTPException(429, f"You've used your {PER_VISITOR} free memos for today. Come back tomorrow, "
                                     "or open one of the memos below.")
        if len(today) >= DAILY_CAP:
            raise HTTPException(429, "Today's free memos are all used. The counter resets at midnight UTC.")
        if sum(1 for j in _jobs if j["status"] == "queued") >= MAX_QUEUE:
            raise HTTPException(429, "The queue is full right now. Try again in a few minutes.")
    try:
        from .tools.crustdata import balance

        left = balance()
    except Exception:  # noqa: BLE001
        left = None
    if left is not None and left < settings.min_credit_balance:
        raise HTTPException(503, "The research credits for the free demo are used up. Thanks for trying it!")
    jid = uuid.uuid4().hex[:10]
    job = {"id": jid, "company": company, "domain": domain, "slug": s, "visitor": me, "created": time.time(),
           "status": "queued", "run_id": f"web-{time.strftime('%Y%m%d')}-{jid}", "started": None, "finished": None,
           "error": None}
    with _lock:
        _jobs.append(job)
        _save()
    _wake.set()
    return {"job": jid}


def _job_view(j: dict) -> dict:
    with _lock:
        queued = sorted((x for x in _jobs if x["status"] == "queued"), key=lambda x: x["created"])
        pos = next((i + 1 for i, x in enumerate(queued) if x["id"] == j["id"]), 0)
        busy = any(x["status"] == "running" for x in _jobs)
    st = _state(j)
    out = {"id": j["id"], "company": j["company"], "domain": j["domain"], "status": j["status"], "error": j["error"],
           "position": pos + (1 if busy and pos else 0), "created": j["created"], "started": j["started"],
           "finished": j["finished"], "url": f"/memo/{j['slug']}/" if j["status"] == "done" else None}
    if st:
        out |= {"phase": st.phase, "claims": len(st.claims),
                "verified": sum(c.support in ("supported", "partial") for c in st.claims),
                "rejected": sum(c.support == "unsupported" for c in st.claims) + st.rejected_in_loop,
                "conflicts": len(st.conflicts), "steps": st.agent_steps, "searches": len(st.searched),
                "pages": len(st.fetched), "self_corrections": st.self_corrections,
                "objections": sum(len(r.objections) for r in st.reviews),
                "questions": len(st.question_status),
                "answered": sum(1 for q in st.question_status.values() if q.get("status") == "answered")}
    return out


@app.get("/api/jobs/{jid}")
def job(jid: str):
    return _job_view(_job(jid))


@app.get("/api/jobs/{jid}/stream")
async def stream(jid: str, since: int = 0):
    """Server-sent events: every line the agents log (search, read, claim, rejection, skeptic objection, recovery),
    plus the job's state every couple of seconds, until the memo is written."""
    j = _job(jid)

    async def gen():
        line, last_view = max(0, since), 0.0
        yield "retry: 2000\n\n"
        while True:
            events = company_dir(j["run_id"], j["company"]) / "events.jsonl"
            if events.exists():
                rows = events.read_text(encoding="utf-8", errors="replace").splitlines()
                for raw in rows[line:]:
                    try:
                        ev = json.loads(raw)
                    except ValueError:
                        continue
                    yield f"data: {json.dumps({'type': 'event', 'i': line, 'kind': ev.get('kind'), 'msg': ev.get('msg'), 't': ev.get('t')})}\n\n"
                    line += 1
            if time.time() - last_view > 2:
                view = _job_view(j)
                last_view = time.time()
                yield f"data: {json.dumps({'type': 'job', **view})}\n\n"
                if view["status"] in ("done", "failed"):
                    return
            await asyncio.sleep(1)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/memo/{s}/")
def memo(s: str):
    m = _memos().get(s)
    if not m:
        raise HTTPException(404, "No dossier for that company yet.")
    return FileResponse(Path(m["dir"]) / m["html"], headers={"Cache-Control": "no-cache"})


@app.get("/memo/{s}/{name}")
def memo_file(s: str, name: str):
    m = _memos().get(s)
    if not m or name not in ("memo.pdf", "memo.png"):
        raise HTTPException(404)
    f = Path(m["dir"]) / name
    if not f.exists():
        raise HTTPException(404)
    return FileResponse(f)


@app.get("/healthz")
def healthz():
    return {"ok": True}
