#!/usr/bin/env python3
"""Jobs for a run over new commits: new-commits.tsv -> jobs.jsonl (load with `jobq.py add jobs.jsonl`).

  enqueue.py new-commits.tsv --release SHA [--milestones SHA,SHA,...]

prio 0   release: production-size b62 1e17 fields (the three long fields start first)
prio 1   release: production-size b60/b58/b57; field-size ladder 1e16 at b62/b64
prio 2   milestones: production-size b60
prio 3   ladder 1e15; milestones b58/b57
prio 4   ladder 1e14
prio 10/20  capped (detailed + niceonly) for every commit: b40/50/60, then every other base
prio 60  two extra reps at b40/50/60 for every commit
Same corpus, specs and rules as the earlier runs (past-runs/). Run 3 used
`enqueue.py commits-run3.tsv --release 8c267de --milestones e07f11f,a7a59c1,59828d6`."""
import argparse, json, random
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ap = argparse.ArgumentParser()
ap.add_argument("commits")
ap.add_argument("--release", required=True, help="short sha that gets the full production-size set")
ap.add_argument("--milestones", default="", help="comma-separated short shas that get b57/b58/b60")
args = ap.parse_args()
corpus = json.loads((HERE / "corpus/full.json").read_text())
lad = json.loads((HERE / "corpus/ladder.json").read_text())
TOP3 = {40, 50, 60}
TAG = args.release
MILESTONES = [m for m in args.milestones.split(",") if m]

commits = []
for l in Path(args.commits).read_text().splitlines():
    repo, sha, date, why, subj = l.split("\t")
    if repo == "repo":
        continue
    commits.append({"repo": repo, "sha": sha, "date": date, "why": why, "name": f"{repo}-{date}-{sha}"})
by_sha = {c["sha"]: c for c in commits}
assert TAG in by_sha and all(m in by_sha for m in MILESTONES)
jobs = []


def add(prio, kind, c, mode, b, spec, key_extra=""):
    jobs.append({"key": f"{kind}:{c['name']}:{mode}:{b}{key_extra}", "prio": prio, "kind": kind,
                 "client": c["name"], "mode": mode, "base": b, "spec": spec, "needs_8650": False})


def capped(prio, c, bases, rep=0):
    # Join-era clients only (all run-3 commits): enqueue.py's rules for date >= JOIN_DATE.
    for b in bases:
        e = corpus["bases"][str(b)]
        lo, hi = e["range"]
        dcap = min(10**9, hi - lo)
        add(prio, "capped", c, "detailed", b, {"strata": [{"stratum": 0, "pred": 0, "start": e["detailed_start"]}],
            "calibrate": True, "cap": dcap, "field_size": dcap, "rep": rep}, f":r{rep}")
        if b >= 65 or "fields5" not in e:  # no niceonly above 64 for join-era builds (run 1 rule)
            continue
        W = e["field_size"]
        add(prio, "capped", c, "niceonly", b, {"strata": e["fields5"], "calibrate": False, "field_size": W,
            "rep": rep, "timeout": 6 * 3600}, f":r{rep}")


def real(prio, c, b):
    r = corpus["real"][str(b)]
    for f in r["fields"]:
        add(prio, "real", c, "niceonly", b,
            {"strata": [f], "field_size": r["field_size"], "warmup": False, "timeout": 40 * 3600}, f":s{f['stratum']}")


tag = by_sha[TAG]
real(0, tag, 62)
for b in (60, 58, 57):
    real(1, tag, b)
for m in MILESTONES:
    real(2, by_sha[m], 60)
    real(3, by_sha[m], 58)
    real(3, by_sha[m], 57)
for k, L in lad.items():
    b, e = L["base"], int(k.split(":")[1])
    if e == 17:
        continue  # the b64 1e17 check is not repeated: the cost model held to -0.9 % in run 2
    for f in L["fields"]:
        jobs.append({"key": f"ladder:{tag['name']}:{b}:1e{e}:s{f['stratum']}", "prio": {16: 1, 15: 3, 14: 4}[e],
                     "kind": "ladder", "client": tag["name"], "mode": "niceonly", "base": b, "needs_8650": False,
                     "spec": {"strata": [f], "field_size": L["field_size"], "warmup": False, "timeout": 40 * 3600}})

all_bases = [int(b) for b in corpus["bases"]]
g = commits[:]
random.Random(3).shuffle(g)
for c in g:
    capped(10, c, [b for b in all_bases if b in TOP3])
for c in g:
    capped(20, c, [b for b in all_bases if b not in TOP3])
for c in commits:
    for rep in (1, 2):
        capped(60, c, sorted(TOP3), rep)

assert len({j["key"] for j in jobs}) == len(jobs)
with open(HERE / "jobs.jsonl", "w") as f:
    for j in sorted(jobs, key=lambda j: j["prio"]):
        f.write(json.dumps(j) + "\n")
print(len(jobs), "jobs", sorted(Counter((j["kind"], j["prio"]) for j in jobs).items()))
