"""The dashboard's figures (imported by build.py). Every colour is a light-theme token; the page
swaps each for its dark counterpart (THEME) when the dark theme is on, so one figure serves both."""
import datetime as dt
import math
import statistics as st
from collections import defaultdict

import plotly.graph_objects as go
from plotly.subplots import make_subplots

# ---- palette (validated reference palette; light token -> dark token) -----------------------------
SURFACE, TEXT, TEXT2, GRID, MUTED, BAND = "#fcfcfb", "#0b0b0b", "#52514e", "#e6e5e0", "#d8d7d2", "#f5edd9"
CAT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
SEQ = ["#86b6ef", "#5598e7", "#2a78d6", "#1c5cab", "#104281", "#0d366b"]
DIV_MID = "#f0efec"
GOOD, WARN, CRIT = "#0ca30c", "#fab219", "#d03b3b"
THEME = {SURFACE: "#1a1a19", TEXT: "#f0efec", TEXT2: "#c3c2b7", GRID: "#383835", MUTED: "#4a4a46", BAND: "#3b3527",
         DIV_MID: "#383835",
         **dict(zip(CAT, ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"])),
         **dict(zip(SEQ, ["#184f95", "#256abf", "#3987e5", "#6da7ec", "#9ec5f4", "#cde2fb"]))}
DETAILED, NICEONLY, PRODUCTION, MODELLED = CAT[0], CAT[1], CAT[2], CAT[6]
FONT = "system-ui, -apple-system, 'Segoe UI', sans-serif"
NICEONLY_FROM = "2023-04-02"  # nice-rust v2.0.0: the first client with a nice-only mode
UNSOUND = ("2026-02-07", "2026-08-06")  # a filter skipped some ranges it should have checked (fixed 2026-08-06)
WORDS = [(1e12, "trillion"), (1e9, "billion"), (1e6, "million"), (1e3, "thousand")]


def words(x):
    for v, w in WORDS:
        if x >= v:
            n = x / v
            return f"{n:.3g} {w}" if n < 100 else f"{n:.0f} {w}"
    return f"{x:.3g}"


def short(x):
    for v, w in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "k")):
        if x >= v:
            return f"{x / v:g}{w}"
    return f"{x:g}"


def frame(fig, h, legend=True, top=40):
    fig.update_layout(template="none", height=h, paper_bgcolor=SURFACE, plot_bgcolor=SURFACE,
                      font=dict(family=FONT, color=TEXT2, size=12), showlegend=legend,
                      legend=dict(orientation="h", yref="container", y=1, yanchor="top", x=0, font=dict(color=TEXT2)),
                      hoverlabel=dict(bgcolor=SURFACE, bordercolor=GRID, font=dict(color=TEXT, family=FONT)),
                      margin=dict(l=80, r=20, t=top, b=50))
    fig.update_xaxes(showgrid=False, linecolor=TEXT2, tickcolor=GRID, zeroline=False)
    fig.update_yaxes(gridcolor=GRID, zeroline=False, showline=False)
    fig.update_annotations(font=dict(color=TEXT, size=13))
    return fig


def rate_axis(fig, lo, hi, long=False, title="numbers checked per second", **kw):
    decades = range(math.floor(math.log10(lo)), math.ceil(math.log10(hi)) + 1)
    steps = (1, 2, 5) if math.log10(hi / lo) <= 2.5 else (1,)
    ticks = [m * 10 ** e for e in decades for m in steps if lo <= m * 10 ** e <= hi]
    fig.update_yaxes(type="log", range=[math.log10(lo), math.log10(hi)], tickvals=ticks,
                     ticktext=[words(t) if long else short(t) for t in ticks], title=title, **kw)


def point_text(D, client):
    c = D["commits"][client]
    return [c["label"], c["subject_short"][:90], c["date"]]


HOVER = "%{customdata[2]} · <b>%{customdata[0]}</b><br>%{customdata[1]}<br><b>%{customdata[3]}</b><extra>%{fullData.name}</extra>"


def custom(D, rows):
    return [point_text(D, r["client"]) + [words(r["rate"]) + "/s"] for r in rows]


