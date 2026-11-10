import asyncio,json
from db import connect,now_iso
from common import emit_event,message_json
NICKS={}; CLIENTS=[]
def send(w,line): w.write((line+'\r\n').encode()); return w.drain()
def irc_name(r): return '#'+r['slug']+'/'+r['name']
def find_channel(n):
 if not n.startswith('#') or n[1:].count('/')!=1:return None
 s,nm=n[1:].split('/')
 c=connect(); r=c.execute('SELECT c.*,w.slug FROM channels c JOIN workspaces w ON w.id=c.workspace_id WHERE w.slug=? AND c.name=? AND c.is_dm=0',(s,nm)).fetchone(); c.close(); return r
async def handle_client(reader,w):
 st={'pass':None,'nick':None,'user':None,'registered':False,'real':False,'joined':set(),'sent':set(),'writer':w}
 CLIENTS.append(st)
 async def num(x): await send(w,':huddle '+x)
 async def names(ch):
  c=connect(); rows=c.execute('SELECT u.username FROM channel_members m JOIN users u ON u.id=m.user_id WHERE m.channel_id=?',(ch['id'],)).fetchall(); c.close()
  ns=[st['nick'] if x['username']==st['user']['username'] else x['username'] for x in rows]
  await num(f'353 {st["nick"]} = {irc_name(ch)} :{" ".join(ns)}'); await num(f'366 {st["nick"]} {irc_name(ch)} :End of /NAMES list')
 async def complete():
  if st['registered'] or not st['nick'] or not st['real']: return
  c=connect(); u=c.execute('SELECT u.* FROM tokens t JOIN users u ON u.id=t.user_id WHERE t.token=?',(st['pass'],)).fetchone(); c.close()
  if not u: await num('464 * :Password incorrect'); w.close(); return
  st['user']=u; st['registered']=True; NICKS[st['nick'].lower()]=st; n=st['nick']
  for code,text in [('001',f'Welcome to Huddle, {n}'),('002','Your host is huddle'),('003','This server was created today'),('004','huddle huddle 1.0'),('005','CHANTYPES=#')]: await num(f'{code} {n} :{text}')
  await num(f'422 {n} :MOTD File is missing')
 try:
  while True:
   raw=await reader.readline()
   if not raw: break
   line=raw.decode(errors='ignore').strip('\r\n'); a=line.split(' ',2); cmd=(a[0] if a else '').upper(); args=a[1:]
   if cmd=='PASS': st['pass']=args[0] if args else ''; await complete()
   elif cmd=='NICK':
    n=args[0] if args else ''
    if n.lower() in NICKS and NICKS[n.lower()] is not st: await num(f'433 * {n} :Nickname is already in use')
    else: st['nick']=n; await complete()
   elif cmd=='USER': st['real']=True; await complete()
   elif cmd=='PING': await num('PONG huddle :'+(args[0].lstrip(':') if args else ''))
   elif cmd=='PONG': pass
   elif cmd=='QUIT': break
   elif not st['registered']: await num('451 * :You have not registered')
   elif cmd=='JOIN':
    target=args[0] if args else ''; ch=find_channel(target)
    if not ch: await num(f'403 {st["nick"]} {target} :No such channel'); continue
    c=connect(); wm=c.execute('SELECT 1 FROM workspace_members WHERE workspace_id=? AND user_id=?',(ch['workspace_id'],st['user']['id'])).fetchone(); cm=c.execute('SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?',(ch['id'],st['user']['id'])).fetchone()
    if ch['is_private'] and not cm: c.close(); await num(f'403 {st["nick"]} {target} :No such channel'); continue
    if not wm: c.execute('INSERT OR IGNORE INTO workspace_members VALUES(?,?,?)',(ch['workspace_id'],st['user']['id'],'member'))
    c.execute('INSERT OR IGNORE INTO channel_members VALUES(?,?)',(ch['id'],st['user']['id'])); c.close(); st['joined'].add(ch['id'])
    await send(w,f':{st["nick"]}!{st["user"]["username"]}@huddle JOIN {irc_name(ch)}')
    await num(f'332 {st["nick"]} {irc_name(ch)} :{ch["topic"]}' if ch['topic'] else f'331 {st["nick"]} {irc_name(ch)} :No topic is set'); await names(ch)
   elif cmd in ('NAMES','TOPIC','WHO','MODE'):
    target=args[0] if args else ''; ch=find_channel(target)
    if cmd=='NAMES' and ch: await names(ch)
    elif cmd=='TOPIC' and ch: await num(f'332 {st["nick"]} {irc_name(ch)} :{ch["topic"]}' if ch['topic'] else f'331 {st["nick"]} {irc_name(ch)} :No topic is set')
    elif cmd=='WHO' and ch:
     c=connect(); rows=c.execute('SELECT u.username FROM channel_members m JOIN users u ON u.id=m.user_id WHERE m.channel_id=?',(ch['id'],)).fetchall(); c.close()
     for x in rows: await num(f'352 {st["nick"]} {irc_name(ch)} {x["username"]} huddle huddle {x["username"]} H :0 {x["username"]}')
     await num(f'315 {st["nick"]} {irc_name(ch)} :End of /WHO list')
    elif cmd=='MODE': await num(f'221 {st["nick"]} +' if not ch else f'324 {st["nick"]} {irc_name(ch)} +')
   elif cmd=='LIST':
    c=connect(); rows=c.execute('SELECT c.*,w.slug,(SELECT COUNT(*) FROM channel_members m WHERE m.channel_id=c.id) n FROM channels c JOIN workspaces w ON w.id=c.workspace_id JOIN workspace_members wm ON wm.workspace_id=w.id WHERE wm.user_id=? AND c.is_dm=0 AND c.is_archived=0',(st['user']['id'],)).fetchall(); c.close()
    await num(f'321 {st["nick"]} Channel :Users Name')
    for ch in rows: await num(f'322 {st["nick"]} {irc_name(ch)} {ch["n"]} :{ch["topic"]}')
    await num(f'323 {st["nick"]} :End of /LIST')
   elif cmd=='PRIVMSG':
    target=args[0] if args else ''; text=args[1].lstrip(':') if len(args)>1 else ''; ch=find_channel(target)
    if not ch or ch['id'] not in st['joined']: await num(f'442 {st["nick"]} {target} :You\'re not on that channel'); continue
    c=connect(); c.execute('INSERT INTO messages(channel_id,author_id,body,created_at) VALUES(?,?,?,?)',(ch['id'],st['user']['id'],text,now_iso())); mid=c.execute('SELECT last_insert_rowid()').fetchone()[0]; m=message_json(c,c.execute('SELECT * FROM messages WHERE id=?',(mid,)).fetchone()); c.close(); emit_event(ch['id'],'message.created',{'message':m}); st['sent'].add(mid)
   else: await num(f'421 {st["nick"]} {cmd} :Unknown command')
 finally:
  if st.get('nick'): NICKS.pop(st['nick'].lower(),None)
  if st in CLIENTS: CLIENTS.remove(st)
  w.close(); await w.wait_closed()
