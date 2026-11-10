import argparse,asyncio,json,os,re,secrets,uuid
from aiohttp import web,WSMsgType
from db import connect,init_db,now_iso
from common import *
NODE=0; sockets=set(); subscriptions={}
def userj(r): return user_to_json(r)
def chan(r): return {k:(bool(r[k]) if k in ('is_private','is_dm','is_archived') else r[k]) for k in ('id','workspace_id','name','is_private','is_dm','topic','is_archived','created_at')}
def member(cid,uid): return connect().execute('SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?',(cid,uid)).fetchone()
def r_owner(cid,uid):
 r=connect().execute('SELECT workspace_id FROM channels WHERE id=?',(cid,)).fetchone()
 return bool(r and r[0] is not None and connect().execute('SELECT 1 FROM workspaces WHERE id=? AND owner_id=?',(r[0],uid)).fetchone())
def access(cid,u,write=False):
 r=connect().execute('SELECT * FROM channels WHERE id=?',(cid,)).fetchone()
 if not r: raise HTTPError(404,'channel not found')
 if not member(cid,u['id']):
  if r['is_dm'] or r['is_private']: raise HTTPError(403,'forbidden')
  if r['workspace_id'] and not connect().execute('SELECT 1 FROM workspace_members WHERE workspace_id=? AND user_id=?',(r['workspace_id'],u['id'])).fetchone(): raise HTTPError(403,'forbidden')
 if write and r['is_archived']: raise HTTPError(423,'channel archived')
 return r
def filej(r):
 return {'id':r['id'],'uploader_id':r['uploader_id'],'filename':r['filename'],'content_type':r['content_type'],'size':r['size'],'created_at':r['created_at']}
def msgj(r):
 c=connect(); a=c.execute('SELECT * FROM users WHERE id=?',(r['author_id'],)).fetchone()
 reps=c.execute('SELECT count(*) FROM messages WHERE parent_id=? AND deleted=0',(r['id'],)).fetchone()[0]
 rx=[]
 for x in c.execute('SELECT emoji FROM reactions WHERE message_id=? GROUP BY emoji ORDER BY min(rowid)',(r['id'],)):
  ids=[z[0] for z in c.execute('SELECT user_id FROM reactions WHERE message_id=? AND emoji=? ORDER BY rowid',(r['id'],x[0]))]
  rx.append({'emoji':x[0],'count':len(ids),'user_ids':ids})
 return {'id':r['id'],'channel_id':r['channel_id'],'author_id':r['author_id'],'author':userj(a),'body':r['body'],'parent_id':r['parent_id'],'reply_count':reps,'created_at':r['created_at'],'edited_at':r['edited_at'],'files':[filej(x) for x in c.execute('SELECT * FROM files WHERE message_id=? ORDER BY id',(r['id'],))],'reactions':rx,'mentions':json.loads(r['mentions'] or '[]')}
def mentions(body,cid,uid):
 c=connect(); out=[]; ids=[x[0] for x in c.execute('SELECT user_id FROM channel_members WHERE channel_id=?',(cid,))]
 for n in re.findall(r'(?<![A-Za-z0-9_@.])@([A-Za-z0-9_][A-Za-z0-9_-]*)(?![A-Za-z0-9_@-])',body):
  if n=='channel': q=ids
  elif n=='here':
   q=[x[0] for x in c.execute('SELECT DISTINCT user_id FROM ws_presence WHERE user_id IN (%s)'%(','.join('?'*len(ids)) if ids else '0'),ids)] if ids else []
  else:
   z=c.execute('SELECT id FROM users WHERE username=?',(n,)).fetchone()
   if z and z[0] in ids: q=[z[0]]
   else:
    g=c.execute('SELECT id FROM groups WHERE workspace_id=(SELECT workspace_id FROM channels WHERE id=?) AND handle=?',(cid,n)).fetchone()
    q=[x[0] for x in c.execute('SELECT user_id FROM group_members WHERE group_id=? AND user_id IN (%s)'%(','.join('?'*len(ids)) if ids else '0'),[g[0]]+ids)] if g and ids else []
  for x in q:
   if x!=uid and x not in out: out.append(x)
 return out

