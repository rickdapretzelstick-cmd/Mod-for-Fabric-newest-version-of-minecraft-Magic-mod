"""Reusable character library: permanent ID, appearance text, colours, seed, reference images."""
import json, time
from . import config, db

DEFAULTS = [
    {"id": "char_wren", "name": "Wren Alder", "appearance": "slender young cartographer, short windswept dark hair, sharp green eyes, freckles, thoughtful expression",
     "clothing": "long rust-red travel coat with brass buttons, wide-brim pointed hat, satchel", "colors": {"cloth": "#c8492f", "accent": "#f2c14e"},
     "face": "angular jaw, high cheekbones, small scar over left eyebrow", "personality": "curious, stubborn, quietly brave", "style": "cinematic dark fantasy illustration, painterly, moody volumetric lighting", "seed": 4242},
    {"id": "char_ion", "name": "Ion Vasquez", "appearance": "tall lighthouse keeper in his fifties, grey stubble, tired kind eyes",
     "clothing": "teal oilskin raincoat, knit cap, lantern in hand", "colors": {"cloth": "#2f8f9d", "accent": "#ffd166"},
     "face": "weathered, deep laugh lines, broken nose", "personality": "calm, superstitious, dry humour", "style": "cinematic moody sea-noir illustration, painterly", "seed": 1717},
    {"id": "char_sable", "name": "Sable Okoye", "appearance": "young engineer with braided hair and round glasses, determined look",
     "clothing": "violet utility jacket with glowing cuffs, tool belt", "colors": {"cloth": "#7b4fbf", "accent": "#6ee7d8"},
     "face": "round face, dimples, bright amber eyes", "personality": "inventive, anxious, loyal", "style": "cinematic retro-futurist illustration, neon rim lighting", "seed": 909},
]


def ensure_defaults():
    for c in DEFAULTS:
        if not db.one("SELECT id FROM characters WHERE id=?", (c["id"],)):
            upsert(c)


def upsert(c):
    db.run("""INSERT INTO characters(id,name,appearance,clothing,colors,face,personality,style,seed,refs,created_at)
              VALUES(?,?,?,?,?,?,?,?,?,?,?)
              ON CONFLICT(id) DO UPDATE SET name=excluded.name, appearance=excluded.appearance, clothing=excluded.clothing,
              colors=excluded.colors, face=excluded.face, personality=excluded.personality, style=excluded.style, seed=excluded.seed""",
           (c["id"], c["name"], c.get("appearance", ""), c.get("clothing", ""), json.dumps(c.get("colors", {})), c.get("face", ""),
            c.get("personality", ""), c.get("style", ""), int(c.get("seed", 1)), json.dumps(c.get("refs", [])), time.time()))


def get(cid):
    r = db.one("SELECT * FROM characters WHERE id=?", (cid,))
    if r:
        r["colors"] = json.loads(r["colors"] or "{}"); r["refs"] = json.loads(r["refs"] or "[]")
    return r


def list_all():
    return [get(r["id"]) for r in db.q("SELECT id FROM characters ORDER BY created_at, id")]


def prompt_prefix(c):
    return f"{c['name']}, {c['appearance']}, wearing {c['clothing']}, {c['face']}, {c['style']}"


def add_ref(cid, rel_path):
    c = get(cid)
    if rel_path not in c["refs"]:
        c["refs"].append(rel_path)
        db.run("UPDATE characters SET refs=? WHERE id=?", (json.dumps(c["refs"]), cid))
