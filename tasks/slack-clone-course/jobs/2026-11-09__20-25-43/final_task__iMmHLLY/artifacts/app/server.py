import asyncio,sqlite3,json,uuid,re,base64,hashlib,os,argparse
from datetime import datetime,timezone
from aiohttp import web,WSMsgType
DB='/app/data/app.db'; clients={}; NODE=0
def now(): return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z')
def db():
 c=sqlite3.connect(DB,timeout=10,isolation_level=None,check_same_thread=False); c.row_factory=sqlite3.Row; c.execute('PRAGMA journal_mode=WAL'); c.execute('PRAGMA busy_timeout=10000'); return c
def init_db():
 os.makedirs('/app/data',exist_ok=True); c=db()
 c.executescript('''CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,username TEXT UNIQUE,password TEXT,display_name TEXT,timezone TEXT DEFAULT "UTC",avatar_url TEXT DEFAULT "",status_text TEXT DEFAULT "",status_emoji TEXT DEFAULT "");
 CREATE TABLE IF NOT EXISTS tokens(token TEXT PRIMARY KEY,user_id INTEGER);
 CREATE TABLE IF NOT EXISTS workspaces(id INTEGER PRIMARY KEY,slug TEXT UNIQUE,name TEXT,owner_id INTEGER,join_mode TEXT DEFAULT "open");
 CREATE TABLE IF NOT EXISTS members(workspace_id INTEGER,user_id INTEGER,role TEXT,PRIMARY KEY(workspace_id,user_id));
 CREATE TABLE IF NOT EXISTS channels(id INTEGER PRIMARY KEY,workspace_id INTEGER,name TEXT,is_private INTEGER DEFAULT 0,is_dm INTEGER DEFAULT 0,topic TEXT DEFAULT "",is_archived INTEGER DEFAULT 0,created_at TEXT,last_event_id INTEGER DEFAULT 0);
 CREATE TABLE IF NOT EXISTS channel_members(channel_id INTEGER,user_id INTEGER,PRIMARY KEY(channel_id,user_id));
 CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY,channel_id INTEGER,author_id INTEGER,body TEXT,parent_id INTEGER,created_at TEXT,edited_at TEXT,deleted INTEGER DEFAULT 0);
 CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT,channel_id INTEGER,event_id INTEGER,payload TEXT);
 CREATE TABLE IF NOT EXISTS reactions(message_id INTEGER,user_id INTEGER,emoji TEXT,PRIMARY KEY(message_id,user_id,emoji));
 CREATE TABLE IF NOT EXISTS reads(user_id INTEGER,channel_id INTEGER,last_read_event_id INTEGER DEFAULT 0,PRIMARY KEY(user_id,channel_id));
 CREATE TABLE IF NOT EXISTS files(id INTEGER PRIMARY KEY,uploader_id INTEGER,filename TEXT,content_type TEXT,size INTEGER,created_at TEXT,data BLOB);
 CREATE TABLE IF NOT EXISTS groupsx(id INTEGER PRIMARY KEY,workspace_id INTEGER,handle TEXT,name TEXT,creator_id INTEGER,user_ids TEXT,UNIQUE(workspace_id,handle)); CREATE TABLE IF NOT EXISTS dm_pairs(user_low INTEGER,user_high INTEGER,channel_id INTEGER,PRIMARY KEY(user_low,user_high)); CREATE TABLE IF NOT EXISTS broadcasts(seq INTEGER PRIMARY KEY AUTOINCREMENT,payload TEXT); CREATE TABLE IF NOT EXISTS message_files(message_id INTEGER,file_id INTEGER UNIQUE); CREATE TABLE IF NOT EXISTS ws_presence(conn_id TEXT PRIMARY KEY,node_id INTEGER,user_id INTEGER);''')
 c.close()
def user(r):
 return {k:r[k] for k in ['id','username','display_name','timezone','avatar_url','status_text','status_emoji']}
def channel(r): return {**dict(r),'is_private':bool(r['is_private']),'is_dm':bool(r['is_dm']),'is_archived':bool(r['is_archived'])}
class E(web.HTTPException):
 def __init__(self,s,m):
  super().__init__(reason=m,text=json.dumps({'error':m}),content_type='application/json'); self.status_code=s
@web.middleware
async def mw(req,handler):
 try:return await handler(req)
 except E as e: return web.json_response({'error':e.reason},status=e.status_code)
 except Exception as e: return web.json_response({'error':str(e)},status=500)
async def body(r):
 try:
  x=await r.json(); return x if isinstance(x,dict) else {}
 except:return {}
