#!/bin/bash
mkdir -p /app
redis_loop() {
  while true; do
    if ! ss -ltn 'sport = :6379' | grep -q LISTEN; then
      redis-server --bind 127.0.0.1 --port 6379 >>/tmp/redis.log 2>&1 &
    fi
    sleep 1
  done
}
redis_loop &
irc_loop() {
  while true; do
    /opt/test-venv/bin/python /app/irc.py >>/tmp/irc.log 2>&1
    sleep 1
  done
}
irc_loop &
for n in 0 1 2; do
  while true; do NODE_ID=$n /opt/test-venv/bin/python /app/server.py >/tmp/node$n.log 2>&1; sleep 1; done &
done
wait
