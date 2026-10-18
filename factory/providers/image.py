"""Image provider. ComfyUI (localhost) when reachable; otherwise a procedural layered painter.
The procedural painter yields stylised silhouette scenes with separate depth layers (for parallax).
It is a stand-in, not a substitute for diffusion-quality art."""
import json, math, random, time, uuid
from pathlib import Path
import numpy as np
import requests
from PIL import Image, ImageDraw, ImageFilter
from .. import config

NEG = "text, watermark, logo, blurry, deformed, extra limbs, lowres, bad anatomy"


def comfy_available(url):
    try:
        return requests.get(url + "/system_stats", timeout=2).ok
    except Exception:
        return False


def _workflow(prompt, seed, s):
    """SD1.5 txt2img graph in ComfyUI API format. Pascal-safe: fp32/fp16 only, no FlashAttention assumptions."""
    return {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": s["checkpoint"]}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["1", 1]}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": NEG, "clip": ["1", 1]}},
        "4": {"class_type": "EmptyLatentImage", "inputs": {"width": s["gen_w"], "height": s["gen_h"], "batch_size": 1}},
        "5": {"class_type": "KSampler", "inputs": {"model": ["1", 0], "positive": ["2", 0], "negative": ["3", 0],
              "latent_image": ["4", 0], "seed": seed, "steps": s["steps"], "cfg": s["cfg"],
              "sampler_name": s["sampler"], "scheduler": s["scheduler"], "denoise": 1.0}},
        "6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
        "7": {"class_type": "SaveImage", "inputs": {"images": ["6", 0], "filename_prefix": "factory"}},
    }


def comfy_generate(prompt, seed, out_path: Path):
    s = config.load_settings()["image"]
    url = s["comfyui_url"]
    r = requests.post(url + "/prompt", json={"prompt": _workflow(prompt, seed, s), "client_id": uuid.uuid4().hex}, timeout=30)
    r.raise_for_status()
    pid = r.json()["prompt_id"]
    t0 = time.time()
    while time.time() - t0 < s["timeout_s"]:
        h = requests.get(f"{url}/history/{pid}", timeout=10).json()
        if pid in h and h[pid].get("outputs"):
            img = next(iter(h[pid]["outputs"].values()))["images"][0]
            data = requests.get(f"{url}/view", params={"filename": img["filename"], "subfolder": img["subfolder"], "type": img["type"]}, timeout=30)
            out_path.write_bytes(data.content)
            return
        time.sleep(1.5)
    raise TimeoutError("ComfyUI generation timed out")


def comfy_free():
    """Ask ComfyUI to unload models and free VRAM between stages."""
    s = config.load_settings()["image"]
    try:
        requests.post(s["comfyui_url"] + "/free", json={"unload_models": True, "free_memory": True}, timeout=10)
    except Exception:
        pass


# ---------- procedural painter ----------
PALETTES = {
    "dusk": [(24, 20, 58), (120, 52, 98), (236, 120, 84)],
    "night": [(5, 8, 24), (14, 26, 62), (46, 86, 130)],
    "dawn": [(30, 36, 80), (170, 90, 110), (250, 190, 130)],
    "storm": [(12, 14, 20), (40, 48, 64), (96, 110, 128)],
    "ember": [(14, 6, 8), (80, 24, 20), (230, 110, 40)],
}


def _grad(w, h, stops):
    t = np.linspace(0, 1, h)[:, None]
    a, b, c = [np.array(x, float) for x in stops]
    top = a + (b - a)[None, :] * np.clip(t / 0.55, 0, 1)
    bot = b + (c - b)[None, :] * np.clip((t - 0.55) / 0.45, 0, 1)
    arr = np.where(t < 0.55, top, bot)
    return Image.fromarray(np.repeat(arr[:, None, :], w, axis=1).astype("uint8"), "RGB")


def _ridge(w, h, rng, base, amp, rough):
    xs = np.arange(w)
    y = np.zeros(w)
    for k in range(1, 6):
        y += rng.uniform(0.4, 1) / k**rough * np.sin(xs / w * math.pi * 2 * k * rng.uniform(0.8, 1.6) + rng.uniform(0, 6.28))
    return base + y * amp


