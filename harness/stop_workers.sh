#!/usr/bin/env bash
# Stop now (kills running jobs; they are requeued on the next start). To let jobs finish: touch STOP.
cd "$(dirname "$0")"
touch STOP
systemctl --user stop perfhist.scope 2>/dev/null
rm -f workers.pids
python3 -c "import sqlite3; c=sqlite3.connect('queue.db'); c.execute('PRAGMA wal_checkpoint(TRUNCATE)'); c.close()"
echo "stopped; clients=$(pgrep -fc "^$(pwd)/bins/") workers=$(pgrep -fc '^python3 worker.py')"
