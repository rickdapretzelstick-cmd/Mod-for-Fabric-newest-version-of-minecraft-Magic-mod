from conftest import make_video
from factory import db, pipeline, config, jobs, stages, util


def _qc_for(video_kwargs):
    pid = pipeline.create_project(idea={"title": "T", "logline": "L", "hook": "H"})
    d = config.project_dir(pid); make_video(d / "final.mp4", **video_kwargs)
    util.jwrite(d / "storyboard.json", {"scenes": []})
    stages.qc(pid); return {c["name"]: c["ok"] for c in util.jread(d / "qc.json")["checks"]}, util.jread(d / "qc.json")


def test_qc_catches_wrong_resolution_no_audio_and_blank():
    r, full = _qc_for(dict(w=720, h=1280, audio=False, color=True))
    assert not r["resolution"] and not r["audio_present_aac"] and not r["no_blank_video"] and not full["technical_passed"]
    assert "NOT ASSESSED" in full["creative_review"]


def test_qc_catches_short_duration():
    r, _ = _qc_for(dict(seconds=10))
    assert not r["duration_in_range"] and r["resolution"]


def test_failed_qc_never_reaches_approval_queue():
    pid = pipeline.create_project(idea={"title": "T", "logline": "L", "hook": "H"})
    d = config.project_dir(pid); make_video(d / "final.mp4", w=720, h=1280); stages.qc(pid)
    assert pipeline.finalize(pid) == "failed"
    assert db.one("SELECT approval_status,status FROM projects WHERE id=?", (pid,))["status"] == "failed"


def test_worker_runs_stage_in_subprocess_and_retries_failure():
    pid = pipeline.create_project(idea={"title": "T", "logline": "L", "hook": "H", "place": "a forest", "secret": "s", "twist": "t"})
    jid = jobs.enqueue(pid, "produce", {"stage": "script"}); jobs.run_job(db.one("SELECT * FROM jobs WHERE id=?", (jid,)))
    assert db.one("SELECT status FROM jobs WHERE id=?", (jid,))["status"] == "done"
    assert db.one("SELECT status FROM stages WHERE project_id=? AND stage='script'", (pid,))["status"] == "done"
    assert (config.project_dir(pid) / "script.json").exists()
    # failing stage (storyboard needs script.json which exists; voiceover needs storyboard visuals -> use missing-file stage)
    pid2 = pipeline.create_project(idea={"title": "T", "logline": "L", "hook": "H"})
    jid2 = jobs.enqueue(pid2, "produce", {"stage": "storyboard"})
    config.save_settings({"jobs": {"max_attempts": 2}})
    try:
        jobs.run_job(db.one("SELECT * FROM jobs WHERE id=?", (jid2,)))
    finally:
        (config.CONFIG_DIR / "settings.json").unlink(missing_ok=True)
    j = db.one("SELECT * FROM jobs WHERE id=?", (jid2,))
    assert j["status"] == "failed" and j["attempts"] == 2 and db.q("SELECT * FROM errors WHERE project_id=?", (pid2,))
    assert db.one("SELECT status FROM projects WHERE id=?", (pid2,))["status"] == "failed"