def releases(fig, D, labels=True, rows=None, gap=40):
    """Release dates as thin lines behind the data; labels above the plot, thinned to stay legible."""
    tags = sorted({(c["date"], c["tag"]) for c in D["commits"].values() if c["tag"]})
    cells = rows or [(None, None)]
    last = None
    for d, t in tags:
        for row, col in cells:
            fig.add_vline(x=d, line=dict(color=GRID, width=1), layer="below", **({"row": row, "col": col} if row else {}))
        day = dt.date.fromisoformat(d).toordinal()
        if labels and (last is None or day - last >= gap):
            last = day
            fig.add_annotation(x=d, y=1, yref="paper", yanchor="bottom", xanchor="center", text=t, textangle=-90,
                               showarrow=False, font=dict(size=10, color=TEXT2))


def unsound_band(fig, rows=None, legend=True):
    for row, col in rows or [(None, None)]:
        fig.add_vrect(x0=UNSOUND[0], x1=UNSOUND[1], fillcolor=BAND, line_width=0, layer="below",
                      **({"row": row, "col": col} if row else {}))
    if legend:
        fig.add_trace(go.Scatter(x=[None], y=[None], mode="markers", marker=dict(symbol="square", size=12, color=BAND),
                                 name="nice-only rates inflated by a filter bug (fixed Aug 2026)", hoverinfo="skip"))


def series(D, mode, base):
    rows = [r for r in D["rates"] if r["mode"] == mode and r["base"] == base]
    return sorted(rows, key=lambda r: D["okey"](r["client"]))


def niceonly_line(D, base):
    """Nice-only rate over time; before the mode existed the client ran the full (detailed) check."""
    pre = [r for r in series(D, "detailed", base) if D["commits"][r["client"]]["date"] < NICEONLY_FROM]
    return pre + [r for r in series(D, "niceonly", base) if D["commits"][r["client"]]["date"] >= NICEONLY_FROM]


def modelled_b64(D):
    out = []
    for sha, v in D["model"]["cost"]["b64_1e18"].items():
        c = next(c for c in D["commits"].values() if c["sha"] == sha)
        out.append({"client": c["name"], "rate": v["rate"], "band": v["band"], "how": v["how"]})
    return sorted(out, key=lambda r: D["okey"](r["client"]))


# ---- 1. hero: base 64 ---------------------------------------------------------------------------
def hero(D):
    fig = go.Figure()
    line = niceonly_line(D, 64)
    x = lambda rows: [D["commits"][r["client"]]["date"] for r in rows]  # noqa: E731
    fig.add_trace(go.Scatter(x=x(line), y=[r["rate"] for r in line], mode="lines", line=dict(color=CAT[0], width=2.5, shape="hv"),
                             name="Measured on fields of up to 10¹³ numbers", customdata=custom(D, line), hovertemplate=HOVER))
    mod = modelled_b64(D)
    fig.add_trace(go.Scatter(x=x(mod), y=[r["rate"] for r in mod], mode="lines", line=dict(color=CAT[1], width=2.5, shape="hv"),
                             name="Modelled on production fields of 10¹⁸ numbers", customdata=custom(D, mod), hovertemplate=HOVER))
    releases(fig, D)
    unsound_band(fig)

    def note(row, text, ax, ay):
        fig.add_annotation(x=D["commits"][row["client"]]["date"], y=math.log10(row["rate"]), text=text, ax=ax, ay=ay,
                           showarrow=True, arrowhead=0, arrowwidth=1, arrowcolor=TEXT2, font=dict(size=12, color=TEXT),
                           align="left", xanchor="left" if ax > 0 else "right")
    by_tag = {D["commits"][r["client"]]["tag"]: r for r in line if D["commits"][r["client"]]["tag"]}
    note(line[0], "Python client<br>" + words(line[0]["rate"]) + "/s", 40, 0)
    if "v2.0.3" in by_tag:
        note(by_tag["v2.0.3"], "Rust client with a residue filter<br>" + words(by_tag["v2.0.3"]["rate"]) + "/s", 30, -40)
    if "v3.2.12" in by_tag:
        note(by_tag["v3.2.12"], "Most-significant-digit filter<br>" + words(by_tag["v3.2.12"]["rate"]) + "/s", -30, -30)
    if mod:
        note(mod[0], f"Overlap join ({D['commits'][mod[0]['client']]['label']})<br>{words(mod[0]['rate'])}/s", -50, 0)
        last = mod[-1]
        note(last, f"{D['commits'][last['client']]['label']}<br>{words(last['rate'])}/s", 24, 0)
    frame(fig, 560, top=80)
    rate_axis(fig, 1.5e4, 2e13, long=True, title=dict(text="numbers checked per second", standoff=12))
    fig.update_xaxes(type="date", range=["2022-12-01", (dt.date.today() + dt.timedelta(days=150)).isoformat()])
    fig.update_layout(legend=dict(yref="paper", y=0.98, yanchor="top", x=0.01, bgcolor=SURFACE), margin=dict(l=120))
    return fig


