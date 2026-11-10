import json,base64,secrets,re
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
  return web.json_response({'error':'internal error'},status=500)

async def read_json(request):
 try:
  x=await request.json()
  return x if isinstance(x,dict) else {}
 except Exception: return {}

def require_user(request):
 h=request.headers.get('Authorization','')
 if not h.startswith('Bearer '): raise HTTPError(401,'authentication required')
 t=h[7:]
 r=db.CONN.execute('SELECT u.* FROM tokens t JOIN users u ON u.id=t.user_id WHERE t.token=?',(t,)).fetchone()
 if not r: raise HTTPError(401,'invalid token')
 return r

def user_to_json(r):
 return {k:r[k] for k in ('id','username','display_name','timezone','avatar_url','status_text','status_emoji')}

def parse_limit(request):
 try: n=int(request.query.get('limit','50'))
 except: raise HTTPError(400,'invalid limit')
 if not 1<=n<=200: raise HTTPError(400,'invalid limit')
 return n

def encode_cursor(n):
 return base64.urlsafe_b64encode(json.dumps({'k':n}).encode()).decode()
def decode_cursor(s):
 try:
  x=json.loads(base64.urlsafe_b64decode(s.encode()).decode())
  if not isinstance(x,dict) or type(x.get('k')) is not int: raise ValueError()
  return x['k']
 except: raise HTTPError(400,'invalid cursor')

def emit_event(channel_id,kind,data):
 c=db.CONN
 c.execute('BEGIN IMMEDIATE')
 try:
  c.execute('UPDATE channels SET last_event_id=last_event_id+1 WHERE id=?',(channel_id,))
  r=c.execute('SELECT last_event_id FROM channels WHERE id=?',(channel_id,)).fetchone()
  if not r: raise ValueError('channel')
  eid=r[0]; p={'type':kind,'event_id':eid,'channel_id':channel_id}; p.update(data)
  c.execute('INSERT INTO events(channel_id,event_id,payload) VALUES(?,?,?)',(channel_id,eid,json.dumps(p)))
  c.execute('COMMIT'); return eid
 except:
  c.execute('ROLLBACK'); raise

def broadcast_global(payload):
 db.CONN.execute('INSERT INTO broadcasts(payload) VALUES(?)',(json.dumps(payload),))

def channel_json(r):
 return {'id':r['id'],'workspace_id':r['workspace_id'],'name':r['name'],
  'is_private':bool(r['is_private']),'is_dm':bool(r['is_dm']),'topic':r['topic'],
  'is_archived':bool(r['is_archived']),'created_at':r['created_at']}

def message_json(r):
 u=db.CONN.execute('SELECT * FROM users WHERE id=?',(r['author_id'],)).fetchone()
 replies=db.CONN.execute('SELECT count(*) FROM messages WHERE parent_id=? AND deleted=0',(r['id'],)).fetchone()[0]
 rs=[]
 for x in db.CONN.execute('SELECT emoji,count(*) n FROM reactions WHERE message_id=? GROUP BY emoji',(r['id'],)):
  ids=[z[0] for z in db.CONN.execute('SELECT user_id FROM reactions WHERE message_id=? AND emoji=?',(r['id'],x['emoji']))]
  rs.append({'emoji':x['emoji'],'count':x['n'],'user_ids':ids})
 return {'id':r['id'],'channel_id':r['channel_id'],'author_id':r['author_id'],
  'author':user_to_json(u),'body':r['body'],'parent_id':r['parent_id'],'reply_count':replies,
  'created_at':r['created_at'],'edited_at':r['edited_at'],'files':[{'id':x['id'],'uploader_id':x['uploader_id'],'filename':x['filename'],'content_type':x['content_type'],'size':x['size'],'created_at':x['created_at']} for x in db.CONN.execute("SELECT f.id,f.uploader_id,f.filename,f.content_type,f.size,f.created_at FROM files f JOIN message_files mf ON mf.file_id=f.id WHERE mf.message_id=?",(r['id'],))],'reactions':rs,
  'mentions':json.loads(r['mentions'] or '[]')}
