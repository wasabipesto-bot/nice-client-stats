#!/usr/bin/env python3
"""jobq.py add <jobs.jsonl>   -- insert jobs (idempotent on key; existing jobs untouched)
   jobq.py status             -- counts by kind/status
   jobq.py requeue <status>   -- put jobs with that status back to pending
   jobq.py reprio <jobs.jsonl> -- update prio of pending jobs by key"""
import json, sqlite3, sys
from collections import Counter
from pathlib import Path

c = sqlite3.connect(Path(__file__).resolve().parent / "queue.db", timeout=60, isolation_level=None)
c.execute("PRAGMA journal_mode=WAL")
c.execute("""CREATE TABLE IF NOT EXISTS jobs (id INTEGER PRIMARY KEY, key TEXT UNIQUE, prio INTEGER, kind TEXT,
             client TEXT, mode TEXT, base INTEGER, needs_8650 INTEGER, spec TEXT, status TEXT DEFAULT 'pending',
             worker TEXT, started REAL, finished REAL, note TEXT)""")
cmd = sys.argv[1]
if cmd == "add":
    n = 0
    for l in open(sys.argv[2]):
        j = json.loads(l)
        cur = c.execute("INSERT OR IGNORE INTO jobs (key, prio, kind, client, mode, base, needs_8650, spec) "
                        "VALUES (?,?,?,?,?,?,?,?)", (j["key"], j["prio"], j["kind"], j["client"], j["mode"], j["base"],
                                                     int(j["needs_8650"]), json.dumps(j["spec"])))
        n += cur.rowcount
    print("added", n)
elif cmd == "sync":  # make pending jobs match the file: drop pending not in it, add new, update prio
    want = {}
    for l in open(sys.argv[2]):
        j = json.loads(l); want[j["key"]] = j
    have = {k for (k,) in c.execute("SELECT key FROM jobs")}
    gone = [k for (k,) in c.execute("SELECT key FROM jobs WHERE status = 'pending'") if k not in want]
    c.executemany("DELETE FROM jobs WHERE key = ? AND status = 'pending'", [(k,) for k in gone])
    for k, j in want.items():
        if k in have:
            c.execute("UPDATE jobs SET prio = ?, spec = ? WHERE key = ? AND status = 'pending'", (j["prio"], json.dumps(j["spec"]), k))
        else:
            c.execute("INSERT INTO jobs (key, prio, kind, client, mode, base, needs_8650, spec) VALUES (?,?,?,?,?,?,?,?)",
                      (k, j["prio"], j["kind"], j["client"], j["mode"], j["base"], int(j["needs_8650"]), json.dumps(j["spec"])))
    print("dropped", len(gone), "added", len(set(want) - have))
elif cmd == "reprio":
    for l in open(sys.argv[2]):
        j = json.loads(l)
        c.execute("UPDATE jobs SET prio = ? WHERE key = ? AND status = 'pending'", (j["prio"], j["key"]))
elif cmd == "requeue":
    print(c.execute("UPDATE jobs SET status = 'pending', worker = NULL WHERE status = ?", (sys.argv[2],)).rowcount)
elif cmd == "status":
    rows = c.execute("SELECT kind, prio, status, count(*) FROM jobs GROUP BY kind, prio, status").fetchall()
    for r in rows:
        print(*r)
    print(Counter(r[0] for r in c.execute("SELECT status FROM jobs")))
