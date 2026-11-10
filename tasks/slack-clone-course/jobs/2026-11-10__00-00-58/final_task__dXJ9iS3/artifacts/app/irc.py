import asyncio,json
from db import connect,now_iso
from common import emit_event,message_json

NICKS={}
CLIENTS={}

async def send(w,line):
 w.write((line+"\r\n").encode()); await w.drain()

def irc_name(r):
 c=connect(); w=c.execute("SELECT slug FROM workspaces WHERE id=?",(r["workspace_id"],)).fetchone(); c.close()
 return "#"+w["slug"]+"/"+r["name"] if w and not r["is_dm"] else None

def find_channel(name):
 if not name.startswith("#") or name.count("/")!=1: return None
 slug,cn=name[1:].split("/")
 c=connect(); r=c.execute("SELECT x.* FROM channels x JOIN workspaces w ON w.id=x.workspace_id WHERE w.slug=? AND x.name=? AND x.is_dm=0",(slug,cn)).fetchone(); c.close(); return r

def readable(c,r,uid):
 return bool(c.execute("SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?",(r["id"],uid)).fetchone() or (not r["is_private"] and c.execute("SELECT 1 FROM workspace_members WHERE workspace_id=? AND user_id=?",(r["workspace_id"],uid)).fetchone()))

async def names(w,nick,r,uid):
 c=connect(); rows=c.execute("SELECT u.username FROM channel_members m JOIN users u ON u.id=m.user_id WHERE m.channel_id=?",(r["id"],)).fetchall()
 vals=[]
 for x in rows:
  vals.append(nick if c.execute("SELECT id FROM users WHERE username=?",(x[0],)).fetchone()[0]==uid else x[0])
 c.close(); await send(w,f":huddle 353 {nick} = {irc_name(r)} :"+ " ".join(vals)); await send(w,f":huddle 366 {nick} {irc_name(r)} :End of /NAMES list")

async def join(w,nick,uid,name):
 r=find_channel(name); c=connect()
 if not r or not readable(c,r,uid): c.close(); await send(w,f":huddle 403 {nick} {name} :No such channel"); return
 joined=c.execute("SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?",(r["id"],uid)).fetchone()
 if not joined:
  c.execute("INSERT OR IGNORE INTO workspace_members VALUES(?,?,?)",(r["workspace_id"],uid,"member"))
  c.execute("INSERT OR IGNORE INTO channel_members VALUES(?,?)",(r["id"],uid))
 c.close()
 CLIENTS[w]["joined"].add(r["id"])
 if not joined: emit_event(r["id"],"member.joined",{"user_id":uid})
 c=connect(); topic=r["topic"]; uname=c.execute("SELECT username FROM users WHERE id=?",(uid,)).fetchone()[0]; c.close()
 await send(w,f":{nick}!{uname}@huddle JOIN {name}")
 await send(w,f":huddle {'332' if topic else '331'} {nick} {name} :{topic or 'No topic is set'}")
 await names(w,nick,r,uid)

async def simple_channel(w,nick,uid,name,cmd):
 r=find_channel(name); c=connect()
 if not r or not readable(c,r,uid): c.close(); await send(w,f":huddle 403 {nick} {name} :No such channel"); return
 if cmd=="TOPIC":
  await send(w,f":huddle {'332' if r['topic'] else '331'} {nick} {name} :{r['topic'] or 'No topic is set'}")
 elif cmd=="NAMES": await names(w,nick,r,uid)
 elif cmd=="MODE": await send(w,f":huddle 324 {nick} {name} +")
 elif cmd=="WHO":
  for x in c.execute("SELECT u.username FROM channel_members m JOIN users u ON u.id=m.user_id WHERE m.channel_id=?",(r["id"],)):
   await send(w,f":huddle 352 {nick} {name} {x[0]} huddle huddle {x[0]} H :0 {x[0]}")
  await send(w,f":huddle 315 {nick} {name} :End of /WHO list")
 c.close()

async def do_privmsg(w,nick,uid,name,text):
 r=find_channel(name); c=connect()
 if not r or r["id"] not in CLIENTS[w]["joined"]:
  c.close(); await send(w,f":huddle 442 {nick} {name} :You're not on that channel"); return
 if not text: c.close(); return
 t=now_iso(); c.execute("INSERT INTO messages(channel_id,author_id,body,created_at,mentions) VALUES(?,?,?,?,?)",(r["id"],uid,text,t,"[]"))
 mid=c.execute("SELECT last_insert_rowid()").fetchone()[0]; m=c.execute("SELECT * FROM messages WHERE id=?",(mid,)).fetchone(); obj=message_json(c,m); c.close()
 CLIENTS[w]["posted"].add(mid); emit_event(r["id"],"message.created",{"message":obj})

