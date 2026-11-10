from aiohttp import web
import db,json,re
from common import *
from routes_channels import channel_by_id,is_channel_member,can_read_channel
from routes_workspaces import role_of,add_workspace_member
def message_by_id(i):
 try: i=int(i)
 except: raise HTTPError(404,'message not found')
 r=db.conn.execute('SELECT * FROM messages WHERE id=? AND deleted=0',(i,)).fetchone()
 if not r: raise HTTPError(404,'message not found')
 return r
MENTION_RE=re.compile(r"(?<![A-Za-z0-9_@.])@([A-Za-z0-9_](?:[A-Za-z0-9_-]*[A-Za-z0-9_])?)(?![A-Za-z0-9_@-])(?!\.[A-Za-z0-9])")
def resolve_mentions(body,channel,author_id):
 out=[]
 for name in MENTION_RE.findall(body):
  ids=[]
  if name=='channel': ids=[x['user_id'] for x in db.conn.execute('SELECT user_id FROM channel_members WHERE channel_id=?',(channel['id'],))]
  elif name=='here': ids=[x['user_id'] for x in db.conn.execute('SELECT user_id FROM channel_members WHERE channel_id=? AND user_id IN (SELECT user_id FROM ws_presence)',(channel['id'],))]
  else:
   r=db.conn.execute('SELECT id FROM users WHERE username=?',(name,)).fetchone()
   if r and db.conn.execute('SELECT 1 FROM workspace_members WHERE workspace_id=? AND user_id=?',(channel['workspace_id'],r['id'])).fetchone(): ids=[r['id']]
   else:
    g=db.conn.execute('SELECT id FROM groups_tbl WHERE workspace_id=? AND handle=?',(channel['workspace_id'],name)).fetchone()
    if g: ids=[x['user_id'] for x in db.conn.execute('SELECT user_id FROM group_members WHERE group_id=? AND user_id IN (SELECT user_id FROM channel_members WHERE channel_id=?)',(g['id'],channel['id']))]
  for i in ids:
   if i!=author_id and i not in out: out.append(i)
 return out
def files_for(mid):
 return [ {'id':x['id'],'uploader_id':x['uploader_id'],'filename':x['filename'],'content_type':x['content_type'],'size':x['size'],'created_at':x['created_at']} for x in db.conn.execute('SELECT * FROM files WHERE message_id=? ORDER BY id',(mid,)) ]
def message_to_json(r):
 a=db.conn.execute('SELECT * FROM users WHERE id=?',(r['author_id'],)).fetchone()
 n=db.conn.execute('SELECT count(*) n FROM messages WHERE parent_id=? AND deleted=0',(r['id'],)).fetchone()['n']
 rs=[]
 for x in db.conn.execute('SELECT emoji,count(*) n FROM reactions WHERE message_id=? GROUP BY emoji',(r['id'],)):
  ids=[z['user_id'] for z in db.conn.execute('SELECT user_id FROM reactions WHERE message_id=? AND emoji=?',(r['id'],x['emoji']))]
  rs.append({'emoji':x['emoji'],'count':x['n'],'user_ids':ids})
 return {'id':r['id'],'channel_id':r['channel_id'],'author_id':r['author_id'],'author':user_to_json(a),'body':r['body'],'parent_id':r['parent_id'],'reply_count':n,'created_at':r['created_at'],'edited_at':r['edited_at'],'files':files_for(r['id']),'reactions':rs,'mentions':json.loads(r['mentions'] or '[]')}
