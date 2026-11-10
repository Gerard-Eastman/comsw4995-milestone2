import asyncio,json
from db import connect,now_iso
from common import emit_event,user_to_json
NICKS={}; CLIENTS=set(); STATES={}
def send(w,line): w.write((line+'\r\n').encode())
async def flush(w): await w.drain()
def user_for(tok):
 c=connect();x=c.execute('SELECT u.* FROM tokens t JOIN users u ON u.id=t.user_id WHERE t.token=?',(tok,)).fetchone();c.close();return x
def find(name):
 if not name.startswith('#') or name.count('/')!=1:return None
 slug,cn=name[1:].split('/')
 c=connect();x=c.execute('SELECT ch.*,w.slug FROM channels ch JOIN workspaces w ON w.id=ch.workspace_id WHERE w.slug=? AND ch.name=? AND ch.is_dm=0',(slug,cn)).fetchone();c.close();return x
def prefix(n,u):return f':{n}!{u["username"]}@huddle'
async def client(reader,w):
 CLIENTS.add((reader,w)); nick='*'; user=None; token=None; joined=set(); sent=set(); registered=False; STATES[w]={'joined':joined,'sent':sent,'nick':nick,'user':None}
 async def reply(x):send(w,x);await flush(w)
 try:
  while True:
   raw=await reader.readline()
   if not raw:break
   line=raw.decode(errors='ignore').strip('\r\n'); parts=line.split(' ',1); cmd=parts[0].upper(); arg=parts[1] if len(parts)>1 else ''
   if cmd=='PASS':token=arg.lstrip(':');continue
   if cmd=='NICK':
    nn=arg.split()[0] if arg else ''
    if nn.lower() in NICKS and NICKS[nn.lower()] is not w: await reply(f':huddle 433 * {nn} :Nickname is already in use');continue
    if nick.lower() in NICKS:NICKS.pop(nick.lower(),None)
    nick=nn;NICKS[nick.lower()]=w;STATES[w]['nick']=nick;continue
   if cmd=='PING':await reply(':huddle PONG huddle :'+arg.lstrip(':'));continue
   if cmd=='PONG':continue
   if cmd=='QUIT':break
   if cmd=='USER':
    if not token or not user:
     user=user_for(token or '')
     if not user: await reply(f':huddle 464 {nick} :Password incorrect');break
    registered=True
    STATES[w]['user']=user
    for n,text in [('001',f'Welcome to Huddle, {nick}'),('002','Your host is huddle'),('003','This server was created today'),('004','huddle huddle 1.0'),('005','CHANTYPES=#')]:
     await reply(f':huddle {n} {nick} :{text}')
    await reply(f':huddle 422 {nick} :MOTD File is missing');continue
   if not registered:
    await reply(f':huddle 451 * :You have not registered');continue
   if cmd=='JOIN':
    nm=arg.split()[0] if arg else '';ch=find(nm)
    if not ch or (ch['is_private'] and not connect().execute('SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?',(ch['id'],user['id'])).fetchone()): await reply(f':huddle 403 {nick} {nm} :No such channel');continue
    c=connect();c.execute('INSERT OR IGNORE INTO channel_members VALUES(?,?)',(ch['id'],user['id']));c.close();joined.add(ch['id']);STATES[w]['joined']=joined
    await reply(f'{prefix(nick,user)} JOIN {nm}')
    await reply(f':huddle 331 {nick} {nm} :No topic is set' if not ch['topic'] else f':huddle 332 {nick} {nm} :{ch["topic"]}')
    c=connect();names=[nick if z[0]==user['id'] else (c.execute('SELECT username FROM users WHERE id=?',(z[0],)).fetchone()[0]) for z in c.execute('SELECT user_id FROM channel_members WHERE channel_id=?',(ch['id'],)).fetchall()];c.close()
    await reply(f':huddle 353 {nick} = {nm} :{" ".join(names)}');await reply(f':huddle 366 {nick} {nm} :End of /NAMES list');continue
   if cmd in ('NAMES','TOPIC','MODE','WHO','LIST'):
    nm=arg.split()[0] if arg else ''
    if cmd=='MODE': await reply(f':huddle 221 {nick} +' if not nm or not nm.startswith('#') else f':huddle 324 {nick} {nm} +');continue
    ch=find(nm) if nm else None
    if cmd=='LIST':
     await reply(f':huddle 321 {nick} Channel :Users Name')
     c2=connect(); rows2=c2.execute('SELECT ch.name,w.slug,ch.topic,(SELECT count(*) FROM channel_members cm WHERE cm.channel_id=ch.id) FROM channels ch JOIN workspaces w ON w.id=ch.workspace_id JOIN memberships wm ON wm.workspace_id=w.id WHERE wm.user_id=? AND ch.is_dm=0 AND ch.is_archived=0 GROUP BY ch.id',(user['id'],)).fetchall();c2.close()
     for rr in rows2: await reply(f':huddle 322 {nick} #{rr[1]}/{rr[0]} {rr[3]} :{rr[2] or ""}')
     await reply(f':huddle 323 {nick} :End of /LIST')
    elif cmd=='TOPIC' and ch: await reply(f':huddle 331 {nick} {nm} :No topic is set' if not ch['topic'] else f':huddle 332 {nick} {nm} :{ch["topic"]}')
    elif cmd=='NAMES' and ch: await reply(f':huddle 353 {nick} = {nm} :');await reply(f':huddle 366 {nick} {nm} :End of /NAMES list')
    elif cmd=='WHO' and ch:
     c2=connect(); rows2=c2.execute('SELECT u.username FROM users u JOIN channel_members cm ON cm.user_id=u.id WHERE cm.channel_id=?',(ch['id'],)).fetchall();c2.close()
     if not rows2: rows2=[(user['username'],)]
     for rr in rows2: await reply(f':huddle 352 {nick} {nm} {rr[0]} huddle huddle {rr[0]} H :0 {rr[0]}')
     await reply(f':huddle 315 {nick} {nm} :End of WHO list')
    continue
   if cmd=='PRIVMSG':
    q=arg.split(' :',1); target=q[0].strip();body=q[1] if len(q)>1 else ''
    ch=find(target)
    if not ch or ch['id'] not in joined: await reply(f':huddle 442 {nick} {target} :You are not on that channel');continue
    c=connect();c.execute('INSERT INTO messages(channel_id,author_id,body,created_at,mentions) VALUES(?,?,?,?,?)',(ch['id'],user['id'],body,now_iso(),'[]'));mid=c.execute('SELECT last_insert_rowid()').fetchone()[0];m=c.execute('SELECT * FROM messages WHERE id=?',(mid,)).fetchone();c.close();sent.add(mid);STATES[w]['sent']=sent
    payload={'message':{'id':m['id'],'channel_id':ch['id'],'author_id':user['id'],'author':user_to_json(user),'body':body,'parent_id':None,'reply_count':0,'created_at':m['created_at'],'edited_at':None,'files':[],'reactions':[],'mentions':[]}}
    emit_event(ch['id'],'message.created',payload);continue
   await reply(f':huddle 421 {nick} {cmd} :Unknown command')
 finally:
  STATES.pop(w,None)
  if nick.lower() in NICKS and NICKS[nick.lower()] is w:NICKS.pop(nick.lower(),None)
  CLIENTS.discard((reader,w));w.close();await w.wait_closed()
