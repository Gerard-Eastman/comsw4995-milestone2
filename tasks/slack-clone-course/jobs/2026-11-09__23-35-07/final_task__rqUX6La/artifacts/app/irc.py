import asyncio,db,json
from common import emit_event,message_json
NICKS={}; CLIENTS=[]
async def send(w,line): w.write((line+'\r\n').encode()); await w.drain()
def cname(c):
 w=db.CONN.execute('SELECT slug FROM workspaces WHERE id=?',(c['workspace_id'],)).fetchone()
 return '#'+w['slug']+'/'+c['name']
def find(name):
 if not name.startswith('#') or name.count('/')!=1:return None
 slug,ch=name[1:].split('/')
 return db.CONN.execute('SELECT c.* FROM channels c JOIN workspaces w ON w.id=c.workspace_id WHERE w.slug=? AND c.name=? AND c.is_dm=0',(slug,ch)).fetchone()
async def numerics(w,nick,c):
 name=cname(c); rows=db.CONN.execute('SELECT u.username FROM channel_members m JOIN users u ON u.id=m.user_id WHERE m.channel_id=?',(c['id'],)).fetchall()
 names=' '.join(x['username'] for x in rows)
 await send(w,f':huddle 353 {nick} = {name} :{names}')
 await send(w,f':huddle 366 {nick} {name} :End of /NAMES list')
