#!/bin/bash
cd /app
mkdir -p /app/data/files
python3 -c 'import aiohttp, tzdata' 2>/dev/null || pip install -q -r /app/requirements.txt >/tmp/pip.log 2>&1
(while true; do redis-server --port 6379 --save '' --appendonly no >/tmp/redis.log 2>&1; sleep 1; done) &
python3 -c 'import sys; sys.path.insert(0, "/app"); import db; db.init_db()'
for i in 0 1 2; do
 (while true; do python3 /app/server.py --port $((8000+i)) --node-id $i >>/tmp/node$i.log 2>&1; sleep 1; done) &
done
(while true; do [ -f /app/irc.py ] && python3 /app/irc.py >>/tmp/irc.log 2>&1; sleep 1; done) &
wait
