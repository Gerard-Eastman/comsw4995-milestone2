import base64,json,uuid
from aiohttp import web
import db

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
 tok=h[7:].strip()
 r=db.get().execute("SELECT u.* FROM tokens t JOIN users u ON u.id=t.user_id WHERE t.token=?", (tok,)).fetchone()
 if not r: raise HTTPError(401,"invalid token")
 return r

def user_to_json(r):
 return {k:r[k] for k in ("id","username","display_name","timezone","avatar_url","status_text","status_emoji")}

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
 c=db.get()
 c.execute("BEGIN IMMEDIATE")
 try:
  c.execute("UPDATE channels SET last_event_id=last_event_id+1 WHERE id=?",(channel_id,))
  eid=c.execute("SELECT last_event_id FROM channels WHERE id=?",(channel_id,)).fetchone()[0]
  p={"type":kind,"event_id":eid,"channel_id":channel_id,**data}
  c.execute("INSERT INTO events(channel_id,event_id,payload) VALUES(?,?,?)",(channel_id,eid,json.dumps(p)))
  c.execute("COMMIT"); return eid
 except:
  c.execute("ROLLBACK"); raise

def broadcast_global(payload):
 db.get().execute("INSERT INTO broadcasts(payload) VALUES(?)",(json.dumps(payload),))
