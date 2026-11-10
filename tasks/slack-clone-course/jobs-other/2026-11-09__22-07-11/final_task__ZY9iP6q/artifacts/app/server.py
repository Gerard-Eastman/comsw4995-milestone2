import asyncio,json,os,re,secrets,sys
from aiohttp import web,WSMsgType
from db import *
C=init_db(); NODE=int(sys.argv[sys.argv.index('--node-id')+1]) if '--node-id' in sys.argv else 0
subs={}
def js(r): return web.json_response(r)
def uid(req):
 t=req.headers.get('Authorization','').replace('Bearer ','') or req.query.get('token','').replace('Bearer ',''); x=C.execute('select user_id from tokens where token=?',(t,)).fetchone()
 if not x: raise web.HTTPUnauthorized()
 return x['user_id']
def user(i):
 x=C.execute('select * from users where id=?',(i,)).fetchone(); return dict(x) if x else None
def msg(x):
 d=dict(x); d['author']=user(d['author_id']); d['parent_id']=d['parent_id']; d['files']=[]; d['reactions']=[]
 for z in C.execute('select emoji,count(*) n from reactions where message_id=? group by emoji',(d['id'],)): d['reactions'].append({'emoji':z['emoji'],'count':z['n']})
 d['reply_count']=C.execute('select count(*) n from messages where parent_id=? and deleted=0',(d['id'],)).fetchone()['n']; return d
def emit(cid,kind,data):
 C.execute('update channels set last_event_id=last_event_id+1 where id=?',(cid,)); n=C.execute('select last_event_id from channels where id=?',(cid,)).fetchone()[0]; p={'type':kind,'event_id':n,'channel_id':cid,**data}; C.execute('insert into events(channel_id,event_id,payload) values(?,?,?)',(cid,n,json.dumps(p))); return p
async def health(r): return js({'status':'ok','node_id':NODE})
async def register(r):
 b=await r.json(); u=b.get('username',''); pw=b.get('password','')
 if not re.fullmatch(r'[A-Za-z0-9_]+',u) or len(pw)<8: raise web.HTTPBadRequest()
 try: C.execute('insert into users(username,password,display_name,created_at) values(?,?,?,?)',(u,pw,b.get('display_name',u),now_iso()))
 except: raise web.HTTPConflict()
 i=C.execute('select last_insert_rowid()').fetchone()[0]; t=secrets.token_urlsafe(24); C.execute('insert into tokens values(?,?)',(t,i)); return web.json_response({'user':user(i),'token':t},status=201)
async def login(r):
 b=await r.json(); x=C.execute('select * from users where username=? and password=?',(b.get('username'),b.get('password'))).fetchone()
 if not x: raise web.HTTPUnauthorized()
 t=secrets.token_urlsafe(24); C.execute('insert into tokens values(?,?)',(t,x['id'])); return js({'user':dict(x),'token':t})
async def me(r): return js({'user':user(uid(r))})
async def workspaces(r):
 u=uid(r); return js({'workspaces':[dict(x) for x in C.execute('select w.* from workspaces w join members m on m.workspace_id=w.id where m.user_id=?',(u,))]})
async def wscreate(r):
 u=uid(r); b=await r.json(); slug=b.get('slug','')
 if not re.fullmatch(r'[a-z0-9-]{2,32}',slug): raise web.HTTPBadRequest()
 try:C.execute('insert into workspaces(slug,name,owner_id) values(?,?,?)',(slug,b.get('name',slug),u))
 except: raise web.HTTPConflict()
 wid=C.execute('select last_insert_rowid()').fetchone()[0]; C.execute('insert into members values(?,?,?)',(wid,u,'owner')); C.execute('insert into channels(workspace_id,name) values(?,?)',(wid,'general')); cid=C.execute('select last_insert_rowid()').fetchone()[0]; C.execute('insert into cmembers values(?,?)',(cid,u)); return web.json_response({'workspace':dict(C.execute('select * from workspaces where id=?',(wid,)).fetchone()),'general_channel':dict(C.execute('select * from channels where id=?',(cid,)).fetchone())},status=201)
async def wsdetail(r):
 u=uid(r); w=C.execute('select * from workspaces where slug=?',(r.match_info['slug'],)).fetchone()
 if not w: raise web.HTTPNotFound()
 return js({'workspace':dict(w),'channels':[dict(x) for x in C.execute('select * from channels where workspace_id=?',(w['id'],))]})
async def chcreate(r):
 u=uid(r); w=C.execute('select * from workspaces where slug=?',(r.match_info['slug'],)).fetchone(); b=await r.json()
 try:C.execute('insert into channels(workspace_id,name,topic,is_private) values(?,?,?,?)',(w['id'],b['name'],b.get('topic',''),int(b.get('is_private',False))))
 except: raise web.HTTPConflict()
 cid=C.execute('select last_insert_rowid()').fetchone()[0]; C.execute('insert into cmembers values(?,?)',(cid,u)); return web.json_response({'channel':dict(C.execute('select * from channels where id=?',(cid,)).fetchone())},status=201)
async def join(r):
 u=uid(r); cid=int(r.match_info['id']); x=C.execute('select * from channels where id=?',(cid,)).fetchone()
 if not x: raise web.HTTPNotFound()
 C.execute('insert or ignore into cmembers values(?,?)',(cid,u)); return js({'channel':dict(x)})
async def messages(r):
 u=uid(r); cid=int(r.match_info['id']); return js({'messages':[msg(x) for x in C.execute('select * from messages where channel_id=? and deleted=0 order by id desc',(cid,))],'next_cursor':None})