def auth(r):
 h=r.headers.get('Authorization',''); t=h[7:] if h.startswith('Bearer ') else r.query.get('token','')
 c=db(); x=c.execute('SELECT u.* FROM tokens t JOIN users u ON u.id=t.user_id WHERE t.token=?',(t,)).fetchone(); c.close()
 if not x: raise E(401,'unauthorized')
 return x
def tok(): return uuid.uuid4().hex+uuid.uuid4().hex
def emit(cid,kind,data):
 c=db(); c.execute('BEGIN IMMEDIATE'); c.execute('UPDATE channels SET last_event_id=last_event_id+1 WHERE id=?',(cid,)); n=c.execute('SELECT last_event_id FROM channels WHERE id=?',(cid,)).fetchone()[0]; p={'type':kind,'event_id':n,'channel_id':cid,**data}; c.execute('INSERT INTO events(channel_id,event_id,payload) VALUES(?,?,?)',(cid,n,json.dumps(p))); c.commit(); c.close(); return p
def msg(c,r):
 d=dict(r); d['author']=user(c.execute('SELECT * FROM users WHERE id=?',(r['author_id'],)).fetchone()); d['parent_id']=r['parent_id']; d['edited_at']=r['edited_at']; d['reply_count']=c.execute('SELECT count(*) FROM messages WHERE parent_id=? AND deleted=0',(r['id'],)).fetchone()[0]; d['files']=[file_json(x) for x in c.execute('SELECT f.* FROM files f JOIN message_files mf ON mf.file_id=f.id WHERE mf.message_id=? ORDER BY f.id',(r['id'],)).fetchall()]; d['mentions']=[]
 rs=c.execute('SELECT emoji,count(*) n FROM reactions WHERE message_id=? GROUP BY emoji',(r['id'],)).fetchall(); d['reactions']=[{'emoji':x['emoji'],'count':x['n'],'user_ids':[z[0] for z in c.execute('SELECT user_id FROM reactions WHERE message_id=? AND emoji=?',(r['id'],x['emoji'])).fetchall()]} for x in rs]; return d
async def health(r): return web.json_response({'status':'ok','node_id':NODE})
async def register(r):
 x=await body(r); u=x.get('username',''); p=x.get('password','')
 if not re.fullmatch(r'[A-Za-z0-9_]{1,32}',u) or len(p)<8: raise E(400,'invalid registration')
 c=db()
 try:c.execute('INSERT INTO users(username,password,display_name) VALUES(?,?,?)',(u,p,x.get('display_name') or u))
 except sqlite3.IntegrityError: raise E(409,'duplicate username')
 uid=c.execute('SELECT last_insert_rowid()').fetchone()[0]; t=tok(); c.execute('INSERT INTO tokens VALUES(?,?)',(t,uid)); z=c.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone(); c.close(); return web.json_response({'user':user(z),'token':t},status=201)
async def login(r):
 x=await body(r); c=db(); z=c.execute('SELECT * FROM users WHERE username=? AND password=?',(x.get('username'),x.get('password'))).fetchone()
 if not z: raise E(401,'invalid credentials')
 t=tok(); c.execute('INSERT INTO tokens VALUES(?,?)',(t,z['id'])); c.close(); return web.json_response({'user':user(z),'token':t})
async def me(r): return web.json_response({'user':user(auth(r))})
async def workspaces(r):
 u=auth(r); c=db()
 if r.method=='POST':
  x=await body(r); slug=x.get('slug','')
  if not re.fullmatch(r'[a-z0-9-]{2,32}',slug) or not x.get('name'): raise E(400,'invalid workspace')
  try:c.execute('INSERT INTO workspaces(slug,name,owner_id) VALUES(?,?,?)',(slug,x['name'],u['id']))
  except sqlite3.IntegrityError: raise E(409,'duplicate slug')
  wid=c.execute('SELECT last_insert_rowid()').fetchone()[0]; c.execute('INSERT INTO members VALUES(?,?,?)',(wid,u['id'],'owner')); c.execute('INSERT INTO channels(workspace_id,name,created_at) VALUES(?,?,?)',(wid,'general',now())); cid=c.execute('SELECT last_insert_rowid()').fetchone()[0]; c.execute('INSERT INTO channel_members VALUES(?,?)',(cid,u['id'])); z=c.execute('SELECT * FROM workspaces WHERE id=?',(wid,)).fetchone(); q=c.execute('SELECT * FROM channels WHERE id=?',(cid,)).fetchone(); c.close(); return web.json_response({'workspace':dict(z),'general_channel':channel(q)},status=201)
 rows=c.execute('SELECT w.* FROM workspaces w JOIN members m ON m.workspace_id=w.id WHERE m.user_id=?',(u['id'],)).fetchall(); c.close(); return web.json_response({'workspaces':[dict(x) for x in rows]})
