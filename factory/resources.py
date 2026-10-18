"""CPU/RAM/GPU/disk monitoring and safe temp cleanup."""
import shutil, subprocess, time
import psutil
from . import config


def gpu_info():
    """Query nvidia-smi. Returns None when no NVIDIA GPU/driver is present (never fabricates values)."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,driver_version,memory.total,memory.used,utilization.gpu,temperature.gpu,compute_cap",
             "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=10)
        if out.returncode != 0 or not out.stdout.strip():
            return None
        n, drv, tot, used, util, temp, cc = [x.strip() for x in out.stdout.strip().splitlines()[0].split(",")]
        return {"name": n, "driver": drv, "vram_total_mb": int(tot), "vram_used_mb": int(used),
                "util_pct": int(util), "temp_c": int(temp), "compute_capability": cc}
    except Exception:
        return None


def snapshot():
    du = shutil.disk_usage(config.DATA_DIR if config.DATA_DIR.exists() else config.ROOT)
    vm = psutil.virtual_memory()
    return {"cpu_pct": psutil.cpu_percent(interval=0.2), "ram_total_gb": round(vm.total / 2**30, 1),
            "ram_used_gb": round(vm.used / 2**30, 1), "disk_free_gb": round(du.free / 2**30, 1),
            "disk_total_gb": round(du.total / 2**30, 1), "gpu": gpu_info(), "ts": time.time()}


def check_disk(min_free_gb: float):
    free = snapshot()["disk_free_gb"]
    if free < min_free_gb:
        raise RuntimeError(f"Only {free} GB free disk; need {min_free_gb} GB (config jobs.min_free_disk_gb)")


def cleanup_tmp(max_age_s=6 * 3600):
    """Delete only stale scratch files under data/tmp. Never touches projects/, characters/ or finals."""
    removed = 0
    now = time.time()
    for p in config.TMP_DIR.glob("*"):
        try:
            if now - p.stat().st_mtime > max_age_s:
                shutil.rmtree(p) if p.is_dir() else p.unlink()
                removed += 1
        except OSError:
            pass
    return removed
