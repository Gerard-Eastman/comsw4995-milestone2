import json,base64,re,sqlite3
from aiohttp import web
from db import connect,now_iso
class HTTPError(Exception):
 def __init__(self,status,msg): self.status=status; self.msg=msg
@web.middleware
async def error_middleware(request,handler):
 try: return await handler(request)
 except HTTPError as e: return web.json_response({'error':e.msg},status=e.status)
 except web.HTTPException: raise
 except Exception as e: return web.json_response({'error':str(e)},status=500)
async def read_json(r):
 try: return await r.json()
 except: raise HTTPError(400,'invalid json')
def require_user(r):
 t=r.headers.get('Authorization','')
 if not t.startswith('Bearer '):
  q=r.query.get('token','')
  t='Bearer '+q if q else ''
 if not t.startswith('Bearer '): raise HTTPError(401,'authentication required')
 c=connect(); x=c.execute('SELECT u.* FROM tokens t JOIN users u ON u.id=t.user_id WHERE t.token=?',(t[7:],)).fetchone(); c.close()
 if not x: raise HTTPError(401,'invalid token')
 return x
def user_to_json(x):
 return {k:x[k] for k in ('id','username','display_name','timezone','avatar_url','status_text','status_emoji')}
def parse_limit(r):
 try: n=int(r.query.get('limit','50'))
 except: raise HTTPError(400,'invalid limit')
 if n<1 or n>200: raise HTTPError(400,'invalid limit')
 return n
def encode_cursor(n): return base64.urlsafe_b64encode(json.dumps({'k':n}).encode()).decode()
def decode_cursor(s):
 if not s:return None
 try:
  x=json.loads(base64.urlsafe_b64decode(s.encode())); n=x['k']
  if not isinstance(n,int): raise ValueError()
  return n
 except: raise HTTPError(400,'invalid cursor')
def emit_event(cid,kind,data):
 c=connect()
 try:
  c.execute('BEGIN IMMEDIATE'); c.execute('UPDATE channels SET last_event_id=last_event_id+1 WHERE id=?',(cid,))
  eid=c.execute('SELECT last_event_id FROM channels WHERE id=?',(cid,)).fetchone()[0]
  p={'type':kind,'event_id':eid,'channel_id':cid};p.update(data)
  c.execute('INSERT INTO events(channel_id,event_id,payload) VALUES(?,?,?)',(cid,eid,json.dumps(p)));c.execute('COMMIT');return eid
 except: c.execute('ROLLBACK');raise
 finally:c.close()
def broadcast_global(p):
 c=connect();c.execute('INSERT INTO broadcasts(payload) VALUES(?)',(json.dumps(p),));c.close()