async def workspace(r):
 u=auth(r); c=db(); w=c.execute('SELECT * FROM workspaces WHERE slug=?',(r.match_info['slug'],)).fetchone()
 if not w: raise E(404,'not found')
 if r.method=='POST':
  x=await body(r); n=x.get('name','')
  if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*',n) or len(n)>32: raise E(400,'invalid channel')
  if c.execute('SELECT 1 FROM channels WHERE workspace_id=? AND name=?',(w['id'],n)).fetchone(): raise E(409,'duplicate channel')
  c.execute('INSERT INTO channels(workspace_id,name,is_private,topic,created_at) VALUES(?,?,?,?,?)',(w['id'],n,int(x.get('is_private',False)),x.get('topic',''),now())); cid=c.execute('SELECT last_insert_rowid()').fetchone()[0]; c.execute('INSERT OR IGNORE INTO channel_members VALUES(?,?)',(cid,u['id'])); q=c.execute('SELECT * FROM channels WHERE id=?',(cid,)).fetchone(); c.close(); return web.json_response({'channel':channel(q)},status=201)
 c.close(); return web.json_response({'workspace':dict(w),'channels':[channel(x) for x in db().execute('SELECT * FROM channels WHERE workspace_id=? AND is_dm=0',(w['id'],)).fetchall()],'read_state':{}})
