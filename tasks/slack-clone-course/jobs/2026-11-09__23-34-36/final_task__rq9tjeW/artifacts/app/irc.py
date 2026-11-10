import asyncio,re,json
from db import connect,now_iso
from common import emit_event,user_by_id,channel_to_json
NICKS={}; CLIENTS=set()
class Client:
 def __init__(self,r,w): self.r=r;self.w=w;self.nick=None;self.user=None;self.passok=False;self.reg=False;self.chans=set(); self.seen={}
 async def send(self,s): self.w.write((s+'\r\n').encode());await self.w.drain()
 async def run(self):
  CLIENTS.add(self)
  try:
   while not self.w.is_closing():
    raw=await self.r.readline()
    if not raw: break
    line=raw.decode(errors='ignore').strip()
    if not line: continue
    await self.cmd(line)
  finally:
   if self.nick: NICKS.pop(self.nick.lower(),None)
   CLIENTS.discard(self)
   self.w.close()
 async def cmd(self,line):
  p=line.split(' ',2); cmd=p[0].upper(); arg=p[1] if len(p)>1 else ''; rest=p[2] if len(p)>2 else ''
  if cmd=='PASS':
   tok=arg; self.user=connect().execute('SELECT u.* FROM tokens t JOIN users u ON u.id=t.user_id WHERE t.token=?',(tok,)).fetchone()
   if not self.user: await self.send(':huddle 464 * :Password incorrect');self.w.close()
   else:self.passok=True
   return
  if cmd=='NICK':
   if not self.passok:
    await self.send(':huddle 464 * :Password incorrect'); self.w.close(); return
   n=arg.lstrip(':')
   if n.lower() in NICKS and NICKS[n.lower()] is not self: await self.send(f':huddle 433 * {n} :Nickname is already in use');return
   self.nick=n;NICKS[n.lower()]=self;await self.register();return
  if cmd=='USER':
   if not self.passok: await self.send(':huddle 464 * :Password incorrect'); self.w.close(); return
   self.userhost=arg.split()[0] if arg else self.nick;await self.register();return
  if cmd=='PING': await self.send(':huddle PONG huddle :'+(rest.lstrip(':') or arg));return
  if cmd=='PONG': return
  if cmd=='QUIT': self.w.close();return
  if not self.reg: await self.send(':huddle 451 * :You have not registered');return
  if cmd=='WHO':
   target=arg or '*'
   await self.send(f':huddle 352 {self.nick} {target} huddle huddle {self.nick} H :0 {self.nick}')
   await self.send(f':huddle 315 {self.nick} {target} :End of /WHO list')
   return
  if cmd in ('JOIN','NAMES'):
   name=arg.split(',')[0]; ch=channel(name)
   if not ch: await self.send(f':huddle 403 {self.nick} {name} :No such channel');return
   if not member(ch['id'],self.user['id']): await self.send(f':huddle 403 {self.nick} {name} :Cannot join channel');return
   self.chans.add(ch['id']); h=connect().execute('SELECT last_event_id FROM channels WHERE id=?',(ch['id'],)).fetchone(); self.seen[ch['id']]=h[0] if h else 0
   await self.send(f':{self.nick}!{self.user["username"]}@huddle JOIN {name}')
   if ch['topic']: await self.send(f':huddle 332 {self.nick} {name} :{ch["topic"]}')
   else: await self.send(f':huddle 331 {self.nick} {name} :No topic is set')
   names=connect().execute('SELECT u.username FROM channel_members cm JOIN users u ON u.id=cm.user_id WHERE cm.channel_id=?',(ch['id'],)).fetchall()
   await self.send(f':huddle 353 {self.nick} = {name} :{" ".join(x[0] for x in names)}')
   await self.send(f':huddle 366 {self.nick} {name} :End of /NAMES list')
   return
  if cmd=='PRIVMSG':
   name=arg; body=rest[1:] if rest.startswith(':') else rest
   ch=channel(name)
   if not ch or ch['id'] not in self.chans: await self.send(f':huddle 442 {self.nick} {name} :You are not on that channel');return
   c=connect();c.execute('INSERT INTO messages(channel_id,author_id,body,created_at,mentions) VALUES(?,?,?,?,?)',(ch['id'],self.user['id'],body,now_iso(),'[]'))
   r=c.execute('SELECT * FROM messages WHERE id=last_insert_rowid()').fetchone()
   m={'id':r['id'],'channel_id':ch['id'],'author_id':self.user['id'],'body':body,'parent_id':None,'reply_count':0,'created_at':r['created_at'],'edited_at':None,'files':[],'reactions':[],'mentions':[],'author':dict(self.user)}
   eid=emit_event(ch['id'],'message.created',{'message':m,'source':'irc','source_nick':self.nick});c.execute('UPDATE messages SET event_id=? WHERE id=?',(eid,r['id']))
   return
  if cmd=='TOPIC':
   ch=channel(arg)
   if not ch: await self.send(f':huddle 403 {self.nick} {arg} :No such channel')
   elif ch['topic']: await self.send(f':huddle 332 {self.nick} {arg} :{ch["topic"]}')
   else: await self.send(f':huddle 331 {self.nick} {arg} :No topic is set')
   return
  if cmd=='NAMES':
   ch=channel(arg)
   if ch: await self.send(f':huddle 353 {self.nick} = {arg} :{self.nick}'); await self.send(f':huddle 366 {self.nick} {arg} :End of /NAMES list')
   else: await self.send(f':huddle 403 {self.nick} {arg} :No such channel')
   return
  if cmd=='LIST':
   await self.send(f':huddle 321 {self.nick} Channel :Users Name')
   for rr in connect().execute('SELECT w.slug,c.name FROM channels c JOIN workspaces w ON w.id=c.workspace_id WHERE c.is_dm=0').fetchall(): await self.send(f':huddle 322 {self.nick} #{rr[0]}/{rr[1]} :0')
   await self.send(f':huddle 323 {self.nick} :End of /LIST'); return
  if cmd=='MODE':
   if arg.startswith('#'): await self.send(f':huddle 324 {self.nick} {arg} +'); return
   await self.send(f':huddle 221 {self.nick} +i'); return
  await self.send(f':huddle 421 {self.nick} {cmd} :Unknown command')
 async def register(self):
  if self.reg or not self.nick or not self.passok or not getattr(self,'userhost',None): return
  self.reg=True
  for n in ('001','002','003','004','005'): await self.send(f':huddle {n} {self.nick} :Welcome')
  await self.send(f':huddle 422 {self.nick} :MOTD File is missing')