def profile_fields(b):
 out={}
 allowed=('display_name','timezone','avatar_url','status_text','status_emoji')
 for k in allowed:
  if k not in b: continue
  v=b[k]
  if not isinstance(v,str): raise HTTPError(400,'invalid profile')
  if k=='display_name' and not 1<=len(v)<=80: raise HTTPError(400,'invalid display_name')
  if k=='status_text' and len(v)>100: raise HTTPError(400,'invalid status_text')
  if k=='status_emoji' and len(v)>64: raise HTTPError(400,'invalid status_emoji')
  if k=='avatar_url' and len(v)>1024: raise HTTPError(400,'invalid avatar_url')
  if k=='timezone':
   try:
    from zoneinfo import ZoneInfo
    ZoneInfo(v)
   except: raise HTTPError(400,'invalid timezone')
  out[k]=v
 return out
async def user_route(req):
 u=require_user(req); c=connect()
 if req.method=='GET':
  try: uid=int(req.match_info['id'])
  except: raise HTTPError(404,'user not found')
  r=c.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone()
  if not r: raise HTTPError(404,'user not found')
  return web.json_response({'user':userj(r)})
 b=await read_json(req); vals=profile_fields(b)
 if vals:
  c.execute('UPDATE users SET '+','.join(k+'=?' for k in vals)+' WHERE id=?',tuple(vals.values())+(u['id'],))
 r=c.execute('SELECT * FROM users WHERE id=?',(u['id'],)).fetchone(); payload={'type':'user.updated','user':userj(r)}; broadcast_global(payload)
 return web.json_response({'user':userj(r)})
async def health(req): return web.json_response({'status':'ok','node_id':NODE})
async def register(req):
 b=await read_json(req); n=b.get('username',''); p=b.get('password','')
 if not re.fullmatch(r'[A-Za-z0-9_]{1,32}',n) or not isinstance(p,str) or len(p)<8: raise HTTPError(400,'invalid registration')
 c=connect()
 if c.execute('SELECT 1 FROM users WHERE username=?',(n,)).fetchone(): raise HTTPError(409,'username exists')
 c.execute('INSERT INTO users(username,password,display_name) VALUES(?,?,?)',(n,p,b.get('display_name') or n)); u=c.execute('SELECT * FROM users WHERE id=last_insert_rowid()').fetchone(); t=secrets.token_urlsafe(24); c.execute('INSERT INTO tokens VALUES(?,?)',(t,u['id']))
 return web.json_response({'user':userj(u),'token':t},status=201)
async def login(req):
 b=await read_json(req); u=connect().execute('SELECT * FROM users WHERE username=? AND password=?',(b.get('username'),b.get('password'))).fetchone()
 if not u: raise HTTPError(401,'invalid credentials')
 t=secrets.token_urlsafe(24); connect().execute('INSERT INTO tokens VALUES(?,?)',(t,u['id'])); return web.json_response({'user':userj(u),'token':t})
async def me(req): return web.json_response({'user':userj(require_user(req))})
async def workspaces(req):
 u=require_user(req); c=connect()
 if req.method=='POST':
  b=await read_json(req); s=b.get('slug','')
  if not re.fullmatch(r'[a-z0-9-]{2,32}',s) or not b.get('name'): raise HTTPError(400,'invalid workspace')
  if c.execute('SELECT 1 FROM workspaces WHERE slug=?',(s,)).fetchone(): raise HTTPError(409,'duplicate')
  c.execute('INSERT INTO workspaces(slug,name,owner_id) VALUES(?,?,?)',(s,b['name'],u['id'])); w=c.execute('SELECT * FROM workspaces WHERE id=last_insert_rowid()').fetchone()
  c.execute('INSERT INTO workspace_members VALUES(?,?,?)',(w['id'],u['id'],'owner')); c.execute('INSERT INTO channels(workspace_id,name,created_at) VALUES(?,?,?)',(w['id'],'general',now_iso())); ch=c.execute('SELECT * FROM channels WHERE id=last_insert_rowid()').fetchone(); c.execute('INSERT INTO channel_members VALUES(?,?)',(ch['id'],u['id']))
  return web.json_response({'workspace':dict(w),'general_channel':chan(ch)},status=201)
 rows=c.execute('SELECT w.* FROM workspaces w JOIN workspace_members m ON m.workspace_id=w.id WHERE m.user_id=?',(u['id'],)).fetchall()
 return web.json_response({'workspaces':[dict(x) for x in rows]})
