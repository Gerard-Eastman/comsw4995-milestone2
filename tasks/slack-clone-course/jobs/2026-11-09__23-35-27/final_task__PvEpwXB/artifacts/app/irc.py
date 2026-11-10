import asyncio,json,re
from db import connect,now_iso
from common import emit_event
from routes_messages import msg
DB=connect()
NICKS={}
CLIENTS=[]
def send(w,line):
    w.write((line+"\r\n").encode())
    return w.drain()
def uname(uid):
    r=DB.execute("SELECT username FROM users WHERE id=?",(uid,)).fetchone()
    return r["username"] if r else "user"
def irc_name(c):
    w=DB.execute("SELECT slug FROM workspaces WHERE id=?",(c["workspace_id"],)).fetchone()
    return "#%s/%s"%(w["slug"],c["name"])
def find_channel(n):
    if not isinstance(n,str) or not n.startswith("#") or n.count("/")!=1:return None
    slug,name=n[1:].split("/")
    return DB.execute("SELECT c.*,w.slug FROM channels c JOIN workspaces w ON w.id=c.workspace_id WHERE w.slug=? AND c.name=? AND c.is_dm=0",(slug,name)).fetchone()
async def numeric(st,num,text,star=False):
    await send(st["w"],":huddle %03d %s %s"%(num,st.get("nick") if not star else "*",text))
async def register(st):
    if st["registered"] or not st.get("nick") or not st.get("user"): return
    t=st.get("token"); r=DB.execute("SELECT user_id FROM tokens WHERE token=?",(t or "",)).fetchone()
    if not r:
        await numeric(st,464,":Password incorrect"); st["close"]=True; return
    st["uid"]=r["user_id"]; st["registered"]=True; NICKS[st["nick"].lower()]=st
    n=st["nick"]
    for x,text in [(1,":Welcome to Huddle, "+n),(2,":Your host is huddle"),(3,":This server was created locally"),(4,":huddle 0.1 aiohttp"),(5,":CASEMAPPING=rfc1459")]:
        await send(st["w"],":huddle %03d %s %s"%(x,n,text))
    await send(st["w"],":huddle 422 %s :MOTD File is missing"%n)
async def names(st,c):
    users=[]
    for x in DB.execute("SELECT u.username,u.id FROM channel_members m JOIN users u ON u.id=m.user_id WHERE m.channel_id=?",(c["id"],)):
        users.append(st["nick"] if x["id"]==st["uid"] else x["username"])
    await send(st["w"],":huddle 353 %s = %s :%s"%(st["nick"],irc_name(c)," ".join(users)))
    await send(st["w"],":huddle 366 %s %s :End of /NAMES list"%(st["nick"],irc_name(c)))
async def join(st,name):
    c=find_channel(name)
    if not c or c["is_private"] and not DB.execute("SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?",(c["id"],st["uid"])).fetchone():
        await send(st["w"],":huddle 403 %s :No such channel"%name); return
    mem=DB.execute("SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?",(c["id"],st["uid"])).fetchone()
    if not mem:
        wr=DB.execute("SELECT join_mode FROM workspaces WHERE id=?",(c["workspace_id"],)).fetchone()
        if not wr or wr["join_mode"]!="open":
            await send(st["w"],":huddle 403 %s :No such channel"%name); return
        DB.execute("INSERT OR IGNORE INTO workspace_members VALUES(?,?,?)",(c["workspace_id"],st["uid"],"member"))
        DB.execute("INSERT OR IGNORE INTO channel_members VALUES(?,?)",(c["id"],st["uid"]))
        emit_event(c["id"],"member.joined",{"user_id":st["uid"]})
    st["joined"].add(c["id"])
    prefix=":%s!%s@huddle"%(st["nick"],uname(st["uid"]))
    await send(st["w"],"%s JOIN %s"%(prefix,name))
    topic=c["topic"] or ""
    await send(st["w"],":huddle %s %s :%s"%(332 if topic else 331,st["nick"],name+" :"+topic if topic else name+" :No topic is set"))
    await names(st,c)