# ---- 2. other bases --------------------------------------------------------------------------------
def bases(D):
    bs = (40, 50, 60, 62)
    fig = make_subplots(rows=2, cols=2, shared_xaxes=True, subplot_titles=[f"Base {b}" for b in bs],
                        vertical_spacing=0.09, horizontal_spacing=0.07)
    cells = [(1, 1), (1, 2), (2, 1), (2, 2)]
    for i, (b, (row, col)) in enumerate(zip(bs, cells)):
        det = series(D, "detailed", b)
        nic = niceonly_line(D, b)
        for rows, name, color in ((det, "Detailed mode (full check of every number)", DETAILED),
                                  (nic, "Nice-only mode (fields of up to 10¹³)", NICEONLY)):
            fig.add_trace(go.Scatter(x=[D["commits"][r["client"]]["date"] for r in rows], y=[r["rate"] for r in rows],
                                     mode="lines", line=dict(color=color, width=2, shape="hv"), name=name, legendgroup=name,
                                     showlegend=i == 0, customdata=custom(D, rows), hovertemplate=HOVER), row=row, col=col)
        prod = [r for r in D["production"] if r["base"] == b]
        if prod:
            fig.add_trace(go.Scatter(x=[D["commits"][r["client"]]["date"] for r in prod], y=[r["rate"] for r in prod],
                                     mode="markers", marker=dict(color=PRODUCTION, size=9, symbol="diamond", line=dict(color=SURFACE, width=1.5)),
                                     name="Nice-only, production-size fields", legendgroup="prod", showlegend=b == 60,
                                     customdata=custom(D, prod), hovertemplate=HOVER), row=row, col=col)
    releases(fig, D, labels=False, rows=cells)
    unsound_band(fig, rows=cells)
    frame(fig, 740, top=100)
    fig.update_xaxes(type="date")
    fig.update_yaxes(type="log", tickvals=[10 ** e for e in range(4, 14)], ticktext=[short(10 ** e) for e in range(4, 14)])
    fig.update_yaxes(title="numbers checked per second", col=1)
    return fig


# ---- 3. production-size fields ---------------------------------------------------------------------
def production(D):
    fig = go.Figure()
    prod = D["production"]
    builds = sorted({r["client"] for r in prod}, key=D["okey"])
    label = {c: f"{D['commits'][c]['label']}" for c in builds}
    for i, b in enumerate(sorted({r["base"] for r in prod})):
        rows = sorted([r for r in prod if r["base"] == b], key=lambda r: D["okey"](r["client"]))
        fig.add_trace(go.Scatter(x=[label[r["client"]] for r in rows], y=[r["rate"] for r in rows], mode="lines+markers",
                                 line=dict(color=CAT[i], width=2), marker=dict(size=8, color=CAT[i]),
                                 name=f"Base {b} ({rows[0]['field_size']:.0e} numbers)".replace("e+", "e"),
                                 customdata=custom(D, rows), hovertemplate=HOVER))
    mod = [r for r in modelled_b64(D) if r["client"] in label]
    fig.add_trace(go.Scatter(x=[label[r["client"]] for r in mod], y=[r["rate"] for r in mod], mode="lines+markers",
                             line=dict(color=MODELLED, width=2, dash="dot"), marker=dict(size=9, symbol="diamond-open", color=MODELLED),
                             error_y=dict(type="data", symmetric=False, array=[r["band"][1] - r["rate"] for r in mod],
                                          arrayminus=[r["rate"] - r["band"][0] for r in mod], color=MODELLED, thickness=1),
                             name="Base 64 (1e18 numbers, modelled ±5 %)", customdata=custom(D, mod), hovertemplate=HOVER))
    frame(fig, 460, top=60)
    fig.update_xaxes(type="category", categoryorder="array", categoryarray=[label[c] for c in builds], title="build (oldest → newest)")
    rate_axis(fig, 2e11, 7e12)
    return fig


