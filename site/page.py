"""The dashboard page (imported by build.py): text, layout, theme handling."""
import datetime as dt
import html
import json
import math
import statistics as st

from charts import (FONT, GRID, MUTED, SURFACE, TEXT, TEXT2, THEME, changes, modelled_b64, niceonly_line, words)

PLOTLY = "https://cdnjs.cloudflare.com/ajax/libs/plotly.js/4.1.1/plotly.min.js"
REPO = "https://github.com/wasabipesto-bot/nice-client-stats"

SECTIONS = [  # (id, title, description); "intro" sections get their prose from the render function
    ("hero", "Search speed at base 64",
     "Numbers checked per second by each client build on one CPU core, at base 64, the base being searched now. "
     "The blue line is measured on fields of up to 10¹³ numbers; the orange line is the same builds on base 64's planned "
     "production fields of 10¹⁸, which are too long to time directly and come from a model checked against measurements."),
    ("bases", "Other bases",
     "The same measurement at four smaller bases, in both client modes. Detailed mode checks every number fully, to "
     "collect statistics; nice-only mode skips the numbers that provably cannot be nice. Diamonds are production-size fields."),
    ("production", "Production-size fields",
     "Since October 2026 the client searches large fields with an overlap join, which gets faster per number as the field "
     "grows. This chart times whole production fields, one per base, for the builds measured that way."),
    ("fieldsize", "Speed against field size",
     "Why small fields understate the join: its rate climbs until fields of about 10¹⁵–10¹⁶ numbers and then levels off. "
     "Diamonds are the base-64 model at 10¹⁸."),
    ("memory", "Peak memory",
     "The most memory the client process used while checking one field. The overlap join trades memory for speed."),
    ("build", "Binary size and build time",
     "Size of each build's release binary and the time to compile it, on the same machine with the Rust release of the "
     "commit's date."),
    ("ratemem", "Speed against memory",
     "Each point is one build at base 60. Colour is the era of the search algorithm, shape the mode."),
    ("changes", "Biggest single changes",
     "The largest steps between consecutive measured builds, averaged over the bases both were measured at. A step can "
     "contain several commits; the last link lists them all."),
    ("profiles", "Speed by base",
     "A few releases across every base. Higher bases have more digits per number, so each check costs more."),
    ("heat_detailed", "Change by build and base: detailed mode",
     "Each cell compares a build with the previous measured build at one base. Red is faster, blue slower."),
    ("heat_niceonly", "Change by build and base: nice-only mode", ""),
    ("cost", "Join cost per field",
     "Seconds per production field against the number of prefixes in it, the work unit of the overlap join. The near-straight "
     "lines are what makes the base-64 model possible."),
    ("chunks", "Production chunk sizes before the join",
     "Clients from July to October 2026 split production fields into larger chunks than the 10¹³ fields here use. Timing "
     "their own chunks shows the difference is small."),
    ("validation", "Validation",
     "Every result compared with a reference run of the current client."),
    ("quality", "Measurement quality",
     "A fixed reference job runs every hour on each core; its time should not drift. Below 1.0 in the middle panel means "
     "the core was shared."),
]


def tiles(D):
    line = niceonly_line(D, 64)
    mod = modelled_b64(D)
    last = mod[-1]
    c_last = D["commits"][last["client"]]
    first = line[0]
    prev = [m for m in mod if D["commits"][m["client"]]["tag"] and m is not last]
    gain = f"×{last['rate'] / prev[-1]['rate']:.2f} over {D['commits'][prev[-1]['client']]['tag']}" if prev else ""
    newest = max(r.get("ts", 0) for r in D["recs"])
    return [
        (f"{last['rate'] / first['rate'] / 1e6:.0f} million×", f"faster at base 64 than the January 2023 client"),
        (f"{words(last['rate'])}/s", f"numbers checked per second at base 64 by {c_last['label']} on one core ({gain})"),
        (f"{len(D['commits'])}", "client builds measured, January 2023 to " + dt.date.fromtimestamp(newest).strftime("%B %Y")),
        (f"{sum(1 for r in D['fields']):,}", "timed fields across " + str(len(D["runs"])) + " measurement runs"),
    ]