async def client(r,w):
 nick=None;token=None;uid=None;got=False;reg=False;joined=set();own=set()
 client_state=(w,joined,own); CLIENTS.append(client_state)
 try:
  while not r.at_eof():
   z=await r.readline()
   if not z:break
   line=z.decode(errors='ignore').strip('\r\n'); ps=line.split(' ',1); cmd=ps[0].upper(); rest=ps[1] if len(ps)>1 else ''; a=rest.split()
   if cmd=='PASS': token=rest.strip()
   elif cmd=='NICK':
    n=a[0] if a else ''
    if n.lower() in NICKS and NICKS[n.lower()] is not w:
     await send(w,f':huddle 433 * {n} :Nickname is already in use');continue
    if nick:NICKS.pop(nick.lower(),None)
    nick=n;NICKS[n.lower()]=w
   elif cmd=='USER':got=True
   elif cmd=='PING':await send(w,':huddle PONG huddle :'+rest.lstrip(':'))
   elif cmd=='PONG':pass
   elif cmd=='QUIT':break
   elif not reg:
    await send(w,f':huddle 451 * :You have not registered');continue
   elif cmd=='JOIN':
    c=find(a[0]) if a else None
    if not c: await send(w,f':huddle 403 {nick} {a[0] if a else ""} :No such channel');continue
    mem=db.CONN.execute('SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?',(c['id'],uid)).fetchone()
    if c['is_private'] and not mem: await send(w,f':huddle 403 {nick} {a[0]} :No such channel');continue
    if not mem:
     db.CONN.execute('INSERT INTO channel_members VALUES(?,?)',(c['id'],uid));emit_event(c['id'],'member.joined',{'user_id':uid})
    joined.add(c['id']); name=cname(c)
    await send(w,f':{nick}!{nick}@huddle JOIN {name}')
    if c['topic']: await send(w,f':huddle 332 {nick} {name} :{c["topic"]}')
    else: await send(w,f':huddle 331 {nick} {name} :No topic is set')
    await numerics(w,nick,c)
   elif cmd=='NAMES':
    c=find(a[0]) if a else None
    if c: await numerics(w,nick,c)
   elif cmd=='TOPIC':
    c=find(a[0]) if a else None
    if c:
     if c['topic']: await send(w,f':huddle 332 {nick} {cname(c)} :{c["topic"]}')
     else: await send(w,f':huddle 331 {nick} {cname(c)} :No topic is set')
   elif cmd=='MODE':
    if a and a[0].startswith('#'): await send(w,f':huddle 324 {nick} {a[0]} +')
    else: await send(w,f':huddle 221 {nick} +')
   elif cmd=='WHO':
    c=find(a[0]) if a else None
    if c:
     for x in db.CONN.execute('SELECT u.username FROM channel_members m JOIN users u ON u.id=m.user_id WHERE m.channel_id=?',(c['id'],)):
      await send(w,f':huddle 352 {nick} {cname(c)} {x["username"]} huddle huddle {x["username"]} H :0 {x["username"]}')
     await send(w,f':huddle 315 {nick} {a[0]} :End of /WHO list')
   elif cmd=='LIST':
    await send(w,f':huddle 321 {nick} Channel :Users Name')
    for c in db.CONN.execute('SELECT c.*,w.slug FROM channels c JOIN workspaces w ON w.id=c.workspace_id JOIN workspace_members m ON m.workspace_id=w.id WHERE m.user_id=? AND c.is_dm=0 AND c.is_private=0',(uid,)):
     await send(w,f':huddle 322 {nick} {cname(c)} 0 :{c["topic"]}')
    await send(w,f':huddle 323 {nick} :End of /LIST')
   elif cmd=='PRIVMSG':
    name=a[0] if a else ''; c=find(name); body=rest.split(' :',1)[1] if ' :' in rest else ''
    if not c or c['id'] not in joined:
     await send(w,f":huddle 442 {nick} {name} :You're not on that channel");continue
    mid=db.CONN.execute('INSERT INTO messages(channel_id,author_id,body,created_at) VALUES(?,?,?,?)',(c['id'],uid,body,db.now_iso())).lastrowid
    obj=message_json(db.CONN.execute('SELECT * FROM messages WHERE id=?',(mid,)).fetchone());emit_event(c['id'],'message.created',{'message':obj});own.add(mid)
   elif cmd not in ('PASS',):
    await send(w,f':huddle 421 {nick} {cmd} :Unknown command')
   if nick and got and not reg:
    x=db.CONN.execute('SELECT user_id FROM tokens WHERE token=?',(token or '',)).fetchone()
    if not x:
     await send(w,f':huddle 464 {nick or "*"} :Password incorrect');return
    uid=x['user_id'];reg=True
    for n,t in [('001',f'Welcome to Huddle, {nick}'),('002','Your host is huddle'),('003','This server was created today'),('004','huddle'),('005','CHANTYPES=#')]:await send(w,f':huddle {n} {nick} :{t}')
    await send(w,f':huddle 422 {nick} :MOTD File is missing')
 finally:
  if client_state in CLIENTS: CLIENTS.remove(client_state)
  if nick:NICKS.pop(nick.lower(),None)
  w.close()
async def pump():
 last=db.CONN.execute('SELECT COALESCE(MAX(seq),0) FROM events').fetchone()[0]
 while True:
  await asyncio.sleep(.05)
  for e in db.CONN.execute('SELECT seq,payload FROM events WHERE seq>? ORDER BY seq',(last,)):
   last=e['seq']; p=json.loads(e['payload'])
   if p['type']!='message.created':continue
   m=p.get('message',{}); mid=m.get('id'); c=db.CONN.execute('SELECT * FROM channels WHERE id=?',(p['channel_id'],)).fetchone()
   if not c:continue
   u=db.CONN.execute('SELECT username FROM users WHERE id=?',(m.get('author_id'),)).fetchone()
   for w,j,o in list(CLIENTS):
    if c['id'] in j and mid not in o:
     try: await send(w,f':{u["username"]}!{u["username"]}@huddle PRIVMSG {cname(c)} :{m.get("body","").replace(chr(10)," ")}')
     except:pass
async def main():
 db.CONN=db.connect();s=await asyncio.start_server(client,'0.0.0.0',6667);asyncio.create_task(pump())
 async with s:await s.serve_forever()
if __name__=='__main__':asyncio.run(main())
