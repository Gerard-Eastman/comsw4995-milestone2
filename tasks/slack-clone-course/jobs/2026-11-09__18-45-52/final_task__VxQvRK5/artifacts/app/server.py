import argparse,asyncio,json,re,secrets,uuid,os
from aiohttp import web,WSMsgType
from db import connect,init_db,now_iso
from common import *
NODE=0
def auth(req): return require_user(req)
def wsobj(r):
 return {'id':r['id'],'slug':r['slug'],'name':r['name'],'owner_id':r['owner_id'],'join_mode':r['join_mode']}
def member(c,w,u): return c.execute('SELECT * FROM workspace_members WHERE workspace_id=? AND user_id=?',(w,u)).fetchone()
def can(c,ch,u):
 return bool(c.execute('SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?',(ch,u)).fetchone())
def getch(c,i):
 try: return c.execute('SELECT * FROM channels WHERE id=?',(int(i),)).fetchone()
 except: return None
async def health(req): return web.json_response({'status':'ok','node_id':NODE})
async def register(req):
 b=await read_json(req); n=b.get('username',''); p=b.get('password','')
 if not re.fullmatch(r'[A-Za-z0-9_]{1,32}',n) or len(p)<8: raise HTTPError(400,'invalid registration')
 c=connect()
 if c.execute('SELECT 1 FROM users WHERE username=?',(n,)).fetchone(): raise HTTPError(409,'username exists')
 cur=c.execute('INSERT INTO users(username,password,display_name) VALUES(?,?,?)',(n,p,b.get('display_name') or n)); uid=cur.lastrowid;t=secrets.token_urlsafe(24);c.execute('INSERT INTO tokens VALUES(?,?)',(t,uid));u=c.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone();c.close()
 return web.json_response({'user':user_to_json(u),'token':t},status=201)
async def login(req):
 b=await read_json(req);c=connect();u=c.execute('SELECT * FROM users WHERE username=? AND password=?',(b.get('username'),b.get('password'))).fetchone()
 if not u: raise HTTPError(401,'invalid credentials')
 t=secrets.token_urlsafe(24);c.execute('INSERT INTO tokens VALUES(?,?)',(t,u['id']));c.close()
 return web.json_response({'user':user_to_json(u),'token':t})
async def me(req): return web.json_response({'user':user_to_json(auth(req))})
async def create_ws(req):
 u=auth(req);b=await read_json(req);slug=b.get('slug','');name=b.get('name','')
 if not re.fullmatch(r'[a-z0-9-]{2,32}',slug) or not name: raise HTTPError(400,'invalid workspace')
 c=connect()
 if c.execute('SELECT 1 FROM workspaces WHERE slug=?',(slug,)).fetchone(): raise HTTPError(409,'workspace exists')
 t=now_iso(); wid=c.execute('INSERT INTO workspaces(slug,name,owner_id) VALUES(?,?,?)',(slug,name,u['id'])).lastrowid
 c.execute('INSERT INTO workspace_members VALUES(?,?,?)',(wid,u['id'],'owner'))
 cid=c.execute('INSERT INTO channels(workspace_id,name,created_at) VALUES(?,?,?)',(wid,'general',t)).lastrowid;c.execute('INSERT INTO channel_members VALUES(?,?)',(cid,u['id']))
 w=c.execute('SELECT * FROM workspaces WHERE id=?',(wid,)).fetchone();ch=c.execute('SELECT * FROM channels WHERE id=?',(cid,)).fetchone();c.close()
 return web.json_response({'workspace':wsobj(w),'general_channel':channel_json(ch)},status=201)
async def list_ws(req):
 u=auth(req);c=connect();rs=c.execute('SELECT w.* FROM workspaces w JOIN workspace_members m ON m.workspace_id=w.id WHERE m.user_id=?',(u['id'],)).fetchall();c.close()
 return web.json_response({'workspaces':[wsobj(x) for x in rs]})
async def get_ws(req):
 u=auth(req);c=connect();w=c.execute('SELECT * FROM workspaces WHERE slug=?',(req.match_info['slug'],)).fetchone()
 if not w: raise HTTPError(404,'not found')
 if not member(c,w['id'],u['id']): raise HTTPError(403,'not a member')
 cs=c.execute('SELECT * FROM channels WHERE workspace_id=? AND is_dm=0 AND is_archived=0',(w['id'],)).fetchall();c.close()
 return web.json_response({'workspace':wsobj(w),'channels':[channel_json(x) for x in cs],'read_state':[]})
