import json,base64,secrets,re
from aiohttp import web
import db
from db import now_iso
class HTTPError(Exception):
 def __init__(self,status,reason): self.status=status; self.reason=reason
@web.middleware
async def error_middleware(request,handler):
 try: return await handler(request)
 except HTTPError as e: return web.json_response({'error':e.reason},status=e.status)
 except Exception as e: return web.json_response({'error':str(e)},status=500)
async def read_json(r):
 try:
  x=await r.json(); return x if isinstance(x,dict) else {}
 except: return {}
def require_user(r):
 h=r.headers.get('Authorization','')
 if not h.startswith('Bearer '): raise HTTPError(401,'authentication required')
 row=db._conn.execute('SELECT u.* FROM tokens t JOIN users u ON u.id=t.user_id WHERE t.token=?',(h[7:],)).fetchone()
 if not row: raise HTTPError(401,'invalid token')
 return row
def user_to_json(r):
 return {k:r[k] for k in ('id','username','display_name','timezone','avatar_url','status_text','status_emoji')}
def parse_limit(r):
 try: n=int(r.query.get('limit','50'))
 except: raise HTTPError(400,'invalid limit')
 if not 1<=n<=200: raise HTTPError(400,'invalid limit')
 return n
def encode_cursor(n): return base64.urlsafe_b64encode(json.dumps({'k':n}).encode()).decode()
def decode_cursor(s):
 try:
  x=json.loads(base64.urlsafe_b64decode(s)); n=x['k']
  if not isinstance(n,int): raise ValueError()
  return n
 except: raise HTTPError(400,'invalid cursor')
def emit_event(cid,kind,data):
 c=db._conn; c.execute('BEGIN IMMEDIATE')
 try:
  c.execute('UPDATE channels SET last_event_id=last_event_id+1 WHERE id=?',(cid,))
  eid=c.execute('SELECT last_event_id FROM channels WHERE id=?',(cid,)).fetchone()[0]
  p={'type':kind,'event_id':eid,'channel_id':cid,**data}
  c.execute('INSERT INTO events(channel_id,event_id,payload) VALUES(?,?,?)',(cid,eid,json.dumps(p)))
  c.execute('COMMIT'); return eid
 except: c.execute('ROLLBACK'); raise
def broadcast_global(p): db._conn.execute('INSERT INTO broadcasts(payload) VALUES(?)',(json.dumps(p),))
