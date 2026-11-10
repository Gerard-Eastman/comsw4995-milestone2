import asyncio,base64,datetime,json,os,re,secrets,sqlite3,argparse
from aiohttp import web,WSMsgType
DB='/app/data/app.db'; con=None; sockets=[]
def now(): return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z')
def init_db():
 global con
 os.makedirs('/app/data',exist_ok=True); con=sqlite3.connect(DB,timeout=10,isolation_level=None,check_same_thread=False); con.row_factory=sqlite3.Row
 con.execute('PRAGMA journal_mode=WAL'); con.execute('PRAGMA busy_timeout=10000')
 con.executescript('''CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,username TEXT UNIQUE,password TEXT,display_name TEXT,timezone TEXT DEFAULT "UTC",avatar_url TEXT DEFAULT "",status_text TEXT DEFAULT "",status_emoji TEXT DEFAULT "");
CREATE TABLE IF NOT EXISTS tokens(token TEXT PRIMARY KEY,user_id INTEGER);
CREATE TABLE IF NOT EXISTS workspaces(id INTEGER PRIMARY KEY,slug TEXT UNIQUE,name TEXT,owner_id INTEGER,join_mode TEXT DEFAULT "open");
CREATE TABLE IF NOT EXISTS members(workspace_id INTEGER,user_id INTEGER,role TEXT,PRIMARY KEY(workspace_id,user_id));
CREATE TABLE IF NOT EXISTS channels(id INTEGER PRIMARY KEY,workspace_id INTEGER,name TEXT,is_private INTEGER DEFAULT 0,is_dm INTEGER DEFAULT 0,topic TEXT DEFAULT "",is_archived INTEGER DEFAULT 0,last_event_id INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS cmembers(channel_id INTEGER,user_id INTEGER,PRIMARY KEY(channel_id,user_id));
CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY,channel_id INTEGER,author_id INTEGER,body TEXT,parent_id INTEGER,created_at TEXT,edited_at TEXT,deleted INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS reactions(message_id INTEGER,user_id INTEGER,emoji TEXT,PRIMARY KEY(message_id,user_id,emoji));
CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT,channel_id INTEGER,event_id INTEGER,payload TEXT);
CREATE TABLE IF NOT EXISTS broadcasts(seq INTEGER PRIMARY KEY AUTOINCREMENT,payload TEXT);''')
def user(r):
 return {'id':r['id'],'username':r['username'],'display_name':r['display_name'],'timezone':r['timezone'],'avatar_url':r['avatar_url'],'status_text':r['status_text'],'status_emoji':r['status_emoji']}
def chan(r): return {'id':r['id'],'workspace_id':r['workspace_id'],'name':r['name'],'is_private':bool(r['is_private']),'is_dm':bool(r['is_dm']),'topic':r['topic'] or '','is_archived':bool(r['is_archived']),'created_at':now()}
def auth(req):
 t=req.headers.get('Authorization','')
 if not t.startswith('Bearer '): raise web.HTTPUnauthorized()
 r=con.execute('SELECT u.* FROM tokens t JOIN users u ON u.id=t.user_id WHERE t.token=?',(t[7:],)).fetchone()
 if not r: raise web.HTTPUnauthorized()
 return r
async def body(req):
 try:
  x=await req.json(); return x if isinstance(x,dict) else {}
 except: return {}
def err(s,m): return web.json_response({'error':m},status=s)
def msg(r):
 a=con.execute('SELECT * FROM users WHERE id=?',(r['author_id'],)).fetchone()
 reacts=[]
 for x in con.execute('SELECT emoji,COUNT(*) n,GROUP_CONCAT(user_id) ids FROM reactions WHERE message_id=? GROUP BY emoji',(r['id'],)):
  reacts.append({'emoji':x['emoji'],'count':x['n'],'user_ids':[int(i) for i in x['ids'].split(',')]})
 n=[int(x['id']) for x in con.execute('SELECT id FROM users WHERE username IN (?)',('',))] if False else []
 return {'id':r['id'],'channel_id':r['channel_id'],'author_id':r['author_id'],'author':user(a),'body':r['body'],'parent_id':r['parent_id'],'reply_count':con.execute('SELECT COUNT(*) FROM messages WHERE parent_id=? AND deleted=0',(r['id'],)).fetchone()[0],'created_at':r['created_at'],'edited_at':r['edited_at'],'files':[],'reactions':reacts,'mentions':n}