async def members(req):
 u=auth(req);c=connect();w=c.execute('SELECT * FROM workspaces WHERE slug=?',(req.match_info['slug'],)).fetchone()
 if not w: raise HTTPError(404,'not found')
 if not member(c,w['id'],u['id']): raise HTTPError(403,'forbidden')
 rs=c.execute('SELECT m.*,u.* FROM workspace_members m JOIN users u ON u.id=m.user_id WHERE m.workspace_id=?',(w['id'],)).fetchall();c.close()
 return web.json_response({'members':[{'user_id':x['user_id'],'role':x['role'],'user':user_to_json(x)} for x in rs]})
async def create_ch(req):
 u=auth(req);c=connect();w=c.execute('SELECT * FROM workspaces WHERE slug=?',(req.match_info['slug'],)).fetchone()
 if not w: raise HTTPError(404,'not found')
 if not member(c,w['id'],u['id']): raise HTTPError(403,'forbidden')
 b=await read_json(req);n=b.get('name','')
 if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*',n) or len(n)>32: raise HTTPError(400,'invalid channel')
 if c.execute('SELECT 1 FROM channels WHERE workspace_id=? AND name=?',(w['id'],n)).fetchone(): raise HTTPError(409,'channel exists')
 cid=c.execute('INSERT INTO channels(workspace_id,name,is_private,topic,created_at) VALUES(?,?,?,?,?)',(w['id'],n,int(bool(b.get('is_private'))),b.get('topic',''),now_iso())).lastrowid;c.execute('INSERT INTO channel_members VALUES(?,?)',(cid,u['id']));r=c.execute('SELECT * FROM channels WHERE id=?',(cid,)).fetchone();c.close()
 emit_event(cid,'member.joined',{'user_id':u['id']})
 return web.json_response({'channel':channel_json(r)},status=201)
async def join(req):
 u=auth(req);c=connect();ch=getch(c,req.match_info['id'])
 if not ch: raise HTTPError(404,'not found')
 w=c.execute('SELECT * FROM workspaces WHERE id=?',(ch['workspace_id'],)).fetchone()
 if ch['is_private']: raise HTTPError(403,'private channel')
 if not member(c,w['id'],u['id']): c.execute('INSERT OR IGNORE INTO workspace_members VALUES(?,?,?)',(w['id'],u['id'],'member'))
 c.execute('INSERT OR IGNORE INTO channel_members VALUES(?,?)',(ch['id'],u['id']));c.close();emit_event(ch['id'],'member.joined',{'user_id':u['id']})
 return web.json_response({'channel':channel_json(ch)})
async def patch_ch(req):
 u=auth(req);c=connect();ch=getch(c,req.match_info['id'])
 if not ch: raise HTTPError(404,'not found')
 w=c.execute('SELECT * FROM workspaces WHERE id=?',(ch['workspace_id'],)).fetchone()
 if not can(c,ch['id'],u['id']) and w['owner_id']!=u['id']: raise HTTPError(403,'forbidden')
 b=await read_json(req)
 if len(b.get('topic',''))>250: raise HTTPError(400,'topic too long')
 c.execute('UPDATE channels SET topic=? WHERE id=?',(b.get('topic',''),ch['id']));r=getch(c,ch['id']);c.close();emit_event(ch['id'],'channel.updated',{'channel':channel_json(r)})
 return web.json_response({'channel':channel_json(r)})
async def archive(req):
 u=auth(req);c=connect();ch=getch(c,req.match_info['id'])
 if not ch: raise HTTPError(404,'not found')
 w=c.execute('SELECT * FROM workspaces WHERE id=?',(ch['workspace_id'],)).fetchone()
 if w['owner_id']!=u['id']: raise HTTPError(403,'forbidden')
 val=0 if req.path.endswith('unarchive') else 1;c.execute('UPDATE channels SET is_archived=? WHERE id=?',(val,ch['id']));r=getch(c,ch['id']);c.close();emit_event(ch['id'],'channel.unarchived' if not val else 'channel.archived',{'channel':channel_json(r)})
 return web.json_response({'channel':channel_json(r)})
