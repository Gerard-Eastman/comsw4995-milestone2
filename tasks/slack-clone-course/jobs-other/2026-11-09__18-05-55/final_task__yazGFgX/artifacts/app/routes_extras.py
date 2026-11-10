import os,secrets
from aiohttp import web
from db import connect,now_iso
from common import *
def setup(app):
 c0=connect(); c0.execute('CREATE TABLE IF NOT EXISTS groups(id INTEGER PRIMARY KEY,workspace_id INTEGER,handle TEXT,name TEXT,created_by INTEGER)'); c0.execute('CREATE TABLE IF NOT EXISTS group_members(group_id INTEGER,user_id INTEGER,PRIMARY KEY(group_id,user_id))')
 async def dms(q):
  u=require_user(q); d=await read_json(q); tid=d.get('user_id')
  if not isinstance(tid,int): raise HTTPError(400,'user_id')
  if not connect().execute('SELECT 1 FROM users WHERE id=?',(tid,)).fetchone(): raise HTTPError(404,'user')
  c=connect(); a,b=sorted((u['id'],tid)); r=c.execute('SELECT id FROM channels WHERE is_dm=1 AND name=?',(f'dm-{a}-{b}',)).fetchone()
  if r:return web.json_response({'channel_id':r['id']})
  c.execute('INSERT INTO channels(workspace_id,name,is_dm,created_at) VALUES(?,?,1,?)',(0,f'dm-{a}-{b}',now_iso())); cid=c.execute('SELECT last_insert_rowid() id').fetchone()['id']
  c.execute('INSERT INTO channel_members(channel_id,user_id) VALUES(?,?),(?,?)',(cid,a,cid,b)); return web.json_response({'channel_id':cid})
 async def profile(q):
  u=require_user(q); id=q.match_info.get('id')
  r=u if id=='me' else connect().execute('SELECT * FROM users WHERE id=?',(id,)).fetchone()
  if not r: raise HTTPError(404,'user')
  return web.json_response({'user':user_to_json(r)})
 async def patchprofile(q):
  u=require_user(q); d=await read_json(q); c=connect()
  limits={'display_name':80,'status_text':100,'status_emoji':64,'avatar_url':1024}
  vals={}
  for k,v in d.items():
   if k not in limits and k!='timezone': continue
   if not isinstance(v,str): raise HTTPError(400,'invalid profile')
   if k=='display_name' and not (1 <= len(v) <= 80): raise HTTPError(400,'invalid profile')
   if k in limits and len(v)>limits[k]: raise HTTPError(400,'invalid profile')
   if k=='timezone':
    import zoneinfo
    try: zoneinfo.ZoneInfo(v)
    except: raise HTTPError(400,'invalid timezone')
   vals[k]=v
  if vals:
   c.execute('UPDATE users SET '+','.join(k+'=?' for k in vals)+' WHERE id=?',(*[vals[k] for k in vals],u['id']))
  updated=user_to_json(c.execute('SELECT * FROM users WHERE id=?',(u['id'],)).fetchone())
  if vals: broadcast_global({'type':'user.updated','user':updated})
  return web.json_response({'user':user_to_json(c.execute('SELECT * FROM users WHERE id=?',(u['id'],)).fetchone())})
 async def groups(q):
  u=require_user(q); slug=q.match_info['slug']; c=connect(); w=c.execute('SELECT * FROM workspaces WHERE slug=?',(slug,)).fetchone()
  if not w: raise HTTPError(404,'workspace')
  if not c.execute('SELECT 1 FROM members WHERE workspace_id=? AND user_id=?',(w['id'],u['id'])).fetchone(): raise HTTPError(403,'forbidden')
  def gj(g):
   return {'id':g['id'],'handle':g['handle'],'name':g['name'],'member_user_ids':[x['user_id'] for x in c.execute('SELECT user_id FROM group_members WHERE group_id=? ORDER BY user_id',(g['id'],))]}
  if q.method=='GET':
   return web.json_response({'groups':[gj(g) for g in c.execute('SELECT * FROM groups WHERE workspace_id=?',(w['id'],)).fetchall()]})
  d=await read_json(q); h=d.get('handle',''); name=d.get('name',''); ids=d.get('user_ids',[])
  import re
  if not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,30}[a-z0-9])?',h) or h in ('here','channel') or not isinstance(name,str) or not name or not isinstance(ids,list): raise HTTPError(400,'invalid group')
  for i in ids:
   if not isinstance(i,int) or not c.execute('SELECT 1 FROM members WHERE workspace_id=? AND user_id=?',(w['id'],i)).fetchone(): raise HTTPError(400,'invalid member')
  if c.execute('SELECT 1 FROM groups WHERE workspace_id=? AND handle=?',(w['id'],h)).fetchone(): raise HTTPError(409,'duplicate group')
  c.execute('INSERT INTO groups(workspace_id,handle,name,created_by) VALUES(?,?,?,?)',(w['id'],h,name,u['id'])); gid=c.execute('SELECT last_insert_rowid() id').fetchone()['id']
  for i in ids: c.execute('INSERT INTO group_members VALUES(?,?)',(gid,i))
  return web.json_response({'group':gj(c.execute('SELECT * FROM groups WHERE id=?',(gid,)).fetchone())},status=201)
 async def group_change(q):
  u=require_user(q); c=connect(); w=c.execute('SELECT * FROM workspaces WHERE slug=?',(q.match_info['slug'],)).fetchone(); g=c.execute('SELECT * FROM groups WHERE workspace_id=? AND handle=?',(w['id'],q.match_info['handle'])).fetchone() if w else None
  if q.method=='DELETE':
   if g and g['created_by']!=u['id'] and w['owner_id']!=u['id']: raise HTTPError(403,'forbidden')
   if g: c.execute('DELETE FROM groups WHERE id=?',(g['id'],)); c.execute('DELETE FROM group_members WHERE group_id=?',(g['id'],))
   return web.json_response({'deleted':True})
  if not g: raise HTTPError(404,'group')
  if g['created_by']!=u['id'] and w['owner_id']!=u['id']: raise HTTPError(403,'forbidden')
  d=await read_json(q)
  if 'name' in d:
   if not isinstance(d['name'],str) or not d['name']: raise HTTPError(400,'invalid name')
   c.execute('UPDATE groups SET name=? WHERE id=?',(d['name'],g['id']))
  if 'user_ids' in d:
   for i in d['user_ids']:
    if not c.execute('SELECT 1 FROM members WHERE workspace_id=? AND user_id=?',(w['id'],i)).fetchone(): raise HTTPError(400,'invalid member')
   c.execute('DELETE FROM group_members WHERE group_id=?',(g['id'],))
   for i in d['user_ids']: c.execute('INSERT INTO group_members VALUES(?,?)',(g['id'],i))
  g=c.execute('SELECT * FROM groups WHERE id=?',(g['id'],)).fetchone()
  return web.json_response({'group':{'id':g['id'],'handle':g['handle'],'name':g['name'],'member_user_ids':[x['user_id'] for x in c.execute('SELECT user_id FROM group_members WHERE group_id=? ORDER BY user_id',(g['id'],))]}})
 async def files(q):
  u=require_user(q)
  if not q.content_type.startswith('multipart/'): raise HTTPError(400,'file')
  r=await q.multipart(); part=None
  async for x in r:
   if x.name=='file': part=x; break
  if not part: raise HTTPError(400,'file')
  data=await part.read()
  if len(data)>10*1024*1024: raise HTTPError(413,'too large')
  c=connect(); c.execute('CREATE TABLE IF NOT EXISTS files(id INTEGER PRIMARY KEY,uploader_id INTEGER,filename TEXT,content_type TEXT,size INTEGER,created_at TEXT,data BLOB)')
  c.execute('INSERT INTO files VALUES(NULL,?,?,?,?,?,?)',(u['id'],part.filename,part.headers.get('Content-Type','application/octet-stream'),len(data),now_iso(),data))
  x=c.execute('SELECT * FROM files WHERE id=last_insert_rowid()').fetchone()
  return web.json_response({'file':{k:x[k] for k in ('id','uploader_id','filename','content_type','size','created_at')}},status=201)
 async def getfile(q):
  require_user(q); x=connect().execute('SELECT * FROM files WHERE id=?',(q.match_info['id'],)).fetchone()
  if not x: raise HTTPError(404,'file')
  if q.path.endswith('/download'): return web.Response(body=x['data'],content_type=x['content_type'],headers={'Content-Disposition':f'attachment; filename="{x["filename"]}"'})
  return web.json_response({'file':{k:x[k] for k in ('id','uploader_id','filename','content_type','size','created_at')}})
 app.router.add_get('/api/workspaces/{slug}/groups',groups); app.router.add_post('/api/workspaces/{slug}/groups',groups); app.router.add_patch('/api/workspaces/{slug}/groups/{handle}',group_change); app.router.add_delete('/api/workspaces/{slug}/groups/{handle}',group_change)
 app.router.add_post('/api/dms',dms); app.router.add_get('/api/users/{id}',profile); app.router.add_patch('/api/users/me',patchprofile)
 app.router.add_post('/api/files',files); app.router.add_get('/api/files/{id}',getfile); app.router.add_get('/api/files/{id}/download',getfile)
