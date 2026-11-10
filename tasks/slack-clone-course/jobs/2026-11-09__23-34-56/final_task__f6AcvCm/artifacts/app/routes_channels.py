from aiohttp import web
import db,re
from common import *
from routes_workspaces import workspace_by_slug,role_of,add_workspace_member
def channel_by_id(i):
 try: i=int(i)
 except: raise HTTPError(404,'channel not found')
 r=db.conn.execute('SELECT * FROM channels WHERE id=?',(i,)).fetchone()
 if not r: raise HTTPError(404,'channel not found')
 return r
def channel_to_json(r):
 return {'id':r['id'],'workspace_id':r['workspace_id'],'name':r['name'],'is_private':bool(r['is_private']),'is_dm':bool(r['is_dm']),'topic':r['topic'] or '','is_archived':bool(r['is_archived']),'created_at':r['created_at']}
def is_channel_member(c,u): return bool(db.conn.execute('SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?',(c,u)).fetchone())
def can_read_channel(c,u):
 if is_channel_member(c['id'],u): return True
 return not c['is_private'] and bool(role_of(c['workspace_id'],u))
def read_state_for(c,u):
 r=db.conn.execute('SELECT last_read_event_id FROM channel_members WHERE channel_id=? AND user_id=?',(c,u)).fetchone()
 last=r['last_read_event_id'] if r else 0
 return {'channel_id':c,'last_read_event_id':last,'unread_count':0,'mention_count':0}
def add_channel_member(c,u):
 if not is_channel_member(c,u):
  db.conn.execute('INSERT INTO channel_members VALUES(?,?,?)',(c,u,0))
  e=emit_event(c,'member.joined',{'user_id':u})
  db.conn.execute('UPDATE channel_members SET last_read_event_id=? WHERE channel_id=? AND user_id=?',(e,c,u))
def setup(app):
 async def create(q):
  u=require_user(q); w=workspace_by_slug(q.match_info['slug']); x=await read_json(q); n=x.get('name'); role=role_of(w['id'],u)
  if role not in ('owner','admin','member') or (role=='member' and bool(x.get('is_private'))): raise HTTPError(403,'forbidden')
  if not isinstance(n,str) or not re.fullmatch(r'[a-z0-9]+(-[a-z0-9]+)*',n) or len(n)>32: raise HTTPError(400,'invalid channel')
  topic=x.get('topic','')
  if not isinstance(topic,str) or len(topic)>250: raise HTTPError(400,'invalid topic')
  if db.conn.execute('SELECT 1 FROM channels WHERE workspace_id=? AND name=?',(w['id'],n)).fetchone(): raise HTTPError(409,'exists')
  i=db.conn.execute('INSERT INTO channels(workspace_id,name,is_private,topic,created_at) VALUES(?,?,?,?,?)',(w['id'],n,int(bool(x.get('is_private'))),topic,db.now_iso())).lastrowid
  add_channel_member(i,u)
  return web.json_response({'channel':channel_to_json(channel_by_id(i))},status=201)
 async def join(q):
  u=require_user(q); c=channel_by_id(q.match_info['id']); w=db.conn.execute('SELECT * FROM workspaces WHERE id=?',(c['workspace_id'],)).fetchone()
  if is_channel_member(c['id'],u): return web.json_response({'channel':channel_to_json(c)})
  if c['is_private']: raise HTTPError(403,'private')
  role=role_of(w['id'],u)
  if role=='guest': raise HTTPError(403,'guest')
  if not role:
   if w['join_mode']!='open': raise HTTPError(403,'invite')
   add_workspace_member(w['id'],u); role='member'
  add_channel_member(c['id'],u); return web.json_response({'channel':channel_to_json(c)})
 async def patch(q):
  u=require_user(q); c=channel_by_id(q.match_info['id']); w=db.conn.execute('SELECT * FROM workspaces WHERE id=?',(c['workspace_id'],)).fetchone()
  if not is_channel_member(c['id'],u) and w['owner_id']!=u: raise HTTPError(403,'forbidden')
  if c['is_archived']: raise HTTPError(423,'archived')
  x=await read_json(q); t=x.get('topic')
  if not isinstance(t,str) or len(t)>250: raise HTTPError(400,'invalid topic')
  db.conn.execute('UPDATE channels SET topic=? WHERE id=?',(t,c['id'])); c=channel_by_id(c['id']); emit_event(c['id'],'channel.updated',{'channel':channel_to_json(c)})
  return web.json_response({'channel':channel_to_json(c)})
 async def leave(q):
  u=require_user(q); c=channel_by_id(q.match_info['id'])
  if is_channel_member(c['id'],u):
   db.conn.execute('DELETE FROM channel_members WHERE channel_id=? AND user_id=?',(c['id'],u)); emit_event(c['id'],'member.left',{'user_id':u})
  return web.json_response({'channel':channel_to_json(c)})
 async def members(q):
  u=require_user(q); c=channel_by_id(q.match_info['id'])
  if not can_read_channel(c,u): raise HTTPError(403,'forbidden')
  rows=db.conn.execute('SELECT u.* FROM users u JOIN channel_members m ON m.user_id=u.id WHERE m.channel_id=?',(c['id'],)).fetchall()
  return web.json_response({'members':[user_to_json(r) for r in rows]})
 async def addmember(q):
  u=require_user(q); c=channel_by_id(q.match_info['id'])
  if not is_channel_member(c['id'],u): raise HTTPError(403,'forbidden')
  x=await read_json(q); name=x.get('username')
  r=db.conn.execute('SELECT id FROM users WHERE username=?',(name,)).fetchone()
  if not r or not role_of(c['workspace_id'],r['id']): raise HTTPError(400,'unknown user')
  add_channel_member(c['id'],r['id'])
  rows=db.conn.execute('SELECT u.* FROM users u JOIN channel_members m ON m.user_id=u.id WHERE m.channel_id=?',(c['id'],)).fetchall()
  return web.json_response({'members':[user_to_json(z) for z in rows]})
 async def archive(q):
  u=require_user(q); c=channel_by_id(q.match_info['id']); w=db.conn.execute('SELECT * FROM workspaces WHERE id=?',(c['workspace_id'],)).fetchone()
  if w['owner_id']!=u: raise HTTPError(403,'forbidden')
  flag=q.match_info['action']=='archive'
  if bool(c['is_archived'])!=flag:
   db.conn.execute('UPDATE channels SET is_archived=? WHERE id=?',(int(flag),c['id'])); c=channel_by_id(c['id']); emit_event(c['id'],'channel.archived' if flag else 'channel.unarchived',{'channel':channel_to_json(c)})
  return web.json_response({'channel':channel_to_json(c)})
 app.router.add_post('/api/workspaces/{slug}/channels',create)
 app.router.add_post('/api/channels/{id}/join',join)
 app.router.add_patch('/api/channels/{id}',patch)
 app.router.add_post('/api/channels/{id}/leave',leave)
 app.router.add_get('/api/channels/{id}/members',members); app.router.add_post('/api/channels/{id}/members',addmember)
 app.router.add_post('/api/channels/{id}/{action:archive|unarchive}',archive)
