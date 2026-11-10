import asyncio,sqlite3,secrets,hashlib,re,json,argparse,datetime
from aiohttp import web,WSMsgType
DB='/app/data/app.db'; con=None; sockets=set()
def now(): return datetime.datetime.now(datetime.timezone.utc).isoformat().replace('+00:00','Z')
def init():
 global con
 con=sqlite3.connect(DB,timeout=10,isolation_level=None,check_same_thread=False); con.row_factory=sqlite3.Row
 con.execute('PRAGMA journal_mode=WAL'); con.executescript('''CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,username TEXT UNIQUE,password TEXT,display_name TEXT,timezone TEXT DEFAULT "UTC",avatar_url TEXT DEFAULT "",status_text TEXT DEFAULT "",status_emoji TEXT DEFAULT "");
CREATE TABLE IF NOT EXISTS tokens(token TEXT PRIMARY KEY,user_id INTEGER); CREATE TABLE IF NOT EXISTS workspaces(id INTEGER PRIMARY KEY,slug TEXT UNIQUE,name TEXT,owner_id INTEGER,join_mode TEXT DEFAULT "open");
CREATE TABLE IF NOT EXISTS members(workspace_id INTEGER,user_id INTEGER,role TEXT,PRIMARY KEY(workspace_id,user_id)); CREATE TABLE IF NOT EXISTS channels(id INTEGER PRIMARY KEY,workspace_id INTEGER,name TEXT,is_private INTEGER DEFAULT 0,is_dm INTEGER DEFAULT 0,topic TEXT DEFAULT "",is_archived INTEGER DEFAULT 0,created_at TEXT);
CREATE TABLE IF NOT EXISTS cmembers(channel_id INTEGER,user_id INTEGER,PRIMARY KEY(channel_id,user_id)); CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY,channel_id INTEGER,author_id INTEGER,body TEXT,parent_id INTEGER,created_at TEXT,edited_at TEXT,deleted INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,channel_id INTEGER,event_id INTEGER,kind TEXT,data TEXT);''')
def user(r): return {k:r[k] for k in ['id','username','display_name','timezone','avatar_url','status_text','status_emoji']}
def chan(r): return {'id':r['id'],'workspace_id':r['workspace_id'],'name':r['name'],'is_private':bool(r['is_private']),'is_dm':bool(r['is_dm']),'topic':r['topic'],'is_archived':bool(r['is_archived']),'created_at':r['created_at']}
def msg(r):
 a=con.execute('select * from users where id=?',(r['author_id'],)).fetchone()
 return {'id':r['id'],'channel_id':r['channel_id'],'author_id':r['author_id'],'author':user(a),'body':r['body'],'parent_id':r['parent_id'],'reply_count':con.execute('select count(*) from messages where parent_id=? and deleted=0',(r['id'],)).fetchone()[0],'created_at':r['created_at'],'edited_at':r['edited_at'],'files':[],'reactions':[],'mentions':[]}
async def body(req):
 try:return await req.json()
 except:return {}
def auth(req):
 t=req.headers.get('Authorization','').replace('Bearer ',''); r=con.execute('select u.* from tokens t join users u on u.id=t.user_id where t.token=?',(t,)).fetchone()
 if not r: raise web.HTTPUnauthorized()
 return r
def out(x,status=200): return web.json_response(x,status=status)
async def health(req): return out({'status':'ok','node_id':req.app['node']})
async def register(req):
 b=await body(req)
 if not re.fullmatch(r'[A-Za-z0-9_]{1,32}',str(b.get('username',''))) or len(str(b.get('password','')))<8: raise web.HTTPBadRequest()
 try: con.execute('insert into users(username,password,display_name) values(?,?,?)',(b['username'],hashlib.sha256(b['password'].encode()).hexdigest(),b.get('display_name') or b['username']))
 except sqlite3.IntegrityError: raise web.HTTPConflict()
 r=con.execute('select * from users where username=?',(b['username'],)).fetchone(); t=secrets.token_urlsafe(24); con.execute('insert into tokens values(?,?)',(t,r['id'])); return out({'user':user(r),'token':t},201)
async def login(req):
 b=await body(req); r=con.execute('select * from users where username=? and password=?',(b.get('username'),hashlib.sha256(str(b.get('password','')).encode()).hexdigest())).fetchone()
 if not r: raise web.HTTPUnauthorized()
 t=secrets.token_urlsafe(24); con.execute('insert into tokens values(?,?)',(t,r['id'])); return out({'user':user(r),'token':t})
async def me(req): return out({'user':user(auth(req))})
async def workspaces(req):
 u=auth(req); rows=con.execute('select w.* from workspaces w join members m on m.workspace_id=w.id where m.user_id=?',(u['id'],)).fetchall()
 return out({'workspaces':[dict(r) for r in rows]})
