"""Original music and SFX synthesised locally with numpy: no third-party audio, so no licensing issues."""
import wave
import numpy as np

SR = 44100
NOTE = {"A": 0, "B": 2, "C": 3, "D": 5, "E": 7, "F": 8, "G": 10}


def freq(n, octave=3):
    return 440 * 2 ** ((n - 9) / 12 + (octave - 4))


def write_wav(path, x):
    x = np.clip(x, -1, 1)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((x * 32767).astype("<i2").tobytes())


def read_wav(path):
    with wave.open(str(path)) as w:
        d = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(float) / 32768
    return d


def _env(n, a, r):
    e = np.ones(n); na, nr = min(int(a * SR), n // 2), min(int(r * SR), n // 2)
    if na: e[:na] = np.linspace(0, 1, na)
    if nr: e[-nr:] *= np.linspace(1, 0, nr)
    return e


def music(duration, mood="night", seed=0):
    """Dark ambient bed: detuned pad on a minor progression + slow pulse + sparse high plucks."""
    rng = np.random.default_rng(seed)
    n = int(duration * SR); t = np.arange(n) / SR
    root = [0, 3, 8, 7][seed % 4] if mood != "dawn" else 5
    prog = [root, root + 8, root + 3, root + 7]
    out = np.zeros(n)
    seg = duration / len(prog)
    for i, r in enumerate(prog):
        a, b = int(i * seg * SR), min(n, int((i + 1) * seg * SR))
        tt = t[a:b]
        for iv, amp in ((0, .5), (3, .35), (7, .3), (12, .15)):
            f = freq(r + iv, 2)
            for det in (-.4, .4):
                out[a:b] += amp * np.sin(2 * np.pi * (f * 2 ** (det / 1200)) * tt + rng.uniform(0, 6)) * .5
        out[a:b] *= _env(b - a, 1.2, 1.2) if i not in (0, len(prog) - 1) else _env(b - a, 2 if i == 0 else .5, .5 if i == 0 else 3)
    pulse = (np.sin(2 * np.pi * 1.2 * t) * .5 + .5) ** 3
    out += .22 * np.sin(2 * np.pi * freq(prog[0], 1) * t) * pulse
    step = 60 / 80 * 1.5
    k = 0
    while k * step < duration - 1:
        n0 = int(k * step * SR); L = int(.9 * SR)
        if n0 + L < n and rng.random() < .55:
            tt = np.arange(L) / SR
            out[n0:n0 + L] += .12 * np.sin(2 * np.pi * freq(prog[(k // 3) % 4] + rng.choice([0, 3, 7, 12]), 5) * tt) * np.exp(-tt * 4)
        k += 1
    return out / max(1e-9, np.max(np.abs(out))) * .5


def whoosh(d=.7, seed=0):
    rng = np.random.default_rng(seed); n = int(d * SR)
    x = rng.standard_normal(n)
    k = np.ones(40) / 40
    lo = np.convolve(x, k, "same")
    sweep = np.sin(np.linspace(0, np.pi, n)) ** 2
    return lo * sweep * 2.2


def impact(d=1.4):
    n = int(d * SR); t = np.arange(n) / SR
    thump = np.sin(2 * np.pi * (90 * np.exp(-t * 6) + 35) * t) * np.exp(-t * 3.5)
    noise = np.random.default_rng(1).standard_normal(n) * np.exp(-t * 14) * .3
    return thump + noise


def riser(d=2.0):
    n = int(d * SR); t = np.arange(n) / SR
    f = 200 * (1 + 6 * (t / d) ** 2)
    ph = 2 * np.pi * np.cumsum(f) / SR
    return np.sin(ph) * (t / d) ** 2 * .5 + np.random.default_rng(2).standard_normal(n) * .08 * (t / d)


def duck_envelope(narr: np.ndarray, depth=.35, win=.08, release=.4):
    """Music gain that dips while narration is present."""
    w = int(win * SR)
    rms = np.sqrt(np.convolve(narr ** 2, np.ones(w) / w, "same"))
    gate = (rms > 0.015).astype(float)
    r = int(release * SR)
    sm = np.convolve(gate, np.ones(r) / r, "same")
    return 1 - (1 - depth) * np.clip(sm * 1.6, 0, 1)


def peak_limit(x, ceiling=.89):
    p = np.max(np.abs(x))
    return x if p <= ceiling else x * (ceiling / p)
