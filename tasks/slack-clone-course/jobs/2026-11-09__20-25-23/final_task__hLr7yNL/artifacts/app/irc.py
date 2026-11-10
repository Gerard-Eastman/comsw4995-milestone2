import asyncio,json,shlex
from db import connect,now_iso
from common import emit_event,msg_json
NICKS={}; CLIENTS=[]
async def send(w,line):
 w.write(((line if line.startswith(':') else ':huddle '+line)+'\r\n').encode()); await w.drain()
def channel(name):
 c=connect()
 if not name.startswith('#') or name.count('/')!=1:c.close();return None
 slug,n=name[1:].split('/',1)
 x=c.execute('SELECT c.*,w.slug FROM channels c JOIN workspaces w ON w.id=c.workspace_id WHERE w.slug=? AND c.name=? AND c.is_dm=0',(slug,n)).fetchone();c.close();return x
def ircname(x): return '#'+x['slug']+'/'+x['name']
async def register(st,w):
 if st.get('registered') or not st.get('nick') or not st.get('user'): return
 c=connect();u=c.execute('SELECT u.* FROM users u JOIN tokens t ON t.user_id=u.id WHERE t.token=?',(st.get('pass',''),)).fetchone();c.close()
 if not u: await send(w,'464 * :Password incorrect');w.close();return
 st['uid']=u['id'];st['username']=u['username'];st['registered']=True;NICKS[st['nick'].lower()]=st
 for n in ('001','002','003','004','005'): await send(w,f'{n} {st["nick"]} :Welcome to Huddle')
 await send(w,f'422 {st["nick"]} :MOTD File is missing')
async def names(st,w,x):
 c=connect(); ms=c.execute('SELECT u.username FROM channel_members m JOIN users u ON u.id=m.user_id WHERE m.channel_id=?',(x['id'],)).fetchall();c.close()
 vals=[st['nick'] if a['username']==st['username'] else a['username'] for a in ms]
 await send(w,f'353 {st["nick"]} = {ircname(x)} :{" ".join(vals)}');await send(w,f'366 {st["nick"]} {ircname(x)} :End of /NAMES list')
async def join(st,w,name):
 x=channel(name)
 if not x: await send(w,f'403 {st.get("nick","*")} {name} :No such channel');return
 c=connect();ok=c.execute('SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?',(x['id'],st['uid'])).fetchone()
 if x['is_private'] and not ok:c.close();await send(w,f'403 {st["nick"]} {name} :No such channel');return
 if not ok:
  c.execute('INSERT OR IGNORE INTO workspace_members(workspace_id,user_id,role) VALUES(?,?,?)',(x['workspace_id'],st['uid'],'member'));c.execute('INSERT OR IGNORE INTO channel_members VALUES(?,?)',(x['id'],st['uid']));c.close();emit_event(x['id'],'member.joined',{'user_id':st['uid']})
 else:c.close()
 st['joined'].add(x['id']);await send(w,f':{st["nick"]}!{st["username"]}@huddle JOIN {name}')
 if x['topic']:await send(w,f'332 {st["nick"]} {name} :{x["topic"]}')
 else:await send(w,f'331 {st["nick"]} {name} :No topic is set')
 await names(st,w,x)
async def privmsg(st,w,name,text):
 x=channel(name)
 if not x or x['id'] not in st['joined']:await send(w,f'442 {st["nick"]} {name} :You\'re not on that channel');return
 c=connect();t=now_iso();c.execute('INSERT INTO messages(channel_id,author_id,body,created_at) VALUES(?,?,?,?)',(x['id'],st['uid'],text,t));mid=c.execute('SELECT last_insert_rowid()').fetchone()[0];m=c.execute('SELECT * FROM messages WHERE id=?',(mid,)).fetchone();out=msg_json(c,m);c.close();emit_event(x['id'],'message.created',{'message':out});st['mine'].add(mid)
