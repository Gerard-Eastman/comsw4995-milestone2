import re
from aiohttp import web
import db
from common import *
def channel_to_json(r):
 return {'id':r['id'],'workspace_id':r['workspace_id'],'name':r['name'],'is_private':bool(r['is_private']),'is_dm':bool(r['is_dm']),'topic':r['topic'] or '','is_archived':bool(r['is_archived']),'created_at':r['created_at']}
def workspace_by_slug(slug):
 r=db.conn.execute('SELECT * FROM workspaces WHERE slug=?',(slug,)).fetchone()
 if not r: raise HTTPError(404,'workspace not found')
 return r
def workspace_to_json(r):
 return {'id':r['id'],'slug':r['slug'],'name':r['name'],'owner_id':r['owner_id'],'join_mode':r['join_mode'],'created_at':r['created_at']}
def role_of(w,u):
 r=db.conn.execute('SELECT role FROM workspace_members WHERE workspace_id=? AND user_id=?',(w,u)).fetchone()
 return r['role'] if r else None
def add_workspace_member(w,u,role='member'):
 db.conn.execute('INSERT OR IGNORE INTO workspace_members VALUES(?,?,?,?)',(w,u,role,db.now_iso()))
def setup(app):
 async def create(q):
  u=require_user(q); x=await read_json(q); slug=x.get('slug'); name=x.get('name')
  if not isinstance(slug,str) or not re.fullmatch(r'[a-z0-9-]{2,32}',slug) or not isinstance(name,str) or not name.strip(): raise HTTPError(400,'invalid workspace')
  if db.conn.execute('SELECT 1 FROM workspaces WHERE slug=?',(slug,)).fetchone(): raise HTTPError(409,'exists')
  t=db.now_iso(); c=db.conn.execute('INSERT INTO workspaces(slug,name,owner_id,join_mode,created_at) VALUES(?,?,?,?,?)',(slug,name,u,'open',t)); wid=c.lastrowid
  add_workspace_member(wid,u,'owner')
  ch=db.conn.execute('INSERT INTO channels(workspace_id,name,created_at) VALUES(?,?,?)',(wid,'general',t)).lastrowid
  db.conn.execute('INSERT INTO channel_members VALUES(?,?,?)',(ch,u,0))
  cr=db.conn.execute('SELECT * FROM channels WHERE id=?',(ch,)).fetchone()
  return web.json_response({'workspace':workspace_to_json(db.conn.execute('SELECT * FROM workspaces WHERE id=?',(wid,)).fetchone()),'general_channel':channel_to_json(cr)},status=201)
 async def listing(q):
  u=require_user(q); rows=db.conn.execute('SELECT w.* FROM workspaces w JOIN workspace_members m ON m.workspace_id=w.id WHERE m.user_id=?',(u,)).fetchall()
  return web.json_response({'workspaces':[workspace_to_json(r) for r in rows]})
 async def detail(q):
  u=require_user(q); w=workspace_by_slug(q.match_info['slug'])
  if not role_of(w['id'],u): raise HTTPError(403,'forbidden')
  inc=q.query.get('include_archived') in ('1','true')
  rows=db.conn.execute('SELECT * FROM channels WHERE workspace_id=? AND (? OR is_archived=0) ORDER BY id',(w['id'],int(inc))).fetchall()
  rows=[r for r in rows if not r['is_private'] or db.conn.execute('SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?',(r['id'],u)).fetchone()]
  states=[]
  for r in rows:
   m=db.conn.execute('SELECT last_read_event_id FROM channel_members WHERE channel_id=? AND user_id=?',(r['id'],u)).fetchone()
   last=m['last_read_event_id'] if m else 0
   unread=db.conn.execute('SELECT count(*) n FROM messages WHERE channel_id=? AND deleted=0 AND event_id>? AND author_id!=?',(r['id'],last,u)).fetchone()['n']
   states.append({'channel_id':r['id'],'last_read_event_id':last,'unread_count':unread,'mention_count':0})
  return web.json_response({'workspace':workspace_to_json(w),'channels':[channel_to_json(r) for r in rows],'read_state':states})
 async def members(q):
  u=require_user(q); w=workspace_by_slug(q.match_info['slug'])
  if not role_of(w['id'],u): raise HTTPError(403,'forbidden')
  out=[]
  for r in db.conn.execute('SELECT m.*,u.* FROM workspace_members m JOIN users u ON u.id=m.user_id WHERE m.workspace_id=?',(w['id'],)):
   out.append({'user_id':r['user_id'],'role':r['role'],'joined_at':r['joined_at'],'user':user_to_json(r)})
  return web.json_response({'members':out})
 app.router.add_get('/api/workspaces/{slug}',detail); app.router.add_post('/api/workspaces',create); app.router.add_get('/api/workspaces',listing); app.router.add_get('/api/workspaces/{slug}/members',members)