async def post_msg(req):
 u=auth(req);c=connect();ch=getch(c,req.match_info['id'])
 if not ch: raise HTTPError(404,'not found')
 if not can(c,ch['id'],u['id']): raise HTTPError(403,'not a member')
 b=await read_json(req);body=b.get('body','')
 if not isinstance(body,str) or not body.strip(): raise HTTPError(400,'empty body')
 if body.startswith('//'):
  body=body[1:]
 elif body.startswith('/'):
  cmd,_,text=body[1:].partition(' '); text=text.strip()
  if cmd=='me':
   if not text: raise HTTPError(400,'/me requires text')
  elif cmd=='shrug':
   body=(text+' ' if text else '')+'¯\\_(ツ)_/¯'
  elif cmd=='topic':
   if len(text)>250: raise HTTPError(400,'topic too long')
   c.execute('UPDATE channels SET topic=? WHERE id=?',(text,ch['id']))
   r2=getch(c,ch['id']); c.close()
   emit_event(ch['id'],'channel.updated',{'channel':channel_json(r2)})
   return web.json_response({'message':None,'channel':channel_json(r2)},status=201)
  elif cmd=='invite':
   if not text.startswith('@') or not text[1:]: raise HTTPError(400,'username required')
   inv=c.execute('SELECT * FROM users WHERE username=?',(text[1:],)).fetchone()
   if not inv: raise HTTPError(404,'user not found')
   w=c.execute('SELECT * FROM workspaces WHERE id=?',(ch['workspace_id'],)).fetchone()
   if not c.execute('SELECT 1 FROM workspace_members WHERE workspace_id=? AND user_id=?',(w['id'],inv['id'])).fetchone(): raise HTTPError(400,'not workspace member')
   c.execute('INSERT OR IGNORE INTO channel_members VALUES(?,?)',(ch['id'],inv['id']))
   c.close(); emit_event(ch['id'],'member.joined',{'user_id':inv['id']})
   return web.json_response({'message':None,'invited_user':user_to_json(inv)},status=201)
  elif cmd in ('archive','unarchive'):
   w=c.execute('SELECT * FROM workspaces WHERE id=?',(ch['workspace_id'],)).fetchone()
   if w['owner_id']!=u['id']: raise HTTPError(403,'forbidden')
   val=1 if cmd=='archive' else 0
   c.execute('UPDATE channels SET is_archived=? WHERE id=?',(val,ch['id']))
   r2=getch(c,ch['id']); c.close()
   emit_event(ch['id'],'channel.archived' if val else 'channel.unarchived',{'channel':channel_json(r2)})
   return web.json_response({'message':None,'channel':channel_json(r2)},status=201)
  else: raise HTTPError(400,'unknown command')
 if ch['is_archived']: raise HTTPError(423,'channel archived')
 fids=b.get('file_ids',[])
 if not isinstance(fids,list) or any(type(x) is not int for x in fids): raise HTTPError(400,'invalid file_ids')
 if len(set(fids))!=len(fids): raise HTTPError(400,'invalid file_ids')
 for fid in fids:
  fr=c.execute('SELECT * FROM files WHERE id=?',(fid,)).fetchone()
  if not fr or fr['uploader_id']!=u['id'] or fr['message_id'] is not None: raise HTTPError(400,'invalid file')
 parent=b.get('parent_id'); mentions=resolve_mentions(c,body,ch,u['id'])
 if False:
  if x=='channel': mentions += [z[0] for z in c.execute('SELECT user_id FROM channel_members WHERE channel_id=? AND user_id!=?',(ch['id'],u['id']))]
  else:
   z=c.execute('SELECT id FROM users WHERE username=?',(x,)).fetchone()
   if z and z[0]!=u['id'] and c.execute('SELECT 1 FROM workspace_members WHERE workspace_id=? AND user_id=?',(ch['workspace_id'],z[0])).fetchone(): mentions.append(z[0])
 mentions=list(dict.fromkeys(mentions));mid=c.execute('INSERT INTO messages(channel_id,author_id,body,parent_id,created_at,mentions) VALUES(?,?,?,?,?,?)',(ch['id'],u['id'],body,parent,now_iso(),json.dumps(mentions))).lastrowid;r=c.execute('SELECT * FROM messages WHERE id=?',(mid,)).fetchone()
 for fid in fids: c.execute('UPDATE files SET message_id=? WHERE id=?',(mid,fid))
 m=msg_json(c,r);c.close();emit_event(ch['id'],'message.reply' if parent else 'message.created',{'message':m})
 return web.json_response({'message':m},status=201)
