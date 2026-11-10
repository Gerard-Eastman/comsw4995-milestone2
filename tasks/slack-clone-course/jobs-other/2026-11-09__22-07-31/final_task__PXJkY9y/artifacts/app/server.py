import asyncio,os,sys,json,secrets,base64,datetime,re,sqlite3
from aiohttp import web,WSMsgType
sys.path.insert(0,'/app'); from db import connect,init_db
C=connect(); NODE=int(sys.argv[sys.argv.index('--node-id')+1]) if '--node-id' in sys.argv else 0; sockets=set(); subs={}
def now(): return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z')
def uj(r): return {k:r[k] for k in ('id','username','display_name','timezone','avatar_url','status_text','status_emoji')}
def err(s,x): raise web.HTTPException(reason=x)
class Locked(Exception): pass
@web.middleware
async def mw(req,handler):
 try:return await handler(req)
 except web.HTTPException as e:return web.json_response({'error':e.reason},status=e.status)
 except Locked:return web.json_response({'error':'archived'},status=423)
 except Exception as e:return web.json_response({'error':str(e)},status=500)
async def body(r):
 try:x=await r.json(); return x if isinstance(x,dict) else {}
 except:return {}
def user(r):
 a=r.headers.get('Authorization',''); t=a[7:] if a.startswith('Bearer ') else ''
 x=C.execute('select u.* from tokens t join users u on u.id=t.user_id where t.token=?',(t,)).fetchone()
 if not x: raise web.HTTPUnauthorized(reason='authentication required')
 return x
def chan(i):
 try:x=C.execute('select * from channels where id=?',(int(i),)).fetchone()
 except:x=None
 if not x: raise web.HTTPNotFound(reason='channel not found')
 return x
def co(x): return {'id':x['id'],'workspace_id':x['workspace_id'],'name':x['name'],'is_private':bool(x['is_private']),'is_dm':bool(x['is_dm']),'topic':x['topic'] or '','is_archived':bool(x['is_archived']),'created_at':x['created_at']}
def emit(cid,kind,data):
 C.execute('begin immediate'); n=C.execute('select last_event_id+1 from channels where id=?',(cid,)).fetchone()[0]; C.execute('update channels set last_event_id=? where id=?',(n,cid)); p={'type':kind,'event_id':n,'channel_id':cid,**data}; C.execute('insert into events(channel_id,event_id,payload) values(?,?,?)',(cid,n,json.dumps(p))); C.commit(); return p
async def health(r): return web.json_response({'status':'ok','node_id':NODE})
async def register(r):
 b=await body(r); u=b.get('username',''); p=b.get('password','')
 if not re.fullmatch(r'[A-Za-z0-9_]{1,32}',u) or len(p)<8: raise web.HTTPBadRequest(reason='invalid registration')
 if C.execute('select 1 from users where username=?',(u,)).fetchone(): raise web.HTTPConflict(reason='duplicate username')
 C.execute('insert into users(username,password,display_name) values(?,?,?)',(u,p,b.get('display_name') or u)); x=C.execute('select * from users where username=?',(u,)).fetchone(); t=secrets.token_urlsafe(24); C.execute('insert into tokens values(?,?)',(t,x['id'],)); return web.json_response({'user':uj(x),'token':t},status=201)
async def login(r):
 b=await body(r); x=C.execute('select * from users where username=? and password=?',(b.get('username'),b.get('password'))).fetchone()
 if not x: raise web.HTTPUnauthorized(reason='wrong credentials')
 t=secrets.token_urlsafe(24); C.execute('insert into tokens values(?,?)',(t,x['id'])); return web.json_response({'user':uj(x),'token':t})
async def me(r): return web.json_response({'user':uj(user(r))})
async def wss(r):
 u=user(r); b=await body(r); slug=b.get('slug',''); name=b.get('name','')
 if not re.fullmatch(r'[a-z0-9-]{2,32}',slug) or not name: raise web.HTTPBadRequest(reason='invalid workspace')
 if C.execute('select 1 from workspaces where slug=?',(slug,)).fetchone(): raise web.HTTPConflict(reason='duplicate')
 C.execute('insert into workspaces(slug,name,owner_id) values(?,?,?)',(slug,name,u['id'])); w=C.execute('select * from workspaces where slug=?',(slug,)).fetchone(); C.execute('insert into members values(?,?,?)',(w['id'],u['id'],'owner')); C.execute('insert into channels(workspace_id,name,created_at) values(?,?,?)',(w['id'],'general',now())); ch=C.execute('select * from channels where workspace_id=?',(w['id'],)).fetchone(); C.execute('insert into channel_members values(?,?)',(ch['id'],u['id'])); return web.json_response({'workspace':dict(w),'general_channel':co(ch)},status=201)
