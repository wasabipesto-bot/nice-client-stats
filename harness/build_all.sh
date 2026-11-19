#!/usr/bin/env bash
# Build everything in commits.tsv: priority pass (tags + the join era), then the rest.
# Within a pass, date order, so each toolchain is installed once and removed after.
cd "$(dirname "$0")"
here=$(pwd)
keep="stable 1.99.1"
pass() {
  local last=""
  while IFS=$'\t' read -r repo sha date why subj; do
    [ "$repo" = nice-client-py ] && continue
    tc=$(python3 -c "import datetime as d;print('1.%d.0'%((d.date.fromisoformat('$date')-d.date(2015,5,14)).days//42))")
    if [ -n "$last" ] && [ "$tc" != "$last" ]; then rustup toolchain uninstall "$last" >/dev/null 2>&1; fi
    last=$tc
    nice -n 10 ./build.sh "$repo" "$sha" || true
  done
  [ -n "$last" ] && rustup toolchain uninstall "$last" >/dev/null 2>&1
}
tail -n +2 commits.tsv | awk -F'\t' '$4 ~ /tag:/ || $3 >= "2026-10-07"' | pass
tail -n +2 commits.tsv | awk -F'\t' '!($4 ~ /tag:/ || $3 >= "2026-10-07")' | pass
echo ALL-BUILDS-DONE
