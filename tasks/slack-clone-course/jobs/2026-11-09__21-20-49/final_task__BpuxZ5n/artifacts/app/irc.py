import asyncio,sqlite3,json,time
DB='/app/huddle.db'; nicks={}; clients=[]
def conn():
 c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; return c
def user_for(t):
 c=conn(); x=c.execute('SELECT u.* FROM tokens t JOIN users u ON u.id=t.user_id WHERE t.token=?',(t,)).fetchone(); c.close(); return x
def chan(name):
 if not name.startswith('#') or '/' not in name[1:]: return None
 slug,cn=name[1:].split('/',1); c=conn()
 x=c.execute('SELECT c.*,w.slug,w.name workspace_name FROM channels c JOIN workspaces w ON w.id=c.workspace_id WHERE w.slug=? AND c.name=? AND c.is_dm=0',(slug,cn)).fetchone(); c.close(); return x
def members(cid):
 c=conn(); a=c.execute('SELECT u.username FROM cmembers m JOIN users u ON u.id=m.user_id WHERE m.channel_id=? ORDER BY u.username',(cid,)).fetchall(); c.close(); return [x['username'] for x in a]
def add_event(cid,typ,payload):
 c=conn(); e=c.execute('SELECT coalesce(max(event_id),0)+1 n FROM events WHERE channel_id=?',(cid,))['n'] if False else c.execute('SELECT coalesce(max(event_id),0)+1 n FROM events WHERE channel_id=?',(cid,)).fetchone()['n']
 payload.update({'type':typ,'event_id':e,'channel_id':cid})
 c.execute('INSERT INTO events VALUES(?,?,?,?)',(cid,e,typ,json.dumps(payload))); c.commit(); c.close(); return e
