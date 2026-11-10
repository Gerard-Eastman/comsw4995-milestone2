import asyncio,sys,json
sys.path.insert(0,'/app')
import db
NICKS={}; CLIENTS={}; LAST={}
async def send(w,line):
 w.write((':huddle '+line+'\r\n').encode()); await w.drain()
async def broadcast():
 while True:
  await asyncio.sleep(.1); c=db.connect()
  for cid,clients in list(CLIENTS.items()):
   for e in c.execute('SELECT * FROM events WHERE channel_id=? AND event_id>? ORDER BY event_id',(cid,LAST.get(cid,0))):
    LAST[cid]=e['event_id']
    if e['kind']!='message.created':continue
    try:
     d=json.loads(e['payload']);m=d.get('message',{}); au=c.execute('SELECT username FROM users WHERE id=?',(m.get('author_id'),)).fetchone(); z=c.execute('SELECT w.slug,c.name FROM channels c JOIN workspaces w ON w.id=c.workspace_id WHERE c.id=?',(cid,)).fetchone()
     if au and z:
      for w,n in list(clients):
       if d.get('source')=='irc' and n==au[0]: continue
       if not w.is_closing():
        w.write(f':{au[0]}!{au[0]}@huddle PRIVMSG #{z[0]}/{z[1]} :{m.get("body","")}\r\n'.encode()); await w.drain()
    except Exception: pass
  c.close()
async def handle_client(r,w):
 c=db.connect(); nick=None;uid=None;passed=None;registered=False;joined={}
 async def register():
  nonlocal uid,registered
  if not passed:
   await send(w,f'464 {nick or "*"} :Password incorrect');return False
  x=c.execute('SELECT u.id FROM tokens t JOIN users u ON u.id=t.user_id WHERE t.token=?',(passed,)).fetchone()
  if not x:
   await send(w,f'464 {nick or "*"} :Password incorrect');return False
  uid=x[0];registered=True
  texts=['Welcome to Huddle, '+nick,'Your host is huddle','This server was created today','huddle huddle aiohttp','CHANTYPES=# :are supported by this server']
  for n,t in zip(['001','002','003','004','005'],texts):await send(w,f'{n} {nick} :{t}')
  await send(w,f'422 {nick} :MOTD File is missing');return True
 try:
  while True:
   line=await r.readline()
   if not line:break
   line=line.decode(errors='replace').strip('\r\n')
   if not line:break
   q=line.split(' ',1);cmd=q[0].upper();rest=q[1] if len(q)>1 else ''
   if cmd=='PASS':passed=rest.lstrip(':');continue
   if cmd=='PING':await send(w,'PONG huddle :'+rest.lstrip(':'));continue
   if cmd in ('PONG',):continue
   if cmd=='QUIT':break
   if cmd=='NICK':
    nn=rest.split()[0] if rest else ''
    if nn.lower() in NICKS and NICKS[nn.lower()] is not w:await send(w,f'433 * {nn} :Nickname is already in use');continue
    if nick:NICKS.pop(nick.lower(),None)
    nick=nn;NICKS[nick.lower()]=w;continue
   if cmd=='USER':
    if not registered and nick and not await register():break
    continue
   if not registered:await send(w,f'421 {nick or "*"} {cmd} :Unknown command' if cmd not in ('JOIN','NAMES','TOPIC','WHO','LIST','MODE','PRIVMSG') else f'451 * :You have not registered');continue
   if cmd in ('JOIN','NAMES','TOPIC'):
    target=rest.split()[0] if rest else ''
    if not target.startswith('#') or '/' not in target:
     if cmd=='JOIN':await send(w,f'403 {nick} {target} :No such channel')
     continue
    slug,name=target[1:].split('/',1);x=c.execute('SELECT c.*,w.slug FROM channels c JOIN workspaces w ON w.id=c.workspace_id WHERE w.slug=? AND c.name=? AND c.is_dm=0',(slug,name)).fetchone()
    if not x or (cmd=='JOIN' and x['is_private'] and not c.execute('SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?',(x['id'],uid)).fetchone()):
     await send(w,f'403 {nick} {target} :No such channel');continue
    if cmd=='TOPIC':
     await send(w,f'332 {nick} {target} :{x["topic"]}' if x['topic'] else f'331 {nick} {target} :No topic is set');continue
    names=' '.join(z[0] for z in c.execute('SELECT u.username FROM users u JOIN channel_members cm ON cm.user_id=u.id WHERE cm.channel_id=?',(x['id'],)))
    if cmd=='NAMES':await send(w,f'353 {nick} = {target} :{names}');await send(w,f'366 {nick} {target} :End of NAMES list');continue
    joined[x['id']]=target;CLIENTS.setdefault(x['id'],[]).append((w,nick));w.write(f':{nick}!{nick}@huddle JOIN {target}\r\n'.encode());await w.drain();await send(w,f'332 {nick} {target} :{x["topic"]}' if x['topic'] else f'331 {nick} {target} :No topic is set');await send(w,f'353 {nick} = {target} :{names}');await send(w,f'366 {nick} {target} :End of NAMES list');continue
   if cmd=='MODE':await send(w,f'221 {nick} +i' if not rest or rest.split()[0]==nick else f'324 {nick} {rest.split()[0]} +nt');continue
   if cmd=='WHO':await send(w,f'352 {nick} {rest} ~ {nick} huddle huddle {nick} H :0 {nick}');await send(w,f'315 {nick} {rest} :End of WHO list');continue
   if cmd=='LIST':
    await send(w,f'321 {nick} Channel :Users Name')
    for zz in c.execute('SELECT w.slug,c.name FROM channels c JOIN workspaces w ON w.id=c.workspace_id WHERE c.is_dm=0'):
     await send(w,f'322 {nick} #{zz["slug"]}/{zz["name"]} :0')
    await send(w,f'323 {nick} :End of LIST');continue
   if cmd=='PRIVMSG':
    z=rest.split(' :',1);target=z[0];text=z[1] if len(z)>1 else ''
    if not target.startswith('#') or '/' not in target:continue
    slug,name=target[1:].split('/',1);x=c.execute('SELECT c.* FROM channels c JOIN workspaces w ON w.id=c.workspace_id WHERE w.slug=? AND c.name=?',(slug,name)).fetchone()
    if not x:await send(w,f'403 {nick} {target} :No such channel');continue
    if x['id'] not in joined:await send(w,f'442 {nick} {target} :You are not on that channel');continue
    c.execute('INSERT INTO messages(channel_id,author_id,body,created_at) VALUES(?,?,?,?)',(x['id'],uid,text,db.now_iso()));mid=c.execute('SELECT last_insert_rowid()').fetchone()[0];m={'id':mid,'channel_id':x['id'],'author_id':uid,'body':text};n=(c.execute('SELECT last_event_id FROM channels WHERE id=?',(x['id'],)).fetchone()[0] or 0)+1;c.execute('UPDATE channels SET last_event_id=? WHERE id=?',(n,x['id']));c.execute('INSERT INTO events(channel_id,event_id,kind,payload) VALUES(?,?,?,?)',(x['id'],n,'message.created',json.dumps({'message':m,'source':'irc'})))
   else:await send(w,f'421 {nick} {cmd} :Unknown command')
 finally:
  if nick:NICKS.pop(nick.lower(),None)
  for cid in joined:CLIENTS[cid]=[(ww,nn) for ww,nn in CLIENTS.get(cid,[]) if ww is not w]
  c.close();w.close()
async def main():
 s=await asyncio.start_server(handle_client,'0.0.0.0',6667);asyncio.create_task(broadcast())
 async with s:await s.serve_forever()
asyncio.run(main())
