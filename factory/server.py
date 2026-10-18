"""Local API + dashboard host. Binds to 127.0.0.1. Approval endpoints refuse the automation token,
so n8n (which holds that token) can queue and produce but can never approve a video."""
import json, secrets, time
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from . import config, db, characters, ideas, jobs, pipeline, approval, publish, resources, util

TOKEN_FILE = config.SECRETS_DIR / "automation_token"
DIST = config.ROOT / "dashboard" / "dist"


def automation_token():
    config.ensure_dirs()
    if not TOKEN_FILE.exists():
        TOKEN_FILE.write_text(secrets.token_urlsafe(32))
    return TOKEN_FILE.read_text().strip()


@asynccontextmanager
async def lifespan(app):
    db.init(); characters.ensure_defaults(); automation_token(); jobs.start()
    yield
    jobs.stop()

app = FastAPI(title="AI Video Factory", lifespan=lifespan)


def human_only(x_automation_token: str | None):
    if x_automation_token:
        raise HTTPException(403, "Automation credentials cannot approve, revise or reject. Use the dashboard.")


def auto_only(x_automation_token: str | None):
    if x_automation_token != automation_token():
        raise HTTPException(401, "Missing/invalid X-Automation-Token (see secrets/automation_token)")


def _fail(e):
    return HTTPException(400, str(e))


def _project_view(p, detail=False):
    pid = p["id"]; d = config.project_dir(pid)
    p = dict(p); p.pop("settings_snapshot", None)
    p["stages"] = pipeline.stage_status(pid)
    p["has_video"] = (d / "final.mp4").exists()
    if detail:
        p["qc"] = util.jread(d / "qc.json"); p["metadata"] = util.jread(d / "metadata.json"); p["storyboard"] = util.jread(d / "storyboard.json")
        p["timeline"] = util.jread(d / "timeline.json"); p["errors"] = db.q("SELECT * FROM errors WHERE project_id=? ORDER BY id DESC LIMIT 50", (pid,))
        p["approvals"] = db.q("SELECT * FROM approvals WHERE project_id=? ORDER BY id DESC", (pid,))
        p["uploads"] = db.q("SELECT * FROM uploads WHERE project_id=? ORDER BY id DESC", (pid,))
        asm = (p["stages"].get("assembly") or {}).get("detail"); p["assembly"] = json.loads(asm) if asm else None
        p["runtime_s"] = (p["timeline"] or {}).get("total")
    return p


@app.get("/api/status")
def status():
    c = {r["status"]: r["n"] for r in db.q("SELECT status, COUNT(*) n FROM projects GROUP BY status")}
    jc = {r["status"]: r["n"] for r in db.q("SELECT status, COUNT(*) n FROM jobs GROUP BY status")}
    from .providers import llm, image, tts
    s = config.load_settings()
    return {"worker_enabled": jobs.enabled(), "projects": c, "jobs": jc, "resources": resources.snapshot(), "quality": s["quality"],
            "providers": {"llm": "ollama" if llm.ollama_available(s["llm"]["ollama_url"]) else "template-fallback",
                          "image": image.pick_backend(), "tts": tts.pick_backend()},
            "youtube_authorised": publish.TOKEN.exists(), "pending_approval": c.get("pending_approval", 0)}


@app.get("/api/projects")
def projects(status: str | None = None):
    rows = db.q("SELECT * FROM projects" + (" WHERE status=?" if status else "") + " ORDER BY id DESC", (status,) if status else ())
    return [_project_view(r) for r in rows]


@app.get("/api/projects/{pid}")
def project_detail(pid: int):
    p = db.one("SELECT * FROM projects WHERE id=?", (pid,))
    if not p: raise HTTPException(404)
    return _project_view(p, True)


@app.get("/media/{pid}/{name:path}")
def media(pid: int, name: str):
    ok = name in ("final.mp4", "thumbnail.jpg", "thumbnail_wide.jpg") or (name.startswith("scenes/s") and name.endswith(".png") and name.count("_") == 0)
    f = config.project_dir(pid) / name
    if not ok or not f.exists(): raise HTTPException(404)
    return FileResponse(f)


@app.get("/charmedia/{cid}/{name}")
def charmedia(cid: str, name: str):
    f = config.CHAR_DIR / cid / name
    if "/" in name or "\\" in name or not f.exists(): raise HTTPException(404)
    return FileResponse(f)


class NewProject(BaseModel):
    idea_id: int


