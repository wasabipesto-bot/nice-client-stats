#!/usr/bin/env python3
"""commits.tsv + corpus/full.json -> jobs.jsonl (priority order, see README).

prio  0-9   real-size join fields (main first at b62 > b60 > b58 > b57; then older join builds)
prio 10/20  skeleton commits (tags, anchors, join builds): b40/50/60, then every other base
prio 30/40  day commits: b40/50/60, then the rest
prio 50     per-PR commits (busy days since MSD)
prio 60     extra reps (2 more) for tags and everything since 2026-08-01
Within a priority, commits are shuffled (seeded) so coverage grows evenly across time.
"""
import json, random, sys
from pathlib import Path

ONLY_DETAILED = "--detailed-only" in sys.argv

HERE = Path(__file__).resolve().parent
corpus = json.loads((HERE / "corpus/full.json").read_text())
MSD_EPOCH, NICEONLY_FROM, API_BASE_FROM = "2026-02-03", "2023-04-02", "2023-04-02"
ANCHORS = {"4bc913a", "f82e402", "64d279f", "a6ceab8", "c444b67", "0e75257", "8c088a2", "8bd154b"}
JOIN = ["8bd154b", "8c088a2", "939d21a", "215eb4b", "90eea6f", "9a4f740", "9f8c211"]  # newest first
TOP3 = {40, 50, 60}
PR_BASES = {40, 50, 60, 70, 80}
MSD_HI_BASES = {52, 54, 57, 60, 64, 70, 80, 90}
HI_BASES = {65, 70, 80, 90, 97}
JOIN_DATE = "2026-10-07"

commits = []
for l in (HERE / "commits.tsv").read_text().splitlines()[1:]:
    repo, sha, date, why, subj = l.split("\t")
    commits.append({"repo": repo, "sha": sha, "date": date, "why": why, "name": f"{repo}-{date}-{sha}"})
by_sha = {c["sha"]: c for c in commits}
for s in JOIN:
    assert s in by_sha, f"join commit {s} missing from commits.tsv"

jobs = []


def add(prio, kind, c, mode, b, spec, key_extra=""):
    if ONLY_DETAILED and mode != "detailed":
        return
    jobs.append({"key": f"{kind}:{c['name']}:{mode}:{b}{key_extra}", "prio": prio, "kind": kind, "client": c["name"],
                 "mode": mode, "base": b, "spec": spec,
                 "needs_8650": c["repo"] == "nice-client-py" or (c["repo"] == "nice-rust" and c["date"] < API_BASE_FROM)})


def capped(prio, c, bases, rep=0):
    uniform = c["repo"] != "nice" or c["date"] < MSD_EPOCH
    msd_prejoin = not uniform and c["date"] < JOIN_DATE
    for b in bases:
        e = corpus["bases"][str(b)]
        lo, hi = e["range"]
        dcap = min(10**9, hi - lo)
        add(prio, "capped", c, "detailed", b, {"strata": [{"stratum": 0, "pred": 0, "start": e["detailed_start"]}],
            "calibrate": True, "cap": dcap, "field_size": dcap, "rep": rep}, f":r{rep}")
        # Pre-join MSD builds take 17-65 min per non-empty 1e13 field at b60 (checkpoint
        # 2026-10-30 00:40): at b52+ only skeleton commits, 8 sample bases, K=3 strata.
        if msd_prejoin and b >= 52 and (c["sha"] not in skel_set or b not in MSD_HI_BASES):
            continue
        # Checkpoint 2026-10-30 18:40: early MSD builds take 2-3 h per non-empty b60 1e13 field.
        # Pre-join: b70 is the only base above 64, and no extra reps at b52+.
        if msd_prejoin and ((b >= 65 and b != 70) or (rep > 0 and b >= 52)):
            continue
        # b65+ has no join and MSD runs on malachite: 2-5 h per capped job even on today's
        # client (checkpoint 2026-10-30 12:40). Skeleton commits only, 5 sample bases, K=3.
        if not uniform and b >= 65 and (c["sha"] not in skel_set or b not in HI_BASES):
            continue
        # Checkpoint 2026-10-31 00:40: at b65+ (no join, MSD on malachite) one capped niceonly job
        # takes 7+ h even on today's client. No niceonly there for MSD/join-era builds.
        if not uniform and b >= 65:
            continue
        if "fields5" in e and c["date"] >= NICEONLY_FROM:
            W = e["field_size"]
            if uniform:
                spec = {"strata": e["fields3"], "calibrate": True, "cap": W, "field_size": W, "rep": rep}
            elif (msd_prejoin and b >= 52) or b >= 65:
                spec = {"strata": e["fields3"], "calibrate": False, "field_size": W, "rep": rep, "timeout": 8 * 3600}
            else:
                spec = {"strata": e["fields5"], "calibrate": False, "field_size": W, "rep": rep, "timeout": 6 * 3600}
            add(prio, "capped", c, "niceonly", b, spec, f":r{rep}")