async def client(r,w):
 nick=None; user=None; passed=False; registered=False; joined={}; cursors={}
 clients.append((w,joined,cursors))
 async def send(x):
  if not w.is_closing(): w.write((x+'\r\n').encode()); await w.drain()
 async def poll():
  while not w.is_closing():
   try:
    for name,cid in list(joined.items()):
     c=conn(); rows=c.execute('SELECT event_id,payload FROM events WHERE channel_id=? AND event_id>? ORDER BY event_id',(cid,cursors.get(cid,0))).fetchall(); c.close()
     for row in rows:
      cursors[cid]=row['event_id']; p=json.loads(row['payload'])
      if p.get('type')=='message.created' and not (p.get('source')=='irc' and p.get('message',{}).get('author_id')==user['id']):
       await send(f":{p['message'].get('author',{}).get('username','huddle')}!{p['message'].get('author',{}).get('username','huddle')}@huddle PRIVMSG {name} :{p['message'].get('body','')}")
    await asyncio.sleep(.08)
   except: return
 task=asyncio.create_task(poll())
 try:
  while not r.at_eof():
   raw=await r.readline()
   if not raw: break
   line=raw.decode(errors='ignore').rstrip('\r\n'); p=line.split(' ',2); cmd=p[0].upper(); args=p[1:]
   if cmd=='PASS':
    user=user_for(args[0] if args else ''); passed=bool(user)
    if not passed: await send(':huddle 464 * :Password incorrect'); return
   elif cmd=='NICK':
    nn=args[0] if args else ''
    if nn.lower() in nicks and (not nick or nick.lower()!=nn.lower()): await send(f':huddle 433 * {nn} :Nickname is already in use'); continue
    if nick:nicks.pop(nick.lower(),None)
    nick=nn
   elif cmd=='USER':
    if not passed: await send(':huddle 464 * :Password incorrect'); return
    if not nick: await send(':huddle 451 * :You have not registered'); continue
    registered=True; nicks[nick.lower()]=w
    for n,t in [('001','Welcome to Huddle'),('002','Your host is huddle'),('003','This server was created today'),('004','huddle huddle 1 2 3 4 5'),('005','NETWORK=huddle CHANTYPES=#')]:
     await send(f':huddle {n} {nick} :{t}')
    await send(f':huddle 422 {nick} :MOTD File is missing')
   elif cmd=='QUIT': return
   elif not registered: await send(f':huddle 451 * :You have not registered')
   elif cmd=='PING': await send(f':huddle PONG huddle :{args[-1] if args else ""}')
   elif cmd=='PONG': pass
   elif cmd in ('JOIN','NAMES','TOPIC','WHO','MODE','LIST'):
    name=args[0] if args else ''
    if cmd=='MODE' and not name.startswith('#'):
     await send(f':huddle 221 {nick} +i'); continue
    c=chan(name)
    if cmd=='LIST':
     await send(f':huddle 321 {nick} Channel :Users Name')
     cc=conn(); rows=cc.execute('SELECT w.slug,c.name FROM channels c JOIN workspaces w ON w.id=c.workspace_id WHERE c.is_dm=0').fetchall();cc.close()
     for x in rows: await send(f':huddle 322 {nick} #{x["slug"]}/{x["name"]} 0 :')
     await send(f':huddle 323 {nick} :End of LIST'); continue
    if not c:
     await send(f':huddle 403 {nick} {name} :No such channel'); continue
    cname=f'#{c["slug"]}/{c["name"]}'
    if cmd=='JOIN':
     cc=conn(); ok=cc.execute('SELECT 1 FROM cmembers WHERE channel_id=? AND user_id=?',(c['id'],user['id'])).fetchone();cc.close()
     if not ok: await send(f':huddle 403 {nick} {name} :Cannot join channel'); continue
     joined[cname]=c['id']; cursors[c['id']]=conn().execute('SELECT coalesce(max(event_id),0) n FROM events WHERE channel_id=?',(c['id'],)).fetchone()['n']
     await send(f':{nick}!{nick}@huddle JOIN {cname}')
     await send(f':huddle 331 {nick} {cname} :No topic')
     await send(f':huddle 353 {nick} = {cname} :{" ".join(members(c["id"]))}')
     await send(f':huddle 366 {nick} {cname} :End of NAMES')
    elif cmd=='NAMES':
     await send(f':huddle 353 {nick} = {cname} :{" ".join(members(c["id"]))}'); await send(f':huddle 366 {nick} {cname} :End of NAMES')
    elif cmd=='TOPIC': await send(f':huddle 331 {nick} {cname} :No topic')
    elif cmd=='WHO': await send(f':huddle 352 {nick} {cname} {nick} huddle huddle {nick} H :0 {nick}'); await send(f':huddle 315 {nick} {cname} :End of WHO list')
    elif cmd=='MODE': await send(f':huddle 324 {nick} {cname} +nt')
   elif cmd=='LIST':
    await send(f':huddle 321 {nick} Channel :Users Name')
    cc=conn(); rows=cc.execute('SELECT w.slug,c.name FROM channels c JOIN workspaces w ON w.id=c.workspace_id WHERE c.is_dm=0').fetchall(); cc.close()
    for x in rows: await send(f':huddle 322 {nick} #{x["slug"]}/{x["name"]} 0 :')
    await send(f':huddle 323 {nick} :End of LIST')
   elif cmd=='PRIVMSG':
    target=args[0] if args else ''; text=(args[1] if len(args)>1 else '').lstrip(':'); c=chan(target)
    if not c: await send(f':huddle 403 {nick} {target} :No such channel'); continue
    if target not in joined: await send(f':huddle 442 {nick} {target} :You are not on that channel'); continue
    db=conn(); mid=db.execute('INSERT INTO messages(channel_id,author_id,body,created_at) VALUES(?,?,?,?)',(c['id'],user['id'],text,time.strftime('%Y-%m-%dT%H:%M:%SZ'))).lastrowid; m=db.execute('SELECT * FROM messages WHERE id=?',(mid,)).fetchone(); db.commit(); db.close()
    add_event(c['id'],'message.created',{'source':'irc','message':{'id':mid,'channel_id':c['id'],'author_id':user['id'],'body':text,'parent_id':None,'reply_count':0,'created_at':m['created_at'],'edited_at':None,'files':[],'reactions':[],'mentions':[],'author':{'id':user['id'],'username':user['username']}}})
   else: await send(f':huddle 421 {nick} {cmd} :Unknown command')
 finally:
  task.cancel(); clients[:] = [x for x in clients if x[0] is not w]
  if nick:nicks.pop(nick.lower(),None)
  w.close()
async def main():
 s=await asyncio.start_server(client,'0.0.0.0',6667)
 async with s: await s.serve_forever()
asyncio.run(main())