def changes_table(D):
    rows = []
    for r in changes(D):
        c = D["commits"][r["client"]]
        p = D["commits"][r["prev"]]
        what = html.escape(c["subject_short"])
        if c["pr"]:
            what += f' (<a href="https://github.com/wasabipesto/{c["repo"]}/pull/{c["pr"]}">#{c["pr"]}</a>)'
        if p["repo"] == c["repo"]:
            since = f'<a href="{c["url"].rsplit("/commit/", 1)[0]}/compare/{p["sha"]}...{c["sha"]}">changes since {html.escape(p["label"])}</a>'
        else:
            since = f"first {c['repo']} build"
        cls = "up" if r["change"] > 1 else "down"
        ch = f"×{r['change']:.2f}" if r["change"] >= 1 else f"÷{1 / r['change']:.2f}"
        rows.append(f'<tr><td>{c["date"]}</td><td class="{cls}">{ch}</td><td>{"detailed" if r["mode"] == "detailed" else "nice-only"}</td>'
                    f'<td><a href="{c["url"]}">{html.escape(c["label"])}</a></td><td>{what}</td><td class="dim">{since}</td></tr>')
    return ('<table class="changes"><thead><tr><th>date</th><th>change</th><th>mode</th><th>build</th>'
            '<th>its last commit</th><th>everything in the step</th></tr></thead><tbody>' + "".join(rows) + "</tbody></table>")


def methodology(D):
    cost = D["model"]["cost"]
    chk = cost.get("check_b64_1e17", {})
    vals = [v["status"] for v in D["validation"]]
    can = [r["secs"] for r in D["recs"] if r.get("kind") == "canary" and r.get("secs") and r.get("ts", 0) > 1793409600]
    # toolchain A/B: one commit built with two Rust releases (run 3)
    ab = {}
    for r in D["fields"]:
        if r["client"].startswith("nice-2026-11-09-c0c357a") and r["mode"] == "detailed" and r["base"] in (50, 60):
            ab.setdefault((r["client"].endswith("-tc100"), r["base"]), []).append(r["size"] / r["secs"])
    ab_txt = ""
    if all((t, b) in ab for t in (False, True) for b in (50, 60)):
        ab_txt = (" One commit built with both Rust 1.99.0 and 1.100.0 shows 1.100.0 makes detailed mode "
                  f"{100 * (1 - st.median(ab[(True, 50)]) / st.median(ab[(False, 50)])):.1f} % slower at base 50 and "
                  f"{100 * (1 - st.median(ab[(True, 60)]) / st.median(ab[(False, 60)])):.1f} % at base 60, which is the small "
                  "step in November 2026.")
    v348 = cost["b64_1e18"].get("8c267de")
    return f"""
<h3>What is measured</h3>
<p>A number is <em>nice</em> in a base when its square and cube together use every digit of that base exactly once
(<a href="https://nicenumbers.net">nicenumbers.net</a>). The search splits each base into fields and hands them to clients.
Each point on this page is one client build checking fields on <strong>one CPU core</strong>; its rate is numbers checked per
second, timed by a stand-in for the search server from the moment the client claims a field to the moment it submits the result.
Detailed mode records how many distinct digits every number has; nice-only mode only looks for nice numbers and skips whatever its
filters rule out, so it is much faster.</p>
<h3>Which builds</h3>
<p>{len(D['commits'])} builds from three repositories: the original Python client
(<a href="https://github.com/wasabipesto/nice-client-py">nice-client-py</a>), the first Rust client
(<a href="https://github.com/wasabipesto/nice-rust">nice-rust</a>) and the current one
(<a href="https://github.com/wasabipesto/nice">nice</a>). The last client change of each day is measured, plus every release, and
since February 2026 every change to the CPU search code. Each build is compiled from its commit with the Rust release that was current
on the commit's date, with default features (CPU only).{ab_txt}</p>
<h3>Hardware and noise</h3>
<p>One core of an AMD EPYC Genoa (Zen 4) virtual server, one job per pinned core, at low priority next to other services. A fixed
reference job runs every hour on each core: {len(can)} runs took {min(can):.2f}–{max(can):.2f} s. Most builds were measured three times
at bases 40, 50 and 60; the median is shown. AVX-512 is available, so the SIMD paths of the recent clients run in that form; other CPUs
will differ.</p>
<h3>Fields</h3>
<p>Detailed mode checks every number at the same cost, so it is timed on a window of about eight seconds. Nice-only mode skips
whole regions, so its speed depends on where it looks: it is timed on whole fields of the production size, capped at 10¹³ numbers,
placed at a few strata of predicted cost (including an empty one) and weighted by how common each stratum is. Production fields at
bases 57–62 are 10¹⁴–10¹⁷ numbers; those were timed whole for selected builds of the overlap-join era.</p>
<h3>The base-64 model</h3>
<p>Base 64's production fields are planned at 10¹⁸ numbers, about {cost['b64_1e18']['8bd154b']['core_days']:.0f} core-days each for v3.4.7.
The join's time per field is its prefix count times a cost per prefix, and that cost drifts up by about
{100 * (cost['drift_per_decade']['b62'] - 1):.0f}–{100 * (cost['drift_per_decade']['b64'] - 1):.0f} % per tenfold field size once fixed costs are
amortised. The model carries measured per-prefix costs to 10¹⁸ with that drift. Checked before the result was known: v3.4.7 at base 64
on 10¹⁷ fields was predicted at {words(chk.get('predicted_rate', 0))}/s and measured at {words(chk.get('measured_rate', 0))}/s.
{'Builds with their own base-64 measurements up to 10¹⁶ (v3.4.6, v3.4.8) use them, with the drift scaled by their own base-62 drift; ' if v348 else ''}
other join builds are scaled from their base-62 10¹⁷ rate. Simple curve fits do not extrapolate the join (the rate peaks and turns
down), which is why this model is used. The band is ±5 %.</p>
<h3>Validation</h3>
<p>Every result was compared with a reference run of the current client: {vals.count('ok'):,} (build, mode, base) results match,
{vals.count('unchecked'):,} were too large to recompute and were checked for reporting no nice number, and {vals.count('wrong')} were
wrong. All the wrong ones are the first two Rust builds above about base 45, where their 128-bit arithmetic overflows; those bases are
left out for them.</p>
<h3>Caveats</h3>
<ul>
<li>From February to August 2026 a nice-only filter skipped some ranges it should have checked (shaded). Nice-only rates there are
inflated; the fix in August shows as a drop.</li>
<li>The finite-difference detailed path (v3.4.7) covers bases 40–62 and 64 but not 63, so detailed mode at base 63 is still about ten
times slower.</li>
<li>Nice-only mode above base 64 has no join and takes many hours per field on recent builds; it is measured only for older builds.</li>
<li>Peak memory is the process's high-water mark, polled while it ran. Build times are for one build at a time on a 4-core machine.</li>
<li>Production chunks: clients from 24 July to 6 October 2026 split production fields into 10⁹-number chunks instead of the 10⁸ used on
10¹³ fields; timing 2,000 production chunks per base for each of them gave rates 0–9 % above the 10¹³ ones.</li>
</ul>
<h3>Data and code</h3>
<p>Raw measurement records, the build list and the validation verdicts are in <a href="{REPO}/tree/main/data">data/</a>; the
measurement harness is in <a href="{REPO}/tree/main/harness">harness/</a>. This page is rebuilt from them on every change.
Downloads: <a href="data/rates.csv">rates.csv</a> (every rate on this page), <a href="data/commits.csv">commits.csv</a>.</p>"""


