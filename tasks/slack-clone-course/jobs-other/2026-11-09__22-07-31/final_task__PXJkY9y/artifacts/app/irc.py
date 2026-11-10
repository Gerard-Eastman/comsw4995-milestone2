import asyncio,sys
sys.path.insert(0,'/app')
from db import connect
NICKS={}
def tok(t):
 c=connect(); x=c.execute('select u.* from tokens t join users u on u.id=t.user_id where t.token=?',(t,)).fetchone(); c.close(); return x
async def send(w,s):
 w.write((s+'\r\n').encode()); await w.drain()
async def client(r,w):
 nick='*'; password=None; userline=False; logged=False
 try:
  while True:
   line=await r.readline()
   if not line: break
   s=line.decode(errors='ignore').strip()
   if not s: continue
   parts=s.split(); cmd=parts[0].upper()
   if cmd=='PASS':
    password=parts[1] if len(parts)>1 else ''
   elif cmd=='NICK':
    n=parts[1] if len(parts)>1 else ''
    if n.lower() in NICKS and NICKS[n.lower()] is not w:
     await send(w,f':huddle 433 * {n} :Nickname is already in use'); continue
    nick=n
   elif cmd=='USER':
    userline=True
   elif cmd=='PING':
    await send(w,':huddle PONG huddle :'+(parts[1] if len(parts)>1 else ''))
   elif cmd=='PONG': pass
   elif cmd=='QUIT': break
   elif logged and cmd not in ('PASS','NICK','USER','PING','PONG','QUIT'):
    await send(w,f':huddle 421 {nick} {cmd} :Unknown command')
   elif not logged:
    if cmd in ('JOIN','NAMES','WHO','LIST','TOPIC','MODE','PRIVMSG'):
     await send(w,':huddle 451 * :You have not registered')
    else:
     await send(w,f':huddle 421 {nick} {cmd} :Unknown command')
   if not logged and userline and password is None:
    await send(w,f':huddle 464 {nick} :Password incorrect'); break
   if not logged and password is not None and nick!='*' and userline:
    me=tok(password)
    if not me:
     await send(w,f':huddle 464 {nick} :Password incorrect'); break
    if nick.lower() in NICKS and NICKS[nick.lower()] is not w:
     await send(w,f':huddle 433 * {nick} :Nickname is already in use'); continue
    logged=True; NICKS[nick.lower()]=w
    for num,text in [('001','Welcome to Huddle'),('002','Your host is huddle'),('003','This server was created today'),('004','huddle huddle 1.0'),('005','CHANTYPES=#')]:
     await send(w,f':huddle {num} {nick} :{text}')
    await send(w,f':huddle 422 {nick} :MOTD File is missing')
 finally:
  if nick.lower() in NICKS and NICKS[nick.lower()] is w: NICKS.pop(nick.lower(),None)
  w.close()
  try: await w.wait_closed()
  except: pass

async def main():
 s=await asyncio.start_server(client,'0.0.0.0',6667)
 async with s: await s.serve_forever()
asyncio.run(main())