msg_json=message_to_json
def setup(app):
 async def post(q):
  u=require_user(q); c=channel_by_id(q.match_info['id'])
  if not is_channel_member(c['id'],u): raise HTTPError(403,'membership')
  x=await read_json(q); body=x.get('body')
  if c['is_archived'] and not (isinstance(body,str) and body.startswith('/unarchive')): raise HTTPError(423,'archived')
  if not isinstance(body,str) or not body.strip(): raise HTTPError(400,'empty')
  if body.startswith('/') and not body.startswith('//'):
   parts=body.split(' ',1); cmd=parts[0][1:]; arg=parts[1] if len(parts)>1 else ''
   if cmd=='me':
    if not arg.strip(): raise HTTPError(400,'/me requires text')
   elif cmd=='shrug':
    body=(arg+' ' if arg else '')+'¯\\_(ツ)_/¯'
   elif cmd in ('topic','invite','archive','unarchive'):
    w=db.conn.execute('SELECT * FROM workspaces WHERE id=?',(c['workspace_id'],)).fetchone()
    if cmd=='topic':
     if len(arg)>250: raise HTTPError(400,'topic too long')
     if w['owner_id']!=u and not is_channel_member(c['id'],u): raise HTTPError(403,'forbidden')
     db.conn.execute('UPDATE channels SET topic=? WHERE id=?',(arg,c['id']))
     c=channel_by_id(c['id']); emit_event(c['id'],'channel.updated',{'channel':__import__('routes_channels').channel_to_json(c)})
     return web.json_response({'message':None,'channel':__import__('routes_channels').channel_to_json(c)},status=201)
    if cmd in ('archive','unarchive'):
     if w['owner_id']!=u: raise HTTPError(403,'forbidden')
     flag=cmd=='archive'; db.conn.execute('UPDATE channels SET is_archived=? WHERE id=?',(int(flag),c['id']))
     c=channel_by_id(c['id']); emit_event(c['id'],'channel.archived' if flag else 'channel.unarchived',{'channel':__import__('routes_channels').channel_to_json(c)})
     return web.json_response({'message':None,'channel':__import__('routes_channels').channel_to_json(c)},status=201)
    if not arg.startswith('@'): raise HTTPError(400,'invalid invite')
    ur=db.conn.execute('SELECT * FROM users WHERE username=?',(arg[1:].strip(),)).fetchone()
    if not ur: raise HTTPError(404,'unknown user')
    if role_of(w['id'],u) not in ('owner','admin'): raise HTTPError(403,'forbidden')
    if not role_of(w['id'],ur['id']): raise HTTPError(400,'user outside workspace')
    db.conn.execute('INSERT OR IGNORE INTO workspace_members VALUES(?,?,?,?)',(w['id'],ur['id'],'member',db.now_iso()))
    db.conn.execute('INSERT OR IGNORE INTO channel_members VALUES(?,?,?)',(c['id'],ur['id'],0))
    return web.json_response({'message':None,'invited_user':user_to_json(ur)},status=201)
   else: raise HTTPError(400,'unknown command')
  if body.startswith('//'): body=body[1:]
  parent=x.get('parent_id')
  if parent is not None:
   p=message_by_id(parent)
   if p['channel_id']!=c['id']: raise HTTPError(400,'invalid parent')
  t=db.now_iso()
  fids=x.get('file_ids',[])
  if not isinstance(fids,list) or any(not isinstance(z,int) for z in fids): raise HTTPError(400,'invalid files')
  if len(set(fids))!=len(fids): raise HTTPError(400,'invalid files')
  for fid in fids:
   fr=db.conn.execute('SELECT * FROM files WHERE id=?',(fid,)).fetchone()
   if not fr or fr['uploader_id']!=u or fr['message_id'] is not None: raise HTTPError(400,'invalid file')
  mentions=resolve_mentions(body,c,u)
  i=db.conn.execute('INSERT INTO messages(channel_id,author_id,body,parent_id,created_at,mentions) VALUES(?,?,?,?,?,?)',(c['id'],u,body,parent,t,json.dumps(mentions))).lastrowid
  for fid in fids: db.conn.execute('UPDATE files SET message_id=? WHERE id=?',(i,fid))
  r=db.conn.execute('SELECT * FROM messages WHERE id=?',(i,)).fetchone()
  eid=emit_event(c['id'],'message.reply' if parent else 'message.created',{'message':message_to_json(r)})
  db.conn.execute('UPDATE messages SET event_id=? WHERE id=?',(eid,i)); r=db.conn.execute('SELECT * FROM messages WHERE id=?',(i,)).fetchone()
  return web.json_response({'message':message_to_json(r)},status=201)
 async def listing(q):
  u=require_user(q); c=channel_by_id(q.match_info['id'])
  if not is_channel_member(c['id'],u): raise HTTPError(403,'membership')
  lim=parse_limit(q); cur=q.query.get('cursor'); key=None if cur is None else decode_cursor(cur)
  if key is None: rows=db.conn.execute('SELECT * FROM messages WHERE channel_id=? AND deleted=0 AND parent_id IS NULL ORDER BY id DESC LIMIT ?',(c['id'],lim+1)).fetchall()
  else: rows=db.conn.execute('SELECT * FROM messages WHERE channel_id=? AND deleted=0 AND parent_id IS NULL AND id<? ORDER BY id DESC LIMIT ?',(c['id'],key,lim+1)).fetchall()
  more=len(rows)>lim; rows=rows[:lim]
  return web.json_response({'messages':[message_to_json(r) for r in rows],'next_cursor':encode_cursor(rows[-1]['id']) if more and rows else None})
 async def replies(q):
  u=require_user(q); parent=message_by_id(q.match_info['parent_id']); c=channel_by_id(parent['channel_id'])
  if not is_channel_member(c['id'],u): raise HTTPError(403,'membership')
  lim=parse_limit(q); cur=q.query.get('cursor'); key=None if cur is None else decode_cursor(cur)
  if key is None: rows=db.conn.execute('SELECT * FROM messages WHERE parent_id=? AND deleted=0 ORDER BY id ASC LIMIT ?',(parent['id'],lim+1)).fetchall()
  else: rows=db.conn.execute('SELECT * FROM messages WHERE parent_id=? AND deleted=0 AND id>? ORDER BY id ASC LIMIT ?',(parent['id'],key,lim+1)).fetchall()
  more=len(rows)>lim; rows=rows[:lim]
  return web.json_response({'replies':[message_to_json(r) for r in rows],'next_cursor':encode_cursor(rows[-1]['id']) if more and rows else None})
 async def pin(q):
  u=require_user(q); r=message_by_id(q.match_info['id']); c=channel_by_id(r['channel_id'])
  if not can_read_channel(c,u): raise HTTPError(403,'forbidden')
  if c['is_archived']: raise HTTPError(423,'archived')
  z=db.conn.execute('SELECT * FROM pins WHERE message_id=?',(r['id'],)).fetchone()
  if not z:
   t=db.now_iso(); db.conn.execute('INSERT INTO pins(message_id,channel_id,pinned_by,pinned_at) VALUES(?,?,?,?)',(r['id'],c['id'],u,t)); z=db.conn.execute('SELECT * FROM pins WHERE message_id=?',(r['id'],)).fetchone()
  return web.json_response({'pin':{'message_id':z['message_id'],'pinned_by':z['pinned_by'],'pinned_at':z['pinned_at']}})
 async def unpin(q):
  u=require_user(q); r=message_by_id(q.match_info['id']); c=channel_by_id(r['channel_id'])
  if not can_read_channel(c,u): raise HTTPError(403,'forbidden')
  if c['is_archived']: raise HTTPError(423,'archived')
  db.conn.execute('DELETE FROM pins WHERE message_id=?',(r['id'],)); return web.json_response({'unpinned':True})
 async def pins(q):
  u=require_user(q); c=channel_by_id(q.match_info['id'])
  if not can_read_channel(c,u): raise HTTPError(403,'forbidden')
  lim=parse_limit(q); cur=q.query.get('cursor'); key=None if cur is None else decode_cursor(cur)
  sql='SELECT rowid AS id,* FROM pins WHERE channel_id=? '+(('AND rowid<? ') if key is not None else '')+'ORDER BY rowid DESC LIMIT ?'
  args=[c['id']]+(([key] if key is not None else []))+[lim+1]; rows=db.conn.execute(sql,args).fetchall(); more=len(rows)>lim; rows=rows[:lim]
  out=[{'message':message_to_json(message_by_id(x['message_id'])),'pinned_by':x['pinned_by'],'pinned_at':x['pinned_at']} for x in rows]
  return web.json_response({'pins':out,'next_cursor':encode_cursor(rows[-1]['id']) if more and rows else None})
 async def search(q):
  u=require_user(q); text=q.query.get('q','')
  if not text: raise HTTPError(400,'missing q')
  lim=parse_limit(q); cur=q.query.get('cursor'); key=None if cur is None else decode_cursor(cur); wid=q.query.get('workspace_id')
  sql='SELECT m.* FROM messages m JOIN channels c ON c.id=m.channel_id JOIN workspace_members wm ON wm.workspace_id=c.workspace_id AND wm.user_id=? WHERE m.deleted=0 AND instr(lower(m.body),lower(?))>0 AND (c.is_private=0 OR EXISTS(SELECT 1 FROM channel_members cm WHERE cm.channel_id=c.id AND cm.user_id=?))'
  args=[u,text,u]
  if wid: sql+=' AND c.workspace_id=?'; args.append(wid)
  if key is not None: sql+=' AND m.id<?'; args.append(key)
  sql+=' ORDER BY m.id DESC LIMIT ?'; args.append(lim+1); rows=db.conn.execute(sql,args).fetchall(); more=len(rows)>lim; rows=rows[:lim]
  return web.json_response({'results':[message_to_json(x) for x in rows],'next_cursor':encode_cursor(rows[-1]['id']) if more and rows else None})
 async def read(q):
  u=require_user(q); c=channel_by_id(q.match_info['id'])
  if not can_read_channel(c,u): raise HTTPError(403,'forbidden')
  r=db.conn.execute('SELECT last_read_event_id FROM channel_members WHERE channel_id=? AND user_id=?',(c['id'],u)).fetchone(); last=r['last_read_event_id'] if r else 0
  rows=db.conn.execute('SELECT * FROM messages WHERE channel_id=? AND deleted=0 AND event_id>? AND author_id!=?',(c['id'],last,u)).fetchall()
  state={'channel_id':c['id'],'last_read_event_id':last,'unread_count':len(rows),'mention_count':sum(u in json.loads(x['mentions'] or '[]') for x in rows)}
  if q.method=='POST':
   try: x=await read_json(q); n=x.get('last_read_event_id')
   except HTTPError: n=db.conn.execute('SELECT last_event_id FROM channels WHERE id=?',(c['id'],)).fetchone()['last_event_id']
   if not isinstance(n,int) or n<0: raise HTTPError(400,'invalid read state')
   n=min(n,db.conn.execute('SELECT last_event_id FROM channels WHERE id=?',(c['id'],)).fetchone()['last_event_id']); db.conn.execute('UPDATE channel_members SET last_read_event_id=MAX(last_read_event_id,?) WHERE channel_id=? AND user_id=?',(n,c['id'],u)); last=db.conn.execute('SELECT last_read_event_id FROM channel_members WHERE channel_id=? AND user_id=?',(c['id'],u)).fetchone()['last_read_event_id']; rows=db.conn.execute('SELECT * FROM messages WHERE channel_id=? AND deleted=0 AND event_id>? AND author_id!=?',(c['id'],last,u)).fetchall(); state={'channel_id':c['id'],'last_read_event_id':last,'unread_count':len(rows),'mention_count':sum(u in json.loads(x['mentions'] or '[]') for x in rows)}; return web.json_response({'read_state':state})
  return web.json_response({'read_state':state})
 app.router.add_post('/api/channels/{id}/messages',post)
 app.router.add_post('/api/messages/{id}/pin',pin); app.router.add_delete('/api/messages/{id}/pin',unpin); app.router.add_get('/api/channels/{id}/pins',pins); app.router.add_get('/api/search',search); app.router.add_route('*','/api/channels/{id}/read',read)
 app.router.add_get('/api/channels/{id}/messages',listing)
 app.router.add_get('/api/messages/{parent_id}/replies',replies)

