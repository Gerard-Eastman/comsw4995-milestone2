from aiohttp import web
import json,re
import db
from common import HTTPError,read_json,require_user,parse_limit,decode_cursor,encode_cursor,message_json,emit_event
def setup(app):
 def access(u,c,write=False):
  if not db.CONN.execute('SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?',(c['id'],u['id'])).fetchone():
   if c['is_private'] or not db.CONN.execute('SELECT 1 FROM workspace_members WHERE workspace_id=? AND user_id=?',(c['workspace_id'],u['id'])).fetchone(): raise HTTPError(403,'not a channel member')
  if write and c['is_archived']: raise HTTPError(423,'channel archived')
 async def post(req):
  u=require_user(req); 
  try: cid=int(req.match_info['id'])
  except: raise HTTPError(404,'channel not found')
  c=db.CONN.execute('SELECT * FROM channels WHERE id=?',(cid,)).fetchone()
  if not c: raise HTTPError(404,'channel not found')
  access(u,c,False); b=await read_json(req); body=b.get('body')
  if not isinstance(body,str) or not body.strip(): raise HTTPError(400,'empty message')
  if body.startswith('/') and not body.startswith('//'):
   cmd,_,arg=body[1:].partition(' ')
   arg=arg.strip()
   if cmd=='me':
    if not arg: raise HTTPError(400,'/me requires text')
   elif cmd=='shrug':
    body=(arg+' ' if arg else '')+'¯\\_(ツ)_/¯'
   elif cmd=='topic':
    if len(arg)>250: raise HTTPError(400,'invalid topic')
    owner=db.CONN.execute('SELECT owner_id FROM workspaces WHERE id=?',(c['workspace_id'],)).fetchone()
    if not db.CONN.execute('SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?',(cid,u['id'])).fetchone() and (not owner or owner['owner_id']!=u['id']): raise HTTPError(403,'forbidden')
    db.CONN.execute('UPDATE channels SET topic=? WHERE id=?',(arg,cid)); c=db.CONN.execute('SELECT * FROM channels WHERE id=?',(cid,)).fetchone()
    emit_event(cid,'channel.updated',{'channel':__import__('common').channel_json(c)})
    return web.json_response({'message':None,'channel':__import__('common').channel_json(c)},status=201)
   elif cmd=='invite':
    if not arg.startswith('@'): raise HTTPError(400,'invalid invite')
    target=db.CONN.execute('SELECT * FROM users WHERE username=?',(arg[1:],)).fetchone()
    if not target: raise HTTPError(404,'user not found')
    if not db.CONN.execute('SELECT 1 FROM workspace_members WHERE workspace_id=? AND user_id=?',(c['workspace_id'],target['id'])).fetchone(): raise HTTPError(400,'user is not in workspace')
    db.CONN.execute('INSERT OR IGNORE INTO channel_members(channel_id,user_id) VALUES(?,?)',(cid,target['id']))
    return web.json_response({'message':None,'invited_user':__import__('common').user_to_json(target)},status=201)
   elif cmd in ('archive','unarchive'):
    owner=db.CONN.execute('SELECT owner_id FROM workspaces WHERE id=?',(c['workspace_id'],)).fetchone()
    if not owner or owner['owner_id']!=u['id']: raise HTTPError(403,'forbidden')
    on=cmd=='archive'; db.CONN.execute('UPDATE channels SET is_archived=? WHERE id=?',(int(on),cid))
    c=db.CONN.execute('SELECT * FROM channels WHERE id=?',(cid,)).fetchone()
    emit_event(cid,'channel.archived' if on else 'channel.unarchived',{})
    return web.json_response({'message':None,'channel':__import__('common').channel_json(c)},status=201)
   else: raise HTTPError(400,'unknown command')
  elif body.startswith('//'): body=body[1:]
  if not (body.startswith('/') and body[1:].startswith('unarchive')) and c['is_archived']: raise HTTPError(423,'channel archived')
  parent=b.get('parent_id'); mentions=[]
  if '@channel' in body:
   mentions += [z[0] for z in db.CONN.execute('SELECT user_id FROM channel_members WHERE channel_id=? AND user_id!=?',(cid,u['id']))]
  if '@here' in body:
   mentions += [z[0] for z in db.CONN.execute('SELECT DISTINCT user_id FROM ws_presence WHERE user_id!=?',(u['id'],))]
  for name in re.findall(r'(?<![\w@])@([A-Za-z0-9_]+)',body):
   x=db.CONN.execute('SELECT id FROM users WHERE username=?',(name,)).fetchone()
   if x and x['id']!=u['id'] and db.CONN.execute('SELECT 1 FROM workspace_members WHERE workspace_id=? AND user_id=?',(c['workspace_id'],x['id'])).fetchone(): mentions.append(x['id'])
  if c['is_archived']: raise HTTPError(423,'channel archived')
  mentions=list(dict.fromkeys(mentions))
  file_ids=b.get('file_ids',[])
  if file_ids is None: file_ids=[]
  if not isinstance(file_ids,list) or any(isinstance(x,bool) or not isinstance(x,int) for x in file_ids): raise HTTPError(400,'invalid files')
  for fid in file_ids:
   f=db.CONN.execute('SELECT uploader_id FROM files WHERE id=?',(fid,)).fetchone()
   if not f or f['uploader_id']!=u['id'] or db.CONN.execute('SELECT 1 FROM message_files WHERE file_id=?',(fid,)).fetchone(): raise HTTPError(400,'invalid file')
  now=db.now_iso()
  mid=db.CONN.execute('INSERT INTO messages(channel_id,author_id,body,parent_id,created_at,mentions) VALUES(?,?,?,?,?,?)',(cid,u['id'],body,parent,now,json.dumps(mentions))).lastrowid
  for fid in file_ids: db.CONN.execute('INSERT INTO message_files(message_id,file_id) VALUES(?,?)',(mid,fid))
  r=db.CONN.execute('SELECT * FROM messages WHERE id=?',(mid,)).fetchone(); obj=message_json(r)
  emit_event(cid,'message.reply' if parent else 'message.created',{'message':obj})
  return web.json_response({'message':obj},status=201)
 async def listing(req):
  u=require_user(req); c=db.CONN.execute('SELECT * FROM channels WHERE id=?',(req.match_info['id'],)).fetchone()
  if not c: raise HTTPError(404,'channel not found')
  access(u,c); n=parse_limit(req); cur=decode_cursor(req.query['cursor']) if req.query.get('cursor') else None
  q='SELECT * FROM messages WHERE channel_id=? AND parent_id IS NULL AND deleted=0 '+('AND id<? ' if cur else '')+'ORDER BY id DESC LIMIT ?'
  rows=db.CONN.execute(q,(c['id'],cur,n+1) if cur else (c['id'],n+1)).fetchall(); more=len(rows)>n; rows=rows[:n]
  return web.json_response({'messages':[message_json(x) for x in rows],'next_cursor':encode_cursor(rows[-1]['id']) if more else None})
 async def replies(req):
  u=require_user(req); r=db.CONN.execute('SELECT * FROM messages WHERE id=?',(req.match_info['id'],)).fetchone()
  if not r: raise HTTPError(404,'message not found')
  c=db.CONN.execute('SELECT * FROM channels WHERE id=?',(r['channel_id'],)).fetchone(); access(u,c); n=parse_limit(req); cur=decode_cursor(req.query['cursor']) if req.query.get('cursor') else None
  q='SELECT * FROM messages WHERE parent_id=? AND deleted=0 '+('AND id>? ' if cur else '')+'ORDER BY id ASC LIMIT ?'
  rows=db.CONN.execute(q,(r['id'],cur,n+1) if cur else (r['id'],n+1)).fetchall(); more=len(rows)>n; rows=rows[:n]
  return web.json_response({'replies':[message_json(x) for x in rows],'next_cursor':encode_cursor(rows[-1]['id']) if more else None})
 async def edit(req):
  u=require_user(req); r=db.CONN.execute('SELECT * FROM messages WHERE id=?',(req.match_info['id'],)).fetchone()
  if not r: raise HTTPError(404,'message not found')
  if r['author_id']!=u['id']: raise HTTPError(403,'forbidden')
  if r['deleted']: raise HTTPError(409,'message deleted')
  if db.CONN.execute('SELECT is_archived FROM channels WHERE id=?',(r['channel_id'],)).fetchone()['is_archived']: raise HTTPError(423,'channel archived')
  b=await read_json(req); body=b.get('body')
  if not isinstance(body,str) or not body.strip(): raise HTTPError(400,'empty message')
  db.CONN.execute('UPDATE messages SET body=?,edited_at=? WHERE id=?',(body,db.now_iso(),r['id'])); r=db.CONN.execute('SELECT * FROM messages WHERE id=?',(r['id'],)).fetchone(); obj=message_json(r)
  emit_event(r['channel_id'],'message.updated',{'message':obj}); return web.json_response({'message':obj})
 async def delete(req):
  u=require_user(req); r=db.CONN.execute('SELECT * FROM messages WHERE id=?',(req.match_info['id'],)).fetchone()
  if not r: raise HTTPError(404,'message not found')
  if r['deleted']: return web.json_response({'deleted':True})
  owner=db.CONN.execute('SELECT owner_id FROM workspaces WHERE id=(SELECT workspace_id FROM channels WHERE id=?)',(r['channel_id'],)).fetchone()
  if r['author_id']!=u['id'] and (not owner or owner['owner_id']!=u['id']): raise HTTPError(403,'forbidden')
  db.CONN.execute('UPDATE messages SET deleted=1 WHERE id=?',(r['id'],)); emit_event(r['channel_id'],'message.deleted',{'message_id':r['id']}); return web.json_response({'deleted':True})
 app.router.add_post('/api/channels/{id}/messages',post);app.router.add_get('/api/channels/{id}/messages',listing)
 app.router.add_get('/api/messages/{id}/replies',replies);app.router.add_patch('/api/messages/{id}',edit);app.router.add_delete('/api/messages/{id}',delete)
