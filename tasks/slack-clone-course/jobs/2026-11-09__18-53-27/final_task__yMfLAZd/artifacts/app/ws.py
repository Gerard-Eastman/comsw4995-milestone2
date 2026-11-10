import asyncio, json, uuid
from aiohttp import web, WSMsgType
import db
from common import HTTPError

SUBS=[]
NODE_ID=0

def cleanup_presence(node_id):
    db.get_conn().execute("DELETE FROM ws_presence WHERE node_id=?",(node_id,))

async def send_to_subscribers(payload):
    dead=[]
    for ws,chids in list(SUBS):
        if payload.get("channel_id") not in chids: continue
        try:
            eid=payload.get("event_id",0); cid=payload.get("channel_id")
            if eid <= chids[cid]: continue
            await ws.send_json(payload); chids[cid]=eid
        except Exception:
            dead.append((ws,chids))
    for x in dead:
        if x in SUBS: SUBS.remove(x)

async def pump(app):
    c=db.get_conn()
    last=c.execute("SELECT COALESCE(MAX(seq),0) FROM events").fetchone()[0]
    lastb=c.execute("SELECT COALESCE(MAX(seq),0) FROM broadcasts").fetchone()[0]
    while True:
        try:
            rows=c.execute("SELECT seq,payload FROM events WHERE seq>? ORDER BY seq",(last,)).fetchall()
            for r in rows:
                last=r["seq"]
                await send_to_subscribers(json.loads(r["payload"]))
            bs=c.execute("SELECT seq,payload FROM broadcasts WHERE seq>? ORDER BY seq",(lastb,)).fetchall()
            for r in bs:
                lastb=r["seq"]
                for ws,_ in list(SUBS):
                    try: await ws.send_json(json.loads(r["payload"]))
                    except Exception: pass
        except Exception:
            pass
        await asyncio.sleep(.05)

def setup(app):
    global NODE_ID
    NODE_ID=app["node_id"]; cleanup_presence(NODE_ID)
    async def handler(request):
        h=request.query.get("token","")
        if h.startswith("Bearer "): h=h[7:]
        r=db.get_conn().execute("SELECT u.* FROM tokens t JOIN users u ON u.id=t.user_id WHERE t.token=?",(h,)).fetchone()
        if not r: raise web.HTTPUnauthorized(text='{"error":"unauthorized"}',content_type="application/json")
        ws=web.WebSocketResponse(); await ws.prepare(request)
        ident=uuid.uuid4().hex; chids={}
        SUBS.append((ws,chids)); db.get_conn().execute("INSERT INTO ws_presence VALUES(?,?,?)",(ident,NODE_ID,r["id"]))
        try:
            async for m in ws:
                if m.type!=WSMsgType.TEXT: continue
                try: b=json.loads(m.data)
                except: continue
                cid=b.get("channel_id"); typ=b.get("type")
                if not isinstance(cid,int): continue
                ch=db.get_conn().execute("SELECT last_event_id FROM channels WHERE id=?",(cid,)).fetchone()
                if not ch: continue
                if typ=="subscribe":
                    chids[cid]=ch["last_event_id"]
                    await ws.send_json({"type":"subscribed","channel_id":cid,"head_event_id":ch["last_event_id"]})
                elif typ=="resume":
                    since=b.get("since_event_id",0)
                    rows=db.get_conn().execute("SELECT payload FROM events WHERE channel_id=? AND event_id>? ORDER BY event_id",(cid,since)).fetchall()
                    for x in rows:
                        p=json.loads(x["payload"]); await ws.send_json(p); chids[cid]=p["event_id"]
                    head=db.get_conn().execute("SELECT last_event_id FROM channels WHERE id=?",(cid,)).fetchone()[0]
                    chids[cid]=head
                    await ws.send_json({"type":"resumed","channel_id":cid,"head_event_id":head})
        finally:
            if (ws,chids) in SUBS: SUBS.remove((ws,chids))
            db.get_conn().execute("DELETE FROM ws_presence WHERE conn_id=?",(ident,))
        return ws
    app.router.add_get("/api/ws",handler)
    async def on_start(app):
        app["pump"]=asyncio.create_task(pump(app))
    async def on_cleanup(app):
        app["pump"].cancel()
    app.on_startup.append(on_start); app.on_cleanup.append(on_cleanup)
