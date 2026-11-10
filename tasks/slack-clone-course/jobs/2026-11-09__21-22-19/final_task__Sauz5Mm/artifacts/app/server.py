import asyncio,base64,hashlib,json,os,re,secrets,sqlite3,sys,uuid
from zoneinfo import ZoneInfo
from datetime import datetime,timezone
from aiohttp import web,WSMsgType
DB='/app/data/app.db'; NODE=0; clients={}; ws_users={}
def now(): return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z')
def con():
 c=sqlite3.connect(DB,timeout=10,isolation_level=None,check_same_thread=False); c.row_factory=sqlite3.Row
 c.execute('PRAGMA journal_mode=WAL'); c.execute('PRAGMA busy_timeout=10000'); return c
def init():
 os.makedirs('/app/data',exist_ok=True); c=con()
 c.executescript('''CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,username TEXT UNIQUE,password TEXT,display_name TEXT,timezone TEXT DEFAULT "UTC",avatar_url TEXT DEFAULT "",status_text TEXT DEFAULT "",status_emoji TEXT DEFAULT "");
 CREATE TABLE IF NOT EXISTS tokens(token TEXT PRIMARY KEY,user_id INTEGER);
 CREATE TABLE IF NOT EXISTS workspaces(id INTEGER PRIMARY KEY,slug TEXT UNIQUE,name TEXT,owner_id INTEGER,join_mode TEXT DEFAULT "open");
 CREATE TABLE IF NOT EXISTS members(workspace_id INTEGER,user_id INTEGER,role TEXT,PRIMARY KEY(workspace_id,user_id));
 CREATE TABLE IF NOT EXISTS channels(id INTEGER PRIMARY KEY,workspace_id INTEGER,name TEXT,is_private INTEGER DEFAULT 0,is_dm INTEGER DEFAULT 0,topic TEXT DEFAULT "",is_archived INTEGER DEFAULT 0,created_at TEXT,last_event_id INTEGER DEFAULT 0);
 CREATE TABLE IF NOT EXISTS cmembers(channel_id INTEGER,user_id INTEGER,PRIMARY KEY(channel_id,user_id));
 CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY,channel_id INTEGER,author_id INTEGER,body TEXT,parent_id INTEGER,created_at TEXT,edited_at TEXT,deleted INTEGER DEFAULT 0,mentions TEXT DEFAULT "[]");
 CREATE TABLE IF NOT EXISTS reactions(message_id INTEGER,user_id INTEGER,emoji TEXT,PRIMARY KEY(message_id,user_id,emoji));
 CREATE TABLE IF NOT EXISTS pins(message_id INTEGER PRIMARY KEY,pinned_by INTEGER,pinned_at TEXT);
 CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT,channel_id INTEGER,event_id INTEGER,payload TEXT);
 CREATE TABLE IF NOT EXISTS broadcasts(seq INTEGER PRIMARY KEY AUTOINCREMENT,payload TEXT);
 CREATE TABLE IF NOT EXISTS readstate(user_id INTEGER,channel_id INTEGER,last_read_event_id INTEGER DEFAULT 0,PRIMARY KEY(user_id,channel_id));
 CREATE TABLE IF NOT EXISTS invitations(code TEXT PRIMARY KEY,workspace_id INTEGER,invited_user_id INTEGER,expires REAL,max_uses INTEGER,uses INTEGER DEFAULT 0,revoked INTEGER DEFAULT 0);
 CREATE TABLE IF NOT EXISTS files(id INTEGER PRIMARY KEY,uploader_id INTEGER,filename TEXT,content_type TEXT,size INTEGER,created_at TEXT,data BLOB);
 CREATE TABLE IF NOT EXISTS message_files(message_id INTEGER,file_id INTEGER,PRIMARY KEY(message_id,file_id));
 CREATE TABLE IF NOT EXISTS ws_presence(conn_id TEXT PRIMARY KEY,node_id INTEGER,user_id INTEGER);
 CREATE TABLE IF NOT EXISTS groups_(id INTEGER PRIMARY KEY,workspace_id INTEGER,handle TEXT,name TEXT,creator_id INTEGER,user_ids TEXT,UNIQUE(workspace_id,handle));''')
 c.close()
def ujson(r): return {k:r[k] for k in ('id','username','display_name','timezone','avatar_url','status_text','status_emoji')}
def chjson(r): return {'id':r['id'],'workspace_id':r['workspace_id'],'name':r['name'],'is_private':bool(r['is_private']),'is_dm':bool(r['is_dm']),'topic':r['topic'] or '','is_archived':bool(r['is_archived']),'created_at':r['created_at']}
class E(Exception):
 def __init__(self,s,m): self.s=s; self.m=m
@web.middleware
async def mw(req,handler):
 try:return await handler(req)
 except E as e:return web.json_response({'error':e.m},status=e.s)
 except web.HTTPException: raise
 except Exception as e:return web.json_response({'error':str(e)},status=500)
def auth(req):
 t=req.headers.get('Authorization','')
 if t.startswith('Bearer '):
  token=t[7:]
 else:
  token=req.query.get('token','')
  if token.startswith('Bearer '): token=token[7:]
 if not token: raise E(401,'unauthorized')
 c=con(); r=c.execute('SELECT u.* FROM tokens t JOIN users u ON u.id=t.user_id WHERE t.token=?',(token,)).fetchone(); c.close()
 if not r: raise E(401,'unauthorized')
 return r
async def body(req):
 try:x=await req.json(); return x if isinstance(x,dict) else {}
 except:return {}
def emit(cid,kind,data):
 c=con(); c.execute('BEGIN IMMEDIATE'); c.execute('UPDATE channels SET last_event_id=last_event_id+1 WHERE id=?',(cid,)); n=c.execute('SELECT last_event_id FROM channels WHERE id=?',(cid,)).fetchone()[0]; p={'type':kind,'event_id':n,'channel_id':cid,**data}; c.execute('INSERT INTO events(channel_id,event_id,payload) VALUES(?,?,?)',(cid,n,json.dumps(p))); c.commit(); c.close(); return n