async def messages(req):
 u=auth(req);c=connect();ch=getch(c,req.match_info['id'])
 if not ch: raise HTTPError(404,'not found')
 if not can(c,ch['id'],u['id']): raise HTTPError(403,'forbidden')
 lim=parse_limit(req.query);cur=decode_cursor(req.query['cursor']) if req.query.get('cursor') else None
 q='SELECT * FROM messages WHERE channel_id=? AND parent_id IS NULL AND deleted=0 '+('AND id<? ' if cur else '')+'ORDER BY id DESC LIMIT ?';args=[ch['id']]+(([cur] if cur else []))+[lim+1];rs=c.execute(q,args).fetchall();out=[msg_json(c,x) for x in rs[:lim]];nextc=encode_cursor(rs[lim-1]['id']) if len(rs)>lim else None;c.close()
 return web.json_response({'messages':out,'next_cursor':nextc})
async def replies(req):
 u=auth(req);c=connect();r=c.execute('SELECT * FROM messages WHERE id=?',(req.match_info['id'],)).fetchone()
 if not r: raise HTTPError(404,'not found')
 rs=c.execute('SELECT * FROM messages WHERE parent_id=? AND deleted=0 ORDER BY id',(r['id'],)).fetchall();out=[msg_json(c,x) for x in rs];c.close();return web.json_response({'replies':out,'next_cursor':None})
def reaction_list(c,mid):
 out=[]
 for x in c.execute('SELECT emoji FROM reactions WHERE message_id=? GROUP BY emoji ORDER BY MIN(rowid)',(mid,)).fetchall():
  ids=[z[0] for z in c.execute('SELECT user_id FROM reactions WHERE message_id=? AND emoji=? ORDER BY rowid',(mid,x['emoji'])).fetchall()]
  out.append({'emoji':x['emoji'],'count':len(ids),'user_ids':ids})
 return out
async def react(req):
 u=auth(req);c=connect()
 try: mid=int(req.match_info['id'])
 except: raise HTTPError(404,'not found')
 r=c.execute('SELECT * FROM messages WHERE id=? AND deleted=0',(mid,)).fetchone()
 if not r: raise HTTPError(404,'not found')
 ch=getch(c,r['channel_id'])
 if not can(c,ch['id'],u['id']): raise HTTPError(403,'forbidden')
 if ch['is_archived']: raise HTTPError(423,'channel archived')
 b=await read_json(req);em=b.get('emoji')
 if not isinstance(em,str) or not em or len(em)>64: raise HTTPError(400,'invalid emoji')
 old=c.execute('SELECT 1 FROM reactions WHERE message_id=? AND user_id=? AND emoji=?',(mid,u['id'],em)).fetchone()
 if not old: c.execute('INSERT INTO reactions(message_id,user_id,emoji,created_at) VALUES(?,?,?,?)',(mid,u['id'],em,now_iso()))
 reactions=reaction_list(c,mid);c.close()
 if not old: emit_event(ch['id'],'reaction.added',{'message_id':mid,'emoji':em,'user_id':u['id'],'reactions':reactions})
 return web.json_response({'reactions':reactions})
async def unreact(req):
 u=auth(req);c=connect()
 try: mid=int(req.match_info['id'])
 except: raise HTTPError(404,'not found')
 r=c.execute('SELECT * FROM messages WHERE id=? AND deleted=0',(mid,)).fetchone()
 if not r: raise HTTPError(404,'not found')
 ch=getch(c,r['channel_id'])
 if not can(c,ch['id'],u['id']): raise HTTPError(403,'forbidden')
 if ch['is_archived']: raise HTTPError(423,'channel archived')
 em=req.match_info['emoji']; old=c.execute('SELECT 1 FROM reactions WHERE message_id=? AND user_id=? AND emoji=?',(mid,u['id'],em)).fetchone()
 if old: c.execute('DELETE FROM reactions WHERE message_id=? AND user_id=? AND emoji=?',(mid,u['id'],em))
 reactions=reaction_list(c,mid);c.close()
 if old: emit_event(ch['id'],'reaction.removed',{'message_id':mid,'emoji':em,'user_id':u['id'],'reactions':reactions})
 return web.json_response({'reactions':reactions})
def file_json(r):
 return {'id':r['id'],'uploader_id':r['uploader_id'],'filename':r['filename'],'content_type':r['content_type'],'size':r['size'],'created_at':r['created_at']}
