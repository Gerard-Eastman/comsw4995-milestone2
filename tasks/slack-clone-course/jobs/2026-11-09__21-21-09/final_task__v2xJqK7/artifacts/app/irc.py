import socket,threading,sqlite3,json,time
DB='/app/data/huddle.db'; clients=[]; nicks={}; lock=threading.RLock()
def db():
 c=sqlite3.connect(DB,timeout=10); c.row_factory=sqlite3.Row; return c
def user(tok):
 c=db(); r=c.execute('SELECT u.* FROM tokens t JOIN users u ON u.id=t.user_id WHERE t.token=?',(tok,)).fetchone(); c.close(); return r
def send(s,x):
 try:s.sendall((x+'\r\n').encode())
 except:pass
def channel(name):
 if not name.startswith('#') or '/' not in name:return None
 slug,cn=name[1:].split('/',1); c=db(); r=c.execute('SELECT c.*,w.slug,w.name wname FROM channels c JOIN workspaces w ON w.id=c.workspace_id WHERE w.slug=? AND c.name=? AND c.is_dm=0',(slug,cn)).fetchone(); c.close(); return r
def emit(ch,kind,payload):
 c=db(); c.execute('CREATE TABLE IF NOT EXISTS seq(channel_id INTEGER PRIMARY KEY,n INTEGER)'); c.execute('INSERT INTO seq(channel_id,n) VALUES(?,?) ON CONFLICT(channel_id) DO UPDATE SET n=n+1',(ch,1)); e=c.execute('SELECT n FROM seq WHERE channel_id=?',(ch,)).fetchone()[0]; c.execute('INSERT OR REPLACE INTO events VALUES(?,?,?,?)',(ch,e,kind,json.dumps(payload))); c.commit(); c.close(); return e
def insertmsg(uid,ch,body):
 c=db(); c.execute('INSERT INTO messages(channel_id,author_id,body,created) VALUES(?,?,?,?)',(ch,uid,body,time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()))); mid=c.execute('SELECT last_insert_rowid()').fetchone()[0]; c.commit(); m=dict(c.execute('SELECT * FROM messages WHERE id=?',(mid,)).fetchone()); c.close(); e=emit(ch,'message.created',{'message':m}); c=db(); c.execute('UPDATE messages SET event_id=? WHERE id=?',(e,mid)); c.commit(); c.close(); return e
def broadcast(ch,line,exclude=None):
 for x in list(clients):
  if x is not exclude and ch in x[3]:send(x[0],line)
