#!/bin/bash
# Verify every official run attempt in /home/claude/m2art/analysis.jsonl that has an app tarball and no result yet.
cd /home/claude/m2verify
python3 - <<'PY' | while read run rep att job; do
import json
for l in open("/home/claude/m2art/analysis.jsonl"):
    a = json.loads(l)
    if a.get("exit_status"):
        print(a["run"], a["rep"], a.get("attempt", 1), a["job"])
PY
  lab="$run-rep$rep-a$att"; out="results/$lab.txt"
  [ -f "$out.sum" ] && grep -q SUMMARY "$out.sum" && continue
  [ -f "/home/claude/m2art/$job.app.tgz" ] || { echo "no tarball for $job"; continue; }
  echo ">>> $lab $job"
  ./verify.sh /home/claude/m2art/$job.app.tgz $run $lab > /dev/null 2>&1
  python3 summarize.py "$out" > "$out.sum"
  cat "$out.sum"
done
