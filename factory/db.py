"""SQLite storage. WAL mode so the API server, worker and stage subprocesses can share it."""
import json, sqlite3, time, threading
from contextlib import contextmanager
from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS ideas(
  id INTEGER PRIMARY KEY, title TEXT, logline TEXT, hook TEXT, genre TEXT, character_id TEXT,
  score REAL, score_detail TEXT, fingerprint TEXT, duplicate_of INTEGER, status TEXT DEFAULT 'new',
  created_at REAL);
CREATE TABLE IF NOT EXISTS projects(
  id INTEGER PRIMARY KEY, idea_id INTEGER, title TEXT, concept TEXT, character_id TEXT,
  status TEXT DEFAULT 'planned',            -- planned|queued|producing|pending_approval|revising|failed|rejected|approved|uploaded
  approval_status TEXT DEFAULT 'pending',   -- pending|approved|revise|rejected   (NULL/missing is NEVER approval)
  approved_sha256 TEXT, approved_visibility TEXT, approved_publish_at TEXT,
  upload_status TEXT DEFAULT 'none',        -- none|uploading|uploaded|failed
  youtube_video_id TEXT, settings_snapshot TEXT, notes TEXT,
  created_at REAL, finished_at REAL, production_seconds REAL DEFAULT 0, est_cost_usd REAL DEFAULT 0,
  final_sha256 TEXT);
CREATE TABLE IF NOT EXISTS stages(
  project_id INTEGER, stage TEXT, status TEXT DEFAULT 'pending', attempts INTEGER DEFAULT 0,
  error TEXT, started_at REAL, finished_at REAL, duration_s REAL DEFAULT 0, detail TEXT,
  PRIMARY KEY(project_id, stage));
CREATE TABLE IF NOT EXISTS jobs(
  id INTEGER PRIMARY KEY, project_id INTEGER, kind TEXT, params TEXT DEFAULT '{}',
  status TEXT DEFAULT 'queued', attempts INTEGER DEFAULT 0, error TEXT, created_at REAL,
  started_at REAL, finished_at REAL);
CREATE TABLE IF NOT EXISTS approvals(
  id INTEGER PRIMARY KEY, project_id INTEGER, decision TEXT, notes TEXT, scope TEXT,
  video_sha256 TEXT, visibility TEXT, publish_at TEXT, created_at REAL);
CREATE TABLE IF NOT EXISTS errors(
  id INTEGER PRIMARY KEY, project_id INTEGER, stage TEXT, message TEXT, created_at REAL);
CREATE TABLE IF NOT EXISTS uploads(
  id INTEGER PRIMARY KEY, project_id INTEGER, status TEXT, youtube_video_id TEXT, visibility TEXT,
  message TEXT, created_at REAL);
CREATE TABLE IF NOT EXISTS analytics(
  id INTEGER PRIMARY KEY, project_id INTEGER, youtube_video_id TEXT, views INTEGER, likes INTEGER,
  comments INTEGER, avg_view_pct REAL, fetched_at REAL);
CREATE TABLE IF NOT EXISTS characters(
  id TEXT PRIMARY KEY, name TEXT, appearance TEXT, clothing TEXT, colors TEXT, face TEXT,
  personality TEXT, style TEXT, seed INTEGER, refs TEXT DEFAULT '[]', created_at REAL);
CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY, message TEXT, project_id INTEGER, created_at REAL);
"""

_lock = threading.Lock()


def connect() -> sqlite3.Connection:
    config.ensure_dirs()
    c = sqlite3.connect(config.DB_PATH, timeout=30, isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    return c


def init():
    with connect() as c:
        c.executescript(SCHEMA)


@contextmanager
def tx():
    c = connect()
    try:
        c.execute("BEGIN IMMEDIATE")
        yield c
        c.execute("COMMIT")
    except Exception:
        c.execute("ROLLBACK")
        raise
    finally:
        c.close()


def q(sql, args=()):
    c = connect()
    try:
        return [dict(r) for r in c.execute(sql, args).fetchall()]
    finally:
        c.close()


def one(sql, args=()):
    r = q(sql, args)
    return r[0] if r else None


def run(sql, args=()):
    c = connect()
    try:
        cur = c.execute(sql, args)
        return cur.lastrowid
    finally:
        c.close()


def kv_get(k, default=None):
    r = one("SELECT v FROM kv WHERE k=?", (k,))
    return json.loads(r["v"]) if r else default


def kv_set(k, v):
    run("INSERT INTO kv(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, json.dumps(v)))


def log_error(project_id, stage, message):
    run("INSERT INTO errors(project_id,stage,message,created_at) VALUES(?,?,?,?)",
        (project_id, stage, str(message)[:4000], time.time()))


def run_count(sql, args=()):
    """Execute and return the number of rows changed (used for atomic claims)."""
    c = connect()
    try:
        return c.execute(sql, args).rowcount
    finally:
        c.close()
