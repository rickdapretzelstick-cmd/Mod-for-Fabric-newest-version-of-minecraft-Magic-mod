"""LLM provider: local Ollama when reachable, otherwise a deterministic template writer.
The template writer is a fallback so the pipeline always runs; its stories are formulaic."""
import json, random, re
import requests
from .. import config


def ollama_available(url):
    try:
        return requests.get(url + "/api/tags", timeout=2).ok
    except Exception:
        return False


def generate_json(prompt: str, system: str = "", fallback=None):
    """Returns (data, backend_used). fallback is a callable producing data when Ollama is unavailable."""
    s = config.load_settings()["llm"]
    if s["backend"] in ("auto", "ollama") and ollama_available(s["ollama_url"]):
        r = requests.post(s["ollama_url"] + "/api/generate", timeout=s["timeout_s"], json={
            "model": s["model"], "prompt": prompt, "system": system, "stream": False,
            "format": "json", "keep_alive": 0, "options": {"temperature": 0.9}})
        r.raise_for_status()
        txt = r.json()["response"]
        m = re.search(r"\{.*\}|\[.*\]", txt, re.S)
        return json.loads(m.group(0) if m else txt), "ollama:" + s["model"]
    if s["backend"] == "ollama":
        raise RuntimeError("llm.backend=ollama but Ollama is not reachable at " + s["ollama_url"])
    if fallback is None:
        raise RuntimeError("No LLM available")
    return fallback(), "template"


# ---- template fallback content ----
SETTINGS = [("an abandoned lighthouse at the edge of a frozen sea", "dusk"),
            ("a night market floating above endless fog", "night"),
            ("a drowned city whose streetlights still glow", "night"),
            ("a desert railway station that no train has visited in decades", "dawn"),
            ("a forest where every tree hums one note", "night"),
            ("a rooftop garden on the last tower of a ruined city", "dusk")]
SECRETS = ["a door that only appears when no one is looking", "a bell that rings one second before disaster",
           "a map that redraws itself each night", "a lantern that shows the past", "a second shadow that moves first",
           "a radio that broadcasts tomorrow"]
TWISTS = ["the stranger was the hero's own future self", "the danger was protecting them all along",
          "the place had been waiting for exactly them", "the warning was a gift, not a threat",
          "the hero had already been here, and forgot"]
GENRES = ["mystery", "fantasy", "sci-fi", "gentle horror", "adventure"]


def template_ideas(n, characters, rng=None):
    rng = rng or random.Random()
    out = []
    for _ in range(n):
        (place, tod), sec, tw = rng.choice(SETTINGS), rng.choice(SECRETS), rng.choice(TWISTS)
        ch = rng.choice(characters) if characters else None
        who = ch["name"] if ch else "a lone traveler"
        out.append({"title": f"{sec.split(' that')[0].capitalize()} in {place.split(' at ')[0].split(' of ')[0].replace('an ','').replace('a ','')}".strip().capitalize(),
                    "logline": f"{who} reaches {place} and finds {sec}. In the end, {tw}.",
                    "hook": f"Nobody ever returns from {place}. {who} did.",
                    "genre": rng.choice(GENRES), "character_id": ch["id"] if ch else None,
                    "place": place, "time_of_day": tod, "secret": sec, "twist": tw})
    return out
