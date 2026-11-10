import re,json
from aiohttp import web
import db
from common import *
from routes_workspaces import cjson
from routes_channels import access

def mjson(r):
 a=db.CONN.execute('SELECT * FROM users WHERE id=?',(r['author_id'],)).fetchone()
 replies=db.CONN.execute('SELECT count(*) n FROM messages WHERE parent_id=? AND deleted=0',(r['id'],)).fetchone()['n']
 rx=[]
 for x in db.CONN.execute('SELECT emoji,count(*) n FROM reactions WHERE message_id=? GROUP BY emoji',(r['id'],)):
  ids=[z['user_id'] for z in db.CONN.execute('SELECT user_id FROM reactions WHERE message_id=? AND emoji=?',(r['id'],x['emoji']))]
  rx.append({'emoji':x['emoji'],'count':x['n'],'user_ids':ids})
 return {'id':r['id'],'channel_id':r['channel_id'],'author_id':r['author_id'],'author':user_to_json(a),'body':r['body'],'parent_id':r['parent_id'],'reply_count':replies,'created_at':r['created_at'],'edited_at':r['edited_at'],'files':[],'reactions':rx,'mentions':json.loads(r['mentions'] or '[]')}
def setup(app):
 async def post(request):
  u=require_user(request)
  try: cid=int(request.match_info['id'])
  except: raise HTTPError(404,'not found')
  ch=db.CONN.execute('SELECT * FROM channels WHERE id=?',(cid,)).fetchone()
  if not ch: raise HTTPError(404,'not found')
  access(u,ch,True); b=await read_json(request); body=b.get('body')
  if not isinstance(body,str) or not body.strip(): raise HTTPError(400,'empty message')
  parent=b.get('parent_id')
  if parent is not None and not db.CONN.execute('SELECT 1 FROM messages WHERE id=? AND channel_id=? AND deleted=0',(parent,cid)).fetchone(): raise HTTPError(400,'invalid parent')
  mentions=[]
  if '@channel' in body:
   mentions=[x['user_id'] for x in db.CONN.execute('SELECT user_id FROM channel_members WHERE channel_id=? AND user_id!=?',(cid,u['id']))]
  for name in re.findall(r'(?<!\w)@([A-Za-z0-9_]+)',body):
   x=db.CONN.execute('SELECT id FROM users WHERE username=?',(name,)).fetchone()
   if x and x['id']!=u['id'] and db.CONN.execute('SELECT 1 FROM workspace_members WHERE workspace_id=? AND user_id=?',(ch['workspace_id'],x['id'])).fetchone() and x['id'] not in mentions: mentions.append(x['id'])
  now=db.now_iso(); db.CONN.execute('INSERT INTO messages(channel_id,author_id,body,parent_id,created_at,mentions) VALUES(?,?,?,?,?,?)',(cid,u['id'],body,parent,now,json.dumps(mentions)))
  mid=db.CONN.execute('SELECT last_insert_rowid()').fetchone()[0]; r=db.CONN.execute('SELECT * FROM messages WHERE id=?',(mid,)).fetchone()
  emit_event(cid,'message.reply' if parent else 'message.created',{'message':mjson(r)})
  return web.json_response({'message':mjson(r)},status=201)
 async def listing(request):
  u=require_user(request); cid=int(request.match_info['id']); ch=db.CONN.execute('SELECT * FROM channels WHERE id=?',(cid,)).fetchone()
  if not ch: raise HTTPError(404,'not found')
  access(u,ch); lim=parse_limit(request); cur=decode_cursor(request.query['cursor']) if request.query.get('cursor') else None
  q='SELECT * FROM messages WHERE channel_id=? AND parent_id IS NULL AND deleted=0'+(' AND id<?' if cur else '')+' ORDER BY id DESC LIMIT ?'
  rs=db.CONN.execute(q,(cid,cur,lim+1) if cur else (cid,lim+1)).fetchall(); more=len(rs)>lim; rs=rs[:lim]
  return web.json_response({'messages':[mjson(x) for x in rs],'next_cursor':encode_cursor(rs[-1]['id']) if more else None})
 async def replies(request):
  u=require_user(request); pid=int(request.match_info['id']); p=db.CONN.execute('SELECT * FROM messages WHERE id=?',(pid,)).fetchone()
  if not p: raise HTTPError(404,'not found')
  ch=db.CONN.execute('SELECT * FROM channels WHERE id=?',(p['channel_id'],)).fetchone(); access(u,ch); lim=parse_limit(request); cur=decode_cursor(request.query['cursor']) if request.query.get('cursor') else None
  q='SELECT * FROM messages WHERE parent_id=? AND deleted=0'+(' AND id>?' if cur else '')+' ORDER BY id ASC LIMIT ?'
  rs=db.CONN.execute(q,(pid,cur,lim+1) if cur else (pid,lim+1)).fetchall(); more=len(rs)>lim; rs=rs[:lim]
  return web.json_response({'replies':[mjson(x) for x in rs],'next_cursor':encode_cursor(rs[-1]['id']) if more else None})
 async def edit(request):
  u=require_user(request); mid=int(request.match_info['id']); r=db.CONN.execute('SELECT * FROM messages WHERE id=?',(mid,)).fetchone()
  if not r: raise HTTPError(404,'not found')
  if r['author_id']!=u['id']: raise HTTPError(403,'author required')
  if r['deleted']: raise HTTPError(409,'deleted')
  b=await read_json(request); body=b.get('body')
  if not isinstance(body,str) or not body.strip(): raise HTTPError(400,'empty message')
  db.CONN.execute('UPDATE messages SET body=?,edited_at=? WHERE id=?',(body,db.now_iso(),mid)); r=db.CONN.execute('SELECT * FROM messages WHERE id=?',(mid,)).fetchone(); emit_event(r['channel_id'],'message.updated',{'message':mjson(r)})
  return web.json_response({'message':mjson(r)})
 async def delete(request):
  u=require_user(request); r=db.CONN.execute('SELECT * FROM messages WHERE id=?',(int(request.match_info['id']),)).fetchone()
  if not r: raise HTTPError(404,'not found')
  w=db.CONN.execute('SELECT owner_id FROM workspaces WHERE id=(SELECT workspace_id FROM channels WHERE id=?)',(r['channel_id'],)).fetchone()
  if r['author_id']!=u['id'] and w['owner_id']!=u['id']: raise HTTPError(403,'forbidden')
  db.CONN.execute('UPDATE messages SET deleted=1 WHERE id=?',(r['id'],)); emit_event(r['channel_id'],'message.deleted',{'message_id':r['id']}); return web.json_response({'deleted':True})
 async def react(request):
  u=require_user(request); r=db.CONN.execute('SELECT * FROM messages WHERE id=?',(int(request.match_info['id']),)).fetchone()
  if not r: raise HTTPError(404,'not found')
  ch=db.CONN.execute('SELECT * FROM channels WHERE id=?',(r['channel_id'],)).fetchone(); access(u,ch); b=await read_json(request); emoji=b.get('emoji')
  if not isinstance(emoji,str) or not emoji: raise HTTPError(400,'invalid emoji')
  db.CONN.execute('INSERT OR IGNORE INTO reactions VALUES(?,?,?)',(r['id'],u['id'],emoji)); return web.json_response({'reactions':mjson(db.CONN.execute('SELECT * FROM messages WHERE id=?',(r['id'],)).fetchone())['reactions']})
 async def unreact(request):
  u=require_user(request); mid=int(request.match_info['id']); db.CONN.execute('DELETE FROM reactions WHERE message_id=? AND user_id=? AND emoji=?',(mid,u['id'],request.match_info['emoji'])); r=db.CONN.execute('SELECT * FROM messages WHERE id=?',(mid,)).fetchone(); return web.json_response({'reactions':mjson(r)['reactions']})
 app.router.add_post('/api/channels/{id}/messages',post); app.router.add_get('/api/channels/{id}/messages',listing)
 app.router.add_get('/api/messages/{id}/replies',replies); app.router.add_patch('/api/messages/{id}',edit); app.router.add_delete('/api/messages/{id}',delete)
 app.router.add_post('/api/messages/{id}/reactions',react); app.router.add_delete('/api/messages/{id}/reactions/{emoji}',unreact)