async def pump():
 seq=0
 try:
  c=connect(); seq=c.execute('SELECT COALESCE(MAX(seq),0) FROM events').fetchone()[0]; c.close()
 except Exception: seq=0
 while True:
  try:
   c=connect(); rows=c.execute('SELECT seq,payload FROM events WHERE seq>? ORDER BY seq',(seq,)).fetchall(); c.close()
   for r in rows:
    seq=r['seq']
    try:
     p=json.loads(r['payload'])
     if p.get('type')!='message.created': continue
     c=connect(); ch=c.execute('SELECT c.*,w.slug FROM channels c JOIN workspaces w ON w.id=c.workspace_id WHERE c.id=?',(p['channel_id'],)).fetchone(); c.close()
     if not ch: continue
     m=p.get('message') or {}; mid=m.get('id'); nick=m.get('author',{}).get('username',''); body=str(m.get('body','')).replace('\\n',' ')
     for st in list(CLIENTS):
      if ch['id'] in st.get('joined',set()) and mid not in st.get('sent',set()):
       try: await send(st['writer'],f':{nick}!{nick}@huddle PRIVMSG {irc_name(ch)} :{body}')
       except Exception: pass
    except Exception: pass
  except Exception: pass
  await asyncio.sleep(.05)
async def main():
 server=await asyncio.start_server(handle_client,'0.0.0.0',6667); task=asyncio.create_task(pump())
 async with server: await server.serve_forever()
 await task
if __name__=='__main__': asyncio.run(main())