async def workspace(req):
 u=require_user(req); c=connect(); w=c.execute('SELECT * FROM workspaces WHERE slug=?',(req.match_info['slug'],)).fetchone()
 if not w: raise HTTPError(404,'workspace not found')
 if not c.execute('SELECT 1 FROM workspace_members WHERE workspace_id=? AND user_id=?',(w['id'],u['id'])).fetchone(): raise HTTPError(403,'forbidden')
 if req.path.endswith('/members'): return web.json_response({'members':[{'user_id':x['user_id'],'role':x['role'],'user':userj(c.execute('SELECT * FROM users WHERE id=?',(x['user_id'],)).fetchone())} for x in c.execute('SELECT * FROM workspace_members WHERE workspace_id=?',(w['id'],))]})
 if req.method=='POST':
  b=await read_json(req); n=b.get('name','')
  if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*',n) or len(n)>32: raise HTTPError(400,'invalid channel')
  if c.execute('SELECT 1 FROM channels WHERE workspace_id=? AND name=?',(w['id'],n)).fetchone(): raise HTTPError(409,'duplicate')
  c.execute('INSERT INTO channels(workspace_id,name,is_private,topic,created_at) VALUES(?,?,?,?,?)',(w['id'],n,int(bool(b.get('is_private'))),b.get('topic',''),now_iso())); ch=c.execute('SELECT * FROM channels WHERE id=last_insert_rowid()').fetchone(); c.execute('INSERT INTO channel_members VALUES(?,?)',(ch['id'],u['id']))
  return web.json_response({'channel':chan(ch)},status=201)
 cs=c.execute('SELECT * FROM channels WHERE workspace_id=? AND is_dm=0',(w['id'],)).fetchall()
 return web.json_response({'workspace':dict(w),'channels':[chan(x) for x in cs],'read_state':[]})
async def read_route(req):
 u=require_user(req); c=connect()
 try: cid=int(req.match_info['id'])
 except: raise HTTPError(404,'channel not found')
 access(cid,u,False)
 row=c.execute('SELECT * FROM read_state WHERE user_id=? AND channel_id=?',(u['id'],cid)).fetchone()
 last=row['last_read_event_id'] if row else 0
 if req.method=='POST':
  b=await read_json(req); n=b.get('last_read_event_id')
  if not isinstance(n,int): raise HTTPError(400,'invalid event id')
  if n>last:
   c.execute('INSERT INTO read_state(user_id,channel_id,last_read_event_id) VALUES(?,?,?) ON CONFLICT(user_id,channel_id) DO UPDATE SET last_read_event_id=excluded.last_read_event_id',(u['id'],cid,n)); last=n
 total=c.execute('SELECT count(*) FROM events WHERE channel_id=? AND event_id>?',(cid,last)).fetchone()[0]
 mentions_n=c.execute("SELECT count(*) FROM messages WHERE channel_id=? AND id IN (SELECT id FROM messages WHERE deleted=0) AND author_id<>? AND mentions LIKE ?",(cid,u['id'],'%'+str(u['id'])+'%')).fetchone()[0]
 return web.json_response({'read_state':{'channel_id':cid,'last_read_event_id':last,'unread_count':total,'mention_count':mentions_n}})
