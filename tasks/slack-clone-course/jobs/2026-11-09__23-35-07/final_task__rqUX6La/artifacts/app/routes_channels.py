from aiohttp import web
import db
from common import HTTPError,read_json,require_user,channel_json,emit_event,user_to_json

def setup(app):
 async def getch(req):
  require_user(req)
  try: cid=int(req.match_info['id'])
  except: raise HTTPError(404,'channel not found')
  r=db.CONN.execute('SELECT * FROM channels WHERE id=?',(cid,)).fetchone()
  if not r: raise HTTPError(404,'channel not found')
  return r
 async def join(req):
  u=require_user(req); c=await getch(req); w=db.CONN.execute('SELECT * FROM workspaces WHERE id=?',(c['workspace_id'],)).fetchone()
  m=db.CONN.execute('SELECT role FROM workspace_members WHERE workspace_id=? AND user_id=?',(w['id'],u['id'])).fetchone()
  already=db.CONN.execute('SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?',(c['id'],u['id'])).fetchone()
  if c['is_private'] and not already: raise HTTPError(403,'forbidden')
  if m and m['role']=='guest' and not already: raise HTTPError(403,'forbidden')
  if not m:
   if w['join_mode']!='open': raise HTTPError(403,'forbidden')
   db.CONN.execute('INSERT INTO workspace_members VALUES(?,?,?)',(w['id'],u['id'],'member'))
  if not db.CONN.execute('SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?',(c['id'],u['id'])).fetchone():
   db.CONN.execute('INSERT INTO channel_members VALUES(?,?)',(c['id'],u['id'])); emit_event(c['id'],'member.joined',{'user_id':u['id']})
  return web.json_response({'channel':channel_json(c)})
 async def leave(req):
  u=require_user(req); c=await getch(req); db.CONN.execute('DELETE FROM channel_members WHERE channel_id=? AND user_id=?',(c['id'],u['id']))
  emit_event(c['id'],'member.left',{'user_id':u['id']})
  return web.json_response({'channel':channel_json(c)})
 async def patch(req):
  u=require_user(req); c=await getch(req)
  if c['is_archived']: raise HTTPError(423,'channel archived')
  b=await read_json(req)
  if not db.CONN.execute('SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?',(c['id'],u['id'])).fetchone() and db.CONN.execute('SELECT owner_id FROM workspaces WHERE id=?',(c['workspace_id'],)).fetchone()['owner_id']!=u['id']: raise HTTPError(403,'forbidden')
  t=b.get('topic','')
  if not isinstance(t,str) or len(t)>250: raise HTTPError(400,'invalid topic')
  db.CONN.execute('UPDATE channels SET topic=? WHERE id=?',(t,c['id'])); c=db.CONN.execute('SELECT * FROM channels WHERE id=?',(c['id'],)).fetchone()
  emit_event(c['id'],'channel.updated',{'channel':channel_json(c)}); return web.json_response({'channel':channel_json(c)})
 async def members(req):
  c=await getch(req); rows=db.CONN.execute('SELECT u.* FROM channel_members m JOIN users u ON u.id=m.user_id WHERE m.channel_id=?',(c['id'],)).fetchall()
  return web.json_response({'members':[user_to_json(x) for x in rows]})
 async def archive(req):
  u=require_user(req); c=await getch(req); w=db.CONN.execute('SELECT owner_id FROM workspaces WHERE id=?',(c['workspace_id'],)).fetchone()
  if w['owner_id']!=u['id']: raise HTTPError(403,'forbidden')
  on=req.path.endswith('/archive'); db.CONN.execute('UPDATE channels SET is_archived=? WHERE id=?',(int(on),c['id']))
  c=db.CONN.execute('SELECT * FROM channels WHERE id=?',(c['id'],)).fetchone(); emit_event(c['id'],'channel.archived' if on else 'channel.unarchived',{})
  return web.json_response({'channel':channel_json(c)})
 app.router.add_post('/api/channels/{id}/join',join);app.router.add_post('/api/channels/{id}/leave',leave)
 app.router.add_patch('/api/channels/{id}',patch);app.router.add_get('/api/channels/{id}/members',members)
 app.router.add_post('/api/channels/{id}/archive',archive);app.router.add_post('/api/channels/{id}/unarchive',archive)