async def handle_client(r,w):
 st={'nick':None,'user':None,'pass':'','joined':set(),'mine':set(),'registered':False,'_w':w};CLIENTS.append(st)
 try:
  while not r.at_eof():
   line=(await r.readline()).decode(errors='ignore').strip('\r\n')
   if not line:continue
   a=line.split(' ',1);cmd=a[0].upper();rest=a[1] if len(a)>1 else ''
   if cmd=='PASS':st['pass']=rest.lstrip(':');await register(st,w);continue
   if cmd=='NICK':
    n=rest.strip().lstrip(':')
    if n.lower() in NICKS and NICKS[n.lower()] is not st:await send(w,f'433 * {n} :Nickname is already in use');continue
    st['nick']=n;await register(st,w);continue
   if cmd=='USER':st['user']=rest;await register(st,w);continue
   if cmd=='PING':await send(w,'PONG huddle :'+rest.lstrip(':'));continue
   if cmd=='PONG':continue
   if cmd=='QUIT':break
   if not st['registered']:await send(w,f'451 * :You have not registered');continue
   if cmd=='JOIN':await join(st,w,rest.split()[0]);continue
   if cmd=='NAMES':x=channel(rest.split()[0]); await names(st,w,x) if x else send(w,f'403 {st["nick"]} {rest} :No such channel');continue
   if cmd=='PRIVMSG':
    z=rest.split(' :',1);await privmsg(st,w,z[0],z[1] if len(z)>1 else '');continue
   if cmd=='TOPIC':
    x=channel(rest)
    if x and x['topic']:await send(w,f'332 {st["nick"]} {rest} :{x["topic"]}')
    else:await send(w,f'331 {st["nick"]} {rest} :No topic is set')
    continue
   if cmd=='WHO':
    x=channel(rest)
    if x:
     c=connect(); ms=c.execute('SELECT u.username FROM channel_members m JOIN users u ON u.id=m.user_id WHERE m.channel_id=?',(x['id'],)).fetchall();c.close()
     for a in ms: await send(w,f'352 {st["nick"]} {rest} {a["username"]} huddle huddle {a["username"]} H :0 {a["username"]}')
    await send(w,f'315 {st["nick"]} {rest} :End of WHO list');continue
   if cmd=='LIST':
    await send(w,f'321 {st["nick"]} Channel :Users Name')
    c=connect(); rows=c.execute('SELECT c.*,w.slug,(SELECT count(*) FROM channel_members m WHERE m.channel_id=c.id) n FROM channels c JOIN workspaces w ON w.id=c.workspace_id WHERE c.is_dm=0').fetchall()
    for x in rows:
     if x['topic']: await send(w,f'322 {st["nick"]} {ircname(x)} {x["n"]} :{x["topic"]}')
     else: await send(w,f'322 {st["nick"]} {ircname(x)} {x["n"]} :')
    c.close();await send(w,f'323 {st["nick"]} :End of /LIST');continue
   if cmd=='MODE':
    target=rest.split()[0] if rest else st["nick"]
    if target.startswith('#'): await send(w,f'324 {st["nick"]} {target} +')
    else: await send(w,f'221 {st["nick"]} +')
    continue
   await send(w,f'421 {st["nick"]} {cmd} :Unknown command')
 finally:
  if st.get('nick'):NICKS.pop(st['nick'].lower(),None)
  if st in CLIENTS: CLIENTS.remove(st);w.close();await w.wait_closed()
async def pump():
 last=0;c=connect();last=c.execute('SELECT COALESCE(MAX(seq),0) FROM events').fetchone()[0];c.close()
 while True:
  c=connect()
  for x in c.execute('SELECT seq,payload,channel_id FROM events WHERE seq>? ORDER BY seq',(last,)):
   last=x['seq']
   try:p=json.loads(x['payload'])
   except:continue
   if p.get('type')!='message.created':continue
   m=p.get('message',{});body=str(m.get('body','')).replace('\n',' ');a=c.execute('SELECT username FROM users WHERE id=?',(m.get('author_id'),)).fetchone()
   ch=c.execute('SELECT c.*,w.slug FROM channels c JOIN workspaces w ON w.id=c.workspace_id WHERE c.id=?',(x['channel_id'],)).fetchone()
   if not a or not ch:continue
   for st in list(CLIENTS):
    if x['channel_id'] in st['joined'] and m.get('id') not in st['mine']:
     try:await send(st['_w'],f':{a["username"]}!{a["username"]}@huddle PRIVMSG {ircname(ch)} :{body}')
     except:pass
  c.close();await asyncio.sleep(.05)
async def main():
 s=await asyncio.start_server(handle_client,'0.0.0.0',6667)
 async with s: await asyncio.gather(s.serve_forever(),pump())
old=handle_client
async def wrapped(r,w):
 # attach writer for pump
 orig=handle_client
 st_task=asyncio.create_task(orig(r,w))
 await st_task
# inject writer into state by wrapping global client after creation is cumbersome; assign pump target from latest
# patch handle_client source behavior by a writer mapping
if __name__=='__main__': asyncio.run(main())
