#!/usr/bin/env python3
"""Queue worker: one pinned core, one mock API port, jobs from queue.db.

  worker.py <worker_id> <core> <port> <lane: long|short>

Results go to results/results.jsonl (one line per measured field, canary or failure) as
soon as they exist. Touch STOP to make every worker exit after its current job.
Only the worker on port 8650 takes jobs for clients with a hard-coded API URL (Jan 2023).
"""
import json, os, sqlite3, subprocess, sys, time
from pathlib import Path

wid, core, port, lane = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]
os.environ["PERFHIST_API"] = f"http://127.0.0.1:{port}"
os.environ["PERFHIST_LOG"] = f"logs/client-w{wid}.log"
HERE = Path(__file__).resolve().parent
os.chdir(HERE)
import run  # noqa: E402  (reads PERFHIST_API at import)

CANARY = "nice-2026-10-29-8c088a2"
CANARY_EVERY = 3600
ASYNC_FROM = "2026-02-07"
DB = HERE / "queue.db"
OUT = HERE / "results" / "results.jsonl"
SUBS = HERE / "results" / "subs"
SUBS.mkdir(parents=True, exist_ok=True)
corpus = json.loads((HERE / "corpus" / "full.json").read_text())


def emit(rec):
    rec.update({"worker": wid, "core": core, "ts": time.time()})
    with open(OUT, "a") as f:
        f.write(json.dumps(rec) + "\n")


def db():
    c = sqlite3.connect(DB, timeout=60, isolation_level=None)
    c.execute("PRAGMA journal_mode=WAL")
    return c


def claim():
    lanes = HERE / "lanes.json"  # live override, e.g. {"4": "long"}: rebalance without restarts
    my_lane = json.loads(lanes.read_text()).get(wid, lane) if lanes.exists() else lane
    c = db()
    c.execute("BEGIN IMMEDIATE")
    order = "(kind = 'real') DESC" if my_lane == "long" else "(kind = 'real') ASC"
    rows = c.execute(f"SELECT id, client, needs_8650 FROM jobs WHERE status = 'pending' "
                     f"ORDER BY {order}, prio, id").fetchall()
    for jid, client, n8650 in rows:
        if n8650 and port != 8650:
            continue
        if not ((HERE / "shims" / client.removeprefix("shim:") / "shim").exists() if client.startswith("shim:")
                else (HERE / "bins" / client).exists()):
            continue
        c.execute("UPDATE jobs SET status = 'running', worker = ?, started = ? WHERE id = ?", (wid, time.time(), jid))
        c.execute("COMMIT")
        job = c.execute("SELECT * FROM jobs WHERE id = ?", (jid,)).fetchone()
        cols = [d[0] for d in c.execute("SELECT * FROM jobs LIMIT 0").description]
        return dict(zip(cols, job))
    c.execute("COMMIT")
    return None


def finish(jid, status, note=""):
    if status == "pending":  # contamination retry: keep the attempt count in note
        db().execute("UPDATE jobs SET status = 'pending', worker = NULL, started = NULL, note = ? WHERE id = ?", (note, jid))
        return
    db().execute("UPDATE jobs SET status = ?, finished = ?, note = ? WHERE id = ?", (status, time.time(), note, jid))


def store_sub(cl, mode, b, st, size, body):
    h, n = run.canon(body)
    (SUBS / f"{cl.name}--{b}-{mode}-{st}-{size}.json").write_text(
        json.dumps({"hist": h, "near": {str(k): v for k, v in (n or {}).items()}}))


CONTAM = 0.97  # client CPU time / timed wall below this: the core was shared, measure again


