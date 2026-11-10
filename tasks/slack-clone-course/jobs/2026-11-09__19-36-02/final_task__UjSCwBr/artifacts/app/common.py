import json,base64,re,secrets
from aiohttp import web
import db
class HTTPError(Exception):
 def __init__(self,status,reason): self.status=status; self.reason=reason
@web.middleware
async def error_middleware(request,handler):
 try: return await handler(request)
 except HTTPError as e: return web.json_response({'error':e.reason},status=e.status)
 except web.HTTPException: raise
 except Exception as e:
  return web.json_response({'error':str(e)},status=500)
async def read_json(request):
 try:
  x=await request.json()
  return x if isinstance(x,dict) else {}
 except: return {}
def user_to_json(r):
 return {k:r[k] or '' for k in ('id','username','display_name','timezone','avatar_url','status_text','status_emoji')}
def require_user(request):
 h=request.headers.get('Authorization','')
 if h.startswith('Bearer '):
  t=h[7:]
 else:
  t=request.query.get('token','')
 if not t:
  raise HTTPError(401,'authentication required')
 r=request.app['db'].execute('SELECT u.* FROM tokens t JOIN users u ON u.id=t.user_id WHERE t.token=?',(t,)).fetchone()
 if not r:
  raise HTTPError(401,'invalid token')
 return r

def parse_limit(request):
 try: n=int(request.query.get('limit','50'))
 except: raise HTTPError(400,'invalid limit')
 if n<1 or n>200: raise HTTPError(400,'invalid limit')
 return n
def encode_cursor(n): return base64.urlsafe_b64encode(json.dumps({'k':n}).encode()).decode()
def decode_cursor(s):
 try:
  x=json.loads(base64.urlsafe_b64decode(s.encode())); n=x['k']
  if not isinstance(n,int): raise ValueError()
  return n
 except: raise HTTPError(400,'invalid cursor')
def emit_event(c,channel_id,kind,data):
 c.execute('BEGIN IMMEDIATE')
 try:
  c.execute('UPDATE channels SET last_event_id=last_event_id+1 WHERE id=?',(channel_id,))
  eid=c.execute('SELECT last_event_id FROM channels WHERE id=?',(channel_id,)).fetchone()[0]
  p={'type':kind,'event_id':eid,'channel_id':channel_id,**data}
  c.execute('INSERT INTO events(channel_id,event_id,payload) VALUES(?,?,?)',(channel_id,eid,json.dumps(p)))
  c.execute('COMMIT'); return eid
 except:
  c.execute('ROLLBACK'); raise
def broadcast_global(c,payload): c.execute('INSERT INTO broadcasts(payload) VALUES(?)',(json.dumps(payload),))
def channel_json(r):
 return {'id':r['id'],'workspace_id':r['workspace_id'],'name':r['name'],'is_private':bool(r['is_private']),'is_dm':bool(r['is_dm']),'topic':r['topic'] or '','is_archived':bool(r['is_archived']),'created_at':r['created_at']}
def message_json(c,r):
 u=c.execute('SELECT * FROM users WHERE id=?',(r['author_id'],)).fetchone()
 replies=c.execute('SELECT count(*) FROM messages WHERE parent_id=? AND deleted=0',(r['id'],)).fetchone()[0]
 return {'id':r['id'],'channel_id':r['channel_id'],'author_id':r['author_id'],'author':user_to_json(u),'body':r['body'],'parent_id':r['parent_id'],'reply_count':replies,'created_at':r['created_at'],'edited_at':r['edited_at'],'files':[],'reactions':[],'mentions':json.loads(r['mentions'] or '[]')}
