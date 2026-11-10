import argparse,asyncio,json,uuid,re,secrets,hashlib
from aiohttp import web,WSMsgType
from db import connect,init_db,now_iso
from common import *
ap=argparse.ArgumentParser(); ap.add_argument('--port',type=int); ap.add_argument('--node-id',type=int); A=ap.parse_args()
NODE=A.node_id
clients={}
def jerr(s,x): raise HTTPError(s,x)
def member(c,w,u):
 return c.execute('SELECT role FROM workspace_members WHERE workspace_id=? AND user_id=?',(w,u)).fetchone()
def access(c,ch,u,write=False):
 m=c.execute('SELECT * FROM channels WHERE id=?',(ch,)).fetchone()
 if not m:jerr(404,'not found')
 if write and m['is_archived']:jerr(423,'archived')
 if m['workspace_id'] is None:
  if not c.execute('SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?',(ch,u)).fetchone(): jerr(403,'forbidden')
  return m
 if not member(c,m['workspace_id'],u): jerr(403,'forbidden')
 if not c.execute('SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?',(ch,u)).fetchone() and m['is_private']:jerr(403,'forbidden')
 return m

async def create_dm(r):
 u=await require_user(r);d=await read_json(r);other=d.get('user_id')
 if not isinstance(other,int):jerr(400,'invalid user_id')
 c=connect();v=c.execute('SELECT id FROM users WHERE id=?',(other,)).fetchone()
 if not v:c.close();jerr(404,'user not found')
 if other==u['id']: c.close();jerr(400,'invalid user_id')
 lo,hi=sorted((u['id'],other));row=c.execute('SELECT channel_id FROM dm_pairs WHERE user_low=? AND user_high=?',(lo,hi)).fetchone()
 if row:c.close();return web.json_response({'channel_id':row[0]})
 t=now_iso();c.execute('INSERT INTO channels(name,is_private,is_dm,created_at) VALUES(?,?,?,?)',(f'dm-{lo}-{hi}',1,1,t));cid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
 c.execute('INSERT INTO dm_pairs VALUES(?,?,?)',(lo,hi,cid));c.execute('INSERT INTO channel_members VALUES(?,?)',(cid,lo));c.execute('INSERT INTO channel_members VALUES(?,?)',(cid,hi));c.close()
 return web.json_response({'channel_id':cid})

def file_obj(x):
 return {'id':x['id'],'uploader_id':x['uploader_id'],'filename':x['filename'],'content_type':x['content_type'],'size':x['size'],'created_at':x['created_at']}
async def upload_file(r):
 u=await require_user(r)
 if not r.content_type.startswith('multipart/'):jerr(400,'multipart required')
 try: reader=await r.multipart()
 except: jerr(400,'invalid multipart')
 part=None
 while True:
  p=await reader.next()
  if p is None: break
  if p.name=='file': part=p; break
  while await p.read_chunk(): pass
 if part is None or not part.filename:jerr(400,'file required')
 import os
 fn=os.path.basename(part.filename);ct=part.headers.get('Content-Type','application/octet-stream');pathdir='/app/data/files';os.makedirs(pathdir,exist_ok=True)
 c=connect();c.execute('INSERT INTO files(uploader_id,filename,content_type,size,created_at,path) VALUES(?,?,?,?,?,?)',(u['id'],fn,ct,0,now_iso(),''));fid=c.execute('SELECT last_insert_rowid()').fetchone()[0];path=f'{pathdir}/{fid}';size=0
 try:
  with open(path,'wb') as f:
   while True:
    b=await part.read_chunk()
    if not b: break
    size+=len(b)
    if size>10*1024*1024:
     f.close();os.remove(path);c.execute('DELETE FROM files WHERE id=?',(fid,));c.close();jerr(413,'file too large')
    f.write(b)
  c.execute('UPDATE files SET size=?,path=? WHERE id=?',(size,path,fid));x=c.execute('SELECT * FROM files WHERE id=?',(fid,)).fetchone();c.close()
 except HTTPError: raise
 except: c.close(); raise
 return web.json_response({'file':file_obj(x)},status=201)
async def get_file(r):
 u=await require_user(r)
 try: fid=int(r.match_info['id'])
 except: jerr(404,'not found')
 c=connect();x=c.execute('SELECT * FROM files WHERE id=?',(fid,)).fetchone();c.close()
 if not x:jerr(404,'not found')
 return web.json_response({'file':file_obj(x)})
async def download_file(r):
 u=await require_user(r)
 try: fid=int(r.match_info['id'])
 except: jerr(404,'not found')
 c=connect();x=c.execute('SELECT * FROM files WHERE id=?',(fid,)).fetchone();c.close()
 if not x:jerr(404,'not found')
 import os
 if not os.path.exists(x['path']):jerr(404,'not found')
 return web.FileResponse(x['path'],headers={'Content-Type':x['content_type'],'Content-Disposition':f'attachment; filename="{x["filename"]}"'})


