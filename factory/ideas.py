"""Idea generation, hook scoring, duplicate detection."""
import json, random, re, time
from . import db, characters
from .providers import llm

STOP = set("a an the of in on at to and or is are was were it its that this with for from by as be has had have who what when where nobody ever".split())
CURIOSITY = ["secret", "never", "nobody", "last", "only", "hidden", "impossible", "forgot", "waiting", "dark", "before", "behind", "disappear"]


def tokens(text):
    return {w for w in re.findall(r"[a-z']+", text.lower()) if w not in STOP and len(w) > 2}


def fingerprint(idea):
    return " ".join(sorted(tokens(idea["title"] + " " + idea["logline"])))


def similarity(a, b):
    A, B = set(a.split()), set(b.split())
    return len(A & B) / max(1, len(A | B))


def heuristic_score(idea):
    """Transparent heuristic (NOT a measure of real audience appeal; real signal comes from analytics)."""
    hook = idea["hook"]; words = len(hook.split())
    d = {"hook_length": 2.0 if 6 <= words <= 14 else 1.0,
         "curiosity_words": min(3.0, sum(w in hook.lower() for w in CURIOSITY) * 1.0),
         "has_twist": 2.0 if idea.get("twist") or "twist" in idea["logline"].lower() or "in the end" in idea["logline"].lower() else 0.5,
         "character": 1.5 if idea.get("character_id") else 0.5,
         "specificity": min(1.5, len(tokens(idea["logline"])) / 10)}
    return round(min(10, sum(d.values())), 2), d


def generate(count=6):
    chars = characters.list_all()
    prompt = ("Write %d ORIGINAL short-film ideas for 40-second vertical cinematic YouTube Shorts as a JSON list. Each item: "
              "title, logline, hook (one gripping opening line), genre, place, time_of_day (dusk|night|dawn), secret, twist, "
              "character_id (one of %s). Do not use existing franchises, real events, or real people." % (count, [c["id"] for c in chars]))
    def fb():
        return llm.template_ideas(count, chars)
    data, backend = llm.generate_json(prompt, "You are a screenwriter of original cinematic shorts.", fb)
    if isinstance(data, dict):
        data = data.get("ideas", [data])
    existing = db.q("SELECT id,fingerprint FROM ideas")
    out = []
    for it in data[:count]:
        it.setdefault("hook", it.get("logline", "")[:80]); it.setdefault("genre", "mystery")
        it.setdefault("character_id", None)
        fp = fingerprint(it)
        dup = next((e["id"] for e in existing if similarity(fp, e["fingerprint"] or "") >= 0.55), None)
        score, detail = heuristic_score(it)
        detail["scored_by"] = "heuristic"
        iid = db.run("INSERT INTO ideas(title,logline,hook,genre,character_id,score,score_detail,fingerprint,duplicate_of,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                     (it.get("title", "Untitled"), it.get("logline", ""), it["hook"], it["genre"], it["character_id"], score,
                      json.dumps({**detail, "raw": it, "backend": backend}), fp, dup, "duplicate" if dup else "new", time.time()))
        existing.append({"id": iid, "fingerprint": fp})
        out.append(db.one("SELECT * FROM ideas WHERE id=?", (iid,)))
    return out, backend
