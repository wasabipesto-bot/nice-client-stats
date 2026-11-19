#!/usr/bin/env python3
"""Check every stored submission against a reference run of the reference client.

  validate.py <reference bin dir> [results/subs]

Detailed: the histogram must match exactly; every near miss a client reports must
carry the right uniques, and every reference number with uniques > 0.9*base + 1 must
be reported (the eras disagree on the exact cutoff, so the boundary is not checked).
Niceonly: the nice list must match the reference's detailed run of the same window
restricted to uniques == base, when the window is small enough to run detailed;
otherwise it is only checked for being empty (no nice numbers are known in the corpus).
"""
import json, math, sys
from pathlib import Path
import run

HERE = Path(__file__).resolve().parent
ref = run.Client(sys.argv[1])
ref.threads = "4"
subs = Path(sys.argv[2]) if len(sys.argv) > 2 else HERE / "results" / "subs"
cache = HERE / "results" / "reference"; cache.mkdir(parents=True, exist_ok=True)
DETAILED_REF_MAX = 10**8  # bigger windows: emptiness check only (reference runs would cost too much)


def reference(base, start, size):
    f = cache / f"{base}-{start}-{size}.json"
    if f.exists():
        return json.loads(f.read_text())
    secs, ru, bodies, how = run.measure(ref, "detailed", base, [(start, start + size)], "0-3", 7200)
    h, n = run.canon(bodies[0])
    out = {"hist": {str(k): v for k, v in h.items()}, "near": {str(k): v for k, v in n.items()}}
    f.write_text(json.dumps(out))
    return out


report = {"ok": 0, "fail": [], "unchecked": 0}
detail = {}  # file stem -> ok | wrong | unchecked (for the validation matrix)
for p in sorted(subs.glob("*.json")):
    client, key = p.stem.split("--")
    base, mode, start, size = key.split("-")
    base, start, size = int(base), int(start), int(size)
    got = json.loads(p.read_text())
    limit = 10**9 if mode == "detailed" else DETAILED_REF_MAX  # detailed refs run at ~2e7/s on the build host
    if size > limit:
        # detailed reports near misses by design; only a 100% nice number would be news
        if any(u == base for u in got["near"].values()):
            report["fail"].append((p.name, "a nice number reported in an unverifiable window")); detail[p.stem] = "wrong"
        else:
            report["unchecked"] += 1; detail[p.stem] = "unchecked"
        continue
    r = reference(base, start, size)
    errs = []
    if mode == "detailed":
        if got["hist"] != r["hist"]:
            errs.append("histogram differs")
        thr = math.floor(0.9 * base) + 1
        for n, u in got["near"].items():
            if n in r["near"] and r["near"][n] != u:
                errs.append(f"near {n}: {u} vs {r['near'][n]}")
        missing = [n for n, u in r["near"].items() if u > thr and n not in got["near"]]
        if missing:
            errs.append(f"{len(missing)} near misses missing")
    else:
        nice = {n for n, u in r["near"].items() if u == base}
        if set(got["near"]) != nice:
            errs.append(f"nice list {sorted(got['near'])} vs {sorted(nice)}")
    if errs:
        report["fail"].append((p.name, errs)); detail[p.stem] = "wrong"
    else:
        report["ok"] += 1; detail[p.stem] = "ok"
out = subs.parent / "validate_detail.json"  # per submission: ok / wrong / unchecked (finish_run.py reads it)
out.write_text(json.dumps(detail))
print(json.dumps(report, indent=1))