def message(c,r):
 a=c.execute('SELECT * FROM users WHERE id=?',(r['author_id'],)).fetchone()
 rs={}
 for x in c.execute('SELECT emoji,user_id FROM reactions WHERE message_id=?',(r['id'],)): rs.setdefault(x['emoji'],[]).append(x['user_id'])
 return {'id':r['id'],'channel_id':r['channel_id'],'author_id':r['author_id'],'author':ujson(a),'body':r['body'],'parent_id':r['parent_id'],'reply_count':c.execute('SELECT count(*) FROM messages WHERE parent_id=? AND deleted=0',(r['id'],)).fetchone()[0],'created_at':r['created_at'],'edited_at':r['edited_at'],'files':[dict(x) for x in c.execute('SELECT f.id,f.uploader_id,f.filename,f.content_type,f.size,f.created_at FROM files f JOIN message_files mf ON mf.file_id=f.id WHERE mf.message_id=?',(r['id'],)).fetchall()],'reactions':[{'emoji':k,'count':len(v),'user_ids':v} for k,v in rs.items()],'mentions':json.loads(r['mentions'] or '[]')}
def wsrow(c,slug):
 r=c.execute('SELECT * FROM workspaces WHERE slug=?',(slug,)).fetchone()
 if not r: raise E(404,'not found')
 return r
async def health(req): return web.json_response({'status':'ok','node_id':NODE})
async def register(req):
 d=await body(req); name=d.get('username',''); pw=d.get('password','')
 if not re.fullmatch(r'[A-Za-z0-9_]{1,32}',name) or len(pw)<8: raise E(400,'invalid')
 c=con()
 try:c.execute('INSERT INTO users(username,password,display_name) VALUES(?,?,?)',(name,pw,d.get('display_name') or name))
 except sqlite3.IntegrityError: raise E(409,'duplicate')
 uid=c.execute('SELECT last_insert_rowid()').fetchone()[0]; tok=secrets.token_urlsafe(24); c.execute('INSERT INTO tokens VALUES(?,?)',(tok,uid)); r=c.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone(); c.close(); return web.json_response({'user':ujson(r),'token':tok},status=201)
async def login(req):
 d=await body(req); c=con(); r=c.execute('SELECT * FROM users WHERE username=? AND password=?',(d.get('username'),d.get('password'))).fetchone()
 if not r: raise E(401,'invalid credentials')
 t=secrets.token_urlsafe(24); c.execute('INSERT INTO tokens VALUES(?,?)',(t,r['id'])); c.close(); return web.json_response({'user':ujson(r),'token':t})
async def me(req): return web.json_response({'user':ujson(auth(req))})
async def workspaces(req):
 u=auth(req); c=con()
 if req.method=='POST':
  d=await body(req); slug=d.get('slug',''); name=d.get('name','')
  if not re.fullmatch(r'[a-z0-9-]{2,32}',slug) or not name: raise E(400,'invalid')
  try:c.execute('INSERT INTO workspaces(slug,name,owner_id) VALUES(?,?,?)',(slug,name,u['id']))
  except sqlite3.IntegrityError: raise E(409,'duplicate')
  wid=c.execute('SELECT last_insert_rowid()').fetchone()[0]; c.execute('INSERT INTO members VALUES(?,?,?)',(wid,u['id'],'owner')); c.execute('INSERT INTO channels(workspace_id,name,created_at) VALUES(?,?,?)',(wid,'general',now())); cid=c.execute('SELECT last_insert_rowid()').fetchone()[0]; c.execute('INSERT INTO cmembers VALUES(?,?)',(cid,u['id'])); r=c.execute('SELECT * FROM workspaces WHERE id=?',(wid,)).fetchone(); q=c.execute('SELECT * FROM channels WHERE id=?',(cid,)).fetchone(); c.close(); return web.json_response({'workspace':dict(r),'general_channel':chjson(q)},status=201)
 rows=c.execute('SELECT w.* FROM workspaces w JOIN members m ON m.workspace_id=w.id WHERE m.user_id=?',(u['id'],)).fetchall(); c.close(); return web.json_response({'workspaces':[dict(x) for x in rows]})
async def workspace(req):
 u=auth(req); c=con(); w=wsrow(c,req.match_info['slug']); c.execute('INSERT OR IGNORE INTO members VALUES(?,?,?)',(w['id'],u['id'],'member')) if w['join_mode']=='open' else None
 rows=c.execute("SELECT ch.* FROM channels ch LEFT JOIN cmembers cm ON cm.channel_id=ch.id AND cm.user_id=? WHERE ch.workspace_id=? AND ch.is_dm=0 AND (ch.is_archived=0 OR ? IN ('1','true','True')) AND (ch.is_private=0 OR cm.user_id=?)",(u['id'],w['id'],req.query.get('include_archived','0'),u['id'])).fetchall()
 if req.method=='PATCH':
  d=await body(req); role=c.execute('SELECT role FROM members WHERE workspace_id=? AND user_id=?',(w['id'],u['id'])).fetchone()
  if not role or role['role'] not in ('owner','admin'): raise E(403,'forbidden')
  if 'join_mode' in d and d['join_mode'] not in ('open','invite_only'): raise E(400,'invalid')
  c.execute('UPDATE workspaces SET name=COALESCE(?,name),join_mode=COALESCE(?,join_mode) WHERE id=?',(d.get('name'),d.get('join_mode'),w['id'])); w=c.execute('SELECT * FROM workspaces WHERE id=?',(w['id'],)).fetchone(); c.close(); return web.json_response({'workspace':dict(w)})
 states=[]
 for x in rows:
  q=c.execute('SELECT last_read_event_id FROM readstate WHERE user_id=? AND channel_id=?',(u['id'],x['id'])).fetchone()
  n=q['last_read_event_id'] if q else 0
  unread=c.execute("SELECT count(*) FROM events e JOIN messages m ON m.id=json_extract(e.payload,'$.message.id') WHERE e.channel_id=? AND e.event_id>? AND m.author_id!=? AND m.deleted=0",(x['id'],n,u['id'])).fetchone()[0]
  mention=c.execute("SELECT count(*) FROM events e JOIN messages m ON m.id=json_extract(e.payload,'$.message.id') WHERE e.channel_id=? AND e.event_id>? AND m.author_id!=? AND m.mentions LIKE ?",(x['id'],n,u['id'],'%'+str(u['id'])+'%')).fetchone()[0]
  states.append({'channel_id':x['id'],'last_read_event_id':n,'unread_count':unread,'mention_count':mention})
 c.close(); return web.json_response({'workspace':dict(w),'channels':[chjson(x) for x in rows],'read_state':states})
