import asyncio,json
import db
from common import emit_event
db.init_db(); C=db._conn
NICKS={}; CLIENTS={}; LAST=0
async def send(w,line):
 try: w.write((line+'\r\n').encode()); await w.drain()
 except: pass
def token_user(t):
 return C.execute('SELECT u.* FROM tokens t JOIN users u ON u.id=t.user_id WHERE t.token=?',(t,)).fetchone()
def chan(name):
 if not name.startswith('#') or name.count('/')!=1: return None
 slug,n=name[1:].split('/')
 return C.execute('SELECT c.*,w.slug,w.owner_id FROM channels c JOIN workspaces w ON w.id=c.workspace_id WHERE w.slug=? AND c.name=? AND c.is_dm=0',(slug,n)).fetchone()
def cname(ch): return '#'+ch['slug']+'/'+ch['name']
def can_read(uid,ch):
 return bool(C.execute('SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?',(ch['id'],uid)).fetchone() or
             (not ch['is_private'] and C.execute('SELECT 1 FROM workspace_members WHERE workspace_id=? AND user_id=?',(ch['workspace_id'],uid)).fetchone()))
async def finish(x):
 if x['registered']: return
 if not x.get('nick') or not x.get('user'): return
 u=token_user(x.get('pass'))
 if not u:
  await send(x['w'],':huddle 464 * :Password incorrect'); x['w'].close(); x['closing']=True; return
 x.update(uid=u['id'],username=u['username'],registered=True)
 CLIENTS[id(x['w'])]=x
 n=x['nick']
 for code,text in [('001',f'Welcome to Huddle, {n}'),('002','Your host is huddle'),('003','This server was created today'),('004','huddle 1.0 o o'),('005','CHANTYPES=# :are supported by this server'),('422','MOTD File is missing')]:
  await send(x['w'],f':huddle {code} {n} :{text}')
async def join(x,name):
 ch=chan(name)
 if not ch or not can_read(x['uid'],ch):
  await send(x['w'],f':huddle 403 {x["nick"]} {name} :No such channel'); return
 if not C.execute('SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?',(ch['id'],x['uid'])).fetchone():
  C.execute('INSERT OR IGNORE INTO workspace_members VALUES(?,?,?)',(ch['workspace_id'],x['uid'],'member'))
  C.execute('INSERT OR IGNORE INTO channel_members VALUES(?,?)',(ch['id'],x['uid']))
  emit_event(ch['id'],'member.joined',{'user_id':x['uid']})
 x['joined'].add(ch['id'])
 await send(x['w'],f':{x["nick"]}!{x["username"]}@huddle JOIN {name}')
 if ch['topic']: await send(x['w'],f':huddle 332 {x["nick"]} {name} :{ch["topic"]}')
 else: await send(x['w'],f':huddle 331 {x["nick"]} {name} :No topic is set')
 names=[r['username'] for r in C.execute('SELECT u.username FROM channel_members m JOIN users u ON u.id=m.user_id WHERE m.channel_id=?',(ch['id'],))]
 if x['username'] not in names: names.append(x['username'])
 await send(x['w'],f':huddle 353 {x["nick"]} = {name} :{" ".join(names)}')
 await send(x['w'],f':huddle 366 {x["nick"]} {name} :End of /NAMES list')
async def info(x,cmd,arg):
 ch=chan(arg) if arg else None
 if cmd=='LIST':
  await send(x['w'],f':huddle 321 {x["nick"]} Channel :Users  Name')
  rows=C.execute('SELECT c.*,w.slug FROM channels c JOIN workspaces w ON w.id=c.workspace_id WHERE c.is_dm=0').fetchall()
  for c in rows:
   if can_read(x['uid'],c):
    n=C.execute('SELECT COUNT(*) FROM channel_members WHERE channel_id=?',(c['id'],)).fetchone()[0]
    await send(x['w'],f':huddle 322 {x["nick"]} {cname(c)} {n} :{c["topic"] or ""}')
  await send(x['w'],f':huddle 323 {x["nick"]} :End of /LIST'); return
 if cmd=='MODE':
  if ch: await send(x['w'],f':huddle 324 {x["nick"]} {arg} +')
  else: await send(x['w'],f':huddle 221 {x["nick"]} +')
  return
 if not ch or not can_read(x['uid'],ch):
  await send(x['w'],f':huddle 403 {x["nick"]} {arg} :No such channel'); return
 if cmd in ('NAMES','TOPIC'):
  if cmd=='TOPIC':
   if ch['topic']: await send(x['w'],f':huddle 332 {x["nick"]} {arg} :{ch["topic"]}')
   else: await send(x['w'],f':huddle 331 {x["nick"]} {arg} :No topic is set')
  else:
   ns=[r['username'] for r in C.execute('SELECT u.username FROM channel_members m JOIN users u ON u.id=m.user_id WHERE m.channel_id=?',(ch['id'],))]
   await send(x['w'],f':huddle 353 {x["nick"]} = {arg} :{" ".join(ns)}')
   await send(x['w'],f':huddle 366 {x["nick"]} {arg} :End of /NAMES list')
 if cmd=='WHO':
  for r in C.execute('SELECT u.username FROM channel_members m JOIN users u ON u.id=m.user_id WHERE m.channel_id=?',(ch['id'],)):
   await send(x['w'],f':huddle 352 {x["nick"]} {arg} huddle huddle {r["username"]} H :0 {r["username"]}')
  await send(x['w'],f':huddle 315 {x["nick"]} {arg} :End of /WHO list')
