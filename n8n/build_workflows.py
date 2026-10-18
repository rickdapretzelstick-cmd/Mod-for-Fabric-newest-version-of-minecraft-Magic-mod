"""Generates the four n8n workflow JSON files. Re-run after editing: python n8n/build_workflows.py
All calls go to the local API (http://127.0.0.1:8765). The X-Automation-Token comes from the n8n env var FACTORY_TOKEN."""
import json, uuid
from pathlib import Path

BASE = "http://127.0.0.1:8765"
HDR = {"parameters": [{"name": "X-Automation-Token", "value": "={{ $env.FACTORY_TOKEN }}"}]}
OUT = Path(__file__).parent / "workflows"


def node(name, type_, params, pos, version=1, **extra):
    return {"id": str(uuid.uuid4()), "name": name, "type": type_, "typeVersion": version, "position": pos, "parameters": params, **extra}


def http(name, method, path, pos, query=None, body=None, timeout=3700000, retries=True):
    p = {"method": method, "url": f"={BASE}{path}", "sendHeaders": True, "headerParameters": HDR, "options": {"timeout": timeout}}
    if query:
        p["sendQuery"] = True; p["queryParameters"] = {"parameters": [{"name": k, "value": v} for k, v in query.items()]}
    if body is not None:
        p["sendBody"] = True; p["specifyBody"] = "json"; p["jsonBody"] = body
    extra = {"retryOnFail": True, "maxTries": 3, "waitBetweenTries": 5000} if retries else {}
    return node(name, "n8n-nodes-base.httpRequest", p, pos, 4.2, **extra)


def wire(nodes, chain):
    conns = {}
    for a, b in zip(chain, chain[1:]):
        conns.setdefault(a, {"main": [[]]})["main"][0].append({"node": b, "type": "main", "index": 0})
    return conns


def save(fname, name, nodes, conns):
    wf = {"name": name, "nodes": nodes, "connections": conns, "active": False, "settings": {"executionOrder": "v1"}, "pinData": {}, "meta": {"templateCredsSetupCompleted": True}}
    (OUT / fname).write_text(json.dumps(wf, indent=2))


