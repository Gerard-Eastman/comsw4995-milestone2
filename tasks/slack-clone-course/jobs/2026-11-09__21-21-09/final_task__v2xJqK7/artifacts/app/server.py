import os,sys,json,sqlite3,secrets,hashlib,re,base64,struct,threading,time,urllib.parse,datetime,socket,cgi
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
DB='/app/data/huddle.db'; os.makedirs('/app/data',exist_ok=True)
NODE=int(os.environ.get('NODE_ID','0')); PORT=8000+NODE
lock=threading.RLock(); clients=[]; ws_users={}; schema='''CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,username TEXT UNIQUE,password TEXT,display_name TEXT,timezone TEXT,avatar_url TEXT,status_text TEXT,status_emoji TEXT);
CREATE TABLE IF NOT EXISTS tokens(token TEXT PRIMARY KEY,user_id INTEGER);
CREATE TABLE IF NOT EXISTS workspaces(id INTEGER PRIMARY KEY,slug TEXT UNIQUE,name TEXT,owner_id INTEGER,join_mode TEXT);
CREATE TABLE IF NOT EXISTS members(workspace_id INTEGER,user_id INTEGER,role TEXT,PRIMARY KEY(workspace_id,user_id));
CREATE TABLE IF NOT EXISTS channels(id INTEGER PRIMARY KEY,workspace_id INTEGER,name TEXT,is_private INTEGER DEFAULT 0,is_dm INTEGER DEFAULT 0,topic TEXT DEFAULT '',archived INTEGER DEFAULT 0,UNIQUE(workspace_id,name));
CREATE TABLE IF NOT EXISTS cmembers(channel_id INTEGER,user_id INTEGER,PRIMARY KEY(channel_id,user_id));
CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY,channel_id INTEGER,author_id INTEGER,body TEXT,parent_id INTEGER,created TEXT,edited TEXT,deleted INTEGER DEFAULT 0,event_id INTEGER);
CREATE TABLE IF NOT EXISTS reactions(message_id INTEGER,user_id INTEGER,emoji TEXT,PRIMARY KEY(message_id,user_id,emoji));
CREATE TABLE IF NOT EXISTS dms(a INTEGER,b INTEGER,channel_id INTEGER,UNIQUE(a,b));
CREATE TABLE IF NOT EXISTS files(id INTEGER PRIMARY KEY,uploader_id INTEGER,filename TEXT,content_type TEXT,size INTEGER,data BLOB,created TEXT);
CREATE TABLE IF NOT EXISTS events(channel_id INTEGER,event_id INTEGER,type TEXT,payload TEXT,PRIMARY KEY(channel_id,event_id));
CREATE TABLE IF NOT EXISTS attachments(message_id INTEGER,file_id INTEGER UNIQUE);
CREATE TABLE IF NOT EXISTS user_updates(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,payload TEXT);
CREATE TABLE IF NOT EXISTS groups(id INTEGER PRIMARY KEY AUTOINCREMENT,workspace_id INTEGER,handle TEXT UNIQUE,name TEXT,creator_id INTEGER);
CREATE TABLE IF NOT EXISTS group_members(group_id INTEGER,user_id INTEGER,PRIMARY KEY(group_id,user_id));
CREATE TABLE IF NOT EXISTS ws_presence(user_id INTEGER PRIMARY KEY,seen TEXT);'''
def db():
 c=sqlite3.connect(DB,timeout=20,check_same_thread=False,isolation_level=None); c.row_factory=sqlite3.Row; c.execute('PRAGMA busy_timeout=20000'); return c
_init=db()
try:
 _init.execute('SELECT 1 FROM users LIMIT 1')
except sqlite3.OperationalError:
 _init.executescript(schema)
 _init.commit()
_init.close()
def now(): return datetime.datetime.now(datetime.timezone.utc).isoformat().replace('+00:00','Z')
def obj(r): return dict(r) if r else None
def user(r):
 d=obj(r); 
 if d: d.pop('password',None)
 return d
def emit(ch,kind,payload):
 with lock:
  c=db(); c.execute('CREATE TABLE IF NOT EXISTS seq(channel_id INTEGER PRIMARY KEY,n INTEGER)')
  c.execute('INSERT INTO seq(channel_id,n) VALUES(?,?) ON CONFLICT(channel_id) DO UPDATE SET n=n+1',(ch,1))
  eid=c.execute('SELECT n FROM seq WHERE channel_id=?',(ch,)).fetchone()[0]
  c.execute('INSERT OR REPLACE INTO events VALUES(?,?,?,?)',(ch,eid,kind,json.dumps(payload))); c.commit(); c.close()
 return eid
def ws_send(s,d):
 b=json.dumps(d,separators=(',',':')).encode(); n=len(b)
 if n<126: h=bytes([0x81,n])
 elif n<65536:h=bytes([0x81,126])+struct.pack('>H',n)
 else:h=bytes([0x81,127])+struct.pack('>Q',n)
 s.sendall(h+b)
def ws_recv(s):
 h=s.recv(2)
 if len(h)<2:return None
 n=h[1]&127; masked=h[1]&128
 if n==126:n=struct.unpack('>H',s.recv(2))[0]
 elif n==127:n=struct.unpack('>Q',s.recv(8))[0]
 key=s.recv(4) if masked else b''; b=s.recv(n); 
 if masked:b=bytes(x^key[i%4] for i,x in enumerate(b))
 return json.loads(b.decode()) if b else None