def client(s):
 tok=nick=usr=None; reg=False; bad=False; joined=set(); last={}; buf=b''
 rec=(s,None,None,joined); clients.append(rec)
 try:
  s.settimeout(.5)
  while 1:
   try:
    q=s.recv(4096)
    if not q:break
    buf+=q
   except socket.timeout:
    if reg and joined:
     c=db()
     for ch in list(joined):
      n=last.get(ch,0)
      for e in c.execute('SELECT event_id,payload FROM events WHERE channel_id=? AND event_id>? ORDER BY event_id',(ch,n)):
       last[ch]=e['event_id']
       try:
        f=json.loads(e['payload']); m=f.get('message',{})
        if f.get('type')=='message.created' and m.get('author_id')!=rec[2]['id']:
         cr=c.execute('SELECT w.slug,c.name FROM channels c JOIN workspaces w ON w.id=c.workspace_id WHERE c.id=?',(ch,)).fetchone()
         if cr: send(s,f':{m.get("author",{}).get("username", "huddle")}!{m.get("author",{}).get("username", "huddle")}@huddle PRIVMSG #{cr["slug"]}/{cr["name"]} :{m.get("body","")}')
       except: pass
     c.close()
    continue
   while b'\n' in buf:
    raw,buf=buf.split(b'\n',1); line=raw.decode('utf8','replace').strip('\r'); z=line.split(' ',2); cmd=z[0].upper(); a=z[1:]
    if cmd=='PASS':
     tok=a[0] if a else ''; 
     if not user(tok): bad=True; send(s,':huddle 464 * :Password incorrect')
    elif cmd=='NICK':
     nn=a[0] if a else ''
     if any(k.lower()==nn.lower() and v is not s for k,v in nicks.items()):send(s,f':huddle 433 * {nn} :Nickname is already in use');continue
     nick=nn
    elif cmd=='USER':usr=a[0] if a else nick
    elif cmd=='PING':send(s,':huddle PONG huddle :'+(a[-1].lstrip(':') if a else ''));continue
    elif cmd=='QUIT':return
    if not reg and nick and usr and (not tok or bad):send(s,':huddle 464 * :Password incorrect');return
    if not reg and tok and nick and usr:
     with lock:nicks[nick]=s
     rec=(s,nick,user(tok),joined); clients[-1]=rec; reg=True
     for n,t in [('001','Welcome to Huddle'),('002','Your host is huddle'),('003','This server was created today'),('004','huddle huddle 1.0'),('005','CHANTYPES=# :are supported'),('422','MOTD File is missing')]:send(s,f':huddle {n} {nick} :{t}')
     continue
    if not reg:
     if cmd not in ('PASS','NICK','USER'):send(s,':huddle 451 * :You have not registered')
     continue
    if cmd=='JOIN':
     name=a[0] if a else ''; ch=channel(name)
     if not ch:send(s,f':huddle 403 {nick} {name} :No such channel');continue
     c=db(); ok=c.execute('SELECT 1 FROM cmembers WHERE channel_id=? AND user_id=?',(ch['id'],rec[2]['id'])).fetchone(); c.close()
     if not ok:send(s,f':huddle 403 {nick} {name} :Cannot join channel');continue
     joined.add(ch['id']); send(s,f':{nick}!{nick}@huddle JOIN {name}');send(s,f':huddle 331 {nick} {name} :No topic' if not ch['topic'] else f':huddle 332 {nick} {name} :{ch["topic"]}')
     c=db(); ns=[r['username'] for r in c.execute('SELECT u.username FROM users u JOIN cmembers m ON m.user_id=u.id WHERE m.channel_id=?',(ch['id'],))]; c.close(); send(s,f':huddle 353 {nick} = {name} :{" ".join(ns)}');send(s,f':huddle 366 {nick} {name} :End of NAMES');continue
    if cmd=='PRIVMSG':
     name=a[0] if a else ''; body=(a[1] if len(a)>1 else '').lstrip(':'); ch=channel(name)
     if not ch:send(s,f':huddle 403 {nick} {name} :No such channel');continue
     if ch['id'] not in joined:send(s,f':huddle 442 {nick} {name} :You are not on that channel');continue
     insertmsg(rec[2]['id'],ch['id'],body); broadcast(ch['id'],f':{nick}!{nick}@huddle PRIVMSG {name} :{body}',s);continue
    if cmd in ('NAMES','TOPIC','WHO','LIST','MODE'):
     name=a[0] if a else ''
     if cmd=='NAMES':send(s,f':huddle 353 {nick} = {name} :{nick}');send(s,f':huddle 366 {nick} {name} :End of NAMES')
     elif cmd=='WHO':send(s,f':huddle 352 {nick} {name} {nick} huddle huddle {nick} H :0 {nick}');send(s,f':huddle 315 {nick} {name} :End of WHO list')
     elif cmd=='LIST':
      c=db(); cr=c.execute('SELECT w.slug,c.name FROM channels c JOIN workspaces w ON w.id=c.workspace_id WHERE c.id=?',(next(iter(joined),-1),)).fetchone(); c.close(); nn=f'#{cr["slug"]}/{cr["name"]}' if cr else name
      send(s,f':huddle 321 {nick} Channel :Users Name');send(s,f':huddle 322 {nick} {nn} 1 :channel');send(s,f':huddle 323 {nick} :End of LIST')
     elif cmd=='TOPIC':send(s,f':huddle 331 {nick} {name} :No topic')
     else:
       send(s,f':huddle 221 {nick} {nick} +i') if name==nick else send(s,f':huddle 324 {nick} {name} +nt')
     continue
    if cmd=='PONG':continue
    send(s,f':huddle 421 {nick} {cmd} :Unknown command')
 finally:
  with lock:
   if nick and nicks.get(nick) is s:del nicks[nick]
  if rec in clients:clients.remove(rec)
  try:s.close()
  except:pass
q=socket.socket();q.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);q.bind(('0.0.0.0',6667));q.listen(100)
while 1:
 s,_=q.accept();threading.Thread(target=client,args=(s,),daemon=True).start()