def group_json(c,g):
 ids=[x[0] for x in c.execute('SELECT user_id FROM group_members WHERE group_id=? ORDER BY user_id',(g['id'],))]
 return {'id':g['id'],'handle':g['handle'],'name':g['name'],'member_user_ids':ids}
def get_workspace(c,slug): return c.execute('SELECT * FROM workspaces WHERE slug=?',(slug,)).fetchone()
async def groups_list(r):
 u=await require_user(r);c=connect();w=get_workspace(c,r.match_info['slug'])
 if not w:c.close();jerr(404,'not found')
 if not member(c,w['id'],u['id']):c.close();jerr(403,'forbidden')
 gs=c.execute('SELECT * FROM groups WHERE workspace_id=? ORDER BY id',(w['id'],)).fetchall();out=[group_json(c,g) for g in gs];c.close();return web.json_response({'groups':out})
async def group_create(r):
 u=await require_user(r);d=await read_json(r);c=connect();w=get_workspace(c,r.match_info['slug'])
 if not w:c.close();jerr(404,'not found')
 if not member(c,w['id'],u['id']):c.close();jerr(403,'forbidden')
 h=d.get('handle');name=d.get('name');ids=d.get('user_ids',[])
 if not isinstance(h,str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,30}[a-z0-9]',h) or h in ('here','channel') or not isinstance(name,str) or not name or not isinstance(ids,list):c.close();jerr(400,'invalid group')
 valid={x[0] for x in c.execute('SELECT user_id FROM workspace_members WHERE workspace_id=?',(w['id'],))}
 if any(not isinstance(x,int) or x not in valid for x in ids):c.close();jerr(400,'invalid members')
 if c.execute('SELECT 1 FROM groups WHERE workspace_id=? AND handle=?',(w['id'],h)).fetchone():c.close();jerr(409,'duplicate handle')
 c.execute('INSERT INTO groups(workspace_id,handle,name,created_by) VALUES(?,?,?,?)',(w['id'],h,name,u['id']));gid=c.execute('SELECT last_insert_rowid()').fetchone()[0];c.executemany('INSERT INTO group_members VALUES(?,?)',[(gid,x) for x in ids]);g=c.execute('SELECT * FROM groups WHERE id=?',(gid,)).fetchone();out=group_json(c,g);c.close();return web.json_response({'group':out},status=201)
async def group_patch(r):
 u=await require_user(r);d=await read_json(r);c=connect();w=get_workspace(c,r.match_info['slug'])
 if not w:c.close();jerr(404,'not found')
 g=c.execute('SELECT * FROM groups WHERE workspace_id=? AND handle=?',(w['id'],r.match_info['handle'])).fetchone()
 if not g:c.close();jerr(404,'not found')
 if u['id']!=g['created_by'] and u['id']!=w['owner_id']:c.close();jerr(403,'forbidden')
 if 'name' in d and (not isinstance(d['name'],str) or not d['name']):c.close();jerr(400,'invalid name')
 if 'user_ids' in d:
  ids=d['user_ids'];valid={x[0] for x in c.execute('SELECT user_id FROM workspace_members WHERE workspace_id=?',(w['id'],))}
  if not isinstance(ids,list) or any(not isinstance(x,int) or x not in valid for x in ids):c.close();jerr(400,'invalid members')
  c.execute('DELETE FROM group_members WHERE group_id=?',(g['id'],));c.executemany('INSERT INTO group_members VALUES(?,?)',[(g['id'],x) for x in ids])
 if 'name' in d:c.execute('UPDATE groups SET name=? WHERE id=?',(d['name'],g['id']))
 g=c.execute('SELECT * FROM groups WHERE id=?',(g['id'],)).fetchone();out=group_json(c,g);c.close();return web.json_response({'group':out})
async def group_delete(r):
 u=await require_user(r);c=connect();w=get_workspace(c,r.match_info['slug'])
 if not w:c.close();jerr(404,'not found')
 g=c.execute('SELECT * FROM groups WHERE workspace_id=? AND handle=?',(w['id'],r.match_info['handle'])).fetchone()
 if g and u['id'] not in (g['created_by'],w['owner_id']):c.close();jerr(403,'forbidden')
 if g:c.execute('DELETE FROM group_members WHERE group_id=?',(g['id'],));c.execute('DELETE FROM groups WHERE id=?',(g['id'],))
 c.close();return web.json_response({'deleted':True})
