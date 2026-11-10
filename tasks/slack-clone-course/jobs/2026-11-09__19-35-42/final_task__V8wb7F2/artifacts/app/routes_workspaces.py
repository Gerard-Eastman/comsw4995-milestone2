import re
from aiohttp import web
import db
from common import *

def wjson(r):
 return {'id':r['id'],'slug':r['slug'],'name':r['name'],'owner_id':r['owner_id'],'join_mode':r['join_mode']}
def cjson(r):
 return {'id':r['id'],'workspace_id':r['workspace_id'],'name':r['name'],'is_private':bool(r['is_private']),'is_dm':bool(r['is_dm']),'topic':r['topic'],'is_archived':bool(r['is_archived']),'created_at':r['created_at']}
def setup(app):
 async def create(request):
  u=require_user(request); b=await read_json(request); slug=b.get('slug'); name=b.get('name')
  if not isinstance(slug,str) or not re.fullmatch(r'[a-z0-9-]{2,32}',slug) or not isinstance(name,str) or not name.strip(): raise HTTPError(400,'invalid workspace')
  if db.CONN.execute('SELECT 1 FROM workspaces WHERE slug=?',(slug,)).fetchone(): raise HTTPError(409,'workspace exists')
  c=db.CONN; c.execute('INSERT INTO workspaces(slug,name,owner_id) VALUES(?,?,?)',(slug,name,u['id']))
  wid=c.execute('SELECT last_insert_rowid()').fetchone()[0]; c.execute('INSERT INTO workspace_members VALUES(?,?,?)',(wid,u['id'],'owner'))
  c.execute('INSERT INTO channels(workspace_id,name,created_at) VALUES(?,?,?)',(wid,'general',db.now_iso()))
  cid=c.execute('SELECT last_insert_rowid()').fetchone()[0]; c.execute('INSERT INTO channel_members VALUES(?,?,?)',(cid,u['id'],db.now_iso()))
  r=c.execute('SELECT * FROM workspaces WHERE id=?',(wid,)).fetchone(); ch=c.execute('SELECT * FROM channels WHERE id=?',(cid,)).fetchone()
  return web.json_response({'workspace':wjson(r),'general_channel':cjson(ch)},status=201)
 async def listing(request):
  u=require_user(request); rs=db.CONN.execute('SELECT w.* FROM workspaces w JOIN workspace_members m ON m.workspace_id=w.id WHERE m.user_id=?',(u['id'],)).fetchall()
  return web.json_response({'workspaces':[wjson(x) for x in rs]})
 async def detail(request):
  u=require_user(request); r=db.CONN.execute('SELECT * FROM workspaces WHERE slug=?',(request.match_info['slug'],)).fetchone()
  if not r: raise HTTPError(404,'not found')
  if not db.CONN.execute('SELECT 1 FROM workspace_members WHERE workspace_id=? AND user_id=?',(r['id'],u['id'])).fetchone(): raise HTTPError(403,'not a member')
  cs=db.CONN.execute('SELECT * FROM channels WHERE workspace_id=? AND is_dm=0 AND is_archived=0',(r['id'],)).fetchall()
  return web.json_response({'workspace':wjson(r),'channels':[cjson(x) for x in cs],'read_state':[]})
 async def members(request):
  u=require_user(request); r=db.CONN.execute('SELECT * FROM workspaces WHERE slug=?',(request.match_info['slug'],)).fetchone()
  if not r: raise HTTPError(404,'not found')
  if not db.CONN.execute('SELECT 1 FROM workspace_members WHERE workspace_id=? AND user_id=?',(r['id'],u['id'])).fetchone(): raise HTTPError(403,'not a member')
  rows=db.CONN.execute('SELECT m.*,u.* FROM workspace_members m JOIN users u ON u.id=m.user_id WHERE m.workspace_id=?',(r['id'],)).fetchall()
  return web.json_response({'members':[{'user_id':x['user_id'],'role':x['role'],'user':user_to_json(x)} for x in rows]})
 async def channels(request):
  u=require_user(request); r=db.CONN.execute('SELECT * FROM workspaces WHERE slug=?',(request.match_info['slug'],)).fetchone()
  if not r: raise HTTPError(404,'not found')
  mem=db.CONN.execute('SELECT role FROM workspace_members WHERE workspace_id=? AND user_id=?',(r['id'],u['id'])).fetchone()
  if not mem: raise HTTPError(403,'not a member')
  b=await read_json(request); name=b.get('name')
  if not isinstance(name,str) or not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*',name) or len(name)>32: raise HTTPError(400,'invalid channel')
  private=bool(b.get('is_private',False))
  if private and mem['role'] not in ('owner','admin'): raise HTTPError(403,'forbidden')
  if db.CONN.execute('SELECT 1 FROM channels WHERE workspace_id=? AND name=?',(r['id'],name)).fetchone(): raise HTTPError(409,'channel exists')
  topic=b.get('topic','')
  if not isinstance(topic,str) or len(topic)>250: raise HTTPError(400,'invalid topic')
  c=db.CONN; c.execute('INSERT INTO channels(workspace_id,name,is_private,topic,created_at) VALUES(?,?,?,?,?)',(r['id'],name,int(private),topic,db.now_iso()))
  cid=c.execute('SELECT last_insert_rowid()').fetchone()[0]; c.execute('INSERT INTO channel_members VALUES(?,?,?)',(cid,u['id'],db.now_iso()))
  return web.json_response({'channel':cjson(c.execute('SELECT * FROM channels WHERE id=?',(cid,)).fetchone())},status=201)
 app.router.add_post('/api/workspaces',create); app.router.add_get('/api/workspaces',listing)
 app.router.add_get('/api/workspaces/{slug}',detail); app.router.add_get('/api/workspaces/{slug}/members',members)
 app.router.add_post('/api/workspaces/{slug}/channels',channels)
