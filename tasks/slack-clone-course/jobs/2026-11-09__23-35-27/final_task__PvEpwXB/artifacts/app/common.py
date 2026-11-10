import json,base64,re
from aiohttp import web
from db import conn,now_iso
class HTTPError(Exception):
    def __init__(self,status,reason): self.status=status; self.reason=reason
@web.middleware
async def error_middleware(request,handler):
    try: return await handler(request)
    except HTTPError as e: return web.json_response({"error":e.reason},status=e.status)
    except web.HTTPException: raise
    except Exception as e:
        return web.json_response({"error":"internal server error"},status=500)
async def read_json(request):
    try:
        x=await request.json()
        return x if isinstance(x,dict) else {}
    except Exception: return {}
def require_user(request):
    h=request.headers.get("Authorization","")
    if not h.startswith("Bearer "): raise HTTPError(401,"authentication required")
    r=conn.execute("SELECT user_id FROM tokens WHERE token=?",(h[7:].strip(),)).fetchone()
    if not r: raise HTTPError(401,"invalid token")
    return r["user_id"]
def user_to_json(row):
    return {k: row[k] if k in row.keys() and row[k] is not None else
            ("" if k not in ("id","username","display_name","timezone") else None)
            for k in ("id","username","display_name","timezone","avatar_url","status_text","status_emoji")}
def parse_limit(request):
    try: n=int(request.query.get("limit","50"))
    except: raise HTTPError(400,"invalid limit")
    if n<1 or n>200: raise HTTPError(400,"invalid limit")
    return n
def encode_cursor(n):
    return base64.urlsafe_b64encode(json.dumps({"k":int(n)}).encode()).decode()
def decode_cursor(s):
    try:
        x=json.loads(base64.urlsafe_b64decode(s.encode()).decode())
        if not isinstance(x,dict) or isinstance(x.get("k"),bool) or not isinstance(x.get("k"),int): raise ValueError()
        return x["k"]
    except: raise HTTPError(400,"invalid cursor")
def emit_event(channel_id,kind,data):
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("UPDATE channels SET last_event_id=last_event_id+1 WHERE id=?",(channel_id,))
        eid=conn.execute("SELECT last_event_id FROM channels WHERE id=?",(channel_id,)).fetchone()[0]
        payload={"type":kind,"event_id":eid,"channel_id":channel_id,**data}
        conn.execute("INSERT INTO events(channel_id,event_id,payload) VALUES(?,?,?)",
                     (channel_id,eid,json.dumps(payload)))
        conn.execute("COMMIT"); return eid
    except:
        conn.execute("ROLLBACK"); raise
def broadcast_global(payload):
    conn.execute("INSERT INTO broadcasts(payload) VALUES(?)",(json.dumps(payload),))
def channel_json(r):
    return {"id":r["id"],"workspace_id":r["workspace_id"],"name":r["name"],
      "is_private":bool(r["is_private"]),"is_dm":bool(r["is_dm"]),"topic":r["topic"] or "",
      "is_archived":bool(r["is_archived"]),"created_at":r["created_at"]}
