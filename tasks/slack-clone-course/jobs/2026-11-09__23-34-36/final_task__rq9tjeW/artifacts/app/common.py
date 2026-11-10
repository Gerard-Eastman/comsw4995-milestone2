import json, base64, re
from aiohttp import web
from db import connect, now_iso
class HTTPError(Exception):
 def __init__(self,status,message='error'): self.status=status; self.message=message
@web.middleware
async def error_middleware(request,handler):
 try: return await handler(request)
 except HTTPError as e: return web.json_response({'error':e.message},status=e.status)
 except web.HTTPException: raise
 except Exception as e:
  print('ERROR',repr(e)); return web.json_response({'error':'internal error'},status=500)
async def read_json(request):
 try: x=await request.json()
 except: raise HTTPError(400,'invalid json')
 if not isinstance(x,dict): raise HTTPError(400,'invalid json')
 return x
def user_to_json(r):
 if not r:return None
 return {k:r[k] for k in ('id','username','display_name','timezone','avatar_url','status_text','status_emoji')}
def require_user(request):
 h=request.headers.get('Authorization','')
 if not h.startswith('Bearer '): raise HTTPError(401,'unauthorized')
 r=connect().execute('SELECT u.* FROM tokens t JOIN users u ON u.id=t.user_id WHERE t.token=?',(h[7:],)).fetchone()
 if not r: raise HTTPError(401,'unauthorized')
 return r
def parse_limit(request):
 try:n=int(request.query.get('limit','50'))
 except:raise HTTPError(400,'invalid limit')
 if n<1 or n>200:raise HTTPError(400,'invalid limit')
 return n
def encode_cursor(n): return base64.urlsafe_b64encode(str(n).encode()).decode()
def decode_cursor(s):
 try:
  n=int(base64.urlsafe_b64decode(s.encode()).decode())
  if n<0: raise ValueError()
  return n
 except: raise HTTPError(400,'invalid cursor')
def emit_event(channel_id,kind,data):
 c=connect(); row=c.execute('SELECT last_event_id FROM channels WHERE id=?',(channel_id,)).fetchone()
 if not row: return 0
 c.execute('BEGIN IMMEDIATE')
 try:
  row=c.execute('SELECT last_event_id FROM channels WHERE id=?',(channel_id,)).fetchone()
  if not row: c.execute('ROLLBACK'); return 0
  eid=row[0]+1; c.execute('UPDATE channels SET last_event_id=? WHERE id=?',(eid,channel_id))
  payload=dict(data); payload.update({'type':kind,'event_id':eid,'channel_id':channel_id})
  c.execute('INSERT INTO events(channel_id,event_id,kind,data,created_at) VALUES(?,?,?,?,?)',(channel_id,eid,kind,json.dumps(payload),now_iso()))
  c.execute('COMMIT'); return eid
 except Exception:
  try: c.execute('ROLLBACK')
  except: pass
  raise
def broadcast_global(payload):
 c=connect(); c.execute('INSERT INTO global_events(data,created_at) VALUES(?,?)',(json.dumps(payload),now_iso()))
def user_by_id(uid):
 return connect().execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone()
def workspace_by_slug(slug):
 r=connect().execute('SELECT * FROM workspaces WHERE slug=?',(slug,)).fetchone()
 if not r: raise HTTPError(404,'workspace not found')
 return r
def workspace_to_json(r): return {k:r[k] for k in ('id','slug','name','owner_id','join_mode','created_at')}
def role_of(wid,uid):
 r=connect().execute('SELECT role FROM workspace_members WHERE workspace_id=? AND user_id=?',(wid,uid)).fetchone()
 return r['role'] if r else None
def channel_by_id(cid):
 try: cid=int(cid)
 except: raise HTTPError(404,'channel not found')
 r=connect().execute('SELECT * FROM channels WHERE id=?',(cid,)).fetchone()
 if not r: raise HTTPError(404,'channel not found')
 return r
def channel_to_json(r):
 return {k:(bool(r[k]) if k in ('is_private','is_dm','is_archived') else r[k]) for k in ('id','workspace_id','name','is_private','is_dm','topic','is_archived','created_at')}
def add_workspace_member(wid,uid,role='member'):
 connect().execute('INSERT OR IGNORE INTO workspace_members(workspace_id,user_id,role,joined_at) VALUES(?,?,?,?)',(wid,uid,role,now_iso()))
def is_channel_member(cid,uid):
 return connect().execute('SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?',(cid,uid)).fetchone() is not None
def add_channel_member(cid,uid):
 c=connect()
 if not is_channel_member(cid,uid):
  c.execute('INSERT INTO channel_members(channel_id,user_id,last_read_event_id) VALUES(?,?,0)',(cid,uid))
  u=user_to_json(user_by_id(uid)); emit_event(cid,'member.joined',{'user_id':uid,'user':u})
def create_channel(wid,name,private,topic,uid):
 c=connect(); c.execute('INSERT INTO channels(workspace_id,name,is_private,is_dm,topic,created_at) VALUES(?,?,?,?,?,?)',(wid,name,int(private),0,topic,now_iso()))
 r=c.execute('SELECT * FROM channels WHERE id=last_insert_rowid()').fetchone(); add_channel_member(r['id'],uid); return r
