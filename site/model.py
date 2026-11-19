"""Production-size model for the overlap join (imported by build.py).

Base 64 has no production field yet; its planned size is 1e18, too long to time on one core
(about 11 core-days on v3.4.7). The model: a field's time is its top-layer prefix count times a
per-prefix cost. That cost falls while fixed costs amortise, bottoms out around 1e15-1e16 and then
rises a few percent per decade. Measured per-prefix cost at 1e16-1e17, carried to 1e18 by the
measured drift, gives the rate. Run 2 checked it out of sample: v3.4.7 at b64 1e17 was predicted
at 1.265e12/s before it ran and measured at 1.276e12/s.
"""
import json
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "harness"))
from corpus_strata import strata  # noqa: E402  (the stratifier the field lists were made with)

V347, V346 = "8bd154b", "9a4f740"


def compute(recs):
    """recs: every measurement record. Returns the field-size series and the cost model."""
    pts = defaultdict(dict)  # (sha7, base, field size) -> {stratum: record}
    for r in recs:
        if r.get("kind") != "field" or r.get("mode") != "niceonly" or not r.get("secs") or r.get("rep", 0) != 0:
            continue
        if r["base"] not in (57, 58, 60, 62, 64) or r["date"] < "2026-10-07" or r["client"].endswith("-tc100"):
            continue
        pts[(r["sha"][:7], r["base"], r["field_size"])][r["stratum"]] = r

    def rate(byst):
        ws = [x.get("w") or 0 for x in byst.values()]
        if abs(sum(ws) - 1) > 1e-6:
            return None  # incomplete
        return sum(ws) / sum(w * x["secs"] / x["size"] for w, x in zip(ws, byst.values()))

    series = defaultdict(dict)  # (sha7, base) -> {field size: rate}
    for (sha, b, W), byst in pts.items():
        rt = rate(byst)
        if rt:
            series[(sha, b)][W] = rt

    def per_prefix(sha, b, W):
        nz = [(x["pred"], x["secs"]) for x in pts.get((sha, b, int(W)), {}).values() if x["pred"] > 0]
        return sum(t for _, t in nz) / sum(p for p, _ in nz) if nz else None

    cand = json.loads((ROOT / "harness/corpus/candidates.json").read_text())
    st18 = strata([tuple(x) for x in cand["ladder:64:1e18"]], 5)
    wp = sum(f["w"] * f["pred"] for f in st18)
    mean_pred = st.mean(f["pred"] for f in st18 if f["pred"])

    c16, c17 = per_prefix(V347, 64, 1e16), per_prefix(V347, 64, 1e17)
    drift_b64 = c17 / c16
    drift_b62 = per_prefix(V347, 62, 1e17) / per_prefix(V347, 62, 1e16)
    central = 1e18 / (c17 * drift_b64 * wp)
    cost = {"drift_per_decade": {"b62": drift_b62, "b64": drift_b64},
            "b64_1e18": {V347: {"rate": central, "band": [central * 0.95, central * 1.05],
                                "core_days": c17 * drift_b64 * mean_pred / 86400, "how": "own b64 1e16 and 1e17"}}}

    # the out-of-sample check, predicted before the b64 1e17 fields ran
    pred17 = json.loads((ROOT / "data/b64_1e17_prediction.json").read_text())["prediction"]
    s17 = pts[(V347, 64, 10**17)]
    if 1 in s17 and 2 in s17:
        lad = {f["stratum"]: f for f in json.loads((ROOT / "harness/corpus/ladder.json").read_text())["64:17"]["fields"]}
        t17 = sum(lad[k]["w"] * s17[k]["secs"] for k in lad if k in s17)
        cost["check_b64_1e17"] = {"predicted_rate": pred17["rate"], "measured_rate": 1e17 / t17,
                                  "fields_h": [(pred17["s1_h"], s17[1]["secs"] / 3600), (pred17["s2_h"], s17[2]["secs"] / 3600)]}

    # builds with their own b64 1e16 ladder and b62 1e16/1e17: carry their b64 1e16 per-prefix cost two
    # decades with v3.4.7's b64 drift, scaled by the build's b62 drift relative to v3.4.7's
    for (sha, b), s in series.items():
        if sha == V347 or b != 64 or 10**16 not in s:
            continue
        if not (per_prefix(sha, 62, 1e17) and per_prefix(sha, 62, 1e16)):
            continue
        d62 = per_prefix(sha, 62, 1e17) / per_prefix(sha, 62, 1e16)
        d64 = drift_b64 * d62 / drift_b62
        c18 = per_prefix(sha, 64, 1e16) * d64 ** 2
        r = 1e18 / (c18 * wp)
        cost["b64_1e18"][sha] = {"rate": r, "band": [r * 0.95, r * 1.05], "core_days": c18 * mean_pred / 86400,
                                 "how": "own b64 1e16, drift scaled by b62", "drift_b62": d62}
    # builds with only a b62 1e17 field: transfer through their b62 1e17 rate relative to v3.4.7
    r62 = series[(V347, 62)].get(10**17)
    for (sha, b), s in series.items():
        if b == 62 and 10**17 in s and sha not in cost["b64_1e18"]:
            r = central * s[10**17] / r62
            cost["b64_1e18"][sha] = {"rate": r, "band": [r * 0.95, r * 1.05], "how": "b62 1e17 ratio to v3.4.7"}
    return {"series": series, "cost": cost}