async def channels(req):
 u=auth(req); c=con(); w=wsrow(c,req.match_info['slug']); role=c.execute('SELECT role FROM members WHERE workspace_id=? AND user_id=?',(w['id'],u['id'])).fetchone()
 if not role: raise E(403,'forbidden')
 d=await body(req); n=d.get('name','')
 if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*',n) or len(n)>32 or len(d.get('topic',''))>250: raise E(400,'invalid')
 if c.execute('SELECT 1 FROM channels WHERE workspace_id=? AND name=?',(w['id'],n)).fetchone(): raise E(409,'duplicate')
 if role['role']=='guest': raise E(403,'forbidden')
 if d.get('is_private') and role['role'] not in ('owner','admin'): raise E(403,'forbidden')
 c.execute('INSERT INTO channels(workspace_id,name,is_private,topic,created_at) VALUES(?,?,?,?,?)',(w['id'],n,int(bool(d.get('is_private'))),d.get('topic',''),now())); cid=c.execute('SELECT last_insert_rowid()').fetchone()[0]; c.execute('INSERT INTO cmembers VALUES(?,?)',(cid,u['id'])); r=c.execute('SELECT * FROM channels WHERE id=?',(cid,)).fetchone(); c.close(); return web.json_response({'channel':chjson(r)},status=201)
async def chan(req):
 u=auth(req); cid=int(req.match_info['id']); c=con(); r=c.execute('SELECT * FROM channels WHERE id=?',(cid,)).fetchone()
 if not r: raise E(404,'not found')
 if req.method=='POST' and req.match_info.get('action')=='join':
  w=c.execute('SELECT * FROM workspaces WHERE id=?',(r['workspace_id'],)).fetchone(); m=c.execute('SELECT * FROM members WHERE workspace_id=? AND user_id=?',(w['id'],u['id'])).fetchone()
  if r['is_private']: raise E(403,'private')
  if m and m['role']=='guest': raise E(403,'forbidden')
  if not m and w['join_mode']=='invite_only': raise E(403,'forbidden')
  was=c.execute('SELECT 1 FROM cmembers WHERE channel_id=? AND user_id=?',(cid,u['id'])).fetchone(); c.execute('INSERT OR IGNORE INTO members VALUES(?,?,?)',(w['id'],u['id'],'member')); c.execute('INSERT OR IGNORE INTO cmembers VALUES(?,?)',(cid,u['id'])); c.close();
  if not was: emit(cid,'member.joined',{'user_id':u['id']})
  return web.json_response({'channel':chjson(r)})
 if req.method=='PATCH':
  if c.execute('SELECT is_archived FROM channels WHERE id=?',(cid,)).fetchone()['is_archived']: raise E(423,'archived')
  d=await body(req)
  if len(d.get('topic',''))>250: raise E(400,'invalid')
  if not c.execute('SELECT 1 FROM cmembers WHERE channel_id=? AND user_id=?',(cid,u['id'])).fetchone() and c.execute('SELECT 1 FROM workspaces w JOIN channels x ON x.workspace_id=w.id WHERE x.id=? AND w.owner_id=?',(cid,u['id'])).fetchone() is None: raise E(403,'forbidden')
  c.execute('UPDATE channels SET topic=? WHERE id=?',(d.get('topic',''),cid)); r=c.execute('SELECT * FROM channels WHERE id=?',(cid,)).fetchone(); c.close(); emit(cid,'channel.updated',{'channel':chjson(r)}); return web.json_response({'channel':chjson(r)})
 c.close(); return web.json_response({'channel':chjson(r)})
async def msgs(req):
 u=auth(req); cid=int(req.match_info['id']); c=con(); ch=c.execute('SELECT * FROM channels WHERE id=?',(cid,)).fetchone()
 if not ch: raise E(404,'not found')
 if not c.execute('SELECT 1 FROM cmembers WHERE channel_id=? AND user_id=?',(cid,u['id'])).fetchone() and c.execute('SELECT 1 FROM workspaces w JOIN channels x ON x.workspace_id=w.id WHERE x.id=? AND w.owner_id=?',(cid,u['id'])).fetchone() is None: raise E(403,'forbidden')
 if req.method=='POST':
  d=await body(req); b=d.get('body','')
  if ch['is_archived'] and b != '/unarchive': raise E(423,'archived')
  if not isinstance(b,str) or not b.strip(): raise E(400,'empty')
  if b.startswith('//'):
   b=b[1:]
  elif b.startswith('/'):
   parts=b.split(' ',1); cmd=parts[0][1:]; arg=parts[1] if len(parts)>1 else ''
   if cmd=='me':
    if not arg.strip(): raise E(400,'missing text')
   elif cmd=='shrug':
    b=(arg+' ' if arg else '')+'¯\\_(ツ)_/¯'
   elif cmd=='topic':
    if len(arg)>250: raise E(400,'invalid')
    c.execute('UPDATE channels SET topic=? WHERE id=?',(arg,cid)); r2=c.execute('SELECT * FROM channels WHERE id=?',(cid,)).fetchone(); c.close(); emit(cid,'channel.updated',{'channel':chjson(r2)}); return web.json_response({'message':None,'channel':chjson(r2)},status=201)
   elif cmd=='archive' or cmd=='unarchive':
    owner=c.execute('SELECT 1 FROM workspaces w WHERE w.id=? AND w.owner_id=?',(ch['workspace_id'],u['id'])).fetchone()
    if not owner: raise E(403,'forbidden')
    val=1 if cmd=='archive' else 0; c.execute('UPDATE channels SET is_archived=? WHERE id=?',(val,cid)); r2=c.execute('SELECT * FROM channels WHERE id=?',(cid,)).fetchone(); c.close(); emit(cid,'channel.archived' if val else 'channel.unarchived',{'channel':chjson(r2)}); return web.json_response({'message':None,'channel':chjson(r2)},status=201)
   elif cmd=='invite':
    if not arg.startswith('@'): raise E(400,'invalid invite')
    target=c.execute('SELECT id FROM users WHERE username=?',(arg[1:].split()[0],)).fetchone()
    if not target: raise E(404,'not found')
    if not c.execute('SELECT 1 FROM members WHERE workspace_id=? AND user_id=?',(ch['workspace_id'],target['id'])).fetchone(): raise E(400,'user is not a workspace member')
    c.execute('INSERT OR IGNORE INTO cmembers VALUES(?,?)',(cid,target['id'])); invited=c.execute('SELECT * FROM users WHERE id=?',(target['id'],)).fetchone(); c.close(); return web.json_response({'message':None,'invited_user':ujson(invited)},status=201)
   else:
    raise E(400,'unknown command')

  file_ids=d.get('file_ids') or []
  if not isinstance(file_ids,list): raise E(400,'invalid files')
  for fid in file_ids:
   if not isinstance(fid,int) or not c.execute('SELECT 1 FROM files WHERE id=? AND uploader_id=?',(fid,u['id'])).fetchone() or c.execute('SELECT 1 FROM message_files WHERE file_id=?',(fid,)).fetchone(): raise E(400,'invalid file')
  mention_ids=[]
  for z in re.findall(r'(?<![A-Za-z0-9_])@([A-Za-z0-9_]+)',b):
   if z=='here':
    online={x['user_id'] for x in c.execute('SELECT DISTINCT user_id FROM ws_presence')}
    mention_ids += [x['user_id'] for x in c.execute('SELECT user_id FROM cmembers WHERE channel_id=? AND user_id!=?',(cid,u['id'])) if x['user_id'] in online]
   elif z=='channel':
    mention_ids += [x['user_id'] for x in c.execute('SELECT user_id FROM cmembers WHERE channel_id=? AND user_id!=?',(cid,u['id']))]
   else:
    x=c.execute('SELECT id FROM users WHERE username=?',(z,)).fetchone()
    if x and x['id']!=u['id'] and c.execute('SELECT 1 FROM cmembers WHERE channel_id=? AND user_id=?',(cid,x['id'])).fetchone(): mention_ids.append(x['id'])
  mention_ids=list(dict.fromkeys(mention_ids))
  c.execute('INSERT INTO messages(channel_id,author_id,body,parent_id,created_at,mentions) VALUES(?,?,?,?,?,?)',(cid,u['id'],b,d.get('parent_id'),now(),json.dumps(mention_ids)))
  mid=c.execute('SELECT last_insert_rowid()').fetchone()[0]; c.executemany('INSERT INTO message_files(message_id,file_id) VALUES(?,?)',[(mid,x) for x in file_ids]); r=c.execute('SELECT * FROM messages WHERE id=?',(mid,)).fetchone(); out=message(c,r); c.close()
  emit(cid,'message.reply' if d.get('parent_id') else 'message.created',{'message':out})
  return web.json_response({'message':out},status=201)
 try:
  lim=int(req.query.get('limit','50')); cur=int(req.query.get('cursor','0') or 0)
 except: raise E(400,'invalid pagination')
 if lim<1 or lim>200: raise E(400,'invalid pagination')
 rows=c.execute('SELECT * FROM messages WHERE channel_id=? AND parent_id IS NULL AND deleted=0 AND id<? ORDER BY id DESC LIMIT ?',(cid,cur or 9223372036854775807,lim+1)).fetchall()
 out=[message(c,x) for x in rows[:lim]]; nxt=str(out[-1]['id']) if len(rows)>lim else None
 c.close(); return web.json_response({'messages':out,'next_cursor':nxt})

