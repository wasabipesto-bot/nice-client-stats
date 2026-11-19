#!/usr/bin/env python3
"""Run-2 jobs (2026-11-02): join field-size ladders + direct b64 1e17, and shim chunk sampling.
prio 0  v3.4.7 b64 1e17 (the two long fields start first)
prio 1  ladder 1e16 (v3.4.7, v3.4.6 at b62, b64);  shim validation (whole 1e13 fields, 1e8 chunks)
prio 2  ladder 1e15;  prio 3 ladder 1e14
prio 4  shim samples, b57-b64 (2000 production-sized 1e9 chunks per base, in 4 parts), every clamp-era build
prio 5  shim samples, b65+ sample bases, clamp-era releases
"""
import json, os
from pathlib import Path
HERE = Path(__file__).resolve().parent
lad = json.loads((HERE / "corpus/ladder.json").read_text())
full = json.loads((HERE / "corpus/full.json").read_text())
# Inputs from a one-off filter survey that is not part of this repository; the generated
# field lists (corpus/*.json) are what the runs used. Set these to rerun the generator.
import os
FM = os.environ.get("PERFHIST_FILTER_SURVEY", "filter-survey")
LADDER_BUILDS = {"nice-2026-10-31-8bd154b": "v3.4.7", "nice-2026-10-08-9a4f740": "v3.4.6"}
jobs = []


def add(key, prio, kind, client, base, spec, mode="niceonly"):
    jobs.append({"key": key, "prio": prio, "kind": kind, "client": client, "mode": mode, "base": base,
                 "needs_8650": False, "spec": spec})


for name in LADDER_BUILDS:
    for k, L in lad.items():
        b, e = L["base"], int(k.split(":")[1])
        if e == 17 and name != "nice-2026-10-31-8bd154b":
            continue
        prio = {17: 0, 16: 1, 15: 2, 14: 3}[e]
        for f in L["fields"]:
            add(f"ladder:{name}:{b}:1e{e}:s{f['stratum']}", prio, "ladder", name, b,
                {"strata": [f], "field_size": L["field_size"], "warmup": False, "timeout": 40 * 3600})

shims = sorted(os.listdir(HERE / "shims")) if (HERE / "shims").exists() else []
clamp_builds = [l.split("\t") for l in (HERE / "commits.tsv").read_text().splitlines()[1:]]
clamp_builds = [f"nice-{r[2]}-{r[1]}" for r in clamp_builds if r[0] == "nice" and "2026-07-24" <= r[2] < "2026-10-07"]
releases = {"0755ad7", "4297fab", "b1d78d3", "22a1665", "da5abea", "6d42656", "0e75257"}  # v3.3.0, v3.4.0-v3.4.5

# shim validation: whole 1e13 fields with the client's own 1e8 chunking, against the client's measured times
for name, b in (("nice-2026-09-08-0e75257", 60), ("nice-2026-08-28-4297fab", 60), ("nice-2026-09-08-0e75257", 57)):
    for f in full["bases"][str(b)]["fields3"]:
        if f["pred"]:
            add(f"shimval:{name}:{b}:s{f['stratum']}", 1, "shim", f"shim:{name}", b,
                {"mode": "field", "chunk": 10**8, "start": f["start"], "size": 10**13, "stratum": f["stratum"], "w": f["w"]})


def chunk_starts(b):
    lo = full["bases"][str(b)]["range"][0]
    rows = [l.split() for l in open(f"{FM}/data/msd_b{b}.txt")]
    return [lo + (int(r[1]) - lo) // 10**9 * 10**9 for r in rows]


for b in (57, 58, 60, 62, 64):
    st = chunk_starts(b)
    for name in clamp_builds:
        for part in range(4):
            add(f"shim:{name}:{b}:p{part}", 4, "shim", f"shim:{name}", b,
                {"mode": "sample", "chunk": 10**9, "starts": st[part::4], "part": part})
for b in (65, 70, 80, 90, 97):
    st = chunk_starts(b)[::4]  # 500 chunks
    for name in clamp_builds:
        if name[-7:] in releases:
            add(f"shim:{name}:{b}:p0", 5, "shim", f"shim:{name}", b,
                {"mode": "sample", "chunk": 10**9, "starts": st, "part": 0})

with open(HERE / "jobs2.jsonl", "w") as fo:
    for j in jobs:
        fo.write(json.dumps(j) + "\n")
from collections import Counter
print(len(jobs), Counter((j["kind"], j["prio"]) for j in jobs), "clamp builds", len(clamp_builds))
