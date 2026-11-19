#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = ["plotly==7.1.0"]
# ///
"""Render the dashboard from data/ into site/out/ (index.html plus CSV downloads).

  uv run site/build.py

Everything is recomputed from the raw measurement records in data/runs/*.jsonl.gz, the commit list
data/commits.csv and the validation verdicts data/validation.csv. CI runs this on every push.
"""
import csv
import gzip
import json
import math
import re
import shutil
import statistics as st
import sys
import time
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DATA = ROOT / "data"
OUT = HERE / "out"
sys.path.insert(0, str(HERE))
import charts  # noqa: E402
import model  # noqa: E402
import page  # noqa: E402

# ---- load ---------------------------------------------------------------------------------------
REPO_URL = {"nice-client-py": "https://github.com/wasabipesto/nice-client-py",
            "nice-rust": "https://github.com/wasabipesto/nice-rust", "nice": "https://github.com/wasabipesto/nice"}
commits = {}  # client name -> info
for r in csv.DictReader(open(DATA / "commits.csv")):
    name = f"{r['repo']}-{r['date']}-{r['sha']}"
    tags = [w[4:] for w in r["why"].split(",") if w.startswith("tag:")]
    pr = re.search(r"\(#(\d+)\)\s*$", r["subject"])
    r.update(name=name, tag=tags[-1] if tags else "", pr=pr.group(1) if pr else "",
             order=int(r["order"] or 0), url=f"{REPO_URL[r['repo']]}/commit/{r['sha']}",
             subject_short=re.sub(r"\s*\(#\d+\)\s*$", "", r["subject"]))
    r["label"] = r["tag"] or (f"#{r['pr']}" if r["pr"] else r["sha"])
    commits[name] = r


def okey(name):
    c = commits[name]
    return (c["date"], c["order"])


recs, runs = [], []
for p in sorted((DATA / "runs").glob("*.jsonl.gz")):
    rs = [json.loads(l) for l in gzip.open(p, "rt")]
    inv = p.with_name(p.name.replace(".jsonl.gz", ".invalidated.json"))
    if inv.exists():  # records of jobs that were invalidated and measured again
        iv = json.loads(inv.read_text())
        cut = {}
        for b in (iv if isinstance(iv, list) else [iv]):
            for j in b["jobs"]:
                cut[j] = max(cut.get(j, 0), b["before_ts"])
        rs = [r for r in rs if not (r.get("job") in cut and r.get("ts", 0) < cut[r["job"]])]
    for r in rs:
        r["_run"] = p.name.split("-")[0]
    runs.append((p.name.split(".")[0], len(rs)))
    recs += rs

validation = [dict(r, base=int(r["base"])) for r in csv.DictReader(open(DATA / "validation.csv"))]
wrong = {(v["client"], v["base"], v["mode"]) for v in validation if v["status"] == "wrong"}

# ---- aggregate ------------------------------------------------------------------------------------
fields = [r for r in recs if r.get("kind") == "field" and r.get("secs")]


def wrate(rs):
    """Stratified estimate: strata carry weights w (equal if absent); rate = sum(w) / sum(w_k t_k / size_k)."""
    ws = [x.get("w") or 1 / len(rs) for x in rs]
    return sum(ws) / sum(w * x["secs"] / x["size"] for w, x in zip(ws, rs))


latest = defaultdict(dict)  # group -> {stratum: newest record}: a retried job keeps only its last attempt
for r in fields:
    # commit points only: ladder records (field-size studies) and builds outside commits.csv
    # (the toolchain A/B rebuild) feed other charts
    if r.get("jobkind") == "ladder" or r["client"] not in commits or (r["client"], r["base"], r["mode"]) in wrong:
        continue
    g = latest[(r["client"], r["mode"], r["base"], r.get("jobkind", "capped"), r.get("rep", 0))]
    if r.get("stratum", 0) not in g or r.get("ts", 0) >= g[r.get("stratum", 0)].get("ts", 0):
        g[r.get("stratum", 0)] = r
groups = {k: list(v.values()) for k, v in latest.items()}

agg = defaultdict(list)  # (client, mode, base) -> [rate per rep]
real = defaultdict(dict)  # (client, base) -> {stratum: record}
for (c, m, b, k, rep), rs in groups.items():
    if k == "real":
        for x in rs:
            real[(c, b)][x["stratum"]] = x
        continue
    if len(rs) < rs[0].get("K", len(rs)) or any(x["secs"] <= 0 for x in rs):
        continue
    agg[(c, m, b)].append(wrate(rs))

rates = []
for (c, m, b), rr in agg.items():
    rates.append({"client": c, "mode": m, "base": b, "rate": st.median(rr), "reps": len(rr),
                  "spread": max(rr) / min(rr) - 1 if len(rr) > 1 else None})
rates.sort(key=lambda r: (okey(r["client"]), r["mode"], r["base"]))
production = []
for (c, b), byst in real.items():
    done = list(byst.values())
    if abs(sum(x.get("w") or 0 for x in done) - 1) > 1e-6:
        continue  # incomplete: not an estimate
    production.append({"client": c, "base": b, "rate": wrate(done), "field_size": done[0]["field_size"]})
production.sort(key=lambda r: (okey(r["client"]), r["base"]))
mdl = model.compute(recs)

# peak memory (VmHWM, KiB) per (client, mode, base, kind): max over the group's records, rep 0
mem = defaultdict(int)
for r in fields:
    if r.get("rep", 0) == 0 and r["client"] in commits and r.get("jobkind") != "ladder":
        k = (r["client"], r["mode"], r["base"], r.get("jobkind", "capped"))
        mem[k] = max(mem[k], (r.get("ru") or {}).get("hwm_kb") or 0)

D = dict(commits=commits, okey=okey, recs=recs, fields=fields, rates=rates, production=production, model=mdl,
         mem=mem, validation=validation, wrong=wrong, runs=runs)

# ---- render ---------------------------------------------------------------------------------------
if OUT.exists():
    shutil.rmtree(OUT)
(OUT / "data").mkdir(parents=True)
figs = charts.build_all(D)
(OUT / "index.html").write_text(page.render(D, figs))
shutil.copy(DATA / "commits.csv", OUT / "data/commits.csv")
with open(OUT / "data/rates.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["date", "repo", "sha", "tag", "mode", "base", "field", "rate_per_s", "reps"])
    for r in rates:
        c = commits[r["client"]]
        w.writerow([c["date"], c["repo"], c["sha"], c["tag"], r["mode"], r["base"], "small (<=1e13)", f"{r['rate']:.6g}", r["reps"]])
    for r in production:
        c = commits[r["client"]]
        w.writerow([c["date"], c["repo"], c["sha"], c["tag"], "niceonly", r["base"], f"production {r['field_size']:.0e}",
                    f"{r['rate']:.6g}", 1])
    for sha, v in mdl["cost"]["b64_1e18"].items():
        c = next(x for x in commits.values() if x["sha"] == sha)
        w.writerow([c["date"], c["repo"], c["sha"], c["tag"], "niceonly", 64, "production 1e18 (modelled)", f"{v['rate']:.6g}", ""])
print(f"{len(recs)} records from {len(runs)} runs, {len(rates)} rates, {len(production)} production rows, "
      f"{len(figs)} charts -> {OUT / 'index.html'} ({(OUT / 'index.html').stat().st_size / 1e6:.1f} MB)")
