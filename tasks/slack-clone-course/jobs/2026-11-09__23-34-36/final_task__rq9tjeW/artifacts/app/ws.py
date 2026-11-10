import asyncio,json,secrets
from aiohttp import web, WSMsgType
from db import connect
from common import require_user,HTTPError
async def handler(req):
 token=req.query.get('token',''); r=connect().execute('SELECT u.* FROM tokens t JOIN users u ON u.id=t.user_id WHERE t.token=?',(token,)).fetchone()
 if not r: raise web.HTTPUnauthorized()
 ws=web.WebSocketResponse(); await ws.prepare(req); subs={}; last={}; global_last=0; socket_id=secrets.token_urlsafe(12)
 connect().execute("INSERT INTO ws_presence(socket_id,user_id,channel_id,created_at) SELECT ?,user_id,channel_id,datetime('now') FROM channel_members WHERE user_id=?",(socket_id,r['id']))
 async def pump():
  nonlocal global_last
  while not ws.closed:
   grows=connect().execute('SELECT id,data FROM global_events WHERE id>? ORDER BY id',(global_last,)).fetchall()
   for gx in grows:
    await ws.send_str(gx['data']); global_last=gx['id']
   for cid in list(subs):
    since=last.get(cid,0); rows=connect().execute('SELECT event_id,data FROM events WHERE channel_id=? AND event_id>? ORDER BY event_id',(cid,since)).fetchall()
    for x in rows:
     await ws.send_str(x['data']); last[cid]=x['event_id']
   await asyncio.sleep(.08)
 task=asyncio.create_task(pump())
 try:
  async for m in ws:
   if m.type!=WSMsgType.TEXT: continue
   try:d=json.loads(m.data)
   except:continue
   if d.get('type') in ('subscribe','resume'):
    cid=int(d.get('channel_id'))
    if not connect().execute('SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?',(cid,r['id'])).fetchone():
     await ws.send_json({'type':'error','error':'not a channel member','channel_id':cid}); continue
    subs[cid]=1; connect().execute('INSERT OR REPLACE INTO ws_presence(socket_id,user_id,channel_id,created_at) VALUES(?,?,?,datetime(\'now\'))',(socket_id,r['id'],cid))
    head=connect().execute('SELECT last_event_id FROM channels WHERE id=?',(cid,)).fetchone(); hv=head[0] if head else 0
    since=int(d.get('since_event_id',0)) if d.get('type')=='resume' else hv; last[cid]=since
    if d.get('type')=='resume':
     replay=connect().execute('SELECT event_id,data FROM events WHERE channel_id=? AND event_id>? ORDER BY event_id',(cid,since)).fetchall()
     for ev in replay: await ws.send_str(ev['data']); last[cid]=ev['event_id']
    await ws.send_json({'type':'resumed' if d['type']=='resume' else 'subscribed','channel_id':cid,'head_event_id':hv})
 finally:
  connect().execute('DELETE FROM ws_presence WHERE socket_id=?',(socket_id,))
  task.cancel()
 return ws
def setup(app): app.router.add_get('/api/ws',handler)
