import argparse,os,json,re
from aiohttp import web
from db import connect,now_iso
from common import *
from routes_auth import setup as auth_setup

async def create_dm(r):
 u=require_user(r);d=await read_json(r)
 if 'user_id' not in d:
  raise HTTPError(400,'user_id required')
 try: other=int(d['user_id'])
 except: raise HTTPError(400,'invalid user_id')
 c=connect()
 if not c.execute('SELECT 1 FROM users WHERE id=?',(other,)).fetchone():
  c.close();raise HTTPError(404,'user not found')
 if other==u['id']:
  low=high=other
 else: low,high=sorted((u['id'],other))
 row=c.execute('SELECT channel_id FROM dm_pairs WHERE user_low=? AND user_high=?',(low,high)).fetchone()
 if row:
  cid=row[0];c.close();return web.json_response({'channel_id':cid})
 name=f'dm-{low}-{high}'
 c.execute('INSERT INTO channels(workspace_id,name,is_private,is_dm,topic,created_at) VALUES(NULL,?,1,1,"",?)',(name,now_iso()))
 cid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
 c.execute('INSERT INTO dm_pairs(user_low,user_high,channel_id) VALUES(?,?,?)',(low,high,cid))
 c.execute('INSERT INTO channel_members(channel_id,user_id) VALUES(?,?)',(cid,low))
 if high!=low:c.execute('INSERT INTO channel_members(channel_id,user_id) VALUES(?,?)',(cid,high))
 c.close();return web.json_response({'channel_id':cid})



def group_json(c,g):
 ids=[z[0] for z in c.execute('SELECT user_id FROM group_members WHERE group_id=? ORDER BY user_id',(g['id'],)).fetchall()]
 return {'id':g['id'],'handle':g['handle'],'name':g['name'],'member_user_ids':ids}
async def groups_list(r):
 u=require_user(r);c=connect();w=c.execute('SELECT * FROM workspaces WHERE slug=?',(r.match_info['slug'],)).fetchone()
 if not w: c.close();raise HTTPError(404,'not found')
 if not c.execute('SELECT 1 FROM memberships WHERE workspace_id=? AND user_id=?',(w['id'],u['id'])).fetchone():c.close();raise HTTPError(403,'forbidden')
 gs=c.execute('SELECT * FROM groups WHERE workspace_id=?',(w['id'],)).fetchall();out=[group_json(c,g) for g in gs];c.close();return web.json_response({'groups':out})
async def group_create(r):
 u=require_user(r);d=await read_json(r);c=connect();w=c.execute('SELECT * FROM workspaces WHERE slug=?',(r.match_info['slug'],)).fetchone()
 if not w:c.close();raise HTTPError(404,'not found')
 if not c.execute('SELECT 1 FROM memberships WHERE workspace_id=? AND user_id=?',(w['id'],u['id'])).fetchone():c.close();raise HTTPError(403,'forbidden')
 h=d.get('handle','');name=d.get('name','');ids=d.get('user_ids',[])
 if not isinstance(h,str) or not __import__('re').fullmatch(r'[a-z0-9][a-z0-9-]{0,30}[a-z0-9]',h) or h in ('here','channel') or not isinstance(name,str) or not name.strip() or not isinstance(ids,list):c.close();raise HTTPError(400,'invalid group')
 if c.execute('SELECT 1 FROM groups WHERE workspace_id=? AND handle=?',(w['id'],h)).fetchone():c.close();raise HTTPError(409,'duplicate')
 valid={z[0] for z in c.execute('SELECT user_id FROM memberships WHERE workspace_id=?',(w['id'],)).fetchall()}
 if any(not isinstance(x,int) or x not in valid for x in ids):c.close();raise HTTPError(400,'invalid members')
 c.execute('INSERT INTO groups(workspace_id,handle,name,created_by) VALUES(?,?,?,?)',(w['id'],h,name,u['id']));gid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
 for x in set(ids):c.execute('INSERT INTO group_members VALUES(?,?)',(gid,x))
 g=c.execute('SELECT * FROM groups WHERE id=?',(gid,)).fetchone();out=group_json(c,g);c.close();return web.json_response({'group':out},status=201)
async def group_patch(r):
 u=require_user(r);d=await read_json(r);c=connect();w=c.execute('SELECT * FROM workspaces WHERE slug=?',(r.match_info['slug'],)).fetchone();g=c.execute('SELECT * FROM groups WHERE workspace_id=? AND handle=?',(w['id'],r.match_info['handle'])).fetchone() if w else None
 if not w:c.close();raise HTTPError(404,'not found')
 if not g:c.close();raise HTTPError(404,'not found')
 role=c.execute('SELECT role FROM memberships WHERE workspace_id=? AND user_id=?',(w['id'],u['id'])).fetchone()
 if g['created_by']!=u['id'] and (not role or role[0]!='owner'):c.close();raise HTTPError(403,'forbidden')
 if 'name' in d:
  if not isinstance(d['name'],str) or not d['name'].strip():c.close();raise HTTPError(400,'name')
  c.execute('UPDATE groups SET name=? WHERE id=?',(d['name'],g['id']))
 if 'user_ids' in d:
  ids=d['user_ids'];valid={z[0] for z in c.execute('SELECT user_id FROM memberships WHERE workspace_id=?',(w['id'],)).fetchall()}
  if not isinstance(ids,list) or any(x not in valid for x in ids):c.close();raise HTTPError(400,'members')
  c.execute('DELETE FROM group_members WHERE group_id=?',(g['id'],))
  for x in set(ids):c.execute('INSERT INTO group_members VALUES(?,?)',(g['id'],x))
 g=c.execute('SELECT * FROM groups WHERE id=?',(g['id'],)).fetchone();out=group_json(c,g);c.close();return web.json_response({'group':out})
async def group_delete(r):
 u=require_user(r);c=connect();w=c.execute('SELECT * FROM workspaces WHERE slug=?',(r.match_info['slug'],)).fetchone()
 if not w:c.close();raise HTTPError(404,'not found')
 g=c.execute('SELECT * FROM groups WHERE workspace_id=? AND handle=?',(w['id'],r.match_info['handle'])).fetchone()
 if g:
  role=c.execute('SELECT role FROM memberships WHERE workspace_id=? AND user_id=?',(w['id'],u['id'])).fetchone()
  if g['created_by']!=u['id'] and (not role or role[0]!='owner'):c.close();raise HTTPError(403,'forbidden')
  c.execute('DELETE FROM group_members WHERE group_id=?',(g['id'],));c.execute('DELETE FROM groups WHERE id=?',(g['id'],))
 c.close();return web.json_response({'deleted':True})


def inv_json(x):
 return {k:x[k] for k in ('code','workspace_id','created_by','max_uses','uses','expires_at','invited_user_id','created_at')}
def inv_active(x):
 import time
 return not x['revoked'] and x['uses']<x['max_uses'] and (x['expires_at'] is None or float(x['expires_at'])>time.time())