# ---- 4. rate against field size --------------------------------------------------------------------
def field_size(D):
    fig = go.Figure()
    s = D["model"]["series"]
    shas = sorted({sha for (sha, b), v in s.items() if b in (62, 64) and len(v) >= 3},
                  key=lambda sha: next(D["okey"](c["name"]) for c in D["commits"].values() if c["sha"] == sha))
    for i, sha in enumerate(shas):
        c = next(c for c in D["commits"].values() if c["sha"] == sha)
        for b, dash in ((62, "solid"), (64, "dash")):
            v = s.get((sha, b))
            if not v or len(v) < 3:
                continue
            xs = sorted(v)
            fig.add_trace(go.Scatter(x=xs, y=[v[x] for x in xs], mode="lines+markers", line=dict(color=CAT[i], width=2, dash=dash),
                                     marker=dict(size=7), name=f"{c['label']}, base {b}",
                                     customdata=[[f"{x:.0e}".replace("e+", "e"), words(v[x])] for x in xs],
                                     hovertemplate="fields of %{customdata[0]}: <b>%{customdata[1]}/s</b><extra>%{fullData.name}</extra>"))
        m = D["model"]["cost"]["b64_1e18"].get(sha)
        if m and "own" in m["how"]:
            fig.add_trace(go.Scatter(x=[1e18], y=[m["rate"]], mode="markers", marker=dict(size=11, symbol="diamond-open", color=CAT[i], line=dict(width=2)),
                                     error_y=dict(type="data", symmetric=False, array=[m["band"][1] - m["rate"]],
                                                  arrayminus=[m["rate"] - m["band"][0]], color=CAT[i], thickness=1),
                                     name=f"{c['label']}, base 64 at 1e18 (modelled)", customdata=[[words(m["rate"])]],
                                     hovertemplate="1e18, modelled: <b>%{customdata[0]}/s</b><extra>%{fullData.name}</extra>"))
    frame(fig, 480, top=60)
    fig.update_xaxes(type="log", title="field size (numbers)", tickvals=[10 ** e for e in range(13, 19)],
                     ticktext=[f"10<sup>{e}</sup>" for e in range(13, 19)])
    rate_axis(fig, 5e10, 7e12)
    return fig


# ---- 5. peak memory ------------------------------------------------------------------------------
def memory(D):
    fig = make_subplots(rows=1, cols=2, subplot_titles=("Detailed mode", "Nice-only mode"), horizontal_spacing=0.08, shared_yaxes=True)
    mem, cm = D["mem"], D["commits"]
    for col, mode in ((1, "detailed"), (2, "niceonly")):
        for i, b in enumerate((40, 50, 60)):
            pts = sorted([(c, v) for (c, m, bb, k), v in mem.items() if m == mode and bb == b and k == "capped" and v],
                         key=lambda x: D["okey"](x[0]))
            fig.add_trace(go.Scatter(x=[cm[c]["date"] for c, _ in pts], y=[v / 1024 for _, v in pts], mode="lines",
                                     line=dict(color=CAT[i], width=2, shape="hv"), name=f"base {b}", legendgroup=f"b{b}", showlegend=col == 1,
                                     customdata=[point_text(D, c) + [f"{v / 1024:.1f} MB"] for c, v in pts], hovertemplate=HOVER),
                          row=1, col=col)
    real = sorted([(c, b, v) for (c, m, b, k), v in mem.items() if k == "real" and v], key=lambda x: D["okey"](x[0]))
    for i, b in enumerate(sorted({b for _, b, _ in real})):
        pts = [(c, v) for c, bb, v in real if bb == b]
        fig.add_trace(go.Scatter(x=[cm[c]["date"] for c, _ in pts], y=[v / 1024 for _, v in pts], mode="markers",
                                 marker=dict(size=9, symbol="diamond", color=CAT[3 + i], line=dict(color=SURFACE, width=1.5)),
                                 name=f"base {b}, production field", customdata=[point_text(D, c) + [f"{v / 1024:.0f} MB"] for c, v in pts],
                                 hovertemplate=HOVER), row=1, col=2)
    releases(fig, D, labels=False, rows=[(1, 1), (1, 2)])
    frame(fig, 460, top=100)
    fig.update_xaxes(type="date")
    fig.update_yaxes(type="log", tickvals=[1, 3, 10, 30, 100, 300, 1000], ticktext=["1 MB", "3", "10", "30", "100", "300", "1 GB"])
    fig.update_yaxes(title="peak memory", col=1)
    return fig