async def upload_file(req):
 u=auth(req)
 if not req.content_type.startswith('multipart/'): raise HTTPError(400,'multipart required')
 try: reader=await req.multipart()
 except: raise HTTPError(400,'multipart required')
 part=None
 while True:
  x=await reader.next()
  if x is None: break
  if x.name=='file': part=x; break
 if part is None: raise HTTPError(400,'file required')
 fn=part.filename or 'upload'; ct=part.headers.get('Content-Type','application/octet-stream')
 c=connect(); cur=c.execute('INSERT INTO files(uploader_id,filename,content_type,size,created_at) VALUES(?,?,?,?,?)',(u['id'],fn,ct,0,now_iso())); fid=cur.lastrowid
 path=f'/app/data/files/{fid}'; total=0; too=False
 try:
  with open(path,'wb') as f:
   while True:
    chunk=await part.read_chunk()
    if not chunk: break
    total+=len(chunk)
    if total>10*1024*1024: too=True; break
    f.write(chunk)
  if too:
   try: os.remove(path)
   except: pass
   c.execute('DELETE FROM files WHERE id=?',(fid,)); c.close(); raise HTTPError(413,'file too large')
  c.execute('UPDATE files SET size=? WHERE id=?',(total,fid)); r=c.execute('SELECT * FROM files WHERE id=?',(fid,)).fetchone();c.close()
  return web.json_response({'file':file_json(r)},status=201)
 except HTTPError: raise
 except Exception:
  c.close()
  try: os.remove(path)
  except: pass
  raise
async def get_file(req):
 u=auth(req)
 try: fid=int(req.match_info['id'])
 except: raise HTTPError(404,'not found')
 c=connect();r=c.execute('SELECT * FROM files WHERE id=?',(fid,)).fetchone();c.close()
 if not r: raise HTTPError(404,'not found')
 return web.json_response({'file':file_json(r)})
async def download_file(req):
 u=auth(req)
 try: fid=int(req.match_info['id'])
 except: raise HTTPError(404,'not found')
 c=connect();r=c.execute('SELECT * FROM files WHERE id=?',(fid,)).fetchone();c.close()
 if not r: raise HTTPError(404,'not found')
 try: data=open(f'/app/data/files/{fid}','rb').read()
 except: raise HTTPError(404,'not found')
 return web.Response(body=data,content_type=r['content_type'],headers={'Content-Disposition':f'attachment; filename="{r["filename"]}"'})
MENTION_RE=re.compile(r"(?<![A-Za-z0-9_@.])@([A-Za-z0-9_](?:[A-Za-z0-9_-]*[A-Za-z0-9_])?)(?![A-Za-z0-9_@-])(?!\.[A-Za-z0-9])")
def group_json(c,r):
 ids=[x[0] for x in c.execute('SELECT user_id FROM group_members WHERE group_id=? ORDER BY user_id',(r['id'],)).fetchall()]
 return {'id':r['id'],'handle':r['handle'],'name':r['name'],'member_user_ids':ids}
def resolve_mentions(c,body,ch,author):
 out=[]
 members=[x[0] for x in c.execute('SELECT user_id FROM channel_members WHERE channel_id=?',(ch['id'],)).fetchall()]
 for name in MENTION_RE.findall(body):
  ids=[]
  if name=='channel': ids=members
  elif name=='here':
   ids=[x[0] for x in c.execute('SELECT DISTINCT user_id FROM ws_presence WHERE user_id IN (%s)'%(','.join('?'*len(members)) if members else 'NULL'),members).fetchall()] if members else []
  else:
   x=c.execute('SELECT id FROM users WHERE username=?',(name,)).fetchone()
   if x and c.execute('SELECT 1 FROM workspace_members WHERE workspace_id=? AND user_id=?',(ch['workspace_id'],x[0])).fetchone(): ids=[x[0]]
   else:
    g=c.execute('SELECT id FROM groups WHERE workspace_id=? AND handle=?',(ch['workspace_id'],name)).fetchone()
    if g: ids=[x[0] for x in c.execute('SELECT user_id FROM group_members WHERE group_id=? AND user_id IN (SELECT user_id FROM channel_members WHERE channel_id=?) ORDER BY user_id',(g[0],ch['id'])).fetchall()]
  for i in ids:
   if i!=author and i not in out: out.append(i)
 return out
