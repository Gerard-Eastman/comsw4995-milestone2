from aiohttp import web
import db
from common import *
from routes_workspaces import cjson

def access(u,ch,write=False):
 m=db.CONN.execute('SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?',(ch['id'],u['id'])).fetchone()
 wm=db.CONN.execute('SELECT 1 FROM workspace_members WHERE workspace_id=? AND user_id=?',(ch['workspace_id'],u['id'])).fetchone()
 if not m and not (wm and not ch['is_private']): raise HTTPError(403,'not a channel member')
 if write and ch['is_archived']: raise HTTPError(423,'channel archived')

def setup(app):
 async def getch(request):
  require_user(request)
  try: cid=int(request.match_info['id'])
  except: raise HTTPError(404,'not found')
  r=db.CONN.execute('SELECT * FROM channels WHERE id=?',(cid,)).fetchone()
  if not r: raise HTTPError(404,'not found')
  return r
 def access(u,ch,write=False):
  m=db.CONN.execute('SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?',(ch['id'],u['id'])).fetchone()
  wm=db.CONN.execute('SELECT 1 FROM workspace_members WHERE workspace_id=? AND user_id=?',(ch['workspace_id'],u['id'])).fetchone()
  if not m and not (wm and not ch['is_private']): raise HTTPError(403,'not a channel member')
  if write and ch['is_archived']: raise HTTPError(423,'channel archived')
 async def join(request):
  u=require_user(request); ch=await getch(request); w=db.CONN.execute('SELECT * FROM workspaces WHERE id=?',(ch['workspace_id'],)).fetchone()
  if ch['is_private']: raise HTTPError(403,'private channel')
  if not db.CONN.execute('SELECT 1 FROM workspace_members WHERE workspace_id=? AND user_id=?',(w['id'],u['id'])).fetchone():
   if w['join_mode']!='open': raise HTTPError(403,'workspace membership required')
   db.CONN.execute('INSERT INTO workspace_members VALUES(?,?,?)',(w['id'],u['id'],'member'))
  if not db.CONN.execute('SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?',(ch['id'],u['id'])).fetchone():
   db.CONN.execute('INSERT INTO channel_members VALUES(?,?,?)',(ch['id'],u['id'],db.now_iso())); emit_event(ch['id'],'member.joined',{'user_id':u['id']})
  return web.json_response({'channel':cjson(ch)})
 async def leave(request):
  u=require_user(request); ch=await getch(request); db.CONN.execute('DELETE FROM channel_members WHERE channel_id=? AND user_id=?',(ch['id'],u['id']))
  emit_event(ch['id'],'member.left',{'user_id':u['id']}); return web.json_response({'channel':cjson(ch)})
 async def patch(request):
  u=require_user(request); ch=await getch(request); access(u,ch); b=await read_json(request); topic=b.get('topic')
  if not isinstance(topic,str) or len(topic)>250: raise HTTPError(400,'invalid topic')
  db.CONN.execute('UPDATE channels SET topic=? WHERE id=?',(topic,ch['id']))
  ch=db.CONN.execute('SELECT * FROM channels WHERE id=?',(ch['id'],)).fetchone(); emit_event(ch['id'],'channel.updated',{'channel':cjson(ch)})
  return web.json_response({'channel':cjson(ch)})
 async def members(request):
  u=require_user(request); ch=await getch(request); access(u,ch)
  rs=db.CONN.execute('SELECT u.* FROM channel_members m JOIN users u ON u.id=m.user_id WHERE m.channel_id=?',(ch['id'],)).fetchall()
  return web.json_response({'members':[user_to_json(x) for x in rs]})
 async def archive(request):
  u=require_user(request); ch=await getch(request); w=db.CONN.execute('SELECT owner_id FROM workspaces WHERE id=?',(ch['workspace_id'],)).fetchone()
  if w['owner_id']!=u['id']: raise HTTPError(403,'owner required')
  db.CONN.execute('UPDATE channels SET is_archived=? WHERE id=?',(1 if request.path.endswith('archive') else 0,ch['id']))
  ch=db.CONN.execute('SELECT * FROM channels WHERE id=?',(ch['id'],)).fetchone()
  emit_event(ch['id'],'channel.archived' if ch['is_archived'] else 'channel.unarchived',{'channel':cjson(ch)})
  return web.json_response({'channel':cjson(ch)})
 app.router.add_post('/api/channels/{id}/join',join); app.router.add_post('/api/channels/{id}/leave',leave)
 app.router.add_patch('/api/channels/{id}',patch); app.router.add_get('/api/channels/{id}/members',members)
 app.router.add_post('/api/channels/{id}/archive',archive); app.router.add_post('/api/channels/{id}/unarchive',archive)
