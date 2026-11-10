import re,secrets
from aiohttp import web
import db
from common import HTTPError,read_json,require_user,user_to_json,channel_json
def setup(app):
 async def create(req):
  u=require_user(req); b=await read_json(req); slug=b.get('slug',''); name=b.get('name','')
  if not re.fullmatch(r'[a-z0-9-]{2,32}',str(slug)) or not isinstance(name,str) or not name: raise HTTPError(400,'invalid workspace')
  if db.CONN.execute('SELECT 1 FROM workspaces WHERE slug=?',(slug,)).fetchone(): raise HTTPError(409,'workspace exists')
  now=db.now_iso(); c=db.CONN
  wid=c.execute('INSERT INTO workspaces(slug,name,owner_id,created_at) VALUES(?,?,?,?)',(slug,name,u['id'],now)).lastrowid
  c.execute('INSERT INTO workspace_members(workspace_id,user_id,role) VALUES(?,?,?)',(wid,u['id'],'owner'))
  cid=c.execute('INSERT INTO channels(workspace_id,name,created_at) VALUES(?,?,?)',(wid,'general',now)).lastrowid
  c.execute('INSERT INTO channel_members(channel_id,user_id) VALUES(?,?)',(cid,u['id']))
  w=c.execute('SELECT * FROM workspaces WHERE id=?',(wid,)).fetchone(); ch=c.execute('SELECT * FROM channels WHERE id=?',(cid,)).fetchone()
  return web.json_response({'workspace':dict(w),'general_channel':channel_json(ch)},status=201)
 async def listing(req):
  u=require_user(req); rows=db.CONN.execute('SELECT w.* FROM workspaces w JOIN workspace_members m ON m.workspace_id=w.id WHERE m.user_id=?',(u['id'],)).fetchall()
  return web.json_response({'workspaces':[dict(x) for x in rows]})
 async def detail(req):
  u=require_user(req); w=db.CONN.execute('SELECT * FROM workspaces WHERE slug=?',(req.match_info['slug'],)).fetchone()
  if not w: raise HTTPError(404,'workspace not found')
  mem=db.CONN.execute('SELECT 1 FROM workspace_members WHERE workspace_id=? AND user_id=?',(w['id'],u['id'])).fetchone()
  if not mem: raise HTTPError(403,'not a member')
  cs=db.CONN.execute('SELECT c.* FROM channels c WHERE c.workspace_id=? AND c.is_dm=0 AND (c.is_archived=0 OR ?=1) AND (c.is_private=0 OR EXISTS(SELECT 1 FROM channel_members cm WHERE cm.channel_id=c.id AND cm.user_id=?))',(w['id'],req.query.get('include_archived') in ('1','true'),u['id'])).fetchall()
  states=[]
  for ch in cs:
   z=db.CONN.execute('SELECT last_read_event_id FROM read_state WHERE user_id=? AND channel_id=?',(u['id'],ch['id'])).fetchone()
   last=z[0] if z else 0
   unread=db.CONN.execute("SELECT count(*) FROM events e JOIN messages m ON json_extract(e.payload,'$.message.id')=m.id WHERE e.channel_id=? AND e.event_id>? AND m.author_id!=?",(ch['id'],last,u['id'])).fetchone()[0]
   mention=db.CONN.execute("SELECT count(*) FROM events e JOIN messages m ON json_extract(e.payload,'$.message.id')=m.id WHERE e.channel_id=? AND e.event_id>? AND m.author_id!=? AND m.mentions LIKE ?", (ch['id'],last,u['id'],'%'+str(u['id'])+'%')).fetchone()[0]
   states.append({'channel_id':ch['id'],'last_read_event_id':last,'unread_count':unread,'mention_count':mention})
  return web.json_response({'workspace':dict(w),'channels':[channel_json(x) for x in cs],'read_state':states})
 async def members(req):
  u=require_user(req); w=db.CONN.execute('SELECT * FROM workspaces WHERE slug=?',(req.match_info['slug'],)).fetchone()
  if not w: raise HTTPError(404,'workspace not found')
  if not db.CONN.execute('SELECT 1 FROM workspace_members WHERE workspace_id=? AND user_id=?',(w['id'],u['id'])).fetchone(): raise HTTPError(403,'not a member')
  rows=db.CONN.execute('SELECT m.*,u.* FROM workspace_members m JOIN users u ON u.id=m.user_id WHERE m.workspace_id=?',(w['id'],)).fetchall()
  return web.json_response({'members':[{'user_id':x['user_id'],'role':x['role'],'user':user_to_json(x)} for x in rows]})
 async def create_channel(req):
  u=require_user(req); slug=req.match_info['slug']; w=db.CONN.execute('SELECT * FROM workspaces WHERE slug=?',(slug,)).fetchone()
  if not w: raise HTTPError(404,'workspace not found')
  m=db.CONN.execute('SELECT role FROM workspace_members WHERE workspace_id=? AND user_id=?',(w['id'],u['id'])).fetchone()
  if not m: raise HTTPError(403,'not a member')
  b=await read_json(req); name=b.get('name','')
  if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*',str(name)) or len(name)>32: raise HTTPError(400,'invalid channel')
  private=bool(b.get('is_private',False))
  if not isinstance(b.get('topic',''),str) or len(b.get('topic',''))>250: raise HTTPError(400,'invalid topic')
  if m['role']=='guest' or (private and m['role'] not in ('owner','admin')): raise HTTPError(403,'forbidden')
  if db.CONN.execute('SELECT 1 FROM channels WHERE workspace_id=? AND name=?',(w['id'],name)).fetchone(): raise HTTPError(409,'channel exists')
  now=db.now_iso(); cid=db.CONN.execute('INSERT INTO channels(workspace_id,name,is_private,topic,created_at) VALUES(?,?,?,?,?)',(w['id'],name,int(private),b.get('topic',''),now)).lastrowid
  db.CONN.execute('INSERT INTO channel_members VALUES(?,?)',(cid,u['id']))
  return web.json_response({'channel':channel_json(db.CONN.execute('SELECT * FROM channels WHERE id=?',(cid,)).fetchone())},status=201)

 async def patch_ws(req):
  u=require_user(req); w=db.CONN.execute('SELECT * FROM workspaces WHERE slug=?',(req.match_info['slug'],)).fetchone()
  if not w: raise HTTPError(404,'workspace not found')
  m=db.CONN.execute('SELECT role FROM workspace_members WHERE workspace_id=? AND user_id=?',(w['id'],u['id'])).fetchone()
  if not m or m['role'] not in ('owner','admin'): raise HTTPError(403,'forbidden')
  b=await read_json(req)
  if 'join_mode' in b and b['join_mode'] not in ('open','invite_only'): raise HTTPError(400,'invalid join mode')
  vals={k:b[k] for k in ('name','join_mode') if k in b}
  if vals: db.CONN.execute('UPDATE workspaces SET '+','.join(k+'=?' for k in vals)+' WHERE id=?',tuple(vals.values())+(w['id'],))
  return web.json_response({'workspace':dict(db.CONN.execute('SELECT * FROM workspaces WHERE id=?',(w['id'],)).fetchone())})
 async def role(req):
  u=require_user(req); w=db.CONN.execute('SELECT * FROM workspaces WHERE slug=?',(req.match_info['slug'],)).fetchone()
  if not w: raise HTTPError(404,'workspace not found')
  me=db.CONN.execute('SELECT role FROM workspace_members WHERE workspace_id=? AND user_id=?',(w['id'],u['id'])).fetchone()
  target=db.CONN.execute('SELECT role FROM workspace_members WHERE workspace_id=? AND user_id=?',(w['id'],req.match_info['user_id'])).fetchone()
  if not target: raise HTTPError(404,'member not found')
  if not me or me['role'] not in ('owner','admin'): raise HTTPError(403,'forbidden')
  b=await read_json(req); role=b.get('role')
  if role not in ('owner','admin','member','guest') or role=='owner': raise HTTPError(400,'invalid role')
  if target['role']=='owner' or (me['role']=='admin' and target['role']=='admin'): raise HTTPError(403,'forbidden')
  db.CONN.execute('UPDATE workspace_members SET role=? WHERE workspace_id=? AND user_id=?',(role,w['id'],req.match_info['user_id']))
  return web.json_response({'member':{'user_id':int(req.match_info['user_id']),'role':role}})
 async def transfer(req):
  u=require_user(req); w=db.CONN.execute('SELECT * FROM workspaces WHERE slug=?',(req.match_info['slug'],)).fetchone()
  if not w or w['owner_id']!=u['id']: raise HTTPError(403,'forbidden')
  b=await read_json(req); x=db.CONN.execute('SELECT role FROM workspace_members WHERE workspace_id=? AND user_id=?',(w['id'],b.get('new_owner_id'))).fetchone()
  if not x or x['role']!='admin': raise HTTPError(400,'target must be admin')
  db.CONN.execute('UPDATE workspace_members SET role=? WHERE workspace_id=? AND user_id=?',('admin',w['id'],u['id']))
  db.CONN.execute('UPDATE workspace_members SET role=? WHERE workspace_id=? AND user_id=?',('owner',w['id'],b['new_owner_id']))
  db.CONN.execute('UPDATE workspaces SET owner_id=? WHERE id=?',(b['new_owner_id'],w['id']))
  return web.json_response({'workspace':dict(db.CONN.execute('SELECT * FROM workspaces WHERE id=?',(w['id'],)).fetchone())})
 app.router.add_post('/api/workspaces',create); app.router.add_get('/api/workspaces',listing)
 app.router.add_get('/api/workspaces/{slug}',detail); app.router.add_get('/api/workspaces/{slug}/members',members)

 async def inv_create(req):
  u=require_user(req); w=db.CONN.execute('SELECT * FROM workspaces WHERE slug=?',(req.match_info['slug'],)).fetchone()
  m=db.CONN.execute('SELECT role FROM workspace_members WHERE workspace_id=? AND user_id=?',(w['id'],u['id'])).fetchone() if w else None
  if not w: raise HTTPError(404,'workspace not found')
  if not m or m['role'] not in ('owner','admin'): raise HTTPError(403,'forbidden')
  b=await read_json(req); target=b.get('invited_user_id')
  if not target and b.get('invited_username'):
   z=db.CONN.execute('SELECT id FROM users WHERE username=?',(b['invited_username'],)).fetchone(); target=z['id'] if z else None
  import datetime
  exp=db.now_iso() if False else (datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(seconds=int(b.get('expires_in_seconds',604800)))).isoformat().replace('+00:00','Z')
  code=secrets.token_urlsafe(16); maxu=1 if target else int(b.get('max_uses',1))
  db.CONN.execute('INSERT INTO invitations VALUES(?,?,?,?,?,?,?)',(code,w['id'],u['id'],target,exp,maxu,0))
  return web.json_response({'invitation':{'code':code,'workspace_id':w['id'],'invited_user_id':target,'max_uses':maxu,'uses':0,'expires_at':exp}},status=201)
 async def inv_accept(req):
  u=require_user(req); x=db.CONN.execute('SELECT * FROM invitations WHERE code=?',(req.match_info['code'],)).fetchone()
  if not x: raise HTTPError(404,'invitation not found')
  import datetime
  if x['invited_user_id'] and x['invited_user_id']!=u['id']: raise HTTPError(403,'targeted invitation')
  if x['uses']>=x['max_uses'] or x['expires_at']<db.now_iso(): raise HTTPError(404,'invitation unavailable')
  db.CONN.execute('INSERT OR REPLACE INTO workspace_members VALUES(?,?,?)',(x['workspace_id'],u['id'],'member'));db.CONN.execute('UPDATE invitations SET uses=uses+1 WHERE code=?',(x['code'],))
  return web.json_response({'workspace':dict(db.CONN.execute('SELECT * FROM workspaces WHERE id=?',(x['workspace_id'],)).fetchone())})
 async def inv_list(req):
  u=require_user(req);w=db.CONN.execute('SELECT * FROM workspaces WHERE slug=?',(req.match_info['slug'],)).fetchone();m=db.CONN.execute('SELECT role FROM workspace_members WHERE workspace_id=? AND user_id=?',(w['id'],u['id'])).fetchone()
  if not m or m['role'] not in ('owner','admin'): raise HTTPError(403,'forbidden')
  return web.json_response({'invitations':[dict(x) for x in db.CONN.execute('SELECT * FROM invitations WHERE workspace_id=? AND uses<max_uses',(w['id'],))]})
 async def inv_delete(req):
  u=require_user(req);w=db.CONN.execute('SELECT * FROM workspaces WHERE slug=?',(req.match_info['slug'],)).fetchone();m=db.CONN.execute('SELECT role FROM workspace_members WHERE workspace_id=? AND user_id=?',(w['id'],u['id'])).fetchone()
  if not m or m['role'] not in ('owner','admin'): raise HTTPError(403,'forbidden')
  db.CONN.execute('DELETE FROM invitations WHERE code=?',(req.match_info['code'],));return web.json_response({'deleted':True})
 app.router.add_post('/api/workspaces/{slug}/channels',create_channel)
 app.router.add_post('/api/workspaces/{slug}/invitations',inv_create);app.router.add_get('/api/workspaces/{slug}/invitations',inv_list)
 app.router.add_post('/api/invitations/{code}/accept',inv_accept);app.router.add_delete('/api/workspaces/{slug}/invitations/{code}',inv_delete)
 app.router.add_patch('/api/workspaces/{slug}',patch_ws)
 app.router.add_patch('/api/workspaces/{slug}/members/{user_id}',role)
 app.router.add_post('/api/workspaces/{slug}/transfer_ownership',transfer)
