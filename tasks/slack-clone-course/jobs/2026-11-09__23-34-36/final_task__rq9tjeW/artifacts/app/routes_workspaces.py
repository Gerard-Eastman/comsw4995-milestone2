import re
from aiohttp import web
from db import connect, now_iso
from common import *
async def create_ws(req):
 u=require_user(req); d=await read_json(req); slug=d.get('slug'); name=d.get('name')
 if not isinstance(slug,str) or not re.fullmatch(r'[a-z0-9-]{2,32}',slug) or not isinstance(name,str) or not name.strip(): raise HTTPError(400,'invalid workspace')
 c=connect()
 if c.execute('SELECT 1 FROM workspaces WHERE slug=?',(slug,)).fetchone(): raise HTTPError(409,'workspace exists')
 c.execute('INSERT INTO workspaces(slug,name,owner_id,join_mode,created_at) VALUES(?,?,?,?,?)',(slug,name,u['id'],'open',now_iso()))
 w=c.execute('SELECT * FROM workspaces WHERE id=last_insert_rowid()').fetchone(); add_workspace_member(w['id'],u['id'],'owner')
 ch=create_channel(w['id'],'general',False,'',u['id'])
 return web.json_response({'workspace':workspace_to_json(w),'general_channel':channel_to_json(ch)},status=201)
async def list_ws(req):
 u=require_user(req); rows=connect().execute('SELECT w.* FROM workspaces w JOIN workspace_members m ON m.workspace_id=w.id WHERE m.user_id=? ORDER BY w.id',(u['id'],)).fetchall()
 return web.json_response({'workspaces':[workspace_to_json(x) for x in rows]})
async def detail(req):
 u=require_user(req); w=workspace_by_slug(req.match_info['slug'])
 if not role_of(w['id'],u['id']): raise HTTPError(403,'not a member')
 include=req.query.get('include_archived') in ('1','true'); q='SELECT * FROM channels WHERE workspace_id=?'
 if not include:q+=' AND is_archived=0'
 cs=[x for x in connect().execute(q+' AND is_dm=0',(w['id'],)).fetchall() if not x['is_private'] or is_channel_member(x['id'],u['id'])]
 states=[]
 from routes_messages import read_state_for
 for ch in cs:
  r=connect().execute('SELECT last_read_event_id FROM channel_members WHERE channel_id=? AND user_id=?',(ch['id'],u['id'])).fetchone()
  states.append(read_state_for(ch['id'],u['id']))
 return web.json_response({'workspace':workspace_to_json(w),'channels':[channel_to_json(x) for x in cs],'read_state':states})
async def members(req):
 u=require_user(req); w=workspace_by_slug(req.match_info['slug'])
 if not role_of(w['id'],u['id']): raise HTTPError(403,'not a member')
 rows=connect().execute('SELECT m.*,u.* FROM workspace_members m JOIN users u ON u.id=m.user_id WHERE m.workspace_id=?',(w['id'],)).fetchall()
 return web.json_response({'members':[{'user_id':r['user_id'],'role':r['role'],'joined_at':r['joined_at'],'user':user_to_json(r)} for r in rows]})
def setup(app):
 app.router.add_post('/api/workspaces',create_ws); app.router.add_get('/api/workspaces',list_ws)
 app.router.add_get('/api/workspaces/{slug}',detail); app.router.add_get('/api/workspaces/{slug}/members',members)

async def set_role(req):
 u=require_user(req); w=workspace_by_slug(req.match_info['slug']); actor=role_of(w['id'],u['id'])
 if actor not in ('owner','admin'): raise HTTPError(403,'forbidden')
 uid=int(req.match_info['user_id']); target=role_of(w['id'],uid)
 if target is None: raise HTTPError(404,'member not found')
 if uid==w['owner_id'] or target=='owner': raise HTTPError(403,'cannot modify owner')
 d=await read_json(req); role=d.get('role')
 if role not in ('admin','member','guest'): raise HTTPError(400,'invalid role')
 if actor=='admin' and target=='admin': raise HTTPError(403,'forbidden')
 c=connect(); c.execute('UPDATE workspace_members SET role=? WHERE workspace_id=? AND user_id=?',(role,w['id'],uid))
 return web.json_response({'member':{'user_id':uid,'role':role,'joined_at':c.execute('SELECT joined_at FROM workspace_members WHERE workspace_id=? AND user_id=?',(w['id'],uid)).fetchone()[0]}})

async def transfer(req):
 u=require_user(req); w=workspace_by_slug(req.match_info['slug'])
 if w['owner_id']!=u['id']: raise HTTPError(403,'forbidden')
 d=await read_json(req); uid=d.get('new_owner_id'); r=role_of(w['id'],uid)
 if r!='admin': raise HTTPError(400,'target must be admin')
 c=connect(); c.execute('UPDATE workspaces SET owner_id=? WHERE id=?',(uid,w['id']))
 c.execute('UPDATE workspace_members SET role=? WHERE workspace_id=? AND user_id=?',('admin',w['id'],u['id']))
 c.execute('UPDATE workspace_members SET role=? WHERE workspace_id=? AND user_id=?',('owner',w['id'],uid))
 return web.json_response({'workspace':workspace_to_json(workspace_by_slug(w['slug']))})