async def join_handler(req):
 req.match_info['action']='join'
 return await chan(req)

async def events_ws(req):
 u=auth(req); ws=web.WebSocketResponse(); await ws.prepare(req); clients[ws]={}; ws_users[ws]=u['id']; conn_id=uuid.uuid4().hex; c=con(); c.execute('INSERT OR REPLACE INTO ws_presence VALUES(?,?,?)',(conn_id,NODE,u['id'])); last=c.execute('SELECT COALESCE(MAX(seq),0) FROM events').fetchone()[0]; c.close()
 try:
  async for x in ws:
   if x.type==WSMsgType.TEXT:
    d=json.loads(x.data); cid=d.get('channel_id')
    if d.get('type')=='subscribe':
     ok=con().execute('SELECT 1 FROM cmembers WHERE channel_id=? AND user_id=?',(cid,u['id'])).fetchone()
     if not ok: await ws.send_json({'type':'error','error':'forbidden'}); continue
     c=con(); h=c.execute('SELECT last_event_id FROM channels WHERE id=?',(cid,)).fetchone()[0]; c.close(); clients[ws][cid]=h; await ws.send_json({'type':'subscribed','channel_id':cid,'head_event_id':h})
    elif d.get('type')=='resume':
     if not con().execute('SELECT 1 FROM cmembers WHERE channel_id=? AND user_id=?',(cid,u['id'])).fetchone(): await ws.send_json({'type':'error','error':'forbidden'}); continue
     c=con(); rs=c.execute('SELECT payload FROM events WHERE channel_id=? AND event_id>? ORDER BY event_id',(cid,d.get('since_event_id',0))).fetchall(); h=c.execute('SELECT last_event_id FROM channels WHERE id=?',(cid,)).fetchone()[0]; clients[ws][cid]=h; c.close()
     for r in rs: await ws.send_str(r['payload'])
     await ws.send_json({'type':'resumed','channel_id':cid,'head_event_id':h})
 finally:
  clients.pop(ws,None); ws_users.pop(ws,None)
  c=con(); c.execute('DELETE FROM ws_presence WHERE conn_id=?',(conn_id,)); c.close()
 return ws
async def pump(app):
 c=con(); last=c.execute('SELECT COALESCE(MAX(seq),0) FROM events').fetchone()[0]; lastb=c.execute('SELECT COALESCE(MAX(seq),0) FROM broadcasts').fetchone()[0]; c.close()
 while True:
  await asyncio.sleep(.05); c=con(); rs=c.execute('SELECT seq,payload FROM events WHERE seq>? ORDER BY seq',(last,)).fetchall(); bs=c.execute('SELECT seq,payload FROM broadcasts WHERE seq>? ORDER BY seq',(lastb,)).fetchall(); last=rs[-1]['seq'] if rs else last; lastb=bs[-1]['seq'] if bs else lastb; c.close()
  for r in bs:
   for w in list(clients):
    try: await w.send_str(r['payload'])
    except: clients.pop(w,None)
  for r in rs:
   for w,subs in list(clients.items()):
    payload=json.loads(r['payload']); cid=payload.get('channel_id')
    if cid not in subs or payload.get('event_id',0) <= subs[cid]: continue
    try: await w.send_str(r['payload']); subs[cid]=payload.get('event_id',subs[cid])
    except: clients.pop(w,None)

