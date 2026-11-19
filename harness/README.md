# Measurement harness

Builds historical client commits, runs each against a mock search server on a pinned CPU core, and records how long
every field takes. Runs are done by hand on a machine with spare cores; a full run takes hours to days.

## A run, step by step

On the **build machine** (has the repositories and Rust):

1. `select_commits.py` writes `new-commits.tsv`: the commits picked by the rules below that are not yet in
   `../data/commits.csv`. Clones of the three client repositories are found through `PERFHIST_NICE_PY`,
   `PERFHIST_NICE_RUST` and `PERFHIST_NICE` (default `~/src/<name>`).
2. `build_list.sh new-commits.tsv` builds each commit into `bins/<repo>-<date>-<sha>/client` with the Rust stable of
   its commit date (`build.sh`; rustup installs the toolchain). Builds are default features, CPU only.
3. `enqueue.py new-commits.tsv --release <sha> [--milestones <sha>,...]` writes `jobs.jsonl`. The release gets the
   full production-size set (bases 57–62 and the 10¹⁴–10¹⁶ field-size ladders at 62 and 64); milestones get bases
   57–60; every commit gets detailed and capped nice-only fields at every base, and three repetitions at 40, 50 and 60.
4. Copy the harness to the measurement host (`rsync -a --exclude results harness/ host:dir/`), then on the host
   `python3 jobq.py add jobs.jsonl` and `PERFHIST_CORES="4 5 6 7" ./start_workers.sh`.

While it runs, from the build machine: `PERFHIST_REMOTE=host:dir PERFHIST_RUN=run4 ./sync.sh` pushes any new
binaries and pulls the results into `results/run4/`. On the host, `python3 jobq.py status` shows progress.

When the queue is empty:

5. On the host, `./stop_workers.sh`; then `sync.sh` once more.
6. Validate: start a mock server (`python3 mock/server.py 8650 &`), then
   `python3 validate.py <current release's bin dir> results/run4/subs` writes `results/run4/validate_detail.json`.
7. `finish_run.py --run run4-<date> --results results/run4 --commits new-commits.tsv` adds the run to `../data/`.
   Commit `data/` and push; CI rebuilds the dashboard.

## How it measures

- **One job per pinned core**, at nice 10 inside a user scope capped at 2.5 GB (`start_workers.sh`), so other
  services on the host keep priority. Each worker starts its own mock server on port `8656 + core`.
- **The mock server** (`mock/server.py`) hands out the field the job asks for and times claim to submit.
- **A canary** (detailed mode, base 50, 5×10⁷ numbers, one fixed build) runs every hour on each core; its time should
  stay within about ±2 %. A field whose CPU time falls below 97 % of its wall time was sharing its core and is
  measured again.
- **Lanes:** a worker in lane `long` takes production-size fields first, `short` everything else first;
  `lanes.json` (`{"7": "long"}`) changes a running worker's lane.
- **Fields** come from `corpus/full.json` (bases, strata, production fields) and `corpus/ladder.json` (field-size
  ladders). The generators in `corpus/` used a one-off filter survey that is not in this repository
  (`PERFHIST_FILTER_SURVEY`), so the generated lists are the source of truth.
- **The oldest clients:** the January 2023 clients hard-code their server address, so `build.sh` patches it to
  `127.0.0.1:8650` and only the worker on port 8650 takes their jobs. The Python clients are not built: put the
  client's `main.py` at its commit (with the same address patch) in `bins/<name>/`, with a `venv/` holding Python 3.11
  and `requests` 2.28.2.

## Files

| file | role |
|---|---|
| `run.py` | runs one client on one field (shared by the worker and validation) |
| `worker.py`, `jobq.py` | the job queue (`queue.db`) and the worker loop |
| `build.sh`, `build_list.sh`, `build_all.sh` | building clients (`build_all.sh` rebuilds everything in a list, as run 1 did) |
| `select_commits.py`, `enqueue.py`, `finish_run.py` | the steps above |
| `validate.py` | compares every stored submission with a reference run |
| `analyze.py` | quick per-file summary of a results file |
| `corpus_strata.py`, `corpus/` | field selection (also used by the dashboard's model) |
| `shim/` | run 2's production-chunk timing shim |
| `past-runs/` | the job generators of runs 1 and 2, kept as a record (they expect to run from this directory) |
