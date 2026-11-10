from aiohttp import web
import os, time, uuid
from zoneinfo import ZoneInfo
import db
from common import *
def file_to_json(r):
 return {'id':r['id'],'uploader_id':r['uploader_id'],'filename':r['filename'],'content_type':r['content_type'],'size':r['size'],'created_at':r['created_at']}
def dm_channel_for(a,b):
 lo,hi=sorted((a,b)); r=db.conn.execute('SELECT channel_id FROM dm_pairs WHERE user_low=? AND user_high=?',(lo,hi)).fetchone()
 if r:return r['channel_id']
 name=f'dm-{lo}-{hi}'; t=db.now_iso()
 c=db.conn.execute('INSERT INTO channels(workspace_id,name,is_private,is_dm,created_at) VALUES(NULL,?,1,1,?)',(name,t)).lastrowid
 db.conn.execute('INSERT INTO dm_pairs VALUES(?,?,?)',(lo,hi,c))
 db.conn.execute('INSERT INTO channel_members VALUES(?,?,?)',(c,a,0)); db.conn.execute('INSERT INTO channel_members VALUES(?,?,?)',(c,b,0))
 return c
def setup(app):
 async def dms(q):
  u=require_user(q); x=await read_json(q); target=x.get('user_id')
  if not isinstance(target,int): raise HTTPError(400,'invalid user_id')
  if not db.conn.execute('SELECT 1 FROM users WHERE id=?',(target,)).fetchone(): raise HTTPError(404,'user')
  return web.json_response({'channel_id':dm_channel_for(u,target)})
 async def upload(q):
  u=require_user(q)
  if not q.content_type.startswith('multipart/'): raise HTTPError(400,'multipart required')
  try: mp=await q.multipart()
  except: raise HTTPError(400,'multipart required')
  part=None
  async for x in mp:
   if x.name=='file': part=x; break
  if part is None: raise HTTPError(400,'file required')
  data=await part.read()
  if len(data)>10*1024*1024: raise HTTPError(413,'too large')
  t=db.now_iso(); typ=part.headers.get('Content-Type','application/octet-stream'); name=part.filename or 'file'
  cur=db.conn.execute('INSERT INTO files(uploader_id,filename,content_type,size,created_at,path) VALUES(?,?,?,?,?,?)',(u,name,typ,len(data),t,''))
  fid=cur.lastrowid; path=f'/app/data/files/{fid}'; open(path,'wb').write(data); db.conn.execute('UPDATE files SET path=? WHERE id=?',(path,fid))
  return web.json_response({'file':file_to_json(db.conn.execute('SELECT * FROM files WHERE id=?',(fid,)).fetchone())},status=201)
 async def getfile(q):
  require_user(q)
  try:i=int(q.match_info['id'])
  except:raise HTTPError(404,'file')
  r=db.conn.execute('SELECT * FROM files WHERE id=?',(i,)).fetchone()
  if not r:raise HTTPError(404,'file')
  return web.json_response({'file':file_to_json(r)})
 async def download(q):
  require_user(q)
  try:i=int(q.match_info['id'])
  except:raise HTTPError(404,'file')
  r=db.conn.execute('SELECT * FROM files WHERE id=?',(i,)).fetchone()
  if not r:raise HTTPError(404,'file')
  disp='attachment; filename="'+r['filename']+'"'
  return web.Response(body=open(r['path'],'rb').read(),content_type=r['content_type'],headers={'Content-Disposition':disp})
 async def user(q):
  require_user(q)
  try:i=int(q.match_info['id'])
  except:raise HTTPError(404,'user')
  r=db.conn.execute('SELECT * FROM users WHERE id=?',(i,)).fetchone()
  if not r:raise HTTPError(404,'user')
  return web.json_response({'user':user_to_json(r)})
 async def profile(q):
  uid=require_user(q); x=await read_json(q); allowed={'display_name','timezone','avatar_url','status_text','status_emoji'}; vals={}
  for k in allowed:
   if k in x:
    v=x[k]
    if not isinstance(v,str): raise HTTPError(400,'invalid profile')
    if k=='display_name' and not 1<=len(v)<=80: raise HTTPError(400,'invalid profile')
    if k=='status_text' and len(v)>100 or k=='status_emoji' and len(v)>64 or k=='avatar_url' and len(v)>1024: raise HTTPError(400,'invalid profile')
    if k=='timezone':
     try: ZoneInfo(v)
     except: raise HTTPError(400,'invalid timezone')
    vals[k]=v
  if vals: db.conn.execute('UPDATE users SET '+','.join(k+'=?' for k in vals)+' WHERE id=?',list(vals.values())+[uid])
  r=db.conn.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone()
  broadcast_global({'type':'user.updated','user':user_to_json(r)})
  return web.json_response({'user':user_to_json(r)})
 app.router.add_post('/api/dms',dms); app.router.add_post('/api/files',upload); app.router.add_get('/api/files/{id}',getfile); app.router.add_get('/api/files/{id}/download',download)
 app.router.add_get('/api/users/{id}',user); app.router.add_patch('/api/users/me',profile)

