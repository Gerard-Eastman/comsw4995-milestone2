import re
from aiohttp import web
from common import *
async def create(req):
 u=require_user(req); w=workspace_by_slug(req.match_info['slug']); role=role_of(w['id'],u['id'])
 if not role: raise HTTPError(403,'not a member')
 d=await read_json(req); n=d.get('name'); private=bool(d.get('is_private',False)); topic=d.get('topic','')
 if not isinstance(n,str) or not re.fullmatch(r'[a-z0-9-]{1,32}',n) or not isinstance(topic,str) or len(topic)>250: raise HTTPError(400,'invalid channel')
 if role=='guest' or (private and role not in ('owner','admin')): raise HTTPError(403,'forbidden')
 c=connect()
 if c.execute('SELECT 1 FROM channels WHERE workspace_id=? AND name=?',(w['id'],n)).fetchone(): raise HTTPError(409,'channel exists')
 try: ch=create_channel(w['id'],n,private,topic,u['id'])
 except: raise HTTPError(409,'channel exists')
 return web.json_response({'channel':channel_to_json(ch)},status=201)
async def join(req):
 u=require_user(req); ch=channel_by_id(req.match_info['id']); w=connect().execute('SELECT * FROM workspaces WHERE id=?',(ch['workspace_id'],)).fetchone()
 if is_channel_member(ch['id'],u['id']): return web.json_response({'channel':channel_to_json(ch)})
 if ch['is_private']: raise HTTPError(403,'private channel')
 role=role_of(w['id'],u['id'])
 if role=='guest': raise HTTPError(403,'forbidden')
 if not role:
  if w['join_mode']!='open': raise HTTPError(403,'invite required')
  add_workspace_member(w['id'],u['id'])
 add_channel_member(ch['id'],u['id']); return web.json_response({'channel':channel_to_json(ch)})
async def leave(req):
 u=require_user(req); ch=channel_by_id(req.match_info['id']); connect().execute('DELETE FROM channel_members WHERE channel_id=? AND user_id=?',(ch['id'],u['id']))
 emit_event(ch['id'],'member.left',{'user_id':u['id']})
 return web.json_response({'channel':channel_to_json(ch)})
async def patch(req):
 u=require_user(req); ch=channel_by_id(req.match_info['id']); w=connect().execute('SELECT * FROM workspaces WHERE id=?',(ch['workspace_id'],)).fetchone()
 if ch['is_archived']: raise HTTPError(423,'channel archived')
 if not is_channel_member(ch['id'],u['id']) and w['owner_id']!=u['id']: raise HTTPError(403,'forbidden')
 d=await read_json(req)
 if 'topic' not in d or not isinstance(d['topic'],str) or len(d['topic'])>250: raise HTTPError(400,'invalid topic')
 connect().execute('UPDATE channels SET topic=? WHERE id=?',(d['topic'],ch['id']))
 emit_event(ch['id'],'channel.updated',{'channel':channel_to_json(channel_by_id(ch['id']))})
 return web.json_response({'channel':channel_to_json(channel_by_id(ch['id']))})
async def cmembers(req):
 u=require_user(req); ch=channel_by_id(req.match_info['id'])
 if not is_channel_member(ch['id'],u['id']): raise HTTPError(403,'forbidden')
 rows=connect().execute('SELECT u.* FROM channel_members m JOIN users u ON u.id=m.user_id WHERE m.channel_id=?',(ch['id'],)).fetchall()
 return web.json_response({'members':[user_to_json(x) for x in rows]})
def setup(app):
 app.router.add_post('/api/workspaces/{slug}/channels',create); app.router.add_post('/api/channels/{id}/join',join)
 app.router.add_post('/api/channels/{id}/leave',leave); app.router.add_patch('/api/channels/{id}',patch)
 app.router.add_get('/api/channels/{id}/members',cmembers)

async def archive(req):
 u=require_user(req); ch=channel_by_id(req.match_info['id']); w=connect().execute('SELECT * FROM workspaces WHERE id=?',(ch['workspace_id'],)).fetchone()
 if w['owner_id']!=u['id']: raise HTTPError(403,'owner only')
 connect().execute('UPDATE channels SET is_archived=1 WHERE id=?',(ch['id'],)); emit_event(ch['id'],'channel.archived',{'channel':channel_to_json(channel_by_id(ch['id']))})
 return web.json_response({'channel':channel_to_json(channel_by_id(ch['id']))})
async def unarchive(req):
 u=require_user(req); ch=channel_by_id(req.match_info['id']); w=connect().execute('SELECT * FROM workspaces WHERE id=?',(ch['workspace_id'],)).fetchone()
 if w['owner_id']!=u['id']: raise HTTPError(403,'owner only')
 connect().execute('UPDATE channels SET is_archived=0 WHERE id=?',(ch['id'],)); emit_event(ch['id'],'channel.unarchived',{'channel':channel_to_json(channel_by_id(ch['id']))})
 return web.json_response({'channel':channel_to_json(channel_by_id(ch['id']))})
_prev_channel_setup=setup
def setup(app):
 _prev_channel_setup(app)
 app.router.add_post('/api/channels/{id}/archive',archive); app.router.add_post('/api/channels/{id}/unarchive',unarchive)
