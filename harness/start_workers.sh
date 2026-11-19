#!/usr/bin/env bash
# Start one worker per core inside a user scope capped at 2.5 GB, at nice 10, so other services on
# the host keep priority and memory. The last core takes the short jobs first (lane short), the
# others the production-size fields (lane long). Stop with stop_workers.sh.
#   PERFHIST_CORES="4 5 6 7" ./start_workers.sh
cd "$(dirname "$0")"
CORES=${PERFHIST_CORES:-"4 5 6 7"}
if [ -s workers.pids ]; then echo "workers.pids exists: run stop_workers.sh first"; exit 1; fi
rm -f STOP
mkdir -p logs results
last=${CORES##* }
systemd-run --user --scope -q -p MemoryMax=2500M -p MemorySwapMax=0 --unit=perfhist \
  nice -n 10 bash -c "
    for w in $CORES; do
      port=\$((8656 + w)); lane=long; [ \$w = $last ] && lane=short
      setsid bash -c \"while [ ! -f STOP ]; do python3 worker.py \$w \$w \$port \$lane >> logs/worker-\$w.log 2>&1; sleep 30; done\" >/dev/null 2>&1 &
      echo \$! >> workers.pids
    done" &
sleep 2; echo "started $(wc -l < workers.pids) workers on cores $CORES in scope perfhist"
