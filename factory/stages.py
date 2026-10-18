"""Pipeline stages. Each stage: fn(pid, scenes=None) -> detail dict. Stages read/write files in the project dir,
are idempotent, cache per-scene outputs by content key, and can be re-run alone."""
import json, math, random, re, subprocess, time
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from . import config, db, characters, util
from .providers import llm, image, tts, audio

TRANSITION = 0.35
LEAD, TAIL = 0.35, 0.55
CAMERAS = ["push_in", "pan_right", "pull_out", "pan_left", "tilt_up", "push_in", "pull_out"]
PLACE_TERRAIN = [("city", "city"), ("market", "city"), ("tower", "city"), ("station", "city"), ("forest", "forest"), ("tree", "forest")]


def pdir(pid):
    return config.project_dir(pid)


def project(pid):
    return db.one("SELECT * FROM projects WHERE id=?", (pid,))


def _terrain(place):
    for k, v in PLACE_TERRAIN:
        if k in place.lower():
            return v
    return "mountains"


# ---------------- script ----------------
def script(pid, scenes=None):
    p = project(pid); idea = json.loads(p["concept"])
    ch = characters.get(p["character_id"]) if p["character_id"] else None
    who = ch["name"] if ch else "A lone traveler"
    place, tod = idea.get("place", "a forgotten place"), idea.get("time_of_day", "night")
    secret, twist = idea.get("secret", "something impossible"), idea.get("twist", "nothing was as it seemed")
    prompt = (f"Write a 7-scene narration script for a 35-second vertical cinematic short. Idea: {idea['title']} — {idea['logline']}. Hook: {idea['hook']}. "
              "Return JSON {title, scenes:[{narration (12-16 words), visual (one sentence describing the image), mood (night|dusk|dawn|storm|ember), "
              "terrain (mountains|city|forest), show_character (bool)}]}. Scene 1 must open with the hook. Scene 7 must give a satisfying ending. Original; no real people or brands.")

    def fb():
        t = _terrain(place)
        mood = tod if tod in ("dusk", "night", "dawn") else "night"
        S = [(idea["hook"], f"wide establishing shot of {place}", mood, False),
             (f"{who} arrived at {place} just as the light failed. The air felt wrong.", f"{who} at the edge of {place}", mood, True),
             (f"There, waiting in the quiet, was {secret}.", f"{secret}, glowing softly", "ember" if t != "forest" else mood, True),
             ("It should have been impossible. But it moved, slowly, like it knew the name.", "dark shapes shifting in fog", "storm", True),
             (f"{who} reached out anyway. And everything changed.", "hand reaching toward a bright light", "ember", True),
             (f"Then it made sense. {twist[0].upper() + twist[1:]}.", "calm revelation, soft light returning", "dawn", True),
             ("Some places don't keep secrets. They keep you, until you are ready to listen.", "wide final shot, the figure small against the horizon", mood, True)]
        return {"title": idea["title"], "scenes": [{"narration": n, "visual": v, "mood": m, "terrain": t, "show_character": sc} for n, v, m, sc in S]}
    data, backend = llm.generate_json(prompt, "You are a precise screenwriter. Output only JSON.", fb)
    sc = data["scenes"][:8]
    if len(sc) < 4:
        raise RuntimeError("Script has too few scenes")
    for i, s in enumerate(sc, 1):
        s["n"] = i
    out = {"title": data.get("title") or idea["title"], "concept": idea["logline"], "backend": backend, "scenes": sc,
           "disclosure": "AI-generated visuals, narration and music."}
    util.jwrite(pdir(pid) / "script.json", out)
    return {"backend": backend, "scenes": len(sc), "words": sum(len(s["narration"].split()) for s in sc)}


