#!/usr/bin/env python3
"""Measure historical nice clients against the mock API, one pinned core each.

  run.py <plan.json>

plan: {"clients": [bin dir names], "bases": [..], "modes": [..], "corpus": "corpus/x.json",
       "reps": 3, "target_secs": 15, "core": 3, "out": "results/x.jsonl", "canary": dir|null}

Uniform-rate clients (no position-dependent filter: everything before MSD landed in
nice on 2026-02-03) are timed on a calibrated sub-window at each stratum's start.
Later clients get the whole production field. Clients with --repeat process a warm-up
field first and are timed submit-to-submit, so per-base setup is amortized the way it
is in production.
"""
import json, os, random, signal, subprocess, sys, time, urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
API = os.environ.get("PERFHIST_API", "http://127.0.0.1:8650")
MSD_EPOCH = "2026-02-03"


def ctl(path, body=None):
    # Generous timeout + retries: a starved mock (e.g. the host's nightly backup) must not
    # turn into a failed job, let alone an orphaned client.
    for attempt in range(6):
        try:
            req = urllib.request.Request(API + path, data=None if body is None else json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read())
        except (TimeoutError, OSError):
            if attempt == 5:
                raise
            time.sleep(5 * (attempt + 1))


class Client:
    def __init__(self, name):
        self.name, self.dir = name, HERE / "bins" / name
        if (self.dir / "main.py").exists():
            self.meta = {"repo": "nice-client-py", "sha": name.split("-")[-1], "date": "-".join(name.split("-")[3:6]),
                         "toolchain": subprocess.check_output([self.dir / "venv/bin/python", "-V"], text=True).strip()}
            self.help, self.era = "", "jan23"
        else:
            self.meta = json.loads((self.dir / "build.json").read_text())
            self.help = subprocess.run([self.dir / "client", "--help"], capture_output=True, text=True).stdout
            if self.meta["repo"] == "nice":
                # the first monorepo builds (2024-07-04..06) still speak the nice-rust protocol
                blob = (self.dir / "client").read_bytes()
                self.era = "rust2" if b"search_start" in blob and b"range_start" not in blob else "v3"
                if self.meta["sha"][:7] in ("d2cfdb0", "b610935"):
                    self.era = "rust2int"  # u128 fields as plain JSON numbers (between the two formats)
            else:
                self.era = "rust2" if "--api-base" in self.help else "jan23"
        self.modes = ["detailed", "niceonly"] if "niceonly" in self.help else ["detailed"]
        self.repeat = "--repeat" in self.help or self.era == "jan23" and self.meta["repo"] == "nice-client-py"
        self.uniform = self.meta["repo"] != "nice" or self.meta["date"] < MSD_EPOCH
        self.threads = "1"
        self.repeat_broken = False

    def cmd(self, mode):
        if self.meta["repo"] == "nice-client-py":
            return [str(self.dir / "venv/bin/python"), str(self.dir / "main.py")]
        c = [str(self.dir / "client")]
        if self.era == "jan23":
            return c + (["--quiet"] if "--quiet" in self.help else [])  # 3a5d367 (2023-01-30) has no -q
        # Options first, mode last: v2.0.x takes the mode as a clap subcommand, which must
        # follow the options; the later positional MODE accepts either order.
        c += ["--api-base", API]
        for flag, extra in (("--repeat", []), ("--threads", [self.threads]), ("--no-progress", []),
                            ("--prefetch-max", ["1"]), ("--quiet", [])):
            if flag in self.help:
                c += [flag] + extra
        return c + [mode]