def resolve_mentions(c,body,ch,author):
 import re
 out=[]
 for m in re.finditer(r'(?<![A-Za-z0-9_@.])@([A-Za-z0-9_](?:[A-Za-z0-9_-]*[A-Za-z0-9_])?)(?![A-Za-z0-9_@-])',body):
  n=m.group(1)
  if n=='channel': ids=[x[0] for x in c.execute('SELECT user_id FROM channel_members WHERE channel_id=?',(ch['id'],))]
  elif n=='here': ids=[x[0] for x in c.execute('SELECT cm.user_id FROM channel_members cm JOIN ws_presence p ON p.user_id=cm.user_id WHERE cm.channel_id=?',(ch['id'],))]
  else:
   x=c.execute('SELECT id FROM users WHERE username=?',(n,)).fetchone()
   ids=[x[0]] if x and ch['workspace_id'] and c.execute('SELECT 1 FROM workspace_members WHERE workspace_id=? AND user_id=?',(ch['workspace_id'],x[0])).fetchone() else []
   if not ids and ch['workspace_id']:
    g=c.execute('SELECT id FROM groups WHERE workspace_id=? AND handle=?',(ch['workspace_id'],n)).fetchone()
    if g:ids=[x[0] for x in c.execute('SELECT user_id FROM group_members WHERE group_id=? AND user_id IN (SELECT user_id FROM channel_members WHERE channel_id=?)',(g['id'],ch['id']))]
  for i in ids:
   if i!=author and i not in out:out.append(i)
 return out

async def read_get(r):
 u=await require_user(r)
 try: cid=int(r.match_info['id'])
 except: jerr(404,'not found')
 c=connect();ch=c.execute('SELECT * FROM channels WHERE id=?',(cid,)).fetchone()
 if not ch:c.close();jerr(404,'not found')
 access(c,cid,u['id'])
 row=c.execute('SELECT last_read_event_id FROM read_state WHERE user_id=? AND channel_id=?',(u['id'],cid)).fetchone()
 last=row[0] if row else 0
 unread=c.execute('SELECT count(*) FROM events WHERE channel_id=? AND event_id>?',(cid,last)).fetchone()[0]
 mention=0
 for mm in c.execute('SELECT author_id,mentions FROM messages WHERE channel_id=? AND deleted=0 AND author_id!=?',(cid,u['id'])):
  try:
   if u['id'] in json.loads(mm['mentions'] or '[]'): mention+=1
  except: pass
 c.close();return web.json_response({'read_state':{'channel_id':cid,'last_read_event_id':last,'unread_count':unread,'mention_count':mention}})
async def read_post(r):
 u=await require_user(r);cid=int(r.match_info['id']);c=connect();ch=c.execute('SELECT * FROM channels WHERE id=?',(cid,)).fetchone()
 if not ch:c.close();jerr(404,'not found')
 access(c,cid,u['id']);d=await read_json(r);n=d.get('last_read_event_id')
 if not isinstance(n,int):c.close();jerr(400,'invalid read state')
 old=c.execute('SELECT last_read_event_id FROM read_state WHERE user_id=? AND channel_id=?',(u['id'],cid)).fetchone()
 if not old or n>old[0]:c.execute('INSERT OR REPLACE INTO read_state VALUES(?,?,?)',(u['id'],cid,n))
 c.close();return await read_get(r)
async def get_user(r):
 u=await require_user(r)
 try: uid=int(r.match_info['id'])
 except: jerr(404,'not found')
 c=connect();x=c.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone();c.close()
 if not x:jerr(404,'not found')
 return web.json_response({'user':user_to_json(x)})
async def patch_profile(r):
 u=await require_user(r);d=await read_json(r)
 allowed=('display_name','timezone','avatar_url','status_text','status_emoji')
 vals={k:d[k] for k in allowed if k in d}
 from zoneinfo import ZoneInfo
 for k,v in vals.items():
  if not isinstance(v,str):jerr(400,'invalid profile')
  if k=='display_name' and not 1<=len(v)<=80:jerr(400,'invalid display_name')
  if k=='status_text' and len(v)>100:jerr(400,'invalid status_text')
  if k=='status_emoji' and len(v)>64:jerr(400,'invalid status_emoji')
  if k=='avatar_url' and len(v)>1024:jerr(400,'invalid avatar_url')
  if k=='timezone':
   try: ZoneInfo(v)
   except: jerr(400,'invalid timezone')
 c=connect()
 if vals:
  q=','.join(k+'=?' for k in vals);c.execute('UPDATE users SET '+q+' WHERE id=?',tuple(vals.values())+(u['id'],))
 x=c.execute('SELECT * FROM users WHERE id=?',(u['id'],)).fetchone();c.close();out=user_to_json(x)
 broadcast_global({'type':'user.updated','user':out})
 return web.json_response({'user':out})