def main():
    OUT.mkdir(exist_ok=True)
    # ---- A: content planning ----
    n = [node("Daily schedule", "n8n-nodes-base.scheduleTrigger", {"rule": {"interval": [{"field": "hours", "hoursInterval": 12}]}}, [0, 0], 1.2),
         node("Manual run", "n8n-nodes-base.manualTrigger", {}, [0, 160]),
         http("Generate & score ideas (dedupe in DB)", "POST", "/api/auto/ideas/generate", [260, 80], query={"count": "8"}),
         node("Pick strongest (not duplicates, above min score)", "n8n-nodes-base.code", {"jsCode":
              "const r = $input.first().json; const min = r.min_score;\n"
              "return r.ideas.filter(i => i.status === 'new' && i.score >= min).sort((a,b)=>b.score-a.score).slice(0,2).map(i => ({json:{idea_id:i.id, title:i.title, score:i.score}}));"}, [520, 80], 2),
         http("Create project (script+storyboard queued)", "POST", "/api/auto/projects", [780, 80], body='={{ JSON.stringify({idea_id: $json.idea_id}) }}', retries=False),
         http("Write script", "POST", "=/api/auto/projects/{{ $json.id }}/stages/script/run", [1040, 80]),
         http("Create storyboard", "POST", "=/api/auto/projects/{{ $('Create project (script+storyboard queued)').item.json.id }}/stages/storyboard/run", [1300, 80])]
    n[5]["parameters"]["url"] = f"={BASE}/api/auto/projects/{{{{ $json.id }}}}/stages/script/run"
    n[6]["parameters"]["url"] = f"={BASE}/api/auto/projects/{{{{ $('Create project (script+storyboard queued)').item.json.id }}}}/stages/storyboard/run"
    chain = ["Daily schedule", n[2]["name"], n[3]["name"], n[4]["name"], n[5]["name"], n[6]["name"]]
    c = wire(n, chain); c.setdefault("Manual run", {"main": [[{"node": n[2]["name"], "type": "main", "index": 0}]]})
    # 'Queue approved concepts': projects are created in 'queued' state; Workflow B picks them up.
    save("A_content_planning.json", "A - Content Planning", n, c)

    # ---- B: video production ----
    stages = [("Load script & divide into scenes", "script"), ("Storyboard scenes", "storyboard"), ("Character & scene design", "characters"),
              ("Generate visual assets", "visuals"), ("Generate narration", "voiceover"), ("Animate scenes", "animation"),
              ("Generate subtitles", "subtitles"), ("Add sound effects & music", "sound"), ("Assemble final video", "assembly"),
              ("Automated QC", "qc"), ("Title & description", "metadata"), ("Create thumbnail", "thumbnail")]
    n = [node("Every 10 minutes", "n8n-nodes-base.scheduleTrigger", {"rule": {"interval": [{"field": "minutes", "minutesInterval": 10}]}}, [0, 0], 1.2),
         node("Manual run", "n8n-nodes-base.manualTrigger", {}, [0, 160]),
         http("Next queued project", "GET", "/api/auto/queue/next", [260, 80], retries=False),
         node("Anything queued?", "n8n-nodes-base.if", {"conditions": {"options": {"caseSensitive": True, "typeValidation": "loose"}, "combinator": "and",
              "conditions": [{"id": "1", "leftValue": "={{ $json.project_id }}", "rightValue": "", "operator": {"type": "number", "operation": "exists", "singleValue": True}}]}}, [520, 80], 2.2)]
    chain = ["Every 10 minutes", "Next queued project", "Anything queued?"]
    x = 780
    for label, st in stages:
        n.append(http(label, "POST", f"/api/auto/projects/{{{{ $('Next queued project').item.json.project_id }}}}/stages/{st}/run", [x, 80], query={"wait": "true"}))
        n[-1]["parameters"]["url"] = f"={BASE}/api/auto/projects/{{{{ $('Next queued project').item.json.project_id }}}}/stages/{st}/run"
        chain.append(label); x += 260
    n.append(http("Save package & queue for approval", "POST", "=/api/auto/projects/{{ $('Next queued project').item.json.project_id }}/finalize", [x, 80]))
    n[-1]["parameters"]["url"] = f"={BASE}/api/auto/projects/{{{{ $('Next queued project').item.json.project_id }}}}/finalize"
    chain.append("Save package & queue for approval")
    c = wire(n, chain[:3]); c["Manual run"] = {"main": [[{"node": "Next queued project", "type": "main", "index": 0}]]}
    c["Anything queued?"] = {"main": [[{"node": chain[3], "type": "main", "index": 0}], []]}
    c.update(wire(n, chain[3:]))
    save("B_video_production.json", "B - Video Production", n, c)

    # ---- C: approval (human in the dashboard; n8n only notifies) ----
    n = [node("Every 15 minutes", "n8n-nodes-base.scheduleTrigger", {"rule": {"interval": [{"field": "minutes", "minutesInterval": 15}]}}, [0, 0], 1.2),
         http("Videos awaiting approval", "GET", "/api/auto/approvals/pending", [260, 0], retries=False),
         node("Any pending?", "n8n-nodes-base.if", {"conditions": {"options": {"caseSensitive": True, "typeValidation": "loose"}, "combinator": "and",
              "conditions": [{"id": "1", "leftValue": "={{ $json.id }}", "rightValue": "", "operator": {"type": "number", "operation": "exists", "singleValue": True}}]}}, [520, 0], 2.2),
         http("Post reminder to dashboard", "POST", "/api/auto/notify", [780, 0], body='={{ JSON.stringify({message: "Awaiting your approval: " + $json.title, project_id: $json.id}) }}', retries=False),
         node("NOTE", "n8n-nodes-base.stickyNote", {"content": "APPROVE / REVISE / REJECT happen only in the dashboard (http://127.0.0.1:8765). The automation token used by n8n is refused by those endpoints, so this workflow cannot approve anything."}, [0, 200])]
    c = wire(n, ["Every 15 minutes", n[1]["name"], "Any pending?"]); c["Any pending?"] = {"main": [[{"node": n[3]["name"], "type": "main", "index": 0}], []]}
    save("C_approval_notifications.json", "C - Approval (human decision in dashboard)", n, c)

    # ---- D: publishing ----
    n = [node("Every 30 minutes", "n8n-nodes-base.scheduleTrigger", {"rule": {"interval": [{"field": "minutes", "minutesInterval": 30}]}}, [0, 0], 1.2),
         node("Manual run", "n8n-nodes-base.manualTrigger", {}, [0, 160]),
         http("Approved & not yet uploaded", "GET", "/api/auto/publish/ready", [260, 80], retries=False),
         http("Publish (server re-verifies approval, hash, duplicates)", "POST", "=/api/auto/projects/{{ $json.id }}/publish", [520, 80], retries=False),
         http("Refresh analytics", "POST", "/api/auto/analytics/refresh", [780, 80], retries=False)]
    n[3]["parameters"]["url"] = f"={BASE}/api/auto/projects/{{{{ $json.id }}}}/publish"
    n[3]["continueOnFail"] = True
    c = wire(n, ["Every 30 minutes", n[2]["name"], n[3]["name"], n[4]["name"]]); c["Manual run"] = {"main": [[{"node": n[2]["name"], "type": "main", "index": 0}]]}
    save("D_publishing.json", "D - Publishing", n, c)
    print("wrote", [p.name for p in OUT.glob("*.json")])


if __name__ == "__main__":
    main()