# Real-size join fields. Rules key on shas so adding a release does not shift the others.
#   v3.4.7 (8bd154b, released during the run on 10-31): b57/58/60 first (prio 0), b62 next.
#   main 8c088a2: b62 first (it was the longest), then b60/58/57.
#   b62 also for #204 and v3.4.6 (added 10-31 12:40); K=3 at b60 for the three oldest builds.
REAL_PLAN = {  # sha: [(base, prio), ...]
    "8bd154b": [(60, 0), (58, 0), (57, 0), (62, 1)],
    "8c088a2": [(62, 0), (60, 1), (58, 1), (57, 1)],
    "939d21a": [(60, 2), (58, 3), (57, 3)],
    "215eb4b": [(60, 4), (58, 5), (57, 5), (62, 5)],
    "90eea6f": [(60, 6), (58, 7), (57, 7)],
    "9a4f740": [(60, 8), (58, 9), (57, 9), (62, 9)],
    "9f8c211": [(60, 9), (58, 9), (57, 9)],
}
K3_AT_B60 = {"90eea6f", "9a4f740", "9f8c211"}
for s, plan in REAL_PLAN.items():
    c = by_sha[s]
    for b, prio in plan:
        r = corpus["real"][str(b)]
        for f in (r["fields3"] if s in K3_AT_B60 and b == 60 else r["fields"]):
            add(prio, "real", c, "niceonly", b,
                {"strata": [f], "field_size": r["field_size"], "warmup": False, "timeout": 40 * 3600},
                f":s{f['stratum']}")

all_bases = [int(b) for b in corpus["bases"]]
skel = [c for c in commits if "tag:" in c["why"] or c["sha"] in ANCHORS or c["sha"] in JOIN]
skel_set = {c["sha"] for c in skel}
import datetime as _dt
week_last = {}
for c in commits:  # commits are date-sorted: the last one seen in a week wins
    week_last[_dt.date.fromisoformat(c["date"]).isocalendar()[:2]] = c["sha"]
week_last = set(week_last.values())
day = [c for c in commits if c["sha"] not in skel_set and "day" in c["why"]]
pr = [c for c in commits if c["sha"] not in skel_set and c["why"] == "pr"]
rng = random.Random(1)
for group, p_top, p_rest in [(skel, 10, 20), (day, 30, 40)]:
    g = group[:]; rng.shuffle(g)
    for c in g:
        capped(p_top, c, [b for b in all_bases if b in TOP3])
    for c in g:
        capped(p_rest, c, [b for b in all_bases if b not in TOP3])
g = pr[:]; rng.shuffle(g)
for c in g:
    capped(50, c, sorted(PR_BASES))
for c in commits:
    if "tag:" in c["why"] or c["date"] >= "2026-08-01":
        for rep in (1, 2):
            capped(60, c, sorted(TOP3), rep)

with open(HERE / "jobs.jsonl", "w") as f:
    for j in jobs:
        f.write(json.dumps(j) + "\n")
from collections import Counter
print(len(jobs), "jobs", Counter((j["kind"], j["prio"]) for j in jobs))
print("skeleton", len(skel), "day", len(day), "pr", len(pr))