async def health(r): return web.json_response({'status':'ok','node_id':NODE})
async def register(r):
 d=await read_json(r); u=d.get('username',''); p=d.get('password','')
 if not re.fullmatch(r'[A-Za-z0-9_]{1,32}',u) or len(p)<8:jerr(400,'invalid registration')
 c=connect()
 if c.execute('SELECT 1 FROM users WHERE username=?',(u,)).fetchone():c.close();jerr(409,'duplicate username')
 c.execute('INSERT INTO users(username,password,display_name,created_at) VALUES(?,?,?,?)',(u,p,d.get('display_name') or u,now_iso()))
 uid=c.execute('SELECT last_insert_rowid()').fetchone()[0]; t=secrets.token_urlsafe(24);c.execute('INSERT INTO tokens VALUES(?,?)',(t,uid));x=c.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone();c.close()
 return web.json_response({'user':user_to_json(x),'token':t},status=201)
async def login(r):
 d=await read_json(r);c=connect();x=c.execute('SELECT * FROM users WHERE username=? AND password=?',(d.get('username'),d.get('password'))).fetchone()
 if not x:c.close();jerr(401,'invalid credentials')
 t=secrets.token_urlsafe(24);c.execute('INSERT INTO tokens VALUES(?,?)',(t,x['id']));c.close();return web.json_response({'user':user_to_json(x),'token':t})
async def me(r): return web.json_response({'user':user_to_json(await require_user(r))})
async def workspaces(r):
 u=await require_user(r);c=connect(); rows=c.execute('SELECT w.* FROM workspaces w JOIN workspace_members m ON m.workspace_id=w.id WHERE m.user_id=?',(u['id'],)).fetchall();c.close()
 return web.json_response({'workspaces':[dict(x) for x in rows]})
async def create_ws(r):
 u=await require_user(r);d=await read_json(r); slug=d.get('slug','');name=d.get('name','')
 if not re.fullmatch(r'[a-z0-9-]{2,32}',slug) or not name:jerr(400,'invalid workspace')
 c=connect()
 if c.execute('SELECT 1 FROM workspaces WHERE slug=?',(slug,)).fetchone():c.close();jerr(409,'duplicate slug')
 t=now_iso();c.execute('INSERT INTO workspaces(slug,name,owner_id,created_at) VALUES(?,?,?,?)',(slug,name,u['id'],t));wid=c.execute('SELECT last_insert_rowid()').fetchone()[0];c.execute('INSERT INTO workspace_members VALUES(?,?,?)',(wid,u['id'],'owner'));c.execute('INSERT INTO channels(workspace_id,name,created_at) VALUES(?,?,?)',(wid,'general',t));cid=c.execute('SELECT last_insert_rowid()').fetchone()[0];c.execute('INSERT INTO channel_members VALUES(?,?)',(cid,u['id']));w=c.execute('SELECT * FROM workspaces WHERE id=?',(wid,)).fetchone();ch=c.execute('SELECT * FROM channels WHERE id=?',(cid,)).fetchone();c.close()
 return web.json_response({'workspace':dict(w),'general_channel':channel_json(ch)},status=201)
async def ws_detail(r):
 u=await require_user(r);c=connect();w=c.execute('SELECT * FROM workspaces WHERE slug=?',(r.match_info['slug'],)).fetchone()
 if not w:c.close();jerr(404,'not found')
 if not member(c,w['id'],u['id']):c.close();jerr(403,'forbidden')
 cs=c.execute('SELECT * FROM channels WHERE workspace_id=? AND is_dm=0 AND is_archived=0',(w['id'],)).fetchall();c.close()
 return web.json_response({'workspace':dict(w),'channels':[channel_json(x) for x in cs],'read_state':[]})
async def create_ch(r):
 u=await require_user(r);d=await read_json(r);c=connect();w=c.execute('SELECT * FROM workspaces WHERE slug=?',(r.match_info['slug'],)).fetchone()
 if not w:c.close();jerr(404,'not found')
 m=member(c,w['id'],u['id'])
 if not m:c.close();jerr(403,'forbidden')
 n=d.get('name','')
 if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*',n) or len(n)>32:c.close();jerr(400,'invalid channel')
 if c.execute('SELECT 1 FROM channels WHERE workspace_id=? AND name=?',(w['id'],n)).fetchone():c.close();jerr(409,'duplicate channel')
 if d.get('is_private') and m['role'] not in ('owner','admin'):c.close();jerr(403,'forbidden')
 t=now_iso();c.execute('INSERT INTO channels(workspace_id,name,is_private,topic,created_at) VALUES(?,?,?,?,?)',(w['id'],n,int(bool(d.get('is_private'))),d.get('topic',''),t));cid=c.execute('SELECT last_insert_rowid()').fetchone()[0];c.execute('INSERT INTO channel_members VALUES(?,?)',(cid,u['id']));x=c.execute('SELECT * FROM channels WHERE id=?',(cid,)).fetchone();c.close();emit_event(cid,'member.joined',{'user_id':u['id']})
 return web.json_response({'channel':channel_json(x)},status=201)
