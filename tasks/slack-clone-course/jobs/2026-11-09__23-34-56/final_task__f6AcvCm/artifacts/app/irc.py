import asyncio,re,sqlite3,json
DB='/app/data/app.db'
clients={}
def conn():
 c=sqlite3.connect(DB,timeout=0.2); c.row_factory=sqlite3.Row; c.execute('PRAGMA busy_timeout=100'); return c
async def send(w,s):
 try: w.write((s+'\r\n').encode()); await w.drain()
 except: pass
def channel(c,target):
 m=re.fullmatch(r'#([^/]+)/(.+)',target)
 if not m:return None
 return c.execute('SELECT ch.*,w.slug FROM channels ch JOIN workspaces w ON w.id=ch.workspace_id WHERE w.slug=? AND ch.name=?',(m.group(1),m.group(2))).fetchone()
async def client(reader,writer):
 c=conn(); uid=None; nick=None; registered=False; joined={}; targets={}; stop=asyncio.Event()
 async def poll():
  while not stop.is_set():
   pc=None
   try:
    pc=conn()
    for cid,since in list(joined.items()):
     target=targets[cid]
     rows=pc.execute('SELECT * FROM events WHERE channel_id=? AND event_id>? ORDER BY event_id',(cid,since)).fetchall()
     for e in rows:
      joined[cid]=e['event_id']
      if e['kind'] in ('message.created','message.reply'):
       d=json.loads(e['data']); m=d.get('message',{}); au=pc.execute('SELECT username FROM users WHERE id=?',(m.get('author_id'),)).fetchone()
       if au and not (d.get('irc_origin') and m.get('author_id')==uid):
        await send(writer,f":{au['username']}!{au['username']}@huddle PRIVMSG {target} :{m.get('body','')}")
   except Exception:
    await asyncio.sleep(.05)
   finally:
    if pc:
     try: pc.close()
     except: pass
   await asyncio.sleep(.03)
 async def commands():
  nonlocal uid,nick,registered
  while True:
   line=await reader.readline()
   if not line: break
   line=line.decode(errors='ignore').rstrip('\r\n'); ps=line.split(' '); cmd=ps[0].upper(); arg=' '.join(ps[1:])
   if cmd=='PASS':
    r=c.execute('SELECT user_id FROM tokens WHERE token=?',(ps[1] if len(ps)>1 else '',)).fetchone()
    if not r: await send(writer,':huddle 464 * :Password incorrect'); return
    uid=r['user_id']
   elif cmd=='NICK':
    n=ps[1] if len(ps)>1 else ''; k=n.lower()
    if k in clients and clients[k][1] is not writer: await send(writer,f':huddle 433 * {n} :Nickname is already in use'); continue
    nick=n; clients[k]=(uid,writer)
   elif cmd=='USER':
    if not uid: await send(writer,':huddle 464 * :Password incorrect'); return
    if not nick: await send(writer,':huddle 451 * :You have not registered'); continue
    registered=True
    for num,text in [('001','Welcome to Huddle'),('002','Your host is huddle'),('003','This server was created today'),('004','huddle huddle 1'),('005','CHANTYPES=# :are supported by this server'),('422','MOTD File is missing')]: await send(writer,f':huddle {num} {nick} :{text}')
   elif cmd=='PING': await send(writer,':huddle PONG huddle :'+arg.lstrip(':'))
   elif cmd=='PONG': continue
   elif cmd=='QUIT': return
   elif not registered:
    await send(writer,':huddle 451 * :You have not registered')
   elif cmd in ('JOIN','NAMES','TOPIC'):
    target=(ps[1] if len(ps)>1 else '').lstrip(':'); r=channel(c,target)
    if not r or (r['is_private'] and not c.execute('SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?',(r['id'],uid)).fetchone()):
     await send(writer,f':huddle 403 {nick} {target} :No such channel'); continue
    if cmd=='JOIN':
     c.execute('INSERT OR IGNORE INTO channel_members VALUES(?,?,?)',(r['id'],uid,0)); c.commit(); head=r['last_event_id']; joined[r['id']]=head; targets[r['id']]=target
     await send(writer,f':{nick}!{nick}@huddle JOIN {target}')
    if cmd in ('JOIN','TOPIC'):
     if r['topic']: await send(writer,f':huddle 332 {nick} {target} :{r["topic"]}')
     else: await send(writer,f':huddle 331 {nick} {target} :No topic is set')
    names=' '.join(x['username'] for x in c.execute('SELECT u.username FROM users u JOIN channel_members m ON m.user_id=u.id WHERE m.channel_id=?',(r['id'],)))
    await send(writer,f':huddle 353 {nick} = {target} :{names}'); await send(writer,f':huddle 366 {nick} {target} :End of /NAMES list')
   elif cmd=='WHO':
    await send(writer,f':huddle 352 {nick} * {nick} huddle huddle {nick} H :0 {nick}')
    await send(writer,f':huddle 315 {nick} {arg} :End of WHO list')
   elif cmd=='LIST':
    await send(writer,f':huddle 321 {nick} Channel :Users Name')
    for z in c.execute("SELECT w.slug,ch.name FROM channels ch JOIN workspaces w ON w.id=ch.workspace_id WHERE ch.is_private=0 AND ch.is_dm=0"):
     await send(writer,f':huddle 322 {nick} #{z["slug"]}/{z["name"]} 1 :Huddle channel')
    await send(writer,f':huddle 323 {nick} :End of LIST')
   elif cmd=='MODE':
    if not arg.strip() or arg.strip().lower()==(nick or '').lower(): await send(writer,f':huddle 221 {nick} +i')
    else: await send(writer,f':huddle 324 {nick} {arg} +')
   elif cmd=='PRIVMSG':
    target=ps[1] if len(ps)>1 else ''; body=line.split(' :',1)[1] if ' :' in line else ''
    r=channel(c,target)
    if not r or r['id'] not in joined: await send(writer,f':huddle 442 {nick} {target} :You are not on that channel'); continue
    t=__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z')
    mid=c.execute('INSERT INTO messages(channel_id,author_id,body,created_at,mentions) VALUES(?,?,?,?,?)',(r['id'],uid,body,t,'[]')).lastrowid
    eid=r['last_event_id']+1; c.execute('UPDATE channels SET last_event_id=? WHERE id=?',(eid,r['id'])); payload=json.dumps({'message':{'id':mid,'channel_id':r['id'],'author_id':uid,'body':body},'irc_origin':True}); c.execute('INSERT INTO events(channel_id,event_id,kind,data,created_at) VALUES(?,?,?,?,?)',(r['id'],eid,'message.created',payload,t)); c.commit(); joined[r['id']]=eid
   else: await send(writer,f':huddle 421 {nick or "*"} {cmd} :Unknown command')
 try:
  task=asyncio.create_task(poll()); await commands()
 finally:
  stop.set()
  if nick and clients.get(nick.lower(),(None,None))[1] is writer: del clients[nick.lower()]
  writer.close(); await writer.wait_closed(); c.close()
async def main():
 s=await asyncio.start_server(client,'0.0.0.0',6667)
 async with s: await s.serve_forever()
asyncio.run(main())