def run_queue(cl, mode, base, fields, core, timeout):
    """One process over `fields` (repeat clients) -> per-field seconds, rusage, submissions."""
    # A trailing 1000-number sentinel: the early-2026 async clients submit a field only once
    # their next claim succeeds, so the last timed field needs one more field behind it.
    sentinel = [fields[-1][0], fields[-1][0] + 1000]
    ctl("/_ctl/arm", {"run_id": f"{cl.name}:{mode}:{base}", "era": cl.era, "mode": mode, "base": base,
                      "fields": [[s, e] for s, e in fields] + [sentinel]})
    env = dict(os.environ, RAYON_NUM_THREADS=cl.threads, USERNAME="perfhist", NICE_VERSION="perfhist",
               RUST_LOG="error", NICE_NO_PROGRESS="1")
    log = open(HERE / os.environ.get("PERFHIST_LOG", "logs/client.log"), "ab")
    p = subprocess.Popen(["taskset", "-c", str(core)] + cl.cmd(mode), env=env, stdout=log, stderr=log,
                         start_new_session=True)
    try:
        return _wait_and_collect(p, fields, timeout)
    finally:
        try:  # never leave a client behind: it would share its core with the next job
            os.killpg(p.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def _wait_and_collect(p, fields, timeout):
    t0, rc, ru, hwm = time.monotonic(), None, None, None
    while True:
        try:  # peak RSS of the client itself (ru_maxrss would include the pre-exec fork)
            hwm = int(next(l for l in open(f"/proc/{p.pid}/status") if l.startswith("VmHWM")).split()[1])
        except (OSError, StopIteration):
            pass
        r = ctl("/_ctl/result")
        if set(range(1, len(fields) + 1)) <= set(r.get("submit_ids", [])):
            break
        pid, status, ru_ = os.wait4(p.pid, os.WNOHANG)
        if pid:
            rc, ru = status, ru_
            break
        if time.monotonic() - t0 > timeout:
            rc = "timeout"
            break
        # The submit time is stamped by the server, so polling only sets how soon we notice.
        time.sleep(min(1.0, 0.02 + (time.monotonic() - t0) / 20))
    if ru is None:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        _, status, ru = os.wait4(p.pid, 0)
        rc = rc or "killed-after-submit"
    r = ctl("/_ctl/result?full=1")
    claims = {int(k): v for k, v in r["claims"].items()}
    subs = {int(k): v for k, v in r["submits"].items()}
    secs, prev = [], None
    for i in range(1, len(fields) + 1):
        if i not in subs:
            secs.append(None); continue
        start = claims[i] if prev is None else max(claims[i], prev)
        secs.append(subs[i]["t"] - start)
        prev = subs[i]["t"]
    return secs, {"rc": rc, "hwm_kb": hwm, "utime": ru.ru_utime, "stime": ru.ru_stime}, \
        [subs.get(i, {}).get("body") for i in range(1, len(fields) + 1)]


def measure(cl, mode, base, fields, core, timeout, warmup=None):
    """Per-field seconds for `fields`; repeat clients first get `warmup` (default: a copy
    of the first field) so per-base setup is not charged to a measured field."""
    if cl.repeat and len(fields) >= 1:
        secs, ru, bodies = run_queue(cl, mode, base, [warmup or fields[0]] + fields, core, timeout)
        if secs[0] is not None and None in secs[1:] and ru["rc"] != "timeout":
            # --repeat is broken in this build (v3.2.x recurses into main() and re-inits
            # rayon's global pool): it is effectively a one-shot client.
            cl.repeat, cl.repeat_broken = False, True
        else:
            return secs[1:], ru, bodies[1:], "repeat"
    out = [run_queue(cl, mode, base, [f], core, timeout) for f in fields]
    return [o[0][0] for o in out], out[-1][1], [o[2][0] for o in out], "oneshot"


def round125(x):
    m = 10 ** int(f"{x:e}".split("e")[1])
    return int(max(k for k in (1, 2, 5, 10) if k * m <= x) * m)


def calibrate(cl, mode, base, start, cap, core, target):
    s = 1000
    while True:
        secs, ru, _, _ = measure(cl, mode, base, [(start, start + s)], core, 3600)
        t = secs[0]
        if t is None:
            return None, ru
        if t >= 1.0 or s >= cap:
            return min(cap, max(1000, round125(s * target / t))), ru
        s = min(cap, s * 10 if t < 0.1 else int(s * 2 / t))


def canon(body):
    """-> (histogram {uniques: count}, near/nice {n: uniques or None})"""
    if not body:
        return None, None
    hist, near = {}, {}
    if "unique_distribution" in body or "nice_numbers" in body:
        ud = body.get("unique_distribution") or []
        # v3.0 (2024-07-07) sent maps {uniques: count} / {n: uniques}; later v3 sends lists
        for u, cnt in (ud.items() if isinstance(ud, dict) else ((d["num_uniques"], d["count"]) for d in ud)):
            if int(cnt):
                hist[int(u)] = int(cnt)
        for d in body.get("nice_numbers") or []:
            near[int(d["number"])] = int(d["num_uniques"])
        nl = body.get("nice_list") or {}
        for n, u in (nl.items() if isinstance(nl, dict) else ((x, None) for x in nl)):
            near[int(str(n).strip('"'))] = None if u is None else int(u)
    else:
        for k, v in (body.get("unique_count") or {}).items():
            if int(v):
                hist[int(k)] = int(v)
        for k, v in (body.get("near_misses") or {}).items():
            near[int(str(k).strip('"'))] = int(v)
        for n in body.get("nice_list") or []:
            near[int(str(n).strip('"'))] = None
    return hist, near


def main():
    plan = json.loads(Path(sys.argv[1]).read_text())
    corpus = json.loads((HERE / plan["corpus"]).read_text())
    core, target, reps = plan.get("core", 3), plan.get("target_secs", 15), plan.get("reps", 3)
    out = open(HERE / plan["out"], "a")
    subs_dir = HERE / "results" / "subs"; subs_dir.mkdir(parents=True, exist_ok=True)
    clients = [Client(n) for n in plan["clients"]]
    canary = Client(plan["canary"]) if plan.get("canary") else None

    def emit(rec):
        out.write(json.dumps(rec) + "\n"); out.flush()

    def do_canary(tag):
        if not canary:
            return
        b = 50; s = int(corpus["bases"][str(b)]["fields"][2]["start"])
        secs, ru, bodies, how = measure(canary, "detailed", b, [(s, s + plan.get("canary_size", 10**7))], core, 600)
        emit({"kind": "canary", "tag": tag, "client": canary.name, "secs": secs[0], "size": plan.get("canary_size", 10**7),
              "ts": time.time()})

    # Calibrate sub-window sizes for uniform clients (median stratum), once.
    sizes = {}
    groups = []
    for cl in clients:
        for mode in plan["modes"]:
            if mode not in cl.modes:
                continue
            for b in plan["bases"]:
                bc = corpus["bases"][str(b)]
                W = int(bc["field_size"])
                cap = W if mode == "niceonly" else min(W, 10**9)
                if cl.uniform or mode == "detailed":
                    mid = int(bc["fields"][len(bc["fields"]) // 2]["start"])
                    s, ru = calibrate(cl, mode, b, mid, cap, core, target)
                    sizes[(cl.name, mode, b)] = s
                    emit({"kind": "calibration", "client": cl.name, "mode": mode, "base": b, "size": s, "ru": ru,
                          "ts": time.time()})
                    if s is None:
                        continue
                groups.append((cl, mode, b))
    print(f"{len(groups)} groups", flush=True)

    do_canary("start")
    passes = [(rep, groups) for rep in range(reps)]
    # Setup-cost check: the same groups again as one process per field.
    for name in plan.get("oneshot_compare", []):
        twin = Client(name); twin.repeat = False
        passes.append(("oneshot", [(twin, m, b) for c, m, b in groups if c.name == name]))
    for rep, groups in passes:
        if isinstance(rep, int):
            random.Random(rep).shuffle(groups)
        for gi, (cl, mode, b) in enumerate(groups):
            bc = corpus["bases"][str(b)]
            W = int(bc["field_size"])
            strata = bc["fields"] if mode == "niceonly" else bc["fields"][len(bc["fields"]) // 2:][:1]
            sub = sizes.get((cl.name, mode, b))
            size = sub if sub else W
            fields = [(int(f["start"]), int(f["start"]) + size) for f in strata]
            w0 = min(bc["fields"], key=lambda f: f["pred"])
            warm = (int(w0["start"]), int(w0["start"]) + size)
            secs, ru, bodies, how = measure(cl, mode, b, fields, core, plan.get("timeout", 7200), warm)
            for f, s, (st, en), body in zip(strata, secs, fields, bodies):
                h, n = canon(body)
                key = f"{b}-{mode}-{st}-{en - st}"
                if body is not None:
                    (subs_dir / f"{cl.name}--{key}.json").write_text(json.dumps({"hist": h, "near": {str(k): v for k, v in (n or {}).items()}}))
                emit({"kind": "field", "client": cl.name, **{k: cl.meta.get(k) for k in ("repo", "sha", "date", "toolchain")},
                      "era": cl.era, "mode": mode, "base": b, "stratum": f["stratum"], "pred": f["pred"],
                      "start": st, "size": en - st, "field_size": W, "subwindow": en - st < W, "rep": rep,
                      "secs": s, "rate": (en - st) / s if s else None, "how": how, "repeat_broken": cl.repeat_broken, "ru": ru, "ts": time.time()})
            print(f"rep {rep} {gi + 1}/{len(groups)} {cl.name} {mode} b{b}: "
                  + " ".join(f"{s:.2f}" if s else "FAIL" for s in secs), flush=True)
            if (gi + 1) % 6 == 0:
                do_canary(f"rep{rep}-g{gi}")
    do_canary("end")


if __name__ == "__main__":
    main()