async def patch_ws(req):
 u=require_user(req); w=workspace_by_slug(req.match_info['slug']); r=role_of(w['id'],u['id'])
 if r not in ('owner','admin'): raise HTTPError(403,'forbidden')
 d=await read_json(req)
 if 'join_mode' in d and d['join_mode'] not in ('open','invite_only'): raise HTTPError(400,'invalid join_mode')
 if 'name' in d and (not isinstance(d['name'],str) or not d['name'].strip()): raise HTTPError(400,'invalid name')
 c=connect()
 if 'name' in d:c.execute('UPDATE workspaces SET name=? WHERE id=?',(d['name'],w['id']))
 if 'join_mode' in d:c.execute('UPDATE workspaces SET join_mode=? WHERE id=?',(d['join_mode'],w['id']))
 return web.json_response({'workspace':workspace_to_json(workspace_by_slug(w['slug']))})

async def create_inv(req):
 u=require_user(req); w=workspace_by_slug(req.match_info['slug'])
 if role_of(w['id'],u['id']) not in ('owner','admin'): raise HTTPError(403,'forbidden')
 d=await read_json(req); target=d.get('invited_user_id')
 if not target and d.get('invited_username'):
  rr=connect().execute('SELECT id FROM users WHERE username=?',(d['invited_username'],)).fetchone()
  if rr: target=rr[0]
 import secrets
 code=secrets.token_urlsafe(12); exp=d.get('expires_in_seconds')
 expires=(__import__('time').time()+int(exp)) if exp else None
 maxuses=1 if target else int(d.get('max_uses',1))
 connect().execute('INSERT INTO invitations(code,workspace_id,invited_user_id,expires_at,max_uses,uses) VALUES(?,?,?,?,?,0)',(code,w['id'],target,expires,maxuses))
 return web.json_response({'invitation':{'code':code,'workspace_id':w['id'],'invited_user_id':target,'max_uses':maxuses,'uses':0,'expires_at':expires}},status=201)

def inv_json(r): return {k:r[k] for k in ('code','workspace_id','invited_user_id','expires_at','max_uses','uses')}

async def list_inv(req):
 u=require_user(req); w=workspace_by_slug(req.match_info['slug'])
 if role_of(w['id'],u['id']) not in ('owner','admin'): raise HTTPError(403,'forbidden')
 rows=connect().execute('SELECT * FROM invitations WHERE workspace_id=? AND revoked=0 AND uses<max_uses',(w['id'],)).fetchall(); rows=[x for x in rows if x['expires_at'] is None or float(x['expires_at'])>__import__('time').time()]
 return web.json_response({'invitations':[inv_json(x) for x in rows]})

async def delete_inv(req):
 u=require_user(req); w=workspace_by_slug(req.match_info['slug'])
 if role_of(w['id'],u['id']) not in ('owner','admin'): raise HTTPError(403,'forbidden')
 c=connect(); r=c.execute('SELECT * FROM invitations WHERE code=? AND workspace_id=?',(req.match_info['code'],w['id'])).fetchone()
 if not r: raise HTTPError(404,'invitation not found')
 c.execute('UPDATE invitations SET revoked=1 WHERE code=?',(r['code'],)); return web.json_response({'deleted':True})

async def accept_inv(req):
 u=require_user(req); c=connect(); r=c.execute('SELECT * FROM invitations WHERE code=? AND revoked=0',(req.match_info['code'],)).fetchone()
 import time
 if not r or (r['expires_at'] is not None and float(r['expires_at'])<=time.time()) or r['uses']>=r['max_uses']: raise HTTPError(404,'invitation not found')
 if r['invited_user_id'] is not None and r['invited_user_id']!=u['id']: raise HTTPError(403,'targeted invitation')
 add_workspace_member(r['workspace_id'],u['id'],'member'); c.execute('UPDATE invitations SET uses=uses+1 WHERE code=?',(r['code'],))
 return web.json_response({'workspace':workspace_to_json(c.execute('SELECT * FROM workspaces WHERE id=?',(r['workspace_id'],)).fetchone())})

_old_setup=setup
def setup(app):
 _old_setup(app)
 app.router.add_patch('/api/workspaces/{slug}/members/{user_id}',set_role)
 app.router.add_post('/api/workspaces/{slug}/transfer_ownership',transfer)
 app.router.add_patch('/api/workspaces/{slug}',patch_ws)
 app.router.add_post('/api/workspaces/{slug}/invitations',create_inv)
 app.router.add_get('/api/workspaces/{slug}/invitations',list_inv)
 app.router.add_delete('/api/workspaces/{slug}/invitations/{code}',delete_inv)
 app.router.add_post('/api/invitations/{code}/accept',accept_inv)
