#!/usr/bin/env bash
# Wait until every agent run that is going right now has finished, then press play on Spotify.
#   m2tools/alert_when_done.sh            (run it in a second Terminal tab)
cd "$(dirname "$0")/../tasks/slack-clone-course/jobs" || exit 1
running() { for r in */result.json; do grep -Eq '"finished_at": *null' "$r" && echo "${r%/result.json}"; done; }
JOBS=$(running)
[ -z "$JOBS" ] && { echo "No run is going right now."; exit 0; }
echo "Waiting for: $(echo $JOBS)"
while :; do
  left=0
  for j in $JOBS; do grep -Eq '"finished_at": *null' "$j/result.json" && left=$((left+1)); done
  [ "$left" -eq 0 ] && break
  sleep 30
done
echo "All finished at $(date '+%H:%M')."
osascript -e 'tell application "Spotify" to play'