def _groups(app):
 import re
 def gj(r):
  return {'id':r['id'],'handle':r['handle'],'name':r['name'],'member_user_ids':sorted(x['user_id'] for x in db.conn.execute('SELECT user_id FROM group_members WHERE group_id=?',(r['id'],)))}
 async def create(q):
  u=require_user(q); from routes_workspaces import workspace_by_slug,role_of
  w=workspace_by_slug(q.match_info['slug'])
  if not role_of(w['id'],u): raise HTTPError(403,'forbidden')
  x=await read_json(q); h=x.get('handle'); n=x.get('name'); ids=x.get('user_ids',[])
  if not isinstance(h,str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,30}[a-z0-9]',h) or h in ('here','channel') or not isinstance(n,str) or not n.strip() or not isinstance(ids,list): raise HTTPError(400,'invalid group')
  if any(not isinstance(i,int) or not db.conn.execute('SELECT 1 FROM workspace_members WHERE workspace_id=? AND user_id=?',(w['id'],i)).fetchone() for i in ids): raise HTTPError(400,'invalid members')
  if db.conn.execute('SELECT 1 FROM groups_tbl WHERE workspace_id=? AND handle=?',(w['id'],h)).fetchone(): raise HTTPError(409,'exists')
  i=db.conn.execute('INSERT INTO groups_tbl(workspace_id,handle,name,creator_id) VALUES(?,?,?,?)',(w['id'],h,n,u)).lastrowid
  for z in ids: db.conn.execute('INSERT INTO group_members VALUES(?,?)',(i,z))
  return web.json_response({'group':gj(db.conn.execute('SELECT * FROM groups_tbl WHERE id=?',(i,)).fetchone())},status=201)
 async def listing(q):
  u=require_user(q); from routes_workspaces import workspace_by_slug,role_of
  w=workspace_by_slug(q.match_info['slug'])
  if not role_of(w['id'],u): raise HTTPError(403,'forbidden')
  return web.json_response({'groups':[gj(r) for r in db.conn.execute('SELECT * FROM groups_tbl WHERE workspace_id=?',(w['id'],))]})
 async def patch(q):
  u=require_user(q); from routes_workspaces import workspace_by_slug,role_of
  w=workspace_by_slug(q.match_info['slug']); r=db.conn.execute('SELECT * FROM groups_tbl WHERE workspace_id=? AND handle=?',(w['id'],q.match_info['handle'])).fetchone()
  if not r: raise HTTPError(404,'group')
  if r['creator_id']!=u and w['owner_id']!=u: raise HTTPError(403,'forbidden')
  x=await read_json(q)
  if 'name' in x and (not isinstance(x['name'],str) or not x['name'].strip()): raise HTTPError(400,'invalid name')
  if 'user_ids' in x:
   if not isinstance(x['user_ids'],list) or any(not isinstance(i,int) or not db.conn.execute('SELECT 1 FROM workspace_members WHERE workspace_id=? AND user_id=?',(w['id'],i)).fetchone() for i in x['user_ids']): raise HTTPError(400,'invalid members')
   db.conn.execute('DELETE FROM group_members WHERE group_id=?',(r['id'],))
   for i in x['user_ids']: db.conn.execute('INSERT INTO group_members VALUES(?,?)',(r['id'],i))
  if 'name' in x: db.conn.execute('UPDATE groups_tbl SET name=? WHERE id=?',(x['name'],r['id']))
  return web.json_response({'group':gj(db.conn.execute('SELECT * FROM groups_tbl WHERE id=?',(r['id'],)).fetchone())})
 async def delete(q):
  u=require_user(q); from routes_workspaces import workspace_by_slug
  w=workspace_by_slug(q.match_info['slug']); r=db.conn.execute('SELECT * FROM groups_tbl WHERE workspace_id=? AND handle=?',(w['id'],q.match_info['handle'])).fetchone()
  if r:
   if r['creator_id']!=u and w['owner_id']!=u: raise HTTPError(403,'forbidden')
   db.conn.execute('DELETE FROM group_members WHERE group_id=?',(r['id'],)); db.conn.execute('DELETE FROM groups_tbl WHERE id=?',(r['id'],))
  return web.json_response({'deleted':True})
 app.router.add_post('/api/workspaces/{slug}/groups',create); app.router.add_get('/api/workspaces/{slug}/groups',listing); app.router.add_patch('/api/workspaces/{slug}/groups/{handle}',patch); app.router.add_delete('/api/workspaces/{slug}/groups/{handle}',delete)
_groups(None) if False else None
_old_extra=setup
def setup(app):
 _old_extra(app); _groups(app)