def run_shim(job, spec):
    """Time this build's own niceonly chunk function on production-sized chunks (see shim/)."""
    name = job["client"].removeprefix("shim:")
    d = HERE / "shims" / name
    k = (d / "k").read_text().strip()
    args = [str(d / "shim"), str(job["base"]), k, spec["mode"], str(spec["chunk"])]
    args += [str(s) for s in spec["starts"]] if spec["mode"] == "sample" else [str(spec["start"]), str(spec["size"])]
    t0 = time.monotonic()
    p = subprocess.Popen(["taskset", "-c", core] + args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    out = p.stdout.read()
    _, status, ru = os.wait4(p.pid, 0)  # reap ourselves to keep the child's rusage
    rc = os.waitstatus_to_exitcode(status)
    wall = time.monotonic() - t0
    cpu = ru.ru_utime + ru.ru_stime
    if rc != 0:
        return "failed", f"shim rc={rc}"
    if wall >= 5 and cpu / wall < CONTAM:
        n = int((job.get("note") or "contam:0").split(":")[1]) + 1
        emit({"kind": "contaminated", "job": job["id"], "client": name, "base": job["base"], "cpu": cpu, "wall": wall, "attempt": n})
        if n < 3:
            return "pending", f"contam:{n}"
    meta = json.loads((d / "build.json").read_text())
    rows = [l.split() for l in out.strip().splitlines()]
    base = {"kind": "shim", "job": job["id"], "client": name, "sha": meta["sha"], "date": meta["date"],
            "toolchain": meta["toolchain"], "base": job["base"], "mode_shim": spec["mode"], "chunk": spec["chunk"],
            "wall": wall, "cpu": cpu, "stratum": spec.get("stratum"), "w": spec.get("w"), "part": spec.get("part")}
    if spec["mode"] == "sample":
        emit({**base, "starts": [int(r[0]) for r in rows], "secs": [float(r[1]) for r in rows],
              "nice": sum(int(r[2]) for r in rows)})
    else:
        emit({**base, "start": int(rows[0][0]), "size": int(rows[0][1]), "secs": float(rows[0][2]), "nice": int(rows[0][3])})
    return "done", ""


def contaminated(secs, ru):
    """One-shot single-field runs: the client is alone on its core iff CPU time ~ wall."""
    if not secs or secs < 5 or not ru or ru.get("utime") is None:
        return False
    return (ru["utime"] + ru["stime"]) / secs < CONTAM


def do_job(job):
    spec = json.loads(job["spec"])
    if job["kind"] == "shim":
        return run_shim(job, spec)
    cl = run.Client(job["client"])
    mode, b = job["mode"], job["base"]
    meta = {k: cl.meta.get(k) for k in ("repo", "sha", "date", "toolchain")}
    base = {"kind": "field", "job": job["id"], "jobkind": job["kind"], "client": cl.name, **meta, "era": cl.era,
            "mode": mode, "base": b, "rep": spec.get("rep", 0)}
    if mode not in cl.modes:
        emit({**base, "kind": "unsupported"}); return "skipped", "mode not supported"
    W = spec["field_size"]
    strata = spec["strata"]
    if spec.get("calibrate"):
        cap = spec["cap"]
        mid = strata[len(strata) // 2]["start"]
        size, ru = run.calibrate(cl, mode, b, mid, cap, core, spec.get("target_secs", 8))
        emit({**base, "kind": "calibration", "size": size, "ru": ru})
        if size is None:
            return "failed", f"calibration failed rc={ru.get('rc')}"
    else:
        size = W
    fields = [(f["start"], f["start"] + size) for f in strata]
    warm = None
    if spec.get("warmup", True) and cl.repeat:
        w0 = min(strata, key=lambda f: f["pred"])
        # per-field setup measured negligible (one-shot == repeat), so keep the warm-up short
        warm = (w0["start"], w0["start"] + (max(1000, size // 20) if spec.get("calibrate") else min(size, 10**9)))
    if not spec.get("warmup", True):
        cl.repeat = False
    if cl.era == "v3" and (cl.meta.get("date") or "") >= ASYNC_FROM:
        # The async pipeline (#71, 2026-02-07) runs a prefetched field concurrently with the
        # current one on the same pinned core, which distorts per-field times: one field per
        # process instead (per-field setup was measured negligible).
        cl.repeat = False
        warm = None
    secs, ru, bodies, how = run.measure(cl, mode, b, fields, core, spec.get("timeout", 4 * 3600), warm)
    if how == "oneshot" and len(fields) == 1 and secs[0] is not None and contaminated(secs[0], ru):
        n = int((job.get("note") or "contam:0").split(":")[1]) + 1
        emit({**base, "kind": "contaminated", "secs": secs[0], "ru": ru, "attempt": n})
        if n < 3:
            return "pending", f"contam:{n}"
    for f, s, (st, en), body in zip(strata, secs, fields, bodies):
        if body is not None:
            store_sub(cl, mode, b, st, en - st, body)
        emit({**base, "stratum": f["stratum"], "K": len(strata), "pred": f["pred"], "w": f.get("w"), "start": st, "size": en - st,
              "field_size": W, "subwindow": en - st < W, "secs": s, "rate": (en - st) / s if s else None,
              "how": how, "repeat_broken": cl.repeat_broken, "ru": ru})
    if any(s is None for s in secs):
        return "failed", f"rc={ru.get('rc')}"
    return "done", ""


def canary():
    cl = run.Client(CANARY)
    cl.repeat = False  # async client: a warm-up would overlap the timed field
    s = corpus["bases"]["50"]["detailed_start"]
    secs, ru, _, _ = run.measure(cl, "detailed", 50, [(s, s + 5 * 10**7)], core, 600)
    emit({"kind": "canary", "client": CANARY, "secs": secs[0], "size": 5 * 10**7})


# A job this worker left 'running' (crash or kill) goes back to the queue.
db().execute("UPDATE jobs SET status = 'pending', worker = NULL WHERE status = 'running' AND worker = ?", (wid,))
mock = subprocess.Popen([sys.executable, str(HERE / "mock" / "server.py"), str(port)],
                        stdout=open(f"logs/mock-{port}.log", "a"), stderr=subprocess.STDOUT)
time.sleep(1)
last_canary = 0
CODE = [HERE / "worker.py", HERE / "run.py", HERE / "mock" / "server.py"]
code_mtime = max(p.stat().st_mtime for p in CODE)
try:
    while not (HERE / "STOP").exists():
        # Deploy = rsync new code; each worker exits between jobs and its supervisor restarts
        # it, so running jobs (some take a day) are never killed by a deploy.
        if max(p.stat().st_mtime for p in CODE) != code_mtime:
            break
        if time.time() - last_canary > CANARY_EVERY:
            canary(); last_canary = time.time()
        job = claim()
        if not job:
            time.sleep(60); continue
        try:
            status, note = do_job(job)
        except Exception as e:  # keep the worker alive; the job is marked and reviewed at checkpoints
            status, note = "failed", f"{type(e).__name__}: {e}"
            emit({"kind": "error", "job": job["id"], "client": job["client"], "error": note})
        finish(job["id"], status, note)
finally:
    mock.terminate()
