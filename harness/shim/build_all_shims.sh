#!/usr/bin/env bash
# Shims for every commit with the clamped chunking and no join (2026-07-24 .. 2026-10-06), date order.
cd "$(dirname "$0")/.."
last=""
awk -F'\t' 'NR>1 && $1=="nice" && $3>="2026-07-24" && $3<"2026-10-07" {print $2, $3}' commits.tsv | while read sha date; do
  tc=$(python3 -c "import datetime as d;print('1.%d.0'%((d.date.fromisoformat('$date')-d.date(2015,5,14)).days//42))")
  [ -n "$last" ] && [ "$tc" != "$last" ] && rustup toolchain uninstall "$last" >/dev/null 2>&1
  last=$tc
  nice -n 10 shim/build_shim.sh "$sha" || true
done
[ -n "$last" ] && rustup toolchain uninstall "$last" >/dev/null 2>&1
echo ALL-SHIMS-DONE
