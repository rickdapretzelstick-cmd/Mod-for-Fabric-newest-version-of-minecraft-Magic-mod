import hashlib, json, os, subprocess, sys
from pathlib import Path
from PIL import ImageFont

FONT_CANDIDATES = ["C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/arial.ttf",
                   "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/Library/Fonts/Arial Bold.ttf"]


def sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def font(size):
    for f in FONT_CANDIDATES:
        if os.path.exists(f):
            return ImageFont.truetype(f, size)
    return ImageFont.load_default()


def jread(p, default=None):
    p = Path(p)
    return json.loads(p.read_text()) if p.exists() else default


def jwrite(p, data):
    Path(p).write_text(json.dumps(data, indent=2))


def key(*parts) -> str:
    return hashlib.sha1(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:16]


def ffprobe(path) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
                         capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError("ffprobe failed: " + out.stderr[:300])
    return json.loads(out.stdout)


def ffmpeg(args, cwd=None, timeout=3600):
    r = subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"] + [str(a) for a in args],
                       cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError("ffmpeg failed: " + r.stderr[-800:])
    return r
