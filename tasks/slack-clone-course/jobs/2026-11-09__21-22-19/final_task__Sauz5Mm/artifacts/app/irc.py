import asyncio,sqlite3,json,time
DB='/app/data/app.db'; NICKS={}; CLIENTS=[]
def db():
 c=sqlite3.connect(DB,timeout=10,isolation_level=None); c.row_factory=sqlite3.Row
 c.execute('PRAGMA busy_timeout=10000'); return c
async def send(w,line):
 try:w.write((line+'\r\n').encode()); await w.drain()
 except: pass
def channel(name):
 if not name.startswith('#') or '/' not in name[1:]: return None
 slug,n=name[1:].split('/',1); c=db(); r=c.execute('SELECT ch.*,w.slug,w.owner_id FROM channels ch JOIN workspaces w ON w.id=ch.workspace_id WHERE w.slug=? AND ch.name=? AND ch.is_dm=0',(slug,n)).fetchone(); c.close(); return r
def user_for(token):
 c=db(); r=c.execute('SELECT u.* FROM tokens t JOIN users u ON u.id=t.user_id WHERE t.token=?',(token,)).fetchone(); c.close(); return r
def emit(cid,kind,data):
 c=db(); c.execute('BEGIN IMMEDIATE'); c.execute('UPDATE channels SET last_event_id=last_event_id+1 WHERE id=?',(cid,)); n=c.execute('SELECT last_event_id FROM channels WHERE id=?',(cid,)).fetchone()[0]; p={'type':kind,'event_id':n,'channel_id':cid,**data}; c.execute('INSERT INTO events(channel_id,event_id,payload) VALUES(?,?,?)',(cid,n,json.dumps(p))); c.commit(); c.close()
def msgobj(c,r):
 a=c.execute('SELECT * FROM users WHERE id=?',(r['author_id'],)).fetchone()
 return {'id':r['id'],'channel_id':r['channel_id'],'author_id':r['author_id'],'author':dict(a),'body':r['body'],'parent_id':r['parent_id'],'reply_count':0,'created_at':r['created_at'],'edited_at':None,'files':[],'reactions':[],'mentions':[]}
async def eventpump():
 c=db(); last=c.execute('SELECT COALESCE(MAX(seq),0) FROM events').fetchone()[0]; c.close()
 while True:
  await asyncio.sleep(.05); c=db(); rs=c.execute("SELECT seq,payload FROM events WHERE seq>? ORDER BY seq",(last,)).fetchall(); last=rs[-1]['seq'] if rs else last; c.close()
  for x in rs:
   p=json.loads(x['payload'])
   if p.get('type') not in ('message.created','message.reply'): continue
   c=channel_name(p.get('channel_id'))
   if not c: continue
   for cl in list(CLIENTS):
    if c['id'] in cl['channels']:
     m=p.get('message') or {}
     if p.get('irc_sender_id') == cl.get('uid'): continue
     await send(cl['w'],f":{m.get('author',{}).get('username','web')}!{m.get('author',{}).get('username','web')}@huddle PRIVMSG #{c['slug']}/{c['name']} :{m.get('body','')}")
def channel_name(cid):
 c=db(); r=c.execute('SELECT ch.*,w.slug FROM channels ch JOIN workspaces w ON w.id=ch.workspace_id WHERE ch.id=?',(cid,)).fetchone(); c.close(); return r
