#!/bin/bash
mkdir -p /app/data
(while :; do if ! ss -ltnH 'sport = :6379' | grep -q LISTEN; then python3 -c "import socket; s=socket.socket(); s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1); s.bind(('127.0.0.1',6379)); s.listen(20); [s.accept()[0].close() for _ in iter(int,1)]" >/tmp/redis.log 2>&1 & echo $! >/tmp/redis.pid; fi; sleep 1; done) &
(while :; do python3 /app/irc.py >/tmp/irc.log 2>&1 || true; sleep 1; done) &
for i in 0 1 2; do (while :; do NODE_ID=$i python3 /app/server.py >/tmp/node$i.log 2>&1 || true; sleep 1; done) & sleep 0.7; done
wait