@app.post("/api/projects")
def new_project(b: NewProject):
    pid = pipeline.create_project(idea_id=b.idea_id); return {"id": pid}


@app.post("/api/projects/{pid}/produce")
def produce(pid: int):
    p = db.one("SELECT status FROM projects WHERE id=?", (pid,))
    if not p or p["status"] in ("rejected", "uploaded"): raise HTTPException(400, "Project not producible")
    jobs.enqueue(pid, "produce"); return {"queued": True}


@app.post("/api/projects/{pid}/retry")
def retry(pid: int, from_stage: str | None = None):
    st = pipeline.stage_status(pid); stg = from_stage or next((s for s in pipeline.ORDER if st[s]["status"] != "done"), None)
    if not stg: raise HTTPException(400, "Nothing to retry")
    pipeline.reset_from(pid, stg) if from_stage else None
    db.run("UPDATE projects SET status='queued' WHERE id=?", (pid,)); jobs.enqueue(pid, "produce"); return {"retrying_from": stg}


class Decision(BaseModel):
    visibility: str = "private"
    publish_at: str | None = None
    notes: str = ""


class Revision(BaseModel):
    scope: str
    scenes: list[int] = []
    edits: dict = {}
    notes: str = ""


@app.post("/api/projects/{pid}/approve")
def approve(pid: int, b: Decision, x_automation_token: str | None = Header(None)):
    human_only(x_automation_token)
    try: return approval.approve(pid, b.visibility, b.publish_at, b.notes)
    except approval.ApprovalError as e: raise _fail(e)


@app.post("/api/projects/{pid}/reject")
def reject(pid: int, b: Decision, x_automation_token: str | None = Header(None)):
    human_only(x_automation_token)
    try: return approval.reject(pid, b.notes)
    except approval.ApprovalError as e: raise _fail(e)


@app.post("/api/projects/{pid}/revise")
def revise(pid: int, b: Revision, x_automation_token: str | None = Header(None)):
    human_only(x_automation_token)
    try: return approval.revise(pid, b.scope, b.scenes, b.edits, b.notes)
    except approval.ApprovalError as e: raise _fail(e)


@app.post("/api/projects/{pid}/publish")
def publish_ep(pid: int):
    try: publish.validate(pid)
    except publish.PublishBlocked as e: raise HTTPException(409, str(e))
    if not publish.TOKEN.exists():
        publish._record(pid, "blocked_no_credentials", msg="not authorised")
        raise HTTPException(412, "YouTube not authorised. Run: python scripts/youtube_auth.py")
    jobs.enqueue(pid, "publish"); return {"queued": True}


@app.get("/api/ideas")
def list_ideas(): return db.q("SELECT id,title,logline,hook,genre,character_id,score,duplicate_of,status,created_at FROM ideas ORDER BY id DESC LIMIT 200")


@app.post("/api/ideas/generate")
def gen_ideas(count: int = 6):
    out, be = ideas.generate(count); return {"backend": be, "ideas": out}


@app.get("/api/characters")
def chars(): return characters.list_all()


class CharIn(BaseModel):
    id: str
    name: str
    appearance: str = ""
    clothing: str = ""
    colors: dict = {}
    face: str = ""
    personality: str = ""
    style: str = ""
    seed: int = 1


@app.post("/api/characters")
def char_upsert(c: CharIn): characters.upsert(c.model_dump()); return characters.get(c.id)


@app.get("/api/settings")
def get_settings(): return config.load_settings()


@app.put("/api/settings")
def put_settings(patch: dict):
    if "quality" in patch and patch["quality"] not in config.load_settings()["quality_presets"]: raise HTTPException(400, "unknown quality preset")
    return config.save_settings(patch)


@app.get("/api/jobs")
def list_jobs(): return db.q("SELECT * FROM jobs ORDER BY id DESC LIMIT 100")


@app.get("/api/errors")
def errors(): return db.q("SELECT * FROM errors ORDER BY id DESC LIMIT 200")


@app.get("/api/uploads")
def uploads(): return db.q("SELECT u.*, p.title FROM uploads u LEFT JOIN projects p ON p.id=u.project_id ORDER BY u.id DESC LIMIT 200")


@app.get("/api/analytics")
def analytics(): return {"rows": db.q("SELECT a.*, p.title FROM analytics a LEFT JOIN projects p ON p.id=a.project_id ORDER BY a.id DESC LIMIT 200"), "authorised": publish.TOKEN.exists()}