async def channels(r):
 u=auth(r); c=db(); ch=c.execute('SELECT * FROM channels WHERE id=?',(r.match_info['id'],)).fetchone()
 if not ch: raise E(404,'not found')
 member=c.execute('SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?',(ch['id'],u['id'])).fetchone()
 if not member and ch['is_dm']: c.close(); raise E(403,'forbidden')
 if not member and not ch['is_private']:
  member=c.execute('SELECT 1 FROM members WHERE workspace_id=? AND user_id=?',(ch['workspace_id'],u['id'])).fetchone()
 if not member and r.method in ('GET','POST','PATCH') and not (r.method=='POST' and r.path.endswith('/join') and not ch['is_private']): c.close(); raise E(403,'forbidden')
 if r.method=='POST' and (r.path.endswith('/archive') or r.path.endswith('/unarchive')):
  w=c.execute('SELECT * FROM workspaces WHERE id=?',(ch['workspace_id'],)).fetchone()
  if not w or w['owner_id']!=u['id']: c.close(); raise E(403,'forbidden')
  archived=1 if r.path.endswith('/archive') else 0
  c.execute('UPDATE channels SET is_archived=? WHERE id=?',(archived,ch['id']))
  q=c.execute('SELECT * FROM channels WHERE id=?',(ch['id'],)).fetchone(); c.close()
  emit(ch['id'],'channel.archived' if archived else 'channel.unarchived',{'channel':channel(q)})
  return web.json_response({'channel':channel(q)})
 if r.method=='POST' and r.path.endswith('/join'):
  c.execute('INSERT OR IGNORE INTO channel_members VALUES(?,?)',(ch['id'],u['id'])); c.execute('INSERT OR IGNORE INTO members VALUES(?,?,?)',(ch['workspace_id'],u['id'],'member')); c.close(); return web.json_response({'channel':channel(ch)})
 if r.method=='POST' and r.path.endswith('/leave'):
  c.execute('DELETE FROM channel_members WHERE channel_id=? AND user_id=?',(ch['id'],u['id'])); c.close(); return web.json_response({'channel':channel(ch)})
 if r.method=='PATCH':
  x=await body(r); c.execute('UPDATE channels SET topic=? WHERE id=?',(x.get('topic',''),ch['id'])); q=c.execute('SELECT * FROM channels WHERE id=?',(ch['id'],)).fetchone(); c.close(); emit(ch['id'],'channel.updated',{'channel':channel(q)}); return web.json_response({'channel':channel(q)})
 if r.method=='GET' and r.path.endswith('/messages'):
  rows=c.execute('SELECT * FROM messages WHERE channel_id=? AND parent_id IS NULL AND deleted=0 ORDER BY id DESC',(ch['id'],)).fetchall(); c.close(); return web.json_response({'messages':[msg(db(),x) for x in rows],'next_cursor':None})
 if r.method=='POST' and r.path.endswith('/messages'):
  x=await body(r); b=x.get('body','')
  if not isinstance(b,str) or not b.strip(): raise E(400,'empty body')
  if ch['is_archived'] and b not in ('/unarchive',): c.close(); raise E(423,'channel archived')
  if b.startswith('//'): b=b[1:]
  elif b.startswith('/me'):
   if b=='/me' or not b[3:].strip(): c.close(); raise E(400,'/me requires text')
  elif b.startswith('/shrug'):
   b=(b[6:].strip()+' ¯\\_(ツ)_/¯').strip()
  elif b.startswith('/topic'):
   text=b[6:].strip()
   if len(text)>250: c.close(); raise E(400,'topic too long')
   c.execute('UPDATE channels SET topic=? WHERE id=?',(text,ch['id'])); q=c.execute('SELECT * FROM channels WHERE id=?',(ch['id'],)).fetchone(); c.close(); emit(ch['id'],'channel.updated',{'channel':channel(q)}); return web.json_response({'message':None,'channel':channel(q)},status=201)
  elif b in ('/archive','/unarchive'):
   w=c.execute('SELECT owner_id FROM workspaces WHERE id=?',(ch['workspace_id'],)).fetchone()
   if not w or w['owner_id']!=u['id']: c.close(); raise E(403,'forbidden')
   ar=1 if b=='/archive' else 0; c.execute('UPDATE channels SET is_archived=? WHERE id=?',(ar,ch['id'])); q=c.execute('SELECT * FROM channels WHERE id=?',(ch['id'],)).fetchone(); c.close(); emit(ch['id'],'channel.archived' if ar else 'channel.unarchived',{'channel':channel(q)}); return web.json_response({'message':None,'channel':channel(q)},status=201)
  elif b.startswith('/invite'):
   parts=b.split()
   if len(parts)!=2 or not parts[1].startswith('@'): c.close(); raise E(400,'invalid invite')
   target=c.execute('SELECT * FROM users WHERE username=?',(parts[1][1:],)).fetchone()
   if not target: c.close(); raise E(404,'user not found')
   if not c.execute('SELECT 1 FROM members WHERE workspace_id=? AND user_id=?',(ch['workspace_id'],target['id'])).fetchone(): c.close(); raise E(400,'user is not a workspace member')
   c.execute('INSERT OR IGNORE INTO channel_members VALUES(?,?)',(ch['id'],target['id'])); c.execute('INSERT OR IGNORE INTO members VALUES(?,?,?)',(ch['workspace_id'],target['id'],'member')); c.close(); return web.json_response({'message':None,'invited_user':user(target)},status=201)
  elif b.startswith('/'): c.close(); raise E(400,'unknown command')
  fids=x.get('file_ids',[])
  if not isinstance(fids,list): c.close(); raise E(400,'invalid file_ids')
  for fid in fids:
   if not isinstance(fid,int) or not c.execute('SELECT 1 FROM files WHERE id=? AND uploader_id=?',(fid,u['id'])).fetchone() or c.execute('SELECT 1 FROM message_files WHERE file_id=?',(fid,)).fetchone():
    c.close(); raise E(400,'invalid attachment')
  c.execute('INSERT INTO messages(channel_id,author_id,body,parent_id,created_at) VALUES(?,?,?,?,?)',(ch['id'],u['id'],b,x.get('parent_id'),now())); mid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
  for fid in fids: c.execute('INSERT INTO message_files VALUES(?,?)',(mid,fid))
  z=c.execute('SELECT * FROM messages WHERE id=?',(mid,)).fetchone()
  mentions=set()
  for m in re.findall(r'(?<![A-Za-z0-9_])@([A-Za-z0-9_-]+)',b):
   if m=='channel':
    mentions.update(x['user_id'] for x in c.execute('SELECT user_id FROM channel_members WHERE channel_id=? AND user_id!=?',(ch['id'],u['id'])).fetchall())
   elif m=='here':
    mentions.update(x['user_id'] for x in c.execute('SELECT DISTINCT p.user_id FROM ws_presence p JOIN channel_members cm ON cm.user_id=p.user_id WHERE cm.channel_id=? AND p.user_id!=?',(ch['id'],u['id'])).fetchall())
   else:
    q=c.execute('SELECT id FROM users WHERE username=?',(m,)).fetchone()
    if q and q['id']!=u['id'] and c.execute('SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?',(ch['id'],q['id'])).fetchone(): mentions.add(q['id'])
    g=c.execute('SELECT user_ids FROM groupsx WHERE workspace_id=? AND handle=?',(ch['workspace_id'],m)).fetchone()
    if g:
     for uid in json.loads(g['user_ids']): 
      if uid!=u['id'] and c.execute('SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?',(ch['id'],uid)).fetchone(): mentions.add(uid)
  d=msg(c,z); d['mentions']=list(mentions); c.close(); emit(ch['id'],'message.reply' if x.get('parent_id') else 'message.created',{'message':d}); return web.json_response({'message':d},status=201)
 c.close(); return web.json_response({'channel':channel(ch)})

