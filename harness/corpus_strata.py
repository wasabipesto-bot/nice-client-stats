import json
def strata(cand, K):
    """Zero-cost fields form one stratum weighted by their share; the rest is cut into
    equal-probability strata, each represented by the field nearest the stratum's mean
    prediction (cost is ~linear in it). Mean field time = sum_k w_k * t_k."""
    cand = sorted(cand)
    n = len(cand)
    zeros = [c for c in cand if c[0] == 0]
    nz = [c for c in cand if c[0] != 0]
    out = []
    if zeros:
        out.append({"pred": 0, "start": zeros[len(zeros) // 2][1], "w": len(zeros) / n})
    k = min(len(nz), K - 1 if zeros else K)
    for i in range(k):
        part = nz[i * len(nz) // k:(i + 1) * len(nz) // k]
        mean = sum(c[0] for c in part) / len(part)
        pick = min(part, key=lambda c: abs(c[0] - mean))
        out.append({"pred": pick[0], "start": pick[1], "w": len(part) / n, "stratum_mean_pred": mean})
    for i, f in enumerate(out):
        f["stratum"] = i
    return out


