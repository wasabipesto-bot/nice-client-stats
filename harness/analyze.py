#!/usr/bin/env python3
"""Summarize a results JSONL: rate per (client, mode, base) as total size / total time
over the strata, rep-to-rep noise, stratum spread for sub-windowed clients, canary drift.

  analyze.py results/feas.jsonl
"""
import json, statistics as st, sys
from collections import defaultdict

recs = [json.loads(l) for l in open(sys.argv[1])]
fields = [r for r in recs if r["kind"] == "field"]
can = [r for r in recs if r["kind"] == "canary" and r["secs"]]

by = defaultdict(lambda: defaultdict(list))  # (client, mode, base) -> rep -> records
for r in fields:
    by[(r["client"], r["mode"], r["base"])][r["rep"]].append(r)


def agg(rs):
    """Rate of one pass over the strata: equal-weight strata, so mean time per field."""
    if any(r["secs"] is None for r in rs):
        return None
    if rs[0]["subwindow"]:  # uniform client: per-number rate is the thing; average it in time
        return sum(r["size"] for r in rs) / sum(r["secs"] for r in rs)
    return rs[0]["field_size"] / st.mean(r["secs"] for r in rs)


def fmt(x):
    return f"{x:9.3g}" if x else "     FAIL"


print(f"{'client':38} {'mode':8} {'base':>4} {'rate/s':>9} {'cv_rep':>7} {'cv_strat':>8} {'1shot/rep':>9} {'how':8} {'win':>8}")
rows = {}
for (c, m, b), reps in sorted(by.items(), key=lambda kv: (kv[0][1], kv[0][2], kv[0][0])):
    rates = {rep: agg(rs) for rep, rs in reps.items()}
    main_rates = [v for k, v in rates.items() if isinstance(k, int) and v]
    rate = st.median(main_rates) if main_rates else None
    cv = st.stdev(main_rates) / st.mean(main_rates) if len(main_rates) > 1 else float("nan")
    first = next(rs for k, rs in reps.items() if isinstance(k, int))
    strat_cv = float("nan")
    if first[0]["subwindow"] and len(first) > 1 and all(r["rate"] for r in first):
        strat_cv = st.stdev(r["rate"] for r in first) / st.mean(r["rate"] for r in first)
    one = rates.get("oneshot")
    ratio = f"{one / rate:9.2f}" if one and rate else " " * 9
    how = first[0]["how"] + ("*" if first[0].get("repeat_broken") else "")
    rows[(c, m, b)] = rate
    print(f"{c:38} {m:8} {b:4} {fmt(rate)} {cv:7.1%} {strat_cv:8.1%} {ratio} {how:8} {first[0]['size']:8.0e}")

if can:
    t = [r["secs"] for r in can]
    print(f"\ncanary (detailed b50, {can[0]['size']:.0e}): n={len(t)} median {st.median(t):.3f}s "
          f"min {min(t):.3f} max {max(t):.3f} cv {st.stdev(t) / st.mean(t) if len(t) > 1 else 0:.1%}")
    print("  series:", " ".join(f"{x:.2f}" for x in t))

print("\nspeedup vs the first client measured in each (mode, base):")
for m in ("detailed", "niceonly"):
    for b in sorted({k[2] for k in rows}):
        series = [(c, rows[(c, mm, bb)]) for (c, mm, bb) in sorted(rows, key=lambda k: k[0].split("-")[-4:-1] if False else k[0])
                  if mm == m and bb == b and rows[(c, mm, bb)]]
        series.sort(key=lambda x: "-".join(x[0].split("-")[-4:-1]))
        if series:
            base_rate = series[0][1]
            print(f"  {m:8} b{b}: " + "  ".join(f"{c.split('-')[-1]} {r / base_rate:,.0f}x" for c, r in series))
