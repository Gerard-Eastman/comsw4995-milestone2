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
 except Exception as e:
  return web.json_response({'error':'internal error'},status=500)
async def read_json(request):
 try:
  x=await request.json(); return x if isinstance(x,dict) else {}
 except: return {}
def require_user(request):
 t=request.headers.get('Authorization','')
 if t.startswith('Bearer '): t=t[7:]
 if not t: raise HTTPError(401,'authentication required')
 c=connect(); r=c.execute('SELECT u.* FROM tokens t JOIN users u ON u.id=t.user_id WHERE t.token=?',(t,)).fetchone(); c.close()
 if not r: raise HTTPError(401,'invalid token')
 request['user']=r; return r
def user_to_json(r):
 return {k:r[k] for k in ('id','username','display_name','timezone','avatar_url','status_text','status_emoji')}
def parse_limit(q):
 try: n=int(q.get('limit','50'))
 except: raise HTTPError(400,'invalid limit')
 if n<1 or n>200: raise HTTPError(400,'invalid limit')
 return n
def encode_cursor(n): return base64.urlsafe_b64encode(json.dumps({'k':n}).encode()).decode()
def decode_cursor(s):
 try:
  x=json.loads(base64.urlsafe_b64decode(s.encode()).decode()); n=x['k']
  if type(n) is not int: raise ValueError()
  return n
 except: raise HTTPError(400,'invalid cursor')
def emit_event(cid,kind,data):
 c=connect()
 try:
  c.execute('BEGIN IMMEDIATE'); c.execute('UPDATE channels SET last_event_id=last_event_id+1 WHERE id=?',(cid,))
  n=c.execute('SELECT last_event_id FROM channels WHERE id=?',(cid,)).fetchone()[0]
  p={'type':kind,'event_id':n,'channel_id':cid}; p.update(data)
  c.execute('INSERT INTO events(channel_id,event_id,payload) VALUES(?,?,?)',(cid,n,json.dumps(p))); c.execute('COMMIT'); return n
 except:
  c.execute('ROLLBACK'); raise
 finally: c.close()
def broadcast_global(p):
 c=connect(); c.execute('INSERT INTO broadcasts(payload) VALUES(?)',(json.dumps(p),)); c.close()
def channel_json(r):
 return {'id':r['id'],'workspace_id':r['workspace_id'],'name':r['name'],'is_private':bool(r['is_private']),'is_dm':bool(r['is_dm']),'topic':r['topic'] or '','is_archived':bool(r['is_archived']),'created_at':r['created_at']}
def msg_json(c,r):
 u=c.execute('SELECT * FROM users WHERE id=?',(r['author_id'],)).fetchone()
 reps=[]
 for x in c.execute('SELECT emoji,COUNT(*) n FROM reactions WHERE message_id=? GROUP BY emoji',(r['id'],)):
  reps.append({'emoji':x['emoji'],'count':x['n'],'user_ids':[z[0] for z in c.execute('SELECT user_id FROM reactions WHERE message_id=? AND emoji=?',(r['id'],x['emoji']))]})
 return {'id':r['id'],'channel_id':r['channel_id'],'author_id':r['author_id'],'author':user_to_json(u),'body':r['body'],'parent_id':r['parent_id'],'reply_count':c.execute('SELECT COUNT(*) FROM messages WHERE parent_id=? AND deleted=0',(r['id'],)).fetchone()[0],'created_at':r['created_at'],'edited_at':r['edited_at'],'files':[{'id':f['id'],'uploader_id':f['uploader_id'],'filename':f['filename'],'content_type':f['content_type'],'size':f['size'],'created_at':f['created_at']} for f in c.execute('SELECT * FROM files WHERE message_id=? ORDER BY id',(r['id'],)).fetchall()],'reactions':reps,'mentions':json.loads(r['mentions'] or '[]')}