async def channel(req):
 u=require_user(req); c=connect(); cid=int(req.match_info['id'])
 if req.path.endswith('/archive') or req.path.endswith('/unarchive'):
  if not r_owner(cid,u['id']): raise HTTPError(403,'forbidden')
  val=0 if req.path.endswith('/unarchive') else 1
  c.execute('UPDATE channels SET is_archived=? WHERE id=?',(val,cid)); r=c.execute('SELECT * FROM channels WHERE id=?',(cid,)).fetchone(); emit_event(cid,'channel.unarchived' if not val else 'channel.archived',{'channel':chan(r)}); return web.json_response({'channel':chan(r)})
 if req.path.endswith('/join'):
  r=c.execute('SELECT * FROM channels WHERE id=?',(cid,)).fetchone()
  if not r: raise HTTPError(404,'channel not found')
  if r['is_private']: raise HTTPError(403,'private')
  if r['workspace_id'] and not c.execute('SELECT 1 FROM workspace_members WHERE workspace_id=? AND user_id=?',(r['workspace_id'],u['id'])).fetchone():
   w=c.execute('SELECT join_mode FROM workspaces WHERE id=?',(r['workspace_id'],)).fetchone()
   if not w or w['join_mode']!='open': raise HTTPError(403,'forbidden')
   c.execute('INSERT OR IGNORE INTO workspace_members VALUES(?,?,?)',(r['workspace_id'],u['id'],'member'))
  c.execute('INSERT OR IGNORE INTO channel_members VALUES(?,?)',(cid,u['id'])); return web.json_response({'channel':chan(r)})
 r=access(cid,u,False if req.path.endswith('/messages') else req.method in ('POST','PATCH'))
 if req.path.endswith('/messages'):
  if req.method=='GET':
   lim=parse_limit(req); cur=decode_cursor(req.query['cursor']) if req.query.get('cursor') else 10**18
   rows=c.execute('SELECT * FROM messages WHERE channel_id=? AND parent_id IS NULL AND deleted=0 AND id<? ORDER BY id DESC LIMIT ?',(cid,cur,lim+1)).fetchall(); nxt=encode_cursor(rows[lim-1]['id']) if len(rows)>lim else None
   return web.json_response({'messages':[msgj(x) for x in rows[:lim]],'next_cursor':nxt})
  b=await read_json(req); body=b.get('body','')
  if not isinstance(body,str) or not body: raise HTTPError(400,'empty body')
  if body.startswith('//'): body=body[1:]
  elif body.startswith('/topic'):
   text=body[6:].strip()
   if len(text)>250: raise HTTPError(400,'topic too long')
   c.execute('UPDATE channels SET topic=? WHERE id=?',(text,cid)); r=c.execute('SELECT * FROM channels WHERE id=?',(cid,)).fetchone()
   emit_event(cid,'channel.updated',{'channel':chan(r)})
   return web.json_response({'message':None,'channel':chan(r)},status=201)
  elif body.startswith('/invite'):
   text=body[7:].strip()
   if not text.startswith('@') or len(text)<2: raise HTTPError(400,'username required')
   target=c.execute('SELECT * FROM users WHERE username=?',(text[1:],)).fetchone()
   if not target: raise HTTPError(404,'user not found')
   if r['workspace_id'] is None or not c.execute('SELECT 1 FROM workspace_members WHERE workspace_id=? AND user_id=?',(r['workspace_id'],target['id'])).fetchone(): raise HTTPError(400,'not workspace member')
   c.execute('INSERT OR IGNORE INTO channel_members VALUES(?,?)',(cid,target['id']))
   emit_event(cid,'member.joined',{'user_id':target['id']})
   return web.json_response({'message':None,'invited_user':userj(target)},status=201)
  elif body.strip() in ('/archive','/unarchive'):
   if not r_owner(cid,u['id']): raise HTTPError(403,'forbidden')
   val=1 if body.strip()=='/archive' else 0
   c.execute('UPDATE channels SET is_archived=? WHERE id=?',(val,cid)); r=c.execute('SELECT * FROM channels WHERE id=?',(cid,)).fetchone()
   emit_event(cid,'channel.archived' if val else 'channel.unarchived',{'channel':chan(r)})
   return web.json_response({'message':None,'channel':chan(r)},status=201)
  elif body.startswith('/shrug'): body=(body[6:].strip()+' ¯\\_(ツ)_/¯').strip()
  elif body == '/me': raise HTTPError(400,'text required')
  elif body.startswith('/me '): pass
  elif body.startswith('/'): raise HTTPError(400,'unknown command')
  if r['is_archived']: raise HTTPError(423,'channel archived')
  par=b.get('parent_id')
  fids=b.get('file_ids',[])
  if not isinstance(fids,list) or any(not isinstance(x,int) for x in fids): raise HTTPError(400,'invalid file_ids')
  for fid in fids:
   fr=c.execute('SELECT * FROM files WHERE id=? AND uploader_id=? AND message_id IS NULL',(fid,u['id'])).fetchone()
   if not fr: raise HTTPError(400,'invalid file')
  men=mentions(body,cid,u['id']); c.execute('INSERT INTO messages(channel_id,author_id,body,parent_id,created_at,mentions) VALUES(?,?,?,?,?,?)',(cid,u['id'],body,par,now_iso(),json.dumps(men))); m=c.execute('SELECT * FROM messages WHERE id=last_insert_rowid()').fetchone();
  for fid in fids: c.execute('UPDATE files SET message_id=? WHERE id=?',(m['id'],fid))
  kind='message.reply' if par else 'message.created'; emit_event(cid,kind,{'message':msgj(m)})
  return web.json_response({'message':msgj(m)},status=201)
