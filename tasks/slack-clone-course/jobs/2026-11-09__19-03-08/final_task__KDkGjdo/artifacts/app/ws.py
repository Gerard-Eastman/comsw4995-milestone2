import asyncio,json,uuid
from aiohttp import web,WSMsgType
from db import connect
from common import HTTPError
CLIENTS={}
async def handler(req):
 tok=req.query.get('token',''); c=connect(); u=c.execute('SELECT u.* FROM tokens t JOIN users u ON u.id=t.user_id WHERE t.token=?',(tok,)).fetchone(); c.close()
 if not u: raise web.HTTPUnauthorized()
 ws=web.WebSocketResponse(); await ws.prepare(req); key=uuid.uuid4().hex; CLIENTS[key]={'ws':ws,'user':u['id'],'subs':set(),'last':{}}
 c=connect(); c.execute('INSERT INTO ws_presence VALUES(?,?,?)',(key,req.app['node_id'],u['id'])); c.close()
 try:
  async for msg in ws:
   if msg.type!=WSMsgType.TEXT: continue
   try:d=json.loads(msg.data)
   except:continue
   cid=d.get('channel_id'); typ=d.get('type')
   if typ=='subscribe' and cid:
    c=connect(); r=c.execute('SELECT last_event_id FROM channels WHERE id=?',(cid,)).fetchone(); c.close()
    if r:
     CLIENTS[key]['subs'].add(int(cid)); CLIENTS[key]['last'][int(cid)]=r[0]; await ws.send_json({'type':'subscribed','channel_id':int(cid),'head_event_id':r[0]})
   elif typ=='resume' and cid:
    since=int(d.get('since_event_id',0)); c=connect(); rows=c.execute('SELECT payload FROM events WHERE channel_id=? AND event_id>? ORDER BY event_id',(cid,since)).fetchall(); head=c.execute('SELECT last_event_id FROM channels WHERE id=?',(cid,)).fetchone(); c.close()
    CLIENTS[key]['subs'].add(int(cid))
    for r in rows: await ws.send_str(r['payload'])
    h=head[0] if head else since; CLIENTS[key]['last'][int(cid)]=h; await ws.send_json({'type':'resumed','channel_id':int(cid),'head_event_id':h})
 finally:
  CLIENTS.pop(key,None); c=connect(); c.execute('DELETE FROM ws_presence WHERE conn_id=?',(key,)); c.close()
 return ws
async def pump():
 seq=0
 c=connect(); r=c.execute('SELECT COALESCE(MAX(seq),0) FROM events').fetchone(); seq=r[0]; c.close()
 while True:
  try:
   c=connect(); rows=c.execute('SELECT seq,payload,channel_id,event_id FROM events WHERE seq>? ORDER BY seq',(seq,)).fetchall(); c.close()
   for r in rows:
    seq=r['seq']
    for x in list(CLIENTS.values()):
     if r['channel_id'] in x['subs'] and r['event_id']>x['last'].get(r['channel_id'],0):
      try: await x['ws'].send_str(r['payload']); x['last'][r['channel_id']]=r['event_id']
      except: pass
  except: pass
  await asyncio.sleep(.05)
def setup(app):
 app.router.add_get('/api/ws',handler)
 async def startup(app):
  app['pump_task']=asyncio.create_task(pump())
 app.on_startup.append(startup)