def channel(name):
 if not name.startswith('#') or '/' not in name:return None
 slug,n=name[1:].split('/',1);return connect().execute('SELECT c.* FROM channels c JOIN workspaces w ON w.id=c.workspace_id WHERE w.slug=? AND c.name=? AND c.is_dm=0',(slug,n)).fetchone()
def member(cid,uid):return connect().execute('SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?',(cid,uid)).fetchone() is not None
async def bridge():
 while True:
  try:
   for cl in list(CLIENTS):
    for key in list(cl.chans):
     since=cl.seen.get(key,0)
     rows=connect().execute("SELECT e.event_id,e.data,c.name,w.slug FROM events e JOIN channels c ON c.id=e.channel_id JOIN workspaces w ON w.id=c.workspace_id WHERE e.channel_id=? AND e.event_id>? ORDER BY e.event_id",(key,since)).fetchall()
     for x in rows:
      cl.seen[key]=x['event_id']
      try:
       d=json.loads(x['data'])
       if d.get('type') not in ('message.created','message.reply'): continue
       m=d.get('message') or {}; au=m.get('author') or {}; nick=au.get('username','user')
       if d.get('source')=='irc' and cl.nick==d.get('source_nick'): continue
       await cl.send(f':{nick}!{nick}@huddle PRIVMSG #{x["slug"]}/{x["name"]} :{m.get("body","")}')
      except Exception:
       pass
  except Exception:
   pass
  await asyncio.sleep(.08)

async def main():
 srv=await asyncio.start_server(lambda r,w:Client(r,w).run(),'0.0.0.0',6667)
 asyncio.create_task(bridge()); await asyncio.Event().wait()
asyncio.run(main())