# ---------------- storyboard ----------------
def storyboard(pid, scenes=None):
    p = project(pid); sc = util.jread(pdir(pid) / "script.json")
    ch = characters.get(p["character_id"]) if p["character_id"] else None
    old = util.jread(pdir(pid) / "storyboard.json", {"scenes": []})
    overrides = {s["n"]: s for s in old["scenes"] if s.get("prompt_override")}
    base_seed = ch["seed"] if ch else random.Random(pid).randint(1, 10**6)
    scenes_out = []
    for i, s in enumerate(sc["scenes"]):
        n = s["n"]
        shot = ["wide establishing shot", "medium shot, low angle", "close-up, shallow depth of field", "over-the-shoulder", "dutch angle",
                "high angle", "silhouette against light"][i % 7]
        prompt = ", ".join(x for x in [characters.prompt_prefix(ch) if (ch and s.get("show_character", True)) else "", s["visual"], shot,
                           "cinematic lighting, volumetric fog, 9:16 vertical composition, highly detailed"] if x)
        sfx = ["impact"] if i == 0 else (["riser"] if i == len(sc["scenes"]) - 3 else (["impact"] if i == len(sc["scenes"]) - 2 else []))
        row = {"n": n, "narration": s["narration"], "visual": s["visual"], "mood": s.get("mood", "night"), "terrain": s.get("terrain", "mountains"),
               "show_character": bool(s.get("show_character", True)), "camera": CAMERAS[i % len(CAMERAS)], "shot": shot, "sfx": sfx,
               "seed": base_seed + n * 7, "prompt": prompt, "negative": image.NEG, "char_x": [.5, .35, .62, .5, .4, .55, .5][i % 7]}
        if n in overrides:
            row["prompt"] = overrides[n]["prompt"]; row["prompt_override"] = True
        scenes_out.append(row)
    util.jwrite(pdir(pid) / "storyboard.json", {"character_id": p["character_id"], "scenes": scenes_out})
    return {"scenes": len(scenes_out)}


# ---------------- characters ----------------
def characters_stage(pid, scenes=None):
    p = project(pid)
    if not p["character_id"]:
        return {"character": None}
    ch = characters.get(p["character_id"])
    if not ch:
        raise RuntimeError(f"Character {p['character_id']} not in library")
    d = config.CHAR_DIR / ch["id"]; d.mkdir(parents=True, exist_ok=True)
    ref = d / "ref_01.png"
    if not ref.exists():
        be = image.pick_backend()
        spec = {"mood": "dusk", "terrain": "city", "cloth_color": ch["colors"].get("cloth"), "accent_color": ch["colors"].get("accent"), "char_scale": 1.3}
        image.generate_scene(spec, ch["seed"], d, "ref_01", 540, 960, characters.prompt_prefix(ch) + ", character reference, full body", be)
        characters.add_ref(ch["id"], f"characters/{ch['id']}/ref_01.png")
    return {"character": ch["id"], "ref": str(ref.name)}


# ---------------- visuals ----------------
def visuals(pid, scenes=None):
    p = project(pid); sb = util.jread(pdir(pid) / "storyboard.json")
    ch = characters.get(p["character_id"]) if p["character_id"] else None
    prof = config.render_profile(); W, H = int(prof["render_w"] * 1.25), int(prof["render_h"] * 1.25)
    d = pdir(pid) / "scenes"; d.mkdir(exist_ok=True)
    cache = util.jread(d / "visual_cache.json", {})
    be = image.pick_backend(); made = 0
    for s in sb["scenes"]:
        k = util.key(s["prompt"], s["seed"], be, W, H, s["mood"], s["terrain"], s["show_character"], s["char_x"], ch and ch["colors"])
        if scenes and s["n"] not in scenes:
            continue
        if cache.get(str(s["n"])) == k and (d / f"s{s['n']:02d}.png").exists():
            continue
        spec = dict(s, cloth_color=ch and ch["colors"].get("cloth"), accent_color=ch and ch["colors"].get("accent"))
        used = image.generate_scene(spec, s["seed"], d, f"s{s['n']:02d}", W, H, s["prompt"], be)
        cache[str(s["n"])] = k; made += 1
    util.jwrite(d / "visual_cache.json", cache)
    util.jwrite(d / "backend.json", {"backend": be})
    if be == "comfyui":
        image.comfy_free()
    return {"backend": be, "generated": made, "render_size": [W, H]}


