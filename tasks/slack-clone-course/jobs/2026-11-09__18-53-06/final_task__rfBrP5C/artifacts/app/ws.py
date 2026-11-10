import asyncio,json,uuid
from aiohttp import web,WSMsgType
import db
from common import HTTPError

subs={}
NODE_ID=0

def cleanup_presence(node_id):
 db.get().execute("DELETE FROM ws_presence WHERE node_id=?",(node_id,))

async def send_to_subscribers(payload):
 cid=payload.get("channel_id")
 for ws in list(subs.get(cid,())):
  try:
   await ws.send_json(payload)
  except Exception:
   subs.get(cid,set()).discard(ws)

async def pump(app):
 es=db.get().execute("SELECT COALESCE(MAX(seq),0) FROM events").fetchone()[0]
 bs=db.get().execute("SELECT COALESCE(MAX(seq),0) FROM broadcasts").fetchone()[0]
 while True:
  try:
   rows=db.get().execute("SELECT seq,payload FROM events WHERE seq>? ORDER BY seq",(es,)).fetchall()
   for r in rows:
    es=r["seq"]
    try: await send_to_subscribers(json.loads(r["payload"]))
    except Exception: pass
   rows=db.get().execute("SELECT seq,payload FROM broadcasts WHERE seq>? ORDER BY seq",(bs,)).fetchall()
   for r in rows:
    bs=r["seq"]; payload=json.loads(r["payload"])
    for ws in list(subs.get(None,set())):
     try: await ws.send_json(payload)
     except Exception: subs.get(None,set()).discard(ws)
   await asyncio.sleep(.05)
  except asyncio.CancelledError: raise
  except Exception: await asyncio.sleep(.05)

def setup(app):
 global NODE_ID
 NODE_ID=app["node_id"]
 cleanup_presence(NODE_ID)
 async def handler(request):
  tok=request.query.get("token","")
  r=db.get().execute("SELECT user_id FROM tokens WHERE token=?",(tok,)).fetchone()
  if not r: raise web.HTTPUnauthorized(text="invalid token")
  ws=web.WebSocketResponse(); await ws.prepare(request)
  conn=uuid.uuid4().hex; uid=r["user_id"]
  db.get().execute("INSERT INTO ws_presence(conn_id,node_id,user_id) VALUES(?,?,?)",(conn,NODE_ID,uid))
  joined=set(); last={}
  try:
   async for m in ws:
    if m.type!=WSMsgType.TEXT: continue
    try: x=json.loads(m.data)
    except: continue
    try: cid=int(x.get("channel_id"))
    except: continue
    if x.get("type")=="subscribe":
     joined.add(cid); subs.setdefault(cid,set()).add(ws)
     head=db.get().execute("SELECT last_event_id FROM channels WHERE id=?",(cid,)).fetchone()
     await ws.send_json({"type":"subscribed","channel_id":cid,"head_event_id":head[0] if head else 0})
    elif x.get("type")=="resume":
     joined.add(cid); subs.setdefault(cid,set()).add(ws)
     since=int(x.get("since_event_id",0))
     rows=db.get().execute("SELECT payload FROM events WHERE channel_id=? AND event_id>? ORDER BY event_id",(cid,since)).fetchall()
     for q in rows:
      p=json.loads(q["payload"])
      if p["event_id"]>last.get(cid,0):
       await ws.send_json(p); last[cid]=p["event_id"]
     head=db.get().execute("SELECT last_event_id FROM channels WHERE id=?",(cid,)).fetchone()
     await ws.send_json({"type":"resumed","channel_id":cid,"head_event_id":head[0] if head else 0})
  finally:
   for cid in joined: subs.get(cid,set()).discard(ws)
   db.get().execute("DELETE FROM ws_presence WHERE conn_id=?",(conn,))
 return_handler=handler
 app.router.add_get("/api/ws",return_handler)
 async def start_pump(app):
  app["pump_task"]=asyncio.create_task(pump(app))
 app.on_startup.append(start_pump)
