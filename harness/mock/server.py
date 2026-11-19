#!/usr/bin/env python3
"""Mock nice API that serves one armed field per run, in the wire format of any
client era, and times claim -> submit on the server side.

Eras (wire formats):
  jan23  GET /claim?username=..        -> {search_id, base, search_start, search_end} (JSON ints)
         POST /submit                  {search_id, unique_count{u:count}, near_misses{n:u}}
  rust2  GET /claim/{detailed,niceonly}?username=..&max_base=..
                                       -> {id, username, base, search_start, search_end, search_range} (strings)
         POST /submit/{detailed,niceonly} {id, unique_count, near_misses, nice_list}
  v3     GET /claim/{detailed,niceonly} -> {claim_id, base, range_start, range_end, range_size} (JSON ints)
         POST /submit                  {claim_id, unique_distribution[], nice_numbers[]}

Control (harness only):
  POST /_ctl/arm     {run_id, era, mode, base, fields: [[start, end], ...]}
  GET  /_ctl/result  -> {run_id, claims: {id: t}, submits: {id: {t, path, body}}, log}
Claims are served in order with ids 1..n; once the queue is empty, claims get 503.
"""
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

LOCK = threading.Lock()
HANG_SECS = 300
STATE = {"armed": None, "next": 0, "claims": {}, "submits": {}, "log": []}


def claim_body(a, i):
    (s, e), b = a["fields"][i - 1], a["base"]
    if a["era"] == "jan23":
        return {"search_id": i, "base": b, "search_start": s, "search_end": e}
    if a["era"] == "rust2int":  # monorepo 2024-07-05/06: nice-rust field names, u128 as JSON ints
        return {"id": i, "username": "perfhist", "base": b, "search_start": s, "search_end": e, "search_range": e - s}
    if a["era"] == "rust2":
        return {"id": i, "username": "perfhist", "base": b,
                "search_start": str(s), "search_end": str(e), "search_range": str(e - s)}
    return {"claim_id": i, "base": b, "range_start": s, "range_end": e, "range_size": e - s}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def do_GET(self):
        path = urlparse(self.path).path
        with LOCK:
            if not path.startswith("/_ctl"):
                STATE["log"].append(("GET", self.path, time.monotonic()))
            if path == "/_ctl/result":
                a = STATE["armed"] or {}
                full = "full" in (urlparse(self.path).query or "")
                return self._send(200, {"run_id": a.get("run_id"), "claims": STATE["claims"],
                                        "n_submits": len(STATE["submits"]),
                                        "submit_ids": sorted(STATE["submits"]),
                                        "submits": STATE["submits"] if full else {},
                                        "log": STATE["log"] if full else []})
            a = STATE["armed"]
            if path in ("/claim", "/claim/detailed", "/claim/niceonly") and a:
                want = {"/claim": None, "/claim/detailed": "detailed", "/claim/niceonly": "niceonly"}[path]
                if want and want != a["mode"]:
                    return self._send(503, {"error": "wrong mode"})
                if STATE["next"] >= len(a["fields"]):
                    hang = True
                else:
                    hang = False
                if not hang:
                    STATE["next"] += 1
                    i = STATE["next"]
                    self._send(200, claim_body(a, i))
                    STATE["claims"][i] = time.monotonic()
                    return
            else:
                return self._send(404, {"error": "unknown " + path})
        # Queue exhausted: a prefetching client (2026 async pipeline) asks for the next field
        # while still working. Hold the request open, as a busy server would, instead of
        # refusing it: a 503 sends those builds into a claim-retry loop that stalls the
        # submission being timed. The harness kills the client after the last submit.
        armed = STATE["armed"]
        t0 = time.monotonic()
        while STATE["armed"] is armed and time.monotonic() - t0 < HANG_SECS:
            time.sleep(0.5)
        self._send(503, {"error": "no field"})

    def do_POST(self):
        path = urlparse(self.path).path
        raw = self._body()
        t = time.monotonic()
        with LOCK:
            if not path.startswith("/_ctl"):
                STATE["log"].append(("POST", self.path, t))
            if path == "/_ctl/arm":
                STATE["armed"] = json.loads(raw)
                STATE["next"] = 0
                STATE["claims"], STATE["submits"], STATE["log"] = {}, {}, []
                return self._send(200, {"ok": True})
            if path.startswith("/submit") and STATE["armed"]:
                body = json.loads(raw or b"{}")
                i = body.get("claim_id", body.get("id", body.get("search_id")))
                STATE["submits"][int(i)] = {"t": t, "path": path, "body": body}
                return self._send(200, {})
        self._send(404, {"error": "unknown " + path})


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8650
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