# ---------------- voiceover ----------------
def voiceover(pid, scenes=None):
    sb = util.jread(pdir(pid) / "storyboard.json"); be = tts.pick_backend()
    d = pdir(pid) / "narration"; d.mkdir(exist_ok=True)
    cache = util.jread(d / "cache.json", {}); durs = {}
    if be == "none":
        raise RuntimeError("No TTS engine available. Install Piper and a voice model (see README).")
    for s in sb["scenes"]:
        f = d / f"n{s['n']:02d}.wav"; k = util.key(s["narration"], be, config.load_settings()["tts"])
        if cache.get(str(s["n"])) != k or not f.exists():
            tts.synthesize(s["narration"], f, be); cache[str(s["n"])] = k
        durs[s["n"]] = tts.wav_duration(f)
    util.jwrite(d / "cache.json", cache); util.jwrite(d / "durations.json", {"backend": be, "durations": durs})
    return {"backend": be, "narration_seconds": round(sum(durs.values()), 2)}


def timeline(pid):
    """Scene durations/starts from narration length, padded to reach the minimum duration."""
    o = config.load_settings()["output"]; v = util.jread(pdir(pid) / "narration" / "durations.json")
    sb = util.jread(pdir(pid) / "storyboard.json"); ds = v["durations"]
    n = len(sb["scenes"]); base = [ds[str(s["n"])] + LEAD + TAIL for s in sb["scenes"]]
    target = o["min_seconds"] + 2.0
    total = sum(base) - (n - 1) * TRANSITION
    extra = max(0.0, (target - total) / n)
    dur = [b + extra for b in base]
    starts, t = [], 0.0
    for d_ in dur:
        starts.append(t); t += d_ - TRANSITION
    total = sum(dur) - (n - 1) * TRANSITION
    return {"durations": dur, "starts": starts, "total": total, "extra_pad_per_scene": extra,
            "narration_starts": [st + LEAD + extra / 2 for st in starts]}


# ---------------- animation ----------------
def _ease(p):
    return p * p * (3 - 2 * p)


def _move(name, p):
    """returns zoom, pan_x, pan_y in normalised units for progress p"""
    e = _ease(p)
    return {"push_in": (1.0 + .16 * e, 0, 0), "pull_out": (1.16 - .16 * e, 0, 0), "pan_right": (1.1, -.05 + .1 * e, 0),
            "pan_left": (1.1, .05 - .1 * e, 0), "tilt_up": (1.1, 0, .05 - .1 * e)}[name]


def render_clip(layers, move, dur, out, W, H, fps):
    """layers: list of (PIL RGBA at 1.25x render size, depth 0..1). Parallax: nearer layers move/zoom more."""
    frames = int(round(dur * fps))
    proc = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(fps), "-i", "-",
                             "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-pix_fmt", "yuv420p", str(out)], stdin=subprocess.PIPE)
    try:
        for f in range(frames):
            p = f / max(1, frames - 1); z, px, py = _move(move, p)
            tt = f / fps
            canvas = None
            for im, depth, kind in layers:
                sw, sh = im.size; zl = 1 + (z - 1) * (.4 + .9 * depth)
                cw, ch_ = sw / zl / 1.25, sh / zl / 1.25   # crop window sized so the 1.25x source has margin
                cw, ch_ = max(cw, 1), max(ch_, 1)
                cx = sw / 2 + px * sw * (.2 + 1.2 * depth) + math.sin(tt * 1.7 + depth) * sw * .002
                cy = sh / 2 + py * sh * (.2 + 1.2 * depth) + math.sin(tt * 1.3) * sh * .002
                if kind == "char":
                    cy -= math.sin(tt * 2.2) * sh * .003   # breathing
                box = (cx - cw / 2, cy - ch_ / 2, cx + cw / 2, cy + ch_ / 2)
                fr = im.resize((W, H), Image.BILINEAR, box=box)
                if canvas is None:
                    canvas = fr
                else:
                    canvas.alpha_composite(fr)
            proc.stdin.write(canvas.convert("RGB").tobytes())
        proc.stdin.close()
        if proc.wait() != 0:
            raise RuntimeError("ffmpeg clip encode failed")
    except Exception:
        proc.kill(); raise


