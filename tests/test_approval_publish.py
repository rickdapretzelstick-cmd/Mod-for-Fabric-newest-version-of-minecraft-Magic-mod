import pytest
from fastapi.testclient import TestClient
from factory import db, publish, approval, config, util, jobs
from factory.server import app, automation_token

fake_up = lambda meta, path, vis, at: "YT_FAKE_123"


def test_unapproved_cannot_publish(pending_project):
    with pytest.raises(publish.PublishBlocked):
        publish.publish(pending_project, uploader=fake_up)


def test_approve_then_publish_records_id(pending_project):
    approval.approve(pending_project, "private")
    r = publish.publish(pending_project, uploader=fake_up)
    p = db.one("SELECT * FROM projects WHERE id=?", (pending_project,))
    assert r["youtube_video_id"] == "YT_FAKE_123" and p["upload_status"] == "uploaded" and p["youtube_video_id"] == "YT_FAKE_123"


def test_no_double_upload(pending_project):
    approval.approve(pending_project); publish.publish(pending_project, uploader=fake_up)
    with pytest.raises(publish.PublishBlocked):
        publish.publish(pending_project, uploader=fake_up)


def test_rejected_cannot_publish(pending_project):
    approval.reject(pending_project, "no")
    with pytest.raises(publish.PublishBlocked):
        publish.publish(pending_project, uploader=fake_up)


def test_reject_after_approve_blocks(pending_project):
    approval.approve(pending_project); approval.reject(pending_project)
    with pytest.raises(publish.PublishBlocked):
        publish.publish(pending_project, uploader=fake_up)


def test_modified_video_after_approval_blocked(pending_project):
    approval.approve(pending_project)
    with open(config.project_dir(pending_project) / "final.mp4", "ab") as f:
        f.write(b"x")
    with pytest.raises(publish.PublishBlocked, match="changed"):
        publish.publish(pending_project, uploader=fake_up)


def test_missing_approval_row_is_not_approval(pending_project):
    db.run("UPDATE projects SET status='approved', approval_status='approved', approved_sha256='x' WHERE id=?", (pending_project,))
    with pytest.raises(publish.PublishBlocked):
        publish.publish(pending_project, uploader=fake_up)


def test_no_credentials_blocks_at_boundary(pending_project):
    approval.approve(pending_project)
    if publish.TOKEN.exists(): pytest.skip("real token present")
    with pytest.raises(publish.PublishBlocked, match="not authorised"):
        publish.publish(pending_project)
    assert db.one("SELECT status FROM uploads WHERE project_id=?", (pending_project,))["status"] == "blocked_no_credentials"


def test_public_visibility_disabled_by_default(pending_project):
    with pytest.raises(approval.ApprovalError):
        approval.approve(pending_project, "public")


def test_api_automation_token_cannot_approve(pending_project):
    c = TestClient(app); h = {"X-Automation-Token": automation_token()}
    assert c.post(f"/api/projects/{pending_project}/approve", json={}, headers=h).status_code == 403
    assert c.post(f"/api/projects/{pending_project}/reject", json={}, headers=h).status_code == 403
    assert c.post(f"/api/projects/{pending_project}/approve", json={}).status_code == 200   # dashboard (no token)
    assert c.post(f"/api/auto/projects/{pending_project}/publish").status_code == 401        # n8n route needs token


def test_api_auto_publish_refuses_pending(pending_project):
    c = TestClient(app); h = {"X-Automation-Token": automation_token()}
    assert c.post(f"/api/auto/projects/{pending_project}/publish", headers=h).status_code == 409


def test_revise_resets_stages_and_queues_job(pending_project):
    from factory import pipeline, util
    for s in pipeline.ORDER: db.run("UPDATE stages SET status='done' WHERE project_id=? AND stage=?", (pending_project, s))
    d = config.project_dir(pending_project); util.jwrite(d / "storyboard.json", {"scenes": [{"n": 1, "prompt": "a"}, {"n": 2, "prompt": "b"}]})
    approval.revise(pending_project, "scenes", [2], {"2": "new prompt"})
    st = pipeline.stage_status(pending_project)
    assert st["script"]["status"] == "done" and st["visuals"]["status"] == "pending" and st["thumbnail"]["status"] == "pending"
    assert util.jread(d / "storyboard.json")["scenes"][1]["prompt"] == "new prompt"
    assert db.one("SELECT status FROM jobs WHERE project_id=?", (pending_project,))["status"] == "queued"
    assert db.one("SELECT approval_status FROM projects WHERE id=?", (pending_project,))["approval_status"] == "revise"


def test_restart_recovery_keeps_approvals_and_requeues(pending_project):
    approval.approve(pending_project)
    jid = jobs.enqueue(pending_project, "produce"); db.run("UPDATE jobs SET status='running' WHERE id=?", (jid,))
    db.run("UPDATE stages SET status='running' WHERE project_id=? AND stage='visuals'", (pending_project,))
    jobs.recover()
    assert db.one("SELECT status FROM jobs WHERE id=?", (jid,))["status"] == "queued"
    assert db.one("SELECT status FROM stages WHERE project_id=? AND stage='visuals'", (pending_project,))["status"] == "pending"
    assert db.one("SELECT approval_status FROM projects WHERE id=?", (pending_project,))["approval_status"] == "approved"
