#!/usr/bin/env bash
# Build one historical client commit with the Rust stable that was current on its
# commit date, and keep only the binary.
#   build.sh <repo> <sha>
# repo: nice-rust | nice   (nice-client-py needs no build: see setup_py.sh)
set -euo pipefail
repo=$1; sha=$2
here=$(cd "$(dirname "$0")" && pwd)
case $repo in
  # clones of github.com/wasabipesto/nice-rust and github.com/wasabipesto/nice
  nice-rust) src=${PERFHIST_NICE_RUST:-$HOME/src/nice-rust} ;;
  nice)      src=${PERFHIST_NICE:-$HOME/src/nice} ;;
  *) echo "unknown repo $repo" >&2; exit 2 ;;
esac
full=$(git -C "$src" rev-parse "$sha^{commit}")
short=${full:0:7}
date=$(git -C "$src" log -1 --format=%cs "$full")
out=$here/bins/$repo-$date-$short
[ -x "$out/client" ] && { echo "already built: $out"; exit 0; }

# Stable as of the commit date: 1.N ships every 42 days from 1.0 (2015-05-15).
tc=$(python3 -c "import datetime as d;print('1.%d.0'%((d.date.fromisoformat('$date')-d.date(2015,5,14)).days//42))")
rustup toolchain list | grep -q "^$tc-" || rustup toolchain install "$tc" --profile minimal >/dev/null 2>&1
tc_full=$(rustup run "$tc" rustc --version)

work=${PERFHIST_BUILD_DIR:-$HOME/perfhist-build}/$short
rm -rf "$work"; mkdir -p "$work"
git -C "$src" archive "$full" | tar -x -C "$work"
cd "$work"

# Era patches: the Jan-2023 nice-rust clients hard-code the API URL.
patched=none
if grep -rqs 'https://nice.wasabipesto.com' src; then
  sed -i 's#https://nice.wasabipesto.com#http://127.0.0.1:8650#g' src/*.rs
  patched=api-url
fi

minor=${tc#1.}; minor=${minor%.0}
export CARGO_TARGET_DIR=$work/target
if [ "$minor" -lt 68 ]; then
  # No sparse registry before 1.68: vendor with today's cargo, build offline.
  cargo +stable vendor --locked --versioned-dirs vendor > vendor.toml 2>/dev/null
  mkdir -p .cargo; cat vendor.toml >> .cargo/config.toml
  offline=--offline
else
  export CARGO_REGISTRIES_CRATES_IO_PROTOCOL=sparse
  offline=
fi

pkg=; bin=nice-rust
if [ "$repo" = nice ]; then pkg="-p nice_client"; bin=nice_client; fi
locked=--locked
start=$(date +%s)
if ! rustup run "$tc" cargo build --release $offline $locked $pkg > build.log 2>&1; then
  locked=  # stale lockfile at this commit: resolve, but record it
  rustup run "$tc" cargo build --release $offline $pkg > build.log 2>&1 \
    || { mkdir -p "$here/logs"; cp build.log "$here/logs/build-$repo-$short.log"; echo "BUILD FAILED $repo $short ($tc)"; exit 1; }
fi
secs=$(( $(date +%s) - start ))

mkdir -p "$out"
cp "$CARGO_TARGET_DIR/release/$bin" "$out/client"
cp Cargo.lock "$out/Cargo.lock" 2>/dev/null || true
cat > "$out/build.json" <<EOF
{"repo":"$repo","sha":"$full","date":"$date","toolchain":"$tc_full","locked":$([ -n "$locked" ] && echo true || echo false),
 "patch":"$patched","build_secs":$secs,"sha256":"$(sha256sum "$out/client" | cut -d' ' -f1)","features":"default"}
EOF
cd /; rm -rf "$work"
echo "built $out ($tc_full, ${secs}s)"
