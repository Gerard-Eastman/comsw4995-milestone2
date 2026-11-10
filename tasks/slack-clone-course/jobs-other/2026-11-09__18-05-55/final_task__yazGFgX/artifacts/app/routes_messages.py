import json,re,time
from aiohttp import web
from db import connect,now_iso
from common import *
MENTION_RE=re.compile(r'(?<![A-Za-z0-9_@.])@([A-Za-z0-9_]+)(?![A-Za-z0-9_@])(?!\.[A-Za-z0-9])')
def setup_db():
 c=connect()
 for sql in ('ALTER TABLE messages ADD COLUMN mentions TEXT DEFAULT "[]"','ALTER TABLE messages ADD COLUMN event_id INTEGER'):
  try:c.execute(sql)
  except:pass
 c.execute('CREATE TABLE IF NOT EXISTS pins(id INTEGER PRIMARY KEY,message_id INTEGER UNIQUE,channel_id INTEGER,pinned_by INTEGER,pinned_at TEXT)')
setup_db()
try:
 connect().execute('ALTER TABLE pins ADD COLUMN channel_id INTEGER')
except: pass
try:
 connect().execute('ALTER TABLE pins ADD COLUMN pinned_by INTEGER')
except: pass
try:
 connect().execute('UPDATE pins SET pinned_by=user_id WHERE pinned_by IS NULL')
except: pass
def chrow(cid):
 r=connect().execute('SELECT * FROM channels WHERE id=?',(cid,)).fetchone()
 if not r: raise HTTPError(404,'channel not found')
 return r
def allowed(ch,uid):
 c=connect()
 if c.execute('SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?',(ch['id'],uid)).fetchone(): return True
 return bool(not ch['is_private'] and c.execute('SELECT 1 FROM members WHERE workspace_id=? AND user_id=?',(ch['workspace_id'],uid)).fetchone())
def msgrow(mid):
 r=connect().execute('SELECT * FROM messages WHERE id=? AND deleted=0',(mid,)).fetchone()
 if not r: raise HTTPError(404,'message not found')
 return r
def mentions(body,ch,uid):
 c=connect(); out=[]
 for name in MENTION_RE.findall(body):
  if name in ('channel','here'):
   ids=[x['user_id'] for x in c.execute('SELECT user_id FROM channel_members WHERE channel_id=?',(ch['id'],))]
   if name=='here': ids=[x['user_id'] for x in c.execute('SELECT cm.user_id FROM channel_members cm JOIN ws_presence p ON p.user_id=cm.user_id WHERE cm.channel_id=?',(ch['id'],))]
  else:
   x=c.execute('SELECT id FROM users WHERE username=?',(name,)).fetchone()
   if not x:
    g=c.execute('SELECT id FROM groups WHERE workspace_id=? AND handle=?',(ch['workspace_id'],name)).fetchone()
    ids=[z['user_id'] for z in c.execute('SELECT user_id FROM group_members WHERE group_id=?',(g['id'],))] if g else []
   else: ids=[x['id']] if c.execute('SELECT 1 FROM members WHERE workspace_id=? AND user_id=?',(ch['workspace_id'],x['id'])).fetchone() else []
  for i in ids:
   if i!=uid and i not in out: out.append(i)
 return out
def obj(r):
 c=connect(); u=c.execute('SELECT * FROM users WHERE id=?',(r['author_id'],)).fetchone()
 rx=[]
 for x in c.execute('SELECT emoji,count(*) n FROM reactions WHERE message_id=? GROUP BY emoji',(r['id'],)):
  rx.append({'emoji':x['emoji'],'count':x['n'],'user_ids':[z['user_id'] for z in c.execute('SELECT user_id FROM reactions WHERE message_id=? AND emoji=?',(r['id'],x['emoji']))]})
 files=[]
 try:
  for f in c.execute('SELECT f.* FROM files f JOIN message_files mf ON mf.file_id=f.id WHERE mf.message_id=?',(r['id'],)): files.append({k:f[k] for k in ('id','uploader_id','filename','content_type','size','created_at')})
 except: pass
 return {'id':r['id'],'channel_id':r['channel_id'],'author_id':r['author_id'],'author':user_to_json(u),'body':r['body'],'parent_id':r['parent_id'],'reply_count':c.execute('SELECT count(*) n FROM messages WHERE parent_id=? AND deleted=0',(r['id'],)).fetchone()['n'],'created_at':r['created_at'],'edited_at':r['edited_at'],'files':files,'reactions':rx,'mentions':json.loads(r['mentions'] or '[]')}
