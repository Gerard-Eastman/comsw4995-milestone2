#!/usr/bin/env bash
# Run the whole milestone 2 run plan (2 repeats of each run, the two repeats in parallel), one run after another.
#   m2tools/run_all.sh                 # all 11 runs, in order
#   m2tools/run_all.sh 2.3 3 4         # only these runs
# Safe to stop with Ctrl-C between runs; rerun with the runs that are left.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
RUNS=("$@")
[ ${#RUNS[@]} -eq 0 ] && RUNS=(1.1 1.2 1.3 2.1 2.2 2.3 3 4 5.1 5.2 5.3)
START=$(date +%s)
for r in "${RUNS[@]}"; do
  echo "================ run $r  ($(date '+%H:%M'))"
  "$HERE/run_config.sh" "$r" 2 official
done
echo "================ all done in $(( ($(date +%s) - START) / 60 )) min"
osascript -e 'tell application "Spotify" to play' 2>/dev/null || afplay /System/Library/Sounds/Glass.aiff