async def adminextra(req):
 u=auth(req); c=con(); slug=req.match_info.get('slug'); w=wsrow(c,slug)
 if req.path.endswith('/transfer_ownership'):
  m=c.execute('SELECT role FROM members WHERE workspace_id=? AND user_id=?',(w['id'],u['id'])).fetchone()
  if not m or m['role']!='owner': raise E(403,'forbidden')
  d=await body(req); t=int(d.get('new_owner_id',0)); x=c.execute('SELECT role FROM members WHERE workspace_id=? AND user_id=?',(w['id'],t)).fetchone()
  if not x or x['role']!='admin': raise E(400,'target must be admin')
  c.execute('UPDATE members SET role=? WHERE workspace_id=? AND user_id=?',('admin',w['id'],u['id'])); c.execute('UPDATE members SET role=? WHERE workspace_id=? AND user_id=?',('owner',w['id'],t)); c.execute('UPDATE workspaces SET owner_id=? WHERE id=?',(t,w['id'])); c.close(); return web.json_response({'ok':True})
 m=c.execute('SELECT role FROM members WHERE workspace_id=? AND user_id=?',(w['id'],u['id'])).fetchone()
 if not m or m['role'] not in ('owner','admin'): raise E(403,'forbidden')
 if req.path.endswith('/invitations') and req.method=='POST':
  d=await body(req); target=d.get('invited_user_id')
  if not target and d.get('invited_username'):
   z=c.execute('SELECT id FROM users WHERE username=?',(d['invited_username'],)).fetchone(); target=z['id'] if z else None
  code=secrets.token_urlsafe(12); exp=__import__('time').time()+int(d.get('expires_in_seconds',604800)); mx=1 if target else int(d.get('max_uses',1)); c.execute('INSERT INTO invitations VALUES(?,?,?,?,?,?,?)',(code,w['id'],target,exp,mx,0,0)); c.close(); return web.json_response({'invitation':{'code':code,'workspace_id':w['id'],'max_uses':mx}},status=201)
 if req.path.endswith('/invitations') and req.method=='GET':
  rs=c.execute('SELECT * FROM invitations WHERE workspace_id=? AND revoked=0',(w['id'],)).fetchall(); c.close(); return web.json_response({'invitations':[dict(x) for x in rs]})
 if '/invitations/' in req.path and req.method=='DELETE':
  code=req.match_info['code']; c.execute('UPDATE invitations SET revoked=1 WHERE code=? AND workspace_id=?',(code,w['id'])); c.close(); return web.json_response({'deleted':True})
 raise E(404,'not found')
async def acceptinvite(req):
 u=auth(req); c=con(); x=c.execute('SELECT * FROM invitations WHERE code=?',(req.match_info['code'],)).fetchone()
 if not x or x['revoked'] or x['uses']>=x['max_uses'] or x['expires']<__import__('time').time(): raise E(404,'not found')
 if x['invited_user_id'] and x['invited_user_id']!=u['id']: raise E(403,'forbidden')
 c.execute('INSERT OR REPLACE INTO members VALUES(?,?,?)',(x['workspace_id'],u['id'],'member')); c.execute('UPDATE invitations SET uses=uses+1 WHERE code=?',(x['code'],)); c.close(); return web.json_response({'accepted':True})
async def pinroutes(req):
 u=auth(req); c=con(); cid=int(req.match_info['id']); ch=c.execute('SELECT * FROM channels WHERE id=?',(cid,)).fetchone()
 if not ch: raise E(404,'not found')
 member=c.execute('SELECT 1 FROM cmembers WHERE channel_id=? AND user_id=?',(cid,u['id'])).fetchone()
 if not member and ch['is_private']: raise E(403,'forbidden')
 try: lim=int(req.query.get('limit','50')); cur=int(req.query.get('cursor','0') or 0)
 except: raise E(400,'invalid pagination')
 if lim<1 or lim>200: raise E(400,'invalid pagination')
 rows=c.execute('SELECT p.*,m.* FROM pins p JOIN messages m ON m.id=p.message_id WHERE m.channel_id=? AND p.message_id<? ORDER BY p.message_id DESC LIMIT ?',(cid,cur or 9223372036854775807,lim+1)).fetchall()
 out=[{'message':message(c,x),'pinned_by':x['pinned_by'],'pinned_at':x['pinned_at']} for x in rows[:lim]]
 c.close(); return web.json_response({'pins':out,'next_cursor':str(out[-1]['message']['id']) if len(rows)>lim else None})

async def search(req):
 u=auth(req); q=req.query.get('q','').strip()
 if not q: raise E(400,'query')
 try: lim=int(req.query.get('limit','50')); cur=int(req.query.get('cursor','0') or 0)
 except: raise E(400,'invalid pagination')
 if lim<1 or lim>200: raise E(400,'invalid pagination')
 c=con(); wid=req.query.get('workspace_id')
 if wid:
  rows=c.execute("SELECT m.* FROM messages m JOIN cmembers cm ON cm.channel_id=m.channel_id JOIN channels ch ON ch.id=m.channel_id WHERE cm.user_id=? AND ch.workspace_id=? AND m.body LIKE ? AND m.deleted=0 AND m.id<? ORDER BY m.id DESC LIMIT ?",(u['id'],int(wid),'%'+q+'%',cur or 9223372036854775807,lim+1)).fetchall()
 else:
  rows=c.execute("SELECT m.* FROM messages m JOIN cmembers cm ON cm.channel_id=m.channel_id WHERE cm.user_id=? AND m.body LIKE ? AND m.deleted=0 AND m.id<? ORDER BY m.id DESC LIMIT ?",(u['id'],'%'+q+'%',cur or 9223372036854775807,lim+1)).fetchall()
 out=[message(c,x) for x in rows[:lim]]; nxt=str(out[-1]['id']) if len(rows)>lim else None; c.close(); return web.json_response({'results':out,'next_cursor':nxt})


