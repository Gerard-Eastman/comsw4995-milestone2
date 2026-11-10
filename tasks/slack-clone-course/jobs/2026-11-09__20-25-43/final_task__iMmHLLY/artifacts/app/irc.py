import asyncio,sqlite3,json
DB='/app/data/app.db'; nicks=set(); clients=[]
def con():
 c=sqlite3.connect(DB,timeout=10); c.row_factory=sqlite3.Row; return c
def user_for(t):
 c=con(); x=c.execute('SELECT u.* FROM tokens t JOIN users u ON u.id=t.user_id WHERE t.token=?',(t,)).fetchone(); c.close(); return x
async def out(w,s):
 try: w.write((s+'\r\n').encode()); await w.drain()
 except: pass
def chan(name):
 if name.count('/')!=1 or not name.startswith('#'): return None
 slug,n=name[1:].split('/')
 c=con(); x=c.execute('SELECT c.*,w.slug,w.owner_id FROM channels c JOIN workspaces w ON w.id=c.workspace_id WHERE w.slug=? AND c.name=? AND c.is_dm=0',(slug,n)).fetchone(); c.close(); return x
def cname(x): return '#'+x['slug']+'/'+x['name']
def names(cid):
 c=con(); rows=c.execute('SELECT u.username FROM channel_members m JOIN users u ON u.id=m.user_id WHERE m.channel_id=? ORDER BY u.username',(cid,)).fetchall(); c.close(); return ' '.join(x['username'] for x in rows)
async def registration(r,w,st):
 nick=st['nick']; uid=st['uid']
 for num,text in [('001','Welcome to Huddle IRC'),('002','Your host is huddle'),('003','This server was created today'),('004','huddle huddle 1.0 ao mtov'),('005','CHANTYPES=# PREFIX=(ov)@+ :are supported by this server'),('422','MOTD File is missing')]: await out(w,f':huddle {num} {nick} :{text}')
