"""Checks the machine and reports what will work. Makes no changes. Run: python scripts/preflight.py"""
import json, platform, shutil, subprocess, sys, urllib.request
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from factory import config, resources

ok = lambda b: "OK  " if b else "MISS"


def http_ok(url):
    try:
        urllib.request.urlopen(url, timeout=2); return True
    except Exception:
        return False


s = config.load_settings(); snap = resources.snapshot(); g = snap["gpu"]
print(f"OS: {platform.platform()}  Python {platform.python_version()}")
print(f"CPU use {snap['cpu_pct']}%  RAM {snap['ram_total_gb']} GB  free disk {snap['disk_free_gb']} GB")
print(f"{ok(snap['disk_free_gb'] >= 30)} disk >= 30 GB free (models + renders)")
if g:
    print(f"{ok(True)} GPU {g['name']} driver {g['driver']} VRAM {g['vram_total_mb']} MB compute capability {g['compute_capability']}")
    cc = g["compute_capability"]
    if cc.startswith("6"):
        print("     Pascal (CC 6.1): use ComfyUI with --force-fp32; avoid SDXL/video diffusion.")
    elif cc.startswith("12"):
        print("     Blackwell (CC 12.x, e.g. RTX 50-series): needs PyTorch built for CUDA 12.8+ (cu128 wheels).")
else:
    print(f"{ok(False)} NVIDIA GPU / nvidia-smi (images fall back to the procedural painter)")
for exe in ("ffmpeg", "ffprobe", "node", "ollama"):
    print(f"{ok(shutil.which(exe))} {exe}")
print(f"{ok(http_ok(s['llm']['ollama_url'] + '/api/tags'))} Ollama reachable ({s['llm']['ollama_url']})")
print(f"{ok(http_ok(s['image']['comfyui_url'] + '/system_stats'))} ComfyUI reachable ({s['image']['comfyui_url']})")
print(f"{ok(shutil.which(s['tts']['piper_exe']) and (ROOT / s['tts']['piper_model']).exists())} Piper + voice model ({s['tts']['piper_model']})")
try:
    import torch
    if torch.cuda.is_available():
        torch.zeros(1).cuda(); print(f"{ok(True)} PyTorch CUDA works: torch {torch.__version__} cuda {torch.version.cuda}")
    else:
        print(f"{ok(False)} PyTorch installed but CUDA unavailable")
except ImportError:
    print("     (torch not in this venv - that is fine; ComfyUI has its own environment)")
print(f"{ok((config.SECRETS_DIR / 'youtube_token.json').exists())} YouTube authorised (optional until you want to upload)")
