"""Persistent job queue + single sequential worker. Each stage runs in its own subprocess so that
(a) timeouts can really kill it, (b) GPU memory is released when the process exits, (c) a crash cannot take down the API."""
import json, subprocess, sys, threading, time
from . import config, db, pipeline, resources, publish

_proc = {"p": None}
_stop = threading.Event()


def enqueue(project_id, kind, params=None):
    return db.run("INSERT INTO jobs(project_id,kind,params,status,created_at) VALUES(?,?,?,?,?)",
                  (project_id, kind, json.dumps(params or {}), "queued", time.time()))


def _kill_orphans():
    """A hard-killed server can leave its stage subprocess running; kill it so two writers never touch one project."""
    import psutil
    for pid in db.kv_get("stage_pids", []):
        try:
            pr = psutil.Process(pid)
            if "factory" in " ".join(pr.cmdline()) and "stage" in pr.cmdline():
                pr.kill()
        except Exception:
            pass
    db.kv_set("stage_pids", [])


def recover():
    """After a crash/restart: running jobs go back to queued; half-finished stages go back to pending."""
    _kill_orphans()
    db.run("UPDATE jobs SET status='queued' WHERE status='running'")
    db.run("UPDATE stages SET status='pending' WHERE status='running'")
    db.run("UPDATE projects SET status='queued' WHERE status='producing'")
    db.run("UPDATE projects SET upload_status='failed', status='approved' WHERE upload_status='uploading' AND youtube_video_id IS NULL")


def enabled():
    return db.kv_get("worker_enabled", True)


def set_enabled(v):
    db.kv_set("worker_enabled", bool(v))
    if not v and _proc["p"]:
        try: _proc["p"].kill()      # job returns to queue via the loop below
        except Exception: pass


def run_stage_subprocess(pid, stage, scenes, timeout, job_id):
    log = config.LOG_DIR / f"job_{job_id}.log"
    cmd = [sys.executable, "-m", "factory", "stage", str(pid), stage] + (["--scenes", ",".join(map(str, scenes))] if scenes else [])
    with open(log, "a") as lf:
        lf.write(f"\n=== {time.ctime()} {stage}\n"); lf.flush()
        p = subprocess.Popen(cmd, stdout=lf, stderr=subprocess.STDOUT, cwd=str(config.ROOT)); _proc["p"] = p
        db.kv_set("stage_pids", [p.pid])
        try:
            rc = p.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            p.kill(); p.wait()
            db.run("UPDATE stages SET status='failed', error=? WHERE project_id=? AND stage=?", (f"Timed out after {timeout}s", pid, stage))
            db.log_error(pid, stage, f"Timed out after {timeout}s")
            return "timeout"
        finally:
            _proc["p"] = None; db.kv_set("stage_pids", [])
    return "ok" if rc == 0 else ("killed" if rc < 0 else "error")


def run_job(job):
    cfg = config.load_settings()["jobs"]; jid, pid = job["id"], job["project_id"]; params = json.loads(job["params"] or "{}")
    if job["kind"] == "publish":
        try:
            publish.publish(pid)
        except Exception as e:
            db.run("UPDATE jobs SET status='failed', error=?, finished_at=? WHERE id=?", (str(e)[:500], time.time(), jid)); return
        db.run("UPDATE jobs SET status='done', finished_at=? WHERE id=?", (time.time(), jid)); return
    if job["kind"] == "ideas":
        from . import ideas
        ideas.generate(params.get("count", 6)); db.run("UPDATE jobs SET status='done', finished_at=? WHERE id=?", (time.time(), jid)); return
    scenes = params.get("scenes"); only = params.get("stage")
    while True:
        stg = only or pipeline.next_stage(pid)
        if stg is None:
            pipeline.finalize(pid); db.run("UPDATE jobs SET status='done', finished_at=? WHERE id=?", (time.time(), jid)); return
        ok = False
        for attempt in range(1, cfg["max_attempts"] + 1):
            if not enabled():
                db.run("UPDATE jobs SET status='queued' WHERE id=?", (jid,)); return
            r = run_stage_subprocess(pid, stg, scenes, cfg["stage_timeout_s"], jid)
            if r == "ok":
                ok = True; break
            if r == "killed" and not enabled():
                db.run("UPDATE stages SET status='pending' WHERE project_id=? AND stage=?", (pid, stg))
                db.run("UPDATE jobs SET status='queued' WHERE id=?", (jid,)); return
            db.run("UPDATE jobs SET attempts=attempts+1 WHERE id=?", (jid,)); time.sleep(2)
        if not ok:
            err = (db.one("SELECT error FROM stages WHERE project_id=? AND stage=?", (pid, stg)) or {}).get("error")
            db.run("UPDATE jobs SET status='failed', error=?, finished_at=? WHERE id=?", (f"{stg}: {err}", time.time(), jid))
            db.run("UPDATE projects SET status='failed' WHERE id=?", (pid,)); return
        if only:
            # a single-stage job (n8n step) must not leave the project looking busy: put it back in the queue
            db.run("UPDATE projects SET status='queued' WHERE id=? AND status='producing'", (pid,))
            db.run("UPDATE jobs SET status='done', finished_at=? WHERE id=?", (time.time(), jid)); return


def loop():
    while not _stop.is_set():
        try:
            if enabled():
                job = db.one("SELECT * FROM jobs WHERE status='queued' ORDER BY id LIMIT 1")
                if job:
                    # never process jobs for rejected projects
                    p = db.one("SELECT status FROM projects WHERE id=?", (job["project_id"],)) if job["project_id"] else None
                    if p and p["status"] == "rejected":
                        db.run("UPDATE jobs SET status='cancelled' WHERE id=?", (job["id"],)); continue
                    db.run("UPDATE jobs SET status='running', started_at=? WHERE id=?", (time.time(), job["id"]))
                    run_job(job); resources.cleanup_tmp(); continue
        except Exception as e:
            db.log_error(None, "worker", repr(e))
        _stop.wait(config.load_settings()["jobs"]["poll_s"])


def start():
    recover(); _stop.clear()
    t = threading.Thread(target=loop, daemon=True, name="factory-worker"); t.start(); return t


def stop():
    _stop.set()