# ---- 6. binary size and build time -----------------------------------------------------------------
def build(D):
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, subplot_titles=("Binary size", "Release build time"), vertical_spacing=0.12)
    rows = sorted([c for c in D["commits"].values() if c["binary_bytes"]], key=lambda c: (c["date"], c["order"]))
    for i, repo in enumerate(("nice-rust", "nice")):
        pts = [c for c in rows if c["repo"] == repo]
        for row, key, fmt in ((1, "binary_bytes", lambda v: f"{int(v) / 2**20:.1f} MB"), (2, "build_secs", lambda v: f"{int(v)} s")):
            fig.add_trace(go.Scatter(x=[c["date"] for c in pts], y=[int(c[key]) / (2**20 if row == 1 else 1) for c in pts],
                                     mode="markers", marker=dict(size=7, color=CAT[i], line=dict(color=SURFACE, width=1)),
                                     name=f"{repo} repository", legendgroup=repo, showlegend=row == 1,
                                     customdata=[[c["label"], c["subject_short"][:90], c["date"], fmt(c[key]) + f" · {c['toolchain'].split(' (')[0]}"] for c in pts],
                                     hovertemplate=HOVER), row=row, col=1)
    releases(fig, D, labels=False, rows=[(1, 1), (2, 1)])
    frame(fig, 560, top=90)
    fig.update_xaxes(type="date")
    fig.update_yaxes(title="MB", rangemode="tozero", row=1, col=1)
    fig.update_yaxes(title="seconds", rangemode="tozero", row=2, col=1)
    return fig


# ---- 7. rate against memory ----------------------------------------------------------------------
ERAS = [("before the MSD filter (2023 – Feb 2026)", None, "2026-02-03"), ("MSD filter (Feb – Oct 2026)", "2026-02-03", "2026-10-07"),
        ("overlap join (Oct 2026 –)", "2026-10-07", None)]


def rate_vs_memory(D):
    fig = go.Figure()
    rate = {(r["client"], r["mode"], r["base"]): r["rate"] for r in D["rates"]}
    cm = D["commits"]
    for i, (name, lo, hi) in enumerate(ERAS):
        for mode, sym in (("detailed", "circle"), ("niceonly", "diamond")):
            pts = [(c, rate[(c, mode, 60)], v) for (c, m, b, k), v in D["mem"].items()
                   if m == mode and b == 60 and k == "capped" and v and (c, mode, 60) in rate
                   and (lo is None or cm[c]["date"] >= lo) and (hi is None or cm[c]["date"] < hi)
                   and (cm[c]["repo"] == "nice" or lo is None)]
            if pts:
                fig.add_trace(go.Scatter(x=[v / 1024 for _, _, v in pts], y=[r for _, r, _ in pts], mode="markers",
                                         name=f"{'detailed' if mode == 'detailed' else 'nice-only'}, {name}",
                                         marker=dict(size=9, symbol=sym, color=CAT[i], line=dict(color=SURFACE, width=1.5)),
                                         customdata=[point_text(D, c) + [f"{words(r)}/s at {v / 1024:.1f} MB"] for c, r, v in pts],
                                         hovertemplate=HOVER))
    prod = [(r, D["mem"].get((r["client"], "niceonly", 60, "real"), 0)) for r in D["production"] if r["base"] == 60]
    prod = [(r, v) for r, v in prod if v]
    fig.add_trace(go.Scatter(x=[v / 1024 for _, v in prod], y=[r["rate"] for r, _ in prod], mode="markers",
                             name="nice-only, production fields (10¹⁶)", marker=dict(size=12, symbol="star", color=CAT[3], line=dict(color=TEXT2, width=1)),
                             customdata=[point_text(D, r["client"]) + [f"{words(r['rate'])}/s at {v / 1024:.0f} MB"] for r, v in prod],
                             hovertemplate=HOVER))
    frame(fig, 500, top=90)
    fig.update_xaxes(type="log", title="peak memory (MB)", tickvals=[3, 10, 30, 100, 300, 1000], ticktext=["3", "10", "30", "100", "300", "1000"])
    rate_axis(fig, 1e5, 1e13)
    return fig


