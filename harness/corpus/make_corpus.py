#!/usr/bin/env python3
"""Pick niceonly fields per base at equal-probability strata of a predicted cost.

Stratifier: MSD survival of 1e9 windows (filter-map pilot, data/msd_b*.txt) where the
production field is 1e9; join top-layer prefix counts of real 1e16 fields
(run3/jf_b*.txt) where the production field is 1e16. With K strata of equal
probability, the mean field time is estimated by the mean over strata of the time of
the field nearest each stratum's median, and the rate is field_size / that mean.
"""
import json, sys
# Inputs from a one-off filter survey that is not part of this repository; the generated
# field lists (corpus/*.json) are what the runs used. Set these to rerun the generator.
import os
FM = os.environ.get("PERFHIST_FILTER_SURVEY", "filter-survey")
K = int(sys.argv[1]) if len(sys.argv) > 1 else 5
bases = [int(x) for x in sys.argv[2].split(",")] if len(sys.argv) > 2 else [40, 50, 60]
FIELD = {40: 10**9, 50: 10**9, 60: 10**16}  # production field sizes (data.nicenumbers.net)
CAP = 10**13  # largest field measured: the smallest the join takes (JOIN_MIN_FIELD_SIZE)
out = {"K": K, "bases": {}}
for b in bases:
    W = min(FIELD[b], CAP)
    if W == 10**9:
        rows = [l.split() for l in open(f"{FM}/data/msd_b{b}.txt")]
        cand = [(int(r[3]) / int(r[2]), int(r[1]), int(r[2])) for r in rows]
        kind = "msd_survival_1e9"
    elif W == 10**16:
        rows = [l.split() for l in open(f"{FM}/run3/jf_b{b}.txt")]
        cand = [(int(r[2]), int(r[1]), W) for r in rows]
        kind = "join_prefixes_1e16"
    else:  # filter_map_probe count <b> <W> <starts...> -> b{b}_{W:.0e}_prefixes.txt
        rows = [l.split() for l in open(f"b{b}_1e{len(str(W)) - 1}_prefixes.txt")]
        cand = [(int(r[1]), int(r[0]), W) for r in rows]
        kind = f"join_prefixes_1e{len(str(W)) - 1}"
    cand.sort()
    n = len(cand)
    fields = []
    for k in range(K):
        q = (k + 0.5) / K
        x, s, w = cand[min(n - 1, int(q * n))]
        fields.append({"stratum": k, "q": q, "pred": x, "start": s, "size": w})
    out["bases"][b] = {"field_size": W, "production_field_size": FIELD[b], "stratifier": kind, "n_candidates": n, "fields": fields}
json.dump(out, sys.stdout, indent=1)
