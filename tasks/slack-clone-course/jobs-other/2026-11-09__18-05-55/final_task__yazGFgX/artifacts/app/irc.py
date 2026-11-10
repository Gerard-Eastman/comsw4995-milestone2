import asyncio, json, shlex
from db import connect, now_iso
from common import emit_event, user_to_json
from routes_messages import obj
NICKS={}
CLIENTS=[]
def send(w,s): w.write((s+'\r\n').encode()); return w.drain()
def channel(name):
 if not name.startswith('#') or name.count('/')!=1:return None
 slug,n=name[1:].split('/')
 return connect().execute('SELECT c.*,w.slug,w.name wsname FROM channels c JOIN workspaces w ON w.id=c.workspace_id WHERE w.slug=? AND c.name=? AND c.is_dm=0',(slug,n)).fetchone()
def readable(ch,uid):
 c=connect()
 return bool(c.execute('SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?',(ch['id'],uid)).fetchone() or (not ch['is_private'] and c.execute('SELECT 1 FROM members WHERE workspace_id=? AND user_id=?',(ch['workspace_id'],uid)).fetchone()))
async def register(x):
 if x.get('registered') or not x.get('nick') or not x.get('user'): return
 r=connect().execute('SELECT u.* FROM users u JOIN tokens t ON t.user_id=u.id WHERE t.token=?',(x.get('pass',''),)).fetchone()
 if not r:
  await send(x['w'],':huddle 464 * :Password incorrect'); x['closed']=True; return
 x.update(registered=True,uid=r['id'],username=r['username'])
 for n in ('001','002','003','004','005'):
  await send(x['w'],f':huddle {n} {x["nick"]} :Welcome to Huddle, {x["nick"]}')
 await send(x['w'],f':huddle 422 {x["nick"]} :MOTD File is missing')
async def names(x,ch):
 c=connect(); names=[]
 for r in c.execute('SELECT u.username FROM users u JOIN channel_members m ON m.user_id=u.id WHERE m.channel_id=?',(ch['id'],)):
  names.append(x['nick'] if r['username']==x['username'] else r['username'])
 name='#'+ch['slug']+'/'+ch['name']
 await send(x['w'],f':huddle 353 {x["nick"]} = {name} :{" ".join(names)}')
 await send(x['w'],f':huddle 366 {x["nick"]} {name} :End of /NAMES list')
