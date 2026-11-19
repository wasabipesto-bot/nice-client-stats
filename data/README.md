# Data formats

## commits.csv

One row per measured build. `order` breaks ties between builds on the same date (position on the repository's
first-parent history). `why` is how the build was picked: `day` (last client change of its day), `pr` (a CPU
performance change since February 2026), `tag:<release>`, or `anchor`. `toolchain` is the Rust release it was built
with (the stable of its commit date). `binary_bytes`, `build_secs` and `sha256` describe the release binary.

## runs/*.jsonl.gz

One JSON object per line, written by `harness/worker.py` as results arrive. Records whose job was later
invalidated and measured again are listed in `<run>.invalidated.json` (`before_ts` per job id); readers drop them.

| `kind` | meaning |
|---|---|
| `field` | one timed field (or stratum of one) |
| `calibration` | the window size chosen for a detailed (uniform-rate) measurement |
| `canary` | the hourly reference job (detailed mode, base 50, 5×10⁷ numbers) on a worker's core |
| `shim` | run 2 only: production-size chunks timed with a build's own chunk function |
| `contaminated`, `error` | a measurement thrown away (core shared, client failure) and retried |

Field records carry: `client` (`<repo>-<date>-<sha>`), `repo`, `sha`, `date`, `toolchain`, `mode` (`detailed` or
`niceonly`), `base`, `jobkind` (`capped`: fields of up to 10¹³; `real`: production-size fields; `ladder`: one build at
several field sizes), `rep`, `stratum`, `K` (strata in the set), `w` (stratum weight), `pred` (predicted cost, the
join's prefix count where it applies), `start`, `size`, `field_size`, `secs` (claim to submit, timed by the mock
server), `rate`, `how`, `ru` (`hwm_kb` peak memory, `utime`, `stime`, `rc`), `worker`, `core`, `ts`.

A rate for a set of strata is `sum(w) / sum(w_k · secs_k / size_k)`.

## validation.csv

`run, client, mode, base, status`, where status is the worst over that group's submissions: `ok` (matches a
reference run of the current client), `unchecked` (too large to recompute; checked for reporting no nice number),
`failed` (client failed), `wrong` (result differs; the base is excluded for that build).

## b64_1e17_prediction.json

The base-64 10¹⁷ prediction recorded before those fields were measured (the model's out-of-sample check).