async def create_ws(req):
 u=auth(req); b=await body(req)
 if not re.fullmatch(r'[a-z0-9-]{2,32}',str(b.get('slug',''))): raise web.HTTPBadRequest()
 try: con.execute('insert into workspaces(slug,name,owner_id) values(?,?,?)',(b['slug'],b.get('name',''),u['id']))
 except sqlite3.IntegrityError: raise web.HTTPConflict()
 w=con.execute('select * from workspaces where slug=?',(b['slug'],)).fetchone(); con.execute('insert into members values(?,?,?)',(w['id'],u['id'],'owner')); con.execute('insert into channels(workspace_id,name,created_at) values(?,?,?)',(w['id'],'general',now())); c=con.execute('select * from channels where workspace_id=?',(w['id'],)).fetchone(); con.execute('insert into cmembers values(?,?)',(c['id'],u['id']))
 return out({'workspace':dict(w),'general_channel':chan(c)},201)
async def workspace(req):
 u=auth(req); w=con.execute('select * from workspaces where slug=?',(req.match_info['slug'],)).fetchone()
 if not w: raise web.HTTPNotFound()
 cs=con.execute('select * from channels where workspace_id=? and is_dm=0',(w['id'],)).fetchall()
 return out({'workspace':dict(w),'channels':[chan(x) for x in cs],'read_state':[]})
async def create_channel(req):
 u=auth(req); w=con.execute('select * from workspaces where slug=?',(req.match_info['slug'],)).fetchone(); b=await body(req)
 if not w: raise web.HTTPNotFound()
 try: con.execute('insert into channels(workspace_id,name,is_private,topic,created_at) values(?,?,?,?,?)',(w['id'],b.get('name'),int(bool(b.get('is_private'))),b.get('topic',''),now()))
 except sqlite3.IntegrityError: raise web.HTTPConflict()
 c=con.execute('select * from channels where workspace_id=? order by id desc limit 1',(w['id'],)).fetchone(); con.execute('insert or ignore into cmembers values(?,?)',(c['id'],u['id'])); return out({'channel':chan(c)},201)
async def join(req):
 u=auth(req); c=con.execute('select * from channels where id=?',(req.match_info['id'],)).fetchone()
 if not c: raise web.HTTPNotFound()
 con.execute('insert or ignore into cmembers values(?,?)',(c['id'],u['id'])); con.execute('insert or ignore into members values(?,?,?)',(c['workspace_id'],u['id'],'member')); return out({'channel':chan(c)})
async def messages(req):
 u=auth(req); cid=int(req.match_info['id']); c=con.execute('select * from channels where id=?',(cid,)).fetchone()
 if not c: raise web.HTTPNotFound()
 if req.method=='GET':
  rs=con.execute('select * from messages where channel_id=? and parent_id is null and deleted=0 order by id desc limit 200',(cid,)).fetchall(); return out({'messages':[msg(r) for r in rs],'next_cursor':None})
 b=await body(req)
 if not str(b.get('body','')).strip(): raise web.HTTPBadRequest()
 con.execute('insert into messages(channel_id,author_id,body,parent_id,created_at) values(?,?,?,?,?)',(cid,u['id'],b['body'],b.get('parent_id'),now())); r=con.execute('select * from messages order by id desc limit 1').fetchone()
 n=(con.execute('select coalesce(max(event_id),0)+1 from events where channel_id=?',(cid,)).fetchone()[0]); con.execute('insert into events(channel_id,event_id,kind,data) values(?,?,?,?)',(cid,n,'message.created',json.dumps(msg(r)))); return out({'message':msg(r)},201)
async def ws(req):
 try:u=auth(req)
 except web.HTTPUnauthorized: raise
 w=web.WebSocketResponse(); await w.prepare(req); sockets.add(w)
 try:
  async for x in w:
   if x.type==WSMsgType.TEXT:
    b=json.loads(x.data)
    if b.get('type')=='subscribe': await w.send_json({'type':'subscribed','channel_id':b['channel_id'],'head_event_id':con.execute('select coalesce(max(event_id),0) from events where channel_id=?',(b['channel_id'],)).fetchone()[0]})
 finally:sockets.discard(w)
 return w
def make(node):
 a=web.Application(client_max_size=20*1024*1024); a['node']=node
 a.router.add_get('/api/health',health); a.router.add_post('/api/auth/register',register); a.router.add_post('/api/auth/login',login); a.router.add_get('/api/auth/me',me)
 a.router.add_get('/api/workspaces',workspaces); a.router.add_post('/api/workspaces',create_ws); a.router.add_get('/api/workspaces/{slug}',workspace); a.router.add_post('/api/workspaces/{slug}/channels',create_channel)
 a.router.add_post('/api/channels/{id}/join',join); a.router.add_route('*','/api/channels/{id}/messages',messages); a.router.add_get('/api/ws',ws); return a
if __name__=='__main__':
 p=argparse.ArgumentParser(); p.add_argument('--port',type=int); p.add_argument('--node-id',type=int); x=p.parse_args(); init(); web.run_app(make(x.node_id),host='0.0.0.0',port=x.port)
