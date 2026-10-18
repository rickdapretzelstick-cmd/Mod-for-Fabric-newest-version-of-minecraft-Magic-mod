"""Human approval. Missing approval is never approval: publication requires an explicit 'approved' row
whose video hash matches the file being uploaded."""
import json, time
from . import config, db, pipeline, util


class ApprovalError(Exception):
    pass


def _proj(pid):
    p = db.one("SELECT * FROM projects WHERE id=?", (pid,))
    if not p:
        raise ApprovalError("No such project")
    return p


def approve(pid, visibility="private", publish_at=None, notes=""):
    p = _proj(pid)
    if p["status"] != "pending_approval":
        raise ApprovalError(f"Project is '{p['status']}', not pending_approval")
    f = config.project_dir(pid) / "final.mp4"
    if not f.exists():
        raise ApprovalError("final.mp4 missing")
    cfg = config.load_settings()["publish"]
    if visibility not in ("private", "unlisted", "public"):
        raise ApprovalError("visibility must be private|unlisted|public")
    if visibility == "public" and not cfg.get("allow_public"):
        raise ApprovalError("Public visibility is disabled (settings publish.allow_public=false). Approve as private/unlisted, then change it on YouTube.")
    sha = util.sha256(f)
    db.run("INSERT INTO approvals(project_id,decision,notes,scope,video_sha256,visibility,publish_at,created_at) VALUES(?,?,?,?,?,?,?,?)",
           (pid, "approved", notes, None, sha, visibility, publish_at, time.time()))
    db.run("UPDATE projects SET status='approved', approval_status='approved', approved_sha256=?, approved_visibility=?, approved_publish_at=? WHERE id=?",
           (sha, visibility, publish_at, pid))
    return {"approved": True, "sha256": sha, "visibility": visibility}


def reject(pid, notes=""):
    p = _proj(pid)
    if p["upload_status"] in ("uploaded",):
        raise ApprovalError("Already uploaded; cannot reject here")
    db.run("INSERT INTO approvals(project_id,decision,notes,created_at) VALUES(?,?,?,?)", (pid, "rejected", notes, time.time()))
    db.run("UPDATE projects SET status='rejected', approval_status='rejected', approved_sha256=NULL WHERE id=?", (pid,))
    db.run("UPDATE jobs SET status='cancelled' WHERE project_id=? AND status='queued'", (pid,))
    return {"rejected": True}


def revise(pid, scope, scenes=None, edits=None, notes=""):
    """scope: scenes | narration | captions | metadata.  edits: {scene_no: text-or-prompt} or {title,description,tags}."""
    p = _proj(pid)
    if p["status"] not in ("pending_approval", "approved", "failed"):
        raise ApprovalError(f"Cannot revise a project in status '{p['status']}'")
    if p["upload_status"] == "uploaded":
        raise ApprovalError("Already uploaded")
    d = config.project_dir(pid); edits = edits or {}; scenes = [int(s) for s in (scenes or [])]
    if scope == "metadata":
        m = util.jread(d / "metadata.json", {})
        for k in ("title", "description", "tags"):
            if k in edits:
                m[k] = edits[k]
        m["edited"] = True; util.jwrite(d / "metadata.json", m)
        start = "thumbnail"   # title is drawn on the thumbnail
    elif scope in ("scenes", "narration", "captions"):
        if not scenes and scope != "captions":
            raise ApprovalError("Specify the scene numbers to revise")
        sb = util.jread(d / "storyboard.json")
        if scope == "scenes":
            for s in sb["scenes"]:
                if s["n"] in scenes:
                    s["seed"] = s.get("seed", 0) + 1000          # new seed = new take, even with no prompt change
                    if str(s["n"]) in edits:
                        s["prompt"] = edits[str(s["n"])]; s["prompt_override"] = True
            util.jwrite(d / "storyboard.json", sb)
        elif scope == "narration":
            sc = util.jread(d / "script.json")
            for s in sb["scenes"] + sc["scenes"]:
                if s["n"] in scenes and str(s["n"]) in edits:
                    s["narration"] = edits[str(s["n"])]
            util.jwrite(d / "storyboard.json", sb); util.jwrite(d / "script.json", sc)
        else:
            ce = util.jread(d / "caption_edits.json", {}); ce.update({str(k): v for k, v in edits.items()}); util.jwrite(d / "caption_edits.json", ce)
        start = REVISE_START[scope]
    else:
        raise ApprovalError("scope must be scenes|narration|captions|metadata")
    db.run("INSERT INTO approvals(project_id,decision,notes,scope,created_at) VALUES(?,?,?,?,?)", (pid, "revise", notes, json.dumps({"scope": scope, "scenes": scenes}), time.time()))
    db.run("UPDATE projects SET status='revising', approval_status='revise', approved_sha256=NULL WHERE id=?", (pid,))
    pipeline.reset_from(pid, start)
    db.run("INSERT INTO jobs(project_id,kind,params,status,created_at) VALUES(?,?,?,?,?)",
           (pid, "produce", json.dumps({"scenes": scenes or None}), "queued", time.time()))
    return {"revising": True, "restart_from": start}


REVISE_START = {"scenes": "visuals", "narration": "voiceover", "captions": "subtitles"}
