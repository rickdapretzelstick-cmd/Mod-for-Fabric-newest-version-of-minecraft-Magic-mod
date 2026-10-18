"""Paths and settings. Settings = defaults file + user override file (config/settings.json)."""
import json, os, copy
from pathlib import Path

ROOT = Path(os.environ.get("FACTORY_ROOT", Path(__file__).resolve().parent.parent))
CONFIG_DIR = ROOT / "config"
DATA_DIR = Path(os.environ.get("FACTORY_DATA", ROOT / "data"))
SECRETS_DIR = ROOT / "secrets"
PROJECTS_DIR = DATA_DIR / "projects"
CHAR_DIR = DATA_DIR / "characters"
TMP_DIR = DATA_DIR / "tmp"
LOG_DIR = DATA_DIR / "logs"
DB_PATH = DATA_DIR / "factory.db"


def ensure_dirs():
    for d in (DATA_DIR, PROJECTS_DIR, CHAR_DIR, TMP_DIR, LOG_DIR, SECRETS_DIR):
        d.mkdir(parents=True, exist_ok=True)


def _merge(a, b):
    for k, v in b.items():
        if isinstance(v, dict) and isinstance(a.get(k), dict):
            _merge(a[k], v)
        else:
            a[k] = v
    return a


def load_settings() -> dict:
    s = json.loads((CONFIG_DIR / "settings.default.json").read_text())
    user = CONFIG_DIR / "settings.json"
    if user.exists():
        _merge(s, json.loads(user.read_text()))
    return s


def save_settings(patch: dict) -> dict:
    user = CONFIG_DIR / "settings.json"
    cur = json.loads(user.read_text()) if user.exists() else {}
    _merge(cur, patch)
    user.write_text(json.dumps(cur, indent=2))
    return load_settings()


def render_profile(s: dict | None = None) -> dict:
    s = s or load_settings()
    return s["quality_presets"][s["quality"]]


def project_dir(pid: int) -> Path:
    d = PROJECTS_DIR / f"{pid:05d}"
    d.mkdir(parents=True, exist_ok=True)
    return d
