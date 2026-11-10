import asyncio,json,uuid
from aiohttp import web,WSMsgType
import db
from common import HTTPError,require_user

def setup(app):
 async def handler(req):
  token=req.query.get('token','')
  r=db.CONN.execute('SELECT user_id FROM tokens WHERE token=?',(token,)).fetchone()
  if not r: raise web.HTTPUnauthorized(text='invalid token')
  ws=web.WebSocketResponse(); await ws.prepare(req)
  cid=uuid.uuid4().hex; node=int(app['node_id'])
  db.CONN.execute('INSERT INTO ws_presence(conn_id,node_id,user_id) VALUES(?,?,?)',(cid,node,r['user_id']))
  subs=set()
  try:
   async for msg in ws:
    if msg.type!=WSMsgType.TEXT: continue
    try: x=json.loads(msg.data)
    except: continue
    channel=x.get('channel_id')
    if x.get('type')=='subscribe' and channel is not None:
     subs.add(int(channel)); q=db.CONN.execute('SELECT last_event_id FROM channels WHERE id=?',(int(channel),)).fetchone()
     if q: await ws.send_json({'type':'subscribed','channel_id':int(channel),'head_event_id':q[0]})
    elif x.get('type')=='resume' and channel is not None:
     channel=int(channel); since=int(x.get('since_event_id',0))
     rows=db.CONN.execute('SELECT payload FROM events WHERE channel_id=? AND event_id>? ORDER BY event_id',(channel,since)).fetchall()
     for z in rows: await ws.send_str(z['payload'])
     q=db.CONN.execute('SELECT last_event_id FROM channels WHERE id=?',(channel,)).fetchone()
     await ws.send_json({'type':'resumed','channel_id':channel,'head_event_id':q[0] if q else 0}); subs.add(channel)
  finally:
   db.CONN.execute('DELETE FROM ws_presence WHERE conn_id=?',(cid,))

 async def pump(app):
  last=db.CONN.execute('SELECT COALESCE(MAX(seq),0) FROM events').fetchone()[0]
  while True:
   await asyncio.sleep(.05)
   rows=db.CONN.execute('SELECT seq,payload,channel_id,event_id FROM events WHERE seq>? ORDER BY seq',(last,)).fetchall()
   last=max([last]+[x['seq'] for x in rows])
   for x in rows:
    for ws in list(app['sockets']):
     try:
      if x['channel_id'] in ws['subs']: await ws['obj'].send_str(x['payload'])
     except: pass
 async def track(req):
  pass
 async def startup(app):
  app['sockets']=[]
  db.CONN.execute('DELETE FROM ws_presence WHERE node_id=?',(int(app['node_id']),))
  async def p():
   last=db.CONN.execute('SELECT COALESCE(MAX(seq),0) FROM events').fetchone()[0]
   blast=db.CONN.execute('SELECT COALESCE(MAX(seq),0) FROM broadcasts').fetchone()[0]
   while True:
    await asyncio.sleep(.05)
    rows=db.CONN.execute('SELECT seq,payload,channel_id,event_id FROM events WHERE seq>? ORDER BY seq',(last,)).fetchall()
    for x in rows:
     last=x['seq']
     for item in list(app['sockets']):
      if x['channel_id'] in item[1] and x['event_id']>item[1][x['channel_id']]:
       try: await item[0].send_str(x['payload']); item[1][x['channel_id']]=x['event_id']
       except: pass
    grows=db.CONN.execute('SELECT seq,payload FROM broadcasts WHERE seq>? ORDER BY seq',(blast,)).fetchall()
    for x in grows:
     blast=x['seq']
     for item in list(app['sockets']):
      try: await item[0].send_str(x['payload'])
      except: pass
  app['pump']=asyncio.create_task(p())
 app.on_startup.append(startup)
 old=handler
 async def wrapped(req):
  token=req.query.get('token',''); r=db.CONN.execute('SELECT user_id FROM tokens WHERE token=?',(token,)).fetchone()
  if not r: raise web.HTTPUnauthorized()
  ws=web.WebSocketResponse(); await ws.prepare(req); subs={}
  app['sockets'].append((ws,subs)); cid=uuid.uuid4().hex
  db.CONN.execute('INSERT OR REPLACE INTO ws_presence(conn_id,node_id,user_id) VALUES(?,?,?)',(cid,int(app['node_id']),r['user_id'])); db.CONN.commit()
  try:
   async for msg in ws:
    if msg.type!=WSMsgType.TEXT: continue
    try: x=json.loads(msg.data)
    except: continue
    ch=x.get('channel_id')
    if ch is None: continue
    ch=int(ch)
    cr=db.CONN.execute('SELECT * FROM channels WHERE id=?',(ch,)).fetchone()
    if not cr: await ws.send_json({'type':'error','error':'channel not found'}); continue
    if cr['is_private'] and not db.CONN.execute('SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?',(ch,r['user_id'])).fetchone(): await ws.send_json({'type':'error','error':'forbidden'}); continue
    if x.get('type')=='subscribe':
     q=db.CONN.execute('SELECT last_event_id FROM channels WHERE id=?',(ch,)).fetchone()
     subs[ch]=q[0] if q else 0
     await ws.send_json({'type':'subscribed','channel_id':ch,'head_event_id':q[0] if q else 0})
    elif x.get('type')=='resume':
     for z in db.CONN.execute('SELECT payload,event_id FROM events WHERE channel_id=? AND event_id>? ORDER BY event_id',(ch,int(x.get('since_event_id',0)))):
      await ws.send_str(z['payload'])
     q=db.CONN.execute('SELECT last_event_id FROM channels WHERE id=?',(ch,)).fetchone()
     await ws.send_json({'type':'resumed','channel_id':ch,'head_event_id':q[0] if q else 0}); subs[ch]=q[0] if q else 0
  finally:
   if (ws,subs) in app['sockets']: app['sockets'].remove((ws,subs))
   db.CONN.execute('DELETE FROM ws_presence WHERE conn_id=?',(cid,))
  return ws
 app.router.add_get('/api/ws',wrapped)