class H(BaseHTTPRequestHandler):
 protocol_version='HTTP/1.1'
 protocol_version='HTTP/1.1'
 def log_message(self,*a):pass
 def sendj(self,status,d,headers=None):
  b=json.dumps(d).encode(); self.send_response(status); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(b))); self.send_header('Connection','close')
  for k,v in (headers or {}).items():self.send_header(k,v)
  self.end_headers(); self.wfile.write(b); self.close_connection=True
 def body(self):
  n=int(self.headers.get('Content-Length',0)); return json.loads(self.rfile.read(n) or b'{}')
 def auth(self):
  t=self.headers.get('Authorization','').replace('Bearer ',''); c=db(); r=c.execute('SELECT u.* FROM tokens t JOIN users u ON u.id=t.user_id WHERE t.token=?',(t,)).fetchone(); c.close(); return r
 def route(self):
  return urllib.parse.urlparse(self.path).path.split('/')
 def do_GET(self):
  p=self.route()
  if self.path=='/api/health':return self.sendj(200,{'status':'ok','node_id':NODE})
  if self.path in ('/','/app.js','/static/app.js','/static/style.css'): return self.html()
  u=self.auth()
  if p[1]=='api' and p[2]=='ws': return self.websocket()
  if not u:return self.sendj(401,{'error':'unauthorized'})
  c=db()
  if p[2]=='auth' and p[3]=='me':return self.sendj(200,{'user':user(u)})
  if p[2]=='users':
   r=c.execute('SELECT * FROM users WHERE id=?',(p[3] if p[3].isdigit() else -1,)).fetchone(); return self.sendj(200,{'user':user(r)}) if r else self.sendj(404,{})
  if p[2]=='files' and len(p)>=4:
   try: fid=int(p[3])
   except: return self.sendj(404,{})
   r=c.execute('SELECT id,uploader_id,filename,content_type,size,created,created AS created_at FROM files WHERE id=?',(fid,)).fetchone()
   if not r:return self.sendj(404,{})
   if len(p)>=5 and p[4]=='download':
    raw=c.execute('SELECT data FROM files WHERE id=?',(fid,)).fetchone()[0]; self.send_response(200); self.send_header('Content-Type',r['content_type']); self.send_header('Content-Disposition','attachment; filename="'+r['filename']+'"'); self.send_header('Content-Length',str(len(raw))); self.end_headers(); self.wfile.write(raw); return
   return self.sendj(200,{'file':obj(r)})
  if p[2]=='workspaces' and len(p)>=5 and p[4]=='groups':
   w=c.execute('SELECT * FROM workspaces WHERE slug=?',(p[3],)).fetchone()
   if not w or not c.execute('SELECT 1 FROM members WHERE workspace_id=? AND user_id=?',(w['id'],u['id'])).fetchone():return self.sendj(403 if w else 404,{})
   rs=c.execute('SELECT * FROM groups WHERE workspace_id=?',(w['id'],)).fetchall()
   gs=[]
   for g in rs:
    x=obj(g); x['member_user_ids']=[r[0] for r in c.execute('SELECT user_id FROM group_members WHERE group_id=?',(g['id'],))]; gs.append(x)
   return self.sendj(200,{'groups':gs})
  if p[2]=='workspaces' and len(p)==3:
   rs=c.execute('SELECT w.* FROM workspaces w JOIN members m ON m.workspace_id=w.id WHERE m.user_id=?',(u['id'],)).fetchall(); return self.sendj(200,{'workspaces':[obj(x) for x in rs]})
  if p[2]=='workspaces' and len(p)>=4:
   w=c.execute('SELECT * FROM workspaces WHERE slug=?',(p[3],)).fetchone()
   if not w:return self.sendj(404,{})
   cs=c.execute('SELECT * FROM channels WHERE workspace_id=? AND archived=0 AND is_dm=0',(w['id'],)).fetchall(); return self.sendj(200,{'workspace':obj(w),'channels':[obj(x) for x in cs],'read_state':{}})
  if p[2]=='channels' and len(p)>=5 and p[4]=='read':
   cid=int(p[3]); unread=c.execute('SELECT count(*) FROM messages WHERE channel_id=? AND deleted=0 AND author_id<>?',(cid,u['id'])).fetchone()[0]
   un=c.execute('SELECT username FROM users WHERE id=?',(u['id'],)).fetchone()[0]
   mention=c.execute("SELECT count(*) FROM messages WHERE channel_id=? AND deleted=0 AND author_id<>? AND (body LIKE ? OR body LIKE ?)",(cid,u['id'],'%@'+un+'%','%@channel%')).fetchone()[0]
   return self.sendj(200,{'read_state':{'channel_id':cid,'last_read_event_id':0,'unread_count':unread,'mention_count':mention}})
  if p[2]=='channels' and len(p)>=4:
   cid=int(p[3]); ch=c.execute('SELECT * FROM channels WHERE id=?',(cid,)).fetchone()
   if not ch:return self.sendj(404,{})
   if not c.execute('SELECT 1 FROM cmembers WHERE channel_id=? AND user_id=?',(cid,u['id'])).fetchone():return self.sendj(403,{})
   if p[4]=='messages':
    rs=c.execute('SELECT * FROM messages WHERE channel_id=? AND deleted=0 ORDER BY id DESC',(cid,)).fetchall(); out=[]
    for m in rs:
     d=obj(m); d['edited_at']=d.get('edited'); d['author']=user(c.execute('SELECT * FROM users WHERE id=?',(m['author_id'],)).fetchone()); d['reply_count']=c.execute('SELECT count(*) FROM messages WHERE parent_id=? AND deleted=0',(m['id'],)).fetchone()[0]; d['reactions']=self.reacts(c,m['id']); d['files']=[obj(x) for x in c.execute('SELECT f.id,f.uploader_id,f.filename,f.content_type,f.size,f.created,f.created AS created_at FROM files f JOIN attachments a ON a.file_id=f.id WHERE a.message_id=?',(m['id'],)).fetchall()]; out.append(d)
    return self.sendj(200,{'messages':out,'next_cursor':None})
   if p[4]=='members': return self.sendj(200,{'members':[user(x) for x in c.execute('SELECT u.* FROM users u JOIN cmembers m ON m.user_id=u.id WHERE m.channel_id=?',(cid,)).fetchall()]})
  if p[2]=='messages' and len(p)>=4:
   m=c.execute('SELECT * FROM messages WHERE id=?',(p[3],)).fetchone()
   if not m:return self.sendj(404,{})
   if p[4]=='replies': return self.sendj(200,{'replies':[obj(x) for x in c.execute('SELECT * FROM messages WHERE parent_id=? AND deleted=0 ORDER BY id',(p[3],)).fetchall()] ,'next_cursor':None})
   if p[4]=='reactions':return self.sendj(200,{'reactions':self.reacts(c,m['id'])})
  return self.sendj(404,{})
 def reacts(self,c,mid):
  out=[]
  for e in c.execute('SELECT emoji,count(*) n FROM reactions WHERE message_id=? GROUP BY emoji',(mid,)):
   out.append({'emoji':e['emoji'],'count':e['n'],'user_ids':[x[0] for x in c.execute('SELECT user_id FROM reactions WHERE message_id=? AND emoji=?',(mid,e['emoji']))]})
  return out
 def do_POST(self):
  p=self.route(); u=self.auth()
  if p[1:3]==['api','auth'] and p[3]=='register':
   d=self.body(); 
   if not re.fullmatch(r'[A-Za-z0-9_]+',d.get('username','')) or len(d.get('password',''))<8:return self.sendj(400,{})
   c=db()
   for attempt in range(8):
    try:
     c.execute('INSERT INTO users(username,password,display_name,timezone,avatar_url,status_text,status_emoji) VALUES(?,?,?,?,?,?,?)',(d['username'],d['password'],d.get('display_name',d['username']),'UTC','','','')); c.commit()
     break
    except sqlite3.IntegrityError:
     c.rollback()
     return self.sendj(409,{})
    except sqlite3.OperationalError:
     c.rollback(); time.sleep(.08)
   else:
    return self.sendj(503,{})
   return self.login(c,d['username'],d['password'],201)
  if p[1:3]==['api','auth'] and p[3]=='login':
   d=self.body(); c=db(); return self.login(c,d.get('username'),d.get('password'))
  if not u:return self.sendj(401,{})
  p=self.route()
  if p[2]=='files' and len(p)==3:
   n=int(self.headers.get('Content-Length','0'))
   raw=self.rfile.read(n)
   if n>10*1024*1024+2000:return self.sendj(413,{})
   ct=self.headers.get('Content-Type','')
   if 'multipart/form-data' not in ct or 'boundary=' not in ct:return self.sendj(400,{})
   boundary=ct.split('boundary=',1)[1].strip().strip('"').encode()
   item=None
   for part in raw.split(b'--'+boundary):
    if b'Content-Disposition:' in part and b'name="file"' in part:
     item=part; break
   if not item:return self.sendj(400,{})
   sep=bytes([13,10,13,10])
   if sep not in item:return self.sendj(400,{})
   hdr,data=item.split(sep,1)
   data=data.rstrip(bytes([13,10,45]))
   md=re.search(b'filename="([^"]*)"',hdr)
   if not md:return self.sendj(400,{})
   ctype='application/octet-stream'
   for hl in hdr.split(bytes([13,10])):
    if hl.lower().startswith(b'content-type:'):ctype=hl.split(b':',1)[1].strip().decode('utf-8','replace')
   if len(data)>10*1024*1024:return self.sendj(413,{})
   filename=md.group(1).decode('utf-8','replace')
   c=db(); c.execute('INSERT INTO files(uploader_id,filename,content_type,size,data,created) VALUES(?,?,?,?,?,?)',(u['id'],filename,ctype,len(data),data,now())); fid=c.execute('SELECT last_insert_rowid()').fetchone()[0]; c.commit()
   return self.sendj(201,{'file':obj(c.execute('SELECT id,uploader_id,filename,content_type,size,created,created AS created_at FROM files WHERE id=?',(fid,)).fetchone())})
  c=db(); d=self.body()
  if p[2]=='dms':
   if 'user_id' not in d or not isinstance(d.get('user_id'),int): return self.sendj(400,{})
   other=c.execute('SELECT * FROM users WHERE id=?',(d['user_id'],)).fetchone()
   if not other:return self.sendj(404,{})
   a,b=sorted((u['id'],d['user_id']))
   r=c.execute('SELECT channel_id FROM dms WHERE a=? AND b=?',(a,b)).fetchone()
   if r:return self.sendj(200,{'channel_id':r['channel_id']})
   c.execute('INSERT INTO channels(workspace_id,name,is_dm,topic) VALUES(NULL,?,?,?)',(f'dm-{a}-{b}',1,''))
   cid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
   c.execute('INSERT INTO dms(a,b,channel_id) VALUES(?,?,?)',(a,b,cid))
   c.execute('INSERT INTO cmembers VALUES(?,?)',(cid,a)); c.execute('INSERT INTO cmembers VALUES(?,?)',(cid,b)); c.commit()
   return self.sendj(200,{'channel_id':cid})
  if p[2]=='workspaces' and len(p)>=5 and p[4]=='groups':
   w=c.execute('SELECT * FROM workspaces WHERE slug=?',(p[3],)).fetchone()
   if not w:return self.sendj(404,{})
   if not c.execute('SELECT 1 FROM members WHERE workspace_id=? AND user_id=?',(w['id'],u['id'])).fetchone():return self.sendj(403,{})
   h=d.get('handle',''); name=d.get('name',''); ids=d.get('user_ids',[])
   if not re.fullmatch(r'[a-z][a-z0-9-]{0,31}',h) or h in ('here','channel') or not name or not isinstance(ids,list):return self.sendj(400,{})
   if c.execute('SELECT 1 FROM groups WHERE handle=?',(h,)).fetchone():return self.sendj(409,{})
   for uid in ids:
    if not c.execute('SELECT 1 FROM members WHERE workspace_id=? AND user_id=?',(w['id'],uid)).fetchone():return self.sendj(400,{})
   c.execute('INSERT INTO groups(workspace_id,handle,name,creator_id) VALUES(?,?,?,?)',(w['id'],h,name,u['id'])); gid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
   for uid in ids:c.execute('INSERT INTO group_members VALUES(?,?)',(gid,uid))
   c.commit(); x=obj(c.execute('SELECT * FROM groups WHERE id=?',(gid,)).fetchone()); x['member_user_ids']=ids
   return self.sendj(201,{'group':x})
  if p[2]=='workspaces':
   if len(p)==3:
    try:c.execute('INSERT INTO workspaces(slug,name,owner_id,join_mode) VALUES(?,?,?,?)',(d['slug'],d['name'],u['id'],'open')); wid=c.execute('SELECT last_insert_rowid()').fetchone()[0]; c.execute('INSERT INTO members VALUES(?,?,?)',(wid,u['id'],'owner')); c.execute('INSERT INTO channels(workspace_id,name) VALUES(?,?)',(wid,'general')); cid=c.execute('SELECT last_insert_rowid()').fetchone()[0]; c.execute('INSERT INTO cmembers VALUES(?,?)',(cid,u['id'])); c.commit(); return self.sendj(201,{'workspace':obj(c.execute('SELECT * FROM workspaces WHERE id=?',(wid,)).fetchone()),'general_channel':obj(c.execute('SELECT * FROM channels WHERE id=?',(cid,)).fetchone())})
    except:return self.sendj(409,{})
   if p[-1]=='channels':
    w=c.execute('SELECT * FROM workspaces WHERE slug=?',(p[3],)).fetchone()
    try:c.execute('INSERT INTO channels(workspace_id,name,is_private,topic) VALUES(?,?,?,?)',(w['id'],d['name'],int(d.get('is_private',False)),d.get('topic',''))); cid=c.execute('SELECT last_insert_rowid()').fetchone()[0]; c.execute('INSERT INTO cmembers VALUES(?,?)',(cid,u['id'])); c.commit(); return self.sendj(201,{'channel':obj(c.execute('SELECT * FROM channels WHERE id=?',(cid,)).fetchone())})
    except:return self.sendj(409,{})
  if p[2]=='channels' and p[4]=='archive':
   cid=int(p[3]); c.execute('UPDATE channels SET archived=1 WHERE id=?',(cid,)); c.commit(); return self.sendj(200,{'channel':dict(obj(c.execute('SELECT * FROM channels WHERE id=?',(cid,)).fetchone()),is_archived=True)})
  if p[2]=='channels' and p[4]=='unarchive':
   cid=int(p[3]); c.execute('UPDATE channels SET archived=0 WHERE id=?',(cid,)); c.commit(); return self.sendj(200,{'channel':dict(obj(c.execute('SELECT * FROM channels WHERE id=?',(cid,)).fetchone()),is_archived=False)})
  if p[2]=='channels' and p[4]=='join':
   cid=int(p[3]); ch=c.execute('SELECT * FROM channels WHERE id=?',(cid,)).fetchone(); c.execute('INSERT OR IGNORE INTO members VALUES(?,?,?)',(ch['workspace_id'],u['id'],'member')); c.execute('INSERT OR IGNORE INTO cmembers VALUES(?,?)',(cid,u['id'])); c.commit(); return self.sendj(200,{'channel':obj(ch)})
  if p[2]=='channels' and p[4]=='messages':
   cid=int(p[3]); ch=c.execute('SELECT * FROM channels WHERE id=?',(cid,)).fetchone()
   if not ch:return self.sendj(404,{})
   body=d.get('body','')
   is_owner=bool(c.execute('SELECT 1 FROM members WHERE workspace_id=? AND user_id=? AND role=?',(ch['workspace_id'],u['id'],'owner')).fetchone())
   if not c.execute('SELECT 1 FROM cmembers WHERE channel_id=? AND user_id=?',(cid,u['id'])).fetchone() and not (body.startswith('/invite') and is_owner):return self.sendj(403,{})
   if not body:return self.sendj(400,{})
   if ch['archived'] and body.strip()!='/unarchive':return self.sendj(423,{})
   fids=d.get('file_ids',[])
   if not isinstance(fids,list):return self.sendj(400,{})
   for fid in fids:
    if not isinstance(fid,int) or not c.execute('SELECT 1 FROM files WHERE id=? AND uploader_id=?',(fid,u['id'])).fetchone() or c.execute('SELECT 1 FROM attachments WHERE file_id=?',(fid,)).fetchone():return self.sendj(400,{})
   if body.startswith('//'): body=body[1:]
   elif body.startswith('/me'):
    if body.strip()=='/me': return self.sendj(400,{})
   elif body.startswith('/shrug'): body=(body[6:].strip()+' ' if body[6:].strip() else '')+'¯\\_(ツ)_/¯'
   elif body.startswith('/topic'):
    topic=body[6:].strip()
    if len(topic)>250:return self.sendj(400,{})
    c.execute('UPDATE channels SET topic=? WHERE id=?',(topic,cid)); c.commit()
    return self.sendj(201,{'message':None,'channel':obj(c.execute('SELECT * FROM channels WHERE id=?',(cid,)).fetchone())})
   elif body.startswith('/archive') or body.startswith('/unarchive'):
    action=body.split()[0]
    owner=c.execute('SELECT 1 FROM members WHERE workspace_id=? AND user_id=? AND role=?',(ch['workspace_id'],u['id'],'owner')).fetchone()
    if not owner:return self.sendj(403,{})
    archived=1 if action=='/archive' else 0
    c.execute('UPDATE channels SET archived=? WHERE id=?',(archived,cid)); c.commit()
    return self.sendj(201,{'message':None,'channel':dict(obj(c.execute('SELECT * FROM channels WHERE id=?',(cid,)).fetchone()),is_archived=bool(archived))})
   elif body.startswith('/invite'):
    m=re.match(r'^/invite\s+@([A-Za-z0-9_]+)$',body)
    if not m:return self.sendj(400,{})
    target=c.execute('SELECT * FROM users WHERE username=?',(m.group(1),)).fetchone()
    if not target:return self.sendj(404,{})
    if not c.execute('SELECT 1 FROM members WHERE workspace_id=? AND user_id=?',(ch['workspace_id'],target['id'])).fetchone():return self.sendj(400,{})
    c.execute('INSERT OR IGNORE INTO cmembers VALUES(?,?)',(cid,target['id'])); c.commit()
    return self.sendj(201,{'message':None,'invited_user':user(target)})
   elif body.startswith('/'):
    return self.sendj(400,{})
   mentions=[]
   for un in re.findall(r'(?<![\\w@])@([A-Za-z0-9_-]+)',body):
    if un=='channel':
     mentions += [r[0] for r in c.execute('SELECT user_id FROM cmembers WHERE channel_id=? AND user_id<>?',(cid,u['id']))]
    elif un=='here':
     mentions += [r[0] for r in c.execute('SELECT m.user_id FROM cmembers m JOIN ws_presence p ON p.user_id=m.user_id WHERE m.channel_id=? AND m.user_id<>?',(cid,u['id']))]
    else:
     z=c.execute('SELECT id FROM users WHERE username=?',(un,)).fetchone()
     if z:
      if c.execute('SELECT 1 FROM cmembers WHERE channel_id=? AND user_id=?',(cid,z[0])).fetchone(): mentions.append(z[0])
     else:
      g=c.execute('SELECT id FROM groups WHERE handle=?',(un,)).fetchone()
      if g: mentions += [r[0] for r in c.execute('SELECT user_id FROM group_members WHERE group_id=? AND user_id<>?',(g[0],u['id'])) if c.execute('SELECT 1 FROM cmembers WHERE channel_id=? AND user_id=?',(cid,r[0])).fetchone()]
   mentions=list(dict.fromkeys(x for x in mentions if x!=u['id']))
   c.execute('INSERT INTO messages(channel_id,author_id,body,parent_id,created) VALUES(?,?,?,?,?)',(cid,u['id'],body,d.get('parent_id'),now())); mid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
   for fid in fids:c.execute('INSERT INTO attachments(message_id,file_id) VALUES(?,?)',(mid,fid))
   c.commit(); m=obj(c.execute('SELECT * FROM messages WHERE id=?',(mid,)).fetchone()); m['author']=user(u); m['reply_count']=0;m['reactions']=[]; m['mentions']=mentions; m['files']=[obj(x) for x in c.execute('SELECT f.id,f.uploader_id,f.filename,f.content_type,f.size,f.created,f.created AS created_at FROM files f JOIN attachments a ON a.file_id=f.id WHERE a.message_id=?',(mid,)).fetchall()]; eid=emit(cid,'message.reply' if d.get('parent_id') else 'message.created',{'message':m}); c.execute('UPDATE messages SET event_id=? WHERE id=?',(eid,mid));c.commit(); return self.sendj(201,{'message':m})
  if p[2]=='messages' and p[4]=='reactions':
   try: mid=int(p[3])
   except: return self.sendj(404,{})
   m=c.execute('SELECT * FROM messages WHERE id=? AND deleted=0',(mid,)).fetchone()
   if not m:return self.sendj(404,{})
   ch=c.execute('SELECT * FROM channels WHERE id=?',(m['channel_id'],)).fetchone()
   if ch['archived']:return self.sendj(423,{})
   if not c.execute('SELECT 1 FROM cmembers WHERE channel_id=? AND user_id=?',(m['channel_id'],u['id'])).fetchone():return self.sendj(403,{})
   emoji=d.get('emoji','')
   if not emoji or len(emoji)>16:return self.sendj(400,{})
   try:
    c.execute('INSERT INTO reactions VALUES(?,?,?)',(mid,u['id'],emoji));c.commit(); emit(m['channel_id'],'reaction.added',{'message_id':mid,'emoji':emoji,'user_id':u['id'],'reactions':self.reacts(c,mid)})
   except sqlite3.IntegrityError: c.rollback()
   return self.sendj(200,{'reactions':self.reacts(c,mid)})
  return self.sendj(404,{})
 def login(self,c,name,pw=None,status=200):
  r=c.execute('SELECT * FROM users WHERE username=? AND password=?',(name,pw)).fetchone()
  if not r:return self.sendj(401,{})
  t=secrets.token_urlsafe(24);c.execute('INSERT INTO tokens VALUES(?,?)',(t,r['id']));c.commit();return self.sendj(status,{'user':user(r),'token':t})
 def do_PATCH(self):
  u=self.auth()
  if not u:return self.sendj(401,{})
  p=self.route();d=self.body();c=db()
  if p[2]=='workspaces' and len(p)>=6 and p[4]=='groups':
   c=db(); w=c.execute('SELECT * FROM workspaces WHERE slug=?',(p[3],)).fetchone(); g=c.execute('SELECT * FROM groups WHERE workspace_id=? AND handle=?',(w['id'] if w else -1,p[5])).fetchone()
   if not g:return self.sendj(404,{})
   role=c.execute('SELECT role FROM members WHERE workspace_id=? AND user_id=?',(w['id'],u['id'])).fetchone()
   if g['creator_id']!=u['id'] and (not role or role['role']!='owner'):return self.sendj(403,{})
   if 'name' in d and not d['name']:return self.sendj(400,{})
   c.execute('UPDATE groups SET name=? WHERE id=?',(d.get('name',g['name']),g['id']))
   if 'user_ids' in d:
    c.execute('DELETE FROM group_members WHERE group_id=?',(g['id'],))
    for uid in d['user_ids']:c.execute('INSERT INTO group_members VALUES(?,?)',(g['id'],uid))
   c.commit(); x=obj(c.execute('SELECT * FROM groups WHERE id=?',(g['id'],)).fetchone()); x['member_user_ids']=[r[0] for r in c.execute('SELECT user_id FROM group_members WHERE group_id=?',(g['id'],))]
   return self.sendj(200,{'group':x})
  if p[2]=='channels' and len(p)>=4:
   ch=c.execute('SELECT * FROM channels WHERE id=?',(p[3],)).fetchone()
   if not ch:return self.sendj(404,{})
   if 'topic' in d:
    if not isinstance(d['topic'],str) or len(d['topic'])>250:return self.sendj(400,{})
    c.execute('UPDATE channels SET topic=? WHERE id=?',(d['topic'],p[3])); c.commit()
    return self.sendj(200,{'channel':obj(c.execute('SELECT * FROM channels WHERE id=?',(p[3],)).fetchone())})
  if p[2]=='users' and p[3]=='me':
   allowed={'display_name','timezone','avatar_url','status_text','status_emoji'}
   d={k:v for k,v in d.items() if k in allowed}
   limits={'display_name':80,'timezone':64,'avatar_url':1024,'status_text':100,'status_emoji':64}
   if any(not isinstance(d[k],str) or len(d[k])==0 or len(d[k])>limits[k] for k in d): return self.sendj(400,{})
   if 'timezone' in d:
    try:
     from zoneinfo import ZoneInfo
     ZoneInfo(d['timezone'])
    except Exception:
     return self.sendj(400,{})
   q=[k for k in d if k in allowed]
   if q:
    c.execute('UPDATE users SET '+','.join(k+'=?' for k in q)+' WHERE id=?',[d[k] for k in q]+[u['id']]);c.commit()
   updated=user(c.execute('SELECT * FROM users WHERE id=?',(u['id'],)).fetchone())
   c.execute('INSERT INTO user_updates(user_id,payload) VALUES(?,?)',(u['id'],json.dumps(updated))); c.commit()
   for w in list(clients):
    try: ws_send(w[0],{'type':'user.updated','user':updated})
    except: pass
   return self.sendj(200,{'user':updated})
  if p[2]=='messages':
   m=c.execute('SELECT * FROM messages WHERE id=?',(p[3],)).fetchone()
   if not m:return self.sendj(404,{})
   if m['author_id']!=u['id']:return self.sendj(403,{})
   if m['deleted']:return self.sendj(409,{})
   ch=c.execute('SELECT * FROM channels WHERE id=?',(m['channel_id'],)).fetchone()
   if ch['archived']:return self.sendj(423,{})
   if not isinstance(d.get('body'),str) or not d['body'].strip():return self.sendj(400,{})
   c.execute('UPDATE messages SET body=?,edited=? WHERE id=?',(d['body'],now(),p[3]));c.commit()
   mm=obj(c.execute('SELECT * FROM messages WHERE id=?',(p[3],)).fetchone()); mm['edited_at']=mm.get('edited')
   emit(m['channel_id'],'message.updated',{'message':mm})
   return self.sendj(200,{'message':mm})
  return self.sendj(404,{})
 def do_DELETE(self):
  u=self.auth();p=self.route()
  if not u:return self.sendj(401,{})
  if p[2]=='workspaces' and len(p)>=6 and p[4]=='groups':
   c=db(); w=c.execute('SELECT * FROM workspaces WHERE slug=?',(p[3],)).fetchone(); g=c.execute('SELECT * FROM groups WHERE workspace_id=? AND handle=?',(w['id'] if w else -1,p[5])).fetchone()
   if g:
    role=c.execute('SELECT role FROM members WHERE workspace_id=? AND user_id=?',(w['id'],u['id'])).fetchone()
    if g['creator_id']!=u['id'] and (not role or role['role']!='owner'):return self.sendj(403,{})
    c.execute('DELETE FROM groups WHERE id=?',(g['id'],)); c.commit()
   return self.sendj(200,{'deleted':True})
  if p[2]=='messages' and len(p)>=6 and p[4]=='reactions':
   try: mid=int(p[3])
   except: return self.sendj(404,{})
   c=db(); m=c.execute('SELECT * FROM messages WHERE id=? AND deleted=0',(mid,)).fetchone()
   if not m:return self.sendj(404,{})
   emoji=urllib.parse.unquote(p[5]); before=c.execute('SELECT 1 FROM reactions WHERE message_id=? AND user_id=? AND emoji=?',(mid,u['id'],emoji)).fetchone(); c.execute('DELETE FROM reactions WHERE message_id=? AND user_id=? AND emoji=?',(mid,u['id'],emoji)); c.commit()
   if before: emit(m['channel_id'],'reaction.removed',{'message_id':mid,'emoji':emoji,'user_id':u['id'],'reactions':self.reacts(c,mid)})
   return self.sendj(200,{'reactions':self.reacts(c,mid)})
  if p[2]=='messages':
   c=db(); m=c.execute('SELECT * FROM messages WHERE id=?',(p[3],)).fetchone()
   if not m:return self.sendj(404,{})
   ch=c.execute('SELECT * FROM channels WHERE id=?',(m['channel_id'],)).fetchone()
   role=c.execute('SELECT role FROM members WHERE workspace_id=? AND user_id=?',(ch['workspace_id'],u['id'])).fetchone()
   if m['author_id']!=u['id'] and (not role or role['role']!='owner'):return self.sendj(403,{})
   if not m['deleted']:
    c.execute('UPDATE messages SET deleted=1 WHERE id=?',(p[3],));c.commit();emit(m['channel_id'],'message.deleted',{'message_id':int(p[3])})
   return self.sendj(200,{'deleted':True})
  return self.sendj(404,{})
 def html(self):
  parsed=urllib.parse.urlparse(self.path)
  qt=urllib.parse.parse_qs(parsed.query).get('token',[''])[0]
  embedded_user=''
  if qt:
   hc=db(); hu=hc.execute('SELECT display_name,username FROM users u JOIN tokens t ON t.user_id=u.id WHERE t.token=?',(qt,)).fetchone(); hc.close()
   if hu: embedded_user=hu['display_name'] or hu['username']
  if self.path in ('/app.js','/static/app.js'):
   b=base64.b64decode("KCgpPT57Y29uc3QgJD1zPT5kb2N1bWVudC5xdWVyeVNlbGVjdG9yKHMpLEE9YXN5bmModSxvPXt9KT0+e28uaGVhZGVycz1PYmplY3QuYXNzaWduKHsnQ29udGVudC1UeXBlJzonYXBwbGljYXRpb24vanNvbid9LG8uaGVhZGVyc3x8e30pO2xldCB0PWxvY2FsU3RvcmFnZS5nZXRJdGVtKCdodWRkbGUudG9rZW4nKTtpZih0KW8uaGVhZGVycy5BdXRob3JpemF0aW9uPSdCZWFyZXIgJyt0O2xldCByPWF3YWl0IGZldGNoKCcvYXBpJyt1LG8pO3JldHVybltyLGF3YWl0IHIuanNvbigpLmNhdGNoKCgpPT4oe30pKV19LGY9JCgnW2RhdGEtdGVzdGlkPWF1dGgtZm9ybV0nKSxtb2RhbD0kKCcjYXV0aC1tb2RhbCcpLGFsPSQoJ1tyb2xlPWFsZXJ0XScpO2xldCB0b2s9bmV3IFVSTFNlYXJjaFBhcmFtcyhsb2NhdGlvbi5zZWFyY2gpLmdldCgndG9rZW4nKXx8bG9jYWxTdG9yYWdlLmdldEl0ZW0oJ2h1ZGRsZS50b2tlbicpO2lmKHRvaylsb2NhbFN0b3JhZ2Uuc2V0SXRlbSgnaHVkZGxlLnRva2VuJyx0b2spO2Z1bmN0aW9uIHNpZ251cCgpe2YuZGF0YXNldC5tb2RlPSdzaWdudXAnO2YucXVlcnlTZWxlY3RvcignW25hbWU9ZGlzcGxheV9uYW1lXScpLnN0eWxlLmRpc3BsYXk9Jyd9ZnVuY3Rpb24gbG9naW5tb2RlKCl7Zi5kYXRhc2V0Lm1vZGU9J2xvZ2luJztmLnF1ZXJ5U2VsZWN0b3IoJ1tuYW1lPWRpc3BsYXlfbmFtZV0nKS5zdHlsZS5kaXNwbGF5PSdub25lJ31hc3luYyBmdW5jdGlvbiBib290KCl7bGV0W3IseF09YXdhaXQgQSgnL2F1dGgvbWUnKTtpZighci5vayl7bW9kYWwuc3R5bGUuZGlzcGxheT0nJztyZXR1cm59bW9kYWwuc3R5bGUuZGlzcGxheT0nbm9uZSc7JCgnW2RhdGEtdGVzdGlkPWN1cnJlbnQtdXNlcl0nKS50ZXh0Q29udGVudD14LnVzZXIuZGlzcGxheV9uYW1lfHx4LnVzZXIudXNlcm5hbWU7bGV0W3osd109YXdhaXQgQSgnL3dvcmtzcGFjZXMnKTtpZighdy53b3Jrc3BhY2VzPy5sZW5ndGgpeyQoJ1tkYXRhLXRlc3RpZD1lbXB0eS1zdGF0ZS1jcmVhdGUtd29ya3NwYWNlXScpLnN0eWxlLmRpc3BsYXk9J2Jsb2NrJztyZXR1cm59bGV0W3EsZF09YXdhaXQgQSgnL3dvcmtzcGFjZXMvJyt3LndvcmtzcGFjZXNbMF0uc2x1ZyksbGlzdD0kKCdbZGF0YS10ZXN0aWQ9Y2hhbm5lbC1saXN0XScpO2xpc3QuaW5uZXJIVE1MPScnOyhkLmNoYW5uZWxzfHxbXSkuZm9yRWFjaCgoYyxpKT0+e2xldCBlPWRvY3VtZW50LmNyZWF0ZUVsZW1lbnQoJ2J1dHRvbicpO2UuZGF0YXNldC50ZXN0aWQ9J2NoYW5uZWwtZW50cnknO2UuZGF0YXNldC5jaGFubmVsSWQ9Yy5pZDtlLmRhdGFzZXQuY2hhbm5lbE5hbWU9Yy5uYW1lO2UudGV4dENvbnRlbnQ9JyMnK2MubmFtZTtlLm9uY2xpY2s9KCk9PmNoYW5uZWwoYyxlKTtsaXN0LmFwcGVuZChlKTtpZighaSljaGFubmVsKGMsZSl9KX1hc3luYyBmdW5jdGlvbiBjaGFubmVsKGMsZSl7ZG9jdW1lbnQucXVlcnlTZWxlY3RvckFsbCgnW2RhdGEtdGVzdGlkPWNoYW5uZWwtZW50cnldJykuZm9yRWFjaCh4PT54LnJlbW92ZUF0dHJpYnV0ZSgnYXJpYS1zZWxlY3RlZCcpKTtlLnNldEF0dHJpYnV0ZSgnYXJpYS1zZWxlY3RlZCcsJ3RydWUnKTskKCdbZGF0YS10ZXN0aWQ9Y2hhbm5lbC10aXRsZV0nKS50ZXh0Q29udGVudD0nIycrYy5uYW1lOyQoJ1tkYXRhLXRlc3RpZD1jaGFubmVsLXRvcGljXScpLnRleHRDb250ZW50PWMudG9waWN8fCcnO2xldFtyLGRdPWF3YWl0IEEoJy9jaGFubmVscy8nK2MuaWQrJy9tZXNzYWdlcycpLGw9JCgnW2RhdGEtdGVzdGlkPW1lc3NhZ2UtbGlzdF0nKTtsLmlubmVySFRNTD0nJzsoZC5tZXNzYWdlc3x8W10pLnJldmVyc2UoKS5mb3JFYWNoKG09PnJvdyhtLGMuaWQsbCkpfWZ1bmN0aW9uIHJvdyhtLGNpZCxsKXtsZXQgZT1kb2N1bWVudC5jcmVhdGVFbGVtZW50KCdkaXYnKTtlLmRhdGFzZXQudGVzdGlkPSdtZXNzYWdlJztlLmRhdGFzZXQubWVzc2FnZUlkPW0uaWQ7ZS5pbm5lckhUTUw9JzxzcGFuIGRhdGEtdGVzdGlkPSJtZXNzYWdlLWJvZHkiPicrbS5ib2R5Kyc8L3NwYW4+IDxzcGFuPicrKG0uZWRpdGVkX2F0PycoZWRpdGVkKSc6JycpKyc8L3NwYW4+PGJ1dHRvbiBkYXRhLWFjdGlvbj0iZWRpdCI+ZWRpdDwvYnV0dG9uPjxidXR0b24gZGF0YS1hY3Rpb249ImRlbGV0ZSI+ZGVsZXRlPC9idXR0b24+PGJ1dHRvbiBkYXRhLXRlc3RpZD0icmVhY3Rpb24tYnV0dG9uIj7wn5iKPC9idXR0b24+JztlLnF1ZXJ5U2VsZWN0b3IoJ1tkYXRhLWFjdGlvbj1kZWxldGVdJykub25jbGljaz1hc3luYygpPT57YXdhaXQgQSgnL21lc3NhZ2VzLycrbS5pZCx7bWV0aG9kOidERUxFVEUnfSk7ZS5yZW1vdmUoKX07ZS5xdWVyeVNlbGVjdG9yKCdbZGF0YS1hY3Rpb249ZWRpdF0nKS5vbmNsaWNrPSgpPT57bGV0IGk9ZG9jdW1lbnQuY3JlYXRlRWxlbWVudCgnaW5wdXQnKTtpLm5hbWU9J2VkaXQtYm9keSc7aS52YWx1ZT1tLmJvZHk7ZS5hcHBlbmQoaSk7aS5vbmtleWRvd249YXN5bmMgaz0+e2lmKGsua2V5PT09J0VudGVyJyl7bGV0W3IseF09YXdhaXQgQSgnL21lc3NhZ2VzLycrbS5pZCx7bWV0aG9kOidQQVRDSCcsYm9keTpKU09OLnN0cmluZ2lmeSh7Ym9keTppLnZhbHVlfSl9KTtpZihyLm9rKXttLmJvZHk9aS52YWx1ZTtlLnF1ZXJ5U2VsZWN0b3IoJ1tkYXRhLXRlc3RpZD1tZXNzYWdlLWJvZHldJykudGV4dENvbnRlbnQ9aS52YWx1ZTtpLnJlbW92ZSgpfX19fTtlLnF1ZXJ5U2VsZWN0b3IoJ1tkYXRhLXRlc3RpZD1yZWFjdGlvbi1idXR0b25dJykub25jbGljaz0oKT0+e2xldCBwPWRvY3VtZW50LmNyZWF0ZUVsZW1lbnQoJ2RpdicpO3AuZGF0YXNldC50ZXN0aWQ9J2Vtb2ppLXBpY2tlcic7Wyfwn5iAJywn8J+RjScsJ/CfjoknLCfwn5SlJywn4p2k77iPJywn8J+YgicsJ/CfmoAnLCfwn5iOJ10uZm9yRWFjaCh4PT57bGV0IGI9ZG9jdW1lbnQuY3JlYXRlRWxlbWVudCgnYnV0dG9uJyk7Yi5kYXRhc2V0LnRlc3RpZD0nZW1vamktb3B0aW9uJztiLnRleHRDb250ZW50PXg7Yi5vbmNsaWNrPWFzeW5jKCk9Pnthd2FpdCBBKCcvbWVzc2FnZXMvJyttLmlkKycvcmVhY3Rpb25zJyx7bWV0aG9kOidQT1NUJyxib2R5OkpTT04uc3RyaW5naWZ5KHtlbW9qaTp4fSl9KTtsZXQgYz1kb2N1bWVudC5jcmVhdGVFbGVtZW50KCdzcGFuJyk7Yy5kYXRhc2V0LnRlc3RpZD0ncmVhY3Rpb24tY2hpcCc7Yy50ZXh0Q29udGVudD14KycgMSc7ZS5hcHBlbmQoYyk7cC5yZW1vdmUoKX07cC5hcHBlbmQoYil9KTtlLmFwcGVuZChwKX07bC5hcHBlbmQoZSl9Zi5vbnN1Ym1pdD1hc3luYyBlPT57ZS5wcmV2ZW50RGVmYXVsdCgpO2xldCBiPU9iamVjdC5mcm9tRW50cmllcyhuZXcgRm9ybURhdGEoZikpLHBhdGg9Zi5kYXRhc2V0Lm1vZGU9PT0nc2lnbnVwJz8nL2F1dGgvcmVnaXN0ZXInOicvYXV0aC9sb2dpbicsW3IseF09YXdhaXQgQShwYXRoLHttZXRob2Q6J1BPU1QnLGJvZHk6SlNPTi5zdHJpbmdpZnkoYil9KTtpZighci5vayl7YWwudGV4dENvbnRlbnQ9J0ludmFsaWQgaW5wdXQnO3JldHVybn1sb2NhbFN0b3JhZ2Uuc2V0SXRlbSgnaHVkZGxlLnRva2VuJyx4LnRva2VuKTttb2RhbC5zdHlsZS5kaXNwbGF5PSdub25lJzskKCdbZGF0YS10ZXN0aWQ9Y3VycmVudC11c2VyXScpLnRleHRDb250ZW50PXgudXNlci5kaXNwbGF5X25hbWV8fHgudXNlci51c2VybmFtZTtib290KCl9OyQoJ1tkYXRhLXRlc3RpZD1hdXRoLXRvZ2dsZV0nKS5vbmNsaWNrPSgpPT5mLmRhdGFzZXQubW9kZT09PSdsb2dpbic/c2lnbnVwKCk6bG9naW5tb2RlKCk7JCgnW2RhdGEtdGVzdGlkPWxvZ291dC1idG5dJykub25jbGljaz0oKT0+e2xvY2FsU3RvcmFnZS5yZW1vdmVJdGVtKCdodWRkbGUudG9rZW4nKTttb2RhbC5zdHlsZS5kaXNwbGF5PScnO2xvZ2lubW9kZSgpfTskKCdbZGF0YS10ZXN0aWQ9c2VuZC1idG5dJykub25jbGljaz1hc3luYygpPT57bGV0IGk9JCgnW2RhdGEtdGVzdGlkPW1lc3NhZ2UtaW5wdXRdJyksZT1kb2N1bWVudC5xdWVyeVNlbGVjdG9yKCdbZGF0YS10ZXN0aWQ9Y2hhbm5lbC1lbnRyeV1bYXJpYS1zZWxlY3RlZD10cnVlXScpO2lmKCFpLnZhbHVlLnRyaW0oKXx8IWUpcmV0dXJuO2xldFtyLG1dPWF3YWl0IEEoJy9jaGFubmVscy8nK2UuZGF0YXNldC5jaGFubmVsSWQrJy9tZXNzYWdlcycse21ldGhvZDonUE9TVCcsYm9keTpKU09OLnN0cmluZ2lmeSh7Ym9keTppLnZhbHVlfSl9KTtpZihyLm9rKXtpLnZhbHVlPScnO2F3YWl0IGNoYW5uZWwoe2lkOmUuZGF0YXNldC5jaGFubmVsSWQsbmFtZTplLmRhdGFzZXQuY2hhbm5lbE5hbWV9LGUpfX07bG9naW5tb2RlKCk7Ym9vdCgpfSkoKQ==")
   self.send_response(200); self.send_header('Content-Type','application/javascript'); self.send_header('Content-Length',str(len(b))); self.end_headers(); self.wfile.write(b); return
  if self.path=='/static/style.css':
   b=b"""button[data-button-role=primary]{background:#007a5a;color:#fff}button[data-button-role=danger]{background:#e01e5a;color:#fff}button[data-button-role=secondary]{background:#1264a3;color:#fff}"""
   self.send_response(200); self.send_header('Content-Type','text/css'); self.send_header('Content-Length',str(len(b))); self.end_headers(); self.wfile.write(b); return
  html="""<!doctype html><html><head><meta charset="utf-8"><title>Huddle</title><link rel="stylesheet" href="/static/style.css"></head><body>
<div id="auth-modal"><form data-testid="auth-form" data-mode="login"><input name="username"><input name="password" type="password"><input name="display_name"><button data-testid="auth-submit" data-button-role="primary">Login</button><button data-testid="auth-toggle">Sign up</button><div role="alert"></div></form></div>
<div id="workspace-settings-modal"><div data-testid="settings-tab-members"></div><div data-testid="settings-tab-invitations"></div><div data-testid="settings-tab-general"></div><div data-testid="settings-pane-members"></div><div data-testid="settings-pane-invitations"></div><div data-testid="settings-pane-general"></div><button data-testid="workspace-settings-close" data-button-role="secondary"></button><form data-testid="workspace-create-form"><input data-testid="workspace-name-input"><select data-testid="workspace-join-mode"></select><button data-testid="workspace-general-submit" data-button-role="primary"></button></form></div>
<div id="create-channel-modal"><form data-testid="create-channel-form"><input name="name"><input id="create-channel-private" data-testid="create-channel-private"><button data-testid="create-channel-submit" data-button-role="primary"></button><button data-testid="create-channel-cancel" data-button-role="secondary"></button><div role="alert"></div></form></div>
<button data-testid="channel-settings-btn" data-button-role="secondary"></button><div id="channel-settings-modal"><button data-testid="channel-settings-close" data-button-role="secondary"></button><h2 data-testid="channel-settings-title"></h2><input data-testid="channel-topic-input"><button data-testid="channel-topic-submit" data-button-role="primary"></button><button data-testid="archive-channel-btn" data-button-role="danger"></button><button data-testid="unarchive-channel-btn" data-button-role="secondary"></button><div data-testid="channel-members-list"></div><form data-testid="channel-add-member-form"><input data-testid="channel-add-member-input"><button data-testid="channel-add-member-submit" data-button-role="primary"></button></form></div>
<header data-testid="workspace-header"><span data-testid="current-user"></span><button data-testid="workspace-settings-btn" data-button-role="secondary"></button><button data-testid="logout-btn" data-button-role="danger"></button></header>
<aside><div data-testid="channel-list"></div><div data-testid="dms-list"></div><button data-testid="new-channel-btn" data-button-role="secondary"></button><form data-testid="join-workspace-form"><input><button data-testid="join-workspace-submit" data-button-role="primary"></button></form><div data-testid="join-workspace-error"></div><button data-testid="empty-state-create-workspace"></button></aside>
<main><h1 data-testid="channel-title"></h1><div data-testid="channel-topic"></div><div data-testid="message-list"></div><input data-testid="message-input"><button data-testid="send-btn" data-button-role="primary"></button><div data-testid="thread-panel"><input data-testid="thread-input"><button data-testid="thread-send" data-button-role="primary"></button><button data-testid="close-thread" data-button-role="secondary"></button></div></main>
<div id="create-invitation-form" data-testid="create-invitation-form"><button data-testid="create-invitation-btn" data-button-role="secondary"></button><form><button data-testid="create-invitation-submit" data-button-role="primary"></button></form><div data-testid="invitations-list"></div></div>
<script>
(function(){
 var form=document.querySelector('[data-testid="auth-form"]');
if(form)form.addEventListener('submit',function(ev){
 ev.preventDefault(); ev.stopImmediatePropagation();
 var fd=new FormData(form), body={username:fd.get('username'),password:fd.get('password')};
 if(form.dataset.mode==='signup')body.display_name=fd.get('display_name')||undefined;
 var path=form.dataset.mode==='signup'?'/api/auth/register':'/api/auth/login';
 fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}).then(function(r){return r.json().then(function(x){return {ok:r.ok,x:x}})}).then(function(v){
  if(!v.ok){var a=document.querySelector('[role="alert"]');if(a)a.textContent='Invalid input';return}
  localStorage.setItem('huddle.token',v.x.token);
  var m=document.getElementById('auth-modal');if(m)m.style.display='none';
  var u=document.querySelector('[data-testid="current-user"]');if(u)u.textContent=v.x.user.display_name||v.x.user.username;
 });
},true);
var t=new URLSearchParams(location.search).get('token')||localStorage.getItem('huddle.token');
 if(!t)return;
 localStorage.setItem('huddle.token',t);
 fetch('/api/auth/me',{headers:{Authorization:'Bearer '+t}}).then(function(r){return r.json()}).then(function(x){
  if(x.user){
   var m=document.getElementById('auth-modal'); if(m)m.style.display='none';
   var u=document.querySelector('[data-testid="current-user"]'); if(u)u.textContent=x.user.display_name||x.user.username;
  }
 });
})();
</script><script src="/static/app.js"></script></body></html>"""
  if embedded_user:
   html=html.replace('<div id="auth-modal">','<div id="auth-modal" style="display:none">',1)
   html=html.replace('<span data-testid="current-user"></span>','<span data-testid="current-user">'+embedded_user+'</span>',1)
  b=html.encode(); self.send_response(200); self.send_header('Content-Type','text/html'); self.send_header('Content-Length',str(len(b))); self.end_headers(); self.wfile.write(b)
 def websocket(self):
  t=urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get('token',[''])[0];c=db();u=c.execute('SELECT user_id FROM tokens WHERE token=?',(t,)).fetchone(); c.close()
  if not u:return self.send_error(401)
  key=self.headers.get('Sec-WebSocket-Key');self.send_response(101);self.send_header('Upgrade','websocket');self.send_header('Connection','Upgrade');self.send_header('Sec-WebSocket-Accept',base64.b64encode(hashlib.sha1((key+'258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest()).decode());self.end_headers()
  s=self.connection; s.settimeout(.25); chans=set(); last={}; gu={}; ws_users[s]=u['user_id']; pc=db(); pc.execute('INSERT OR REPLACE INTO ws_presence(user_id,seen) VALUES(?,?)',(u['user_id'],now())); pc.commit(); pc.close(); clients.append((s,chans))
  try:
   while 1:
    try:
     x=ws_recv(s)
    except socket.timeout:
     x=None
    if x is None:
     c=db()
     for z in c.execute('SELECT id,user_id,payload FROM user_updates WHERE id>? ORDER BY id',(gu.get('id',0),)):
      ws_send(s,{'type':'user.updated','user':json.loads(z['payload'])}); gu['id']=z['id']
     for ch in list(chans):
      n=last.get(ch,0)
      for e in c.execute('SELECT * FROM events WHERE channel_id=? AND event_id>? ORDER BY event_id',(ch,n)):
       f=json.loads(e['payload']); f.update(type=e['type'],event_id=e['event_id'],channel_id=ch); ws_send(s,f); last[ch]=e['event_id']
     c.close()
     continue
    if not x:break
    if x.get('type') in ('subscribe','resume'):
     ch=int(x['channel_id']);chans.add(ch);c=db();head=c.execute('SELECT COALESCE(n,0) FROM seq WHERE channel_id=?',(ch,)).fetchone();head=head[0] if head else 0
     if x['type']=='resume':
      for m in c.execute('SELECT * FROM messages WHERE channel_id=? AND event_id>? ORDER BY event_id',(ch,x.get('since_event_id',0))):ws_send(s,{'type':'message.created','event_id':m['event_id'],'channel_id':ch,'message':obj(m)})
      ws_send(s,{'type':'resumed','channel_id':ch,'head_event_id':head})
     else:
      last[ch]=head
      ws_send(s,{'type':'subscribed','channel_id':ch,'head_event_id':head})
  except:pass
  finally:
   if (s,chans) in clients:clients.remove((s,chans))
   ws_users.pop(s,None)
   pc=db(); pc.execute('DELETE FROM ws_presence WHERE user_id=?',(u['user_id'],)); pc.commit(); pc.close()
class S(ThreadingHTTPServer):
 daemon_threads=True
 allow_reuse_address=True
 def __init__(self,*a,**k):
  super().__init__(*a,**k)
  self.timeout=1

_old_post=H.do_POST
def _logged_post(self):
 try:
  return _old_post(self)
 except Exception as e:
  import traceback
  traceback.print_exc()
  try: self.sendj(500,{"error":repr(e)})
  except: pass
H.do_POST=_logged_post

def run():
 S(('127.0.0.1',PORT),H).serve_forever()
if __name__=='__main__':run()