def member_to_json(w,u):
 r=db.conn.execute('SELECT m.*,x.* FROM workspace_members m JOIN users x ON x.id=m.user_id WHERE m.workspace_id=? AND m.user_id=?',(w,u)).fetchone()
 if not r: raise HTTPError(404,'member not found')
 return {'user_id':r['user_id'],'role':r['role'],'joined_at':r['joined_at'],'user':user_to_json(r)}
def require_role(w,u,allowed):
 if role_of(w,u) not in allowed: raise HTTPError(403,'forbidden')
def _role_handlers(app):
 async def change(q):
  uid=require_user(q); w=workspace_by_slug(q.match_info['slug']); require_role(w['id'],uid,('owner','admin'))
  try: target=int(q.match_info['user_id'])
  except: raise HTTPError(404,'member not found')
  x=await read_json(q); role=x.get('role')
  if role=='owner' or role not in ('admin','member','guest'): raise HTTPError(400,'invalid role')
  old=role_of(w['id'],target)
  if not old: raise HTTPError(404,'member not found')
  if target==w['owner_id'] or (role_of(w['id'],uid)=='admin' and old=='admin'): raise HTTPError(403,'forbidden')
  db.conn.execute('UPDATE workspace_members SET role=? WHERE workspace_id=? AND user_id=?',(role,w['id'],target))
  return web.json_response({'member':member_to_json(w['id'],target)})
 async def transfer(q):
  uid=require_user(q); w=workspace_by_slug(q.match_info['slug']); require_role(w['id'],uid,('owner',))
  x=await read_json(q); target=x.get('new_owner_id')
  if role_of(w['id'],target)!='admin': raise HTTPError(400,'target must be admin')
  db.conn.execute('UPDATE workspace_members SET role=? WHERE workspace_id=? AND user_id=?',('admin',w['id'],uid))
  db.conn.execute('UPDATE workspace_members SET role=? WHERE workspace_id=? AND user_id=?',('owner',w['id'],target))
  db.conn.execute('UPDATE workspaces SET owner_id=? WHERE id=?',(target,w['id']))
  return web.json_response({'workspace':workspace_to_json(db.conn.execute('SELECT * FROM workspaces WHERE id=?',(w['id'],)).fetchone())})
 async def patch(q):
  uid=require_user(q); w=workspace_by_slug(q.match_info['slug']); require_role(w['id'],uid,('owner','admin')); x=await read_json(q)
  if 'name' in x and (not isinstance(x['name'],str) or not x['name'].strip()): raise HTTPError(400,'invalid name')
  if 'join_mode' in x and x['join_mode'] not in ('open','invite_only'): raise HTTPError(400,'invalid join mode')
  vals=[]; args=[]
  for k in ('name','join_mode'):
   if k in x: vals.append(k+'=?'); args.append(x[k])
  if vals: db.conn.execute('UPDATE workspaces SET '+','.join(vals)+' WHERE id=?',args+[w['id']])
  return web.json_response({'workspace':workspace_to_json(db.conn.execute('SELECT * FROM workspaces WHERE id=?',(w['id'],)).fetchone())})
 app.router.add_patch('/api/workspaces/{slug}/members/{user_id}',change)
 app.router.add_post('/api/workspaces/{slug}/transfer_ownership',transfer)
 app.router.add_patch('/api/workspaces/{slug}',patch)
_old_setup=setup
def setup(app):
 _old_setup(app); _role_handlers(app)

import time,secrets
def invitation_to_json(r):
 return {'code':r['code'],'workspace_id':r['workspace_id'],'created_by':r['created_by'],'max_uses':r['max_uses'],'uses':r['uses'],'expires_at':r['expires_at'],'invited_user_id':r['invited_user_id'],'created_at':r['created_at']}
