"""Image provider. ComfyUI (localhost) when reachable; otherwise a procedural layered painter.
The procedural painter yields stylised silhouette scenes with separate depth layers (for parallax).
It is a stand-in, not a substitute for diffusion-quality art."""
import json, math, random, time, uuid
from pathlib import Path
import numpy as np
import requests
from PIL import Image, ImageDraw, ImageFilter
from .. import config

NEG = "text, watermark, logo, caption, blurry, deformed, extra limbs, extra fingers, lowres, bad anatomy, cartoon"


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
    elif kind == "interior":    # dark stone room: brick courses + an arched window, no sky objects
        empty = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        sky = _grad(w, h, [(26, 18, 24), (52, 34, 40), (92, 58, 52)]).convert("RGBA"); sd = ImageDraw.Draw(sky)
        for r in range(0, h, h // 16):
            sd.line([0, r, w, r], fill=(20, 14, 18, 150), width=2)
            for c in range((r // (h // 16)) % 2 * (w // 12), w, w // 6):
                sd.line([c, r, c, r + h // 16], fill=(20, 14, 18, 150), width=2)
        sd.rounded_rectangle([w * .62, h * .12, w * .9, h * .42], radius=int(w * .14), fill=(30, 40, 84, 255), outline=(14, 10, 14, 255), width=int(w * .02))
        far = mid = near = empty
    elif kind == "sea":
        def sea_layer(top, shade):
            img = Image.new("RGBA", (w, h), (0, 0, 0, 0)); dr = ImageDraw.Draw(img)
            col = tuple(int(c * shade) for c in pal[1]) + (255,)
            dr.rectangle([0, int(top), w, h], fill=col)
            for _ in range(14):   # ice floes / wave glints
                x, y = rng.randint(0, w), rng.randint(int(top) + 8, h)
                fw = rng.randint(w // 10, w // 4); dr.polygon([(x, y), (x + fw, y), (x + fw * .85, y + h * .012), (x + fw * .1, y + h * .012)], fill=tuple(min(255, int(c * (shade + .5))) for c in pal[1]) + (200,))
            return img
        far = silhouette(_ridge(w, h, rng, h * .66, h * .015, 1.0), .6)
        mid = sea_layer(h * .68, .9)
        near = silhouette(_ridge(w, h, rng, h * .96, h * .02, .8), .12)
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
    _props(spec, pal, w, h, rng, mid, fog, char)
    return {"sky": sky, "far": far, "mid": mid, "near": near, "fog": fog, "char": char}


def _glow(layer, cx, cy, r, color, alpha=200, blur=None):
    g = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    ImageDraw.Draw(g).ellipse([cx - r, cy - r, cx + r, cy + r], fill=tuple(color) + (alpha,))
    layer.alpha_composite(g.filter(ImageFilter.GaussianBlur(blur or max(2, r // 2))))


def _lighthouse(layer, fogl, cx, base, ht, w, lit=True, red=False):
    d = ImageDraw.Draw(layer); bw = ht * .16; tw = bw * .6
    d.polygon([(cx - bw, base), (cx + bw, base), (cx + tw, base - ht), (cx - tw, base - ht)], fill=(226, 224, 232, 255))
    for i in range(1, 4):   # red bands
        y0 = base - ht * (i * .26); y1 = y0 - ht * .1; k0 = bw - (bw - tw) * (base - y0) / ht; k1 = bw - (bw - tw) * (base - y1) / ht
        d.polygon([(cx - k0, y0), (cx + k0, y0), (cx + k1, y1), (cx - k1, y1)], fill=(196, 52, 48, 255))
    d.rectangle([cx - tw * 1.25, base - ht - ht * .06, cx + tw * 1.25, base - ht], fill=(40, 36, 50, 255))
    d.polygon([(cx - tw * 1.4, base - ht - ht * .06), (cx + tw * 1.4, base - ht - ht * .06), (cx, base - ht - ht * .2)], fill=(196, 52, 48, 255))
    lamp = (255, 90, 70) if red else (255, 224, 140)
    if lit:
        _glow(fogl, cx, base - ht - ht * .03, int(ht * .12), lamp, 230)
        d.rectangle([cx - tw * .7, base - ht - ht * .05, cx + tw * .7, base - ht - ht * .01], fill=lamp + (255,))


def _props(spec, pal, w, h, rng, mid, fogl, char):
    props = spec.get("props") or []
    d = ImageDraw.Draw(mid); gold = (255, 214, 120)
    if "lighthouse" in props or "lighthouse_red" in props:
        _lighthouse(mid, fogl, int(w * spec.get("lh_x", .68)), int(h * .7), int(h * spec.get("lh_h", .42)), w, red="lighthouse_red" in props)
    if "lighthouse_far" in props:
        _lighthouse(mid, fogl, int(w * .75), int(h * .67), int(h * .2), w)
    if "beam" in props:
        bx, by = int(w * spec.get("lh_x", .68)), int(h * (.7 - spec.get("lh_h", .42)))
        b = Image.new("RGBA", fogl.size, (0, 0, 0, 0))
        ImageDraw.Draw(b).polygon([(bx, by), (0, by - h * .1), (0, by + h * .12)], fill=gold + (70,)); fogl.alpha_composite(b.filter(ImageFilter.GaussianBlur(8)))
    if "lamp" in props:    # giant glowing lens with rays
        cx, cy = int(w * .5), int(h * .36)
        for ang in range(0, 360, 20):
            a = math.radians(ang); b = Image.new("RGBA", fogl.size, (0, 0, 0, 0))
            ImageDraw.Draw(b).polygon([(cx, cy), (cx + math.cos(a - .06) * w, cy + math.sin(a - .06) * w), (cx + math.cos(a + .06) * w, cy + math.sin(a + .06) * w)], fill=gold + (38,))
            fogl.alpha_composite(b.filter(ImageFilter.GaussianBlur(4)))
        _glow(fogl, cx, cy, int(w * .2), gold, 235, int(w * .08)); d.ellipse([cx - w * .11, cy - w * .11, cx + w * .11, cy + w * .11], outline=(60, 44, 40, 255), width=int(w * .014))
    if "lights" in props:   # many small glows under the ice
        for _ in range(46):
            x, y = rng.randint(0, w), rng.randint(int(h * .72), int(h * .95))
            _glow(fogl, x, y, rng.randint(3, 7), rng.choice([gold, (150, 220, 255), (255, 170, 120)]), 230, 4)
    if "boats" in props:
        for i in range(5):
            x, y, sz = int(w * (.12 + i * .19)), int(h * (.72 + rng.uniform(0, .05))), int(h * rng.uniform(.04, .07))
            d.polygon([(x - sz, y), (x + sz, y), (x + sz * .6, y + sz * .35), (x - sz * .6, y + sz * .35)], fill=(34, 26, 38, 255))
            d.polygon([(x, y - sz * 1.6), (x, y - sz * .1), (x + sz * .8, y - sz * .1)], fill=(246, 232, 210, 255))
    if "stairs" in props:
        for i in range(9):
            x0 = w * (.12 + i * .09); y0 = h * (.86 - i * .075)
            d.rectangle([x0, y0, x0 + w * .22, y0 + h * .03], fill=(72, 52, 58, 255))
        for _ in range(26):
            x, y = rng.randint(int(w * .05), int(w * .95)), rng.randint(int(h * .1), int(h * .8))
            d.rectangle([x, y, x + w * .05, y + 3], fill=(120, 96, 100, 160))
        _glow(fogl, int(w * .2), int(h * .5), int(w * .2), gold, 120)
    if "ghost" in props:    # golden second figure beside the hero, translucent
        gh = Image.new("RGBA", char.size, (0, 0, 0, 0))
        _draw_character(gh, dict(spec, cloth_color="#ffd778", accent_color="#fff3c4", char_x=spec.get("char_x", .5) + .26, char_scale=1.05), w, h, rng)
        a = gh.split()[3].point(lambda v: int(v * .55)); gh.putalpha(a)
        char.alpha_composite(gh.filter(ImageFilter.GaussianBlur(3)))
        _glow(fogl, int(w * (spec.get("char_x", .5) + .26)), int(h * .75), int(w * .22), gold, 80, int(w * .08))


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
    sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).ellipse([cx - bw * 1.5, base - ch * .03, cx + bw * 1.5, base + ch * .05], fill=(0, 0, 0, 110))
    img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(6)))
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
    neg = spec.get("negative") or NEG
    """Writes {name}.png (flattened) and, for procedural scenes, {name}_<layer>.png for parallax."""
    s = config.load_settings()["image"]
    if backend == "comfyui":
        comfy_generate(prompt, seed, out_dir / f"{name}.png")
        return "comfyui"
    if backend == "diffusers":
        diffusers_generate(prompt, seed, out_dir / f"{name}.png", w, h, neg)
        return "diffusers"
    if backend == "hybrid":
        _hybrid(spec, seed, out_dir, name, w, h, prompt, neg)
        return "hybrid"
    layers = paint_layers(spec, w, h, seed)
    for k, im in layers.items():
        im.save(out_dir / f"{name}_{k}.png")
    flatten(layers).save(out_dir / f"{name}.png")
    return "procedural"


_DIFF = {}


def diffusers_available():
    try:
        import torch, diffusers, peft   # noqa: F401
        return True
    except ImportError:
        return False


def diffusers_generate(prompt, seed, out_path: Path, w, h, negative=NEG):
    """Local diffusion via Hugging Face diffusers: SD1.5-class checkpoint + LCM-LoRA (4-5 steps). CUDA if present, else CPU.
    Pipeline stays loaded for the duration of the (subprocess) stage, then is freed with the process."""
    import torch
    from diffusers import StableDiffusionPipeline, LCMScheduler
    from PIL import Image
    d = config.load_settings()["image"]["diffusers"]
    if "pipe" not in _DIFF:
        cuda = torch.cuda.is_available()
        cache = str(config.ROOT / d["cache_dir"])
        pipe = StableDiffusionPipeline.from_pretrained(d["model"], torch_dtype=torch.float16 if cuda else torch.float32, safety_checker=None, cache_dir=cache)
        pipe.load_lora_weights(d["lora"], cache_dir=cache); pipe.fuse_lora()
        pipe.scheduler = LCMScheduler.from_config(pipe.scheduler.config)
        _DIFF["pipe"] = pipe.to("cuda" if cuda else "cpu")
    gen = torch.Generator().manual_seed(int(seed) % (2**31))
    im = _DIFF["pipe"](prompt, negative_prompt=negative, num_inference_steps=d["steps"], guidance_scale=d["guidance"], width=d["w"], height=d["h"], generator=gen).images[0]
    im.resize((w, h), Image.LANCZOS).save(out_path)


def _hybrid(spec, seed, out_dir, name, w, h, prompt, neg):
    """AI-painted people-free backdrop + flat-shape character layer on top (depth layers kept for parallax)."""
    diffusers_generate(prompt, seed, out_dir / f"{name}_bg.png", w, h, neg)
    bg = Image.open(out_dir / f"{name}_bg.png").convert("RGBA")
    empty = Image.new("RGBA", (w, h), (0, 0, 0, 0)); char = empty.copy(); fogl = empty.copy()
    rng = random.Random(seed)
    if spec.get("show_character", True):
        _draw_character(char, spec, w, h, rng)
    if "ghost" in (spec.get("props") or []):
        _props({"props": ["ghost"], "char_x": spec.get("char_x", .5), "cloth_color": spec.get("cloth_color"), "accent_color": spec.get("accent_color")}, None, w, h, rng, empty.copy(), fogl, char)
    layers = {"sky": bg, "far": empty, "mid": empty, "near": empty, "fog": fogl, "char": char}
    for k, im in layers.items():
        im.save(out_dir / f"{name}_{k}.png")
    flatten(layers).save(out_dir / f"{name}.png")


def pick_backend():
    s = config.load_settings()["image"]
    if s["backend"] in ("comfyui", "diffusers", "procedural", "hybrid"):
        return s["backend"]
    if comfy_available(s["comfyui_url"]):
        return "comfyui"
    if diffusers_available():
        return "hybrid"
    return "procedural"
