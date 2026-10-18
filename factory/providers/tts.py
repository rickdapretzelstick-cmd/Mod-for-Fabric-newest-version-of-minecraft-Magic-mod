"""Local TTS: Piper (preferred) -> espeak-ng -> none. 'none' yields silent narration and a QC failure,
so a video with no real voice can never look approved-ready by accident."""
import shutil, subprocess, wave
from pathlib import Path
from .. import config


def wav_duration(p: Path) -> float:
    with wave.open(str(p)) as w:
        return w.getnframes() / w.getframerate()


def pick_backend():
    s = config.load_settings()["tts"]
    model = config.ROOT / s["piper_model"]
    if s["backend"] in ("auto", "piper") and shutil.which(s["piper_exe"]) and model.exists():
        return "piper"
    if s["backend"] in ("auto", "espeak") and (shutil.which("espeak-ng") or shutil.which("espeak")):
        return "espeak"
    if s["backend"] == "piper":
        raise RuntimeError("tts.backend=piper but piper executable or model is missing")
    return "none"


def synthesize(text: str, out: Path, backend: str):
    s = config.load_settings()["tts"]
    if backend == "piper":
        model = config.ROOT / s["piper_model"]
        subprocess.run([s["piper_exe"], "--model", str(model), "--output_file", str(out),
                        "--length_scale", str(1.0 / s["speed"])], input=text, text=True, check=True, timeout=300)
    elif backend == "espeak":
        exe = shutil.which("espeak-ng") or shutil.which("espeak")
        subprocess.run([exe, "-v", "en-us", "-s", "150", "-w", str(out), text], check=True, timeout=120)
    else:
        raise RuntimeError("No TTS engine available (install Piper: see README)")
    # normalise to 44.1k mono 16-bit for the mixer
    tmp = out.with_suffix(".norm.wav")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(out), "-ar", "44100", "-ac", "1", "-sample_fmt", "s16", str(tmp)], check=True)
    tmp.replace(out)