async def join(r):
 u=await require_user(r);c=connect();ch=c.execute('SELECT * FROM channels WHERE id=?',(r.match_info['id'],)).fetchone()
 if not ch:c.close();jerr(404,'not found')
 if ch['is_private']:c.close();jerr(403,'forbidden')
 if not member(c,ch['workspace_id'],u['id']):c.execute('INSERT INTO workspace_members VALUES(?,?,?)',(ch['workspace_id'],u['id'],'member'))
 c.execute('INSERT OR IGNORE INTO channel_members VALUES(?,?)',(ch['id'],u['id']));c.close();return web.json_response({'channel':channel_json(ch)})

async def archive_channel(r):
 u=await require_user(r)
 try: cid=int(r.match_info['id'])
 except: jerr(404,'not found')
 c=connect();ch=c.execute('SELECT * FROM channels WHERE id=?',(cid,)).fetchone()
 if not ch:c.close();jerr(404,'not found')
 w=c.execute('SELECT * FROM workspaces WHERE id=?',(ch['workspace_id'],)).fetchone()
 if w['owner_id']!=u['id']:c.close();jerr(403,'forbidden')
 c.execute('UPDATE channels SET is_archived=1 WHERE id=?',(cid,));ch=c.execute('SELECT * FROM channels WHERE id=?',(cid,)).fetchone();c.close()
 emit_event(cid,'channel.archived',{'channel':channel_json(ch)})
 return web.json_response({'channel':channel_json(ch)})
async def unarchive_channel(r):
 u=await require_user(r)
 try: cid=int(r.match_info['id'])
 except: jerr(404,'not found')
 c=connect();ch=c.execute('SELECT * FROM channels WHERE id=?',(cid,)).fetchone()
 if not ch:c.close();jerr(404,'not found')
 w=c.execute('SELECT * FROM workspaces WHERE id=?',(ch['workspace_id'],)).fetchone()
 if w['owner_id']!=u['id']:c.close();jerr(403,'forbidden')
 c.execute('UPDATE channels SET is_archived=0 WHERE id=?',(cid,));ch=c.execute('SELECT * FROM channels WHERE id=?',(cid,)).fetchone();c.close()
 emit_event(cid,'channel.unarchived',{'channel':channel_json(ch)})
 return web.json_response({'channel':channel_json(ch)})

async def edit_message(r):
 u=await require_user(r)
 try: mid=int(r.match_info['id'])
 except: jerr(404,'not found')
 c=connect();m=c.execute('SELECT * FROM messages WHERE id=?',(mid,)).fetchone()
 if not m:c.close();jerr(404,'not found')
 if m['author_id']!=u['id']:c.close();jerr(403,'forbidden')
 if m['deleted']:c.close();jerr(409,'message deleted')
 ch=c.execute('SELECT * FROM channels WHERE id=?',(m['channel_id'],)).fetchone()
 if ch['is_archived']:c.close();jerr(423,'archived')
 d=await read_json(r);body=d.get('body')
 if not isinstance(body,str) or not body.strip():c.close();jerr(400,'empty body')
 edited=now_iso();c.execute('UPDATE messages SET body=?,edited_at=? WHERE id=?',(body,edited,mid))
 m=c.execute('SELECT * FROM messages WHERE id=?',(mid,)).fetchone();out=msg_json(c,m);c.close()
 emit_event(ch['id'],'message.updated',{'message':out})
 return web.json_response({'message':out})
async def delete_message(r):
 u=await require_user(r)
 try: mid=int(r.match_info['id'])
 except: jerr(404,'not found')
 c=connect();m=c.execute('SELECT * FROM messages WHERE id=?',(mid,)).fetchone()
 if not m:c.close();jerr(404,'not found')
 ch=c.execute('SELECT * FROM channels WHERE id=?',(m['channel_id'],)).fetchone();w=c.execute('SELECT * FROM workspaces WHERE id=?',(ch['workspace_id'],)).fetchone()
 if m['author_id']!=u['id'] and w['owner_id']!=u['id']:c.close();jerr(403,'forbidden')
 if m['deleted']:c.close();return web.json_response({'deleted':True})
 if ch['is_archived']:c.close();jerr(423,'archived')
 c.execute('UPDATE messages SET deleted=1 WHERE id=?',(mid,));c.close()
 emit_event(ch['id'],'message.deleted',{'message_id':mid})
 return web.json_response({'deleted':True})