def _skyline(w, h, rng, base, amp):
    top = np.full(w, float(base))
    x = 0
    while x < w:
        bw = rng.randint(w // 24, w // 9)
        top[x:x + bw] = base - rng.uniform(0.2, 1) * amp
        x += bw
    return top


def paint_layers(spec: dict, w: int, h: int, seed: int):
    """Returns dict of RGBA/RGB PIL layers: sky, far, mid, near, char (+fog). Same seed -> same scene."""
    rng = random.Random(seed)
    pal = PALETTES.get(spec.get("mood", "night"), PALETTES["night"])
    kind = spec.get("terrain", "mountains")
    sky = _grad(w, h, pal).convert("RGBA")
    d = ImageDraw.Draw(sky)
    for _ in range(140 if spec.get("mood") in ("night", "dusk", "dawn") else 40):
        x, y, r = rng.randint(0, w), rng.randint(0, int(h * .5)), rng.choice([1, 1, 2])
        d.ellipse([x - r, y - r, x + r, y + r], fill=(255, 255, 255, rng.randint(90, 220)))
    cx, cy, R = int(w * rng.uniform(.25, .75)), int(h * rng.uniform(.14, .3)), int(w * .09)
    glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse([cx - R * 2, cy - R * 2, cx + R * 2, cy + R * 2], fill=pal[2] + (70,))
    sky = Image.alpha_composite(sky, glow.filter(ImageFilter.GaussianBlur(R)))
    ImageDraw.Draw(sky).ellipse([cx - R, cy - R, cx + R, cy + R], fill=tuple(min(255, c + 80) for c in pal[2]) + (255,))

    def silhouette(top_y, shade, windows=False):
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        dr = ImageDraw.Draw(img)
        col = tuple(int(c * shade) for c in pal[0]) + (255,)
        for x in range(w):
            dr.line([x, int(top_y[x]), x, h], fill=col)
        if windows:
            for _ in range(70):
                x = rng.randint(0, w - 1)
                y = rng.randint(int(top_y[x]) + 6, int(min(h, top_y[x] + h * .25)))
                dr.rectangle([x, y, x + 3, y + 5], fill=(255, 210, 120, 220))
        return img

    if kind == "city":
        far, mid, near = (silhouette(_skyline(w, h, rng, h * .62, h * .16), .55), silhouette(_skyline(w, h, rng, h * .72, h * .2), .35, True),
                          silhouette(_skyline(w, h, rng, h * .86, h * .12), .15))
    elif kind == "forest":
        def trees(base, sh):
            t = _ridge(w, h, rng, base, h * .05, 1.2)
            img = silhouette(t, sh)
            dr = ImageDraw.Draw(img)
            for _ in range(w // 18):
                x = rng.randint(0, w); y = int(t[min(w - 1, x)]); th = rng.randint(int(h * .05), int(h * .13))
                dr.polygon([(x - th // 4, y + 4), (x + th // 4, y + 4), (x, y - th)], fill=tuple(int(c * sh) for c in pal[0]) + (255,))
            return img
        far, mid, near = trees(h * .66, .5), trees(h * .76, .3), trees(h * .88, .12)
    else:
        far, mid, near = (silhouette(_ridge(w, h, rng, h * .62, h * .09, 1.0), .55), silhouette(_ridge(w, h, rng, h * .74, h * .08, .9), .35),
                          silhouette(_ridge(w, h, rng, h * .9, h * .05, .8), .12))
    fog = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    fd = ImageDraw.Draw(fog)
    for _ in range(9):
        y = rng.randint(int(h * .55), int(h * .85)); fd.ellipse([rng.randint(-w // 3, w // 2), y, rng.randint(w // 2, w + w // 3), y + h // 14], fill=pal[2] + (38,))
    fog = fog.filter(ImageFilter.GaussianBlur(h // 60))
    char = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    if spec.get("show_character", True):
        _draw_character(char, spec, w, h, rng)
    return {"sky": sky, "far": far, "mid": mid, "near": near, "fog": fog, "char": char}


def _hex(c, default):
    try:
        c = c.lstrip("#"); return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))
    except Exception:
        return default


def _draw_character(img, spec, w, h, rng):
    """Stylised silhouette in the character's registered colours (consistent between episodes)."""
    cloth = _hex(spec.get("cloth_color", "#c8492f"), (200, 70, 50))
    acc = _hex(spec.get("accent_color", "#f2c14e"), (240, 190, 80))
    scale = spec.get("char_scale", 1.0)
    cx, base = int(w * spec.get("char_x", .5)), int(h * .93)
    ch = int(h * .27 * scale); bw = int(ch * .26)
    d = ImageDraw.Draw(img)
    d.polygon([(cx - bw, base), (cx + bw, base), (cx + bw // 2, base - ch * .65), (cx - bw // 2, base - ch * .65)], fill=cloth + (255,))
    d.rectangle([cx - bw // 2, base - ch * .68, cx + bw // 2, base - ch * .6], fill=acc + (255,))
    hr = int(ch * .13)
    d.ellipse([cx - hr, base - ch * .65 - hr * 2, cx + hr, base - ch * .65], fill=(30, 24, 30, 255))
    d.polygon([(cx - hr * 1.3, base - ch * .8), (cx, base - ch * 1.12), (cx + hr * 1.3, base - ch * .8)], fill=cloth + (255,))
    glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse([cx + bw, base - ch * .5, cx + bw + hr * 2, base - ch * .5 + hr * 2], fill=acc + (230,))
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(6)))


def flatten(layers: dict) -> Image.Image:
    im = layers["sky"].copy()
    for k in ("far", "mid", "fog", "near", "char"):
        im.alpha_composite(layers[k])
    return im.convert("RGB")


def generate_scene(spec: dict, seed: int, out_dir: Path, name: str, w: int, h: int, prompt: str, backend: str):
    """Writes {name}.png (flattened) and, for procedural scenes, {name}_<layer>.png for parallax."""
    s = config.load_settings()["image"]
    use_comfy = backend == "comfyui"
    if use_comfy:
        comfy_generate(prompt, seed, out_dir / f"{name}.png")
        return "comfyui"
    layers = paint_layers(spec, w, h, seed)
    for k, im in layers.items():
        im.save(out_dir / f"{name}_{k}.png")
    flatten(layers).save(out_dir / f"{name}.png")
    return "procedural"


def pick_backend():
    s = config.load_settings()["image"]
    if s["backend"] == "comfyui":
        return "comfyui"
    if s["backend"] == "auto" and comfy_available(s["comfyui_url"]):
        return "comfyui"
    return "procedural"