async def post(r):
 u=uid(r); cid=int(r.match_info['id']); b=await r.json(); body=b.get('body','')
 if not isinstance(body,str) or not body.strip(): raise web.HTTPBadRequest()
 C.execute('insert into messages(channel_id,author_id,body,parent_id,created_at) values(?,?,?,?,?)',(cid,u,body,b.get('parent_id'),now_iso())); i=C.execute('select last_insert_rowid()').fetchone()[0]; d=msg(C.execute('select * from messages where id=?',(i,)).fetchone()); p=emit(cid,'message.reply' if b.get('parent_id') else 'message.created',{'message':d}); return web.json_response({'message':d},status=201)
async def edit(r):
 u=uid(r); i=int(r.match_info['id']); x=C.execute('select * from messages where id=?',(i,)).fetchone()
 if not x: raise web.HTTPNotFound()
 owner=C.execute('select owner_id from workspaces w join channels c on c.workspace_id=w.id where c.id=?',(x['channel_id'],)).fetchone()
 if x['author_id']!=u: raise web.HTTPForbidden()
 if x['deleted']: raise web.HTTPConflict()
 if C.execute('select archived from channels where id=?',(x['channel_id'],)).fetchone()['archived']: return web.Response(status=423,text='423: Locked')
 try: b=await r.json()
 except Exception: b={}
 body=b.get('body') if isinstance(b,dict) else None
 if not isinstance(body,str) or not body.strip(): raise web.HTTPBadRequest()
 C.execute('update messages set body=?,edited_at=? where id=?',(body,now_iso(),i)); d=msg(C.execute('select * from messages where id=?',(i,)).fetchone()); emit(x['channel_id'],'message.updated',{'message':d}); return js({'message':d})
async def delete(r):
 u=uid(r); i=int(r.match_info['id']); x=C.execute('select * from messages where id=?',(i,)).fetchone()
 if not x: raise web.HTTPNotFound()
 owner=C.execute('select owner_id from workspaces w join channels c on c.workspace_id=w.id where c.id=?',(x['channel_id'],)).fetchone()
 if x['author_id']!=u and (not owner or owner['owner_id']!=u): raise web.HTTPForbidden()
 if not x['deleted']: C.execute('update messages set deleted=1 where id=?',(i,)); emit(x['channel_id'],'message.deleted',{'message_id':i})
 return js({'deleted':True})

async def archive(r):
 u=uid(r); x=C.execute('select c.*,w.owner_id from channels c join workspaces w on w.id=c.workspace_id where c.id=?',(int(r.match_info['id']),)).fetchone()
 if not x: raise web.HTTPNotFound()
 if x['owner_id']!=u: raise web.HTTPForbidden()
 C.execute('update channels set archived=1 where id=?',(x['id'],)); return js({'channel':dict(C.execute('select * from channels where id=?',(x['id'],)).fetchone())})
async def unarchive(r):
 u=uid(r); x=C.execute('select c.*,w.owner_id from channels c join workspaces w on w.id=c.workspace_id where c.id=?',(int(r.match_info['id']),)).fetchone()
 if not x: raise web.HTTPNotFound()
 if x['owner_id']!=u: raise web.HTTPForbidden()
 C.execute('update channels set archived=0 where id=?',(x['id'],)); return js({'channel':dict(C.execute('select * from channels where id=?',(x['id'],)).fetchone())})
async def wsock(r):
 uid(r); w=web.WebSocketResponse(); await w.prepare(r); subs[w]=set()
 try:
  async for m in w:
   if m.type==WSMsgType.TEXT:
    b=json.loads(m.data)
    if b.get('type')=='subscribe':
     cid=b['channel_id']; subs[w].add(cid); h=C.execute('select last_event_id from channels where id=?',(cid,)).fetchone(); await w.send_json({'type':'subscribed','channel_id':cid,'head_event_id':h[0] if h else 0})
 finally: subs.pop(w,None)
 return w
async def pump():
 last=0
 while True:
  await asyncio.sleep(.05)
  rows=C.execute('select seq,payload from events where seq>? order by seq',(last,)).fetchall()
  for x in rows:
   last=x['seq']; p=json.loads(x['payload'])
   for w in list(subs):
    if p.get('channel_id') not in subs.get(w,set()): continue
    try: await w.send_json(p)
    except: subs.pop(w,None)
async def startup(app):
 app['pump']=asyncio.create_task(pump())
async def cleanup(app):
 app['pump'].cancel()
async def root(r): return web.Response(text=open('/app/static/index.html').read(),content_type='text/html')
app=web.Application(client_max_size=20*1024*1024); app.on_startup.append(startup); app.on_cleanup.append(cleanup); app.router.add_get('/api/health',health); app.router.add_post('/api/auth/register',register); app.router.add_post('/api/auth/login',login); app.router.add_get('/api/auth/me',me); app.router.add_get('/api/workspaces',workspaces); app.router.add_post('/api/workspaces',wscreate); app.router.add_get('/api/workspaces/{slug}',wsdetail); app.router.add_post('/api/workspaces/{slug}/channels',chcreate); app.router.add_post('/api/channels/{id}/join',join); app.router.add_post('/api/channels/{id}/archive',archive); app.router.add_post('/api/channels/{id}/unarchive',unarchive); app.router.add_get('/api/channels/{id}/messages',messages); app.router.add_post('/api/channels/{id}/messages',post); app.router.add_patch('/api/messages/{id}',edit); app.router.add_delete('/api/messages/{id}',delete); app.router.add_get('/api/ws',wsock); app.router.add_get('/',root); app.router.add_static('/static','/app/static')
web.run_app(app,host='0.0.0.0',port=int(sys.argv[sys.argv.index('--port')+1]))