async def groups(req):
 u=auth(req); c=connect(); w=c.execute('SELECT * FROM workspaces WHERE slug=?',(req.match_info['slug'],)).fetchone()
 if not w: raise HTTPError(404,'not found')
 if not member(c,w['id'],u['id']): raise HTTPError(403,'forbidden')
 rs=c.execute('SELECT * FROM groups WHERE workspace_id=? ORDER BY id',(w['id'],)).fetchall()
 if req.method=='GET': out=[group_json(c,r) for r in rs]; c.close(); return web.json_response({'groups':out})
 b=await read_json(req); h=b.get('handle'); name=b.get('name'); ids=b.get('user_ids',[])
 if not isinstance(h,str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,30}[a-z0-9]',h) or h in ('here','channel') or not isinstance(name,str) or not name or not isinstance(ids,list): raise HTTPError(400,'invalid group')
 if any(type(i) is not int or not member(c,w['id'],i) for i in ids): raise HTTPError(400,'invalid user_ids')
 if c.execute('SELECT 1 FROM groups WHERE workspace_id=? AND handle=?',(w['id'],h)).fetchone(): raise HTTPError(409,'group exists')
 gid=c.execute('INSERT INTO groups(workspace_id,handle,name,created_by) VALUES(?,?,?,?)',(w['id'],h,name,u['id'])).lastrowid
 for i in sorted(set(ids)): c.execute('INSERT INTO group_members VALUES(?,?)',(gid,i))
 r=c.execute('SELECT * FROM groups WHERE id=?',(gid,)).fetchone(); out=group_json(c,r);c.close();return web.json_response({'group':out},status=201)
async def group_item(req):
 u=auth(req); c=connect(); w=c.execute('SELECT * FROM workspaces WHERE slug=?',(req.match_info['slug'],)).fetchone()
 if not w: raise HTTPError(404,'not found')
 if not member(c,w['id'],u['id']): raise HTTPError(403,'forbidden')
 g=c.execute('SELECT * FROM groups WHERE workspace_id=? AND handle=?',(w['id'],req.match_info['handle'])).fetchone()
 if req.method=='DELETE':
  if not g: c.close(); return web.json_response({'deleted':True})
  if g['created_by']!=u['id'] and w['owner_id']!=u['id']: raise HTTPError(403,'forbidden')
  c.execute('DELETE FROM group_members WHERE group_id=?',(g['id'],));c.execute('DELETE FROM groups WHERE id=?',(g['id'],));c.close();return web.json_response({'deleted':True})
 if not g: raise HTTPError(404,'not found')
 if g['created_by']!=u['id'] and w['owner_id']!=u['id']: raise HTTPError(403,'forbidden')
 b=await read_json(req)
 if 'name' in b and (not isinstance(b['name'],str) or not b['name']): raise HTTPError(400,'invalid name')
 if 'user_ids' in b and (not isinstance(b['user_ids'],list) or any(type(i) is not int or not member(c,w['id'],i) for i in b['user_ids'])): raise HTTPError(400,'invalid user_ids')
 if 'name' in b: c.execute('UPDATE groups SET name=? WHERE id=?',(b['name'],g['id']))
 if 'user_ids' in b:
  c.execute('DELETE FROM group_members WHERE group_id=?',(g['id'],))
  for i in sorted(set(b['user_ids'])): c.execute('INSERT INTO group_members VALUES(?,?)',(g['id'],i))
 r=c.execute('SELECT * FROM groups WHERE id=?',(g['id'],)).fetchone();out=group_json(c,r);c.close();return web.json_response({'group':out})
async def dm(req):
 u=auth(req);b=await read_json(req);v=b.get('user_id')
 if type(v) is not int: raise HTTPError(400,'invalid user_id')
 c=connect()
 if not c.execute('SELECT 1 FROM users WHERE id=?',(v,)).fetchone(): raise HTTPError(404,'user not found')
 if v==u['id']: raise HTTPError(400,'invalid user_id')
 a,z=sorted((u['id'],v)); pair=c.execute('SELECT channel_id FROM dm_pairs WHERE user_low=? AND user_high=?',(a,z)).fetchone()
 if pair:
  cid=pair[0]
 else:
  cid=c.execute('INSERT INTO channels(workspace_id,name,is_private,is_dm,created_at) VALUES(NULL,?,?,1,?)',(None,f'dm-{a}-{z}',now_iso())).lastrowid
  c.execute('INSERT INTO channel_members VALUES(?,?)',(cid,a));c.execute('INSERT INTO channel_members VALUES(?,?)',(cid,z))
  c.execute('INSERT INTO dm_pairs VALUES(?,?,?)',(a,z,cid))
 c.close();return web.json_response({'channel_id':cid})
