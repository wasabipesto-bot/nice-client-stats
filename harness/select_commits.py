#!/usr/bin/env python3
"""List the commits to build: on each repo's first-parent history, the last commit of
every day that touched client code, plus every tagged release. Writes new-commits.tsv: the
selected commits that are not yet in ../data/commits.csv (what a new run should measure).
Repository clones: PERFHIST_NICE_PY, PERFHIST_NICE_RUST, PERFHIST_NICE (default ~/src/<name>)."""
import csv, os
import subprocess
from pathlib import Path

REPOS = [  # name, path, client paths
    ("nice-client-py", os.environ.get("PERFHIST_NICE_PY", str(Path.home() / "src/nice-client-py")), ["main.py", "requirements.txt"]),
    ("nice-rust", os.environ.get("PERFHIST_NICE_RUST", str(Path.home() / "src/nice-rust")), ["src", "Cargo.toml", "Cargo.lock"]),
    ("nice", os.environ.get("PERFHIST_NICE", str(Path.home() / "src/nice")), ["client", "common", "Cargo.toml", "Cargo.lock"]),
]
REF = {"nice": "origin/main"}


def git(path, *a):
    return subprocess.check_output(["git", "-C", path, *a], text=True)


# From MSD (2026-02-03) on, several CPU performance PRs often merged on one day: take
# every first-parent commit there that touches CPU client code, not just the day's last.
PER_PR_SINCE = "2026-02-03"
CPU_PATHS = ["client/src", "common/src", ":!common/src/cubecl*", ":!common/src/gpu*",
             ":!common/src/cuda*", ":!common/src/db_util", ":!common/src/bench_defs.rs"]
# Anchors measured from the start stay in, whatever later commits do to the day picks.
ANCHORS = {"8c088a2": "anchor"}
rows = []
for name, path, paths in REPOS:
    ref = REF.get(name, "HEAD")
    tags = {}
    for line in git(path, "tag", "--format=%(refname:short) %(objectname:short=7) %(*objectname:short=7)").split("\n"):
        if line.strip():
            t, o, deref = (line.split() + [""])[:3]
            tags[(deref or o)[:7]] = t
    log = git(path, "log", ref, "--first-parent", "--format=%h %cs %s", "--", *paths).strip().split("\n")
    per_pr = set()
    if name == "nice":
        per_pr = {l[:7] for l in git(path, "log", ref, "--first-parent", f"--since={PER_PR_SINCE}",
                                     "--format=%h", "--", *CPU_PATHS).split()}
    seen_days = set()
    for line in log:  # newest first: the first commit seen on a day is that day's last
        sha, day, subj = line.split(" ", 2)
        why = []
        if day not in seen_days:
            seen_days.add(day); why.append("day")
        if sha[:7] in tags:
            why.append("tag:" + tags[sha[:7]])
        if sha[:7] in per_pr and "day" not in why:
            why.append("pr")
        if sha[:7] in ANCHORS and not why:
            why.append(ANCHORS[sha[:7]])
        if why:
            rows.append((name, sha[:7], day, ",".join(why), subj))
    # Tags on commits that don't touch client paths still get built, for release labels.
    have = {r[1] for r in rows}
    for sha7, t in tags.items():
        if sha7 not in have and subprocess.run(["git", "-C", path, "merge-base", "--is-ancestor", sha7, ref]).returncode == 0:
            rows.append((name, sha7, git(path, "log", "-1", "--format=%cs", sha7).strip(), "tag:" + t,
                         git(path, "log", "-1", "--format=%s", sha7).strip()))
rows.sort(key=lambda r: r[2])
known = {(r["repo"], r["sha"]) for r in csv.DictReader(open(Path(__file__).parent.parent / "data/commits.csv"))}
rows = [r for r in rows if (r[0], r[1]) not in known]
with open(Path(__file__).parent / "new-commits.tsv", "w") as f:
    f.write("repo\tsha\tdate\twhy\tsubject\n")
    for r in rows:
        f.write("\t".join(r) + "\n")
print(len(rows), "new commits;", {n: sum(r[0] == n for r in rows) for n, _, _ in REPOS})
