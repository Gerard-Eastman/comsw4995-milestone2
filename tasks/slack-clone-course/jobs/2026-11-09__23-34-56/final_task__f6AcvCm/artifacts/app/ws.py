import asyncio,json
from aiohttp import web,WSMsgType
import db
from routes_channels import is_channel_member
async def handler(q):
 tok=q.query.get('token','')
 if tok.startswith('Bearer '): tok=tok[7:]
 ur=db.conn.execute('SELECT user_id FROM tokens WHERE token=?',(tok,)).fetchone()
 if not ur: raise web.HTTPUnauthorized()
 uid=ur['user_id']; db.conn.execute('INSERT OR REPLACE INTO ws_presence(user_id,node_id,connected_at) VALUES(?,?,?)',(uid,0,db.now_iso())); ws=web.WebSocketResponse(); await ws.prepare(q); last={}; global_last=0
 async def pump():
  nonlocal global_last
  while not ws.closed:
   rows=db.conn.execute('SELECT * FROM global_events WHERE id>? ORDER BY id',(global_last,)).fetchall()
   for r in rows:
    await ws.send_json(json.loads(r['payload'])); global_last=r['id']
   for cid,since in list(last.items()):
    rows=db.conn.execute('SELECT * FROM events WHERE channel_id=? AND event_id>? ORDER BY event_id',(cid,since)).fetchall()
    for r in rows:
     p=json.loads(r['data']); out={'type':r['kind'],'event_id':r['event_id'],'channel_id':cid}; out.update(p); await ws.send_json(out); last[cid]=r['event_id']
   await asyncio.sleep(.05)
 task=asyncio.create_task(pump())
 try:
  async for m in ws:
   if m.type!=WSMsgType.TEXT: continue
   x=json.loads(m.data); cid=int(x.get('channel_id',0)); c=db.conn.execute('SELECT * FROM channels WHERE id=?',(cid,)).fetchone()
   if not c or (c['is_private'] and not is_channel_member(cid,uid)):
    await ws.send_json({'type':'error','channel_id':cid,'error':'forbidden'}); continue
   if x.get('type')=='subscribe':
    h=db.conn.execute('SELECT last_event_id FROM channels WHERE id=?',(cid,)).fetchone()['last_event_id']; last[cid]=h
    await ws.send_json({'type':'subscribed','channel_id':cid,'head_event_id':h})
   elif x.get('type')=='resume':
    since=int(x.get('since_event_id',0)); rows=db.conn.execute('SELECT * FROM events WHERE channel_id=? AND event_id>? ORDER BY event_id',(cid,since)).fetchall()
    for r in rows:
     p=json.loads(r['data']); out={'type':r['kind'],'event_id':r['event_id'],'channel_id':cid}; out.update(p); await ws.send_json(out)
    head=db.conn.execute('SELECT last_event_id FROM channels WHERE id=?',(cid,)).fetchone()['last_event_id']; last[cid]=head
    await ws.send_json({'type':'resumed','channel_id':cid,'head_event_id':head})
 finally:
  task.cancel()
  db.conn.execute('DELETE FROM ws_presence WHERE user_id=?',(uid,))
 return ws
def setup(app): app.router.add_get('/api/ws',handler)