async def postmsg(r):
 u=await require_user(r);cid=int(r.match_info['id']);c=connect();ch=c.execute('SELECT * FROM channels WHERE id=?',(cid,)).fetchone()
 if not ch:c.close();jerr(404,'not found')
 d=await read_json(r);body=d.get('body','')
 if not isinstance(body,str) or not body.strip():c.close();jerr(400,'empty body')
 cmd=body
 if cmd.startswith('//'): body=cmd[1:]
 elif cmd.startswith('/'):
  parts=cmd.split(' ',1); name=parts[0]; arg=parts[1] if len(parts)>1 else ''
  w=c.execute('SELECT * FROM workspaces WHERE id=?',(ch['workspace_id'],)).fetchone()
  if name=='/me':
   if not arg.strip():c.close();jerr(400,'/me requires text')
  elif name=='/shrug': body=(arg.strip()+' ' if arg.strip() else '')+'¯\\_(ツ)_/¯'
  elif name=='/topic':
   if len(arg)>250:c.close();jerr(400,'topic too long')
   if not w or not member(c,w['id'],u['id']):c.close();jerr(403,'forbidden')
   c.execute('UPDATE channels SET topic=? WHERE id=?',(arg,cid));ch=c.execute('SELECT * FROM channels WHERE id=?',(cid,)).fetchone();c.close();emit_event(cid,'channel.updated',{'channel':channel_json(ch)});return web.json_response({'message':None,'channel':channel_json(ch)},status=201)
  elif name in ('/archive','/unarchive'):
   if not w or w['owner_id']!=u['id']:c.close();jerr(403,'forbidden')
   c.execute('UPDATE channels SET is_archived=? WHERE id=?',(1 if name=='/archive' else 0,cid));ch=c.execute('SELECT * FROM channels WHERE id=?',(cid,)).fetchone();c.close();emit_event(cid,'channel.archived' if name=='/archive' else 'channel.unarchived',{'channel':channel_json(ch)});return web.json_response({'message':None,'channel':channel_json(ch)},status=201)
  elif name=='/invite':
   if not c.execute('SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?',(cid,u['id'])).fetchone():c.close();jerr(403,'forbidden')
   if not arg.startswith('@') or not w or not member(c,w['id'],u['id']):c.close();jerr(400 if not arg else 403,'invalid invite')
   v=c.execute('SELECT * FROM users WHERE username=?',(arg[1:].strip(),)).fetchone()
   if not v:c.close();jerr(404,'user not found')
   if not member(c,w['id'],v['id']):c.close();jerr(400,'outside workspace')
   c.execute('INSERT OR IGNORE INTO channel_members VALUES(?,?)',(cid,v['id']));c.close();return web.json_response({'message':None,'invited_user':user_to_json(v)},status=201)
  else:c.close();jerr(400,'unknown command')
 ch=access(c,cid,u['id'],True)
 fids=d.get('file_ids',[])
 if not isinstance(fids,list) or any(not isinstance(z,int) for z in fids):c.close();jerr(400,'invalid file_ids')
 if fids:
  marks=','.join('?'*len(fids)); rows=c.execute(f'SELECT * FROM files WHERE id IN ({marks})',fids).fetchall()
  if len(rows)!=len(set(fids)) or any(x['uploader_id']!=u['id'] or x['message_id'] is not None for x in rows):c.close();jerr(400,'invalid files')
 mentions=resolve_mentions(c,body,ch,u['id']);t=now_iso();c.execute('INSERT INTO messages(channel_id,author_id,body,parent_id,created_at,mentions) VALUES(?,?,?,?,?,?)',(cid,u['id'],body,d.get('parent_id'),t,json.dumps(mentions)));mid=c.execute('SELECT last_insert_rowid()').fetchone()[0];x=c.execute('SELECT * FROM messages WHERE id=?',(mid,)).fetchone()
 if fids:c.executemany('UPDATE files SET message_id=? WHERE id=?',[(mid,z) for z in fids]);x=c.execute('SELECT * FROM messages WHERE id=?',(mid,)).fetchone()
 out=msg_json(c,x);c.close();emit_event(cid,'message.reply' if d.get('parent_id') else 'message.created',{'message':out})
 return web.json_response({'message':out},status=201)

async def replies(r):
 u=await require_user(r)
 try: mid=int(r.match_info['id'])
 except: jerr(404,'not found')
 c=connect();parent=c.execute('SELECT * FROM messages WHERE id=? AND deleted=0',(mid,)).fetchone()
 if not parent:c.close();jerr(404,'not found')
 access(c,parent['channel_id'],u['id']); n=parse_limit(r);q='SELECT * FROM messages WHERE parent_id=? AND deleted=0';args=[mid]
 if r.query.get('cursor'):q+=' AND id>?';args.append(decode_cursor(r.query['cursor']))
 q+=' ORDER BY id ASC LIMIT ?';args.append(n+1);xs=c.execute(q,args).fetchall();out=[msg_json(c,x) for x in xs[:n]];cur=encode_cursor(xs[n-1]['id']) if len(xs)>n else None;c.close()
 return web.json_response({'replies':out,'next_cursor':cur})
