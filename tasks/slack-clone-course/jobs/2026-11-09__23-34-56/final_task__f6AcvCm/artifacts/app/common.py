import json,base64,re
from aiohttp import web
import db
class HTTPError(Exception):
 def __init__(self,status,message='error'): self.status=status; self.message=message
@web.middleware
async def error_middleware(request,handler):
 try: return await handler(request)
 except HTTPError as e: return web.json_response({'error':e.message},status=e.status)
 except web.HTTPException: raise
 except Exception as e: return web.json_response({'error':str(e)},status=500)
async def read_json(request):
 try: return await request.json()
 except: raise HTTPError(400,'invalid json')
def require_user(request):
 h=request.headers.get('Authorization','')
 if not h.startswith('Bearer '): raise HTTPError(401,'unauthorized')
 r=db.conn.execute('SELECT user_id FROM tokens WHERE token=?',(h[7:],)).fetchone()
 if not r: raise HTTPError(401,'unauthorized')
 return r['user_id']
def user_to_json(r):
 return {'id':r['id'],'username':r['username'],'display_name':r['display_name'],'timezone':r['timezone'] or 'UTC','avatar_url':r['avatar_url'] or '','status_text':r['status_text'] or '','status_emoji':r['status_emoji'] or ''}
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
 r=db.conn.execute('SELECT last_event_id FROM channels WHERE id=?',(channel_id,)).fetchone()
 if not r: return 0
 eid=r['last_event_id']+1
 db.conn.execute('UPDATE channels SET last_event_id=? WHERE id=?',(eid,channel_id))
 db.conn.execute('INSERT INTO events(channel_id,event_id,kind,data,created_at) VALUES(?,?,?,?,?)',(channel_id,eid,kind,json.dumps(data),db.now_iso()))
 return eid
def broadcast_global(payload):
 db.conn.execute('INSERT INTO global_events(payload,created_at) VALUES(?,?)',(json.dumps(payload),db.now_iso()))