# ---- 8. biggest changes (table rows) ---------------------------------------------------------------
def changes(D, n=14):
    """Geometric-mean change over the bases two consecutive measured builds share (at least five)."""
    out = []
    for mode in ("detailed", "niceonly"):
        by = defaultdict(dict)
        for r in D["rates"]:
            if r["mode"] == mode:
                by[r["client"]][r["base"]] = r["rate"]
        builds = sorted(by, key=D["okey"])
        for prev, cur in zip(builds, builds[1:]):
            common = set(by[prev]) & set(by[cur])
            if mode == "niceonly" and D["commits"][cur]["date"] < NICEONLY_FROM:
                continue
            if len(common) >= 5:
                g = math.exp(st.mean(math.log(by[cur][b] / by[prev][b]) for b in common))
                out.append({"client": cur, "prev": prev, "mode": mode, "change": g, "bases": len(common)})
    out.sort(key=lambda r: -abs(math.log(r["change"])))
    return out[:n]


# ---- 9. rate by base for a few releases ------------------------------------------------------------
PROFILE_TAGS = ["v1.1.4", "v2.3.0", "v3.2.0", "v3.2.12", "v3.4.5", "v3.4.8"]


def profiles(D):
    fig = make_subplots(rows=1, cols=2, subplot_titles=("Detailed mode", "Nice-only mode (fields of up to 10¹³)"), horizontal_spacing=0.07)
    tagc = {c["tag"]: c["name"] for c in D["commits"].values() if c["tag"]}
    tags = [t for t in PROFILE_TAGS if t in tagc]
    for i, t in enumerate(tags):
        c = tagc[t]
        for col, mode in ((1, "detailed"), (2, "niceonly")):
            rows = sorted([r for r in D["rates"] if r["client"] == c and r["mode"] == mode], key=lambda r: r["base"])
            if not rows:
                continue
            color = SEQ[round(i * (len(SEQ) - 1) / max(1, len(tags) - 1))]
            fig.add_trace(go.Scatter(x=[r["base"] for r in rows], y=[r["rate"] for r in rows], mode="lines+markers",
                                     line=dict(color=color, width=2), marker=dict(size=5), name=f"{t} ({D['commits'][c]['date'][:7]})",
                                     legendgroup=t, showlegend=col == 1,
                                     customdata=[[f"base {r['base']}", words(r["rate"])] for r in rows],
                                     hovertemplate="%{customdata[0]}: <b>%{customdata[1]}/s</b><extra>%{fullData.name}</extra>"),
                          row=1, col=col)
    frame(fig, 480, top=100)
    fig.update_yaxes(type="log", tickvals=[10 ** e for e in range(4, 14)], ticktext=[short(10 ** e) for e in range(4, 14)])
    fig.update_yaxes(title="numbers checked per second", col=1)
    fig.update_xaxes(title="base")
    return fig


