import re, secrets, time
from aiohttp import web
from db import connect,now_iso
from common import *
def setup(app):
 async def create(q):
  u=require_user(q); d=await read_json(q); slug=d.get('slug',''); name=d.get('name','')
  if not re.fullmatch(r'[a-z0-9-]{2,32}',slug) or not name: raise HTTPError(400,'invalid workspace')
  c=connect()
  try: c.execute('INSERT INTO workspaces(slug,name,owner_id,created_at) VALUES(?,?,?,?)',(slug,name,u['id'],now_iso()))
  except: raise HTTPError(409,'duplicate workspace')
  w=c.execute('SELECT * FROM workspaces WHERE slug=?',(slug,)).fetchone()
  c.execute('INSERT INTO members VALUES(?,?,?)',(w['id'],u['id'],'owner'))
  c.execute('INSERT INTO channels(workspace_id,name,created_at) VALUES(?,?,?)',(w['id'],'general',now_iso()))
  ch=c.execute('SELECT * FROM channels WHERE workspace_id=? AND name="general"',(w['id'],)).fetchone()
  c.execute('INSERT INTO channel_members VALUES(?,?)',(ch['id'],u['id']))
  return web.json_response({'workspace':dict(w),'general_channel':dict(ch)},status=201)
 async def listing(q):
  u=require_user(q); rows=connect().execute('SELECT w.* FROM workspaces w JOIN members m ON m.workspace_id=w.id WHERE m.user_id=?',(u['id'],)).fetchall()
  return web.json_response({'workspaces':[dict(x) for x in rows]})
 async def detail(q):
  u=require_user(q); c=connect(); w=c.execute('SELECT * FROM workspaces WHERE slug=?',(q.match_info['slug'],)).fetchone()
  if not w: raise HTTPError(404,'not found')
  if not c.execute('SELECT 1 FROM members WHERE workspace_id=? AND user_id=?',(w['id'],u['id'])).fetchone(): raise HTTPError(403,'forbidden')
  ch=c.execute('SELECT * FROM channels WHERE workspace_id=? AND is_dm=0 AND (is_archived=0 OR ?)',(w['id'],q.query.get('include_archived') in ('1','true'))).fetchall()
  visible=[x for x in ch if not x['is_private'] or c.execute('SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?',(x['id'],u['id'])).fetchone()]
  states=[]
  import json
  for x in visible:
   rr=c.execute('SELECT last_read_event_id FROM readstate WHERE user_id=? AND channel_id=?',(u['id'],x['id'])).fetchone()
   last=rr['last_read_event_id'] if rr else 0
   ms=c.execute('SELECT * FROM messages WHERE channel_id=? AND deleted=0 AND event_id>? AND author_id!=?',(x['id'],last,u['id'])).fetchall()
   states.append({'channel_id':x['id'],'last_read_event_id':last,'unread_count':len(ms),'mention_count':sum(u['id'] in json.loads(m['mentions'] or '[]') for m in ms)})
  return web.json_response({'workspace':dict(w),'channels':[dict(x) for x in visible],'read_state':states})
 async def members(q):
  u=require_user(q); c=connect(); w=c.execute('SELECT * FROM workspaces WHERE slug=?',(q.match_info['slug'],)).fetchone()
  if not w: raise HTTPError(404,'not found')
  rows=c.execute('SELECT m.user_id,m.role,u.* FROM members m JOIN users u ON u.id=m.user_id WHERE m.workspace_id=?',(w['id'],)).fetchall()
  return web.json_response({'members':[{'user_id':x['user_id'],'role':x['role'],'user':user_to_json(x)} for x in rows]})
 async def create_channel(q):
  u=require_user(q); d=await read_json(q); slug=q.match_info['slug']; c=connect()
  w=c.execute('SELECT * FROM workspaces WHERE slug=?',(slug,)).fetchone()
  mem=c.execute('SELECT role FROM members WHERE workspace_id=? AND user_id=?',(w['id'],u['id'])).fetchone() if w else None
  if not w: raise HTTPError(404,'not found')
  if not mem or mem['role']=='guest': raise HTTPError(403,'forbidden')
  n=d.get('name','')
  if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*',n) or len(n)>32: raise HTTPError(400,'invalid channel')
  if c.execute('SELECT 1 FROM channels WHERE workspace_id=? AND name=?',(w['id'],n)).fetchone(): raise HTTPError(409,'duplicate channel')
  if len(d.get('topic',''))>250: raise HTTPError(400,'topic too long')
  if d.get('is_private') and mem['role'] not in ('owner','admin'): raise HTTPError(403,'forbidden')
  c.execute('INSERT INTO channels(workspace_id,name,is_private,topic,created_at) VALUES(?,?,?,?,?)',(w['id'],n,int(bool(d.get('is_private'))),d.get('topic',''),now_iso()))
  ch=c.execute('SELECT * FROM channels WHERE id=last_insert_rowid()').fetchone(); c.execute('INSERT INTO channel_members VALUES(?,?)',(ch['id'],u['id']))
  return web.json_response({'channel':{**dict(ch),'is_private':bool(ch['is_private']),'is_dm':bool(ch['is_dm']),'is_archived':bool(ch['is_archived'])}},status=201)
 app.router.add_post('/api/workspaces',create); app.router.add_get('/api/workspaces',listing); app.router.add_get('/api/workspaces/{slug}',detail); app.router.add_get('/api/workspaces/{slug}/members',members); app.router.add_post('/api/workspaces/{slug}/channels',create_channel)

 async def set_role(q):
  u=require_user(q); d=await read_json(q); c=connect(); slug=q.match_info['slug']
  w=c.execute('SELECT * FROM workspaces WHERE slug=?',(slug,)).fetchone()
  if not w: raise HTTPError(404,'not found')
  actor=c.execute('SELECT role FROM members WHERE workspace_id=? AND user_id=?',(w['id'],u['id'])).fetchone()
  if not actor or actor['role'] not in ('owner','admin'): raise HTTPError(403,'forbidden')
  target_id=int(q.match_info['user_id']) if q.match_info['user_id'].isdigit() else 0
  target=c.execute('SELECT role FROM members WHERE workspace_id=? AND user_id=?',(w['id'],target_id)).fetchone()
  if not target: raise HTTPError(404,'not found')
  role=d.get('role')
  if role not in ('owner','admin','member','guest') or role=='owner': raise HTTPError(400,'invalid role')
  if target['role']=='owner' or target_id==w['owner_id']: raise HTTPError(403,'cannot modify owner')
  if actor['role']=='admin' and target['role']=='admin': raise HTTPError(403,'cannot modify admin')
  c.execute('UPDATE members SET role=? WHERE workspace_id=? AND user_id=?',(role,w['id'],target_id))
  return web.json_response({'member':{'user_id':target_id,'role':role,'joined_at':None}})
 async def transfer(q):
  u=require_user(q); d=await read_json(q); c=connect()
  w=c.execute('SELECT * FROM workspaces WHERE slug=?',(q.match_info['slug'],)).fetchone()
  if not w: raise HTTPError(404,'not found')
  if w['owner_id']!=u['id']: raise HTTPError(403,'forbidden')
  tid=d.get('new_owner_id'); t=c.execute('SELECT role FROM members WHERE workspace_id=? AND user_id=?',(w['id'],tid)).fetchone()
  if not t or t['role']!='admin': raise HTTPError(400,'target must be admin')
  c.execute('UPDATE members SET role="admin" WHERE workspace_id=? AND user_id=?',(w['id'],u['id']))
  c.execute('UPDATE members SET role="owner" WHERE workspace_id=? AND user_id=?',(w['id'],tid))
  c.execute('UPDATE workspaces SET owner_id=? WHERE id=?',(tid,w['id']))
  return web.json_response({'workspace':dict(c.execute('SELECT * FROM workspaces WHERE id=?',(w['id'],)).fetchone())})
 async def patch_workspace(q):
  u=require_user(q); d=await read_json(q); c=connect(); w=c.execute('SELECT * FROM workspaces WHERE slug=?',(q.match_info['slug'],)).fetchone()
  if not w: raise HTTPError(404,'not found')
  r=c.execute('SELECT role FROM members WHERE workspace_id=? AND user_id=?',(w['id'],u['id'])).fetchone()
  if not r or r['role'] not in ('owner','admin'): raise HTTPError(403,'forbidden')
  if 'name' in d and (not isinstance(d['name'],str) or not d['name']): raise HTTPError(400,'invalid name')
  if 'join_mode' in d and d['join_mode'] not in ('open','invite_only'): raise HTTPError(400,'invalid join mode')
  vals=[]; args=[]
  for k in ('name','join_mode'):
   if k in d: vals.append(k+'=?'); args.append(d[k])
  if vals: c.execute('UPDATE workspaces SET '+','.join(vals)+' WHERE id=?',(*args,w['id']))
  return web.json_response({'workspace':dict(c.execute('SELECT * FROM workspaces WHERE id=?',(w['id'],)).fetchone())})
 async def create_inv(q):
  u=require_user(q); d=await read_json(q); c=connect(); w=c.execute('SELECT * FROM workspaces WHERE slug=?',(q.match_info['slug'],)).fetchone()
  if not w: raise HTTPError(404,'not found')
  r=c.execute('SELECT role FROM members WHERE workspace_id=? AND user_id=?',(w['id'],u['id'])).fetchone()
  if not r or r['role'] not in ('owner','admin'): raise HTTPError(403,'forbidden')
  target=d.get('invited_user_id')
  if d.get('invited_username'):
   x=c.execute('SELECT id FROM users WHERE username=?',(d['invited_username'],)).fetchone()
   if not x: raise HTTPError(400,'unknown user')
   target=x['id']
  try: mx=int(d.get('max_uses',1))
  except: raise HTTPError(400,'invalid max_uses')
  if mx<1: raise HTTPError(400,'invalid max_uses')
  if target is not None: mx=1
  exp=None
  if 'expires_in_seconds' in d:
   try: exp=time.time()+float(d['expires_in_seconds'])
   except: raise HTTPError(400,'invalid expiry')
  code=secrets.token_urlsafe(12); c.execute('INSERT INTO invitations VALUES(?,?,?,?,?,?,?,?,?)',(code,w['id'],u['id'],mx,0,exp,target,0,now_iso()))
  return web.json_response({'invitation':dict(c.execute('SELECT * FROM invitations WHERE code=?',(code,)).fetchone())},status=201)
 def active(x): return not x['revoked'] and x['uses']<x['max_uses'] and (x['expires_at'] is None or x['expires_at']>time.time())
 async def list_inv(q):
  u=require_user(q); c=connect(); w=c.execute('SELECT * FROM workspaces WHERE slug=?',(q.match_info['slug'],)).fetchone()
  if not w: raise HTTPError(404,'not found')
  r=c.execute('SELECT role FROM members WHERE workspace_id=? AND user_id=?',(w['id'],u['id'])).fetchone()
  if not r or r['role'] not in ('owner','admin'): raise HTTPError(403,'forbidden')
  return web.json_response({'invitations':[dict(x) for x in c.execute('SELECT * FROM invitations WHERE workspace_id=? AND revoked=0',(w['id'],)).fetchall() if active(x)]})
 async def delete_inv(q):
  u=require_user(q); c=connect(); w=c.execute('SELECT * FROM workspaces WHERE slug=?',(q.match_info['slug'],)).fetchone()
  if not w: raise HTTPError(404,'not found')
  r=c.execute('SELECT role FROM members WHERE workspace_id=? AND user_id=?',(w['id'],u['id'])).fetchone()
  if not r or r['role'] not in ('owner','admin'): raise HTTPError(403,'forbidden')
  x=c.execute('SELECT * FROM invitations WHERE code=? AND workspace_id=?',(q.match_info['code'],w['id'])).fetchone()
  if not x: raise HTTPError(404,'not found')
  c.execute('UPDATE invitations SET revoked=1 WHERE code=?',(x['code'],)); return web.json_response({'deleted':True})
 async def accept_inv(q):
  u=require_user(q); c=connect(); x=c.execute('SELECT * FROM invitations WHERE code=?',(q.match_info['code'],)).fetchone()
  if not x or not active(x): raise HTTPError(404,'not found')
  if x['invited_user_id'] is not None and x['invited_user_id']!=u['id']: raise HTTPError(403,'wrong target')
  w=c.execute('SELECT * FROM workspaces WHERE id=?',(x['workspace_id'],)).fetchone()
  c.execute('INSERT OR IGNORE INTO members VALUES(?,?,?)',(w['id'],u['id'],'member'))
  g=c.execute('SELECT id FROM channels WHERE workspace_id=? AND name="general"',(w['id'],)).fetchone()
  if g: c.execute('INSERT OR IGNORE INTO channel_members VALUES(?,?)',(g['id'],u['id']))
  c.execute('UPDATE invitations SET uses=uses+1 WHERE code=?',(x['code'],))
  m=c.execute('SELECT * FROM members WHERE workspace_id=? AND user_id=?',(w['id'],u['id'])).fetchone()
  return web.json_response({'workspace':dict(w),'member':{'user_id':u['id'],'role':m['role']}})
 app.router.add_patch('/api/workspaces/{slug}',patch_workspace)
 app.router.add_post('/api/workspaces/{slug}/invitations',create_inv); app.router.add_get('/api/workspaces/{slug}/invitations',list_inv)
 app.router.add_delete('/api/workspaces/{slug}/invitations/{code}',delete_inv); app.router.add_post('/api/invitations/{code}/accept',accept_inv)
 app.router.add_patch('/api/workspaces/{slug}/members/{user_id}',set_role)
 app.router.add_post('/api/workspaces/{slug}/transfer_ownership',transfer)