def emit(cid,kind,data):
 con.execute('BEGIN IMMEDIATE'); h=con.execute('SELECT last_event_id FROM channels WHERE id=?',(cid,)).fetchone()[0]+1; con.execute('UPDATE channels SET last_event_id=? WHERE id=?',(h,cid)); p={'type':kind,'event_id':h,'channel_id':cid,**data}; con.execute('INSERT INTO events(channel_id,event_id,payload) VALUES(?,?,?)',(cid,h,json.dumps(p))); con.execute('COMMIT'); return p
async def pump():
 last=con.execute('SELECT COALESCE(MAX(seq),0) FROM events').fetchone()[0]
 while True:
  try:
   rows=con.execute('SELECT * FROM events WHERE seq>? ORDER BY seq',(last,)).fetchall()
   for e in rows:
    last=e['seq']; p=json.loads(e['payload'])
    for ws in list(sockets):
     try:
      if p['channel_id'] in getattr(ws,'subs',set()) and not ws.closed:
       await ws.send_json(p)
     except Exception:
      pass
  except Exception:
   pass
  await asyncio.sleep(.05)
async def api(req):
 path=req.path; method=req.method
 if path=='/api/health': return web.json_response({'status':'ok','node_id':req.app['node']})
 if path=='/': return web.FileResponse('/app/static/index.html')
 if path.startswith('/static/'): return web.FileResponse('/app/static/'+path[8:])
 try:
  if path=='/api/auth/register' and method=='POST':
   d=await body(req); u=d.get('username',''); p=d.get('password','')
   if not re.fullmatch(r'[A-Za-z0-9_]{1,32}',u) or len(p)<8:return err(400,'invalid credentials')
   try: con.execute('INSERT INTO users(username,password,display_name) VALUES(?,?,?)',(u,p,d.get('display_name') or u))
   except sqlite3.IntegrityError:return err(409,'duplicate username')
   uid=con.execute('SELECT last_insert_rowid()').fetchone()[0]; t=secrets.token_urlsafe(24); con.execute('INSERT INTO tokens VALUES(?,?)',(t,uid)); return web.json_response({'user':user(con.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone()),'token':t},status=201)
  if path=='/api/auth/login' and method=='POST':
   d=await body(req); r=con.execute('SELECT * FROM users WHERE username=? AND password=?',(d.get('username'),d.get('password'))).fetchone()
   if not r:return err(401,'invalid credentials')
   t=secrets.token_urlsafe(24);con.execute('INSERT INTO tokens VALUES(?,?)',(t,r['id']));return web.json_response({'user':user(r),'token':t})
  u=auth(req)
  if path=='/api/auth/me': return web.json_response({'user':user(u)})
  if path=='/api/workspaces' and method=='POST':
   d=await body(req); slug=d.get('slug',''); name=d.get('name','')
   if not re.fullmatch(r'[a-z0-9-]{2,32}',slug) or not name:return err(400,'invalid workspace')
   try: con.execute('INSERT INTO workspaces(slug,name,owner_id) VALUES(?,?,?)',(slug,name,u['id']))
   except sqlite3.IntegrityError:return err(409,'duplicate workspace')
   wid=con.execute('SELECT last_insert_rowid()').fetchone()[0];con.execute('INSERT INTO members VALUES(?,?,?)',(wid,u['id'],'owner'));con.execute('INSERT INTO channels(workspace_id,name) VALUES(?,?)',(wid,'general'));cid=con.execute('SELECT last_insert_rowid()').fetchone()[0];con.execute('INSERT INTO cmembers VALUES(?,?)',(cid,u['id']));return web.json_response({'workspace':{'id':wid,'slug':slug,'name':name,'owner_id':u['id'],'join_mode':'open'},'general_channel':chan(con.execute('SELECT * FROM channels WHERE id=?',(cid,)).fetchone())},status=201)
  if path=='/api/workspaces' and method=='GET':
   return web.json_response({'workspaces':[dict(x) for x in con.execute('SELECT w.* FROM workspaces w JOIN members m ON m.workspace_id=w.id WHERE m.user_id=?',(u['id'],))]})
  m=re.fullmatch(r'/api/workspaces/([^/]+)',path)
  if m and method=='GET':
   w=con.execute('SELECT * FROM workspaces WHERE slug=?',(m.group(1),)).fetchone()
   if not w:return err(404,'not found')
   cs=[chan(x) for x in con.execute('SELECT c.* FROM channels c JOIN cmembers m ON m.channel_id=c.id WHERE c.workspace_id=? AND m.user_id=? AND c.is_dm=0',(w['id'],u['id']))]
   return web.json_response({'workspace':dict(w),'channels':cs,'read_state':[]})
  m=re.fullmatch(r'/api/workspaces/([^/]+)/channels',path)
  if m and method=='POST':
   w=con.execute('SELECT * FROM workspaces WHERE slug=?',(m.group(1),)).fetchone(); d=await body(req)
   if not w:return err(404,'not found')
   n=d.get('name','')
   if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*',n) or len(n)>32:return err(400,'invalid name')
   if con.execute('SELECT 1 FROM channels WHERE workspace_id=? AND name=?',(w['id'],n)).fetchone():return err(409,'duplicate channel')
   con.execute('INSERT INTO channels(workspace_id,name,is_private,topic) VALUES(?,?,?,?)',(w['id'],n,int(bool(d.get('is_private'))),d.get('topic','')));cid=con.execute('SELECT last_insert_rowid()').fetchone()[0];con.execute('INSERT INTO cmembers VALUES(?,?)',(cid,u['id']));return web.json_response({'channel':chan(con.execute('SELECT * FROM channels WHERE id=?',(cid,)).fetchone())},status=201)
  m=re.fullmatch(r'/api/channels/(\d+)/join',path)
  if m and method=='POST':
   c=con.execute('SELECT c.*,w.join_mode FROM channels c JOIN workspaces w ON w.id=c.workspace_id WHERE c.id=?',(int(m.group(1)),)).fetchone()
   if not c:return err(404,'not found')
   con.execute('INSERT OR IGNORE INTO members VALUES(?,?,?)',(c['workspace_id'],u['id'],'member'));con.execute('INSERT OR IGNORE INTO cmembers VALUES(?,?)',(c['id'],u['id']));return web.json_response({'channel':chan(c)})
  m=re.fullmatch(r'/api/channels/(\d+)',path)
  if m and method=='PATCH':
   c=con.execute('SELECT c.*,w.owner_id FROM channels c JOIN workspaces w ON w.id=c.workspace_id WHERE c.id=?',(int(m.group(1)),)).fetchone()
   if not c:return err(404,'not found')
   d=await body(req)
   if not isinstance(d.get('topic',''),str) or len(d.get('topic',''))>250:return err(400,'invalid topic')
   con.execute('UPDATE channels SET topic=? WHERE id=?',(d.get('topic',''),c['id']))
   return web.json_response({'channel':chan(con.execute('SELECT * FROM channels WHERE id=?',(c['id'],)).fetchone())})
  m=re.fullmatch(r'/api/channels/(\d+)/(archive|unarchive)',path)
  if m and method=='POST':
   c=con.execute('SELECT c.*,w.owner_id FROM channels c JOIN workspaces w ON w.id=c.workspace_id WHERE c.id=?',(int(m.group(1)),)).fetchone()
   if not c:return err(404,'not found')
   if c['owner_id']!=u['id']:return err(403,'forbidden')
   value=1 if m.group(2)=='archive' else 0
   con.execute('UPDATE channels SET is_archived=? WHERE id=?',(value,c['id']))
   return web.json_response({'channel':chan(con.execute('SELECT * FROM channels WHERE id=?',(c['id'],)).fetchone())})
  m=re.fullmatch(r'/api/channels/(\d+)/messages',path)
  if m:
   cid=int(m.group(1)); c=con.execute('SELECT * FROM channels WHERE id=?',(cid,)).fetchone()
   if not c:return err(404,'not found')
   if method=='POST':
    d=await body(req); b=d.get('body','')
    if not isinstance(b,str) or not b.strip():return err(400,'empty body')
    con.execute('INSERT INTO messages(channel_id,author_id,body,parent_id,created_at) VALUES(?,?,?,?,?)',(cid,u['id'],b,d.get('parent_id'),now())); r=con.execute('SELECT * FROM messages WHERE id=?',(con.execute('SELECT last_insert_rowid()').fetchone()[0],)).fetchone(); mm=msg(r); emit(cid,'message.reply' if r['parent_id'] else 'message.created',{'message':mm});return web.json_response({'message':mm},status=201)
   rows=con.execute('SELECT * FROM messages WHERE channel_id=? AND parent_id IS NULL AND deleted=0 ORDER BY id DESC',(cid,)).fetchall();return web.json_response({'messages':[msg(x) for x in rows],'next_cursor':None})
  m=re.fullmatch(r'/api/messages/(\d+)',path)
  if m:
   r=con.execute('SELECT * FROM messages WHERE id=?',(int(m.group(1)),)).fetchone()
   if not r:return err(404,'not found')
   if method=='PATCH':
    d=await body(req)
    if r['author_id']!=u['id']:return err(403,'forbidden')
    if r['deleted']:return err(409,'deleted')
    if not str(d.get('body','')).strip():return err(400,'empty body')
    archived=con.execute('SELECT is_archived FROM channels WHERE id=?',(r['channel_id'],)).fetchone()
    if archived and archived['is_archived']:return err(423,'archived channel')
    con.execute('UPDATE messages SET body=?,edited_at=? WHERE id=?',(d['body'],now(),r['id'])); mm=msg(con.execute('SELECT * FROM messages WHERE id=?',(r['id'],)).fetchone());emit(r['channel_id'],'message.updated',{'message':mm});return web.json_response({'message':mm})
   if method=='DELETE':
    owner=con.execute('SELECT w.owner_id FROM workspaces w JOIN channels c ON c.workspace_id=w.id WHERE c.id=?',(r['channel_id'],)).fetchone()
    if r['author_id']!=u['id'] and (not owner or owner['owner_id']!=u['id']):return err(403,'forbidden')
    if not r['deleted']:con.execute('UPDATE messages SET deleted=1 WHERE id=?',(r['id'],));emit(r['channel_id'],'message.deleted',{'message_id':r['id']})
    return web.json_response({'deleted':True})
  m=re.fullmatch(r'/api/messages/(\d+)/replies',path)
  if m:
   rows=con.execute('SELECT * FROM messages WHERE parent_id=? AND deleted=0 ORDER BY id',(int(m.group(1)),)).fetchall();return web.json_response({'replies':[msg(x) for x in rows],'next_cursor':None})
  m=re.fullmatch(r'/api/messages/(\d+)/reactions',path)
  if m and method=='POST':
   r=con.execute('SELECT * FROM messages WHERE id=?',(int(m.group(1)),)).fetchone()
   if not r or r['deleted']:return err(404,'not found')
   d=await body(req);con.execute('INSERT OR IGNORE INTO reactions VALUES(?,?,?)',(int(m.group(1)),u['id'],d.get('emoji','👍')));return web.json_response({'reactions':msg(r)['reactions']})
  m=re.fullmatch(r'/api/messages/(\d+)/reactions/(.+)',path)
  if m and method=='DELETE':
   con.execute('DELETE FROM reactions WHERE message_id=? AND user_id=? AND emoji=?',(int(m.group(1)),u['id'],m.group(2)));return web.json_response({'reactions':msg(con.execute('SELECT * FROM messages WHERE id=?',(int(m.group(1)),)).fetchone())['reactions']})
  return err(404,'not found')
 except web.HTTPException: raise
 except Exception as e: return err(500,str(e))
