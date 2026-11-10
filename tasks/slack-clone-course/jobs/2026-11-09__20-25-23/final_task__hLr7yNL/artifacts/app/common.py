import json,base64,secrets,re
from aiohttp import web
from db import connect,now_iso
class HTTPError(Exception):
 def __init__(self,status,reason): self.status=status; self.reason=reason
@web.middleware
async def error_middleware(request,handler):
 try: return await handler(request)
 except HTTPError as e: return web.json_response({'error':e.reason},status=e.status)
 except web.HTTPException: raise
 except Exception as e: return web.json_response({'error':'internal error'},status=500)
async def read_json(r):
 try:
  x=await r.json()
  return x if isinstance(x,dict) else {}
 except: return {}
def user_to_json(x):
 return {k:x[k] for k in ('id','username','display_name','timezone','avatar_url','status_text','status_emoji')}
async def require_user(r):
 t=r.headers.get('Authorization','')
 if t.startswith('Bearer '): t=t[7:]
 else: t=r.query.get('token','')
 if not t: raise HTTPError(401,'unauthorized')
 c=connect(); x=c.execute('SELECT u.* FROM tokens t JOIN users u ON u.id=t.user_id WHERE t.token=?',(t,)).fetchone(); c.close()
 if not x: raise HTTPError(401,'unauthorized')
 return x
def parse_limit(r):
 try: n=int(r.query.get('limit','50'))
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
def emit_event(cid,kind,data):
 c=connect()
 try:
  c.execute('BEGIN IMMEDIATE'); c.execute('UPDATE channels SET last_event_id=last_event_id+1 WHERE id=?',(cid,))
  n=c.execute('SELECT last_event_id FROM channels WHERE id=?',(cid,)).fetchone()[0]
  p={'type':kind,'event_id':n,'channel_id':cid,**data}
  c.execute('INSERT INTO events(channel_id,event_id,payload) VALUES(?,?,?)',(cid,n,json.dumps(p))); c.execute('COMMIT'); return n
 except:
  c.execute('ROLLBACK'); raise
 finally: c.close()
def broadcast_global(p):
 c=connect(); c.execute('INSERT INTO broadcasts(payload) VALUES(?)',(json.dumps(p),)); c.close()
def channel_json(x):
 return {'id':x['id'],'workspace_id':x['workspace_id'],'name':x['name'],'is_private':bool(x['is_private']),'is_dm':bool(x['is_dm']),'topic':x['topic'] or '','is_archived':bool(x['is_archived']),'created_at':x['created_at']}
def msg_json(c,x):
 a=c.execute('SELECT * FROM users WHERE id=?',(x['author_id'],)).fetchone()
 replies=c.execute('SELECT count(*) FROM messages WHERE parent_id=? AND deleted=0',(x['id'],)).fetchone()[0]
 rs=[]
 for e in c.execute('SELECT emoji,count(*) n FROM reactions WHERE message_id=? GROUP BY emoji',(x['id'],)):
  ids=[z[0] for z in c.execute('SELECT user_id FROM reactions WHERE message_id=? AND emoji=?',(x['id'],e['emoji']))]
  rs.append({'emoji':e['emoji'],'count':e['n'],'user_ids':ids})
 return {'id':x['id'],'channel_id':x['channel_id'],'author_id':x['author_id'],'author':user_to_json(a),'body':x['body'],'parent_id':x['parent_id'],'reply_count':replies,'created_at':x['created_at'],'edited_at':x['edited_at'],'files':[{'id':f['id'],'uploader_id':f['uploader_id'],'filename':f['filename'],'content_type':f['content_type'],'size':f['size'],'created_at':f['created_at']} for f in c.execute('SELECT * FROM files WHERE message_id=? ORDER BY id',(x['id'],))],'reactions':rs,'mentions':json.loads(x['mentions'] or '[]')}