def invitation_is_active(r):
 return not r['revoked'] and r['uses']<r['max_uses'] and (r['expires_at'] is None or float(r['expires_at'])>time.time())
def _invitation_handlers(app):
 async def create_inv(q):
  uid=require_user(q); w=workspace_by_slug(q.match_info['slug']); require_role(w['id'],uid,('owner','admin')); x=await read_json(q)
  target=x.get('invited_user_id')
  if x.get('invited_username') is not None:
   ur=db.conn.execute('SELECT id FROM users WHERE username=?',(x['invited_username'],)).fetchone()
   if not ur: raise HTTPError(400,'unknown user')
   target=ur['id']
  try: mx=int(x.get('max_uses',1))
  except: raise HTTPError(400,'invalid max uses')
  if mx<1: raise HTTPError(400,'invalid max uses')
  if target is not None: mx=1
  exp=x.get('expires_in_seconds'); expires=None
  if exp is not None:
   try: expires=time.time()+int(exp)
   except: raise HTTPError(400,'invalid expiry')
  code=secrets.token_urlsafe(12); t=db.now_iso()
  db.conn.execute('INSERT INTO invitations(code,workspace_id,created_by,invited_user_id,expires_at,max_uses,uses,revoked,created_at) VALUES(?,?,?,?,?,?,?,?,?)',(code,w['id'],uid,target,expires,mx,0,0,t))
  return web.json_response({'invitation':invitation_to_json(db.conn.execute('SELECT * FROM invitations WHERE code=?',(code,)).fetchone())},status=201)
 async def list_inv(q):
  uid=require_user(q); w=workspace_by_slug(q.match_info['slug']); require_role(w['id'],uid,('owner','admin'))
  rows=db.conn.execute('SELECT * FROM invitations WHERE workspace_id=? AND revoked=0 ORDER BY created_at DESC',(w['id'],)).fetchall()
  return web.json_response({'invitations':[invitation_to_json(r) for r in rows]})
 async def delete_inv(q):
  uid=require_user(q); w=workspace_by_slug(q.match_info['slug']); require_role(w['id'],uid,('owner','admin'))
  r=db.conn.execute('SELECT * FROM invitations WHERE code=? AND workspace_id=?',(q.match_info['code'],w['id'])).fetchone()
  if not r: raise HTTPError(404,'not found')
  db.conn.execute('UPDATE invitations SET revoked=1 WHERE code=?',(r['code'],)); return web.json_response({'deleted':True})
 async def accept(q):
  uid=require_user(q); r=db.conn.execute('SELECT * FROM invitations WHERE code=?',(q.match_info['code'],)).fetchone()
  if not r or not invitation_is_active(r): raise HTTPError(404,'not found')
  if r['invited_user_id'] is not None and r['invited_user_id']!=uid: raise HTTPError(403,'wrong user')
  w=db.conn.execute('SELECT * FROM workspaces WHERE id=?',(r['workspace_id'],)).fetchone()
  db.conn.execute('UPDATE invitations SET uses=uses+1 WHERE code=?',(r['code'],))
  add_workspace_member(w['id'],uid,'member')
  ch=db.conn.execute("SELECT * FROM channels WHERE workspace_id=? AND name='general'",(w['id'],)).fetchone()
  if ch and not db.conn.execute('SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?',(ch['id'],uid)).fetchone():
   db.conn.execute('INSERT INTO channel_members VALUES(?,?,?)',(ch['id'],uid,0))
  return web.json_response({'workspace':workspace_to_json(w),'member':member_to_json(w['id'],uid)})
 app.router.add_post('/api/workspaces/{slug}/invitations',create_inv)
 app.router.add_get('/api/workspaces/{slug}/invitations',list_inv)
 app.router.add_delete('/api/workspaces/{slug}/invitations/{code}',delete_inv)
 app.router.add_post('/api/invitations/{code}/accept',accept)
_invitation_handlers(_old_setup.__globals__.get('_app')) if False else None
_prev_setup=setup
def setup(app):
 _prev_setup(app); _role_handlers(app); _invitation_handlers(app)