async def handle(r,w):
 st={'nick':None,'uid':None,'reg':False,'joined':set(),'own':set()}
 clients.append((w,st))
 try:
  while True:
   raw=await r.readline()
   if not raw: break
   x=raw.decode(errors='ignore').strip(); ps=x.split(); cmd=ps[0].upper() if ps else ''
   if cmd=='PASS':
    u=user_for(x[5:].strip() if len(x)>5 else '')
    if not u: await out(w,':huddle 464 * :Password incorrect'); return
    st['uid']=u['id']; st['username']=u['username']
   elif cmd=='NICK':
    if len(ps)<2: continue
    nn=ps[1]
    if any(q.lower()==nn.lower() for q in nicks) and (not st['nick'] or st['nick'].lower()!=nn.lower()):
     await out(w,f':huddle 433 * {nn} :Nickname is already in use'); continue
    if st['nick']: nicks.discard(st['nick'])
    st['nick']=nn
   elif cmd=='USER':
    if st['uid'] is None: await out(w,':huddle 464 * :Password incorrect'); return
    if st['nick'] and not st['reg']:
     st['reg']=True; nicks.add(st['nick']); await registration(r,w,st)
   elif cmd=='PING':
    arg=x.split(':',1)[1] if ':' in x else (ps[1] if len(ps)>1 else '')
    await out(w,f':huddle PONG huddle :{arg}')
   elif cmd=='PONG': pass
   elif cmd=='QUIT': return
   elif not st['reg']:
    await out(w,':huddle 451 * :You have not registered')
   elif cmd in ('JOIN','NAMES','TOPIC','WHO','LIST','MODE','PRIVMSG'):
    if cmd=='JOIN':
     nm=ps[1] if len(ps)>1 else ''; ch=chan(nm)
     if not ch: await out(w,f':huddle 403 {st["nick"]} {nm} :No such channel'); continue
     c=con(); mem=c.execute('SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?',(ch['id'],st['uid'])).fetchone()
     if not mem:
      if ch['is_private']: c.close(); await out(w,f':huddle 403 {st["nick"]} {nm} :No such channel'); continue
      c.execute('INSERT OR IGNORE INTO channel_members VALUES(?,?)',(ch['id'],st['uid'])); c.execute('INSERT OR IGNORE INTO members VALUES(?,?,?)',(ch['workspace_id'],st['uid'],'member')); c.commit()
     topic=ch['topic']; c.close(); st['joined'].add(ch['id'])
     await out(w,f':{st["nick"]}!{st["username"]}@huddle JOIN {nm}')
     await out(w,f':huddle {"332" if topic else "331"} {st["nick"]} {nm} :{topic or "No topic is set"}')
     await out(w,f':huddle 353 {st["nick"]} = {nm} :{names(ch["id"])}')
     await out(w,f':huddle 366 {st["nick"]} {nm} :End of /NAMES list')
    elif cmd in ('NAMES','TOPIC','WHO','MODE'):
     nm=ps[1] if len(ps)>1 else ''
     if cmd=='MODE' and not nm.startswith('#'): await out(w,f':huddle 221 {st["nick"]} +'); continue
     ch=chan(nm)
     if not ch: await out(w,f':huddle 403 {st["nick"]} {nm} :No such channel'); continue
     if cmd=='NAMES': await out(w,f':huddle 353 {st["nick"]} = {nm} :{names(ch["id"])}'); await out(w,f':huddle 366 {st["nick"]} {nm} :End of /NAMES list')
     elif cmd=='TOPIC': await out(w,f':huddle {"332" if ch["topic"] else "331"} {st["nick"]} {nm} :{ch["topic"] or "No topic is set"}')
     elif cmd=='MODE': await out(w,f':huddle 324 {st["nick"]} {nm} +')
     else:
      c=con(); rows=c.execute('SELECT u.username FROM channel_members m JOIN users u ON u.id=m.user_id WHERE m.channel_id=?',(ch['id'],)).fetchall(); c.close()
      for q in rows: await out(w,f':huddle 352 {st["nick"]} {nm} {q["username"]} huddle huddle {q["username"]} H :0 {q["username"]}')
      await out(w,f':huddle 315 {st["nick"]} {nm} :End of /WHO list')
    elif cmd=='LIST':
     await out(w,f':huddle 321 {st["nick"]} Channel :Users Name')
     c=con(); rows=c.execute('SELECT c.*,w.slug FROM channels c JOIN workspaces w ON w.id=c.workspace_id JOIN members m ON m.workspace_id=w.id WHERE m.user_id=? AND c.is_dm=0 GROUP BY c.id',(st['uid'],)).fetchall()
     for q in rows:
      count=c.execute('SELECT count(*) FROM channel_members WHERE channel_id=?',(q['id'],)).fetchone()[0]; await out(w,f':huddle 322 {st["nick"]} {cname(q)} {count} :{q["topic"] or ""}')
     c.close(); await out(w,f':huddle 323 {st["nick"]} :End of /LIST')
    elif cmd=='PRIVMSG':
     nm=ps[1] if len(ps)>1 else ''; body=x.split(' :',1)[1] if ' :' in x else ''
     ch=chan(nm)
     if not ch or ch['id'] not in st['joined']: await out(w,f':huddle 442 {st["nick"]} {nm} :You are not on that channel'); continue
     c=con(); c.execute('INSERT INTO messages(channel_id,author_id,body,created_at) VALUES(?,?,?,datetime("now"))',(ch['id'],st['uid'],body)); mid=c.execute('SELECT last_insert_rowid()').fetchone()[0]; z=c.execute('SELECT m.*,u.username FROM messages m JOIN users u ON u.id=m.author_id WHERE m.id=?',(mid,)).fetchone(); c.close()
     c=con(); c.execute('BEGIN IMMEDIATE'); c.execute('UPDATE channels SET last_event_id=last_event_id+1 WHERE id=?',(ch['id'],)); eid=c.execute('SELECT last_event_id FROM channels WHERE id=?',(ch['id'],)).fetchone()[0]; payload={'type':'message.created','event_id':eid,'channel_id':ch['id'],'message':{'id':mid,'channel_id':ch['id'],'author_id':st['uid'],'author':{'id':st['uid'],'username':st['username'],'display_name':st['username'],'timezone':'UTC','avatar_url':'','status_text':'','status_emoji':''},'body':body,'parent_id':None,'reply_count':0,'created_at':z['created_at'],'edited_at':None,'files':[],'reactions':[],'mentions':[]}}; c.execute('INSERT INTO events(channel_id,event_id,payload) VALUES(?,?,?)',(ch['id'],eid,json.dumps(payload))); c.commit(); c.close(); st['own'].add(mid)
   else:
    await out(w,f':huddle 421 {st["nick"]} {cmd} :Unknown command')
 finally:
  if st['nick']: nicks.discard(st['nick'])
  try: clients.remove((w,st))
  except: pass
  w.close()
async def pump():
 c=con(); seen=c.execute('SELECT COALESCE(MAX(seq),0) FROM events').fetchone()[0]; c.close()
 while True:
  await asyncio.sleep(.05); c=con(); rows=c.execute('SELECT seq,payload FROM events WHERE seq>? ORDER BY seq',(seen,)).fetchall(); c.close()
  for q in rows:
   seen=q['seq']; p=json.loads(q['payload'])
   if p.get('type')!='message.created': continue
   mid=p.get('message',{}).get('id'); ch=chan_by_id(p['channel_id'])
   if not ch: continue
   for w,st in list(clients):
    if p['channel_id'] in st['joined'] and mid not in st['own']:
     a=p['message'].get('author',{}).get('username','user'); b=p['message'].get('body','').replace('\n',' ')
     await out(w,f':{a}!{a}@huddle PRIVMSG {cname(ch)} :{b}')
def chan_by_id(cid):
 c=con(); x=c.execute('SELECT c.*,w.slug FROM channels c JOIN workspaces w ON w.id=c.workspace_id WHERE c.id=?',(cid,)).fetchone(); c.close(); return x
async def main():
 asyncio.create_task(pump()); s=await asyncio.start_server(handle,'0.0.0.0',6667)
 async with s: await s.serve_forever()
asyncio.run(main())