@app.post("/api/analytics/refresh")
def analytics_refresh():
    try: return publish.fetch_analytics()
    except Exception as e: raise HTTPException(500, str(e))


@app.post("/api/worker/{action}")
def worker(action: str):
    if action not in ("start", "stop"): raise HTTPException(404)
    jobs.set_enabled(action == "start"); return {"worker_enabled": jobs.enabled()}


@app.get("/api/notifications")
def notifs(): return db.q("SELECT * FROM notifications ORDER BY id DESC LIMIT 50")


# ------------- automation (n8n) endpoints: token required -------------
@app.post("/api/auto/ideas/generate")
def auto_ideas(count: int = 8, x_automation_token: str | None = Header(None)):
    auto_only(x_automation_token); out, be = ideas.generate(count)
    min_score = config.load_settings()["queue"]["idea_min_score"]
    return {"backend": be, "ideas": out, "min_score": min_score}


@app.post("/api/auto/projects")
def auto_new(b: NewProject, x_automation_token: str | None = Header(None)):
    auto_only(x_automation_token)
    pend = db.one("SELECT COUNT(*) n FROM projects WHERE status IN ('queued','producing','pending_approval','revising')")["n"]
    if pend >= config.load_settings()["queue"]["max_pending_approval"]:
        raise HTTPException(429, "Queue full: approve/reject existing videos first")
    return {"id": pipeline.create_project(idea_id=b.idea_id)}


@app.post("/api/auto/projects/{pid}/stages/{stage}/run")
def auto_stage(pid: int, stage: str, wait: bool = True, force: bool = False, timeout: int = 3600, x_automation_token: str | None = Header(None)):
    auto_only(x_automation_token)
    if stage not in pipeline.ORDER: raise HTTPException(404, "unknown stage")
    st = pipeline.stage_status(pid).get(stage)
    if st and st["status"] == "done" and not force: return {"skipped": "already done"}
    if force: pipeline.reset_from(pid, stage)
    jid = jobs.enqueue(pid, "produce", {"stage": stage})
    t0 = time.time()
    while wait and time.time() - t0 < timeout:
        j = db.one("SELECT status,error FROM jobs WHERE id=?", (jid,))
        if j["status"] == "done": return {"stage": stage, "status": "done"}
        if j["status"] in ("failed", "cancelled"): raise HTTPException(500, j["error"] or j["status"])
        time.sleep(1.5)
    return {"job": jid, "status": "queued"}


@app.post("/api/auto/projects/{pid}/finalize")
def auto_final(pid: int, x_automation_token: str | None = Header(None)):
    auto_only(x_automation_token)
    if pipeline.next_stage(pid): raise HTTPException(409, f"Stage {pipeline.next_stage(pid)} not complete")
    return {"result": pipeline.finalize(pid)}


@app.get("/api/auto/queue/next")
def auto_next(x_automation_token: str | None = Header(None)):
    auto_only(x_automation_token)
    r = db.one("SELECT id FROM projects WHERE status='queued' ORDER BY id LIMIT 1"); return {"project_id": r["id"] if r else None}


@app.get("/api/auto/approvals/pending")
def auto_pending(x_automation_token: str | None = Header(None)):
    auto_only(x_automation_token)
    return db.q("SELECT id,title FROM projects WHERE status='pending_approval'")


@app.get("/api/auto/publish/ready")
def auto_ready(x_automation_token: str | None = Header(None)):
    auto_only(x_automation_token)
    return db.q("SELECT id,title FROM projects WHERE approval_status='approved' AND status='approved' AND youtube_video_id IS NULL")


@app.post("/api/auto/projects/{pid}/publish")
def auto_publish(pid: int, x_automation_token: str | None = Header(None)):
    auto_only(x_automation_token)
    try: return publish.publish(pid)      # same hard gates; refuses unapproved/rejected/duplicate
    except publish.PublishBlocked as e: raise HTTPException(409, str(e))


@app.post("/api/auto/analytics/refresh")
def auto_an(x_automation_token: str | None = Header(None)):
    auto_only(x_automation_token); return publish.fetch_analytics()


@app.post("/api/auto/notify")
def auto_notify(b: dict, x_automation_token: str | None = Header(None)):
    auto_only(x_automation_token)
    db.run("INSERT INTO notifications(message,project_id,created_at) VALUES(?,?,?)", (str(b.get("message", ""))[:300], b.get("project_id"), time.time())); return {"ok": True}


if DIST.exists():
    app.mount("/", StaticFiles(directory=DIST, html=True), name="dashboard")
