from aiohttp import web
from db import connect,now_iso
from common import *
import re
def setup(app):
 async def create(req):
  u=require_user(req); d=await read_json(req); slug=d.get('slug',''); name=d.get('name','')
  if not re.fullmatch(r'[a-z0-9-]{2,32}',slug) or not name: raise HTTPError(400,'invalid workspace')
  c=connect()
  if c.execute('SELECT 1 FROM workspaces WHERE slug=?',(slug,)).fetchone(): raise HTTPError(409,'workspace exists')
  c.execute('INSERT INTO workspaces(slug,name,owner_id,created_at) VALUES(?,?,?,?)',(slug,name,u['id'],now_iso()))
  wid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
  c.execute('INSERT INTO workspace_members VALUES(?,?,?)',(wid,u['id'],'owner'))
  c.execute('INSERT INTO channels(workspace_id,name,created_at) VALUES(?,?,?)',(wid,'general',now_iso()))
  cid=c.execute('SELECT last_insert_rowid()').fetchone()[0]; c.execute('INSERT INTO channel_members VALUES(?,?)',(cid,u['id']))
  w=c.execute('SELECT * FROM workspaces WHERE id=?',(wid,)).fetchone(); ch=c.execute('SELECT * FROM channels WHERE id=?',(cid,)).fetchone(); c.close()
  return web.json_response({'workspace':dict(w),'general_channel':channel_json(ch)},status=201)
 async def listing(req):
  u=require_user(req); c=connect(); rows=c.execute('SELECT w.* FROM workspaces w JOIN workspace_members m ON m.workspace_id=w.id WHERE m.user_id=?',(u['id'],)).fetchall(); c.close()
  return web.json_response({'workspaces':[dict(x) for x in rows]})
 async def detail(req):
  u=require_user(req); c=connect(); w=c.execute('SELECT * FROM workspaces WHERE slug=?',(req.match_info['slug'],)).fetchone()
  if not w: raise HTTPError(404,'not found')
  if not c.execute('SELECT 1 FROM workspace_members WHERE workspace_id=? AND user_id=?',(w['id'],u['id'])).fetchone(): raise HTTPError(403,'forbidden')
  cs=c.execute('SELECT * FROM channels WHERE workspace_id=? AND is_dm=0 AND is_archived=0',(w['id'],)).fetchall(); c.close()
  return web.json_response({'workspace':dict(w),'channels':[channel_json(x) for x in cs],'read_state':[]})
 async def members(req):
  u=require_user(req); c=connect(); w=c.execute('SELECT * FROM workspaces WHERE slug=?',(req.match_info['slug'],)).fetchone()
  if not w: raise HTTPError(404,'not found')
  rows=c.execute('SELECT m.*,u.* FROM workspace_members m JOIN users u ON u.id=m.user_id WHERE m.workspace_id=?',(w['id'],)).fetchall(); c.close()
  return web.json_response({'members':[{'user_id':x['user_id'],'role':x['role'],'user':user_to_json(x)} for x in rows]})
 app.router.add_post('/api/workspaces',create); app.router.add_get('/api/workspaces',listing); app.router.add_get('/api/workspaces/{slug}',detail); app.router.add_get('/api/workspaces/{slug}/members',members)
