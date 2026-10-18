"""YouTube publishing via the official Data API with user-authorised OAuth. Hard gates before any upload."""
import json, time
from . import config, db, util
from .stages import pdir

TOKEN = config.SECRETS_DIR / "youtube_token.json"
CLIENT = config.SECRETS_DIR / "client_secret.json"


class PublishBlocked(Exception):
    pass


def _record(pid, status, vid=None, vis=None, msg=""):
    db.run("INSERT INTO uploads(project_id,status,youtube_video_id,visibility,message,created_at) VALUES(?,?,?,?,?,?)", (pid, status, vid, vis, msg, time.time()))


def validate(pid):
    """All gates except credentials. Raises PublishBlocked with the reason."""
    p = db.one("SELECT * FROM projects WHERE id=?", (pid,))
    if not p:
        raise PublishBlocked("No such project")
    if p["approval_status"] != "approved" or p["status"] not in ("approved", "uploading"):
        raise PublishBlocked(f"Not approved (approval_status={p['approval_status']}, status={p['status']})")
    ap = db.one("SELECT * FROM approvals WHERE project_id=? ORDER BY id DESC LIMIT 1", (pid,))
    if not ap or ap["decision"] != "approved":
        raise PublishBlocked("Latest approval record is not 'approved'")
    f = pdir(pid) / "final.mp4"
    if not f.exists():
        raise PublishBlocked("final.mp4 missing")
    sha = util.sha256(f)
    if not (sha == p["approved_sha256"] == ap["video_sha256"]):
        raise PublishBlocked("Video file changed since it was approved; re-approval required")
    pr = util.ffprobe(f)
    if not any(s["codec_type"] == "video" and s["codec_name"] == "h264" for s in pr["streams"]):
        raise PublishBlocked("final.mp4 is not valid H.264")
    if p["youtube_video_id"] or p["upload_status"] in ("uploaded", "uploading"):
        raise PublishBlocked(f"Already uploaded or in progress (id={p['youtube_video_id']})")
    return p, ap, f


def _service():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    scopes = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.readonly"]
    creds = Credentials.from_authorized_user_file(str(TOKEN), scopes)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request()); TOKEN.write_text(creds.to_json())
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def youtube_upload(meta, path, visibility, publish_at):
    from googleapiclient.http import MediaFileUpload
    yt = _service()
    status = {"privacyStatus": "private" if publish_at else visibility, "selfDeclaredMadeForKids": bool(meta.get("made_for_kids", False)),
              "containsSyntheticMedia": bool(meta.get("contains_synthetic_media", True))}
    if publish_at:
        status["publishAt"] = publish_at
    body = {"snippet": {"title": meta["title"][:100], "description": meta["description"], "tags": meta.get("tags", []), "categoryId": meta.get("category_id", "24")},
            "status": status}
    req = yt.videos().insert(part="snippet,status", body=body, media_body=MediaFileUpload(str(path), mimetype="video/mp4", resumable=True, chunksize=8 * 1024 * 1024))
    resp = None
    while resp is None:
        _, resp = req.next_chunk()
    vid = resp["id"]
    chk = yt.videos().list(part="status", id=vid).execute()
    if not chk.get("items"):
        raise RuntimeError("Upload returned an id but videos.list could not confirm it")
    return vid


def publish(pid, uploader=None):
    """uploader(meta, path, visibility, publish_at) -> video_id. Defaults to the real YouTube API."""
    p, ap, f = validate(pid)
    if uploader is None and not TOKEN.exists():
        _record(pid, "blocked_no_credentials", msg="Run scripts/youtube_auth.py to authorise")
        raise PublishBlocked("YouTube not authorised yet. Put client_secret.json in secrets/ and run: python scripts/youtube_auth.py")
    # atomic claim prevents double upload from two concurrent callers
    if db.run_count("UPDATE projects SET upload_status='uploading', status='uploading' WHERE id=? AND upload_status IN ('none','failed') AND youtube_video_id IS NULL", (pid,)) != 1:
        raise PublishBlocked("Another upload already claimed this project")
    meta = util.jread(pdir(pid) / "metadata.json")
    vis = ap["visibility"] or "private"
    try:
        vid = (uploader or youtube_upload)(meta, f, vis, ap["publish_at"])
    except Exception as e:
        db.run("UPDATE projects SET upload_status='failed', status='approved' WHERE id=?", (pid,))
        _record(pid, "failed", vis=vis, msg=str(e)[:500]); db.log_error(pid, "publish", e)
        raise
    db.run("UPDATE projects SET upload_status='uploaded', status='uploaded', youtube_video_id=? WHERE id=?", (vid, pid))
    _record(pid, "uploaded", vid, vis, "confirmed")
    return {"youtube_video_id": vid, "visibility": vis}


def fetch_analytics():
    """Pull public stats for uploaded videos via the Data API (needs authorisation). Records real numbers only."""
    rows = db.q("SELECT id,youtube_video_id FROM projects WHERE youtube_video_id IS NOT NULL")
    if not rows or not TOKEN.exists():
        return {"updated": 0, "reason": "no uploaded videos or not authorised"}
    yt = _service(); ids = {r["youtube_video_id"]: r["id"] for r in rows}
    resp = yt.videos().list(part="statistics", id=",".join(ids)).execute()
    for it in resp.get("items", []):
        s = it["statistics"]
        db.run("INSERT INTO analytics(project_id,youtube_video_id,views,likes,comments,avg_view_pct,fetched_at) VALUES(?,?,?,?,?,?,?)",
               (ids[it["id"]], it["id"], int(s.get("viewCount", 0)), int(s.get("likeCount", 0)), int(s.get("commentCount", 0)), None, time.time()))
    return {"updated": len(resp.get("items", []))}