def file_json(x):
 return {'id':x['id'],'uploader_id':x['uploader_id'],'filename':x['filename'],'content_type':x['content_type'],'size':x['size'],'created_at':x['created_at']}
async def files_route(r):
 u=auth(r); c=db()
 if r.method=='POST':
  try: form=await r.multipart()
  except: c.close(); raise E(400,'invalid multipart')
  part=None
  async for q in form:
   if q.name=='file': part=q; break
  if part is None: c.close(); raise E(400,'missing file')
  data=await part.read()
  if len(data)>10*1024*1024: c.close(); raise E(413,'file too large')
  name=part.filename or 'file'; typ=part.headers.get('Content-Type','application/octet-stream')
  c.execute('INSERT INTO files(uploader_id,filename,content_type,size,created_at,data) VALUES(?,?,?,?,?,?)',(u['id'],name,typ,len(data),now(),data))
  x=c.execute('SELECT * FROM files WHERE id=?',(c.execute('SELECT last_insert_rowid()').fetchone()[0],)).fetchone(); c.close()
  return web.json_response({'file':file_json(x)},status=201)
 try: fid=int(r.match_info['id'])
 except: c.close(); raise E(404,'not found')
 x=c.execute('SELECT * FROM files WHERE id=?',(fid,)).fetchone()
 if not x: c.close(); raise E(404,'not found')
 if r.path.endswith('/download'):
  data=x['data']; typ=x['content_type']; name=x['filename']; c.close()
  return web.Response(body=data,content_type=typ,headers={'Content-Disposition':'attachment; filename="'+name.replace('"','')+'"'} )
 c.close(); return web.json_response({'file':file_json(x)})

def group_obj(x):
 return {'id':x['id'],'handle':x['handle'],'name':x['name'],'member_user_ids':json.loads(x['user_ids'] or '[]')}
async def groups_route(r):
 u=auth(r); c=db(); w=c.execute('SELECT * FROM workspaces WHERE slug=?',(r.match_info['slug'],)).fetchone()
 if not w: c.close(); raise E(404,'not found')
 if not c.execute('SELECT 1 FROM members WHERE workspace_id=? AND user_id=?',(w['id'],u['id'])).fetchone(): c.close(); raise E(403,'forbidden')
 h=r.match_info.get('handle')
 if r.method=='GET':
  rows=c.execute('SELECT * FROM groupsx WHERE workspace_id=? ORDER BY id',(w['id'],)).fetchall(); c.close(); return web.json_response({'groups':[group_obj(x) for x in rows]})
 if r.method=='POST':
  x=await body(r); handle=x.get('handle',''); name=x.get('name',''); ids=x.get('user_ids',[])
  if not isinstance(handle,str) or not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*',handle) or handle in ('here','channel') or not name or not isinstance(ids,list): c.close(); raise E(400,'invalid group')
  for uid in ids:
   if not isinstance(uid,int) or not c.execute('SELECT 1 FROM members WHERE workspace_id=? AND user_id=?',(w['id'],uid)).fetchone(): c.close(); raise E(400,'user is not a workspace member')
  try: c.execute('INSERT INTO groupsx(workspace_id,handle,name,creator_id,user_ids) VALUES(?,?,?,?,?)',(w['id'],handle,name,u['id'],json.dumps(ids)))
  except sqlite3.IntegrityError: c.close(); raise E(409,'duplicate handle')
  z=c.execute('SELECT * FROM groupsx WHERE id=?',(c.execute('SELECT last_insert_rowid()').fetchone()[0],)).fetchone(); c.close(); return web.json_response({'group':group_obj(z)},status=201)
 row=c.execute('SELECT * FROM groupsx WHERE workspace_id=? AND handle=?',(w['id'],h)).fetchone()
 if not row:
  if r.method=='DELETE': c.close(); return web.json_response({'deleted':True})
  c.close(); raise E(404,'not found')
 owner=w['owner_id']==u['id']
 if row['creator_id']!=u['id'] and not owner: c.close(); raise E(403,'forbidden')
 if r.method=='DELETE': c.execute('DELETE FROM groupsx WHERE id=?',(row['id'],)); c.close(); return web.json_response({'deleted':True})
 x=await body(r); name=x.get('name',row['name']); ids=x.get('user_ids',json.loads(row['user_ids']))
 if not isinstance(name,str) or not name or not isinstance(ids,list): c.close(); raise E(400,'invalid group')
 for uid in ids:
  if not isinstance(uid,int) or not c.execute('SELECT 1 FROM members WHERE workspace_id=? AND user_id=?',(w['id'],uid)).fetchone(): c.close(); raise E(400,'user is not a workspace member')
 c.execute('UPDATE groupsx SET name=?,user_ids=? WHERE id=?',(name,json.dumps(ids),row['id'])); z=c.execute('SELECT * FROM groupsx WHERE id=?',(row['id'],)).fetchone(); c.close(); return web.json_response({'group':group_obj(z)})
