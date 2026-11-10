import json,asyncio,uuid
from aiohttp import web,WSMsgType
from db import conn
from common import require_user,HTTPError
async def handler(request):
    token=request.query.get("token","")
    row=conn.execute("SELECT user_id FROM tokens WHERE token=?",(token,)).fetchone()
    if not row: raise HTTPError(401,"invalid token")
    uid=row["user_id"]
    sock=web.WebSocketResponse()
    await sock.prepare(request)
    conn_id=uuid.uuid4().hex
    conn.execute("INSERT OR REPLACE INTO ws_presence(conn_id,node_id,user_id) VALUES(?,?,?)",(conn_id,request.app["node_id"],uid))
    chans=set()
    last=conn.execute("SELECT COALESCE(MAX(seq),0) FROM events").fetchone()[0]
    blast=conn.execute("SELECT COALESCE(MAX(seq),0) FROM broadcasts").fetchone()[0]
    async def receive():
        nonlocal last
        async for m in sock:
            if m.type!=WSMsgType.TEXT: break
            try: b=json.loads(m.data)
            except: continue
            try: cid=int(b.get("channel_id",0))
            except: continue
            if b.get("type")=="subscribe":
                c=conn.execute("SELECT * FROM channels WHERE id=?",(cid,)).fetchone()
                ok=conn.execute("SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?",(cid,uid)).fetchone()
                wm=conn.execute("SELECT 1 FROM workspace_members WHERE workspace_id=? AND user_id=?",(c["workspace_id"],uid)).fetchone() if c else None
                if not c or (c["is_private"] and not ok) or (not ok and not wm):
                    await sock.send_json({"type":"error","error":"not a channel member"}); continue
                chans.add(cid); r=conn.execute("SELECT last_event_id FROM channels WHERE id=?",(cid,)).fetchone()
                await sock.send_json({"type":"subscribed","channel_id":cid,"head_event_id":r[0] if r else 0})
            elif b.get("type")=="resume":
                c=conn.execute("SELECT * FROM channels WHERE id=?",(cid,)).fetchone()
                ok=conn.execute("SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?",(cid,uid)).fetchone()
                wm=conn.execute("SELECT 1 FROM workspace_members WHERE workspace_id=? AND user_id=?",(c["workspace_id"],uid)).fetchone() if c else None
                if not c or (c["is_private"] and not ok) or (not ok and not wm):
                    await sock.send_json({"type":"error","error":"not a channel member"}); continue
                chans.add(cid)
                for r in conn.execute("SELECT payload FROM events WHERE channel_id=? AND event_id>? ORDER BY event_id",(cid,int(b.get("since_event_id",0)))):
                    await sock.send_str(r["payload"])
                r=conn.execute("SELECT last_event_id FROM channels WHERE id=?",(cid,)).fetchone()
                await sock.send_json({"type":"resumed","channel_id":cid,"head_event_id":r[0] if r else 0})
    async def send_events():
        nonlocal last,blast
        while not sock.closed:
            await asyncio.sleep(.05)
            grows=conn.execute("SELECT * FROM broadcasts WHERE seq>? ORDER BY seq",(blast,)).fetchall()
            for g in grows:
                blast=g["seq"]
                await sock.send_str(g["payload"])
            rows=conn.execute("SELECT * FROM events WHERE seq>? ORDER BY seq",(last,)).fetchall()
            for r in rows:
                last=r["seq"]
                if r["channel_id"] in chans:
                    await sock.send_str(r["payload"])
    tasks=[asyncio.create_task(receive()),asyncio.create_task(send_events())]
    try: await tasks[0]
    finally:
        conn.execute("DELETE FROM ws_presence WHERE conn_id=?",(conn_id,))
        for t in tasks: t.cancel()
    return sock
def setup(app): app.router.add_get("/api/ws",handler)