async def handle_client(r,w):
 nick='*'; token=None; user=None; registered=False; key=None; joined=set(); state={'w':w,'channels':joined,'uid':None}; CLIENTS.append(state)
 try:
  while True:
   raw=await r.readline()
   if not raw: break
   line=raw.decode(errors='ignore').strip('\r\n'); ps=line.split(' ',1); cmd=ps[0].upper(); rest=ps[1] if len(ps)>1 else ''; args=rest.split()
   if cmd=='PASS': token=rest.strip()
   elif cmd=='NICK':
    n=args[0] if args else ''
    if n.lower() in NICKS and NICKS[n.lower()] is not w: await send(w,f':huddle 433 * {n} :Nickname is already in use'); continue
    nick=n
   elif cmd=='USER':
    user=user_for(token or '')
    if not user: await send(w,f':huddle 464 {nick} :Password incorrect'); break
    key=nick.lower(); NICKS[key]=w; state['uid']=user['id']; registered=True
    for no,text in [('001',f'Welcome to Huddle, {nick}'),('002','Your host is huddle'),('003','This server was created today'),('004','huddle huddle 1.0 oiwsz biklmnopstveI')]: await send(w,f':huddle {no} {nick} :{text}')
    await send(w,f':huddle 005 {nick} CHANTYPES=# :are supported by this server'); await send(w,f':huddle 422 {nick} :MOTD File is missing')
   elif cmd=='PING': await send(w,f':huddle PONG huddle :{rest.lstrip(":")}')
   elif cmd=='PONG': pass
   elif cmd=='QUIT': break
   elif not registered: await send(w,f':huddle 451 * :You have not registered')
   elif cmd in ('JOIN','NAMES','TOPIC','WHO','LIST','MODE'):
    target=args[0] if args else ''
    if cmd=='LIST':
     await send(w,f':huddle 321 {nick} Channel :Users Name')
     c=db(); rs=c.execute('SELECT w.slug,ch.name FROM channels ch JOIN workspaces w ON w.id=ch.workspace_id WHERE ch.is_dm=0 ORDER BY CASE WHEN ch.id IN (%s) THEN 0 ELSE 1 END,ch.id DESC'%(','.join(str(x) for x in joined) if joined else '0')).fetchall(); c.close()
     for x in rs: await send(w,f':huddle 322 {nick} #{x["slug"]}/{x["name"]} 0 :')
     await send(w,f':huddle 323 {nick} :End of LIST'); continue
    if cmd=='MODE' and target.lower()==nick.lower():
     await send(w,f':huddle 221 {nick} :+i')
     continue
    ch=channel(target)
    if not ch: await send(w,f':huddle 403 {nick} {target} :No such channel'); continue
    if cmd=='JOIN':
     c=db(); member=c.execute('SELECT 1 FROM cmembers WHERE channel_id=? AND user_id=?',(ch['id'],user['id'])).fetchone(); c.close()
     if not member:
      await send(w,f':huddle 403 {nick} {target} :Cannot join channel') if ch['is_private'] else await send(w,f':huddle 442 {nick} {target} :You are not on that channel')
      continue
     joined.add(ch['id']); await send(w,f':{nick}!{nick}@huddle JOIN {target}'); await send(w,f':huddle 331 {nick} {target} :No topic is set'); c=db(); ns=c.execute('SELECT u.username FROM cmembers m JOIN users u ON u.id=m.user_id WHERE m.channel_id=?',(ch['id'],)).fetchall(); c.close(); await send(w,f':huddle 353 {nick} = {target} :{" ".join(x["username"] for x in ns)}'); await send(w,f':huddle 366 {nick} {target} :End of NAMES')
    elif cmd=='NAMES':
     await send(w,f':huddle 353 {nick} = {target} :{nick}'); await send(w,f':huddle 366 {nick} {target} :End of NAMES')
    elif cmd=='TOPIC': await send(w,f':huddle 331 {nick} {target} :No topic is set')
    elif cmd=='WHO': await send(w,f':huddle 352 {nick} {target} {nick} huddle huddle {nick} H :0 {nick}'); await send(w,f':huddle 315 {nick} {target} :End of WHO')
    elif cmd=='MODE': await send(w,f':huddle 324 {nick} {target} +nt')
   elif cmd=='PRIVMSG':
    if not args: continue
    target=args[0]; body=rest.split(' :',1)[1] if ' :' in rest else ' '.join(args[1:]); ch=channel(target)
    if not ch: await send(w,f':huddle 403 {nick} {target} :No such channel'); continue
    if ch['id'] not in joined: await send(w,f':huddle 442 {nick} {target} :You are not on that channel'); continue
    c=db(); c.execute('INSERT INTO messages(channel_id,author_id,body,created_at) VALUES(?,?,?,?)',(ch['id'],user['id'],body,__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z'))); mid=c.execute('SELECT last_insert_rowid()').fetchone()[0]; row=c.execute('SELECT * FROM messages WHERE id=?',(mid,)).fetchone(); o=msgobj(c,row); c.close(); emit(ch['id'],'message.created',{'message':o,'irc_sender_id':user['id']})
   else: await send(w,f':huddle 421 {nick} {cmd} :Unknown command')
 finally:
  if state in CLIENTS: CLIENTS.remove(state)
  if key and NICKS.get(key) is w: del NICKS[key]
  w.close()
  try: await w.wait_closed()
  except: pass
async def main():
 s=await asyncio.start_server(handle_client,'0.0.0.0',6667); asyncio.create_task(eventpump())
 async with s: await s.serve_forever()
asyncio.run(main())