async def client(reader,w):
 x={'w':w,'nick':None,'username':None,'pass':None,'user':None,'joined':set(),'selfmsgs':set(),'seen':{},'closed':False}; CLIENTS.append(x)
 try:
  while not reader.at_eof() and not x['closed']:
   line=(await reader.readline()).decode(errors='ignore').strip('\r\n')
   if not line: continue
   a=line.split(' ',1); cmd=a[0].upper(); rest=a[1] if len(a)>1 else ''
   if cmd=='PASS':
    x['pass']=rest.strip(); await register(x)
   elif cmd=='NICK':
    nick=rest.strip()
    if nick.lower() in NICKS and NICKS[nick.lower()] is not x:
     await send(w,f':huddle 433 * {nick} :Nickname is already in use'); continue
    if x.get('nick'): NICKS.pop(x['nick'].lower(),None)
    x['nick']=nick; NICKS[nick.lower()]=x; await register(x)
   elif cmd=='USER': x['user']=rest; await register(x)
   elif cmd=='PING': await send(w,':huddle PONG huddle :'+rest.lstrip(':'))
   elif cmd=='PONG': pass
   elif cmd=='QUIT': break
   elif not x.get('registered'):
    if cmd in ('NICK','USER','PASS'): await register(x)
    else: await send(w,':huddle 451 * :You have not registered')
   elif cmd=='JOIN':
    nm=rest.split()[0] if rest else ''; ch=channel(nm)
    if not ch or not readable(ch,x['uid']):
     await send(w,f':huddle 403 {x["nick"]} {nm} :No such channel'); continue
    c=connect()
    if not c.execute('SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?',(ch['id'],x['uid'])).fetchone():
     c.execute('INSERT OR IGNORE INTO members VALUES(?,?,?)',(ch['workspace_id'],x['uid'],'member')); c.execute('INSERT OR IGNORE INTO channel_members VALUES(?,?)',(ch['id'],x['uid']))
     emit_event(ch['id'],'member.joined',{'user_id':x['uid']})
    x['joined'].add(ch['id']); x['seen'][ch['id']]=connect().execute('SELECT COALESCE(MAX(event_id),0) n FROM events WHERE channel_id=?',(ch['id'],)).fetchone()['n']; prefix=f':{x["nick"]}!{x["username"]}@huddle'
    await send(w,f'{prefix} JOIN {nm}')
    await send(w,f':huddle 332 {x["nick"]} {nm} :{ch["topic"]}' if ch['topic'] else f':huddle 331 {x["nick"]} {nm} :No topic is set')
    await names(x,ch); 
   elif cmd in ('NAMES','TOPIC','WHO','MODE'):
    nm=rest.split()[0] if rest else ''; ch=channel(nm) if nm.startswith('#') else None
    if cmd=='MODE':
     await send(w,f':huddle 324 {x["nick"]} {nm} +' if ch else f':huddle 221 {x["nick"]} +')
    elif ch and readable(ch,x['uid']):
     if cmd=='NAMES': await names(x,ch)
     elif cmd=='TOPIC': await send(w,f':huddle 332 {x["nick"]} {nm} :{ch["topic"]}' if ch['topic'] else f':huddle 331 {x["nick"]} {nm} :No topic is set')
     elif cmd=='WHO':
      for mr in connect().execute('SELECT u.username FROM users u JOIN channel_members m ON m.user_id=u.id WHERE m.channel_id=?',(ch['id'],)):
       await send(w,f':huddle 352 {x["nick"]} {nm} {mr["username"]} huddle huddle {mr["username"]} H :0 {mr["username"]}')
      await send(w,f':huddle 315 {x["nick"]} {nm} :End of WHO list')
    else: await send(w,f':huddle 315 {x["nick"]} {nm} :End of WHO list')
   elif cmd=='PRIVMSG':
    if ' :' in rest: nm,text=rest.split(' :',1)
    else: nm,text=rest.split(' ',1) if ' ' in rest else (rest,'')
    ch=channel(nm)
    if not ch or ch['id'] not in x['joined']: await send(w,f':huddle 442 {x["nick"]} {nm} :You\'re not on that channel'); continue
    c=connect(); c.execute('INSERT INTO messages(channel_id,author_id,body,created_at,mentions) VALUES(?,?,?,?,?)',(ch['id'],x['uid'],text,now_iso(),'[]'))
    r=c.execute('SELECT * FROM messages WHERE id=last_insert_rowid()').fetchone(); o=obj(r); eid=emit_event(ch['id'],'message.created',{'message':o}); c.execute('UPDATE messages SET event_id=? WHERE id=?',(eid,r['id'])); x['selfmsgs'].add(r['id'])
   elif cmd=='LIST':
    await send(w,f':huddle 321 {x["nick"]} Channel :Users Name')
    for ch in connect().execute('SELECT c.*,w.slug FROM channels c JOIN workspaces w ON w.id=c.workspace_id WHERE c.is_dm=0'):
     if readable(ch,x['uid']): await send(w,f':huddle 322 {x["nick"]} #{ch["slug"]}/{ch["name"]} 0 :{ch["topic"]}')
    await send(w,f':huddle 323 {x["nick"]} :End of LIST')
   else: await send(w,f':huddle 421 {x["nick"]} {cmd} :Unknown command')
 finally:
  if x.get('nick'): NICKS.pop(x['nick'].lower(),None)
  CLIENTS.remove(x) if x in CLIENTS else None; w.close(); await w.wait_closed()
async def pump():
 while True:
  c=connect()
  for x in list(CLIENTS):
   for cid in list(x['joined']):
    last=x['seen'].get(cid,0); rows=c.execute('SELECT * FROM events WHERE channel_id=? AND event_id>? ORDER BY event_id',(cid,last)).fetchall()
    for e in rows:
     x['seen'][cid]=e['event_id']
     if e['kind']!='message.created': continue
     d=json.loads(e['data']); m=d.get('message',{}); 
     if m.get('id') in x['selfmsgs']: continue
     ch=c.execute('SELECT c.*,w.slug FROM channels c JOIN workspaces w ON w.id=c.workspace_id WHERE c.id=?',(cid,)).fetchone()
     if ch: await send(x['w'],f':{m.get("author",{}).get("username","user")}!{m.get("author",{}).get("username","user")}@huddle PRIVMSG #{ch["slug"]}/{ch["name"]} :{m.get("body","")}'.replace('\n',' '))
  await asyncio.sleep(.05)
async def main():
 server=await asyncio.start_server(client,'0.0.0.0',6667); asyncio.create_task(pump()); await server.serve_forever()
asyncio.run(main())