async def ws_patch(r):
 u=require_user(r);d=await read_json(r);c=connect();w=c.execute('SELECT * FROM workspaces WHERE slug=?',(r.match_info['slug'],)).fetchone()
 if not w: c.close();raise HTTPError(404,'not found')
 role=c.execute('SELECT role FROM memberships WHERE workspace_id=? AND user_id=?',(w['id'],u['id'])).fetchone()
 if not role or role[0] not in ('owner','admin'): c.close();raise HTTPError(403,'forbidden')
 if 'join_mode' in d and d['join_mode'] not in ('open','invite_only'):c.close();raise HTTPError(400,'join_mode')
 if 'name' in d and (not isinstance(d['name'],str) or not d['name'].strip()):c.close();raise HTTPError(400,'name')
 sets=[];args=[]
 for k in ('name','join_mode'):
  if k in d:sets.append(k+'=?');args.append(d[k])
 if sets:args.append(w['id']);c.execute('UPDATE workspaces SET '+','.join(sets)+' WHERE id=?',args)
 w=c.execute('SELECT * FROM workspaces WHERE id=?',(w['id'],)).fetchone();c.close();return web.json_response({'workspace':dict(w)})
async def inv_create(r):
 u=require_user(r);d=await read_json(r);c=connect();w=c.execute('SELECT * FROM workspaces WHERE slug=?',(r.match_info['slug'],)).fetchone()
 if not w:c.close();raise HTTPError(404,'not found')
 role=c.execute('SELECT role FROM memberships WHERE workspace_id=? AND user_id=?',(w['id'],u['id'])).fetchone()
 if not role or role[0] not in ('owner','admin'):c.close();raise HTTPError(403,'forbidden')
 target=d.get('invited_user_id')
 if d.get('invited_username'):
  z=c.execute('SELECT id FROM users WHERE username=?',(d['invited_username'],)).fetchone()
  if not z:c.close();raise HTTPError(400,'unknown username')
  target=z[0]
 try: uses=int(d.get('max_uses',1))
 except: c.close();raise HTTPError(400,'max_uses')
 if uses<1:c.close();raise HTTPError(400,'max_uses')
 if target is not None:uses=1
 import secrets,time
 exp=None if d.get('expires_in_seconds') is None else time.time()+int(d['expires_in_seconds'])
 code=secrets.token_urlsafe(12);now=now_iso()
 c.execute('INSERT INTO invitations(code,workspace_id,created_by,max_uses,uses,expires_at,invited_user_id,revoked,created_at) VALUES(?,?,?,?,?,?,?,?,?)',(code,w['id'],u['id'],uses,0,exp,target,0,now))
 x=c.execute('SELECT * FROM invitations WHERE code=?',(code,)).fetchone();c.close();return web.json_response({'invitation':inv_json(x)},status=201)
async def inv_list(r):
 u=require_user(r);c=connect();w=c.execute('SELECT * FROM workspaces WHERE slug=?',(r.match_info['slug'],)).fetchone()
 if not w:c.close();raise HTTPError(404,'not found')
 role=c.execute('SELECT role FROM memberships WHERE workspace_id=? AND user_id=?',(w['id'],u['id'])).fetchone()
 if not role or role[0] not in ('owner','admin'):c.close();raise HTTPError(403,'forbidden')
 out=[inv_json(x) for x in c.execute('SELECT * FROM invitations WHERE workspace_id=?',(w['id'],)).fetchall() if inv_active(x)];c.close();return web.json_response({'invitations':out})
async def inv_delete(r):
 u=require_user(r);c=connect();w=c.execute('SELECT * FROM workspaces WHERE slug=?',(r.match_info['slug'],)).fetchone();x=c.execute('SELECT * FROM invitations WHERE code=?',(r.match_info['code'],)).fetchone()
 if not w:c.close();raise HTTPError(404,'not found')
 role=c.execute('SELECT role FROM memberships WHERE workspace_id=? AND user_id=?',(w['id'],u['id'])).fetchone()
 if not role or role[0] not in ('owner','admin'):c.close();raise HTTPError(403,'forbidden')
 if not x:c.close();raise HTTPError(404,'not found')
 c.execute('UPDATE invitations SET revoked=1 WHERE code=?',(x['code'],));c.close();return web.json_response({'deleted':True})
async def inv_accept(r):
 u=require_user(r);c=connect();x=c.execute('SELECT * FROM invitations WHERE code=?',(r.match_info['code'],)).fetchone()
 if not x or not inv_active(x):c.close();raise HTTPError(404,'not found')
 if x['invited_user_id'] is not None and x['invited_user_id']!=u['id']:c.close();raise HTTPError(403,'targeted invitation')
 c.execute('UPDATE invitations SET uses=uses+1 WHERE code=?',(x['code'],))
 if not c.execute('SELECT 1 FROM memberships WHERE workspace_id=? AND user_id=?',(x['workspace_id'],u['id'])).fetchone():c.execute('INSERT INTO memberships(workspace_id,user_id,role,joined_at) VALUES(?,?,?,?)',(x['workspace_id'],u['id'],'member',now_iso()))
 w=c.execute('SELECT * FROM workspaces WHERE id=?',(x['workspace_id'],)).fetchone();g=c.execute('SELECT * FROM channels WHERE workspace_id=? AND name="general"',(w['id'],)).fetchone();c.execute('INSERT OR IGNORE INTO channel_members(channel_id,user_id) VALUES(?,?)',(g['id'],u['id']));m=c.execute('SELECT role,joined_at FROM memberships WHERE workspace_id=? AND user_id=?',(w['id'],u['id'])).fetchone();c.close();return web.json_response({'workspace':dict(w),'member':{'user_id':u['id'],'role':m['role'],'joined_at':m['joined_at'],'user':user_to_json(u)}})

async def get_user(r):
 u=require_user(r)
 try: uid=int(r.match_info['id'])
 except: raise HTTPError(404,'not found')
 c=connect();x=c.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone();c.close()
 if not x: raise HTTPError(404,'not found')
 return web.json_response({'user':user_to_json(x)})
async def patch_profile(r):
 u=require_user(r);d=await read_json(r)
 allowed={'display_name':80,'timezone':64,'avatar_url':500,'status_text':100,'status_emoji':32}
 for k,v in d.items():
  if k not in allowed: continue
  if not isinstance(v,str) or len(v)>allowed[k] or (k=='display_name' and not v.strip()): raise HTTPError(400,'invalid profile')
 if 'timezone' in d:
  try:
   from zoneinfo import ZoneInfo
   ZoneInfo(d['timezone'])
  except: raise HTTPError(400,'invalid timezone')
 c=connect();sets=[];args=[]
 for k in allowed:
  if k in d: sets.append(k+'=?');args.append(d[k])
 if sets:
  args.append(u['id']);c.execute('UPDATE users SET '+','.join(sets)+' WHERE id=?',args)
 x=c.execute('SELECT * FROM users WHERE id=?',(u['id'],)).fetchone();c.close();out=user_to_json(x);broadcast_global({'type':'user.updated','user':out});return web.json_response({'user':out})


