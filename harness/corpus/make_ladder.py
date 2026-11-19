#!/usr/bin/env python3
"""Field-size ladder for the join extrapolation (2026-11-02): b62 and b64 at 1e14, 1e15 (K=5) and
1e16 (K=3), production-grid-aligned windows stratified by join top-layer prefix count."""
import json
from make_full import strata, counts, aligned_starts, cached  # same sampler and strata as the main corpus
out = {}
for b in (62, 64):
    for e, K in ((14, 5), (15, 5), (16, 3)):
        W = 10 ** e
        cand = cached(f"ladder:{b}:{W}", lambda: counts(b, W, aligned_starts(b, W, 300, 6400 + b * 10 + e)))
        out[f"{b}:{e}"] = {"base": b, "field_size": W, "fields": strata(cand, K), "n_candidates": len(cand)}
        print(b, f"1e{e}", [(f["pred"], round(f["w"], 3)) for f in out[f"{b}:{e}"]["fields"]], flush=True)
json.dump(out, open("ladder.json", "w"), indent=1)