async def wlist(r):
 u=user(r); rows=C.execute('select w.* from workspaces w join members m on m.workspace_id=w.id where m.user_id=?',(u['id'],)).fetchall(); return web.json_response({'workspaces':[dict(x) for x in rows]})
async def wdetail(r):
 u=user(r); w=C.execute('select * from workspaces where slug=?',(r.match_info['slug'],)).fetchone()
 if not w: raise web.HTTPNotFound(reason='workspace')
 rows=C.execute('select c.* from channels c join channel_members m on m.channel_id=c.id where c.workspace_id=? and m.user_id=? and c.is_dm=0',(w['id'],u['id'])).fetchall(); return web.json_response({'workspace':dict(w),'channels':[co(x) for x in rows],'read_state':{}})
async def channels(r):
 u=user(r); w=C.execute('select * from workspaces where slug=?',(r.match_info['slug'],)).fetchone()
 if not w: raise web.HTTPNotFound(reason='workspace')
 b=await body(r); n=b.get('name','')
 if not re.fullmatch(r'[a-z0-9-]{1,32}',n): raise web.HTTPBadRequest(reason='invalid channel')
 if C.execute('select 1 from channels where workspace_id=? and name=?',(w['id'],n)).fetchone(): raise web.HTTPConflict(reason='duplicate channel')
 C.execute('insert into channels(workspace_id,name,is_private,topic,created_at) values(?,?,?,?,?)',(w['id'],n,int(bool(b.get('is_private'))),b.get('topic',''),now())); x=C.execute('select * from channels where id=last_insert_rowid()').fetchone(); C.execute('insert into channel_members values(?,?)',(x['id'],u['id'])); return web.json_response({'channel':co(x)},status=201)
async def join(r):
 u=user(r); x=chan(r.match_info['id']); C.execute('insert or ignore into channel_members values(?,?)',(x['id'],u['id'])); return web.json_response({'channel':co(x)})
def msgj(x):
 a=C.execute('select * from users where id=?',(x['author_id'],)).fetchone(); rs=C.execute('select emoji,count(*) n from reactions where message_id=? group by emoji',(x['id'],)).fetchall()
 return {'id':x['id'],'channel_id':x['channel_id'],'author_id':x['author_id'],'author':uj(a),'body':x['body'],'parent_id':x['parent_id'],'reply_count':C.execute('select count(*) from messages where parent_id=? and deleted=0',(x['id'],)).fetchone()[0],'created_at':x['created_at'],'edited_at':x['edited_at'],'files':[],'reactions':[{'emoji':z['emoji'],'count':z['n'],'user_ids':[]} for z in rs],'mentions':[]}
async def archive(r):
 u=user(r); x=chan(r.match_info['id'])
 owner=C.execute('select owner_id from workspaces where id=?',(x['workspace_id'],)).fetchone()
 if not owner or owner['owner_id']!=u['id']: raise web.HTTPForbidden(reason='forbidden')
 C.execute('update channels set is_archived=1 where id=?',(x['id'],))
 return web.json_response({'channel':co(C.execute('select * from channels where id=?',(x['id'],)).fetchone())})
async def postmsg(r):
 u=user(r); x=chan(r.match_info['id']); b=await body(r); text=b.get('body','')
 if not text: raise web.HTTPBadRequest(reason='empty message')
 C.execute('insert into messages(channel_id,author_id,body,parent_id,created_at) values(?,?,?,?,?)',(x['id'],u['id'],text,b.get('parent_id'),now())); m=C.execute('select * from messages where id=last_insert_rowid()').fetchone(); p=emit(x['id'],'message.reply' if m['parent_id'] else 'message.created',{'message':msgj(m)}); return web.json_response({'message':msgj(m)},status=201)
async def listmsg(r):
 user(r); x=chan(r.match_info['id']); rows=C.execute('select * from messages where channel_id=? and deleted=0 order by id desc',(x['id'],)).fetchall(); return web.json_response({'messages':[msgj(z) for z in rows],'next_cursor':None})