def animation(pid, scenes=None):
    prof = config.render_profile(); W, H, fps = prof["render_w"], prof["render_h"], prof["fps"]
    sb = util.jread(pdir(pid) / "storyboard.json"); tl = timeline(pid); util.jwrite(pdir(pid) / "timeline.json", tl)
    d = pdir(pid) / "scenes"; cache = util.jread(d / "clip_cache.json", {}); made = 0
    for i, s in enumerate(sb["scenes"]):
        n = s["n"]; clip = d / f"s{n:02d}.mp4"
        k = util.key(s["camera"], round(tl["durations"][i], 3), W, H, fps, (d / f"s{n:02d}.png").stat().st_mtime_ns)
        if cache.get(str(n)) == k and clip.exists():
            continue
        names = [("sky", .0), ("far", .15), ("mid", .4), ("fog", .55), ("char", .75), ("near", 1.0)]
        if (d / f"s{n:02d}_sky.png").exists():
            layers = [(Image.open(d / f"s{n:02d}_{nm}.png").convert("RGBA"), dp, nm) for nm, dp in names]
            if not s["show_character"]:
                layers = [l for l in layers if l[2] != "char"]
            # char layer should sit between mid/fog and near; reorder by painter order sky,far,mid,fog,char,near
        else:
            layers = [(Image.open(d / f"s{n:02d}.png").convert("RGBA"), .5, "flat")]   # diffusion image: camera move only
        render_clip(layers, s["camera"], tl["durations"][i], clip, W, H, fps)
        cache[str(n)] = k; made += 1
    util.jwrite(d / "clip_cache.json", cache)
    return {"clips_rendered": made, "render_size": [W, H], "parallax": (d / "s01_sky.png").exists(), "total_seconds": round(tl["total"], 2)}