async def read_state(r):
 u=auth(r); c=db(); cid=int(r.match_info['id'])
 ch=c.execute('SELECT * FROM channels WHERE id=?',(cid,)).fetchone()
 if not ch: c.close(); raise E(404,'not found')
 if not c.execute('SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?',(cid,u['id'])).fetchone(): c.close(); raise E(403,'forbidden')
 q=c.execute('SELECT last_read_event_id FROM reads WHERE user_id=? AND channel_id=?',(u['id'],cid)).fetchone()
 last=q['last_event_id'] if q else 0
 if r.method=='POST':
  x=await body(r); n=x.get('last_read_event_id',last)
  if not isinstance(n,int): c.close(); raise E(400,'invalid event id')
  last=max(last,n); c.execute('INSERT OR REPLACE INTO reads VALUES(?,?,?)',(u['id'],cid,last))
 head=c.execute('SELECT last_event_id FROM channels WHERE id=?',(cid,)).fetchone()['last_event_id']; unread=c.execute('SELECT count(*) FROM events WHERE channel_id=? AND event_id>?',(cid,last)).fetchone()[0]
 rows=c.execute('SELECT body,author_id FROM messages WHERE channel_id=? AND deleted=0 AND author_id!=?',(cid,u['id'])).fetchall()
 mention_count=0
 groups=[]
 if ch['workspace_id']:
  for gx in c.execute('SELECT handle,user_ids FROM groupsx WHERE workspace_id=?',(ch['workspace_id'],)).fetchall():
   try:
    if u['id'] in json.loads(gx['user_ids'] or '[]'): groups.append(gx['handle'])
   except: pass
 for row in rows:
  text=row['body']
  hit=bool(re.search(r'(?<![A-Za-z0-9_])@'+re.escape(u['username'])+r'(?![A-Za-z0-9_])',text))
  hit=hit or bool(re.search(r'(?<![A-Za-z0-9_])@(channel|here)(?![A-Za-z0-9_])',text))
  hit=hit or any(bool(re.search(r'(?<![A-Za-z0-9_])@'+re.escape(g)+r'(?![A-Za-z0-9_])',text)) for g in groups)
  if hit: mention_count+=1
 c.close(); return web.json_response({'read_state':{'channel_id':cid,'last_read_event_id':last,'unread_count':unread,'mention_count':mention_count}})

async def profile(r):
 u=auth(r); c=db()
 if r.method=='GET':
  try: uid=int(r.match_info['id'])
  except: c.close(); raise E(404,'not found')
  z=c.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone()
  c.close()
  if not z: raise E(404,'not found')
  return web.json_response({'user':user(z)})
 x=await body(r); fields=['display_name','timezone','avatar_url','status_text','status_emoji']; vals={}
 for k in fields:
  if k in x:
   if not isinstance(x[k],str): raise E(400,'invalid profile')
   lim={'display_name':80,'status_text':100,'status_emoji':64,'avatar_url':500}.get(k,100)
   if len(x[k])>lim or (k=='display_name' and not x[k]): raise E(400,'invalid profile')
   vals[k]=x[k]
 if 'timezone' in vals:
  import zoneinfo
  try: zoneinfo.ZoneInfo(vals['timezone'])
  except: raise E(400,'invalid timezone')
 if vals:
  c.execute('UPDATE users SET '+','.join(k+'=?' for k in vals)+' WHERE id=?',(*vals.values(),u['id']))
 z=c.execute('SELECT * FROM users WHERE id=?',(u['id'],)).fetchone(); payload=json.dumps({'type':'user.updated','user':user(z)}); c.execute('INSERT INTO broadcasts(payload) VALUES(?)',(payload,)); c.close()
 return web.json_response({'user':user(z)})

async def dms(r):
 u=auth(r); x=await body(r); other=x.get('user_id')
 if not isinstance(other,int): raise E(400,'invalid user_id')
 c=db(); target=c.execute('SELECT * FROM users WHERE id=?',(other,)).fetchone()
 if not target: c.close(); raise E(404,'user not found')
 if other==u['id']: c.close(); raise E(400,'invalid user_id')
 lo,hi=sorted((u['id'],other)); pair=c.execute('SELECT channel_id FROM dm_pairs WHERE user_low=? AND user_high=?',(lo,hi)).fetchone()
 if pair: cid=pair['channel_id']
 else:
  c.execute('INSERT INTO channels(name,is_private,is_dm,created_at) VALUES(?,?,?,?)',(f'dm-{lo}-{hi}',1,1,now()))
  cid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
  c.execute('INSERT INTO dm_pairs VALUES(?,?,?)',(lo,hi,cid))
  c.execute('INSERT INTO channel_members VALUES(?,?)',(cid,lo)); c.execute('INSERT INTO channel_members VALUES(?,?)',(cid,hi))
 c.close(); return web.json_response({'channel_id':cid})