async def edit(r):
 u=user(r); i=int(r.match_info['id']); x=C.execute('select * from messages where id=?',(i,)).fetchone()
 if not x: raise web.HTTPNotFound(reason='message')
 if x['author_id']!=u['id']: raise web.HTTPForbidden(reason='forbidden')
 if x['deleted']: raise web.HTTPConflict(reason='deleted message')
 if C.execute('select is_archived from channels where id=?',(x['channel_id'],)).fetchone()['is_archived']: raise Locked()
 b=await body(r)
 if not isinstance(b.get('body'),str) or not b.get('body').strip(): raise web.HTTPBadRequest(reason='empty message')
 C.execute('update messages set body=?,edited_at=? where id=?',(b.get('body',''),now(),i)); x=C.execute('select * from messages where id=?',(i,)).fetchone(); emit(x['channel_id'],'message.updated',{'message':msgj(x)}); return web.json_response({'message':msgj(x)})
async def delete(r):
 u=user(r); i=int(r.match_info['id']); x=C.execute('select * from messages where id=?',(i,)).fetchone()
 if not x: raise web.HTTPNotFound(reason='message')
 owner=C.execute('select owner_id from workspaces w join channels c on c.workspace_id=w.id where c.id=?',(x['channel_id'],)).fetchone()
 if x['author_id']!=u['id'] and (not owner or owner['owner_id']!=u['id']): raise web.HTTPForbidden(reason='forbidden')
 if not x['deleted']: C.execute('update messages set deleted=1 where id=?',(i,)); emit(x['channel_id'],'message.deleted',{'message_id':i})
 return web.json_response({'deleted':True})
async def react(r):
 u=user(r); i=int(r.match_info['id']); x=C.execute('select * from messages where id=? and deleted=0',(i,)).fetchone()
 if not x: raise web.HTTPNotFound(reason='message')
 b=await body(r); C.execute('insert or ignore into reactions values(?,?,?)',(i,u['id'],b.get('emoji',''))); return web.json_response({'reactions':[]})
async def ws(r):
 t=r.query.get('token',''); x=C.execute('select user_id from tokens where token=?',(t,)).fetchone()
 if not x: raise web.HTTPUnauthorized()
 q=web.WebSocketResponse(); await q.prepare(r); sockets.add(q)
 try:
  async for m in q:
   if m.type==WSMsgType.TEXT:
    d=json.loads(m.data)
    if d.get('type')=='subscribe':
     cid=int(d.get('channel_id')); head=C.execute('select last_event_id from channels where id=?',(cid,)).fetchone()[0]; subs[q]=(cid,head); await q.send_json({'type':'subscribed','channel_id':cid,'head_event_id':head})
 finally:
  sockets.discard(q); subs.pop(q,None)
 return q
async def pump():
 last=0
 while True:
  for z in C.execute('select seq,payload from events where seq>? order by seq',(last,)).fetchall():
   last=z['seq']
   for s in list(sockets):
    try:
     d=json.loads(z['payload']); sub=subs.get(s)
     if sub and sub[0]==d.get('channel_id') and d.get('event_id',0)>sub[1]: await s.send_str(z['payload']); subs[s]=(sub[0],d['event_id'])
    except: sockets.discard(s); subs.pop(s,None)
  await asyncio.sleep(.05)
async def root(r): return web.FileResponse('/app/static/index.html')
app=web.Application(middlewares=[mw],client_max_size=20*1024*1024); app.router.add_get('/api/health',health); app.router.add_post('/api/auth/register',register); app.router.add_post('/api/auth/login',login); app.router.add_get('/api/auth/me',me); app.router.add_post('/api/workspaces',wss); app.router.add_get('/api/workspaces',wlist); app.router.add_get('/api/workspaces/{slug}',wdetail); app.router.add_post('/api/workspaces/{slug}/channels',channels); app.router.add_post('/api/channels/{id}/join',join); app.router.add_post('/api/channels/{id}/archive',archive); app.router.add_post('/api/channels/{id}/messages',postmsg); app.router.add_get('/api/channels/{id}/messages',listmsg); app.router.add_patch('/api/messages/{id}',edit); app.router.add_delete('/api/messages/{id}',delete); app.router.add_post('/api/messages/{id}/reactions',react); app.router.add_get('/api/ws',ws); app.router.add_get('/',root); app.router.add_static('/static/','/app/static')
init_db();
async def startup(a): asyncio.create_task(pump())
app.on_startup.append(startup); web.run_app(app,host='0.0.0.0',port=int(sys.argv[sys.argv.index('--port')+1]))
