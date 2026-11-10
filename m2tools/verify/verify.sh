#!/bin/bash
# verify.sh <app.tgz|app-dir> <run> [label]: rerun that run's checks (verbose) on an agent-built /app with a fresh database.
set -u
# Match the task image: Python 3.12 venv first on PATH (like /opt/venv there), with pip-installable deps
export PATH="/opt/venv312/bin:$PATH" VIRTUAL_ENV=/opt/venv312
SRC="$1"; RUN="$2"; LABEL="${3:-}"; TS=$(date +%s%N)
python3 /home/claude/m2verify/killapp.py; sleep 1
mkdir -p /tmp/old-apps /tmp/old-specs
[ -e /app ] && mv /app /tmp/old-apps/app-$TS
if [ -d "$SRC" ]; then cp -r "$SRC" /app; else mkdir -p /tmp/unpack-$TS && tar -xzf "$SRC" -C /tmp/unpack-$TS && mv /tmp/unpack-$TS/app /app; fi
[ -d /app/data ] && mv /app/data /tmp/old-apps/data-$TS; mkdir -p /app/data
mkdir -p /tmp/old-apps/dbs-$TS; for f in /app/*.db /app/*.db-wal /app/*.db-shm /app/*.sqlite /app/*.sqlite3; do [ -e "$f" ] && mv "$f" /tmp/old-apps/dbs-$TS/; done
cp /home/claude/m2/tasks/slack-clone-course/course-staff-files/final_task/environment/timer.sh /app/timer.sh
[ -e /spec ] && mv /spec /tmp/old-specs/spec-$TS
cp -r /home/claude/m2build/$RUN /spec
for f in $(find /spec -name lib.sh); do sed -i 's/^FEEDBACK=.*/FEEDBACK=verbose/' $f; done
OUT=/home/claude/m2verify/results/${LABEL:-run$RUN-$TS}.txt; mkdir -p "$(dirname "$OUT")"
{
echo "# verify run=$RUN label=$LABEL src=$SRC $(date)"
timeout 60 python3 /tmp/harness.py "bash /spec/tools/restart.sh --full" | head -3
CHECKS="/spec/base/checks/check_base.sh"
[ -f /spec/checks/regression.sh ] && CHECKS="$CHECKS /spec/checks/regression.sh"
for c in a b c d e; do for f in $(ls /spec/$c/checks/check_${c}_*.sh 2>/dev/null | sort -V); do CHECKS="$CHECKS $f"; done; done
for f in $CHECKS; do
  echo "== $f"
  timeout 45 python3 /tmp/harness.py "bash $f" | grep -E "^(FAIL|RESULT|REGRESSION)|TIMEOUT"
done
} 2>&1 | tee "$OUT"
python3 /home/claude/m2verify/summarize.py "$OUT"