async def post_reaction(req):
 u=require_user(req); c=connect(); m=c.execute('SELECT * FROM messages WHERE id=? AND deleted=0',(int(req.match_info['id']),)).fetchone()
 if not m: raise HTTPError(404,'message not found')
 access(m['channel_id'],u,True); b=await read_json(req); e=b.get('emoji')
 if not isinstance(e,str) or not e or len(e)>64: raise HTTPError(400,'invalid emoji')
 before=c.execute('SELECT 1 FROM reactions WHERE message_id=? AND user_id=? AND emoji=?',(m['id'],u['id'],e)).fetchone(); c.execute('INSERT OR IGNORE INTO reactions VALUES(?,?,?,?)',(m['id'],u['id'],e,now_iso()));
 if not before: emit_event(m['channel_id'],'reaction.added',{'message_id':m['id'],'emoji':e,'user_id':u['id'],'reactions':msgj(m)['reactions']})
 return web.json_response({'reactions':msgj(m)['reactions']})
async def delete_reaction(req):
 u=require_user(req); c=connect()
 try: mid=int(req.match_info['id'])
 except: raise HTTPError(404,'message not found')
 m=c.execute('SELECT * FROM messages WHERE id=? AND deleted=0',(mid,)).fetchone()
 if not m: raise HTTPError(404,'message not found')
 access(m['channel_id'],u,True); e=req.match_info['emoji']
 changed=c.execute('DELETE FROM reactions WHERE message_id=? AND user_id=? AND emoji=?',(mid,u['id'],e)).rowcount
 if changed: emit_event(m['channel_id'],'reaction.removed',{'message_id':mid,'emoji':e,'user_id':u['id'],'reactions':msgj(m)['reactions']})
 return web.json_response({'reactions':msgj(m)['reactions']})
async def upload_file(req):
 u=require_user(req)
 if not req.content_type.startswith('multipart/'): raise HTTPError(400,'multipart required')
 try: rd=await req.multipart()
 except: raise HTTPError(400,'invalid multipart')
 part=None
 while True:
  x=await rd.next()
  if x is None: break
  if x.name=='file': part=x; break
 if part is None: raise HTTPError(400,'file required')
 os.makedirs('/app/data/files',exist_ok=True); tmp='/app/data/files/.upload-'+secrets.token_hex(8); n=0
 with open(tmp,'wb') as f:
  while True:
   b=await part.read_chunk()
   if not b: break
   n+=len(b)
   if n>10*1024*1024: f.close(); os.unlink(tmp); raise HTTPError(413,'file too large')
   f.write(b)
 c=connect(); ct=part.headers.get('Content-Type','application/octet-stream'); c.execute('INSERT INTO files(uploader_id,filename,content_type,size,created_at) VALUES(?,?,?,?,?)',(u['id'],part.filename or 'file',ct,n,now_iso())); r=c.execute('SELECT * FROM files WHERE id=last_insert_rowid()').fetchone(); os.rename(tmp,'/app/data/files/'+str(r['id']))
 return web.json_response({'file':filej(r)},status=201)
async def file_route(req):
 require_user(req)
 try: fid=int(req.match_info['id'])
 except: raise HTTPError(404,'file not found')
 r=connect().execute('SELECT * FROM files WHERE id=?',(fid,)).fetchone()
 if not r: raise HTTPError(404,'file not found')
 if req.path.endswith('/download'):
  return web.Response(body=open('/app/data/files/'+str(fid),'rb').read(),content_type=r['content_type'],headers={'Content-Disposition':'attachment; filename="'+r['filename'].replace('"','')+'"'} )
 return web.json_response({'file':filej(r)})
def groupj(r):
 c=connect(); return {'id':r['id'],'handle':r['handle'],'name':r['name'],'member_user_ids':sorted(x[0] for x in c.execute('SELECT user_id FROM group_members WHERE group_id=?',(r['id'],)))}
