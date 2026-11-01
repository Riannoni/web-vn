#!/usr/bin/env python3
"""Deterministic, zero-model curated P0 backlog staging. Never reviews a task.
Caller must approve entries in task-catalog.json before installation.
"""
import argparse
import json
from pathlib import Path
import teamctl as m
import coordinator as c

def replenish(root, catalog):
    root=Path(root).resolve()
    if not (root/"state/team.sqlite3").is_file():
        raise FileNotFoundError("not initialized")
    specs=json.loads(Path(catalog).read_text())
    # An empty approved catalog parks future seeding; existing tasks are untouched.
    if not isinstance(specs,list) or len(specs)>32:
        raise ValueError("invalid curated catalog")
    ids=[s["id"] for s in specs]
    if len(ids)!=len(set(ids)):
        raise ValueError("duplicate catalog ids")
    db=m.open_db()
    changes=[]
    try:
        db.execute("BEGIN IMMEDIATE")
        state=db.execute("SELECT v FROM team_meta WHERE k='state'").fetchone()
        if not state or state[0]!="active":
            db.execute("ROLLBACK")
            return {"state":"inactive","enqueued":[]}
        existing={x["id"]:x["state"] for x in db.execute("SELECT id,state FROM task")}
        counts={lane:db.execute("SELECT COUNT(*) FROM task WHERE state='pending' AND id LIKE ?",(lane+"-%",)).fetchone()[0] for lane in m.LANES}
        # Treat each entry as a preapproved exact task: do not LLM-generate, mutate
        # existing rows, or assume a review_pending/blocked dependency is done.
        for s in specs:
            lane=s["lane"]
            if lane not in m.LANES or not s["id"].startswith(lane+"-"):
                raise ValueError("invalid lane/task")
            if s["id"] in existing or counts[lane]>=2:
                continue
            paths=s["paths"]
            m._checked_scope(lane,paths)
            deps=s.get("dependencies",[])
            if not isinstance(deps,list) or len(deps)>12 or s["id"] in deps or len(set(deps))!=len(deps):
                raise ValueError("bad dependencies")
            if any(dep not in existing for dep in deps):
                continue
            if any(existing[dep]=="blocked" for dep in deps):
                continue
            if not isinstance(s["instructions"],str) or len(s["instructions"])<70 or not s["goal"].startswith("render-v1 #20"):
                raise ValueError("not approved source-only P0")
            if not isinstance(s["priority"],int) or not 1<=s["priority"]<=100:
                raise ValueError("priority")
            if any(not p.endswith((".py",".test.py")) for p in paths):
                raise ValueError("source-only scope required")
            c.add(db,s["id"],"source_inventory",paths,deps,goal=s["goal"],priority=s["priority"])
            db.execute("UPDATE task SET action=? WHERE id=?",(s["instructions"],s["id"]))
            existing[s["id"]]="pending"
            counts[lane]+=1
            changes.append(s["id"])
        db.execute("COMMIT")
        return {"state":"active","enqueued":changes}
    except BaseException:
        if db.in_transaction: db.execute("ROLLBACK")
        raise
    finally:
        db.close()

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--root",type=Path,required=True)
    p.add_argument("--catalog",type=Path,required=True)
    args=p.parse_args()
    print(json.dumps(replenish(args.root,args.catalog),sort_keys=True))
