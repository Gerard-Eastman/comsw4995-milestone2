from aiohttp import web
from db import connect,now_iso
from common import *
import re
def setup(app):
 async def create(req):
  u=require_user(req); d=await read_json(req); c=connect(); w=c.execute('SELECT * FROM workspaces WHERE slug=?',(req.match_info['slug'],)).fetchone()
  if not w: raise HTTPError(404,'not found')
  if not c.execute('SELECT 1 FROM workspace_members WHERE workspace_id=? AND user_id=?',(w['id'],u['id'])).fetchone(): raise HTTPError(403,'forbidden')
  name=d.get('name','')
  if not re.fullmatch(r'[a-z0-9]+(-[a-z0-9]+)*',name) or len(name)>32: raise HTTPError(400,'invalid channel')
  if c.execute('SELECT 1 FROM channels WHERE workspace_id=? AND name=?',(w['id'],name)).fetchone(): raise HTTPError(409,'channel exists')
  c.execute('INSERT INTO channels(workspace_id,name,is_private,topic,created_at) VALUES(?,?,?,?,?)',(w['id'],name,int(bool(d.get('is_private'))),d.get('topic',''),now_iso()))
  cid=c.execute('SELECT last_insert_rowid()').fetchone()[0]; c.execute('INSERT INTO channel_members VALUES(?,?)',(cid,u['id'])); ch=c.execute('SELECT * FROM channels WHERE id=?',(cid,)).fetchone(); c.close()
  return web.json_response({'channel':channel_json(ch)},status=201)
 async def join(req):
  u=require_user(req); c=connect(); ch=c.execute('SELECT * FROM channels WHERE id=?',(req.match_info['id'],)).fetchone()
  if not ch: raise HTTPError(404,'not found')
  if ch['is_private']: raise HTTPError(403,'private channel')
  if not c.execute('SELECT 1 FROM workspace_members WHERE workspace_id=? AND user_id=?',(ch['workspace_id'],u['id'])).fetchone(): c.execute('INSERT OR IGNORE INTO workspace_members VALUES(?,?,?)',(ch['workspace_id'],u['id'],'member'))
  c.execute('INSERT OR IGNORE INTO channel_members VALUES(?,?)',(ch['id'],u['id'])); c.close(); return web.json_response({'channel':channel_json(ch)})
 async def patch(req):
  u=require_user(req); d=await read_json(req); c=connect(); ch=c.execute('SELECT * FROM channels WHERE id=?',(req.match_info['id'],)).fetchone()
  if not ch: raise HTTPError(404,'not found')
  c.execute('UPDATE channels SET topic=? WHERE id=?',(d.get('topic',''),ch['id'])); ch=c.execute('SELECT * FROM channels WHERE id=?',(ch['id'],)).fetchone(); c.close(); emit_event(ch['id'],'channel.updated',{'channel':channel_json(ch)}); return web.json_response({'channel':channel_json(ch)})
 async def archive(req):
  u=require_user(req); c=connect(); ch=c.execute('SELECT ch.*,w.owner_id FROM channels ch JOIN workspaces w ON w.id=ch.workspace_id WHERE ch.id=?',(req.match_info['id'],)).fetchone()
  if not ch: raise HTTPError(404,'not found')
  if ch['owner_id']!=u['id']: raise HTTPError(403,'forbidden')
  c.execute('UPDATE channels SET is_archived=? WHERE id=?',(1 if req.path.endswith('/archive') else 0,ch['id']))
  ch=c.execute('SELECT * FROM channels WHERE id=?',(ch['id'],)).fetchone(); c.close()
  emit_event(ch['id'],'channel.archived' if ch['is_archived'] else 'channel.unarchived',{'channel':channel_json(ch)})
  return web.json_response({'channel':channel_json(ch)})
 app.router.add_post('/api/workspaces/{slug}/channels',create); app.router.add_post('/api/channels/{id}/join',join); app.router.add_patch('/api/channels/{id}',patch)
 app.router.add_post('/api/channels/{id}/archive',archive); app.router.add_post('/api/channels/{id}/unarchive',archive)