async def upload_file(r):
 u=require_user(r)
 if not r.content_type.startswith('multipart/'): raise HTTPError(400,'multipart required')
 try: reader=await r.multipart()
 except: raise HTTPError(400,'multipart required')
 part=None
 while True:
  x=await reader.next()
  if x is None: break
  if x.name=='file': part=x;break
  await x.release()
 if part is None: raise HTTPError(400,'file required')
 data=await part.read()
 if len(data)>10*1024*1024: raise HTTPError(413,'file too large')
 c=connect();ct=part.headers.get('Content-Type','application/octet-stream');fn=part.filename or 'file'
 c.execute('INSERT INTO files(uploader_id,filename,content_type,size,created_at) VALUES(?,?,?,?,?)',(u['id'],fn,ct,len(data),now_iso()))
 fid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
 with open('/app/data/files/'+str(fid),'wb') as f:f.write(data)
 z=c.execute('SELECT * FROM files WHERE id=?',(fid,)).fetchone();c.close()
 return web.json_response({'file':file_json(z)},status=201)
async def get_file(r):
 require_user(r);c=connect()
 try: fid=int(r.match_info['id'])
 except: c.close();raise HTTPError(404,'not found')
 z=c.execute('SELECT * FROM files WHERE id=?',(fid,)).fetchone();c.close()
 if not z: raise HTTPError(404,'not found')
 return web.json_response({'file':file_json(z)})
async def download_file(r):
 require_user(r);c=connect()
 try: fid=int(r.match_info['id'])
 except: c.close();raise HTTPError(404,'not found')
 z=c.execute('SELECT * FROM files WHERE id=?',(fid,)).fetchone();c.close()
 if not z: raise HTTPError(404,'not found')
 try: data=open('/app/data/files/'+str(fid),'rb').read()
 except: raise HTTPError(404,'not found')
 resp=web.Response(body=data,content_type=z['content_type']);resp.headers['Content-Disposition']='attachment; filename="'+z['filename']+'"';return resp

async def health(r): return web.json_response({'status':'ok','node_id':r.app['node_id']})
def chan(x):
 return {'id':x['id'],'workspace_id':x['workspace_id'],'name':x['name'],'is_private':bool(x['is_private']),'is_dm':bool(x['is_dm']),'topic':x['topic'] or '','is_archived':bool(x['is_archived']),'created_at':x['created_at']}
def file_json(x):
 return {'id':x['id'],'uploader_id':x['uploader_id'],'filename':x['filename'],'content_type':x['content_type'],'size':x['size'],'created_at':x['created_at']}
def attached_files(c,mid):
 try: rows=c.execute('SELECT * FROM files WHERE message_id=? ORDER BY id',(mid,)).fetchall()
 except: rows=[]
 return [file_json(x) for x in rows]
def msg(c,x):
 u=c.execute('SELECT * FROM users WHERE id=?',(x['author_id'],)).fetchone()
 return {'id':x['id'],'channel_id':x['channel_id'],'author_id':x['author_id'],'author':user_to_json(u),'body':x['body'],'parent_id':x['parent_id'],'reply_count':c.execute('SELECT count(*) FROM messages WHERE parent_id=? AND deleted=0',(x['id'],)).fetchone()[0],'created_at':x['created_at'],'edited_at':x['edited_at'],'files':attached_files(c,x['id']),'reactions':reaction_data(c,x['id']),'mentions':json.loads(x['mentions'] or '[]') if 'mentions' in x.keys() else []}
async def workspaces(r):
 u=require_user(r);c=connect(); rows=c.execute('SELECT w.* FROM workspaces w JOIN memberships m ON m.workspace_id=w.id WHERE m.user_id=?',(u['id'],)).fetchall();c.close()
 return web.json_response({'workspaces':[dict(x) for x in rows]})
async def create_ws(r):
 u=require_user(r);d=await read_json(r); slug=d.get('slug','')
 if not __import__('re').fullmatch(r'[a-z0-9-]{2,32}',slug):raise HTTPError(400,'invalid slug')
 c=connect()
 try:c.execute('INSERT INTO workspaces(slug,name,owner_id,created_at) VALUES(?,?,?,?)',(slug,d.get('name',''),u['id'],now_iso()))
 except:c.close();raise HTTPError(409,'duplicate workspace')
 wid=c.execute('SELECT last_insert_rowid()').fetchone()[0];c.execute('INSERT INTO memberships(workspace_id,user_id,role) VALUES(?,?,?)',(wid,u['id'],'owner'));c.execute('INSERT INTO channels(workspace_id,name,created_at) VALUES(?,?,?)',(wid,'general',now_iso()));cid=c.execute('SELECT last_insert_rowid()').fetchone()[0];c.execute('INSERT INTO channel_members VALUES(?,?)',(cid,u['id']));w=c.execute('SELECT * FROM workspaces WHERE id=?',(wid,)).fetchone();ch=c.execute('SELECT * FROM channels WHERE id=?',(cid,)).fetchone();c.close()
 return web.json_response({'workspace':dict(w),'general_channel':chan(ch)},status=201)
async def detail(r):
 u=require_user(r);c=connect();w=c.execute('SELECT * FROM workspaces WHERE slug=?',(r.match_info['slug'],)).fetchone()
 if not w:raise HTTPError(404,'not found')
 arch='1' if r.query.get('include_archived') in ('1','true') else '0'
 rows=c.execute('SELECT ch.* FROM channels ch WHERE ch.workspace_id=? AND ch.is_dm=0 AND (? OR ch.is_archived=0) AND (ch.is_private=0 OR EXISTS(SELECT 1 FROM channel_members cm WHERE cm.channel_id=ch.id AND cm.user_id=?))',(w['id'],arch,u['id'])).fetchall();states=[read_obj(c,x['id'],u['id']) for x in rows];c.close(); return web.json_response({'workspace':dict(w),'channels':[chan(x) for x in rows],'read_state':states})
