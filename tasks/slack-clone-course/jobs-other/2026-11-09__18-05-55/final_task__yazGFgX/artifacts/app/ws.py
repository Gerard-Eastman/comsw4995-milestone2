import asyncio,json
from aiohttp import web,WSMsgType
from common import require_user,HTTPError
from db import connect
async def handler(q):
 token=q.query.get('token','')
 if not token: raise web.HTTPUnauthorized()
 c=connect(); c.execute('CREATE TABLE IF NOT EXISTS ws_presence(user_id INTEGER PRIMARY KEY)'); r=c.execute('SELECT user_id FROM tokens WHERE token=?',(token,)).fetchone()
 if not r: raise web.HTTPUnauthorized()
 ws=web.WebSocketResponse(); await ws.prepare(q); subs={}; global_last=0; c.execute('INSERT OR REPLACE INTO ws_presence(user_id) VALUES(?)',(r['user_id'],))
 async def pump():
  nonlocal global_last
  while not ws.closed:
   grows=c.execute('SELECT id,payload FROM global_events WHERE id>? ORDER BY id',(global_last,)).fetchall()
   for gx in grows:
    await ws.send_json(json.loads(gx['payload'])); global_last=gx['id']
   for cid,last in list(subs.items()):
    rows=c.execute('SELECT * FROM events WHERE channel_id=? AND event_id>? ORDER BY event_id',(cid,last)).fetchall()
    for x in rows:
     await ws.send_json({'type':x['kind'],'event_id':x['event_id'],'channel_id':cid,**json.loads(x['data'])}); subs[cid]=x['event_id']
   await asyncio.sleep(.08)
 task=asyncio.create_task(pump())
 try:
  async for m in ws:
   if m.type!=WSMsgType.TEXT: continue
   d=json.loads(m.data); cid=int(d.get('channel_id',0))
   if d.get('type')=='subscribe':
    ch=c.execute('SELECT * FROM channels WHERE id=?',(cid,)).fetchone()
    ok=ch and (c.execute('SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?',(cid,r['user_id'])).fetchone() or (not ch['is_private'] and c.execute('SELECT 1 FROM members WHERE workspace_id=? AND user_id=?',(ch['workspace_id'],r['user_id'])).fetchone()))
    if not ok:
     await ws.send_json({'type':'error','error':'forbidden','channel_id':cid}); continue
    head=c.execute('SELECT COALESCE(MAX(event_id),0) n FROM events WHERE channel_id=?',(cid,)).fetchone()['n']; subs[cid]=head
    await ws.send_json({'type':'subscribed','channel_id':cid,'head_event_id':head})
   elif d.get('type')=='resume':
    ch=c.execute('SELECT * FROM channels WHERE id=?',(cid,)).fetchone()
    ok=ch and (c.execute('SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?',(cid,r['user_id'])).fetchone() or (not ch['is_private'] and c.execute('SELECT 1 FROM members WHERE workspace_id=? AND user_id=?',(ch['workspace_id'],r['user_id'])).fetchone()))
    if not ok:
     await ws.send_json({'type':'error','error':'forbidden','channel_id':cid}); continue
    since=int(d.get('since_event_id',0)); rows=c.execute('SELECT * FROM events WHERE channel_id=? AND event_id>? ORDER BY event_id',(cid,since)).fetchall()
    for x in rows: await ws.send_json({'type':x['kind'],'event_id':x['event_id'],'channel_id':cid,**json.loads(x['data'])})
    head=c.execute('SELECT COALESCE(MAX(event_id),0) n FROM events WHERE channel_id=?',(cid,)).fetchone()['n']; subs[cid]=head
    await ws.send_json({'type':'resumed','channel_id':cid,'head_event_id':head})
 finally:
  task.cancel()
  c.execute('DELETE FROM ws_presence WHERE user_id=?',(r['user_id'],))
 return ws
def setup(app): app.router.add_get('/api/ws',handler)