async def read_channel(req):
 u=auth(req); c=connect(); ch=getch(c,req.match_info['id'])
 if not ch: raise HTTPError(404,'not found')
 if not can(c,ch['id'],u['id']): raise HTTPError(403,'forbidden')
 st=c.execute('SELECT * FROM read_state WHERE user_id=? AND channel_id=?',(u['id'],ch['id'])).fetchone()
 last=st['last_read_event_id'] if st else 0
 mentioned=0
 for x in c.execute('SELECT author_id,mentions FROM messages WHERE channel_id=? AND deleted=0',(ch['id'],)).fetchall():
  try: ids=json.loads(x['mentions'] or '[]')
  except: ids=[]
  if x['author_id']!=u['id'] and u['id'] in ids: mentioned+=1
 head=c.execute('SELECT last_event_id FROM channels WHERE id=?',(ch['id'],)).fetchone()[0]
 c.close()
 rs={'channel_id':ch['id'],'last_read_event_id':last,'unread_count':max(0,head-last),'mention_count':mentioned}
 return web.json_response({'read_state':rs})
async def mark_read(req):
 u=auth(req); c=connect(); ch=getch(c,req.match_info['id'])
 if not ch: raise HTTPError(404,'not found')
 if not can(c,ch['id'],u['id']): raise HTTPError(403,'forbidden')
 b=await read_json(req); n=b.get('last_read_event_id')
 if type(n) is not int: raise HTTPError(400,'invalid event id')
 old=c.execute('SELECT last_read_event_id FROM read_state WHERE user_id=? AND channel_id=?',(u['id'],ch['id'])).fetchone()
 if old: n=max(n,old[0]); c.execute('UPDATE read_state SET last_read_event_id=? WHERE user_id=? AND channel_id=?',(n,u['id'],ch['id']))
 else: c.execute('INSERT INTO read_state VALUES(?,?,?)',(u['id'],ch['id'],n))
 c.close()
 return await read_channel(req)
def validate_profile(b):
 import zoneinfo
 allowed={'display_name','timezone','avatar_url','status_text','status_emoji'}
 out={k:v for k,v in b.items() if k in allowed}
 for k,v in out.items():
  if not isinstance(v,str): raise HTTPError(400,'invalid profile')
 if 'display_name' in out and not 1<=len(out['display_name'])<=80: raise HTTPError(400,'invalid display_name')
 if 'status_text' in out and len(out['status_text'])>100: raise HTTPError(400,'invalid status_text')
 if 'status_emoji' in out and len(out['status_emoji'])>64: raise HTTPError(400,'invalid status_emoji')
 if 'avatar_url' in out and len(out['avatar_url'])>1024: raise HTTPError(400,'invalid avatar_url')
 if 'timezone' in out:
  try: zoneinfo.ZoneInfo(out['timezone'])
  except: raise HTTPError(400,'invalid timezone')
 return out
async def get_user(req):
 auth(req)
 try: uid=int(req.match_info['id'])
 except: raise HTTPError(404,'not found')
 c=connect(); x=c.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone(); c.close()
 if not x: raise HTTPError(404,'not found')
 return web.json_response({'user':user_to_json(x)})
async def profile(req):
 u=auth(req); vals=validate_profile(await read_json(req)); c=connect()
 for k,v in vals.items(): c.execute(f'UPDATE users SET {k}=? WHERE id=?',(v,u['id']))
 x=c.execute('SELECT * FROM users WHERE id=?',(u['id'],)).fetchone(); c.close()
 out=user_to_json(x); broadcast_global({'type':'user.updated','user':out})
 return web.json_response({'user':out})
