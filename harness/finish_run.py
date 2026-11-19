#!/usr/bin/env python3
"""Turn a finished run into repository data (run from harness/, after sync.sh and validate.py).

  finish_run.py --run run4-2026-12-10 --results results/run4 --commits new-commits.tsv

- results/<run>/results.jsonl     -> ../data/runs/<run>.jsonl.gz (unchanged, gzipped)
- the commits TSV + bins/*/build.json -> rows appended to ../data/commits.csv
- results/<run>/validate_detail.json (validate.py <reference build> results/<run>/subs)
                                   -> worst verdict per (build, mode, base) appended to ../data/validation.csv
Then commit data/ and push: CI rebuilds the site from it.
"""
import argparse, csv, gzip, json, os, shutil, subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "data"
ap = argparse.ArgumentParser()
ap.add_argument("--run", required=True)
ap.add_argument("--results", required=True)
ap.add_argument("--commits", required=True)
a = ap.parse_args()
res = Path(a.results)

dst = DATA / "runs" / f"{a.run}.jsonl.gz"
assert not dst.exists(), f"{dst} exists"
with open(res / "results.jsonl", "rb") as fi, gzip.open(dst, "wb", compresslevel=9) as fo:
    shutil.copyfileobj(fi, fo)

fields = ["repo", "sha", "date", "order", "why", "subject", "toolchain", "patch", "binary_bytes", "build_secs", "sha256"]
known = {(r["repo"], r["sha"]) for r in csv.DictReader(open(DATA / "commits.csv"))}
src = {"nice": os.environ.get("PERFHIST_NICE", str(Path.home() / "src/nice"))}
new = []
for line in Path(a.commits).read_text().splitlines():
    repo, sha, date, why, subj = line.split("\t")
    if repo == "repo" or (repo, sha) in known:
        continue
    d = HERE / "bins" / f"{repo}-{date}-{sha}"
    b = json.loads((d / "build.json").read_text())
    order = ""
    if repo in src:  # same-day tie-break: position on the first-parent history
        order = 1000 + int(subprocess.check_output(["git", "-C", src[repo], "rev-list", "--first-parent", "--count", sha]))
    new.append({"repo": repo, "sha": sha, "date": date, "order": order, "why": why, "subject": subj,
                "toolchain": b.get("toolchain", ""), "patch": b.get("patch", ""),
                "binary_bytes": (d / "client").stat().st_size, "build_secs": b.get("build_secs", ""), "sha256": b.get("sha256", "")})
with open(DATA / "commits.csv", "a", newline="") as f:
    csv.DictWriter(f, fieldnames=fields).writerows(new)

code = {"wrong": 3, "failed": 2, "ok": 1, "unchecked": 0}
worst = {}
vd = res / "validate_detail.json"
for stem, s in (json.loads(vd.read_text()).items() if vd.exists() else []):
    client, key = stem.split("--")
    b, m = key.split("-")[:2]
    k = (client, m, int(b))
    if k not in worst or code[s] > code[worst[k]]:
        worst[k] = s
with open(DATA / "validation.csv", "a", newline="") as f:
    w = csv.writer(f)
    for (c, m, b), s in sorted(worst.items()):
        w.writerow([a.run.split("-")[0], c, m, b, s])
print(f"{dst.name}; {len(new)} commits appended; {len(worst)} validation rows"
      + ("" if vd.exists() else " (no validate_detail.json: run validate.py first)"))
