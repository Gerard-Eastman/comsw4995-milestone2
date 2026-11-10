from aiohttp import web
import json,re
import db
from common import HTTPError,read_json,require_user,parse_limit,decode_cursor,encode_cursor,message_json,user_to_json,emit_event

def setup(app):
 async def upload(req):
  u=require_user(req)
  try: reader=await req.multipart()
  except Exception: raise HTTPError(400,'multipart required')
  part=None
  async for x in reader:
   if x.name=='file': part=x; break
  if not part: raise HTTPError(400,'file required')
  data=await part.read()
  if len(data)>10*1024*1024: raise HTTPError(413,'file too large')
  name=part.filename or 'file'; typ=part.headers.get('Content-Type','application/octet-stream'); now=db.now_iso()
  fid=db.CONN.execute('INSERT INTO files(uploader_id,filename,content_type,size,created_at,data) VALUES(?,?,?,?,?,?)',(u['id'],name,typ,len(data),now,data)).lastrowid
  return web.json_response({'file':{'id':fid,'uploader_id':u['id'],'filename':name,'content_type':typ,'size':len(data),'created_at':now}},status=201)
 async def file_meta(req):
  require_user(req); f=db.CONN.execute('SELECT * FROM files WHERE id=?',(req.match_info['id'],)).fetchone()
  if not f: raise HTTPError(404,'file not found')
  return web.json_response({'file':{k:f[k] for k in ('id','uploader_id','filename','content_type','size','created_at')}})
 async def download(req):
  require_user(req); f=db.CONN.execute('SELECT * FROM files WHERE id=?',(req.match_info['id'],)).fetchone()
  if not f: raise HTTPError(404,'file not found')
  return web.Response(body=f['data'],content_type=f['content_type'],headers={'Content-Disposition':'attachment; filename="'+f['filename']+'"'})
 async def group_create(req):
  u=require_user(req); w=db.CONN.execute('SELECT * FROM workspaces WHERE slug=?',(req.match_info['slug'],)).fetchone()
  if not w: raise HTTPError(404,'workspace not found')
  if not db.CONN.execute('SELECT 1 FROM workspace_members WHERE workspace_id=? AND user_id=?',(w['id'],u['id'])).fetchone(): raise HTTPError(403,'forbidden')
  b=await read_json(req); h=b.get('handle',''); name=b.get('name',''); ids=b.get('user_ids',[])
  if not isinstance(h,str) or not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,31}',h) or h in ('here','channel','everyone') or not isinstance(name,str) or not name or not isinstance(ids,list): raise HTTPError(400,'invalid group')
  if db.CONN.execute('SELECT 1 FROM groups_tbl WHERE workspace_id=? AND handle=?',(w['id'],h)).fetchone(): raise HTTPError(409,'group exists')
  now=db.CONN.execute('INSERT INTO groups_tbl(workspace_id,handle,name,creator_id) VALUES(?,?,?,?)',(w['id'],h,name,u['id'])).lastrowid
  for x in ids:
   if not db.CONN.execute('SELECT 1 FROM workspace_members WHERE workspace_id=? AND user_id=?',(w['id'],x)).fetchone(): raise HTTPError(400,'invalid member')
   db.CONN.execute('INSERT OR IGNORE INTO group_members VALUES(?,?)',(now,x))
  return web.json_response({'group':{'id':now,'handle':h,'name':name,'member_user_ids':ids}},status=201)
 async def group_list(req):
  u=require_user(req); w=db.CONN.execute('SELECT * FROM workspaces WHERE slug=?',(req.match_info['slug'],)).fetchone()
  if not w: raise HTTPError(404,'workspace not found')
  if not db.CONN.execute('SELECT 1 FROM workspace_members WHERE workspace_id=? AND user_id=?',(w['id'],u['id'])).fetchone(): raise HTTPError(403,'forbidden')
  out=[]
  for g in db.CONN.execute('SELECT * FROM groups_tbl WHERE workspace_id=?',(w['id'],)):
   out.append({'id':g['id'],'handle':g['handle'],'name':g['name'],'member_user_ids':[z[0] for z in db.CONN.execute('SELECT user_id FROM group_members WHERE group_id=?',(g['id'],))]})
  return web.json_response({'groups':out})
 async def group_patch(req):
  u=require_user(req); w=db.CONN.execute('SELECT * FROM workspaces WHERE slug=?',(req.match_info['slug'],)).fetchone(); g=db.CONN.execute('SELECT * FROM groups_tbl WHERE workspace_id=? AND handle=?',(w['id'],req.match_info['handle'])).fetchone() if w else None
  if not g: raise HTTPError(404,'group not found')
  if g['creator_id']!=u['id'] and db.CONN.execute('SELECT owner_id FROM workspaces WHERE id=?',(w['id'],)).fetchone()['owner_id']!=u['id']: raise HTTPError(403,'forbidden')
  b=await read_json(req); name=b.get('name',g['name']); ids=b.get('user_ids',[])
  db.CONN.execute('UPDATE groups_tbl SET name=? WHERE id=?',(name,g['id'])); db.CONN.execute('DELETE FROM group_members WHERE group_id=?',(g['id'],))
  for x in ids: db.CONN.execute('INSERT OR IGNORE INTO group_members VALUES(?,?)',(g['id'],x))
  return web.json_response({'group':{'id':g['id'],'handle':g['handle'],'name':name,'member_user_ids':ids}})
 async def group_delete(req):
  u=require_user(req); w=db.CONN.execute('SELECT * FROM workspaces WHERE slug=?',(req.match_info['slug'],)).fetchone(); g=db.CONN.execute('SELECT * FROM groups_tbl WHERE workspace_id=? AND handle=?',(w['id'],req.match_info['handle'])).fetchone() if w else None
  if not g: return web.json_response({'deleted':True})
  if g['creator_id']!=u['id'] and w['owner_id']!=u['id']: raise HTTPError(403,'forbidden')
  db.CONN.execute('DELETE FROM groups_tbl WHERE id=?',(g['id'],)); db.CONN.execute('DELETE FROM group_members WHERE group_id=?',(g['id'],))
  return web.json_response({'deleted':True})
 async def dms(req):
  u=require_user(req); b=await read_json(req); target=b.get('user_id')
  if isinstance(target,bool) or not isinstance(target,int): raise HTTPError(400,'invalid user_id')
  if not db.CONN.execute('SELECT 1 FROM users WHERE id=?',(target,)).fetchone(): raise HTTPError(404,'user not found')
  if target==u['id']: raise HTTPError(400,'invalid user_id')
  shared=db.CONN.execute('SELECT workspace_id FROM workspace_members WHERE user_id=? LIMIT 1',(u['id'],)).fetchone()
  wid=shared['workspace_id'] if shared else 0
  old=db.CONN.execute('SELECT c.id FROM channels c JOIN channel_members a ON a.channel_id=c.id JOIN channel_members b ON b.channel_id=c.id WHERE c.workspace_id=? AND c.is_dm=1 AND a.user_id=? AND b.user_id=? LIMIT 1',(wid,u['id'],target)).fetchone()
  if old: return web.json_response({'channel_id':old['id']})
  now=db.now_iso(); cid=db.CONN.execute('INSERT INTO channels(workspace_id,name,is_dm,created_at) VALUES(?,?,1,?)',(wid,'dm-'+str(u['id'])+'-'+str(target),now)).lastrowid
  db.CONN.execute('INSERT INTO channel_members VALUES(?,?)',(cid,u['id'])); db.CONN.execute('INSERT INTO channel_members VALUES(?,?)',(cid,target))
  return web.json_response({'channel_id':cid})
 def msg(req):
  try: i=int(req.match_info['id'])
  except: raise HTTPError(404,'message not found')
  r=db.CONN.execute('SELECT * FROM messages WHERE id=? AND deleted=0',(i,)).fetchone()
  if not r: raise HTTPError(404,'message not found')
  c=db.CONN.execute('SELECT * FROM channels WHERE id=?',(r['channel_id'],)).fetchone()
  return r,c
 def access(u,c):
  if c['is_private'] and not db.CONN.execute('SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?',(c['id'],u['id'])).fetchone(): raise HTTPError(403,'forbidden')
  if not c['is_private'] and not db.CONN.execute('SELECT 1 FROM workspace_members WHERE workspace_id=? AND user_id=?',(c['workspace_id'],u['id'])).fetchone(): raise HTTPError(403,'forbidden')
 app.router.add_post('/api/dms',dms)
 app.router.add_post('/api/workspaces/{slug}/groups',group_create);app.router.add_get('/api/workspaces/{slug}/groups',group_list)
 app.router.add_patch('/api/workspaces/{slug}/groups/{handle}',group_patch);app.router.add_delete('/api/workspaces/{slug}/groups/{handle}',group_delete)
 app.router.add_post('/api/files',upload); app.router.add_get('/api/files/{id}',file_meta); app.router.add_get('/api/files/{id}/download',download)
 async def react(req):
  u=require_user(req); r,c=msg(req); access(u,c)
  if c['is_archived']: raise HTTPError(423,'channel archived')
  b=await read_json(req); e=b.get('emoji')
  if not isinstance(e,str) or not e or len(e)>32: raise HTTPError(400,'invalid emoji')
  db.CONN.execute('INSERT OR IGNORE INTO reactions VALUES(?,?,?)',(r['id'],u['id'],e))
  if db.CONN.execute('SELECT changes()').fetchone()[0]: emit_event(c['id'],'reaction.added',{'message_id':r['id'],'emoji':e,'user_id':u['id'],'reactions':message_json(r)['reactions']})
  return web.json_response({'reactions':message_json(r)['reactions']})
 async def unreact(req):
  u=require_user(req); r,c=msg(req); access(u,c)
  if c['is_archived']: raise HTTPError(423,'channel archived')
  e=req.match_info['emoji']; db.CONN.execute('DELETE FROM reactions WHERE message_id=? AND user_id=? AND emoji=?',(r['id'],u['id'],e))
  if db.CONN.execute('SELECT changes()').fetchone()[0]: emit_event(c['id'],'reaction.removed',{'message_id':r['id'],'emoji':e,'user_id':u['id'],'reactions':message_json(r)['reactions']})
  return web.json_response({'reactions':message_json(r)['reactions']})
 async def pin(req):
  u=require_user(req); r,c=msg(req); access(u,c)
  if c['is_archived']: raise HTTPError(423,'channel archived')
  now=db.now_iso(); db.CONN.execute('INSERT OR IGNORE INTO pins VALUES(?,?,?)',(r['id'],u['id'],now))
  x=db.CONN.execute('SELECT * FROM pins WHERE message_id=?',(r['id'],)).fetchone()
  return web.json_response({'pin':{'message_id':r['id'],'pinned_by':x['pinned_by'],'pinned_at':x['pinned_at']}})
 async def unpin(req):
  u=require_user(req); r,c=msg(req); access(u,c); db.CONN.execute('DELETE FROM pins WHERE message_id=?',(r['id'],))
  return web.json_response({'unpinned':True})
 async def pins(req):
  u=require_user(req); cid=int(req.match_info['id']); c=db.CONN.execute('SELECT * FROM channels WHERE id=?',(cid,)).fetchone()
  if not c: raise HTTPError(404,'channel not found')
  access(u,c); n=parse_limit(req); cur=decode_cursor(req.query['cursor']) if req.query.get('cursor') else None
  q='SELECT p.*,m.* FROM pins p JOIN messages m ON m.id=p.message_id WHERE m.channel_id=? '+('AND p.message_id<? ' if cur else '')+'ORDER BY p.message_id DESC LIMIT ?'
  rows=db.CONN.execute(q,(cid,cur,n+1) if cur else (cid,n+1)).fetchall(); more=len(rows)>n; rows=rows[:n]
  return web.json_response({'pins':[{'message':message_json(x),'pinned_by':x['pinned_by'],'pinned_at':x['pinned_at']} for x in rows],'next_cursor':encode_cursor(rows[-1]['message_id']) if more else None})
 async def search(req):
  u=require_user(req); q=req.query.get('q','')
  if not q: raise HTTPError(400,'missing query')
  n=parse_limit(req); cur=decode_cursor(req.query['cursor']) if req.query.get('cursor') else None
  sql='SELECT m.* FROM messages m JOIN channels c ON c.id=m.channel_id WHERE m.deleted=0 AND m.body LIKE ? AND (c.is_private=0 OR EXISTS(SELECT 1 FROM channel_members x WHERE x.channel_id=c.id AND x.user_id=?)) '
  args=['%'+q+'%',u['id']]
  if req.query.get('workspace_id'):
   sql+='AND c.workspace_id=? '; args.append(int(req.query['workspace_id']))
  if cur: sql+='AND m.id<? '; args.append(cur)
  sql+='ORDER BY m.id DESC LIMIT ?'; args.append(n+1)
  rows=db.CONN.execute(sql,args).fetchall(); more=len(rows)>n; rows=rows[:n]
  return web.json_response({'results':[message_json(x) for x in rows],'next_cursor':encode_cursor(rows[-1]['id']) if more else None})
 async def read(req):
  u=require_user(req); cid=int(req.match_info['id']); c=db.CONN.execute('SELECT * FROM channels WHERE id=?',(cid,)).fetchone()
  if not c: raise HTTPError(404,'channel not found')
  access(u,c); x=db.CONN.execute('SELECT last_read_event_id FROM read_state WHERE user_id=? AND channel_id=?',(u['id'],cid)).fetchone(); last=x[0] if x else 0
  unread=db.CONN.execute('SELECT count(*) FROM events e JOIN messages m ON json_extract(e.payload,"$.message.id")=m.id WHERE e.channel_id=? AND e.event_id>? AND m.author_id!=?',(cid,last,u['id'])).fetchone()[0]
  mention=db.CONN.execute('SELECT count(*) FROM events e JOIN messages m ON json_extract(e.payload,"$.message.id")=m.id WHERE e.channel_id=? AND e.event_id>? AND m.author_id!=? AND m.mentions LIKE ?', (cid,last,u['id'],'%'+str(u['id'])+'%')).fetchone()[0]
  return web.json_response({'read_state':{'channel_id':cid,'last_read_event_id':last,'unread_count':unread,'mention_count':mention}})
 async def mark(req):
  u=require_user(req); cid=int(req.match_info['id']); c=db.CONN.execute('SELECT * FROM channels WHERE id=?',(cid,)).fetchone(); access(u,c)
  b=await read_json(req); x=int(b.get('last_read_event_id',0)); old=db.CONN.execute('SELECT last_read_event_id FROM read_state WHERE user_id=? AND channel_id=?',(u['id'],cid)).fetchone()
  x=max(x,old[0] if old else 0); db.CONN.execute('INSERT OR REPLACE INTO read_state VALUES(?,?,?)',(u['id'],cid,x))
  return await read(req)
 for method,path,fn in [('POST','/api/messages/{id}/reactions',react),('DELETE','/api/messages/{id}/reactions/{emoji}',unreact),('POST','/api/messages/{id}/pin',pin),('DELETE','/api/messages/{id}/pin',unpin),('GET','/api/channels/{id}/pins',pins),('GET','/api/search',search),('GET','/api/channels/{id}/read',read),('POST','/api/channels/{id}/read',mark)]: app.router.add_route(method,path,fn)
