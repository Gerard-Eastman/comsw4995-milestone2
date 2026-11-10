import json,base64,secrets,re
from aiohttp import web
from db import connect,now_iso
class HTTPError(Exception):
 def __init__(self,status,msg): self.status=status; self.msg=msg
@web.middleware
async def error_middleware(request,handler):
 try: return await handler(request)
 except HTTPError as e: return web.json_response({'error':e.msg},status=e.status)
 except web.HTTPException: raise
 except Exception as e:
  return web.json_response({'error':str(e)},status=500)
async def read_json(request):
 try: return await request.json()
 except: raise HTTPError(400,'invalid json')
def user_to_json(r):
 return {k:r[k] for k in ('id','username','display_name','timezone','avatar_url','status_text','status_emoji')}
def require_user(request):
 t=request.headers.get('Authorization','')
 if t.lower().startswith('bearer '): t=t[7:]
 if not t: raise HTTPError(401,'authentication required')
 r=connect().execute('SELECT u.* FROM users u JOIN tokens t ON t.user_id=u.id WHERE t.token=?',(t,)).fetchone()
 if not r: raise HTTPError(401,'invalid token')
 return r
def parse_limit(request):
 try: n=int(request.query.get('limit','50'))
 except: raise HTTPError(400,'invalid limit')
 if n<1 or n>200: raise HTTPError(400,'invalid limit')
 return n
def encode_cursor(n): return base64.urlsafe_b64encode(str(n).encode()).decode()
def decode_cursor(s):
 try: return int(base64.urlsafe_b64decode(s.encode()).decode())
 except: raise HTTPError(400,'invalid cursor')
def emit_event(channel_id,kind,data):
 import time
 c=connect()
 for attempt in range(30):
  try:
   c.execute('BEGIN IMMEDIATE')
   n=c.execute('SELECT COALESCE(MAX(event_id),0)+1 n FROM events WHERE channel_id=?',(channel_id,)).fetchone()['n']
   c.execute('INSERT INTO events(channel_id,event_id,kind,data) VALUES(?,?,?,?)',(channel_id,n,kind,json.dumps(data)))
   c.execute('COMMIT')
   return n
  except Exception as e:
   try: c.execute('ROLLBACK')
   except: pass
   if 'locked' not in str(e).lower() and 'busy' not in str(e).lower(): raise
   time.sleep(.02)
 raise HTTPError(503,'database busy')

def broadcast_global(payload):
 c=connect()
 c.execute('CREATE TABLE IF NOT EXISTS global_events(id INTEGER PRIMARY KEY,payload TEXT)')
 c.execute('INSERT INTO global_events(payload) VALUES(?)',(json.dumps(payload),))

def json_user(r): return user_to_json(r)