async def extra(req):
 u=auth(req); c=con(); path=req.path
 if '/workspaces/' in path and path.endswith('/members'):
  w=wsrow(c,req.match_info['slug']); rs=c.execute('SELECT m.*,u.* FROM members m JOIN users u ON u.id=m.user_id WHERE m.workspace_id=?',(w['id'],)).fetchall(); c.close()
  return web.json_response({'members':[{'user_id':r['user_id'],'role':r['role'],'user':ujson(r)} for r in rs]})
 if '/workspaces/' in path and '/members/' in path and req.method=='PATCH':
  w=wsrow(c,req.match_info['slug']); tid=int(req.match_info['user_id']); actor=c.execute('SELECT role FROM members WHERE workspace_id=? AND user_id=?',(w['id'],u['id'])).fetchone(); old=c.execute('SELECT role FROM members WHERE workspace_id=? AND user_id=?',(w['id'],tid)).fetchone()
  if not old: raise E(404,'not found')
  if not actor or actor['role'] not in ('owner','admin') or tid==w['owner_id'] or (actor['role']=='admin' and old['role']=='admin'): raise E(403,'forbidden')
  d=await body(req); role=d.get('role')
  if role not in ('admin','member','guest'): raise E(400,'invalid')
  c.execute('UPDATE members SET role=? WHERE workspace_id=? AND user_id=?',(role,w['id'],tid)); c.close(); return web.json_response({'member':{'user_id':tid,'role':role}})
 if path.endswith('/leave'):
  cid=int(req.match_info['id']); c.execute('DELETE FROM cmembers WHERE channel_id=? AND user_id=?',(cid,u['id'])); r=c.execute('SELECT * FROM channels WHERE id=?',(cid,)).fetchone(); c.close(); emit(cid,'member.left',{'user_id':u['id']}); return web.json_response({'channel':chjson(r)})
 if path.endswith('/members'):
  cid=int(req.match_info['id']); rs=c.execute('SELECT u.* FROM cmembers x JOIN users u ON u.id=x.user_id WHERE x.channel_id=?',(cid,)).fetchall(); c.close(); return web.json_response({'members':[ujson(x) for x in rs]})
 if path.endswith('/archive') or path.endswith('/unarchive'):
  cid=int(req.match_info['id']); r=c.execute('SELECT * FROM channels WHERE id=?',(cid,)).fetchone(); w=c.execute('SELECT * FROM workspaces WHERE id=?',(r['workspace_id'],)).fetchone()
  if w['owner_id']!=u['id']: raise E(403,'forbidden')
  val=0 if path.endswith('unarchive') else 1; c.execute('UPDATE channels SET is_archived=? WHERE id=?',(val,cid)); r=c.execute('SELECT * FROM channels WHERE id=?',(cid,)).fetchone(); c.close(); emit(cid,'channel.unarchived' if not val else 'channel.archived',{'channel':chjson(r)}); return web.json_response({'channel':chjson(r)})
 if path.endswith('/read'):
  cid=int(req.match_info['id']); row=c.execute('SELECT last_read_event_id FROM readstate WHERE user_id=? AND channel_id=?',(u['id'],cid)).fetchone(); n=row['last_read_event_id'] if row else 0
  if req.method=='POST': n=max(n,int((await body(req)).get('last_read_event_id',0))); c.execute('INSERT OR REPLACE INTO readstate VALUES(?,?,?)',(u['id'],cid,n))
  unread=c.execute("SELECT count(*) FROM events e JOIN messages m ON m.id=json_extract(e.payload,'$.message.id') WHERE e.channel_id=? AND e.event_id>? AND m.author_id!=? AND m.deleted=0",(cid,n,u['id'])).fetchone()[0]
  mention=c.execute("SELECT count(*) FROM events e JOIN messages m ON m.id=json_extract(e.payload,'$.message.id') WHERE e.channel_id=? AND e.event_id>? AND m.author_id!=? AND m.mentions LIKE ?",(cid,n,u['id'],'%'+str(u['id'])+'%')).fetchone()[0]
  c.close(); return web.json_response({'read_state':{'channel_id':cid,'last_read_event_id':n,'unread_count':unread,'mention_count':mention}})
 if path.endswith('/replies'):
  pid=int(req.match_info['id'])
  try: lim=int(req.query.get('limit','50')); cur=int(req.query.get('cursor','0') or 0)
  except: raise E(400,'invalid pagination')
  if lim<1 or lim>200: raise E(400,'invalid pagination')
  if not c.execute('SELECT 1 FROM messages WHERE id=?',(pid,)).fetchone(): raise E(404,'not found')
  rows=c.execute('SELECT * FROM messages WHERE parent_id=? AND deleted=0 AND id>? ORDER BY id LIMIT ?',(pid,cur,lim+1)).fetchall(); out=[message(c,x) for x in rows[:lim]]; c.close(); return web.json_response({'replies':out,'next_cursor':str(out[-1]['id']) if len(rows)>lim else None})
 if req.method in ('PATCH','DELETE') and '/messages/' in path:
  mid=int(req.match_info['id']); r=c.execute('SELECT * FROM messages WHERE id=?',(mid,)).fetchone()
  if not r: raise E(404,'not found')
  w=c.execute('SELECT w.* FROM workspaces w JOIN channels ch ON ch.workspace_id=w.id WHERE ch.id=?',(r['channel_id'],)).fetchone()
  if req.method=='DELETE':
   if r['deleted']: c.close(); return web.json_response({'deleted':True})
   if r['author_id']!=u['id'] and (not w or w['owner_id']!=u['id']): raise E(403,'forbidden')
   c.execute('UPDATE messages SET deleted=1 WHERE id=?',(mid,)); c.close(); emit(r['channel_id'],'message.deleted',{'message_id':mid}); return web.json_response({'deleted':True})
  if r['author_id']!=u['id']: raise E(403,'forbidden')
  if r['deleted']: raise E(409,'deleted')
  if c.execute('SELECT is_archived FROM channels WHERE id=?',(r['channel_id'],)).fetchone()['is_archived']: raise E(423,'archived')
  d=await body(req)
  if not isinstance(d.get('body'),str) or not d['body'].strip(): raise E(400,'empty')
  c.execute('UPDATE messages SET body=?,edited_at=? WHERE id=?',(d['body'],now(),mid)); r=c.execute('SELECT * FROM messages WHERE id=?',(mid,)).fetchone(); out=message(c,r); c.close(); emit(r['channel_id'],'message.updated',{'message':out}); return web.json_response({'message':out})
 raise E(404,'not found')

async def replies_handler(req):
 u=auth(req); c=con(); pid=int(req.match_info['id'])
 try: lim=int(req.query.get('limit','50')); cur=int(req.query.get('cursor','0') or 0)
 except: c.close(); raise E(400,'invalid pagination')
 if lim<1 or lim>200: c.close(); raise E(400,'invalid pagination')
 parent=c.execute('SELECT * FROM messages WHERE id=?',(pid,)).fetchone()
 if not parent: c.close(); raise E(404,'not found')
 if not c.execute('SELECT 1 FROM cmembers WHERE channel_id=? AND user_id=?',(parent['channel_id'],u['id'])).fetchone(): c.close(); raise E(403,'forbidden')
 rows=c.execute('SELECT * FROM messages WHERE parent_id=? AND deleted=0 AND id>? ORDER BY id LIMIT ?',(pid,cur,lim+1)).fetchall()
 out=[message(c,x) for x in rows[:lim]]; nxt=str(out[-1]['id']) if len(rows)>lim else None
 c.close(); return web.json_response({'replies':out,'next_cursor':nxt})