async def privmsg(x,target,text):
 ch=chan(target)
 if not ch or ch['id'] not in x['joined']:
  await send(x['w'],f':huddle 442 {x["nick"]} {target} :You\'re not on that channel'); return
 body=text.lstrip(':')
 C.execute('INSERT INTO messages(channel_id,author_id,body,created_at) VALUES(?,?,?,?)',(ch['id'],x['uid'],body,db.now_iso()))
 mid=C.execute('SELECT last_insert_rowid()').fetchone()[0]
 r=C.execute('SELECT * FROM messages WHERE id=?',(mid,)).fetchone()
 u=C.execute('SELECT * FROM users WHERE id=?',(x['uid'],)).fetchone()
 mo={'id':mid,'channel_id':ch['id'],'author_id':x['uid'],'author':{k:u[k] for k in ('id','username','display_name','timezone','avatar_url','status_text','status_emoji')},'body':body,'parent_id':None,'reply_count':0,'created_at':r['created_at'],'edited_at':None,'files':[],'reactions':[],'mentions':[]}
 x['posted'].add(mid); emit_event(ch['id'],'message.created',{'message':mo})
async def handle_client(r,w):
 x={'w':w,'nick':None,'pass':None,'user':None,'registered':False,'joined':set(),'posted':set(),'closing':False}
 try:
  while not r.at_eof() and not x['closing']:
   raw=await r.readline()
   if not raw: break
   line=raw.decode(errors='ignore').strip()
   if not line: continue
   ps=line.split(' ',2); cmd=ps[0].upper(); arg=ps[1] if len(ps)>1 else ''; rest=ps[2] if len(ps)>2 else ''
   if cmd=='PASS': x['pass']=arg
   elif cmd=='NICK':
    if arg.lower() in NICKS and NICKS[arg.lower()] is not w: await send(w,f':huddle 433 * {arg} :Nickname is already in use'); continue
    if x['nick']: NICKS.pop(x['nick'].lower(),None)
    x['nick']=arg; NICKS[arg.lower()]=w; await finish(x)
   elif cmd=='USER': x['user']=arg; await finish(x)
   elif cmd=='PING': await send(w,':huddle PONG huddle :'+(arg or rest.lstrip(':')))
   elif cmd=='PONG': pass
   elif cmd=='QUIT': break
   elif not x['registered']: await send(w,':huddle 451 * :You have not registered')
   elif cmd=='JOIN': await join(x,arg)
   elif cmd in ('NAMES','TOPIC','WHO','LIST','MODE'): await info(x,cmd,arg)
   elif cmd=='PRIVMSG': await privmsg(x,arg,rest)
   else: await send(w,f':huddle 421 {x["nick"]} {cmd} :Unknown command')
 finally:
  CLIENTS.pop(id(w),None)
  if x['nick']: NICKS.pop(x['nick'].lower(),None)
  try: w.close(); await w.wait_closed()
  except: pass
async def pump():
 global LAST
 LAST=C.execute('SELECT COALESCE(MAX(seq),0) FROM events').fetchone()[0]
 while True:
  await asyncio.sleep(.05)
  for z in C.execute('SELECT seq,payload FROM events WHERE seq>? ORDER BY seq',(LAST,)).fetchall():
   LAST=z['seq']
   try: p=json.loads(z['payload'])
   except: continue
   if p.get('type')!='message.created': continue
   m=p.get('message') or {}; ch=C.execute('SELECT c.*,w.slug FROM channels c JOIN workspaces w ON w.id=c.workspace_id WHERE c.id=?',(p['channel_id'],)).fetchone()
   if not ch: continue
   au=C.execute('SELECT username FROM users WHERE id=?',(m.get('author_id'),)).fetchone(); un=au[0] if au else 'huddle'
   for x in list(CLIENTS.values()):
    if ch['id'] in x['joined'] and m.get('id') not in x['posted']:
     await send(x['w'],f':{un}!{un}@huddle PRIVMSG {cname(ch)} :{str(m.get("body","")).replace(chr(10)," ")}')
async def main():
 s=await asyncio.start_server(handle_client,'0.0.0.0',6667); asyncio.create_task(pump())
 async with s: await s.serve_forever()
if __name__=='__main__': asyncio.run(main())