async def handle(st,line):
    with open("/tmp/irc-trace.log","a") as f: f.write("HANDLE "+repr(line)+"\\n")
    parts=line.strip().split(" ",1); cmd=parts[0].upper(); rest=parts[1] if len(parts)>1 else ""
    if cmd=="PASS": st["token"]=rest.lstrip(":"); return
    if cmd=="NICK":
        n=rest.strip().lstrip(":")
        if n.lower() in NICKS and NICKS[n.lower()] is not st:
            await send(st["w"],":huddle 433 * %s :Nickname is already in use"%n); return
        st["nick"]=n; await register(st); return
    if cmd=="USER":
        st["user"]=rest; await register(st); return
    if cmd=="PING":
        await send(st["w"],":huddle PONG huddle :"+rest.lstrip(":")); return
    if cmd=="PONG": return
    if cmd=="QUIT": st["close"]=True; return
    if not st["registered"]:
        await send(st["w"],":huddle 421 %s %s :Unknown command"%(st.get("nick","*"),cmd) if cmd not in ("JOIN","NAMES","WHO","LIST","TOPIC","MODE","PRIVMSG") else ":huddle 451 * :You have not registered")
        return
    if cmd=="JOIN":
        await join(st,rest.split()[0]); return
    if cmd=="NAMES":
        c=find_channel(rest.split()[0]); 
        if c: await names(st,c)
        return
    if cmd=="TOPIC":
        c=find_channel(rest.split()[0])
        if c:
            if c["topic"]: await send(st["w"],":huddle 332 %s %s :%s"%(st["nick"],rest.split()[0],c["topic"]))
            else: await send(st["w"],":huddle 331 %s %s :No topic is set"%(st["nick"],rest.split()[0]))
        return
    if cmd=="WHO":
        target=rest.split()[0] if rest else ""
        c=find_channel(target)
        if c:
            for x in DB.execute("SELECT u.username,u.id FROM channel_members m JOIN users u ON u.id=m.user_id WHERE m.channel_id=?",(c["id"],)):
                nick=st["nick"] if x["id"]==st["uid"] else x["username"]
                await send(st["w"],":huddle 352 %s %s %s huddle huddle %s H :0 %s"%(st["nick"],target,x["username"],nick,nick))
        await send(st["w"],":huddle 315 %s %s :End of /WHO list"%(st["nick"],target))
        return
    if cmd=="MODE":
        a=rest.split()[0] if rest else st["nick"]
        await send(st["w"],":huddle 324 %s %s +"%(st["nick"],a) if a.startswith("#") else ":huddle 221 %s +"%st["nick"]); return
    if cmd=="LIST":
        await send(st["w"],":huddle 321 %s Channel :Users Name"%st["nick"])
        for c in DB.execute("SELECT c.*,w.slug FROM channels c JOIN workspaces w ON w.id=c.workspace_id WHERE c.is_dm=0"):
            if DB.execute("SELECT 1 FROM workspace_members WHERE workspace_id=? AND user_id=?",(c["workspace_id"],st["uid"])).fetchone():
                count=DB.execute("SELECT count(*) n FROM channel_members WHERE channel_id=?",(c["id"],)).fetchone()["n"]
                await send(st["w"],":huddle 322 %s %s %s :%s"%(st["nick"],irc_name(c),count,c["topic"] or ""))
        await send(st["w"],":huddle 323 %s :End of /LIST"%st["nick"]); return
    if cmd=="PRIVMSG":
        if " :" not in rest: return
        target,text=rest.split(" :",1); c=find_channel(target)
        if not c or c["id"] not in st["joined"]:
            await send(st["w"],":huddle 442 %s :You're not on that channel"%target); return
        cur=DB.execute("INSERT INTO messages(channel_id,author_id,body,created_at,mentions) VALUES(?,?,?,?,?)",(c["id"],st["uid"],text,now_iso(),"[]"))
        r=DB.execute("SELECT * FROM messages WHERE id=?",(cur.lastrowid,)).fetchone()
        emit_event(c["id"],"message.created",{"message":msg(r)}); st["self"].add(cur.lastrowid); return
    await send(st["w"],":huddle 421 %s %s :Unknown command"%(st["nick"],cmd))
async def handle_client(reader,writer):
    st={"w":writer,"registered":False,"joined":set(),"self":set(),"close":False}
    CLIENTS.append(st)
    try:
        while not st["close"]:
            raw=await reader.readline()
            if not raw: break
            await handle(st,raw.decode(errors="ignore").rstrip("\r\n"))
    except Exception as e:
        import traceback
        with open("/tmp/irc-client.log","a") as f: traceback.print_exc(file=f)
    finally:
        with open("/tmp/irc-trace.log","a") as f: f.write("FINALLY "+repr(st)+"\\n")
        if st.get("nick"): NICKS.pop(st["nick"].lower(),None)
        if st in CLIENTS: CLIENTS.remove(st)
        writer.close(); await writer.wait_closed()
async def irc_pump():
    seq=DB.execute("SELECT COALESCE(MAX(seq),0) FROM events").fetchone()[0]
    while True:
        await asyncio.sleep(.05)
        for r in DB.execute("SELECT * FROM events WHERE seq>? ORDER BY seq",(seq,)):
            seq=r["seq"]
            try: p=json.loads(r["payload"])
            except: continue
            if p.get("type")!="message.created": continue
            m=p.get("message") or {}; mid=m.get("id"); c=DB.execute("SELECT * FROM channels WHERE id=?",(p["channel_id"],)).fetchone()
            if not c or c["is_dm"]: continue
            name=irc_name(c); sender=uname(m.get("author_id")); body=str(m.get("body","")).replace("\n"," ")
            for st in list(CLIENTS):
                if st.get("registered") and c["id"] in st["joined"] and mid not in st["self"]:
                    await send(st["w"],":%s!%s@huddle PRIVMSG %s :%s"%(sender,sender,name,body))
async def main():
    server=await asyncio.start_server(handle_client,"0.0.0.0",6667)
    asyncio.create_task(irc_pump())
    async with server: await server.serve_forever()
if __name__=="__main__": asyncio.run(main())