async def groups_route(req):
 u=require_user(req); c=connect(); w=c.execute('SELECT * FROM workspaces WHERE slug=?',(req.match_info['slug'],)).fetchone()
 if not w: raise HTTPError(404,'workspace not found')
 if not c.execute('SELECT 1 FROM workspace_members WHERE workspace_id=? AND user_id=?',(w['id'],u['id'])).fetchone(): raise HTTPError(403,'forbidden')
 handle=req.match_info.get('handle')
 if req.method=='GET':
  return web.json_response({'groups':[groupj(x) for x in c.execute('SELECT * FROM groups WHERE workspace_id=?',(w['id'],))]})
 if req.method=='POST':
  b=await read_json(req); h=b.get('handle',''); name=b.get('name',''); ids=b.get('user_ids',[])
  if not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,30}[a-z0-9])?',h) or h in ('here','channel') or not isinstance(name,str) or not name or not isinstance(ids,list): raise HTTPError(400,'invalid group')
  members={x[0] for x in c.execute('SELECT user_id FROM workspace_members WHERE workspace_id=?',(w['id'],))}
  if any(not isinstance(x,int) or x not in members for x in ids): raise HTTPError(400,'invalid members')
  if c.execute('SELECT 1 FROM groups WHERE workspace_id=? AND handle=?',(w['id'],h)).fetchone(): raise HTTPError(409,'duplicate group')
  c.execute('INSERT INTO groups(workspace_id,handle,name,created_by) VALUES(?,?,?,?)',(w['id'],h,name,u['id'])); g=c.execute('SELECT * FROM groups WHERE id=last_insert_rowid()').fetchone()
  c.executemany('INSERT INTO group_members VALUES(?,?)',[(g['id'],x) for x in ids]); return web.json_response({'group':groupj(g)},status=201)
 g=c.execute('SELECT * FROM groups WHERE workspace_id=? AND handle=?',(w['id'],handle)).fetchone()
 if not g:
  if req.method=='DELETE': return web.json_response({'deleted':True})
  raise HTTPError(404,'group not found')
 if g['created_by']!=u['id'] and w['owner_id']!=u['id']: raise HTTPError(403,'forbidden')
 if req.method=='DELETE':
  c.execute('DELETE FROM groups WHERE id=?',(g['id'],)); return web.json_response({'deleted':True})
 b=await read_json(req)
 if 'name' in b:
  if not isinstance(b['name'],str) or not b['name']: raise HTTPError(400,'invalid name')
  c.execute('UPDATE groups SET name=? WHERE id=?',(b['name'],g['id']))
 if 'user_ids' in b:
  ids=b['user_ids']; members={x[0] for x in c.execute('SELECT user_id FROM workspace_members WHERE workspace_id=?',(w['id'],))}
  if not isinstance(ids,list) or any(x not in members for x in ids): raise HTTPError(400,'invalid members')
  c.execute('DELETE FROM group_members WHERE group_id=?',(g['id'],)); c.executemany('INSERT INTO group_members VALUES(?,?)',[(g['id'],x) for x in ids])
 return web.json_response({'group':groupj(c.execute('SELECT * FROM groups WHERE id=?',(g['id'],)).fetchone())})
async def dms(req):
 u=require_user(req); b=await read_json(req); v=b.get('user_id')
 if not isinstance(v,int): raise HTTPError(400,'user_id')
 if not connect().execute('SELECT 1 FROM users WHERE id=?',(v,)).fetchone(): raise HTTPError(404,'user')
 a,z=sorted((u['id'],v)); c=connect(); x=c.execute('SELECT channel_id FROM dm_pairs WHERE user_low=? AND user_high=?',(a,z)).fetchone()
 if x:return web.json_response({'channel_id':x[0]})
 c.execute('INSERT INTO channels(name,is_private,is_dm,created_at) VALUES(?,?,?,?)',(f'dm-{a}-{z}',1,1,now_iso())); cid=c.execute('SELECT last_insert_rowid()').fetchone()[0]; c.execute('INSERT INTO dm_pairs VALUES(?,?,?)',(a,z,cid)); c.executemany('INSERT INTO channel_members VALUES(?,?)',[(cid,a),(cid,z)]); return web.json_response({'channel_id':cid})