def _mutation_handlers(app):
 async def edit(q):
  u=require_user(q)
  try: mid=int(q.match_info['id'])
  except: raise HTTPError(404,'message not found')
  raw=db.conn.execute('SELECT * FROM messages WHERE id=?',(mid,)).fetchone()
  if not raw: raise HTTPError(404,'message not found')
  if raw['author_id']!=u: raise HTTPError(403,'forbidden')
  if raw['deleted']: raise HTTPError(409,'deleted')
  r=message_by_id(mid); c=channel_by_id(r['channel_id'])
  if c['is_archived']: raise HTTPError(423,'archived')
  x=await read_json(q); body=x.get('body')
  if not isinstance(body,str) or not body.strip(): raise HTTPError(400,'empty')
  db.conn.execute('UPDATE messages SET body=?,edited_at=? WHERE id=?',(body,db.now_iso(),r['id']))
  r=message_by_id(r['id']); eid=emit_event(c['id'],'message.updated',{'message':message_to_json(r)}); db.conn.execute('UPDATE messages SET event_id=? WHERE id=?',(eid,r['id']))
  return web.json_response({'message':message_to_json(r)})
 async def delete(q):
  u=require_user(q)
  try: mid=int(q.match_info['id'])
  except: raise HTTPError(404,'message not found')
  raw=db.conn.execute('SELECT * FROM messages WHERE id=?',(mid,)).fetchone()
  if not raw: raise HTTPError(404,'message not found')
  c=channel_by_id(raw['channel_id']); w=db.conn.execute('SELECT owner_id FROM workspaces WHERE id=?',(c['workspace_id'],)).fetchone()
  if raw['author_id']!=u and w['owner_id']!=u: raise HTTPError(403,'forbidden')
  if raw['deleted']: return web.json_response({'deleted':True})
  db.conn.execute('UPDATE messages SET deleted=1 WHERE id=?',(mid,))
  emit_event(c['id'],'message.deleted',{'message_id':mid})
  return web.json_response({'deleted':True})
 async def react(q):
  u=require_user(q); r=message_by_id(q.match_info['id']); c=channel_by_id(r['channel_id'])
  if not can_read_channel(c,u): raise HTTPError(403,'forbidden')
  if c['is_archived']: raise HTTPError(423,'archived')
  x=await read_json(q); emoji=x.get('emoji')
  if not isinstance(emoji,str) or not emoji or len(emoji)>32: raise HTTPError(400,'invalid emoji')
  exists=db.conn.execute('SELECT 1 FROM reactions WHERE message_id=? AND user_id=? AND emoji=?',(r['id'],u,emoji)).fetchone()
  if not exists:
   db.conn.execute('INSERT INTO reactions VALUES(?,?,?,?)',(r['id'],u,emoji,db.now_iso()))
   rr=message_to_json(message_by_id(r['id']))['reactions']; emit_event(c['id'],'reaction.added',{'message_id':r['id'],'emoji':emoji,'user_id':u,'reactions':rr})
  return web.json_response({'reactions':message_to_json(message_by_id(r['id']))['reactions']})
 async def unreact(q):
  u=require_user(q); r=message_by_id(q.match_info['id']); c=channel_by_id(r['channel_id'])
  if not can_read_channel(c,u): raise HTTPError(403,'forbidden')
  if c['is_archived']: raise HTTPError(423,'archived')
  emoji=q.match_info['emoji']; exists=db.conn.execute('SELECT 1 FROM reactions WHERE message_id=? AND user_id=? AND emoji=?',(r['id'],u,emoji)).fetchone()
  if exists:
   db.conn.execute('DELETE FROM reactions WHERE message_id=? AND user_id=? AND emoji=?',(r['id'],u,emoji))
   rr=message_to_json(message_by_id(r['id']))['reactions']; emit_event(c['id'],'reaction.removed',{'message_id':r['id'],'emoji':emoji,'user_id':u,'reactions':rr})
  return web.json_response({'reactions':message_to_json(message_by_id(r['id']))['reactions']})
 app.router.add_patch('/api/messages/{id}',edit); app.router.add_delete('/api/messages/{id}',delete)
 app.router.add_post('/api/messages/{id}/reactions',react); app.router.add_delete('/api/messages/{id}/reactions/{emoji}',unreact)
_mutation_handlers(app) if False else None
_prev_message_setup=setup
def setup(app):
 _prev_message_setup(app); _mutation_handlers(app)