async def create_channel(r):
 u=require_user(r);d=await read_json(r);c=connect();w=c.execute('SELECT * FROM workspaces WHERE slug=?',(r.match_info['slug'],)).fetchone()
 if not w:raise HTTPError(404,'not found')
 role=c.execute('SELECT role FROM memberships WHERE workspace_id=? AND user_id=?',(w['id'],u['id'])).fetchone()
 if not role or (role[0]=='guest') or (role[0]=='member' and d.get('is_private')): raise HTTPError(403,'forbidden')
 n=d.get('name','')
 if c.execute('SELECT 1 FROM channels WHERE workspace_id=? AND name=?',(w['id'],n)).fetchone(): c.close(); raise HTTPError(409,'duplicate channel')
 if not __import__('re').fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*',n) or len(n)>32 or len(d.get('topic',''))>250:raise HTTPError(400,'invalid name')
 try:c.execute('INSERT INTO channels(workspace_id,name,is_private,topic,created_at) VALUES(?,?,?,?,?)',(w['id'],n,int(bool(d.get('is_private'))),d.get('topic',''),now_iso()))
 except:c.close();raise HTTPError(409,'duplicate channel')
 cid=c.execute('SELECT last_insert_rowid()').fetchone()[0];c.execute('INSERT INTO channel_members VALUES(?,?)',(cid,u['id']));x=c.execute('SELECT * FROM channels WHERE id=?',(cid,)).fetchone();c.close();return web.json_response({'channel':chan(x)},status=201)
async def join(r):
 u=require_user(r);c=connect();x=c.execute('SELECT * FROM channels WHERE id=?',(r.match_info['id'],)).fetchone()
 if not x:raise HTTPError(404,'not found')
 if x['is_private']: raise HTTPError(403,'private channel')
 role=c.execute('SELECT role FROM memberships WHERE workspace_id=? AND user_id=?',(x['workspace_id'],u['id'])).fetchone()
 if not role and c.execute('SELECT join_mode FROM workspaces WHERE id=?',(x['workspace_id'],)).fetchone()[0]=='invite_only': raise HTTPError(403,'invite required')
 role=c.execute('SELECT role FROM memberships WHERE workspace_id=? AND user_id=?',(x['workspace_id'],u['id'])).fetchone()
 if role and role[0]=='guest': raise HTTPError(403,'guest cannot join')
 already=c.execute('SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?',(x['id'],u['id'])).fetchone();c.execute('INSERT OR IGNORE INTO channel_members VALUES(?,?)',(x['id'],u['id']));c.execute('INSERT OR IGNORE INTO memberships(workspace_id,user_id,role) VALUES(?,?,?)',(x['workspace_id'],u['id'],'member')); head=c.execute('SELECT last_event_id FROM channels WHERE id=?',(x['id'],)).fetchone()[0];
 if not already: emit_event(x['id'],'member.joined',{'user_id':u['id'],'user':user_to_json(u)})
 c.execute('INSERT OR IGNORE INTO read_state(user_id,channel_id,last_read_event_id) VALUES(?,?,?)',(u['id'],x['id'],head));c.close();return web.json_response({'channel':chan(x)})
async def post(r):
 u=require_user(r);d=await read_json(r);body=d.get('body','')
 if not body.strip():raise HTTPError(400,'empty body')
 c=connect();x=c.execute('SELECT * FROM channels WHERE id=?',(r.match_info['id'],)).fetchone()
 if not x:raise HTTPError(404,'not found')
 if x['is_private'] and not c.execute('SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?',(x['id'],u['id'])).fetchone(): c.close();raise HTTPError(403,'forbidden')
 if body.startswith('//'):
  body=body[1:]
 elif body.startswith('/'):
  cmd,_,text=body[1:].partition(' ');text=text.strip()
  if cmd=='me':
   if not text:c.close();raise HTTPError(400,'/me needs text')
   body='/me '+text
  elif cmd=='shrug':
   body=(text+' ' if text else '')+'¯\\_(ツ)_/¯'
  elif cmd=='topic':
   if len(text)>250:c.close();raise HTTPError(400,'topic')
   c.execute('UPDATE channels SET topic=? WHERE id=?',(text,x['id']));x=c.execute('SELECT * FROM channels WHERE id=?',(x['id'],)).fetchone();c.close();emit_event(x['id'],'channel.updated',{'channel':chan(x)});return web.json_response({'message':None,'channel':chan(x)},status=201)
  elif cmd=='invite':
   if not c.execute('SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?',(x['id'],u['id'])).fetchone():c.close();raise HTTPError(403,'forbidden')
   if not text.startswith('@') or len(text)<2:c.close();raise HTTPError(400,'username required')
   target=c.execute('SELECT * FROM users WHERE username=?',(text[1:],)).fetchone()
   if not target:c.close();raise HTTPError(404,'user not found')
   if not c.execute('SELECT 1 FROM memberships WHERE workspace_id=? AND user_id=?',(x['workspace_id'],target['id'])).fetchone():c.close();raise HTTPError(400,'not workspace member')
   c.execute('INSERT OR IGNORE INTO channel_members(channel_id,user_id) VALUES(?,?)',(x['id'],target['id']));c.close();emit_event(x['id'],'member.joined',{'user_id':target['id'],'user':user_to_json(target)});return web.json_response({'message':None,'invited_user':user_to_json(target)},status=201)
  elif cmd in ('archive','unarchive'):
   w=c.execute('SELECT owner_id FROM workspaces WHERE id=?',(x['workspace_id'],)).fetchone()
   if not w or w['owner_id']!=u['id']:c.close();raise HTTPError(403,'owner')
   val=1 if cmd=='archive' else 0;c.execute('UPDATE channels SET is_archived=? WHERE id=?',(val,x['id']));x=c.execute('SELECT * FROM channels WHERE id=?',(x['id'],)).fetchone();c.close();emit_event(x['id'],'channel.archived' if val else 'channel.unarchived',{'channel':chan(x)});return web.json_response({'message':None,'channel':chan(x)},status=201)
  else:
   c.close();raise HTTPError(400,'unknown command')
 access(c,x,u['id'],True)
 fids=d.get('file_ids',[])
 if not isinstance(fids,list) or any(not isinstance(z,int) for z in fids): c.close();raise HTTPError(400,'invalid file_ids')
 if len(set(fids))!=len(fids): c.close();raise HTTPError(400,'invalid file_ids')
 for fid in fids:
  f=c.execute('SELECT * FROM files WHERE id=?',(fid,)).fetchone()
  if not f or f['uploader_id']!=u['id'] or f['message_id'] is not None: c.close();raise HTTPError(400,'invalid file')
 if d.get('parent_id') is not None and not c.execute('SELECT 1 FROM messages WHERE id=? AND channel_id=? AND deleted=0',(d.get('parent_id'),x['id'])).fetchone(): c.close(); raise HTTPError(404,'parent not found')
 names=re.findall(r'(?<![A-Za-z0-9_])@([A-Za-z0-9_]+)',body)
 ids=[]
 for nm in names:
  if nm=='channel':
   ids += [z[0] for z in c.execute('SELECT user_id FROM channel_members WHERE channel_id=? AND user_id!=?',(x['id'],u['id'])).fetchall()]
  elif nm=='here':
   ids += [z[0] for z in c.execute('SELECT DISTINCT cm.user_id FROM channel_members cm JOIN ws_presence wp ON wp.user_id=cm.user_id WHERE cm.channel_id=? AND cm.user_id!=? AND (wp.channel_id=? OR wp.channel_id=0)',(x['id'],u['id'],x['id'])).fetchall()]
  else:
   z=c.execute('SELECT id FROM users WHERE username=?',(nm,)).fetchone()
   if z and z[0]!=u['id'] and c.execute('SELECT 1 FROM memberships WHERE workspace_id=? AND user_id=?',(x['workspace_id'],z[0])).fetchone(): ids.append(z[0])
   else:
    g=c.execute('SELECT id FROM groups WHERE workspace_id=? AND handle=?',(x['workspace_id'],nm)).fetchone()
    if g: ids += [z[0] for z in c.execute('SELECT user_id FROM group_members WHERE group_id=? AND user_id IN (SELECT user_id FROM channel_members WHERE channel_id=?)',(g['id'],x['id'])).fetchall()]
 ids=list(dict.fromkeys(ids))
 c.execute('INSERT INTO messages(channel_id,author_id,body,parent_id,created_at,mentions) VALUES(?,?,?,?,?,?)',(x['id'],u['id'],body,d.get('parent_id'),now_iso(),json.dumps(ids)));mid=c.execute('SELECT last_insert_rowid()').fetchone()[0];
 for fid in fids: c.execute('UPDATE files SET message_id=? WHERE id=?',(mid,fid))
 m=c.execute('SELECT * FROM messages WHERE id=?',(mid,)).fetchone();c.close();data={'message':msg(connect(),m)};emit_event(x['id'],'message.reply' if d.get('parent_id') else 'message.created',data);return web.json_response(data,status=201)
