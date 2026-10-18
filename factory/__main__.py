import argparse, json, sys
from . import config, db, characters, pipeline, ideas


def main():
    ap = argparse.ArgumentParser(prog="factory"); sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init"); sub.add_parser("serve")
    i = sub.add_parser("ideas"); i.add_argument("-n", type=int, default=6)
    n = sub.add_parser("new"); n.add_argument("--idea", type=int)
    r = sub.add_parser("run"); r.add_argument("pid", type=int)
    s = sub.add_parser("stage"); s.add_argument("pid", type=int); s.add_argument("stage"); s.add_argument("--scenes", default="")
    a = ap.parse_args()
    db.init(); characters.ensure_defaults()
    if a.cmd == "init": print("initialised", config.DB_PATH)
    elif a.cmd == "ideas":
        for it, in [(x,) for x in ideas.generate(a.n)[0]]: print(it["id"], it["score"], it["status"], it["title"])
    elif a.cmd == "new":
        idea_id = a.idea or next(x["id"] for x in db.q("SELECT id FROM ideas WHERE status='new' ORDER BY score DESC"))
        print("project", pipeline.create_project(idea_id=idea_id))
    elif a.cmd == "run": print(pipeline.produce_inprocess(a.pid))
    elif a.cmd == "stage":
        sc = [int(x) for x in a.scenes.split(",") if x] or None
        print(json.dumps(pipeline.run_stage(a.pid, a.stage, sc), default=str))
    elif a.cmd == "serve":
        import uvicorn
        st = config.load_settings()["server"]; uvicorn.run("factory.server:app", host=st["host"], port=st["port"])


if __name__ == "__main__":
    main()
