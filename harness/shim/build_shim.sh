#!/usr/bin/env bash
# Build perfhist_shim inside one monorepo commit's client crate, with that commit's toolchain and lockfile.
#   build_shim.sh <sha>   -> shims/<nice-date-sha>/{shim,k}
set -euo pipefail
sha=$1; here=$(cd "$(dirname "$0")/.." && pwd); src=$HOME/projects/nice
full=$(git -C "$src" rev-parse "$sha^{commit}"); short=${full:0:7}; date=$(git -C "$src" log -1 --format=%cs "$full")
out=$here/shims/nice-$date-$short
[ -x "$out/shim" ] && { echo "already built: $out"; exit 0; }
tc=$(python3 -c "import datetime as d;print('1.%d.0'%((d.date.fromisoformat('$date')-d.date(2015,5,14)).days//42))")
rustup toolchain list | grep -q "^$tc-" || rustup toolchain install "$tc" --profile minimal >/dev/null 2>&1
work=$HOME/perfhist-build/shim-$short; rm -rf "$work"; mkdir -p "$work"
git -C "$src" archive "$full" | tar -x -C "$work"
mkdir -p "$work/client/src/bin" && cp "$here/shim/perfhist_shim.rs" "$work/client/src/bin/"
k=$(grep -oE 'DEFAULT_LSD_K_VALUE: u32 = [0-9]+' "$work/client/src/main.rs" | grep -oE '[0-9]+$')
cd "$work" && export CARGO_TARGET_DIR=$work/target CARGO_REGISTRIES_CRATES_IO_PROTOCOL=sparse
rustup run "$tc" cargo build --release --locked -p nice_client --bin perfhist_shim > build.log 2>&1 \
  || { cp build.log "$here/logs/shim-build-$short.log"; echo "SHIM BUILD FAILED $short"; exit 1; }
mkdir -p "$out"; cp "$CARGO_TARGET_DIR/release/perfhist_shim" "$out/shim"; echo "$k" > "$out/k"
echo "{\"sha\":\"$full\",\"date\":\"$date\",\"toolchain\":\"$(rustup run "$tc" rustc --version)\",\"k\":$k}" > "$out/build.json"
cd /; rm -rf "$work"; echo "built shim $out (k=$k, $tc)"
