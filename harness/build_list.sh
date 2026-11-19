#!/usr/bin/env bash
# Build every commit in a commits TSV (repo, sha, date, why, subject), one at a time at nice 10,
# each with the Rust stable of its commit date (build.sh). Toolchains it installs stay installed.
#   ./build_list.sh new-commits.tsv
cd "$(dirname "$0")"
while IFS=$'\t' read -r repo sha date why subj; do
  [ "$repo" = repo ] && continue
  nice -n 10 ./build.sh "$repo" "$sha" || true
done < "${1:?commits tsv}"
