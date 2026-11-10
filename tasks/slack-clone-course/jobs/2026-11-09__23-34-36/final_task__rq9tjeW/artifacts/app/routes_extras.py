import json,os,re,secrets
from zoneinfo import ZoneInfo
from aiohttp import web
from db import connect,now_iso
from common import *
def groupj(r): return {'id':r['id'],'handle':r['handle'],'name':r['name'],'member_user_ids':json.loads(r['user_ids'] or '[]')}
async def dms(req):
 u=require_user(req); d=await read_json(req)
 if 'user_id' not in d:
  raise HTTPError(400,'invalid user')
 try: other=int(d['user_id'])
 except: raise HTTPError(400,'invalid user')
 if not user_by_id(other) or other==u['id']: raise HTTPError(404,'user not found')
 c=connect(); a,b=sorted((u['id'],other))
 pair=c.execute('SELECT channel_id FROM dm_pairs WHERE user_low=? AND user_high=?',(a,b)).fetchone()
 if pair: return web.json_response({'channel_id':pair[0]})
 c.execute('INSERT INTO channels(workspace_id,name,is_private,is_dm,created_at) VALUES(NULL,?,?,1,?)',(f'dm-{a}-{b}',1,now_iso()))
 cid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
 c.execute('INSERT INTO dm_pairs(user_low,user_high,channel_id) VALUES(?,?,?)',(a,b,cid))
 add_channel_member(cid,a); add_channel_member(cid,b)
 return web.json_response({'channel_id':cid})

async def upload(req):
 u=require_user(req)
 try: rd=await req.multipart()
 except Exception: raise HTTPError(400,'multipart required')
 part=None
 async for x in rd:
  if x.name=='file': part=x; break
 if not part: raise HTTPError(400,'file required')
 data=await part.read()
 if len(data)>10*1024*1024: raise web.HTTPRequestEntityTooLarge(max_size=10*1024*1024,actual_size=len(data))
 c=connect(); c.execute('INSERT INTO files(uploader_id,filename,content_type,size,data,created_at) VALUES(?,?,?,?,?,?)',(u['id'],part.filename or 'file',part.headers.get('Content-Type','application/octet-stream'),len(data),data,now_iso()))
 r=c.execute('SELECT * FROM files WHERE id=last_insert_rowid()').fetchone()
 return web.json_response({'file':{k:r[k] for k in ('id','uploader_id','filename','content_type','size','created_at')}},status=201)
def fj(r): return {k:r[k] for k in ('id','uploader_id','filename','content_type','size','created_at')}
async def getfile(req):
 require_user(req); r=connect().execute('SELECT * FROM files WHERE id=?',(req.match_info['id'],)).fetchone()
 if not r: raise HTTPError(404,'file not found')
 return web.json_response({'file':fj(r)})
async def download(req):
 require_user(req); r=connect().execute('SELECT * FROM files WHERE id=?',(req.match_info['id'],)).fetchone()
 if not r: raise HTTPError(404,'file not found')
 return web.Response(body=r['data'],content_type=r['content_type'],headers={'Content-Disposition':f'attachment; filename="{r["filename"]}"'})
async def profile(req):
 u=require_user(req); r=user_by_id(req.match_info['id'])
 if not r: raise HTTPError(404,'user not found')
 return web.json_response({'user':user_to_json(r)})
async def patchprofile(req):
 u=require_user(req); d=await read_json(req); allowed=['display_name','timezone','avatar_url','status_text','status_emoji']
 if 'timezone' in d:
  try: ZoneInfo(d['timezone'])
  except Exception: raise HTTPError(400,'invalid timezone')
 limits={'display_name':80,'status_text':100,'status_emoji':64,'avatar_url':1024,'timezone':100}
 if any(k in d and (not isinstance(d[k],str) or len(d[k])>limits[k] or (k=='display_name' and not d[k].strip())) for k in allowed): raise HTTPError(400,'invalid profile')
 c=connect(); vals=[d[k] for k in allowed if k in d]
 if vals:c.execute('UPDATE users SET '+','.join(k+'=?' for k in allowed if k in d)+' WHERE id=?',vals+[u['id']])
 out=user_to_json(user_by_id(u['id'])); broadcast_global({'type':'user.updated','user':out}); return web.json_response({'user':out})
async def groups(req):
 u=require_user(req); w=workspace_by_slug(req.match_info['slug'])
 if not role_of(w['id'],u['id']): raise HTTPError(403,'forbidden')
 c=connect(); rows=c.execute('SELECT * FROM groups_tbl WHERE workspace_id=?',(w['id'],)).fetchall()
 if req.method=='GET': return web.json_response({'groups':[groupj(x) for x in rows]})
 d=await read_json(req); h=d.get('handle'); ids=d.get('user_ids',[])
 if not isinstance(h,str) or h in ('channel','here') or not re.fullmatch(r'[a-z0-9](?:[a-z0-9_-]{0,30}[a-z0-9])?',h) or not isinstance(d.get('name'),str) or not d['name'].strip() or not isinstance(ids,list): raise HTTPError(400,'invalid group')
 if any(not isinstance(x,int) or not c.execute('SELECT 1 FROM workspace_members WHERE workspace_id=? AND user_id=?',(w['id'],x)).fetchone() for x in ids): raise HTTPError(400,'invalid members')
 if c.execute('SELECT 1 FROM groups_tbl WHERE workspace_id=? AND handle=?',(w['id'],h)).fetchone(): raise HTTPError(409,'group exists')
 c.execute('INSERT INTO groups_tbl(workspace_id,handle,name,creator_id,user_ids) VALUES(?,?,?,?,?)',(w['id'],h,d['name'],u['id'],json.dumps(ids)))
 return web.json_response({'group':groupj(c.execute('SELECT * FROM groups_tbl WHERE id=last_insert_rowid()').fetchone())},status=201)
async def groupedit(req):
 u=require_user(req); w=workspace_by_slug(req.match_info['slug']); c=connect(); r=c.execute('SELECT * FROM groups_tbl WHERE workspace_id=? AND handle=?',(w['id'],req.match_info['handle'])).fetchone()
 if not r:
  if req.method=='DELETE': return web.json_response({'deleted':True})
  raise HTTPError(404,'group not found')
 if r['creator_id']!=u['id'] and w['owner_id']!=u['id']: raise HTTPError(403,'forbidden')
 if req.method=='DELETE': c.execute('DELETE FROM groups_tbl WHERE id=?',(r['id'],)); return web.json_response({'deleted':True})
 d=await read_json(req); c.execute('UPDATE groups_tbl SET name=?,user_ids=? WHERE id=?',(d.get('name',r['name']),json.dumps(d.get('user_ids',json.loads(r['user_ids']))),r['id']))
 return web.json_response({'group':groupj(c.execute('SELECT * FROM groups_tbl WHERE id=?',(r['id'],)).fetchone())})
def setup(app):
 app.router.add_post('/api/dms',dms); app.router.add_post('/api/files',upload); app.router.add_get('/api/files/{id}',getfile); app.router.add_get('/api/files/{id}/download',download)
 app.router.add_get('/api/users/{id}',profile); app.router.add_patch('/api/users/me',patchprofile)
 app.router.add_get('/api/workspaces/{slug}/groups',groups); app.router.add_post('/api/workspaces/{slug}/groups',groups)
 app.router.add_patch('/api/workspaces/{slug}/groups/{handle}',groupedit); app.router.add_delete('/api/workspaces/{slug}/groups/{handle}',groupedit)
