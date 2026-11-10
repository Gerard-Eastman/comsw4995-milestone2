import asyncio,json,uuid
from aiohttp import web,WSMsgType
import db
from common import HTTPError,require_user

SUBS={}
async def send_to_subscribers(payload):
 for ws in list(SUBS.get(payload.get('channel_id'),set())):
  try: await ws.send_json(payload)
  except Exception:
   for s in list(SUBS.get(payload.get('channel_id'),set())):
    if s is ws: SUBS[payload.get('channel_id')].discard(s)

def setup(app):
 async def handler(request):
  token=request.query.get('token','')
  if token:
   r=db.CONN.execute('SELECT u.* FROM tokens t JOIN users u ON u.id=t.user_id WHERE t.token=?',(token,)).fetchone()
   if not r: raise HTTPError(401,'invalid token')
   user=r
  else:
   user=require_user(request)
  ws=web.WebSocketResponse(); await ws.prepare(request)
  conn=uuid.uuid4().hex; node=app['node_id']
  db.CONN.execute('INSERT OR REPLACE INTO ws_presence VALUES(?,?,?)',(conn,node,user['id']))
  subscribed=set()
  try:
   async for msg in ws:
    if msg.type!=WSMsgType.TEXT: continue
    try: b=json.loads(msg.data)
    except: continue
    typ=b.get('type'); cid=b.get('channel_id')
    if not isinstance(cid,int): continue
    ch=db.CONN.execute('SELECT * FROM channels WHERE id=?',(cid,)).fetchone()
    if not ch: continue
    if typ=='subscribe':
     SUBS.setdefault(cid,set()).add(ws); subscribed.add(cid)
     await ws.send_json({'type':'subscribed','channel_id':cid,'head_event_id':ch['last_event_id']})
    elif typ=='resume':
     since=b.get('since_event_id',0)
     rows=db.CONN.execute('SELECT payload FROM events WHERE channel_id=? AND event_id>? ORDER BY event_id',(cid,since)).fetchall()
     for r in rows: await ws.send_str(r['payload'])
     SUBS.setdefault(cid,set()).add(ws); subscribed.add(cid)
     head=db.CONN.execute('SELECT last_event_id FROM channels WHERE id=?',(cid,)).fetchone()['last_event_id']
     await ws.send_json({'type':'resumed','channel_id':cid,'head_event_id':head})
  finally:
   for cid in subscribed:
    SUBS.get(cid,set()).discard(ws)
   db.CONN.execute('DELETE FROM ws_presence WHERE conn_id=?',(conn,))
  return ws
 app.router.add_get('/api/ws',handler)
 async def pump(app):
  db.CONN.execute('DELETE FROM ws_presence WHERE node_id=?',(app['node_id'],))
  app['event_seq']=(db.CONN.execute('SELECT coalesce(max(seq),0) x FROM events').fetchone()['x'])
  app['broadcast_seq']=(db.CONN.execute('SELECT coalesce(max(seq),0) x FROM broadcasts').fetchone()['x'])
  while True:
   try:
    rows=db.CONN.execute('SELECT seq,payload FROM events WHERE seq>? ORDER BY seq',(app['event_seq'],)).fetchall()
    if rows:
     app['event_seq']=rows[-1]['seq']
     for r in rows:
      await send_to_subscribers(json.loads(r['payload']))
    rows=db.CONN.execute('SELECT seq,payload FROM broadcasts WHERE seq>? ORDER BY seq',(app['broadcast_seq'],)).fetchall()
    if rows:
     app['broadcast_seq']=rows[-1]['seq']
     for r in rows:
      for ws in list({x for s in SUBS.values() for x in s}):
       try: await ws.send_str(r['payload'])
       except Exception: pass
   except Exception: pass
   await asyncio.sleep(.05)
 async def startup(app): app['pump']=asyncio.create_task(pump(app))
 async def cleanup(app): app['pump'].cancel()
 app.on_startup.append(startup); app.on_cleanup.append(cleanup)