def setup(app):
 async def create(q):
  u=require_user(q); d=await read_json(q); ch=chrow(int(q.match_info['id']))
  if not allowed(ch,u['id']): raise HTTPError(403,'forbidden')
  body=d.get('body')
  if ch['is_archived'] and body != '/unarchive': raise HTTPError(423,'archived')
  if not isinstance(body,str) or not body.strip(): raise HTTPError(400,'empty body')
  if body.startswith('//'): body=body[1:]
  elif body.startswith('/'):
   cmd,_,text=body[1:].partition(' '); text=text.strip()
   if cmd=='me':
    if not text: raise HTTPError(400,'/me requires text')
   elif cmd=='shrug':
    body=(text+' ' if text else '')+'¯\\_(ツ)_/¯'
   elif cmd=='topic':
    if len(text)>250: raise HTTPError(400,'topic too long')
    c=connect(); c.execute('UPDATE channels SET topic=? WHERE id=?',(text,ch['id']))
    channel=dict(c.execute('SELECT * FROM channels WHERE id=?',(ch['id'],)).fetchone())
    for k in ('is_private','is_dm','is_archived'): channel[k]=bool(channel[k])
    emit_event(ch['id'],'channel.updated',{'channel':channel})
    return web.json_response({'message':None,'channel':channel},status=201)
   elif cmd=='invite':
    if not text.startswith('@') or len(text)<2: raise HTTPError(400,'missing user')
    x=connect().execute('SELECT * FROM users WHERE username=?',(text[1:],)).fetchone()
    if not x: raise HTTPError(404,'user')
    c=connect()
    if not c.execute('SELECT 1 FROM members WHERE workspace_id=? AND user_id=?',(ch['workspace_id'],x['id'])).fetchone(): raise HTTPError(400,'not workspace member')
    if not c.execute('SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?',(ch['id'],u['id'])).fetchone(): raise HTTPError(403,'forbidden')
    if not c.execute('SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?',(ch['id'],x['id'])).fetchone():
     c.execute('INSERT INTO channel_members VALUES(?,?)',(ch['id'],x['id']))
     emit_event(ch['id'],'member.joined',{'user_id':x['id'],'user':user_to_json(x)})
    return web.json_response({'message':None,'invited_user':user_to_json(x)},status=201)
   elif cmd in ('archive','unarchive'):
    c=connect(); w=c.execute('SELECT owner_id FROM workspaces WHERE id=?',(ch['workspace_id'],)).fetchone()
    if w['owner_id']!=u['id']: raise HTTPError(403,'owner only')
    flag=1 if cmd=='archive' else 0
    c.execute('UPDATE channels SET is_archived=? WHERE id=?',(flag,ch['id']))
    channel=dict(c.execute('SELECT * FROM channels WHERE id=?',(ch['id'],)).fetchone())
    for k in ('is_private','is_dm','is_archived'): channel[k]=bool(channel[k])
    emit_event(ch['id'],'channel.archived' if flag else 'channel.unarchived',{'channel':channel})
    return web.json_response({'message':None,'channel':channel},status=201)
   else: raise HTTPError(400,'unknown command')
  c=connect(); parent=d.get('parent_id')
  if parent:
   p=msgrow(parent)
   if p['channel_id']!=ch['id']: raise HTTPError(404,'parent not found')
  ms=json.dumps(mentions(body,ch,u['id'])); now=now_iso()
  file_ids=d.get('file_ids',[])
  if file_ids:
   c=connect(); c.execute('CREATE TABLE IF NOT EXISTS message_files(message_id INTEGER,file_id INTEGER UNIQUE)')
   for fid in file_ids:
    f=c.execute('SELECT * FROM files WHERE id=? AND uploader_id=?',(fid,u['id'])).fetchone()
    if not f or c.execute('SELECT 1 FROM message_files WHERE file_id=?',(fid,)).fetchone(): raise HTTPError(400,'invalid file')
  c.execute('INSERT INTO messages(channel_id,author_id,body,parent_id,created_at,mentions) VALUES(?,?,?,?,?,?)',(ch['id'],u['id'],body,parent,now,ms))
  r=c.execute('SELECT * FROM messages WHERE id=last_insert_rowid()').fetchone()
  for fid in file_ids: c.execute('INSERT INTO message_files VALUES(?,?)',(r['id'],fid))
  o=obj(r)
  eid=emit_event(ch['id'],'message.reply' if parent else 'message.created',{'message':o})
  c.execute('UPDATE messages SET event_id=? WHERE id=?',(eid,r['id']))
  return web.json_response({'message':o},status=201)
 async def listing(q):
  u=require_user(q); ch=chrow(int(q.match_info['id']))
  if not allowed(ch,u['id']): raise HTTPError(403,'forbidden')
  n=parse_limit(q); k=10**18 if not q.query.get('cursor') else decode_cursor(q.query['cursor'])
  rows=connect().execute('SELECT * FROM messages WHERE channel_id=? AND parent_id IS NULL AND deleted=0 AND id<? ORDER BY id DESC LIMIT ?',(ch['id'],k,n+1)).fetchall()
  return web.json_response({'messages':[obj(x) for x in rows[:n]],'next_cursor':encode_cursor(rows[n-1]['id']) if len(rows)>n else None})
 async def replies(q):
  u=require_user(q); p=msgrow(int(q.match_info['id'])); ch=chrow(p['channel_id'])
  if not allowed(ch,u['id']): raise HTTPError(403,'forbidden')
  n=parse_limit(q); k=0 if not q.query.get('cursor') else decode_cursor(q.query['cursor'])
  rows=connect().execute('SELECT * FROM messages WHERE parent_id=? AND deleted=0 AND id>? ORDER BY id ASC LIMIT ?',(p['id'],k,n+1)).fetchall()
  return web.json_response({'replies':[obj(x) for x in rows[:n]],'next_cursor':encode_cursor(rows[n-1]['id']) if len(rows)>n else None})
 async def pin(q):
  u=require_user(q); r=msgrow(int(q.match_info['id'])); ch=chrow(r['channel_id'])
  if not allowed(ch,u['id']): raise HTTPError(403,'forbidden')
  if ch['is_archived']: raise HTTPError(423,'archived')
  c=connect(); x=c.execute('SELECT * FROM pins WHERE message_id=?',(r['id'],)).fetchone()
  if not x:
   c.execute('INSERT INTO pins(message_id,channel_id,pinned_by,pinned_at) VALUES(?,?,?,?)',(r['id'],ch['id'],u['id'],now_iso())); x=c.execute('SELECT * FROM pins WHERE message_id=?',(r['id'],)).fetchone()
  return web.json_response({'pin':{'message_id':x['message_id'],'pinned_by':x['pinned_by'],'pinned_at':x['pinned_at']}})
 async def unpin(q):
  u=require_user(q); r=msgrow(int(q.match_info['id'])); ch=chrow(r['channel_id'])
  if not allowed(ch,u['id']): raise HTTPError(403,'forbidden')
  connect().execute('DELETE FROM pins WHERE message_id=?',(r['id'],)); return web.json_response({'unpinned':True})
 async def pins(q):
  u=require_user(q); ch=chrow(int(q.match_info['id']))
  if not allowed(ch,u['id']): raise HTTPError(403,'forbidden')
  n=parse_limit(q); k=10**18 if not q.query.get('cursor') else decode_cursor(q.query['cursor']); c=connect()
  rows=c.execute('SELECT rowid AS id,* FROM pins WHERE channel_id=? AND rowid<? ORDER BY rowid DESC LIMIT ?',(ch['id'],k,n+1)).fetchall()
  return web.json_response({'pins':[{'message':obj(msgrow(x['message_id'])),'pinned_by':x['pinned_by'],'pinned_at':x['pinned_at']} for x in rows[:n]],'next_cursor':encode_cursor(rows[n-1]['id']) if len(rows)>n else None})
 async def search(q):
  u=require_user(q); term=q.query.get('q','')
  if not term: raise HTTPError(400,'missing q')
  n=parse_limit(q); k=10**18 if not q.query.get('cursor') else decode_cursor(q.query['cursor']); c=connect()
  ws=q.query.get('workspace_id')
  extra=' AND ch.workspace_id=?' if ws else ''
  args=[f'%{term}%',k]
  if ws: args.insert(1,int(ws))
  rows=c.execute('SELECT m.* FROM messages m JOIN channels ch ON ch.id=m.channel_id WHERE m.deleted=0 AND lower(m.body) LIKE lower(?)'+extra+' AND m.id<? ORDER BY m.id DESC LIMIT ?',tuple([args[0]]+([args[1]] if ws else [])+[args[-1],n+1])).fetchall()
  rows=[x for x in rows if allowed(c.execute('SELECT * FROM channels WHERE id=?',(x['channel_id'],)).fetchone(),u['id'])]
  return web.json_response({'results':[obj(x) for x in rows[:n]],'next_cursor':encode_cursor(rows[n-1]['id']) if len(rows)>n else None})
 async def read(q):
  u=require_user(q); ch=chrow(int(q.match_info['id']))
  if not allowed(ch,u['id']): raise HTTPError(403,'forbidden')
  c=connect(); x=c.execute('SELECT * FROM readstate WHERE user_id=? AND channel_id=?',(u['id'],ch['id'])).fetchone()
  last=x['last_read_event_id'] if x else 0
  rows=c.execute('SELECT * FROM messages WHERE channel_id=? AND deleted=0 AND event_id>? AND author_id!=?',(ch['id'],last,u['id'])).fetchall()
  st={'channel_id':ch['id'],'last_read_event_id':last,'unread_count':len(rows),'mention_count':sum(u['id'] in json.loads(r['mentions'] or '[]') for r in rows)}
  if q.method=='POST':
   d=await read_json(q); v=d.get('last_read_event_id')
   if not isinstance(v,int) or v<0: raise HTTPError(400,'invalid read state')
   head=connect().execute('SELECT COALESCE(MAX(event_id),0) n FROM events WHERE channel_id=?',(ch['id'],)).fetchone()['n']; v=min(v,head)
   if x: connect().execute('UPDATE readstate SET last_read_event_id=max(last_read_event_id,?) WHERE user_id=? AND channel_id=?',(v,u['id'],ch['id']))
   else: connect().execute('INSERT INTO readstate VALUES(?,?,?)',(u['id'],ch['id'],v))
   row=connect().execute('SELECT last_read_event_id FROM readstate WHERE user_id=? AND channel_id=?',(u['id'],ch['id'])).fetchone()
   remain=connect().execute('SELECT * FROM messages WHERE channel_id=? AND deleted=0 AND event_id>? AND author_id!=?',(ch['id'],row['last_read_event_id'],u['id'])).fetchall()
   return web.json_response({'read_state':{'channel_id':ch['id'],'last_read_event_id':row['last_read_event_id'],'unread_count':len(remain),'mention_count':sum(u['id'] in json.loads(r['mentions'] or '[]') for r in remain)}})
  return web.json_response({'read_state':st})
 app.router.add_post('/api/channels/{id}/messages',create); app.router.add_get('/api/channels/{id}/messages',listing); app.router.add_get('/api/messages/{id}/replies',replies)
 app.router.add_post('/api/messages/{id}/pin',pin); app.router.add_delete('/api/messages/{id}/pin',unpin); app.router.add_get('/api/channels/{id}/pins',pins); app.router.add_get('/api/search',search)
 app.router.add_get('/api/channels/{id}/read',read); app.router.add_post('/api/channels/{id}/read',read)

 async def edit(q):
  u=require_user(q); d=await read_json(q); c=connect(); r=c.execute('SELECT * FROM messages WHERE id=?',(q.match_info['id'],)).fetchone()
  if not r: raise HTTPError(404,'message not found')
  ch=chrow(r['channel_id'])
  if ch['is_archived']: raise HTTPError(423,'archived')
  if r['author_id']!=u['id']: raise HTTPError(403,'forbidden')
  if r['deleted']: raise HTTPError(409,'message deleted')
  body=d.get('body')
  if not isinstance(body,str) or not body.strip(): raise HTTPError(400,'empty body')
  c.execute('UPDATE messages SET body=?,edited_at=? WHERE id=?',(body,now_iso(),r['id']))
  nr=msgrow(r['id']); o=obj(nr); emit_event(ch['id'],'message.updated',{'message':o})
  return web.json_response({'message':o})
 async def delete(q):
  u=require_user(q); c=connect(); r=c.execute('SELECT * FROM messages WHERE id=?',(q.match_info['id'],)).fetchone()
  if not r: raise HTTPError(404,'message not found')
  ch=chrow(r['channel_id'])
  if r['deleted']: return web.json_response({'deleted':True})
  if ch['is_archived']: raise HTTPError(423,'archived')
  owner=c.execute('SELECT owner_id FROM workspaces WHERE id=?',(ch['workspace_id'],)).fetchone()
  if r['author_id']!=u['id'] and owner['owner_id']!=u['id']: raise HTTPError(403,'forbidden')
  c.execute('UPDATE messages SET deleted=1 WHERE id=?',(r['id'],)); emit_event(ch['id'],'message.deleted',{'message_id':r['id']})
  return web.json_response({'deleted':True})
 async def react(q):
  u=require_user(q); r=msgrow(int(q.match_info['id'])); ch=chrow(r['channel_id']); c=connect()
  if ch['is_archived']: raise HTTPError(423,'archived')
  if not allowed(ch,u['id']): raise HTTPError(403,'forbidden')
  d=await read_json(q); emoji=d.get('emoji')
  if not isinstance(emoji,str) or not emoji or len(emoji)>64: raise HTTPError(400,'invalid emoji')
  if not c.execute('SELECT 1 FROM reactions WHERE message_id=? AND user_id=? AND emoji=?',(r['id'],u['id'],emoji)).fetchone():
   c.execute('INSERT INTO reactions VALUES(?,?,?)',(r['id'],u['id'],emoji)); emit_event(ch['id'],'reaction.added',{'message_id':r['id'],'emoji':emoji,'user_id':u['id'],'reactions':obj(msgrow(r['id']))['reactions']})
  return web.json_response({'reactions':obj(msgrow(r['id']))['reactions']})
 async def unreact(q):
  u=require_user(q); r=msgrow(int(q.match_info['id'])); ch=chrow(r['channel_id']); c=connect()
  if ch['is_archived']: raise HTTPError(423,'archived')
  if not allowed(ch,u['id']): raise HTTPError(403,'forbidden')
  emoji=q.match_info['emoji']; existed=c.execute('SELECT 1 FROM reactions WHERE message_id=? AND user_id=? AND emoji=?',(r['id'],u['id'],emoji)).fetchone()
  if existed:
   c.execute('DELETE FROM reactions WHERE message_id=? AND user_id=? AND emoji=?',(r['id'],u['id'],emoji)); emit_event(ch['id'],'reaction.removed',{'message_id':r['id'],'emoji':emoji,'user_id':u['id'],'reactions':obj(msgrow(r['id']))['reactions']})
  return web.json_response({'reactions':obj(msgrow(r['id']))['reactions']})
 app.router.add_patch('/api/messages/{id}',edit); app.router.add_delete('/api/messages/{id}',delete)
 app.router.add_post('/api/messages/{id}/reactions',react); app.router.add_delete('/api/messages/{id}/reactions/{emoji}',unreact)
