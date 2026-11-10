import json,base64,secrets,re
from aiohttp import web
from db import connect,now_iso
class HTTPError(Exception):
 def __init__(self,status,reason): self.status=status; self.reason=reason
@web.middleware
async def error_middleware(request,handler):
 try: return await handler(request)
 except HTTPError as e: return web.json_response({'error':e.reason},status=e.status)
 except Exception as e: return web.json_response({'error':str(e)},status=500)
async def read_json(request):
 try:
  x=await request.json()
  return x if isinstance(x,dict) else {}
 except: return {}
def require_user(request):
 h=request.headers.get('Authorization','')
 if not h.startswith('Bearer '): raise HTTPError(401,'authentication required')
 r=connect().execute('SELECT u.* FROM tokens t JOIN users u ON u.id=t.user_id WHERE t.token=?',(h[7:],)).fetchone()
 if not r: raise HTTPError(401,'invalid token')
 return r
def user_to_json(r):
 return {k:r[k] or '' for k in ('id','username','display_name','timezone','avatar_url','status_text','status_emoji')}
def parse_limit(request):
 try: n=int(request.query.get('limit','50'))
 except: raise HTTPError(400,'invalid limit')
 if not 1<=n<=200: raise HTTPError(400,'invalid limit')
 return n
def encode_cursor(n): return base64.urlsafe_b64encode(json.dumps({'k':n}).encode()).decode()
def decode_cursor(s):
 try:
  x=json.loads(base64.urlsafe_b64decode(s.encode())); n=x['k']
  if not isinstance(n,int): raise ValueError()
  return n
 except: raise HTTPError(400,'invalid cursor')
def emit_event(cid,kind,data):
 c=connect(); c.execute('BEGIN IMMEDIATE')
 try:
  c.execute('UPDATE channels SET last_event_id=last_event_id+1 WHERE id=?',(cid,))
  n=c.execute('SELECT last_event_id FROM channels WHERE id=?',(cid,)).fetchone()[0]
  p={'type':kind,'event_id':n,'channel_id':cid,**data}
  c.execute('INSERT INTO events(channel_id,event_id,payload) VALUES(?,?,?)',(cid,n,json.dumps(p))); c.commit(); return n
 except: c.rollback(); raise
def broadcast_global(p): connect().execute('INSERT INTO broadcasts(payload) VALUES(?)',(json.dumps(p),))