async def message_route(r):
 u=auth(r); c=db(); z=c.execute('SELECT * FROM messages WHERE id=?',(r.match_info['id'],)).fetchone()
 if not z: raise E(404,'not found')
 ch=c.execute('SELECT * FROM channels WHERE id=?',(z['channel_id'],)).fetchone()
 owner=c.execute('SELECT owner_id FROM workspaces WHERE id=?',(ch['workspace_id'],)).fetchone() if ch['workspace_id'] else None
 if r.path.startswith('/api/messages/') and ('/reactions' in r.path) and z['deleted']: c.close(); raise E(404,'not found')
 if r.method=='PATCH':
  if z['author_id']!=u['id']: c.close(); raise E(403,'forbidden')
  if z['deleted']: c.close(); raise E(409,'message deleted')
  if ch['is_archived']: c.close(); raise E(423,'channel archived')
  x=await body(r); b=x.get('body')
  if not isinstance(b,str) or not b.strip(): c.close(); raise E(400,'empty body')
  c.execute('UPDATE messages SET body=?,edited_at=? WHERE id=?',(b,now(),z['id'])); q=c.execute('SELECT * FROM messages WHERE id=?',(z['id'],)).fetchone(); c.close(); d=msg(db(),q); emit(z['channel_id'],'message.updated',{'message':d}); return web.json_response({'message':d})
 if r.method=='DELETE' and '/reactions/' not in r.path:
  if z['deleted']: c.close(); return web.json_response({'deleted':True})
  if z['author_id']!=u['id'] and (not owner or owner['owner_id']!=u['id']): c.close(); raise E(403,'forbidden')
  c.execute('UPDATE messages SET deleted=1 WHERE id=?',(z['id'],)); c.close(); emit(z['channel_id'],'message.deleted',{'message_id':z['id']}); return web.json_response({'deleted':True})
 if r.path.startswith('/api/messages/') and ('/reactions' in r.path):
  ch=c.execute('SELECT * FROM channels WHERE id=?',(z['channel_id'],)).fetchone()
  allowed=c.execute('SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?',(z['channel_id'],u['id'])).fetchone()
  if not allowed and ch['is_dm']==0 and not ch['is_private']:
   allowed=c.execute('SELECT 1 FROM members WHERE workspace_id=? AND user_id=?',(ch['workspace_id'],u['id'])).fetchone()
  if not allowed: c.close(); raise E(403,'forbidden')
  if ch['is_archived']: c.close(); raise E(423,'channel archived')
  if r.method=='POST':
   x=await body(r); emoji=x.get('emoji')
   if not isinstance(emoji,str) or not emoji or len(emoji)>64: c.close(); raise E(400,'invalid emoji')
   before=c.execute('SELECT 1 FROM reactions WHERE message_id=? AND user_id=? AND emoji=?',(z['id'],u['id'],emoji)).fetchone()
   c.execute('INSERT OR IGNORE INTO reactions VALUES(?,?,?)',(z['id'],u['id'],emoji)); changed=before is None
  else:
   emoji=r.match_info.get('emoji','')
   before=c.execute('SELECT 1 FROM reactions WHERE message_id=? AND user_id=? AND emoji=?',(z['id'],u['id'],emoji)).fetchone()
   c.execute('DELETE FROM reactions WHERE message_id=? AND user_id=? AND emoji=?',(z['id'],u['id'],emoji)); changed=before is not None
  reactions=msg(c,z)['reactions']; c.close()
  if changed: emit(z['channel_id'],'reaction.added' if r.method=='POST' else 'reaction.removed',{'message_id':z['id'],'emoji':emoji,'user_id':u['id'],'reactions':reactions})
  return web.json_response({'reactions':reactions})
 if r.method=='GET' and r.path.endswith('/replies'):
  rows=c.execute('SELECT * FROM messages WHERE parent_id=? AND deleted=0 ORDER BY id',(z['id'],)).fetchall(); c.close(); return web.json_response({'replies':[msg(db(),x) for x in rows],'next_cursor':None})
 c.close(); return web.json_response({'message':msg(db(),z)})