async def ws(req):
 if req.query.get('token') and not req.headers.get('Authorization'):
  tok=req.query['token']
  urow=connect().execute('SELECT u.* FROM tokens t JOIN users u ON u.id=t.user_id WHERE t.token=?',(tok,)).fetchone()
  if not urow: raise HTTPError(401,'invalid token')
  u=urow
 else:
  u=require_user(req)
 w=web.WebSocketResponse(); await w.prepare(req); sockets.add(w); subscriptions[w]=set(); connid=uuid.uuid4().hex; connect().execute('INSERT INTO ws_presence VALUES(?,?,?)',(connid,NODE,u['id'])); cid=None
 try:
  async for x in w:
   if x.type==WSMsgType.TEXT:
    b=json.loads(x.data); cid=b.get('channel_id')
    if b.get('type')=='subscribe': subscriptions[w].add(cid)
    if b.get('type')=='subscribe':
     h=connect().execute('SELECT last_event_id FROM channels WHERE id=?',(cid,)).fetchone(); await w.send_json({'type':'subscribed','channel_id':cid,'head_event_id':h[0] if h else 0})
    if b.get('type')=='resume':
     for e in connect().execute('SELECT payload FROM events WHERE channel_id=? AND event_id>? ORDER BY event_id',(cid,b.get('since_event_id',0))): await w.send_str(e[0])
     h=connect().execute('SELECT last_event_id FROM channels WHERE id=?',(cid,)).fetchone(); await w.send_json({'type':'resumed','channel_id':cid,'head_event_id':h[0] if h else 0})
 finally: sockets.discard(w); subscriptions.pop(w,None); connect().execute('DELETE FROM ws_presence WHERE conn_id=?',(connid,))
 return w
async def start_pump(app):
 app['pump_task']=asyncio.create_task(pump(app))
async def pump(app):
 last=0; blast=0
 while True:
  c=connect()
  for e in c.execute('SELECT seq,payload FROM events WHERE seq>? ORDER BY seq',(last,)):
   last=e['seq']; p=json.loads(e['payload'])
   for s in list(sockets):
    try:
     if p.get('channel_id') in subscriptions.get(s,set()): await s.send_str(e['payload'])
    except: pass
  for e in c.execute('SELECT seq,payload FROM broadcasts WHERE seq>? ORDER BY seq',(blast,)):
   blast=e['seq']
   for s in list(sockets):
    try: await s.send_str(e['payload'])
    except: pass
  await asyncio.sleep(.05)
def setup(app):
 app.router.add_get('/api/health',health); app.router.add_post('/api/auth/register',register); app.router.add_post('/api/auth/login',login); app.router.add_get('/api/auth/me',me); app.router.add_get('/api/users/{id}',user_route); app.router.add_patch('/api/users/me',user_route)
 app.router.add_route('*','/api/workspaces',workspaces); app.router.add_route('*','/api/workspaces/{slug}',workspace); app.router.add_route('*','/api/workspaces/{slug}/groups',groups_route); app.router.add_route('*','/api/workspaces/{slug}/groups/{handle}',groups_route); app.router.add_route('*','/api/workspaces/{slug}/channels',workspace); app.router.add_get('/api/workspaces/{slug}/members',workspace)
 app.router.add_route('*','/api/channels/{id}/read',read_route); app.router.add_route('*','/api/channels/{id}/messages',channel); app.router.add_post('/api/channels/{id}/join',channel); app.router.add_post('/api/messages/{id}/reactions',post_reaction); app.router.add_delete('/api/messages/{id}/reactions/{emoji}',delete_reaction); app.router.add_post('/api/channels/{id}/archive',channel); app.router.add_post('/api/channels/{id}/unarchive',channel); app.router.add_post('/api/dms',dms); app.router.add_post('/api/files',upload_file); app.router.add_get('/api/files/{id}',file_route); app.router.add_get('/api/files/{id}/download',file_route); app.router.add_get('/api/ws',ws)
def main():
 global NODE
 p=argparse.ArgumentParser(); p.add_argument('--port',type=int); p.add_argument('--node-id',type=int); a=p.parse_args(); NODE=a.node_id; init_db(); app=web.Application(middlewares=[error_middleware],client_max_size=20*1024*1024); setup(app); app.on_startup.append(start_pump); web.run_app(app,host='0.0.0.0',port=a.port)
if __name__=='__main__': main()
