#!/usr/bin/env python3
"""Full-run corpus -> corpus/full.json.

Per base (40-97, nonempty range):
  detailed: one seeded start; the window size is calibrated per client (rate is uniform).
  niceonly (35 live bases): fields of W = min(production size, 1e13), at equal-probability
    strata of a predicted cost. K=5 set for MSD-era clients, K=3 set for uniform clients.
    Stratifier: MSD survival (filter-map pilot data at 1e9; the probe's `msd` at larger W),
    or join top-layer prefix counts (`count`) where the join runs (57-64).
real: production-size fields for the join at b57 (1e14), b58 (1e15), b60 (1e16), b62 (1e17),
  stratified by prefix counts (Oct-23 survey for 58/60/62, fresh counts for 57).
"""
import json, random, subprocess, sys
from bases import base_range, niceonly_residues

# Inputs from a one-off filter survey that is not part of this repository; the generated
# field lists (corpus/*.json) are what the runs used. Set these to rerun the generator.
import os
FM = os.environ.get("PERFHIST_FILTER_SURVEY", "filter-survey")
PROBE = os.environ.get("PERFHIST_FILTER_PROBE", "filter_map_probe")
CAP = 10**13
PROD = {**{b: 10**9 for b in range(40, 51)}, 52: 10**10, 53: 10**12, 54: 10**13, 57: 10**14,
        58: 10**15, 60: 10**16, 62: 10**17}  # data.nicenumbers.net, 2026-10-29
JOIN = {57, 58, 60, 62, 64}
NCAND = 300


def probe(*args):
    return subprocess.run(["taskset", "-c", "0-3", PROBE, *map(str, args)], capture_output=True, text=True,
                          check=True).stdout.split("\n")


def aligned_starts(b, W, n, seed):
    s, e = base_range(b)
    k = (e - s) // W
    r = random.Random(seed)
    return [s + r.randrange(k) * W for _ in range(n)]


def strata(cand, K):
    """Zero-cost fields form one stratum weighted by their share; the rest is cut into
    equal-probability strata, each represented by the field nearest the stratum's mean
    prediction (cost is ~linear in it). Mean field time = sum_k w_k * t_k."""
    cand = sorted(cand)
    n = len(cand)
    zeros = [c for c in cand if c[0] == 0]
    nz = [c for c in cand if c[0] != 0]
    out = []
    if zeros:
        out.append({"pred": 0, "start": zeros[len(zeros) // 2][1], "w": len(zeros) / n})
    k = min(len(nz), K - 1 if zeros else K)
    for i in range(k):
        part = nz[i * len(nz) // k:(i + 1) * len(nz) // k]
        mean = sum(c[0] for c in part) / len(part)
        pick = min(part, key=lambda c: abs(c[0] - mean))
        out.append({"pred": pick[0], "start": pick[1], "w": len(part) / n, "stratum_mean_pred": mean})
    for i, f in enumerate(out):
        f["stratum"] = i
    return out


CACHE = "candidates.json"
try:
    cache = json.load(open(CACHE))
except FileNotFoundError:
    cache = {}


def cached(key, fn):
    if key not in cache:
        cache[key] = fn()
        json.dump(cache, open(CACHE, "w"))
    return [tuple(x) for x in cache[key]]


def counts(b, W, starts):
    out = []
    for i in range(0, len(starts), 100):
        for l in probe("count", b, f"{W:.0e}", *starts[i:i + 100]):
            if l.strip():
                s, p, _ = l.split()
                out.append((int(p), int(s)))
    return out


if __name__ == "__main__":
    out = {"cap": CAP, "bases": {}, "real": {}}
    for b in range(40, 98):
        r = base_range(b)
        if not r:
            continue
        s, e = r
        entry = {"range": [s, e], "detailed_start": aligned_starts(b, 1, 1, 1000 + b)[0] if e - s > 2 * 10**9 else s}
        if niceonly_residues(b):
            W = min(PROD.get(b, CAP), CAP, e - s)
            if W == 10**9 and b in (40, 42, 44, 45, 48, 49, 50):
                rows = [l.split() for l in open(f"{FM}/data/msd_b{b}.txt")]
                cand = [(int(x[3]) / int(x[2]), int(x[1])) for x in rows]
                kind = "msd_survival(pilot)"
            elif b in JOIN:
                cand = cached(f"join:{b}:{W}", lambda: counts(b, W, aligned_starts(b, W, NCAND, b)))
                kind = "join_prefixes"
            else:
                cand = cached(f"msd:{b}:{W}", lambda: [(int(x[3]) / int(x[2]), int(x[1])) for x in
                              (l.split() for l in probe("msd", b, NCAND, f"{W:.0e}", b) if l.strip())])
                kind = "msd_survival"
            entry.update({"field_size": W, "production_field_size": PROD.get(b), "stratifier": kind,
                          "n_candidates": len(cand), "fields5": strata(cand, 5), "fields3": strata(cand, 3)})
        out["bases"][b] = entry
        print(b, entry.get("field_size"), entry.get("stratifier"), [(f["pred"], round(f["w"], 3)) for f in entry.get("fields5", [])],
              file=sys.stderr, flush=True)

    # Production-size join fields.
    for b, W, src, K in [(57, 10**14, None, 5), (58, 10**15, "jf_b58_all.txt", 5), (60, 10**16, "jf_b60.txt", 5),
                         (62, 10**17, "jf_b62.txt", 3)]:
        if src:
            cand = [(int(x.split()[2]), int(x.split()[1])) for x in open(f"{FM}/run3/{src}")]
        else:
            cand = cached(f"real:{b}:{W}", lambda: counts(b, W, aligned_starts(b, W, 400, 5700)))
        out["real"][b] = {"field_size": W, "stratifier": "join_prefixes", "n_candidates": len(cand),
                          "fields": strata(cand, K)}
        print("real", b, W, [(f["pred"], round(f["w"], 3)) for f in out["real"][b]["fields"]], file=sys.stderr)
    json.dump(out, open("full.json", "w"), indent=1)