async def msgactions(req):
 u=auth(req); c=con(); mid=int(req.match_info['id']); r=c.execute('SELECT * FROM messages WHERE id=?',(mid,)).fetchone()
 if not r: c.close(); raise E(404,'not found')
 if r['deleted']: c.close(); raise E(404,'not found')
 if not c.execute('SELECT 1 FROM cmembers WHERE channel_id=? AND user_id=?',(r['channel_id'],u['id'])).fetchone(): c.close(); raise E(403,'forbidden')
 archived=c.execute('SELECT is_archived FROM channels WHERE id=?',(r['channel_id'],)).fetchone()['is_archived']
 if req.path.endswith('/pin') and req.method=='DELETE':
  c.execute('DELETE FROM pins WHERE message_id=?',(mid,)); c.close(); return web.json_response({'unpinned':True})
 if req.path.endswith('/pin'):
  if archived: c.close(); raise E(423,'archived')
  c.execute('INSERT OR REPLACE INTO pins VALUES(?,?,?)',(mid,u['id'],now())); p=c.execute('SELECT * FROM pins WHERE message_id=?',(mid,)).fetchone(); c.close(); return web.json_response({'pin':dict(p)})
 if '/reactions/' in req.path and req.method=='DELETE':
  if archived: c.close(); raise E(423,'archived')
  e=req.match_info.get('emoji',''); changed=c.execute('DELETE FROM reactions WHERE message_id=? AND user_id=? AND emoji=?',(mid,u['id'],e)).rowcount; out=message(c,r)['reactions']; c.close()
  if changed: emit(r['channel_id'],'reaction.removed',{'message_id':mid,'emoji':e,'user_id':u['id'],'reactions':out})
  return web.json_response({'reactions':out})
 if req.path.endswith('/reactions'):
  if archived: c.close(); raise E(423,'archived')
  e=(await body(req)).get('emoji','')
  if not isinstance(e,str) or not e.strip() or len(e)>64: c.close(); raise E(400,'invalid emoji')
  changed=c.execute('INSERT OR IGNORE INTO reactions VALUES(?,?,?)',(mid,u['id'],e)).rowcount; out=message(c,r)['reactions']; c.close()
  if changed: emit(r['channel_id'],'reaction.added',{'message_id':mid,'emoji':e,'user_id':u['id'],'reactions':out})
  return web.json_response({'reactions':out})
 raise E(404,'not found')



async def dms(req):
 u=auth(req); d=await body(req); target=d.get('user_id')
 if not isinstance(target,int): raise E(400,'invalid user_id')
 c=con(); other=c.execute('SELECT id FROM users WHERE id=?',(target,)).fetchone()
 if not other: c.close(); raise E(404,'not found')
 if target==u['id']: c.close(); raise E(400,'invalid user_id')
 a,b=sorted((u['id'],target)); name=f'dm-{a}-{b}'
 r=c.execute('SELECT id FROM channels WHERE is_dm=1 AND name=?',(name,)).fetchone()
 if not r:
  common=c.execute('SELECT workspace_id FROM members WHERE user_id=? AND workspace_id IN (SELECT workspace_id FROM members WHERE user_id=?) LIMIT 1',(u['id'],target)).fetchone()
  wid=common['workspace_id'] if common else 1
  c.execute('INSERT INTO channels(workspace_id,name,is_dm,created_at) VALUES(?,?,1,?)',(wid,name,now()))
  cid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
  c.execute('INSERT OR IGNORE INTO cmembers VALUES(?,?)',(cid,u['id']))
  c.execute('INSERT OR IGNORE INTO cmembers VALUES(?,?)',(cid,target))
 else:
  cid=r['id']; c.execute('INSERT OR IGNORE INTO cmembers VALUES(?,?)',(cid,u['id'])); c.execute('INSERT OR IGNORE INTO cmembers VALUES(?,?)',(cid,target))
 c.close(); return web.json_response({'channel_id':cid})


async def files(req):
 u=auth(req); c=con()
 if req.method=='POST':
  if not req.headers.get('Content-Type','').lower().startswith('multipart/'): c.close(); raise E(400,'multipart required')
  rd=await req.multipart(); part=None
  async for x in rd:
   if x.name=='file': part=x; break
  if part is None: c.close(); raise E(400,'missing file')
  data=await part.read()
  if len(data)>10*1024*1024: c.close(); raise E(413,'file too large')
  c.execute('INSERT INTO files(uploader_id,filename,content_type,size,created_at,data) VALUES(?,?,?,?,?,?)',(u['id'],part.filename or 'file',part.headers.get('Content-Type','application/octet-stream'),len(data),now(),data))
  fid=c.execute('SELECT last_insert_rowid()').fetchone()[0]; r=c.execute('SELECT id,uploader_id,filename,content_type,size,created_at FROM files WHERE id=?',(fid,)).fetchone(); c.close()
  return web.json_response({'file':dict(r)},status=201)
 fid=int(req.match_info['id']); r=c.execute('SELECT id,uploader_id,filename,content_type,size,created_at,data FROM files WHERE id=?',(fid,)).fetchone()
 if not r: c.close(); raise E(404,'not found')
 if req.path.endswith('/download'):
  data=r['data']; c.close(); return web.Response(body=data,content_type=r['content_type'],headers={'Content-Disposition':f'attachment; filename="{r["filename"]}"'})
 out={k:r[k] for k in ('id','uploader_id','filename','content_type','size','created_at')}; c.close(); return web.json_response({'file':out})