async def ws_handler(req):
 t=req.query.get('token',''); c=connect()
 u=c.execute('SELECT u.* FROM tokens t JOIN users u ON u.id=t.user_id WHERE t.token=?',(t,)).fetchone(); c.close()
 if not u: raise HTTPError(401,'invalid token')
 ws=web.WebSocketResponse(); await ws.prepare(req); subs=set(); conn_id=uuid.uuid4().hex
 c=connect(); c.execute('INSERT OR REPLACE INTO ws_presence VALUES(?,?,?)',(conn_id,NODE,u['id'])); c.close()
 req.app['sockets'].append((ws,subs))
 try:
  async for msg in ws:
   if msg.type!=WSMsgType.TEXT: continue
   b=json.loads(msg.data); typ=b.get('type'); cid=b.get('channel_id')
   if typ=='subscribe':
    subs.add(cid); c=connect(); h=c.execute('SELECT last_event_id FROM channels WHERE id=?',(cid,)).fetchone(); c.close()
    await ws.send_json({'type':'subscribed','channel_id':cid,'head_event_id':h[0] if h else 0})
   elif typ=='resume':
    c=connect(); rs=c.execute('SELECT payload FROM events WHERE channel_id=? AND event_id>? ORDER BY event_id',(cid,b.get('since_event_id',0))).fetchall(); h=c.execute('SELECT last_event_id FROM channels WHERE id=?',(cid,)).fetchone(); c.close()
    for x in rs: await ws.send_str(x[0])
    subs.add(cid); await ws.send_json({'type':'resumed','channel_id':cid,'head_event_id':h[0] if h else 0})
 finally:
  c=connect(); c.execute('DELETE FROM ws_presence WHERE conn_id=?',(conn_id,)); c.close()
  try: req.app['sockets'].remove((ws,subs))
  except ValueError: pass
 return ws
async def pump(app):
 seen=0; bseen=0
 while True:
  try:
   c=connect()
   rs=c.execute('SELECT seq,payload,channel_id FROM events WHERE seq>? ORDER BY seq',(seen,)).fetchall()
   bs=c.execute('SELECT seq,payload FROM broadcasts WHERE seq>? ORDER BY seq',(bseen,)).fetchall()
   if rs: seen=rs[-1]['seq']
   if bs: bseen=bs[-1]['seq']
   c.close()
   for x in rs:
    for w,subs in list(app['sockets']):
     if x['channel_id'] in subs:
      try: await w.send_str(x['payload'])
      except: pass
   for x in bs:
    for w,subs in list(app['sockets']):
     try: await w.send_str(x['payload'])
     except: pass
  except Exception as e:
   open('/tmp/pump-error.log','a').write(repr(e)+'\n')
  await asyncio.sleep(.05)
async def on_start(app): app['sockets']=[];app['pump']=asyncio.create_task(pump(app))
def make():
 app=web.Application(middlewares=[error_middleware],client_max_size=20*1024*1024);app.router.add_get('/api/health',health);app.router.add_post('/api/auth/register',register);app.router.add_post('/api/auth/login',login);app.router.add_get('/api/auth/me',me);app.router.add_post('/api/workspaces',create_ws);app.router.add_get('/api/workspaces',list_ws);app.router.add_get('/api/workspaces/{slug}',get_ws);app.router.add_get('/api/workspaces/{slug}/members',members);app.router.add_get('/api/workspaces/{slug}/groups',groups);app.router.add_post('/api/workspaces/{slug}/groups',groups);app.router.add_patch('/api/workspaces/{slug}/groups/{handle}',group_item);app.router.add_delete('/api/workspaces/{slug}/groups/{handle}',group_item);app.router.add_post('/api/workspaces/{slug}/channels',create_ch);app.router.add_post('/api/channels/{id}/join',join);app.router.add_patch('/api/channels/{id}',patch_ch);app.router.add_post('/api/channels/{id}/archive',archive);app.router.add_post('/api/channels/{id}/unarchive',archive);app.router.add_post('/api/channels/{id}/messages',post_msg);app.router.add_get('/api/channels/{id}/messages',messages);app.router.add_get('/api/messages/{id}/replies',replies);app.router.add_post('/api/messages/{id}/reactions',react);app.router.add_delete('/api/messages/{id}/reactions/{emoji}',unreact);app.router.add_post('/api/dms',dm);app.router.add_post('/api/files',upload_file);app.router.add_get('/api/files/{id}',get_file);app.router.add_get('/api/files/{id}/download',download_file);app.router.add_get('/api/users/{id}',get_user);app.router.add_patch('/api/users/me',profile);app.router.add_get('/api/channels/{id}/read',read_channel);app.router.add_post('/api/channels/{id}/read',mark_read);app.router.add_get('/api/ws',ws_handler);app.on_startup.append(on_start);return app
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--port',type=int);p.add_argument('--node-id',type=int);a=p.parse_args();NODE=a.node_id;init_db();web.run_app(make(),host='0.0.0.0',port=a.port)