async def messages(r):
 u=require_user(r);c=connect();x=get_channel(c,r.match_info['id']);access(c,x,u['id'])
 n=parse_limit(r);cur=decode_cursor(r.query.get('cursor'))
 if cur is None: rows=c.execute('SELECT * FROM messages WHERE channel_id=? AND parent_id IS NULL AND deleted=0 ORDER BY id DESC LIMIT ?',(x['id'],n+1)).fetchall()
 else: rows=c.execute('SELECT * FROM messages WHERE channel_id=? AND parent_id IS NULL AND deleted=0 AND id<? ORDER BY id DESC LIMIT ?',(x['id'],cur,n+1)).fetchall()
 more=len(rows)>n; rows=rows[:n];out=[msg(c,z) for z in rows];nextc=encode_cursor(rows[-1]['id']) if more and rows else None;c.close()
 return web.json_response({'messages':out,'next_cursor':nextc})
async def replies(r):
 u=require_user(r);c=connect()
 try: mid=int(r.match_info['id'])
 except: c.close();raise HTTPError(404,'not found')
 parent=c.execute('SELECT * FROM messages WHERE id=? AND deleted=0',(mid,)).fetchone()
 if not parent:c.close();raise HTTPError(404,'not found')
 x=get_channel(c,parent['channel_id']);access(c,x,u['id']);n=parse_limit(r);cur=decode_cursor(r.query.get('cursor'))
 if cur is None: rows=c.execute('SELECT * FROM messages WHERE channel_id=? AND parent_id=? AND deleted=0 ORDER BY id ASC LIMIT ?',(x['id'],mid,n+1)).fetchall()
 else: rows=c.execute('SELECT * FROM messages WHERE channel_id=? AND parent_id=? AND deleted=0 AND id>? ORDER BY id ASC LIMIT ?',(x['id'],mid,cur,n+1)).fetchall()
 more=len(rows)>n;rows=rows[:n];out=[msg(c,z) for z in rows];nextc=encode_cursor(rows[-1]['id']) if more and rows else None;c.close()
 return web.json_response({'replies':out,'next_cursor':nextc})

async def pin_message(r):
 u=require_user(r);c=connect()
 try: mid=int(r.match_info['id'])
 except: c.close();raise HTTPError(404,'not found')
 m=c.execute('SELECT * FROM messages WHERE id=? AND deleted=0',(mid,)).fetchone()
 if not m:c.close();raise HTTPError(404,'not found')
 x=get_channel(c,m['channel_id']);access(c,x,u['id'],True)
 old=c.execute('SELECT * FROM pins WHERE message_id=?',(mid,)).fetchone()
 if not old:
  t=now_iso();c.execute('INSERT INTO pins(message_id,pinned_by,pinned_at) VALUES(?,?,?)',(mid,u['id'],t));old=c.execute('SELECT * FROM pins WHERE message_id=?',(mid,)).fetchone()
 c.close();return web.json_response({'pin':{'message_id':old['message_id'],'pinned_by':old['pinned_by'],'pinned_at':old['pinned_at']}})
async def unpin_message(r):
 u=require_user(r);c=connect()
 try:mid=int(r.match_info['id'])
 except:c.close();raise HTTPError(404,'not found')
 m=c.execute('SELECT * FROM messages WHERE id=?',(mid,)).fetchone()
 if not m:c.close();raise HTTPError(404,'not found')
 x=get_channel(c,m['channel_id']);access(c,x,u['id'],True);c.execute('DELETE FROM pins WHERE message_id=?',(mid,));c.close();return web.json_response({'unpinned':True})
async def pins_list(r):
 u=require_user(r);c=connect();x=get_channel(c,r.match_info['id']);access(c,x,u['id']);n=parse_limit(r);cur=decode_cursor(r.query.get('cursor'))
 q='SELECT p.*,m.* FROM pins p JOIN messages m ON m.id=p.message_id WHERE m.channel_id=? AND m.deleted=0';args=[x['id']]
 if cur is not None:q+=' AND p.message_id<?';args.append(cur)
 q+=' ORDER BY p.message_id DESC LIMIT ?';args.append(n+1);rows=c.execute(q,args).fetchall();more=len(rows)>n;rows=rows[:n];out=[]
 for z in rows:
  mm=c.execute('SELECT * FROM messages WHERE id=?',(z['message_id'],)).fetchone()
  out.append({'message':msg(c,mm),'pinned_by':z['pinned_by'],'pinned_at':z['pinned_at']})
 nxt=encode_cursor(rows[-1]['message_id']) if more and rows else None;c.close();return web.json_response({'pins':out,'next_cursor':nxt})
async def search(r):
 u=require_user(r);q=r.query.get('q','')
 if not q:raise HTTPError(400,'query required')
 c=connect();n=parse_limit(r);cur=decode_cursor(r.query.get('cursor'));wsid=r.query.get('workspace_id')
 sql="""SELECT m.* FROM messages m JOIN channels ch ON ch.id=m.channel_id
 WHERE m.deleted=0 AND lower(m.body) LIKE lower(?) AND
 ((ch.is_private=0 AND EXISTS(SELECT 1 FROM memberships wm WHERE wm.workspace_id=ch.workspace_id AND wm.user_id=?))
  OR EXISTS(SELECT 1 FROM channel_members cm WHERE cm.channel_id=ch.id AND cm.user_id=?))"""
 args=['%'+q+'%',u['id'],u['id']]
 if wsid:
  try:int(wsid)
  except:c.close();raise HTTPError(400,'workspace_id')
  sql+=' AND ch.workspace_id=?';args.append(int(wsid))
 if cur is not None:sql+=' AND m.id<?';args.append(cur)
 sql+=' ORDER BY m.id DESC LIMIT ?';args.append(n+1);rows=c.execute(sql,args).fetchall();more=len(rows)>n;rows=rows[:n];out=[msg(c,z) for z in rows];nxt=encode_cursor(rows[-1]['id']) if more and rows else None;c.close();return web.json_response({'results':out,'next_cursor':nxt})