async def ws(r):
 u=auth(r); w=web.WebSocketResponse(); await w.prepare(r); cid=str(uuid.uuid4()); c=db(); c.execute('INSERT INTO ws_presence VALUES(?,?,?)',(cid,NODE,u['id'])); c.close(); subs=set(); clients[w]=subs
 try:
  async for m in w:
   if m.type==WSMsgType.TEXT:
    x=json.loads(m.data); cid=x.get('channel_id')
    if x.get('type')=='subscribe':
     subs.add(cid); c=db(); h=c.execute('SELECT last_event_id FROM channels WHERE id=?',(cid,)).fetchone(); c.close(); await w.send_json({'type':'subscribed','channel_id':cid,'head_event_id':h[0] if h else 0})
    elif x.get('type')=='resume':
     c=db(); rows=c.execute('SELECT payload FROM events WHERE channel_id=? AND event_id>? ORDER BY event_id',(cid,x.get('since_event_id',0))).fetchall(); h=c.execute('SELECT last_event_id FROM channels WHERE id=?',(cid,)).fetchone()[0]; c.close()
     for q in rows: await w.send_str(q[0])
     await w.send_json({'type':'resumed','channel_id':cid,'head_event_id':h})
 finally:
  clients.pop(w,None); c=db(); c.execute('DELETE FROM ws_presence WHERE conn_id=?',(cid,)); c.close()
 return w
async def pump():
 c=db(); seen=c.execute('SELECT COALESCE(MAX(seq),0) FROM events').fetchone()[0]; bseen=c.execute('SELECT COALESCE(MAX(seq),0) FROM broadcasts').fetchone()[0]; c.close()
 while True:
  await asyncio.sleep(.05); c=db(); rows=c.execute('SELECT seq,payload FROM events WHERE seq>? ORDER BY seq',(seen,)).fetchall(); grows=c.execute('SELECT seq,payload FROM broadcasts WHERE seq>? ORDER BY seq',(bseen,)).fetchall(); c.close()
  for q in rows:
   seen=q['seq']; p=json.loads(q['payload'])
   for w,subs in list(clients.items()):
    if p.get('channel_id') not in subs: continue
    try: await w.send_str(q['payload'])
    except: clients.pop(w,None)
  for q in grows:
   bseen=q['seq']
   for w in list(clients):
    try: await w.send_str(q['payload'])
    except: clients.pop(w,None)
def app():
 a=web.Application(middlewares=[mw],client_max_size=20*1024*1024)
 a.router.add_get('/api/health',health); a.router.add_route('*','/api/files',files_route); a.router.add_route('*','/api/files/{id}',files_route); a.router.add_route('*','/api/files/{id}/download',files_route); a.router.add_route('*','/api/users/me',profile); a.router.add_route('*','/api/users/{id}',profile); a.router.add_post('/api/dms',dms); a.router.add_post('/api/auth/register',register); a.router.add_post('/api/auth/login',login); a.router.add_get('/api/auth/me',me)
 a.router.add_route('*','/api/workspaces',workspaces); a.router.add_route('*','/api/workspaces/{slug}/groups',groups_route); a.router.add_route('*','/api/workspaces/{slug}/groups/{handle}',groups_route); a.router.add_route('*','/api/workspaces/{slug}',workspace); a.router.add_route('*','/api/workspaces/{slug}/channels',workspace)
 a.router.add_route('*','/api/channels/{id}/read',read_state); a.router.add_route('*','/api/channels/{id}',channels); a.router.add_route('*','/api/channels/{id}/archive',channels); a.router.add_route('*','/api/channels/{id}/unarchive',channels); a.router.add_route('*','/api/channels/{id}/join',channels); a.router.add_route('*','/api/channels/{id}/leave',channels); a.router.add_route('*','/api/channels/{id}/messages',channels)
 a.router.add_route('*','/api/messages/{id}/reactions/{emoji}',message_route); a.router.add_route('*','/api/messages/{id}/reactions',message_route); a.router.add_route('*','/api/messages/{id}/replies',message_route); a.router.add_route('*','/api/messages/{id}',message_route); a.router.add_get('/api/ws',ws)
 a.router.add_static('/static/','/app/static')
 async def home(r): return web.FileResponse('/app/static/index.html')
 a.router.add_get('/',home)
 async def startup(app): app['pump_task']=asyncio.create_task(pump())
 a.on_startup.append(startup); return a
if __name__=='__main__':
 p=argparse.ArgumentParser(); p.add_argument('--port',type=int); p.add_argument('--node-id',type=int); x=p.parse_args(); NODE=x.node_id; init_db(); web.run_app(app(),host='0.0.0.0',port=x.port)
