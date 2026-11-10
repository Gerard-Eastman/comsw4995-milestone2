#!/usr/bin/env bash
# Like run_all.sh, but overlaps rows: each row's two repeats start as soon as the previous row's
# containers are built (its /spec is baked into the image by then), with at most MAXROWS rows going at once.
# Agent setup (apt-get, uv) takes ~20 min per trial on this network, so overlapping saves hours.
#   m2tools/run_fast.sh                  # default: 3 4 5.1 5.2 5.3, then the 1.x reruns
#   m2tools/run_fast.sh 4 5.1            # only these rows
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
JOBS="$ROOT/tasks/slack-clone-course/jobs"
MAXROWS=${MAXROWS:-2}
RUNS=("$@")
[ ${#RUNS[@]} -eq 0 ] && RUNS=(3 4 5.1 5.2 5.3 1.1 1.2 1.3)
mkdir -p "$ROOT/m2logs"
START=$(date +%s)

built() {  # $1 = number of job folders that existed before the row started: true when the 2 new trials are past image build
  local n=0
  for j in $(ls "$JOBS" | tail -n +"$(( $1 + 1 ))"); do
    for t in "$JOBS/$j"/final_task__*; do
      [ -f "$t/trial.log" ] && grep -q "Running command" "$t/trial.log" && n=$((n+1))
    done
  done
  [ "$n" -ge 2 ]
}

pids=()
for r in "${RUNS[@]}"; do
  while :; do  # keep at most MAXROWS rows running
    alive=0; for p in "${pids[@]:-}"; do [ -n "$p" ] && kill -0 "$p" 2>/dev/null && alive=$((alive+1)); done
    [ "$alive" -lt "$MAXROWS" ] && break
    sleep 20
  done
  before=$(ls "$JOBS" | wc -l | tr -d ' ')
  echo "================ row $r starting  ($(date '+%H:%M'))"
  "$HERE/run_config.sh" "$r" 2 official > "$ROOT/m2logs/row-$r.log" 2>&1 &
  pids+=($!)
  for i in $(seq 1 60); do   # up to 10 min: both repeats of THIS row started, and both of their containers built
    [ "$(grep -c 'started' "$ROOT/m2logs/row-$r.log" 2>/dev/null)" -ge 2 ] && built "$before" && break; sleep 10
  done
  echo "               row $r containers built ($(date '+%H:%M')); next row may start"
done
echo "================ all rows started; waiting for them to finish"
for p in "${pids[@]}"; do wait "$p"; done
grep official "$ROOT/runs-m2.log" | tail -n $(( ${#RUNS[@]} * 2 ))
echo "================ all done in $(( ($(date +%s) - START) / 60 )) min"
osascript -e 'tell application "Spotify" to play' 2>/dev/null || afplay /System/Library/Sounds/Glass.aiff
