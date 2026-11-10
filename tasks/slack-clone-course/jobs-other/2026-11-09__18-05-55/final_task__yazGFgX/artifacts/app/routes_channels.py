from aiohttp import web
from db import connect
from common import *
def setup(app):
 async def join(q):
  u=require_user(q); c=connect(); ch=c.execute('SELECT * FROM channels WHERE id=?',(q.match_info['id'],)).fetchone()
  if not ch: raise HTTPError(404,'not found')
  w=c.execute('SELECT * FROM workspaces WHERE id=?',(ch['workspace_id'],)).fetchone()
  role=c.execute('SELECT role FROM members WHERE workspace_id=? AND user_id=?',(w['id'],u['id'])).fetchone()
  if role and role['role']=='guest': raise HTTPError(403,'guests cannot join')
  if ch['is_private']: raise HTTPError(403,'private channel')
  role=c.execute('SELECT role FROM members WHERE workspace_id=? AND user_id=?',(w['id'],u['id'])).fetchone() if False else None
  if not c.execute('SELECT 1 FROM members WHERE workspace_id=? AND user_id=?',(w['id'],u['id'])).fetchone():
   if w['join_mode']!='open': raise HTTPError(403,'invite required')
   c.execute('INSERT INTO members VALUES(?,?,?)',(w['id'],u['id'],'member'))
  existed=c.execute('SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?',(ch['id'],u['id'])).fetchone()
  c.execute('INSERT OR IGNORE INTO channel_members VALUES(?,?)',(ch['id'],u['id']))
  if not existed:
   emit_event(ch['id'],'member.joined',{'user_id':u['id'],'user':user_to_json(u)})
  return web.json_response({'channel':_ch(ch)})
 async def patch(q):
  u=require_user(q); d=await read_json(q); c=connect(); ch=c.execute('SELECT * FROM channels WHERE id=?',(q.match_info['id'],)).fetchone()
  if not ch: raise HTTPError(404,'not found')
  if ch['is_archived']: raise HTTPError(423,'archived')
  if len(d.get('topic',''))>250: raise HTTPError(400,'topic too long')
  role=c.execute('SELECT role FROM members WHERE workspace_id=? AND user_id=?',(ch['workspace_id'],u['id'])).fetchone()
  if not c.execute('SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?',(ch['id'],u['id'])).fetchone() and not (role and role['role']=='owner'): raise HTTPError(403,'forbidden')
  c.execute('UPDATE channels SET topic=? WHERE id=?',(d.get('topic',''),ch['id']))
  emit_event(ch['id'],'channel.updated',{'channel':_ch(c.execute('SELECT * FROM channels WHERE id=?',(ch['id'],)).fetchone())})
  return web.json_response({'channel':_ch(c.execute('SELECT * FROM channels WHERE id=?',(ch['id'],)).fetchone())})
 async def leave(q):
  u=require_user(q); c=connect(); ch=c.execute('SELECT * FROM channels WHERE id=?',(q.match_info['id'],)).fetchone()
  if not ch: raise HTTPError(404,'not found')
  existed=c.execute('SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?',(ch['id'],u['id'])).fetchone()
  c.execute('DELETE FROM channel_members WHERE channel_id=? AND user_id=?',(ch['id'],u['id']))
  if existed: emit_event(ch['id'],'member.left',{'user_id':u['id']})
  return web.json_response({'channel':_ch(ch)})
 async def cmembers(q):
  u=require_user(q); c=connect(); ch=c.execute('SELECT * FROM channels WHERE id=?',(q.match_info['id'],)).fetchone()
  if not ch: raise HTTPError(404,'not found')
  rows=c.execute('SELECT u.* FROM users u JOIN channel_members m ON m.user_id=u.id WHERE m.channel_id=?',(ch['id'],)).fetchall()
  return web.json_response({'members':[user_to_json(x) for x in rows]})
 async def archive(q):
  u=require_user(q); c=connect(); ch=c.execute('SELECT * FROM channels WHERE id=?',(q.match_info['id'],)).fetchone()
  if not ch: raise HTTPError(404,'not found')
  w=c.execute('SELECT owner_id FROM workspaces WHERE id=?',(ch['workspace_id'],)).fetchone()
  if w['owner_id']!=u['id']: raise HTTPError(403,'owner only')
  flag=1 if q.path.endswith('/archive') else 0
  c.execute('UPDATE channels SET is_archived=? WHERE id=?',(flag,ch['id']))
  emit_event(ch['id'],'channel.archived' if flag else 'channel.unarchived',{'channel':_ch(c.execute('SELECT * FROM channels WHERE id=?',(ch['id'],)).fetchone())})
  return web.json_response({'channel':_ch(c.execute('SELECT * FROM channels WHERE id=?',(ch['id'],)).fetchone())})
 app.router.add_post('/api/channels/{id}/join',join); app.router.add_patch('/api/channels/{id}',patch)
 app.router.add_post('/api/channels/{id}/leave',leave); app.router.add_get('/api/channels/{id}/members',cmembers)
 app.router.add_post('/api/channels/{id}/archive',archive); app.router.add_post('/api/channels/{id}/unarchive',archive)

def _ch(r):
 d=dict(r)
 for k in ('is_private','is_dm','is_archived'): d[k]=bool(d[k])
 return d