async def ws_handler(req):
 try:
  t=req.query.get('token')
  if t:
   r=con.execute('SELECT u.* FROM tokens t JOIN users u ON u.id=t.user_id WHERE t.token=?',(t,)).fetchone()
   if not r: raise Exception()
   u=r
  else:
   u=auth(req)
 except: raise web.HTTPUnauthorized()
 ws=web.WebSocketResponse();await ws.prepare(req);ws.subs=set();sockets.append(ws)
 try:
  async for x in ws:
   if x.type==WSMsgType.TEXT:
    d=json.loads(x.data);cid=int(d.get('channel_id',0)); c=con.execute('SELECT last_event_id FROM channels WHERE id=?',(cid,)).fetchone()
    if d.get('type')=='subscribe':ws.subs.add(cid);await ws.send_json({'type':'subscribed','channel_id':cid,'head_event_id':c[0] if c else 0})
    elif d.get('type')=='resume':
     for r in con.execute('SELECT payload FROM events WHERE channel_id=? AND event_id>? ORDER BY event_id',(cid,int(d.get('since_event_id',0)))):await ws.send_str(r[0])
     await ws.send_json({'type':'resumed','channel_id':cid,'head_event_id':c[0] if c else 0})
 finally:
  if ws in sockets: sockets.remove(ws)
 return ws
def make(port,node):
 app=web.Application();app['node']=node;app.router.add_route('*','/{tail:.*}',api);app.router.add_get('/api/ws',ws_handler)
 async def st(a):a['pump']=asyncio.create_task(pump())
 async def cl(a):a['pump'].cancel()
 app.on_startup.append(st);app.on_cleanup.append(cl);return app
if __name__=='__main__':
 init_db();p=argparse.ArgumentParser();p.add_argument('--port',type=int);p.add_argument('--node-id',type=int);a=p.parse_args();web.run_app(make(a.port,a.node_id),host='0.0.0.0',port=a.port)