def read_obj(c,cid,uid):
 row=c.execute('SELECT last_read_event_id FROM read_state WHERE user_id=? AND channel_id=?',(uid,cid)).fetchone()
 last=row[0] if row else 0
 unread=mention=0
 for z in c.execute('SELECT event_id,payload FROM events WHERE channel_id=? AND event_id>? ORDER BY event_id',(cid,last)).fetchall():
  try: p=json.loads(z['payload'])
  except: continue
  if p.get('type') not in ('message.created','message.reply'): continue
  m=p.get('message') or {}
  if m.get('author_id')==uid: continue
  unread+=1
  if uid in (m.get('mentions') or []): mention+=1
 return {'channel_id':cid,'last_read_event_id':last,'unread_count':unread,'mention_count':mention}

async def get_read(r):
 u=require_user(r);c=connect();x=get_channel(c,r.match_info['id']);access(c,x,u['id']);o=read_obj(c,x['id'],u['id']);c.close();return web.json_response({'read_state':o})
async def set_read(r):
 u=require_user(r);d=await read_json(r);c=connect();x=get_channel(c,r.match_info['id']);access(c,x,u['id']);old=read_obj(c,x['id'],u['id'])['last_read_event_id'];n=max(old,int(d.get('last_read_event_id',0)));c.execute('INSERT OR REPLACE INTO read_state(user_id,channel_id,last_read_event_id) VALUES(?,?,?)',(u['id'],x['id'],n));o=read_obj(c,x['id'],u['id']);c.close();return web.json_response({'read_state':o})


async def edit_message(r):
 u=require_user(r);d=await read_json(r);c=connect();m=c.execute('SELECT * FROM messages WHERE id=?',(r.match_info['id'],)).fetchone()
 if not m: raise HTTPError(404,'not found')
 x=get_channel(c,m['channel_id']);access(c,x,u['id'],True)
 if m['author_id']!=u['id']: raise HTTPError(403,'forbidden')
 if m['deleted']: raise HTTPError(409,'deleted')
 if not isinstance(d.get('body'),str) or not d.get('body','').strip(): raise HTTPError(400,'empty body')
 c.execute('UPDATE messages SET body=?,edited_at=? WHERE id=?',(d.get('body',''),now_iso(),m['id']));m=c.execute('SELECT * FROM messages WHERE id=?',(m['id'],)).fetchone();c.close();emit_event(x['id'],'message.updated',{'message':msg(connect(),m)});return web.json_response({'message':msg(connect(),m)})
async def delete_message(r):
 u=require_user(r);c=connect();m=c.execute('SELECT * FROM messages WHERE id=?',(r.match_info['id'],)).fetchone()
 if not m:c.close();raise HTTPError(404,'not found')
 if m['deleted']: c.close(); return web.json_response({'deleted':True})
 x=get_channel(c,m['channel_id']);access(c,x,u['id'],True);w=c.execute('SELECT owner_id FROM workspaces WHERE id=?',(x['workspace_id'],)).fetchone()
 if m['author_id']!=u['id'] and w['owner_id']!=u['id']:raise HTTPError(403,'forbidden')
 c.execute('UPDATE messages SET deleted=1 WHERE id=?',(m['id'],));c.close();emit_event(x['id'],'message.deleted',{'message_id':m['id']});return web.json_response({'deleted':True})
def reaction_data(c,mid):
 return [{'emoji':z['emoji'],'count':z['n'],'user_ids':[q[0] for q in c.execute('SELECT user_id FROM reactions WHERE message_id=? AND emoji=?',(mid,z['emoji'])).fetchall()]} for z in c.execute('SELECT emoji,count(*) n FROM reactions WHERE message_id=? GROUP BY emoji',(mid,)).fetchall()]
async def add_reaction(r):
 u=require_user(r);d=await read_json(r);e=d.get('emoji','')
 if not isinstance(e,str) or not e or len(e)>32 or any(ch.isspace() for ch in e): raise HTTPError(400,'invalid emoji')
 c=connect();m=c.execute('SELECT * FROM messages WHERE id=? AND deleted=0',(r.match_info['id'],)).fetchone()
 if not m:c.close();raise HTTPError(404,'not found')
 x=get_channel(c,m['channel_id']);access(c,x,u['id'],True)
 before=c.execute('SELECT 1 FROM reactions WHERE message_id=? AND user_id=? AND emoji=?',(m['id'],u['id'],e)).fetchone()
 c.execute('INSERT OR IGNORE INTO reactions(message_id,user_id,emoji) VALUES(?,?,?)',(m['id'],u['id'],e));rs=reaction_data(c,m['id']);c.close()
 if before: return web.json_response({'reactions':rs})
 emit_event(x['id'],'reaction.added',{'message_id':m['id'],'emoji':e,'user_id':u['id'],'reactions':rs});return web.json_response({'reactions':rs})
async def remove_reaction(r):
 u=require_user(r);c=connect();m=c.execute('SELECT * FROM messages WHERE id=? AND deleted=0',(r.match_info['id'],)).fetchone()
 if not m:c.close();raise HTTPError(404,'not found')
 x=get_channel(c,m['channel_id']);access(c,x,u['id'],True);before=c.execute('SELECT 1 FROM reactions WHERE message_id=? AND user_id=? AND emoji=?',(m['id'],u['id'],r.match_info['emoji'])).fetchone();c.execute('DELETE FROM reactions WHERE message_id=? AND user_id=? AND emoji=?',(m['id'],u['id'],r.match_info['emoji']));rs=reaction_data(c,m['id']);c.close()
 if not before:return web.json_response({'reactions':rs})
 emit_event(x['id'],'reaction.removed',{'message_id':m['id'],'emoji':r.match_info['emoji'],'user_id':u['id'],'reactions':rs});return web.json_response({'reactions':rs})