# ---------------- subtitles ----------------
def _ass_time(t):
    h, m, s = int(t // 3600), int(t % 3600 // 60), t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def subtitles(pid, scenes=None):
    st = config.load_settings()["captions"]; o = config.load_settings()["output"]
    sb = util.jread(pdir(pid) / "storyboard.json"); tl = util.jread(pdir(pid) / "timeline.json") or timeline(pid)
    durs = util.jread(pdir(pid) / "narration" / "durations.json")["durations"]
    ed = util.jread(pdir(pid) / "caption_edits.json", {})
    lines = [f"[Script Info]\nScriptType: v4.00+\nPlayResX: {o['width']}\nPlayResY: {o['height']}\nWrapStyle: 2\n",
             "[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding",
             f"Style: Cap,{st['font']},{st['size']},&H0000E5FF,&H00FFFFFF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,6,2,2,80,80,520,1\n",
             "[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text"]
    count = 0
    for i, s in enumerate(sb["scenes"]):
        text = ed.get(str(s["n"]), s["narration"]); words = text.split()
        if not words:
            continue
        t0 = tl["narration_starts"][i]; total = durs[str(s["n"])]
        weights = [len(re.sub(r"\W", "", w)) + 1 for w in words]; sw = sum(weights); acc = 0
        wt = []
        for w, wg in zip(words, weights):
            wt.append((t0 + total * acc / sw, t0 + total * (acc + wg) / sw)); acc += wg
        for c in range(0, len(words), st["chunk_words"]):
            ch = words[c:c + st["chunk_words"]]; ts = wt[c:c + len(ch)]
            start, end = ts[0][0], ts[-1][1] + (.15 if c + len(ch) < len(words) else .35)
            k = "".join(f"{{\\kf{max(1, int((b - a) * 100))}}}{w.upper()} " for w, (a, b) in zip(ch, ts))
            lines.append(f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Cap,,0,0,0,,{k.strip()}"); count += 1
    (pdir(pid) / "subs.ass").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"events": count}


# ---------------- sound ----------------
def sound(pid, scenes=None):
    sb = util.jread(pdir(pid) / "storyboard.json"); tl = util.jread(pdir(pid) / "timeline.json")
    total = tl["total"] + .4; SR = audio.SR; n = int(total * SR)
    narr = np.zeros(n)
    for i, s in enumerate(sb["scenes"]):
        w = audio.read_wav(pdir(pid) / "narration" / f"n{s['n']:02d}.wav")
        w = w / max(1e-9, np.max(np.abs(w))) * .85
        a = int(tl["narration_starts"][i] * SR); narr[a:a + len(w)] += w[:max(0, n - a)]
    mood = sb["scenes"][0]["mood"]
    mus = audio.music(total, mood, seed=pid) * audio.duck_envelope(narr) * .55
    fx = np.zeros(n)

    def put(x, t):
        a = max(0, int(t * SR)); fx[a:a + len(x)] += x[:max(0, n - a)]
    for i, s in enumerate(sb["scenes"]):
        if i > 0:
            put(audio.whoosh(.7, i) * .5, tl["starts"][i] - .1)
        for tag in s.get("sfx", []):
            if tag == "impact": put(audio.impact() * .9, tl["starts"][i] + .02)
            if tag == "riser": put(audio.riser(min(2.2, tl["durations"][i])) * .5, tl["starts"][i])
    mix = audio.peak_limit(narr + mus + fx)
    mix[-int(.5 * SR):] *= np.linspace(1, 0, int(.5 * SR))
    audio.write_wav(pdir(pid) / "mix.wav", mix)
    return {"peak": round(float(np.max(np.abs(mix))), 3), "seconds": round(total, 2), "music": "synthesised locally (original)"}


# ---------------- assembly ----------------
def assembly(pid, scenes=None):
    o = config.load_settings()["output"]; prof = config.render_profile()
    sb = util.jread(pdir(pid) / "storyboard.json"); tl = util.jread(pdir(pid) / "timeline.json")
    n = len(sb["scenes"]); args = []
    for s in sb["scenes"]:
        args += ["-i", f"scenes/s{s['n']:02d}.mp4"]
    args += ["-i", "mix.wav"]
    f, prev, acc = [], "[0:v]", tl["durations"][0]
    for i in range(1, n):
        off = acc - TRANSITION
        f.append(f"{prev}[{i}:v]xfade=transition={'fade' if i % 2 else 'fadeblack'}:duration={TRANSITION}:offset={off:.3f}[x{i}]")
        prev = f"[x{i}]"; acc = off + tl["durations"][i]
    up = prof["render_w"] != o["width"]
    post = (f"scale={o['width']}:{o['height']}:flags=lanczos," if up else "") + "vignette=PI/5,noise=alls=5:allf=t,format=yuv420p,subtitles=subs.ass"
    f.append(f"{prev}{post}[v]")
    out = pdir(pid) / "final.mp4"; tmp = pdir(pid) / "final.partial.mp4"
    util.ffmpeg(args + ["-filter_complex", ";".join(f), "-map", "[v]", "-map", f"{n}:a", "-r", o["fps"], "-c:v", "libx264", "-preset", "medium",
                        "-crf", "18", "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-t", f"{tl['total']:.3f}", "-movflags", "+faststart", tmp.name],
                cwd=str(pdir(pid)))
    tmp.replace(out)
    sha = util.sha256(out)
    db.run("UPDATE projects SET final_sha256=? WHERE id=?", (sha, pid))
    return {"output": f"{o['width']}x{o['height']}", "rendered_at": f"{prof['render_w']}x{prof['render_h']}", "upscaled": up,
            "resolution_note": prof["note"], "sha256": sha, "seconds": round(tl["total"], 2)}


# ---------------- QC ----------------
def qc(pid, scenes=None):
    o = config.load_settings()["output"]; f = pdir(pid) / "final.mp4"; checks = []

    def add(name, ok, detail=""):
        checks.append({"name": name, "ok": bool(ok), "detail": str(detail)})
    add("file_exists", f.exists(), f)
    if not f.exists():
        return _qc_save(pid, checks)
    try:
        pr = util.ffprobe(f)
    except Exception as e:
        add("ffprobe_readable", False, e); return _qc_save(pid, checks)
    vs = next((s for s in pr["streams"] if s["codec_type"] == "video"), None); as_ = next((s for s in pr["streams"] if s["codec_type"] == "audio"), None)
    dur = float(pr["format"]["duration"])
    add("resolution", vs and (vs["width"], vs["height"]) == (o["width"], o["height"]), vs and f"{vs['width']}x{vs['height']}")
    add("aspect_9_16", vs and abs(vs["width"] / vs["height"] - 9 / 16) < .002)
    add("video_codec_h264", vs and vs["codec_name"] == "h264" and vs.get("pix_fmt") == "yuv420p", vs and f"{vs['codec_name']}/{vs.get('pix_fmt')}")
    num, den = (vs["r_frame_rate"].split("/") + ["1"])[:2]
    add("fps", vs and abs(int(num) / int(den) - o["fps"]) < .01, vs and vs["r_frame_rate"])
    add("audio_present_aac", as_ and as_["codec_name"] == "aac", as_ and as_["codec_name"])
    add("duration_in_range", o["min_seconds"] <= dur <= o["max_seconds"], f"{dur:.2f}s (allowed {o['min_seconds']}-{o['max_seconds']})")
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(f), "-f", "null", "-"], capture_output=True, text=True)
    add("decodes_without_errors", r.returncode == 0 and not r.stderr.strip(), r.stderr[:200])
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(f), "-af", "volumedetect", "-vn", "-f", "null", "-"], capture_output=True, text=True)
    mean = re.search(r"mean_volume: (-?[\d.]+|-inf)", r.stderr); mx = re.search(r"max_volume: (-?[\d.]+)", r.stderr)
    mean_v = float(mean.group(1)) if mean and mean.group(1) != "-inf" else -99; max_v = float(mx.group(1)) if mx else 0
    add("audio_not_silent", mean_v > -45, f"mean {mean_v} dB")
    add("audio_no_clipping", max_v < -0.3, f"peak {max_v} dB")
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(f), "-vf", "freezedetect=n=-60dB:d=1.5,blackdetect=d=0.8:pix_th=0.05", "-an", "-f", "null", "-"], capture_output=True, text=True)
    frozen = re.findall(r"freeze_duration: ([\d.]+)", r.stderr); black = re.findall(r"black_duration:([\d.]+)", r.stderr)
    add("no_frozen_video", sum(map(float, frozen)) < 1.0, f"{len(frozen)} freeze segments")
    add("no_blank_video", sum(map(float, black)) < 1.0, f"{len(black)} black segments")
    sb = util.jread(pdir(pid) / "storyboard.json", {"scenes": []})
    missing = [s["n"] for s in sb["scenes"] if not (pdir(pid) / "scenes" / f"s{s['n']:02d}.mp4").exists()]
    add("all_scenes_present", not missing and len(sb["scenes"]) >= 4, f"missing {missing}")
    ev = re.findall(r"Dialogue: \d+,([\d:.]+),([\d:.]+),", (pdir(pid) / "subs.ass").read_text(encoding="utf-8")) if (pdir(pid) / "subs.ass").exists() else []
    to = lambda t: sum(float(x) * m for x, m in zip(t.split(":"), (3600, 60, 1)))
    ok = bool(ev) and all(0 <= to(a) < to(b) <= dur + .05 for a, b in ev) and all(to(ev[i][0]) >= to(ev[i - 1][0]) for i in range(1, len(ev)))
    add("subtitle_timing", ok, f"{len(ev)} events")
    sha = util.sha256(f)
    dup = db.one("SELECT id FROM projects WHERE final_sha256=? AND id<>?", (sha, pid))
    add("not_duplicate_output", not dup, dup and f"identical to project {dup['id']}")
    tts_be = (util.jread(pdir(pid) / "narration" / "durations.json") or {}).get("backend")
    add("real_narration", tts_be in ("piper", "espeak"), tts_be)
    return _qc_save(pid, checks)


