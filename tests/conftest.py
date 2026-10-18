import os, sys, tempfile, subprocess, shutil
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["FACTORY_DATA"] = tempfile.mkdtemp(prefix="factory_test_")
import pytest
from factory import db, config, characters, pipeline


@pytest.fixture(autouse=True)
def fresh():
    shutil.rmtree(config.DATA_DIR, ignore_errors=True)
    config.ensure_dirs(); db.init(); characters.ensure_defaults()
    yield


def make_video(path, w=1080, h=1920, audio=True, seconds=33, color=False):
    src = f"testsrc2=s={w}x{h}:r=30:d={seconds}" if not color else f"color=c=black:s={w}x{h}:r=30:d={seconds}"
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", src]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=f=220:d={seconds}"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p"] + (["-c:a", "aac", "-shortest"] if audio else ["-an"]) + [str(path)]
    subprocess.run(cmd, check=True)


@pytest.fixture
def pending_project():
    """A project in pending_approval with a valid dummy final.mp4 (skips the slow render)."""
    from factory import util
    idea = {"title": "T", "logline": "L", "hook": "H", "genre": "mystery"}
    pid = pipeline.create_project(idea=idea, character_id="char_wren")
    d = config.project_dir(pid); make_video(d / "final.mp4")
    util.jwrite(d / "metadata.json", {"title": "T #shorts", "description": "d", "tags": [], "contains_synthetic_media": True})
    db.run("UPDATE projects SET status='pending_approval', final_sha256=? WHERE id=?", (util.sha256(d / "final.mp4"), pid))
    return pid