async def ws_handler(r):
 from aiohttp import web_ws
 u=require_user(r); w=web.WebSocketResponse();await w.prepare(r); seen=0; subscribed=set(); presence={0}; node_id=r.app['node_id']; pc=connect(); pc.execute('INSERT OR IGNORE INTO ws_presence(user_id,channel_id,node_id) VALUES(?,?,?)',(u['id'],0,node_id)); pc.close()
 async def pump():
  nonlocal seen
  broad=0
  while not w.closed:
   c=connect()
   for pcid in presence: c.execute('INSERT OR IGNORE INTO ws_presence(user_id,channel_id,node_id) VALUES(?,?,?)',(u['id'],pcid,node_id))
   rows=c.execute('SELECT seq,payload FROM events WHERE seq>? ORDER BY seq',(seen,)).fetchall();bs=c.execute('SELECT seq,payload FROM broadcasts WHERE seq>? ORDER BY seq',(broad,)).fetchall();c.close()
   for x in rows:
    seen=x['seq'];p=json.loads(x['payload'])
    if p.get('channel_id') in subscribed: await w.send_json(p)
   for x in bs:
    broad=x['seq'];await w.send_json(json.loads(x['payload']))
   await __import__('asyncio').sleep(.12)
 import asyncio
 task=asyncio.create_task(pump())
 try:
  async for m in w:
   if m.type==web.WSMsgType.TEXT:
    d=json.loads(m.data);typ=d.get('type');cid=int(d.get('channel_id',0))
    c=connect();head=c.execute('SELECT last_event_id FROM channels WHERE id=?',(cid,)).fetchone();head=head[0] if head else 0
    if typ=='subscribe':
     xx=c.execute('SELECT * FROM channels WHERE id=?',(cid,)).fetchone()
     if xx and xx['is_private'] and not c.execute('SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?',(cid,u['id'])).fetchone(): await w.send_json({'type':'error','error':'forbidden'}); c.close(); continue
     subscribed.add(cid); c.execute('INSERT OR IGNORE INTO ws_presence(user_id,channel_id,node_id) VALUES(?,?,?)',(u['id'],cid,node_id)); presence.add(cid); await w.send_json({'type':'subscribed','channel_id':cid,'head_event_id':head})
    elif typ=='resume':
     xx=c.execute('SELECT * FROM channels WHERE id=?',(cid,)).fetchone()
     if xx and xx['is_private'] and not c.execute('SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?',(cid,u['id'])).fetchone(): await w.send_json({'type':'error','error':'forbidden'}); c.close(); continue
     subscribed.add(cid); c.execute('INSERT OR IGNORE INTO ws_presence(user_id,channel_id,node_id) VALUES(?,?,?)',(u['id'],cid,node_id)); presence.add(cid); since=int(d.get('since_event_id',0)); ev=c.execute('SELECT payload FROM events WHERE channel_id=? AND event_id>? ORDER BY event_id',(cid,since)).fetchall()
     for e in ev: await w.send_json(json.loads(e[0]))
     await w.send_json({'type':'resumed','channel_id':cid,'head_event_id':head})
    c.close()
 finally:
  task.cancel()
  c2=connect()
  for pcid in presence: c2.execute('DELETE FROM ws_presence WHERE user_id=? AND channel_id=? AND node_id=?',(u['id'],pcid,node_id))
  c2.close()
 return w

async def members(r):
 u=require_user(r);c=connect();w=c.execute('SELECT * FROM workspaces WHERE slug=?',(r.match_info['slug'],)).fetchone()
 if not w: raise HTTPError(404,'not found')
 if not c.execute('SELECT 1 FROM memberships WHERE workspace_id=? AND user_id=?',(w['id'],u['id'])).fetchone(): raise HTTPError(403,'forbidden')
 rows=c.execute('SELECT m.*,u.* FROM memberships m JOIN users u ON u.id=m.user_id WHERE m.workspace_id=?',(w['id'],)).fetchall()
 out=[{'user_id':x['user_id'],'role':x['role'],'joined_at':x['joined_at'] if 'joined_at' in x.keys() else None,'user':user_to_json(x)} for x in rows];c.close();return web.json_response({'members':out})
async def role_patch(r):
 u=require_user(r);d=await read_json(r);c=connect();w=c.execute('SELECT * FROM workspaces WHERE slug=?',(r.match_info['slug'],)).fetchone()
 if not w: raise HTTPError(404,'not found')
 cr=c.execute('SELECT role FROM memberships WHERE workspace_id=? AND user_id=?',(w['id'],u['id'])).fetchone()
 if not cr or cr[0] not in ('owner','admin'): raise HTTPError(403,'forbidden')
 role=d.get('role'); target=int(r.match_info['user_id']); tr=c.execute('SELECT role FROM memberships WHERE workspace_id=? AND user_id=?',(w['id'],target)).fetchone()
 if role=='owner' or role not in ('admin','member','guest'): raise HTTPError(400,'invalid role')
 if not tr: raise HTTPError(404,'not found')
 if tr[0]=='owner' or (cr[0]=='admin' and tr[0]=='admin'): raise HTTPError(403,'forbidden')
 c.execute('UPDATE memberships SET role=? WHERE workspace_id=? AND user_id=?',(role,w['id'],target));x=c.execute('SELECT u.* FROM users u WHERE u.id=?',(target,)).fetchone();c.close()
 return web.json_response({'member':{'user_id':target,'role':role,'joined_at':None,'user':user_to_json(x)}})
async def transfer(r):
 u=require_user(r);d=await read_json(r);c=connect();w=c.execute('SELECT * FROM workspaces WHERE slug=?',(r.match_info['slug'],)).fetchone()
 if not w: raise HTTPError(404,'not found')
 if w['owner_id']!=u['id']: raise HTTPError(403,'forbidden')
 tid=d.get('new_owner_id');tr=c.execute('SELECT role FROM memberships WHERE workspace_id=? AND user_id=?',(w['id'],tid)).fetchone()
 if not tr or tr[0]!='admin': raise HTTPError(400,'target must be admin')
 c.execute('UPDATE memberships SET role="admin" WHERE workspace_id=? AND user_id=?',(w['id'],u['id']));c.execute('UPDATE memberships SET role="owner" WHERE workspace_id=? AND user_id=?',(w['id'],tid));c.execute('UPDATE workspaces SET owner_id=? WHERE id=?',(tid,w['id']));x=c.execute('SELECT * FROM workspaces WHERE id=?',(w['id'],)).fetchone();c.close();return web.json_response({'workspace':dict(x)})


def get_channel(c,i):
 try:x=c.execute('SELECT * FROM channels WHERE id=?',(int(i),)).fetchone()
 except: x=None
 if not x: raise HTTPError(404,'not found')
 return x
def access(c,x,uid,write=False):
 if x['is_private'] and not c.execute('SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?',(x['id'],uid)).fetchone():
  raise HTTPError(403,'forbidden')
 if not x['is_private'] and not c.execute('SELECT 1 FROM memberships WHERE workspace_id=? AND user_id=?',(x['workspace_id'],uid)).fetchone():
  raise HTTPError(403,'forbidden')
 if write and x['is_archived']: raise HTTPError(423,'archived')