async def patch_channel(r):
 u=await require_user(r)
 try: cid=int(r.match_info['id'])
 except: jerr(404,'not found')
 c=connect();ch=c.execute('SELECT * FROM channels WHERE id=?',(cid,)).fetchone()
 if not ch:c.close();jerr(404,'not found')
 if not c.execute('SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?',(cid,u['id'])).fetchone():c.close();jerr(403,'forbidden')
 d=await read_json(r);topic=d.get('topic')
 if not isinstance(topic,str) or len(topic)>250:c.close();jerr(400,'invalid topic')
 c.execute('UPDATE channels SET topic=? WHERE id=?',(topic,cid));ch=c.execute('SELECT * FROM channels WHERE id=?',(cid,)).fetchone();c.close();emit_event(cid,'channel.updated',{'channel':channel_json(ch)})
 return web.json_response({'channel':channel_json(ch)})
async def messages(r):
 u=await require_user(r);c=connect();ch=access(c,int(r.match_info['id']),u['id']);n=parse_limit(r);q='SELECT * FROM messages WHERE channel_id=? AND deleted=0 AND parent_id IS NULL';args=[ch['id']]
 if r.query.get('cursor'):q+=' AND id<?';args.append(decode_cursor(r.query['cursor']))
 q+=' ORDER BY id DESC LIMIT ?';args.append(n+1);xs=c.execute(q,args).fetchall();out=[msg_json(c,x) for x in xs[:n]];cur=encode_cursor(xs[n-1]['id']) if len(xs)>n else None;c.close();return web.json_response({'messages':out,'next_cursor':cur})

def reaction_list(c,mid):
 out=[]
 for x in c.execute('SELECT emoji, user_id FROM reactions WHERE message_id=? ORDER BY rowid',(mid,)):
  z=next((a for a in out if a['emoji']==x['emoji']),None)
  if not z: z={'emoji':x['emoji'],'count':0,'user_ids':[]};out.append(z)
  z['count']+=1;z['user_ids'].append(x['user_id'])
 return out
async def react_add(r):
 u=await require_user(r)
 try: mid=int(r.match_info['id'])
 except: jerr(404,'not found')
 c=connect(); m=c.execute('SELECT * FROM messages WHERE id=? AND deleted=0',(mid,)).fetchone()
 if not m:c.close();jerr(404,'not found')
 access(c,m['channel_id'],u['id'],True); d=await read_json(r); e=d.get('emoji')
 if not isinstance(e,str) or not e or len(e)>64:c.close();jerr(400,'invalid emoji')
 old=c.execute('SELECT 1 FROM reactions WHERE message_id=? AND user_id=? AND emoji=?',(mid,u['id'],e)).fetchone()
 if not old:
  c.execute('INSERT INTO reactions(message_id,user_id,emoji,created_at) VALUES(?,?,?,?)',(mid,u['id'],e,now_iso()))
  rs=reaction_list(c,mid);c.close();emit_event(m['channel_id'],'reaction.added',{'message_id':mid,'emoji':e,'user_id':u['id'],'reactions':rs})
 else: rs=reaction_list(c,mid);c.close()
 return web.json_response({'reactions':rs})
async def react_del(r):
 u=await require_user(r)
 try: mid=int(r.match_info['id'])
 except: jerr(404,'not found')
 c=connect();m=c.execute('SELECT * FROM messages WHERE id=? AND deleted=0',(mid,)).fetchone()
 if not m:c.close();jerr(404,'not found')
 access(c,m['channel_id'],u['id'],True);e=r.match_info['emoji']
 old=c.execute('SELECT 1 FROM reactions WHERE message_id=? AND user_id=? AND emoji=?',(mid,u['id'],e)).fetchone()
 if old:
  c.execute('DELETE FROM reactions WHERE message_id=? AND user_id=? AND emoji=?',(mid,u['id'],e));rs=reaction_list(c,mid);c.close()
  emit_event(m['channel_id'],'reaction.removed',{'message_id':mid,'emoji':e,'user_id':u['id'],'reactions':rs})
 else: rs=reaction_list(c,mid);c.close()
 return web.json_response({'reactions':rs})
