import asyncio,shlex,json
from db import *
C=connect(); NICKS={}; CLIENTS={}
def send(w,s): w.write((s+'\r\n').encode()); return w.drain()
def auth(t):
 x=C.execute('select u.* from tokens t join users u on u.id=t.user_id where t.token=?',(t,)).fetchone(); return x
def chan(n):
 if not n.startswith('#') or n.count('/')!=1:return None
 a,b=n[1:].split('/')
 return C.execute('select c.*,w.slug,w.owner_id from channels c join workspaces w on w.id=c.workspace_id where w.slug=? and c.name=?',(a,b)).fetchone()
async def client(r,w):
 nick='*'; user=None; token=None; joined=set(); posted=set(); registered=False
 async def out(x): await send(w,':huddle '+x)
 try:
  while True:
   line=await r.readline()
   if not line: break
   z=line.decode(errors='ignore').strip('\r\n')
   if not z: continue
   p=z.split(' ',2); cmd=p[0].upper(); arg=p[1:] 
   if cmd=='PASS': token=arg[0] if arg else ''
   elif cmd=='PING': await out('PONG huddle :'+(arg[0] if arg else '')); continue
   elif cmd=='PONG': continue
   elif cmd=='QUIT': break
   elif cmd=='NICK':
    n=arg[0] if arg else ''
    if n.lower() in NICKS and NICKS[n.lower()] is not w: await out('433 * '+n+' :Nickname is already in use'); continue
    nick=n
   elif cmd=='USER':
    user=auth(token or '')
    if not user: await out('464 '+nick+' :Password incorrect'); break
    registered=True; NICKS[nick.lower()]=w; CLIENTS[w]=(user,nick,joined,posted)
    for q in ['001 '+nick+' :Welcome to Huddle, '+nick,'002 '+nick+' :Your host is huddle','003 '+nick+' :This server was created today','004 '+nick+' huddle','005 '+nick+' :CHANTYPES=#','422 '+nick+' :MOTD File is missing']: await out(q)
   elif not registered:
    await out(('421 * '+cmd+' :Unknown command') if cmd not in ('JOIN','NAMES','TOPIC','WHO','LIST','MODE','PRIVMSG') else '451 * :You have not registered')
   elif cmd=='JOIN':
    name=arg[0] if arg else ''; c=chan(name)
    if not c or (c['is_private'] and not C.execute('select 1 from cmembers where channel_id=? and user_id=?',(c['id'],user['id'])).fetchone()): await out('403 '+nick+' '+name+' :No such channel'); continue
    C.execute('insert or ignore into cmembers values(?,?)',(c['id'],user['id'])); joined.add(c['id']); await out(nick+'!'+user['username']+'@huddle JOIN '+name)
    await out(('332 '+nick+' '+name+' :'+c['topic']) if c['topic'] else '331 '+nick+' '+name+' :No topic is set')
    names=[]
    for m in C.execute('select u.username from cmembers x join users u on u.id=x.user_id where x.channel_id=?',(c['id'],)): names.append(nick if m['username']==user['username'] else m['username'])
    await out('353 '+nick+' = '+name+' :'+ ' '.join(names)); await out('366 '+nick+' '+name+' :End of /NAMES list')
   elif cmd in ('NAMES','TOPIC','WHO','MODE','LIST'):
    name=arg[0] if arg else ''; c=chan(name) if name.startswith('#') else None
    if cmd=='LIST':
     await out('321 '+nick+' Channel :Users Name')
     for c in C.execute('select c.*,w.slug from channels c join workspaces w on w.id=c.workspace_id'): await out('322 '+nick+' #'+c['slug']+'/'+c['name']+' 0 :'+(c['topic'] or ''))
     await out('323 '+nick+' :End of /LIST')
    elif c:
     if cmd=='TOPIC': await out(('332 '+nick+' '+name+' :'+c['topic']) if c['topic'] else '331 '+nick+' '+name+' :No topic is set')
     elif cmd=='MODE': await out('324 '+nick+' '+name+' +')
     elif cmd=='WHO':
      for m in C.execute('select u.username from cmembers x join users u on u.id=x.user_id where x.channel_id=?',(c['id'],)): await out('352 '+nick+' '+name+' '+m['username']+' huddle huddle '+m['username']+' H :0 '+m['username'])
      await out('315 '+nick+' '+name+' :End of /WHO list')
     else:
      names=[m['username'] for m in C.execute('select u.username from cmembers x join users u on u.id=x.user_id where x.channel_id=?',(c['id'],))]
      await out('353 '+nick+' = '+name+' :'+ ' '.join(names)); await out('366 '+nick+' '+name+' :End of /NAMES list')
   elif cmd=='PRIVMSG':
    name=arg[0] if arg else ''; body=(arg[1] if len(arg)>1 else '').lstrip(':'); c=chan(name)
    if not c or c['id'] not in joined: await out("442 "+nick+" "+name+" :You are not on that channel"); continue
    C.execute('insert into messages(channel_id,author_id,body,created_at) values(?,?,?,?)',(c['id'],user['id'],body,now_iso())); i=C.execute('select last_insert_rowid()').fetchone()[0]; x=dict(C.execute('select * from messages where id=?',(i,)).fetchone()); x['author']=dict(C.execute('select * from users where id=?',(user['id'],)).fetchone()); x['files']=[]; x['reactions']=[]; x['parent_id']=None; x['reply_count']=0; posted.add(i); emit(c['id'],'message.created',{'message':x})
   else: await out('421 '+nick+' '+cmd+' :Unknown command')
 finally:
  if nick.lower() in NICKS and NICKS[nick.lower()] is w: del NICKS[nick.lower()]
  CLIENTS.pop(w,None); w.close()
async def pump():
 last=C.execute('select coalesce(max(seq),0) from events').fetchone()[0]
 while True:
  await asyncio.sleep(.05)
  for e in C.execute('select * from events where seq>? order by seq',(last,)):
   last=e['seq']; p=json.loads(e['payload'])
   if p.get('type')!='message.created': continue
   m=p.get('message',{}); c=C.execute('select c.*,w.slug from channels c join workspaces w on w.id=c.workspace_id where c.id=?',(p['channel_id'],)).fetchone()
   if not c: continue
   for w,(u,n,j,posted) in list(CLIENTS.items()):
    if c['id'] in j and m.get('id') not in posted:
     await send(w,':'+m.get('author',{}).get('username',u['username'])+'!'+m.get('author',{}).get('username',u['username'])+'@huddle PRIVMSG #'+c['slug']+'/'+c['name']+' :'+m.get('body','').replace('\\n',' '))
async def main():
 s=await asyncio.start_server(client,'0.0.0.0',6667)
 asyncio.create_task(pump())
 async with s:
  await s.serve_forever()
asyncio.run(main())