async def groups(req):
 u=auth(req); c=con(); w=wsrow(c,req.match_info['slug']); member=c.execute('SELECT role FROM members WHERE workspace_id=? AND user_id=?',(w['id'],u['id'])).fetchone()
 if not member: c.close(); raise E(403,'forbidden')
 handle=req.match_info.get('handle')
 if req.method=='GET':
  rs=c.execute('SELECT * FROM groups_ WHERE workspace_id=?',(w['id'],)).fetchall(); out=[]
  for r in rs: out.append({'id':r['id'],'handle':r['handle'],'name':r['name'],'member_user_ids':json.loads(r['user_ids'] or '[]')})
  c.close(); return web.json_response({'groups':out})
 if req.method=='POST':
  d=await body(req); h=d.get('handle',''); name=d.get('name',''); ids=d.get('user_ids',[])
  if not isinstance(h,str) or h in ('here','channel') or not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,30}[a-z0-9])?',h) or not isinstance(name,str) or not name or not isinstance(ids,list): c.close(); raise E(400,'invalid')
  if c.execute('SELECT 1 FROM groups_ WHERE workspace_id=? AND handle=?',(w['id'],h)).fetchone(): c.close(); raise E(409,'duplicate')
  unique_ids=list(dict.fromkeys(ids))
  valid=[x['user_id'] for x in c.execute('SELECT user_id FROM members WHERE workspace_id=? AND user_id IN (%s)'%(','.join('?'*len(unique_ids)) if unique_ids else 'NULL'),[w['id']]+unique_ids)] if unique_ids else []
  if len(valid)!=len(unique_ids): c.close(); raise E(400,'invalid members')
  c.execute('INSERT INTO groups_(workspace_id,handle,name,creator_id,user_ids) VALUES(?,?,?,?,?)',(w['id'],h,name,u['id'],json.dumps(valid))); r=c.execute('SELECT * FROM groups_ WHERE id=?',(c.execute('SELECT last_insert_rowid()').fetchone()[0],)).fetchone(); c.close()
  return web.json_response({'group':{'id':r['id'],'handle':r['handle'],'name':r['name'],'member_user_ids':valid}},status=201)
 r=c.execute('SELECT * FROM groups_ WHERE workspace_id=? AND handle=?',(w['id'],handle)).fetchone()
 if not r:
  if req.method=='DELETE': c.close(); return web.json_response({'deleted':True})
  c.close(); raise E(404,'not found')
 if req.method=='DELETE':
  if r['creator_id']!=u['id'] and w['owner_id']!=u['id']: c.close(); raise E(403,'forbidden')
  c.execute('DELETE FROM groups_ WHERE id=?',(r['id'],)); c.close(); return web.json_response({'deleted':True})
 if req.method=='PATCH':
  if r['creator_id']!=u['id'] and w['owner_id']!=u['id']: c.close(); raise E(403,'forbidden')
  d=await body(req); name=d.get('name',r['name']); ids=d.get('user_ids',json.loads(r['user_ids'] or '[]'))
  if not isinstance(name,str) or not name or not isinstance(ids,list): c.close(); raise E(400,'invalid')
  c.execute('UPDATE groups_ SET name=?,user_ids=? WHERE id=?',(name,json.dumps(ids),r['id'])); c.close(); return web.json_response({'group':{'id':r['id'],'handle':r['handle'],'name':name,'member_user_ids':ids}})
 raise E(405,'method')


async def profiles(req):
 u=auth(req); c=con()
 if req.method=='GET':
  try: uid=int(req.match_info['id'])
  except: c.close(); raise E(404,'not found')
  r=c.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone()
  if not r: c.close(); raise E(404,'not found')
  c.close(); return web.json_response({'user':ujson(r)})
 d=await body(req)
 allowed=('display_name','timezone','avatar_url','status_text','status_emoji')
 if 'timezone' in d:
  try:
   if not isinstance(d['timezone'],str) or len(d['timezone'])>64: raise ValueError()
   ZoneInfo(d['timezone'])
  except Exception: raise E(400,'invalid timezone')
 for k in allowed:
  if k in d and (not isinstance(d[k],str) or len(d[k])>(80 if k=='display_name' else 100 if k=='status_text' else 64 if k=='status_emoji' else 1024 if k=='avatar_url' else 250) or (k=='display_name' and not d[k].strip())): raise E(400,'invalid profile')
 c=con(); vals={k:d[k] for k in allowed if k in d}
 if vals:
  sets=','.join(k+'=?' for k in vals); c.execute('UPDATE users SET '+sets+' WHERE id=?',list(vals.values())+[u['id']])
 r=c.execute('SELECT * FROM users WHERE id=?',(u['id'],)).fetchone(); payload={'type':'user.updated','user':ujson(r)}
 c.execute('INSERT INTO broadcasts(payload) VALUES(?)',(json.dumps(payload),)); c.close()
 return web.json_response({'user':ujson(r)})

def initapp():
 app=web.Application(middlewares=[mw],client_max_size=20*1024*1024)
 app.router.add_get('/api/health',health)
 app.router.add_post('/api/auth/register',register)
 app.router.add_post('/api/auth/login',login)
 app.router.add_get('/api/auth/me',me)
 app.router.add_get('/api/users/{id}',profiles)
 app.router.add_patch('/api/users/me',profiles)
 app.router.add_post('/api/dms',dms)
 app.router.add_post('/api/files',files)
 app.router.add_get('/api/files/{id}',files)
 app.router.add_get('/api/files/{id}/download',files)
 app.router.add_route('*','/api/workspaces',workspaces)
 app.router.add_route('*','/api/workspaces/{slug}/groups',groups)
 app.router.add_route('*','/api/workspaces/{slug}/groups/{handle}',groups)
 app.router.add_route('*','/api/workspaces/{slug}',workspace)
 app.router.add_post('/api/workspaces/{slug}/channels',channels)
 app.router.add_route('*','/api/workspaces/{slug}/members',extra)
 app.router.add_route('*','/api/workspaces/{slug}/members/{user_id}',extra)
 app.router.add_route('*','/api/workspaces/{slug}/transfer_ownership',adminextra)
 app.router.add_route('*','/api/workspaces/{slug}/invitations',adminextra)
 app.router.add_route('*','/api/workspaces/{slug}/invitations/{code}',adminextra)
 app.router.add_post('/api/invitations/{code}/accept',acceptinvite)
 app.router.add_route('*','/api/channels/{id}',chan)
 app.router.add_post('/api/channels/{id}/join',join_handler)
 app.router.add_route('*','/api/channels/{id}/leave',extra)
 app.router.add_route('*','/api/channels/{id}/members',extra)
 app.router.add_route('*','/api/channels/{id}/archive',extra)
 app.router.add_route('*','/api/channels/{id}/unarchive',extra)
 app.router.add_route('*','/api/channels/{id}/read',extra)
 app.router.add_route('*','/api/channels/{id}/pins',pinroutes)
 app.router.add_route('*','/api/channels/{id}/messages',msgs)
 app.router.add_route('*','/api/messages/{id}/replies',replies_handler)
 app.router.add_route('*','/api/messages/{id}/pin',msgactions)
 app.router.add_route('*','/api/messages/{id}/reactions',msgactions)
 app.router.add_route('*','/api/messages/{id}/reactions/{emoji}',msgactions)
 app.router.add_route('*','/api/messages/{id}',extra)
 app.router.add_get('/api/search',search)
 app.router.add_get('/api/ws',events_ws)
 async def index(req): return web.FileResponse('/app/static/index.html')
 app.router.add_get('/', index)
 app.router.add_static('/static', '/app/static')
 app.router.add_static('/', '/app/static',show_index=True)
 async def startup(a):
  a['pump_task']=asyncio.create_task(pump(a))
 app.on_startup.append(startup)
 return app

if __name__=='__main__':
 init(); import argparse; p=argparse.ArgumentParser(); p.add_argument('--port',type=int); p.add_argument('--node-id',type=int); a=p.parse_args(); NODE=a.node_id; web.run_app(initapp(),host='0.0.0.0',port=a.port)