def _qc_save(pid, checks):
    res = {"technical_passed": all(c["ok"] for c in checks), "checks": checks,
           "creative_review": "NOT ASSESSED — automated checks verify technical validity only. A human must judge story, visuals and pacing."}
    util.jwrite(pdir(pid) / "qc.json", res)
    return {"technical_passed": res["technical_passed"], "failed": [c["name"] for c in checks if not c["ok"]]}


# ---------------- thumbnail ----------------
def thumbnail(pid, scenes=None):
    p = project(pid); sb = util.jread(pdir(pid) / "storyboard.json"); idx = min(2, len(sb["scenes"]) - 1)
    tl = util.jread(pdir(pid) / "timeline.json"); t = tl["starts"][idx] + tl["durations"][idx] * .55
    frame = pdir(pid) / "thumb_frame.png"
    util.ffmpeg(["-ss", f"{t:.2f}", "-i", "final.mp4", "-frames:v", "1", frame.name], cwd=str(pdir(pid)))
    im = Image.open(frame).convert("RGB"); W, H = im.size
    title = (util.jread(pdir(pid) / "metadata.json") or {}).get("title") or p["title"]
    words = title.upper().split()[:6]
    d = ImageDraw.Draw(im); fnt = util.font(int(W * .12))
    lines, cur = [], ""
    for w in words:
        if d.textlength((cur + " " + w).strip(), font=fnt) > W * .86 and cur:
            lines.append(cur); cur = w
        else:
            cur = (cur + " " + w).strip()
    lines.append(cur)
    y = int(H * .1)
    for ln in lines[:4]:
        x = (W - d.textlength(ln, font=fnt)) / 2
        d.text((x, y), ln, font=fnt, fill=(255, 229, 0), stroke_width=int(W * .012), stroke_fill=(0, 0, 0)); y += int(W * .15)
    im.save(pdir(pid) / "thumbnail.jpg", quality=92)
    bg = im.resize((1280, 1280 * H // W)).crop((0, 400, 1280, 1120)).filter(ImageFilter.GaussianBlur(18))
    inner = im.resize((int(720 * W / H), 720)); bg.paste(inner, ((1280 - inner.width) // 2, 0)); bg.save(pdir(pid) / "thumbnail_wide.jpg", quality=90)
    return {"thumbnail": "thumbnail.jpg", "wide": "thumbnail_wide.jpg", "frame_time": round(t, 2)}


# ---------------- metadata ----------------
def metadata(pid, scenes=None):
    p = project(pid); sc = util.jread(pdir(pid) / "script.json"); st = config.load_settings()
    existing = util.jread(pdir(pid) / "metadata.json", {})
    if existing.get("edited"):
        return {"kept": "human-edited metadata preserved"}
    idea = json.loads(p["concept"]); title = sc["title"].strip().rstrip(".")
    title = (title if len(title) <= 80 else title[:79]) + " #shorts"
    desc = (f"{idea['hook']}\n\n{idea['logline']}\n\n"
            "Made with AI: visuals, narration and music are AI-generated/synthesised. This is a work of fiction.\n\n#shorts #story #cinematic #mystery")
    meta = {"title": title, "description": desc, "tags": ["shorts", "short film", "cinematic", "story", idea.get("genre", "mystery"), "AI generated"],
            "category_id": st["publish"]["category_id"], "made_for_kids": False,
            "contains_synthetic_media": st["publish"]["synthetic_content_disclosure"], "edited": False}
    util.jwrite(pdir(pid) / "metadata.json", meta)
    return {"title": title}


STAGE_FUNCS = {"script": script, "storyboard": storyboard, "characters": characters_stage, "visuals": visuals, "voiceover": voiceover,
               "animation": animation, "subtitles": subtitles, "sound": sound, "assembly": assembly, "qc": qc, "metadata": metadata, "thumbnail": thumbnail}
