"""Stage orchestration: state tracking, retry/invalidations, finalisation to approval queue."""
import json, time, traceback
from . import config, db, stages, util, resources

ORDER = ["script", "storyboard", "characters", "visuals", "voiceover", "animation", "subtitles", "sound", "assembly", "qc", "metadata", "thumbnail"]
GPU_STAGES = {"visuals"}


def create_project(idea_id=None, idea=None, character_id=None):
    if idea_id:
        row = db.one("SELECT * FROM ideas WHERE id=?", (idea_id,))
        raw = json.loads(row["score_detail"])["raw"]
        raw.update(title=row["title"], logline=row["logline"], hook=row["hook"], genre=row["genre"])
        idea, character_id = raw, row["character_id"]
        db.run("UPDATE ideas SET status='queued' WHERE id=?", (idea_id,))
    pid = db.run("INSERT INTO projects(idea_id,title,concept,character_id,status,settings_snapshot,created_at) VALUES(?,?,?,?,?,?,?)",
                 (idea_id, idea["title"], json.dumps(idea), character_id, "queued", json.dumps(config.load_settings()), time.time()))
    for s in ORDER:
        db.run("INSERT INTO stages(project_id,stage) VALUES(?,?)", (pid, s))
    config.project_dir(pid)
    return pid


def stage_status(pid):
    return {r["stage"]: r for r in db.q("SELECT * FROM stages WHERE project_id=?", (pid,))}


def next_stage(pid):
    st = stage_status(pid)
    return next((s for s in ORDER if st[s]["status"] != "done"), None)


def reset_from(pid, stage):
    """Mark `stage` and everything after as pending (outputs stay on disk; caches decide what is recomputed)."""
    for s in ORDER[ORDER.index(stage):]:
        db.run("UPDATE stages SET status='pending', error=NULL WHERE project_id=? AND stage=?", (pid, s))


def run_stage(pid, stage, scenes=None):
    """Runs one stage in this process. Records status/attempts/duration/errors. Raises on failure."""
    cfg = config.load_settings()
    resources.check_disk(cfg["jobs"]["min_free_disk_gb"])
    t0 = time.time()
    db.run("UPDATE stages SET status='running', attempts=attempts+1, started_at=?, error=NULL WHERE project_id=? AND stage=?", (t0, pid, stage))
    db.run("UPDATE projects SET status='producing' WHERE id=? AND status IN ('queued','planned','failed','revising')", (pid,))
    try:
        detail = stages.STAGE_FUNCS[stage](pid, scenes)
    except Exception as e:
        msg = f"{type(e).__name__}: {e}"
        db.run("UPDATE stages SET status='failed', error=?, finished_at=?, duration_s=? WHERE project_id=? AND stage=?", (msg, time.time(), time.time() - t0, pid, stage))
        db.log_error(pid, stage, msg + "\n" + traceback.format_exc()[-1500:])
        raise
    dur = time.time() - t0
    db.run("UPDATE stages SET status='done', finished_at=?, duration_s=?, detail=? WHERE project_id=? AND stage=?", (time.time(), dur, json.dumps(detail, default=str), pid, stage))
    return detail


def finalize(pid):
    """After all stages: QC gate, cost, then pending_approval. Never sets any approval."""
    qc = util.jread(config.project_dir(pid) / "qc.json", {})
    st = stage_status(pid); total = sum(r["duration_s"] or 0 for r in st.values())
    cfg = config.load_settings()["cost"]
    img = util.jread(config.project_dir(pid) / "scenes" / "backend.json", {}).get("backend")
    watts = cfg["system_watts"] + (cfg["gpu_watts"] * (st["visuals"]["duration_s"] or 0) / max(total, 1) if img == "comfyui" else 0)
    cost = round(total / 3600 * watts / 1000 * cfg["usd_per_kwh"], 4)
    if not qc.get("technical_passed"):
        failed = [c["name"] for c in qc.get("checks", []) if not c["ok"]]
        db.run("UPDATE projects SET status='failed', production_seconds=?, est_cost_usd=? WHERE id=?", (total, cost, pid))
        db.log_error(pid, "qc", "Technical QC failed: " + ", ".join(failed))
        return "failed"
    db.run("UPDATE projects SET status='pending_approval', approval_status='pending', finished_at=?, production_seconds=?, est_cost_usd=? WHERE id=?",
           (time.time(), total, cost, pid))
    db.run("INSERT INTO notifications(message,project_id,created_at) VALUES(?,?,?)", ("Video ready for your approval", pid, time.time()))
    return "pending_approval"


def produce_inprocess(pid, scenes=None):
    """Convenience for CLI/tests: run all remaining stages sequentially."""
    while (s := next_stage(pid)):
        run_stage(pid, s, scenes)
    return finalize(pid)


# ---- revision -> which stage to restart from ----
REVISE_START = {"scenes": "visuals", "narration": "voiceover", "captions": "subtitles", "metadata": None}