async def pump():
 seen=0
 while True:
  c=connect();rows=c.execute('SELECT seq,payload FROM events WHERE seq>? ORDER BY seq',(seen,)).fetchall();seen=rows[-1]['seq'] if rows else seen;c.close()
  for z in rows:
   p=json.loads(z['payload'])
   if p.get('type')!='message.created':continue
   c=connect();ch=c.execute('SELECT ch.name,w.slug FROM channels ch JOIN workspaces w ON w.id=ch.workspace_id WHERE ch.id=?',(p['channel_id'],)).fetchone();u=c.execute('SELECT username FROM users WHERE id=?',(p['message']['author_id'],)).fetchone();c.close()
   if not ch:continue
   nm='#'+ch['slug']+'/'+ch['name'];body=p['message']['body']
   for r,w in list(CLIENTS):
    st=STATES.get(w,{})
    if p['message']['id'] in st.get('sent',set()) or p['channel_id'] not in st.get('joined',set()): continue
    try:send(w,f':{u["username"]}!{u["username"]}@huddle PRIVMSG {nm} :{body}');await w.drain()
    except:pass
  await asyncio.sleep(.05)
async def main():
 srv=await asyncio.start_server(client,'0.0.0.0',6667)
 asyncio.create_task(pump())
 async with srv:
  await srv.serve_forever()
asyncio.run(main())