async def ws_handler(r):
 u=await require_user(r);w=web.WebSocketResponse();await w.prepare(r);key=uuid.uuid4().hex;clients[key]=(w,u['id'],set(),{});pc=connect();pc.execute('INSERT OR REPLACE INTO ws_presence(conn_id,node_id,user_id) VALUES(?,?,?)',(key,NODE,u['id']));pc.close()
 try:
  async for m in w:
   if m.type==WSMsgType.TEXT:
    d=json.loads(m.data);cid=int(d.get('channel_id',0));c=connect();ch=c.execute('SELECT * FROM channels WHERE id=?',(cid,)).fetchone()
    if d.get('type')=='subscribe':
     clients[key][2].add(cid);clients[key][3][cid]=ch['last_event_id'];await w.send_json({'type':'subscribed','channel_id':cid,'head_event_id':ch['last_event_id']})
    elif d.get('type')=='resume':
     for x in c.execute('SELECT payload FROM events WHERE channel_id=? AND event_id>? ORDER BY event_id',(cid,int(d.get('since_event_id',0)))):await w.send_str(x['payload'])
     await w.send_json({'type':'resumed','channel_id':cid,'head_event_id':ch['last_event_id']})
    c.close()
 finally:
  clients.pop(key,None);pc=connect();pc.execute('DELETE FROM ws_presence WHERE conn_id=?',(key,));pc.close()
 return w
async def pump(app):
 last=0
 c0=connect()
 row=c0.execute('SELECT COALESCE(MAX(seq),0) FROM events').fetchone(); last=row[0]
 brow=c0.execute('SELECT COALESCE(MAX(seq),0) FROM broadcasts').fetchone(); lastb=brow[0]
 c0.close()
 while True:
  c=connect()
  for x in c.execute('SELECT seq,payload,channel_id FROM events WHERE seq>? ORDER BY seq',(last,)):
   last=x['seq']
   for w,u,s,heads in list(clients.values()):
    if x['channel_id'] in s and x['channel_id'] in heads and json.loads(x['payload']).get('event_id',0)>heads[x['channel_id']]:
     try: await w.send_str(x['payload'])
     except: pass
  for x in c.execute('SELECT seq,payload FROM broadcasts WHERE seq>? ORDER BY seq',(lastb,)):
   lastb=x['seq']
   for w,u,s,heads in list(clients.values()):
    try: await w.send_str(x['payload'])
    except: pass
  c.close();await asyncio.sleep(.05)

async def startup(app): app['pump']=asyncio.create_task(pump(app))
async def cleanup(app): app['pump'].cancel()
app=web.Application(middlewares=[error_middleware],client_max_size=20*1024*1024);app.on_startup.append(startup);app.on_cleanup.append(cleanup)
app.router.add_get('/api/health',health);app.router.add_get('/api/users/{id}',get_user);app.router.add_get('/api/channels/{id}/read',read_get);app.router.add_post('/api/channels/{id}/read',read_post);app.router.add_get('/api/workspaces/{slug}/groups',groups_list);app.router.add_post('/api/workspaces/{slug}/groups',group_create);app.router.add_patch('/api/workspaces/{slug}/groups/{handle}',group_patch);app.router.add_delete('/api/workspaces/{slug}/groups/{handle}',group_delete);app.router.add_patch('/api/users/me',patch_profile);app.router.add_post('/api/files',upload_file);app.router.add_get('/api/files/{id}',get_file);app.router.add_get('/api/files/{id}/download',download_file);app.router.add_post('/api/dms',create_dm);app.router.add_post('/api/auth/register',register);app.router.add_post('/api/auth/login',login);app.router.add_get('/api/auth/me',me)
app.router.add_get('/api/workspaces',workspaces);app.router.add_post('/api/workspaces',create_ws);app.router.add_get('/api/workspaces/{slug}',ws_detail);app.router.add_post('/api/workspaces/{slug}/channels',create_ch)
app.router.add_post('/api/channels/{id}/join',join);app.router.add_post('/api/channels/{id}/archive',archive_channel);app.router.add_post('/api/channels/{id}/unarchive',unarchive_channel);app.router.add_post('/api/messages/{id}/reactions',react_add);app.router.add_delete('/api/messages/{id}/reactions/{emoji}',react_del);app.router.add_post('/api/channels/{id}/messages',postmsg);app.router.add_patch('/api/messages/{id}',edit_message);app.router.add_delete('/api/messages/{id}',delete_message);app.router.add_get('/api/channels/{id}/messages',messages);app.router.add_get('/api/messages/{id}/replies',replies);app.router.add_patch('/api/channels/{id}',patch_channel);app.router.add_get('/api/ws',ws_handler)
app.router.add_static('/static/','/app/static');app.router.add_get('/',lambda r:web.FileResponse('/app/static/index.html',headers={'Content-Type':'text/html; charset=utf-8'}) if __import__('os').path.exists('/app/static/index.html') else web.Response(text='Huddle',content_type='text/html'))
init_db();web.run_app(app,host='0.0.0.0',port=A.port)
