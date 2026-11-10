#!/usr/bin/env bash
# Run one row of the milestone 2 run plan.
#   m2tools/run_config.sh <run> [repeats] [tag]
#     run:     1.1 1.2 1.3 2.1 2.2 2.3 3 4 5.1 5.2 5.3   (the /spec comes from my-specs-m2/<run>/)
#     repeats: how many repeats to run at the same time (default 2), each its own job folder
#     tag:     "official" (default) or "practice"; practice runs are logged as such and do not touch spec-copies/
# Logs one line per repeat to runs-m2.log: date, run, repeat, tag, job folder, cost.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUN="${1:?usage: m2tools/run_config.sh <run> [repeats] [tag]}"
N="${2:-2}"
TAG="${3:-official}"
SRC="$ROOT/my-specs-m2/$RUN"
TASK="$ROOT/tasks/slack-clone-course"
SPECS="$TASK/course-staff-files/final_task/environment/milestone-specs/milestone-2-specs"
[ -d "$SRC" ] || { echo "no such run: $SRC" >&2; exit 1; }
docker info >/dev/null 2>&1 || { echo "Docker is not running. Run 'colima start' first." >&2; exit 1; }
grep -qE '^OPENAI_API_KEY="?sk-' "$ROOT/dev.env" || { echo "No OpenAI key in dev.env." >&2; exit 1; }

# 1. put exactly this run's /spec into milestone-2-specs, and point the spec link at it
mkdir -p "$SPECS"
find "$SPECS" -mindepth 1 -maxdepth 1 ! -name .gitkeep -exec rm -rf {} +
cp -R "$SRC"/. "$SPECS"/
rm -f "$SPECS/.version"
ln -sfn ../course-staff-files/final_task/environment/milestone-specs/milestone-2-specs "$TASK/student-files/spec"
VER=$(cat "$SRC/.version" 2>/dev/null || echo "?")

# 2. start the repeats (separate jobs, 20 s apart so job folders and builds do not collide)
mkdir -p "$ROOT/m2logs"
cd "$TASK/student-files"
STAMP=$(date +%Y%m%d-%H%M%S)
pids=()
for i in $(seq 1 "$N"); do
  LOG="$ROOT/m2logs/$STAMP-run$RUN-rep$i-$TAG.log"
  ./run_student_openai.sh 2 --agent-setup-timeout-multiplier 8 >"$LOG" 2>&1 &
  pids+=($!)
  echo "$(date '+%H:%M:%S') run $RUN repeat $i started ($TAG); log: m2logs/$(basename "$LOG")"
  [ "$i" -lt "$N" ] && sleep 20
done
echo "Waiting for $N repeat(s) of run $RUN (up to ~60 min). Follow one with: tail -f m2logs/$STAMP-run$RUN-rep1-$TAG.log"
for i in $(seq 1 "$N"); do
  wait "${pids[$((i-1))]}"; st=$?
  LOG="$ROOT/m2logs/$STAMP-run$RUN-rep$i-$TAG.log"
  job=$(grep -oE "jobs/[0-9_-]+" "$LOG" | tail -1)
  cost=$("$ROOT/.venv/bin/python" "$ROOT/m2tools/analyze_job.py" "$TASK/$job" 2>/dev/null | "$ROOT/.venv/bin/python" -c 'import json,sys; c=json.loads(sys.stdin.readline()).get("cost"); print(f"${c:.2f}" if c else "?")' 2>/dev/null)
  line="$(date '+%Y-%m-%d %H:%M') run=$RUN repeat=$i tag=$TAG job=${job:-?} cost=${cost:-?} exit=$st spec=\"$VER\""
  echo "$line" >> "$ROOT/runs-m2.log"
  echo "$line"
done

# 3. keep a copy of exactly what the agent got
if [ "$TAG" = official ]; then
  mkdir -p "$ROOT/spec-copies/$RUN"
  find "$ROOT/spec-copies/$RUN" -mindepth 1 -maxdepth 1 -exec rm -rf {} +
  cp -R "$SPECS"/. "$ROOT/spec-copies/$RUN"/
fi