# ---- 10. change heatmaps ---------------------------------------------------------------------------
def heatmap(D, mode):
    rows = [r for r in D["rates"] if r["mode"] == mode]
    builds = sorted({r["client"] for r in rows}, key=D["okey"])
    bases = sorted({r["base"] for r in rows})
    val = {(r["client"], r["base"]): r["rate"] for r in rows}
    labels = [f"{D['commits'][c]['date']} {D['commits'][c]['label']}" for c in builds]
    z, text = [], []
    for b in bases:
        zr, tr, prev = [], [], None
        for c in builds:
            v = val.get((c, b))
            if v and prev:
                zr.append(math.log2(v / prev)); tr.append(f"×{v / prev:.2f}")
            else:
                zr.append(None); tr.append("")
            prev = v or prev
        z.append(zr); text.append(tr)
    fig = go.Figure(go.Heatmap(z=z, x=labels, y=[f"b{b}" for b in bases], text=text, zmid=0, zmin=-2, zmax=2,
                               colorscale=[[0, CAT[0]], [0.5, DIV_MID], [1, CAT[7]]], xgap=1, ygap=1,
                               colorbar=dict(title=dict(text="vs previous", side="top"), tickvals=[-2, -1, 0, 1, 2],
                                             ticktext=["÷4 slower", "÷2", "same", "×2", "×4 faster"], len=0.9),
                               hovertemplate="%{x}<br>%{y}: %{text}<extra></extra>"))
    frame(fig, 560, legend=False, top=20)
    fig.update_xaxes(type="category", tickangle=-60, tickfont=dict(size=9), tickvals=labels[::max(1, len(labels) // 36)], showline=False)
    fig.update_yaxes(type="category", tickfont=dict(size=10), title="base")
    fig.update_layout(margin=dict(b=130))
    return fig


# ---- 11. cost model --------------------------------------------------------------------------------
COST_BUILDS = ["9f8c211", "9a4f740", "215eb4b", "8c088a2", "8bd154b", "e07f11f", "a7a59c1", "8c267de"]


def cost_model(D):
    fig = make_subplots(rows=1, cols=3, horizontal_spacing=0.07,
                        subplot_titles=("Base 60, fields of 10¹³", "Base 60, fields of 10¹⁶ (production)", "Base 62, fields of 10¹⁷ (production)"))
    for i, sha in enumerate(COST_BUILDS):
        c = next((c for c in D["commits"].values() if c["sha"] == sha), None)
        if not c:
            continue
        for col, (b, kind) in enumerate(((60, "capped"), (60, "real"), (62, "real")), start=1):
            pts = sorted([(r["pred"], r["secs"]) for r in D["fields"] if r["client"] == c["name"] and r["base"] == b and r["mode"] == "niceonly"
                          and r.get("jobkind") == kind and r.get("pred", 0) > 0 and r.get("rep", 0) == 0])
            if pts:
                fig.add_trace(go.Scatter(x=[p for p, _ in pts], y=[t for _, t in pts], mode="lines+markers", name=c["label"], legendgroup=sha,
                                         showlegend=col == 1, line=dict(color=CAT[i], width=2), marker=dict(size=6),
                                         hovertemplate="%{x:,} prefixes: %{y:,.0f} s<extra>" + c["label"] + "</extra>"), row=1, col=col)
    frame(fig, 460, top=100)
    fig.update_xaxes(type="log", title="prefixes in the field")
    fig.update_yaxes(type="log")
    fig.update_yaxes(title="seconds per field, one core", col=1)
    return fig


# ---- 12. production chunks for the pre-join builds -------------------------------------------------
def chunks(D):
    sh, date = defaultdict(list), {}
    for r in D["recs"]:
        if r.get("kind") == "shim" and r.get("mode_shim") == "sample":
            sh[(r["client"], r["base"])] += r["secs"]
            date[r["client"]] = r["date"]
    cap = {(r["client"], r["base"]): r["rate"] for r in D["rates"] if r["mode"] == "niceonly"}
    fig = go.Figure()
    for i, b in enumerate((57, 60, 64)):
        names = sorted({c for c, bb in sh if bb == b}, key=lambda c: (date[c], D["commits"].get(c, {}).get("order", 0)))
        fig.add_trace(go.Scatter(x=[date[c] for c in names], y=[1e9 / st.mean(sh[(c, b)]) for c in names], mode="lines",
                                 line=dict(color=CAT[i], width=2, shape="hv"), name=f"base {b}, production chunks",
                                 customdata=[[c[-7:], "", date[c], f"{words(1e9 / st.mean(sh[(c, b)]))}/s ({len(sh[(c, b)])} chunks)"] for c in names],
                                 hovertemplate=HOVER))
        cn = [c for c in names if (c, b) in cap]
        fig.add_trace(go.Scatter(x=[date[c] for c in cn], y=[cap[(c, b)] for c in cn], mode="markers",
                                 marker=dict(size=7, symbol="circle-open", color=CAT[i], line=dict(width=1.5)), name=f"base {b}, whole 10¹³ fields",
                                 customdata=[[c[-7:], "", date[c], f"{words(cap[(c, b)])}/s"] for c in cn], hovertemplate=HOVER))
    frame(fig, 440, top=60)
    fig.update_xaxes(type="date")
    rate_axis(fig, 1e9, 2e11)
    return fig


# ---- 13. validation --------------------------------------------------------------------------------
def validation(D):
    code = {"wrong": 3, "failed": 2, "ok": 1, "unchecked": 0}
    status = {}
    for v in D["validation"]:
        if v["client"] not in D["commits"]:
            continue
        k = (v["client"], v["base"], v["mode"])
        if k not in status or code[v["status"]] > code[status[k]]:
            status[k] = v["status"]
    builds = sorted({c for c, _, _ in status}, key=D["okey"])
    bases = sorted({b for _, b, _ in status})
    labels = [f"{D['commits'][c]['date']} {D['commits'][c]['label']}" for c in builds]
    fig = make_subplots(rows=2, cols=1, subplot_titles=("Detailed mode", "Nice-only mode"), vertical_spacing=0.14)
    scale = [[0, MUTED], [0.33, MUTED], [0.34, GOOD], [0.66, GOOD], [0.67, WARN], [0.9, WARN], [0.91, CRIT], [1, CRIT]]
    words_ = {"ok": "matches the reference", "unchecked": "too large to recompute; no nice number reported",
              "failed": "client failed (base unsupported)", "wrong": "wrong result (base unsupported)"}
    for row, m in ((1, "detailed"), (2, "niceonly")):
        z = [[code[status[(c, b, m)]] if (c, b, m) in status else None for c in builds] for b in bases]
        t = [[words_[status[(c, b, m)]] if (c, b, m) in status else "" for c in builds] for b in bases]
        fig.add_trace(go.Heatmap(z=z, x=labels, y=[f"b{b}" for b in bases], text=t, zmin=0, zmax=3, colorscale=scale, showscale=False,
                                 xgap=1, ygap=1, hovertemplate="%{x}<br>%{y}: %{text}<extra></extra>"), row=row, col=1)
    for k in ("ok", "unchecked", "failed", "wrong"):
        fig.add_trace(go.Scatter(x=[None], y=[None], mode="markers", marker=dict(size=12, symbol="square",
                                 color={"ok": GOOD, "unchecked": MUTED, "failed": WARN, "wrong": CRIT}[k]), name=words_[k]))
    frame(fig, 780, top=90)
    fig.update_xaxes(type="category", tickangle=-60, tickfont=dict(size=9), tickvals=labels[::max(1, len(labels) // 36)], showline=False)
    fig.update_yaxes(type="category", tickfont=dict(size=8))
    fig.update_layout(margin=dict(b=130))
    return fig


# ---- 14. measurement quality -----------------------------------------------------------------------
def quality(D):
    fig = make_subplots(rows=1, cols=3, horizontal_spacing=0.08, subplot_titles=(
        "Reference job time, every hour per core", "CPU time ÷ wall time per field", "Spread between repeat runs"))
    # canaries before 2026-10-31 01:00 UTC ran in repeat mode (warm-up overlapped): not comparable
    can = [r for r in D["recs"] if r.get("kind") == "canary" and r.get("secs") and r.get("ts", 0) > 1793409600]
    runs = sorted({r["_run"] for r in can})
    for i, run in enumerate(runs):
        pts = [r for r in can if r["_run"] == run]
        fig.add_trace(go.Scatter(x=[dt.datetime.fromtimestamp(r["ts"], dt.UTC).strftime("%Y-%m-%d %H:%M") for r in pts],
                                 y=[r["secs"] for r in pts], mode="markers", marker=dict(size=5, color=CAT[i]), name=run,
                                 hovertemplate="%{x}: %{y:.2f} s<extra>" + run + "</extra>"), row=1, col=1)
    ratios = [min((r["ru"]["utime"] + r["ru"]["stime"]) / r["secs"], 1.5) for r in D["fields"]
              if r.get("how") == "oneshot" and r["secs"] >= 5 and r.get("ru")]
    fig.add_trace(go.Histogram(x=ratios, nbinsx=60, marker=dict(color=CAT[0]), name="fields", showlegend=False), row=1, col=2)
    spread = {"detailed": [], "niceonly": []}
    for r in D["rates"]:
        if r["spread"] is not None:
            spread[r["mode"]].append(100 * r["spread"])
    for i, m in enumerate(("detailed", "niceonly")):
        fig.add_trace(go.Box(y=spread[m], name="detailed" if m == "detailed" else "nice-only", marker=dict(color=CAT[i]),
                             boxpoints=False, showlegend=False), row=1, col=3)
    frame(fig, 420, top=90)
    fig.update_yaxes(title="seconds", row=1, col=1)
    fig.update_xaxes(title="ratio", row=1, col=2)
    fig.update_yaxes(title="fields", row=1, col=2)
    fig.update_yaxes(title="% (max ÷ min − 1)", row=1, col=3)
    return fig


def build_all(D):
    return {"hero": hero(D), "bases": bases(D), "production": production(D), "fieldsize": field_size(D), "memory": memory(D),
            "build": build(D), "ratemem": rate_vs_memory(D), "profiles": profiles(D), "heat_detailed": heatmap(D, "detailed"),
            "heat_niceonly": heatmap(D, "niceonly"), "cost": cost_model(D), "chunks": chunks(D), "validation": validation(D),
            "quality": quality(D)}