async def patch_channel(r):
 u=require_user(r);d=await read_json(r);c=connect();x=get_channel(c,r.match_info['id']);
 if x['is_archived']: raise HTTPError(423,'archived')
 role=c.execute('SELECT role FROM memberships WHERE workspace_id=? AND user_id=?',(x['workspace_id'],u['id'])).fetchone()
 if not (c.execute('SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?',(x['id'],u['id'])).fetchone() or (role and role[0]=='owner')): raise HTTPError(403,'forbidden')
 if len(d.get('topic',''))>250: raise HTTPError(400,'topic')
 c.execute('UPDATE channels SET topic=? WHERE id=?',(d.get('topic',''),x['id']));x=c.execute('SELECT * FROM channels WHERE id=?',(x['id'],)).fetchone();c.close();emit_event(x['id'],'channel.updated',{'channel':chan(x)});return web.json_response({'channel':chan(x)})
async def leave_channel(r):
 u=require_user(r);c=connect();x=get_channel(c,r.match_info['id']);was=c.execute('SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?',(x['id'],u['id'])).fetchone();c.execute('DELETE FROM channel_members WHERE channel_id=? AND user_id=?',(x['id'],u['id']));c.close();
 if was: emit_event(x['id'],'member.left',{'user_id':u['id']})
 return web.json_response({'channel':chan(x)})
async def channel_members(r):
 u=require_user(r);c=connect();x=get_channel(c,r.match_info['id']);access(c,x,u['id']);rows=c.execute('SELECT u.* FROM users u JOIN channel_members m ON m.user_id=u.id WHERE m.channel_id=?',(x['id'],)).fetchall();c.close();return web.json_response({'members':[user_to_json(a) for a in rows]})
async def archive(r):
 u=require_user(r);c=connect();x=get_channel(c,r.match_info['id']);w=c.execute('SELECT owner_id FROM workspaces WHERE id=?',(x['workspace_id'],)).fetchone()
 if w['owner_id']!=u['id']:raise HTTPError(403,'owner')
 c.execute('UPDATE channels SET is_archived=? WHERE id=?',(1 if r.match_info['action']=='archive' else 0,x['id']));x=c.execute('SELECT * FROM channels WHERE id=?',(x['id'],)).fetchone();c.close();emit_event(x['id'],'channel.archived' if x['is_archived'] else 'channel.unarchived',{'channel':chan(x)});return web.json_response({'channel':chan(x)})

def invite_init():
 c=connect()
 for col,typ in [('created_by','INTEGER'),('revoked','INTEGER DEFAULT 0'),('created_at','TEXT')]:
  try: c.execute('ALTER TABLE invitations ADD COLUMN '+col+' '+typ)
  except: pass
 c.close()

def group_init():
 c=connect()
 c.execute('CREATE TABLE IF NOT EXISTS groups(id INTEGER PRIMARY KEY,workspace_id INTEGER,handle TEXT,name TEXT,created_by INTEGER,UNIQUE(workspace_id,handle))')
 c.execute('CREATE TABLE IF NOT EXISTS group_members(group_id INTEGER,user_id INTEGER,PRIMARY KEY(group_id,user_id))')
 c.execute('CREATE TABLE IF NOT EXISTS ws_presence(user_id INTEGER,channel_id INTEGER,node_id INTEGER,PRIMARY KEY(user_id,channel_id,node_id))')
 c.close()

def file_init():
 c=connect()
 try: c.execute('ALTER TABLE files ADD COLUMN message_id INTEGER')
 except: pass
 c.close()

def dm_init():
 c=connect()
 c.execute('CREATE TABLE IF NOT EXISTS dm_pairs(user_low INTEGER,user_high INTEGER,channel_id INTEGER,PRIMARY KEY(user_low,user_high))')
 c.close()
dm_init();group_init();file_init();invite_init()

def build(args):
 app=web.Application(middlewares=[error_middleware],client_max_size=20*1024*1024);app['node_id']=args.node_id
 app.router.add_get('/api/health',health);app.router.add_post('/api/dms',create_dm);auth_setup(app);app.router.add_post('/api/files',upload_file);app.router.add_get('/api/files/{id}',get_file);app.router.add_get('/api/files/{id}/download',download_file);app.router.add_get('/api/users/{id}',get_user);app.router.add_patch('/api/users/me',patch_profile);app.router.add_get('/api/workspaces/{slug}/groups',groups_list);app.router.add_post('/api/workspaces/{slug}/groups',group_create);app.router.add_patch('/api/workspaces/{slug}/groups/{handle}',group_patch);app.router.add_delete('/api/workspaces/{slug}/groups/{handle}',group_delete)
 app.router.add_get('/api/workspaces',workspaces);app.router.add_post('/api/workspaces',create_ws);app.router.add_get('/api/workspaces/{slug}',detail);app.router.add_patch('/api/workspaces/{slug}',ws_patch);app.router.add_post('/api/workspaces/{slug}/invitations',inv_create);app.router.add_get('/api/workspaces/{slug}/invitations',inv_list);app.router.add_delete('/api/workspaces/{slug}/invitations/{code}',inv_delete);app.router.add_post('/api/invitations/{code}/accept',inv_accept);app.router.add_get('/api/workspaces/{slug}/members',members);app.router.add_patch('/api/workspaces/{slug}/members/{user_id}',role_patch);app.router.add_post('/api/workspaces/{slug}/transfer_ownership',transfer);app.router.add_post('/api/workspaces/{slug}/channels',create_channel)
 app.router.add_post('/api/channels/{id}/join',join);app.router.add_post('/api/channels/{id}/messages',post);app.router.add_get('/api/channels/{id}/messages',messages);app.router.add_get('/api/messages/{id}/replies',replies);app.router.add_post('/api/messages/{id}/pin',pin_message);app.router.add_delete('/api/messages/{id}/pin',unpin_message);app.router.add_get('/api/channels/{id}/pins',pins_list);app.router.add_get('/api/search',search);app.router.add_patch('/api/messages/{id}',edit_message);app.router.add_delete('/api/messages/{id}',delete_message);app.router.add_post('/api/messages/{id}/reactions',add_reaction);app.router.add_delete('/api/messages/{id}/reactions/{emoji}',remove_reaction);app.router.add_get('/api/channels/{id}/read',get_read);app.router.add_post('/api/channels/{id}/read',set_read);app.router.add_patch('/api/channels/{id}',patch_channel);app.router.add_post('/api/channels/{id}/leave',leave_channel);app.router.add_get('/api/channels/{id}/members',channel_members);app.router.add_post('/api/channels/{id}/{action:archive|unarchive}',archive)
 app.router.add_get('/api/ws',ws_handler)
 async def index(r):
  return web.Response(text='<!doctype html><html><body><h1>Huddle</h1></body></html>',content_type='text/html')
 app.router.add_get('/',lambda r:web.FileResponse('/app/static/index.html'));app.router.add_static('/static/','/app/static');return app
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--port',type=int);p.add_argument('--node-id',type=int);a=p.parse_args();web.run_app(build(a),host='0.0.0.0',port=a.port)
