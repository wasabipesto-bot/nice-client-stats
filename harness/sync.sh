#!/usr/bin/env bash
# From the build machine: push new binaries to the measurement host, pull a consistent queue
# snapshot, the results and the logs back into results/<run>/.
#   PERFHIST_REMOTE=host:dir PERFHIST_RUN=run4 ./sync.sh
set -euo pipefail
cd "$(dirname "$0")"
: "${PERFHIST_REMOTE:?set PERFHIST_REMOTE=host:dir}" "${PERFHIST_RUN:?set PERFHIST_RUN, e.g. run4}"
host=${PERFHIST_REMOTE%%:*}; dir=${PERFHIST_REMOTE#*:}
rsync -a bins/ "$PERFHIST_REMOTE/bins/"
mkdir -p "results/$PERFHIST_RUN"
ssh "$host" "cd $dir && python3 -c \"import sqlite3; s=sqlite3.connect('queue.db'); d=sqlite3.connect('results/queue-snapshot.db'); s.backup(d); d.close()\""
rsync -a "$PERFHIST_REMOTE/results/" "results/$PERFHIST_RUN/"
rsync -a "$PERFHIST_REMOTE/logs/" "results/$PERFHIST_RUN/logs/"
echo "synced $(wc -l < "results/$PERFHIST_RUN/results.jsonl" 2>/dev/null || echo 0) records into results/$PERFHIST_RUN"