def render(D, figs):
    theme = json.dumps({k.lower(): v for k, v in THEME.items()})
    blocks = []
    for sid, title, desc in SECTIONS:
        if sid == "changes":
            body = changes_table(D)
        else:
            spec = figs[sid].to_json().replace("</", "<\\/")
            body = f'<div class="fig" id="f-{sid}"></div><script type="application/json" class="spec" data-for="f-{sid}">{spec}</script>'
        head = f"<h2>{html.escape(title)}</h2>" if title else ""
        p = f'<p class="desc">{desc}</p>' if desc else ""
        blocks.append(f'<section id="{sid}">{head}{p}{body}</section>')
    tile_html = "".join(f'<div class="tile"><div class="big">{a}</div><div>{b}</div></div>' for a, b in tiles(D))
    built = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d %H:%M UTC")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Nice client stats</title>
<meta name="description" content="How fast the nice-number search client has become, build by build, since January 2023.">
<script src="{PLOTLY}"></script>
<style>
:root {{ --surface:{SURFACE}; --text:{TEXT}; --text2:{TEXT2}; --grid:{GRID}; --muted:{MUTED}; --up:#0a7d0a; --down:#c23b3b; }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{ --surface:{THEME[SURFACE]}; --text:{THEME[TEXT]};
  --text2:{THEME[TEXT2]}; --grid:{THEME[GRID]}; --muted:{THEME[MUTED]}; --up:#3fbf3f; --down:#e66767; }} }}
:root[data-theme="dark"] {{ --surface:{THEME[SURFACE]}; --text:{THEME[TEXT]}; --text2:{THEME[TEXT2]}; --grid:{THEME[GRID]};
  --muted:{THEME[MUTED]}; --up:#3fbf3f; --down:#e66767; }}
body {{ margin:0; background:var(--surface); color:var(--text); font-family:{FONT}; line-height:1.5; }}
main {{ max-width:1180px; margin:0 auto; padding:24px 16px 64px; }}
header {{ display:flex; justify-content:space-between; align-items:baseline; gap:16px; flex-wrap:wrap; }}
h1 {{ font-size:1.9rem; margin:0 0 4px; }} h2 {{ font-size:1.3rem; margin:48px 0 4px; }} h3 {{ font-size:1.05rem; margin:24px 0 4px; }}
a {{ color:inherit; text-decoration-color:var(--text2); }}
.lede {{ color:var(--text2); max-width:62em; margin:8px 0 0; }}
.desc {{ color:var(--text2); max-width:62em; margin:0 0 8px; }}
.tiles {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(220px, 1fr)); gap:12px; margin:24px 0 8px; }}
.tile {{ border:1px solid var(--grid); border-radius:8px; padding:12px 14px; color:var(--text2); font-size:.92rem; }}
.tile .big {{ color:var(--text); font-size:1.6rem; font-weight:650; }}
.fig {{ width:100%; min-height:200px; }}
button {{ font:inherit; color:var(--text); background:transparent; border:1px solid var(--grid); border-radius:6px; padding:4px 10px; cursor:pointer; }}
table.changes {{ border-collapse:collapse; width:100%; font-size:.92rem; }}
.changes th, .changes td {{ text-align:left; padding:6px 10px 6px 0; border-bottom:1px solid var(--grid); vertical-align:top; }}
.changes th {{ color:var(--text2); font-weight:500; }} .changes .up {{ color:var(--up); font-weight:600; }}
.changes .down {{ color:var(--down); font-weight:600; }} .dim {{ color:var(--text2); }}
.table-wrap {{ overflow-x:auto; }}
#methodology {{ max-width:62em; }} #methodology p, #methodology li {{ color:var(--text2); }}
footer {{ margin-top:48px; color:var(--text2); font-size:.9rem; border-top:1px solid var(--grid); padding-top:12px; }}
</style></head>
<body><main>
<header><div><h1>Nice client stats</h1></div><button id="theme" type="button">Toggle dark mode</button></header>
<p class="lede">How fast the <a href="https://nicenumbers.net">nice-number</a> search client has become since January 2023. Every client
build is compiled from its source and timed on the same CPU core, so the lines show the software getting faster, not the hardware.
Hover over a line for the build and what changed; the <a href="#methodology">methodology</a> at the bottom explains the details.</p>
<div class="tiles">{tile_html}</div>
{"".join(blocks).replace('<section id="changes">', '<section id="changes" class="table-wrap">')}
<section id="methodology"><h2>Methodology</h2>{methodology(D)}</section>
<footer>Built {built} from <a href="{REPO}">{REPO.removeprefix("https://")}</a>. Charts: Plotly.</footer>
</main>
<script>
const MAP = {theme};
const swap = s => s.replace(/#[0-9a-fA-F]{{6}}/g, m => MAP[m.toLowerCase()] || m);
function dark() {{
  const t = document.documentElement.dataset.theme;
  return t ? t === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
}}
function draw() {{
  const d = dark();
  document.querySelectorAll("script.spec").forEach(s => {{
    const fig = JSON.parse(d ? swap(s.textContent) : s.textContent);
    fig.layout.autosize = true; delete fig.layout.width;
    Plotly.react(s.dataset.for, fig.data, fig.layout, {{displaylogo: false, responsive: true}});
  }});
}}
try {{ const t = localStorage.getItem("theme"); if (t) document.documentElement.dataset.theme = t; }} catch (e) {{}}
document.getElementById("theme").addEventListener("click", () => {{
  const t = dark() ? "light" : "dark";
  document.documentElement.dataset.theme = t;
  try {{ localStorage.setItem("theme", t); }} catch (e) {{}}
  draw();
}});
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", draw);
draw();
</script></body></html>"""