async def handle_client(reader,writer):
 nick=None; key=None; passed=None; uid=None; userpart=False; reg=False
 CLIENTS[writer]={"joined":set(),"posted":set(),"nick":None,"uid":None}
 try:
  while True:
   raw=await reader.readline()
   if not raw: break
   line=raw.decode("utf8","replace").rstrip("\r\n"); p=line.split(" ",2); cmd=p[0].upper(); args=p[1:]; shown=nick or "*"
   if cmd=="QUIT": break
   if cmd=="PING": await send(writer,":huddle PONG huddle :"+(args[-1].lstrip(":") if args else "")); continue
   if cmd=="PONG": continue
   if cmd=="PASS": passed=args[0] if args else ""; continue
   if cmd=="NICK":
    nn=args[0].lstrip(":") if args else ""
    if nn and nn.lower() in NICKS and NICKS[nn.lower()] is not writer: await send(writer,f":huddle 433 * {nn} :Nickname is already in use"); continue
    if key: NICKS.pop(key,None)
    nick=nn; key=nn.lower(); continue
   if cmd=="USER": userpart=True
   elif not reg and cmd not in ("PASS","NICK","USER"):
    await send(writer,f":huddle 451 {shown} :You have not registered"); continue
   if not reg and nick and userpart:
    c=connect(); row=c.execute("SELECT u.id,u.username FROM tokens t JOIN users u ON u.id=t.user_id WHERE t.token=?",(passed or "",)).fetchone(); c.close()
    if not row: await send(writer,f":huddle 464 {nick} :Password incorrect"); break
    uid=row[0]; reg=True; NICKS[key]=writer; CLIENTS[writer].update(nick=nick,uid=uid)
    for code,text in [("001",f"Welcome to Huddle, {nick}"),("002","Your host is huddle"),("003","This server was created today"),("004","huddle huddle"),("005","CHANTYPES=# :are supported by this server"),("422","MOTD File is missing")]: await send(writer,f":huddle {code} {nick} :{text}")
    continue
   if not reg: continue
   if cmd=="JOIN" and args: await join(writer,nick,uid,args[0])
   elif cmd in ("NAMES","TOPIC","WHO","MODE") and args:
    if cmd=="MODE" and not args[0].startswith("#"): await send(writer,f":huddle 221 {nick} +")
    else: await simple_channel(writer,nick,uid,args[0],cmd)
   elif cmd=="PRIVMSG" and len(args)>=2: await do_privmsg(writer,nick,uid,args[0],args[1].lstrip(":"))
   elif cmd=="LIST":
    c=connect(); await send(writer,f":huddle 321 {nick} Channel :Users Name")
    for r in c.execute("SELECT x.*,w.slug FROM channels x JOIN workspaces w ON w.id=x.workspace_id WHERE x.is_dm=0"):
     if readable(c,r,uid): await send(writer,f":huddle 322 {nick} #{r['slug']}/{r['name']} 0 :{r['topic']}")
    c.close(); await send(writer,f":huddle 323 {nick} :End of /LIST")
   elif cmd not in ("PASS","NICK","USER"): await send(writer,f":huddle 421 {nick} {cmd} :Unknown command")
 finally:
  if key: NICKS.pop(key,None)
  CLIENTS.pop(writer,None); writer.close()
  try: await writer.wait_closed()
  except: pass

async def irc_pump():
 last=connect().execute("SELECT COALESCE(MAX(seq),0) FROM events").fetchone()[0]
 while True:
  c=connect()
  rows=c.execute("SELECT seq,payload FROM events WHERE seq>? ORDER BY seq",(last,)).fetchall()
  for row in rows:
   last=row["seq"]; p=json.loads(row["payload"])
   if p.get("type")=="message.created":
    m=p.get("message",{}); mid=m.get("id"); a=c.execute("SELECT username FROM users WHERE id=?",(m.get("author_id"),)).fetchone()
    r=c.execute("SELECT x.*,w.slug FROM channels x JOIN workspaces w ON w.id=x.workspace_id WHERE x.id=?",(p.get("channel_id"),)).fetchone()
    if r and a:
     name="#"+r["slug"]+"/"+r["name"]
     for w,z in list(CLIENTS.items()):
      if r["id"] in z["joined"] and mid not in z["posted"]:
       try: await send(w,f":{a[0]}!{a[0]}@huddle PRIVMSG {name} :"+str(m.get("body","")).replace("\n"," "))
       except: pass
  c.close(); await asyncio.sleep(.05)

async def main():
 s=await asyncio.start_server(handle_client,"0.0.0.0",6667); asyncio.create_task(irc_pump())
 async with s: await s.serve_forever()
if __name__=="__main__": asyncio.run(main())
