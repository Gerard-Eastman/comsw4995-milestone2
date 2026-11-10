import argparse,asyncio,json,os,re,secrets,uuid
from aiohttp import web,WSMsgType
from db import connect,init_db,now_iso
from common import *
NODE=0; sockets=set(); subscriptions={}; seen=0; bseen=0

def workspace(c,slug):
 return c.execute("SELECT * FROM workspaces WHERE slug=?",(slug,)).fetchone()
def member(c,w,u):
 return c.execute("SELECT * FROM workspace_members WHERE workspace_id=? AND user_id=?",(w,u)).fetchone()
def ch(c,i): return c.execute("SELECT * FROM channels WHERE id=?",(i,)).fetchone()
def can(c,r,u):
 x=r if "workspace_id" in r.keys() else ch(c,r["channel_id"])
 return c.execute("SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?",(x["id"],u)).fetchone() or (not x["is_private"] and member(c,x["workspace_id"],u))
def ws_obj(r): return {k:r[k] for k in ("id","slug","name","owner_id","join_mode")}
async def health(q): return web.json_response({"status":"ok","node_id":NODE})
async def register(q):
 d=await read_json(q); un=d.get("username",""); pw=d.get("password","")
 if not re.fullmatch(r"[A-Za-z0-9_]{1,32}",un) or len(pw)<8: raise HTTPError(400,"invalid registration")
 c=connect()
 if c.execute("SELECT 1 FROM users WHERE username=?",(un,)).fetchone(): c.close(); raise HTTPError(409,"username already exists")
 c.execute("INSERT INTO users(username,password,display_name) VALUES(?,?,?)",(un,pw,d.get("display_name") or un))
 uid=c.execute("SELECT last_insert_rowid()").fetchone()[0]; tok=secrets.token_urlsafe(24); c.execute("INSERT INTO tokens VALUES(?,?)",(tok,uid)); u=c.execute("SELECT * FROM users WHERE id=?",(uid,)).fetchone(); c.close()
 return web.json_response({"user":user_to_json(u),"token":tok},status=201)
async def login(q):
 d=await read_json(q); c=connect(); u=c.execute("SELECT * FROM users WHERE username=? AND password=?",(d.get("username"),d.get("password"))).fetchone()
 if not u: c.close(); raise HTTPError(401,"invalid credentials")
 t=secrets.token_urlsafe(24); c.execute("INSERT INTO tokens VALUES(?,?)",(t,u["id"],)); c.close()
 return web.json_response({"user":user_to_json(u),"token":t})
async def me(q): return web.json_response({"user":user_to_json(require_user(q))})
async def create_ws(q):
 u=require_user(q); d=await read_json(q); slug=d.get("slug",""); name=d.get("name","")
 if not re.fullmatch(r"[a-z0-9-]{2,32}",slug) or not name: raise HTTPError(400,"invalid workspace")
 c=connect()
 if c.execute("SELECT 1 FROM workspaces WHERE slug=?",(slug,)).fetchone(): c.close(); raise HTTPError(409,"workspace exists")
 t=now_iso(); c.execute("INSERT INTO workspaces(slug,name,owner_id,created_at) VALUES(?,?,?,?)",(slug,name,u["id"],t)); wid=c.execute("SELECT last_insert_rowid()").fetchone()[0]
 c.execute("INSERT INTO workspace_members VALUES(?,?,?)",(wid,u["id"],"owner")); c.execute("INSERT INTO channels(workspace_id,name,created_at) VALUES(?,?,?)",(wid,"general",t)); cid=c.execute("SELECT last_insert_rowid()").fetchone()[0]; c.execute("INSERT INTO channel_members VALUES(?,?)",(cid,u["id"]))
 w=c.execute("SELECT * FROM workspaces WHERE id=?",(wid,)).fetchone(); a=ch(c,cid); c.close()
 return web.json_response({"workspace":ws_obj(w),"general_channel":channel_json(a)},status=201)
async def list_ws(q):
 u=require_user(q); c=connect(); rows=c.execute("SELECT w.* FROM workspaces w JOIN workspace_members m ON m.workspace_id=w.id WHERE m.user_id=?",(u["id"],)).fetchall(); c.close(); return web.json_response({"workspaces":[ws_obj(x) for x in rows]})
async def get_ws(q):
 u=require_user(q); slug=q.match_info["slug"]; c=connect(); w=workspace(c,slug)
 if not w: c.close(); raise HTTPError(404,"workspace not found")
 if not member(c,w["id"],u["id"]): c.close(); raise HTTPError(403,"not a member")
 rows=c.execute("SELECT * FROM channels WHERE workspace_id=? AND is_dm=0 AND is_archived=0",(w["id"],)).fetchall(); c.close()
 return web.json_response({"workspace":ws_obj(w),"channels":[channel_json(x) for x in rows],"read_state":[]})
async def create_channel(q):
 u=require_user(q); slug=q.match_info["slug"]; d=await read_json(q); c=connect(); w=workspace(c,slug)
 if not w: c.close(); raise HTTPError(404,"workspace not found")
 m=member(c,w["id"],u["id"])
 if not m: c.close(); raise HTTPError(403,"not a member")
 name=d.get("name","")
 if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*",name) or len(name)>32: c.close(); raise HTTPError(400,"invalid channel")
 if c.execute("SELECT 1 FROM channels WHERE workspace_id=? AND name=?",(w["id"],name)).fetchone(): c.close(); raise HTTPError(409,"channel exists")
 t=now_iso(); c.execute("INSERT INTO channels(workspace_id,name,is_private,topic,created_at) VALUES(?,?,?,?,?)",(w["id"],name,int(bool(d.get("is_private"))),d.get("topic",""),t)); cid=c.execute("SELECT last_insert_rowid()").fetchone()[0]; c.execute("INSERT INTO channel_members VALUES(?,?)",(cid,u["id"])); r=ch(c,cid); c.close(); return web.json_response({"channel":channel_json(r)},status=201)
async def join(q):
 u=require_user(q); i=q.match_info["id"]; c=connect()
 try: i=int(i)
 except: c.close(); raise HTTPError(404,"channel not found")
 r=ch(c,i)
 if not r: c.close(); raise HTTPError(404,"channel not found")
 w=workspace(c,str(r["workspace_id"])) if False else c.execute("SELECT * FROM workspaces WHERE id=?",(r["workspace_id"],)).fetchone()
 if r["is_private"] and not member(c,w["id"],u["id"]): c.close(); raise HTTPError(403,"private channel")
 if not member(c,w["id"],u["id"]): c.execute("INSERT OR IGNORE INTO workspace_members VALUES(?,?,?)",(w["id"],u["id"],"member"))
 c.execute("INSERT OR IGNORE INTO channel_members VALUES(?,?)",(i,u["id"])); c.close(); return web.json_response({"channel":channel_json(r)})
async def patch_channel(q):
 u=require_user(q); c=connect(); r=ch(c,int(q.match_info["id"]))
 if not r: c.close(); raise HTTPError(404,"channel not found")
 if not can(c,{"channel_id":r["id"]},u["id"]): c.close(); raise HTTPError(403,"not a member")
 d=await read_json(q)
 if len(str(d.get("topic","")))>250: c.close(); raise HTTPError(400,"invalid topic")
 c.execute("UPDATE channels SET topic=? WHERE id=?",(d.get("topic",r["topic"]),r["id"])); r=ch(c,r["id"]); c.close()
 emit_event(r["id"],"channel.updated",{"channel":channel_json(r)})
 return web.json_response({"channel":channel_json(r)})
async def archive(q):
 u=require_user(q); c=connect(); r=ch(c,int(q.match_info["id"]))
 if not r: c.close(); raise HTTPError(404,"channel not found")
 w=c.execute("SELECT * FROM workspaces WHERE id=?",(r["workspace_id"],)).fetchone()
 if w["owner_id"]!=u["id"]: c.close(); raise HTTPError(403,"forbidden")
 kind="channel.archived" if q.path.endswith("archive") else "channel.unarchived"
 c.execute("UPDATE channels SET is_archived=? WHERE id=?",(0 if kind.endswith("unarchived") else 1,r["id"])); r=ch(c,r["id"]); c.close()
 emit_event(r["id"],kind,{"channel":channel_json(r)})
 return web.json_response({"channel":channel_json(r)})
async def post_message(q):
 u=require_user(q); cid=int(q.match_info["id"]); d=await read_json(q); body=d.get("body","")
 c=connect(); r=ch(c,cid)
 if not r: c.close(); raise HTTPError(404,"channel not found")
 if r["is_archived"]: c.close(); raise HTTPError(423,"channel is archived")
 if not can(c,r,u["id"]): c.close(); raise HTTPError(403,"not a member")
 if not isinstance(body,str) or not body.strip(): c.close(); raise HTTPError(400,"empty message")
 parent=d.get("parent_id"); t=now_iso()
 mentions=[]
 for x in re.findall(r"(?<!\w)@([A-Za-z0-9_]+)",body):
  z=c.execute("SELECT u.id FROM users u JOIN workspace_members m ON m.user_id=u.id WHERE u.username=? AND m.workspace_id=?",(x,r["workspace_id"])).fetchone()
  if z and z[0]!=u["id"] and z[0] not in mentions: mentions.append(z[0])
 c.execute("INSERT INTO messages(channel_id,author_id,body,parent_id,created_at,mentions) VALUES(?,?,?,?,?,?)",(cid,u["id"],body,parent,t,json.dumps(mentions)))
 mid=c.execute("SELECT last_insert_rowid()").fetchone()[0]; mr=c.execute("SELECT * FROM messages WHERE id=?",(mid,)).fetchone(); obj=message_json(c,mr); c.close()
 emit_event(cid,"message.reply" if parent else "message.created",{"message":obj})
 return web.json_response({"message":obj},status=201)
async def edit_message(q):
 u=require_user(q)
 try: mid=int(q.match_info["id"])
 except: raise HTTPError(404,"message not found")
 c=connect(); r=c.execute("SELECT * FROM messages WHERE id=?",(mid,)).fetchone()
 if not r: c.close(); raise HTTPError(404,"message not found")
 if r["author_id"]!=u["id"]: c.close(); raise HTTPError(403,"forbidden")
 if r["deleted"]: c.close(); raise HTTPError(409,"message deleted")
 chrow=ch(c,r["channel_id"])
 if chrow["is_archived"]: c.close(); raise HTTPError(423,"channel is archived")
 d=await read_json(q); body=d.get("body")
 if not isinstance(body,str) or not body.strip(): c.close(); raise HTTPError(400,"empty message")
 t=now_iso()
 c.execute("UPDATE messages SET body=?,edited_at=? WHERE id=?",(body,t,mid))
 r=c.execute("SELECT * FROM messages WHERE id=?",(mid,)).fetchone()
 obj=message_json(c,r); c.close()
 emit_event(r["channel_id"],"message.updated",{"message":obj})
 return web.json_response({"message":obj})

async def delete_message(q):
 u=require_user(q)
 try: mid=int(q.match_info["id"])
 except: raise HTTPError(404,"message not found")
 c=connect(); r=c.execute("SELECT * FROM messages WHERE id=?",(mid,)).fetchone()
 if not r: c.close(); raise HTTPError(404,"message not found")
 owner=c.execute("SELECT owner_id FROM workspaces w JOIN channels x ON x.workspace_id=w.id WHERE x.id=?",(r["channel_id"],)).fetchone()
 if r["author_id"]!=u["id"] and (not owner or owner[0]!=u["id"]):
  c.close(); raise HTTPError(403,"forbidden")
 if r["deleted"]:
  c.close(); return web.json_response({"deleted":True})
 c.execute("UPDATE messages SET deleted=1 WHERE id=?",(mid,)); cid=r["channel_id"]; c.close()
 emit_event(cid,"message.deleted",{"message_id":mid})
 return web.json_response({"deleted":True})

async def get_messages(q):
 u=require_user(q); cid=int(q.match_info["id"]); c=connect(); r=ch(c,cid)
 if not r: c.close(); raise HTTPError(404,"channel not found")
 if not can(c,r,u["id"]): c.close(); raise HTTPError(403,"not a member")
 n=parse_limit(q); cur=decode_cursor(q.query["cursor"]) if q.query.get("cursor") else None
 sql="SELECT * FROM messages WHERE channel_id=? AND parent_id IS NULL AND deleted=0"
 args=[cid]
 if cur is not None: sql+=" AND id<?"; args.append(cur)
 rows=c.execute(sql+" ORDER BY id DESC LIMIT ?",args+[n+1]).fetchall(); more=len(rows)>n; rows=rows[:n]
 out=[message_json(c,x) for x in rows]; nxt=encode_cursor(rows[-1]["id"]) if more else None; c.close()
 return web.json_response({"messages":out,"next_cursor":nxt})
async def add_reaction(q):
 u=require_user(q); mid=int(q.match_info["id"]); d=await read_json(q); emoji=d.get("emoji","")
 if not isinstance(emoji,str) or not emoji: raise HTTPError(400,"invalid emoji")
 c=connect(); m=c.execute("SELECT * FROM messages WHERE id=? AND deleted=0",(mid,)).fetchone()
 if not m: c.close(); raise HTTPError(404,"message not found")
 if not can(c,m,u["id"]): c.close(); raise HTTPError(403,"not a member")
 c.execute("INSERT OR IGNORE INTO reactions(message_id,user_id,emoji) VALUES(?,?,?)",(mid,u["id"],emoji)); c.close()
 emit_event(m["channel_id"],"reaction.added",{"message_id":mid,"emoji":emoji,"user_id":u["id"]})
 c=connect(); rows=c.execute("SELECT emoji,COUNT(*) n,GROUP_CONCAT(user_id) ids FROM reactions WHERE message_id=? GROUP BY emoji",(mid,)).fetchall(); c.close()
 return web.json_response({"reactions":[{"emoji":x["emoji"],"count":x["n"],"user_ids":[int(z) for z in x["ids"].split(",")]} for x in rows]})
async def remove_reaction(q):
 u=require_user(q); mid=int(q.match_info["id"]); emoji=q.match_info["emoji"]; c=connect()
 m=c.execute("SELECT * FROM messages WHERE id=? AND deleted=0",(mid,)).fetchone()
 if not m: c.close(); raise HTTPError(404,"message not found")
 c.execute("DELETE FROM reactions WHERE message_id=? AND user_id=? AND emoji=?",(mid,u["id"],emoji)); c.close()
 emit_event(m["channel_id"],"reaction.removed",{"message_id":mid,"emoji":emoji,"user_id":u["id"]})
 c=connect(); rows=c.execute("SELECT emoji,COUNT(*) n,GROUP_CONCAT(user_id) ids FROM reactions WHERE message_id=? GROUP BY emoji",(mid,)).fetchall(); c.close()
 return web.json_response({"reactions":[{"emoji":x["emoji"],"count":x["n"],"user_ids":[int(z) for z in x["ids"].split(",")]} for x in rows]})
async def replies(q):
 u=require_user(q); pid=int(q.match_info["id"]); c=connect(); p=c.execute("SELECT * FROM messages WHERE id=?",(pid,)).fetchone()
 if not p: c.close(); raise HTTPError(404,"message not found")
 if not can(c,p,u["id"]): c.close(); raise HTTPError(403,"not a member")
 n=parse_limit(q); cur=decode_cursor(q.query["cursor"]) if q.query.get("cursor") else None
 sql="SELECT * FROM messages WHERE parent_id=? AND deleted=0"; args=[pid]
 if cur is not None: sql+=" AND id>?"; args.append(cur)
 rows=c.execute(sql+" ORDER BY id ASC LIMIT ?",args+[n+1]).fetchall(); more=len(rows)>n; rows=rows[:n]
 out=[message_json(c,x) for x in rows]; nxt=encode_cursor(rows[-1]["id"]) if more else None; c.close()
 return web.json_response({"replies":out,"next_cursor":nxt})
async def ws_handler(q):
 token=q.query.get("token","")
 if token:
  c=connect(); u=c.execute("SELECT u.* FROM tokens t JOIN users u ON u.id=t.user_id WHERE t.token=?",(token,)).fetchone(); c.close()
  if not u: raise HTTPError(401,"invalid token")
 else:
  u=require_user(q)
 ws=web.WebSocketResponse(); await ws.prepare(q); sockets.add(ws); subscriptions[ws]=set(); conn=uuid.uuid4().hex
 c=connect(); c.execute("INSERT OR REPLACE INTO ws_presence VALUES(?,?,?)",(conn,NODE,u["id"])); c.close()
 try:
  async for msg in ws:
   if msg.type!=WSMsgType.TEXT: continue
   d=json.loads(msg.data); cid=int(d.get("channel_id",0)); c=connect(); r=ch(c,cid)
   if d.get("type")=="subscribe":
    subscriptions[ws].add(cid)
    head=r["last_event_id"] if r else 0; await ws.send_json({"type":"subscribed","channel_id":cid,"head_event_id":head})
   elif d.get("type")=="resume":
    since=int(d.get("since_event_id",0))
    for x in c.execute("SELECT payload FROM events WHERE channel_id=? AND event_id>? ORDER BY event_id",(cid,since)): await ws.send_str(x[0])
    head=r["last_event_id"] if r else 0; await ws.send_json({"type":"resumed","channel_id":cid,"head_event_id":head})
   c.close()
 finally:
  sockets.discard(ws); subscriptions.pop(ws,None); c=connect(); c.execute("DELETE FROM ws_presence WHERE conn_id=?",(conn,)); c.close()
 return ws
async def pump(app):
 last=connect().execute("SELECT COALESCE(MAX(seq),0) FROM events").fetchone()[0]
 while True:
  c=connect()
  for x in c.execute("SELECT seq,payload FROM events WHERE seq>? ORDER BY seq",(last,)):
   last=x["seq"]
   for ws in list(sockets):
    try:
     payload=json.loads(x["payload"])
     if payload.get("channel_id") not in subscriptions.get(ws,set()): continue
     await ws.send_str(x["payload"])
    except: sockets.discard(ws)
  c.close(); await asyncio.sleep(.05)
async def on_start(app):
 init_db(); app["pump"]=asyncio.create_task(pump(app))
async def on_cleanup(app): app["pump"].cancel()
def build():
 app=web.Application(middlewares=[error_middleware],client_max_size=20*1024*1024)
 app.router.add_get("/",lambda q:web.FileResponse("/app/static/index.html",headers={"Content-Type":"text/html"})); app.router.add_static("/static/","/app/static"); app.router.add_get("/api/health",health); app.router.add_post("/api/auth/register",register); app.router.add_post("/api/auth/login",login); app.router.add_get("/api/auth/me",me)
 app.router.add_post("/api/workspaces",create_ws); app.router.add_get("/api/workspaces",list_ws); app.router.add_get("/api/workspaces/{slug}",get_ws); app.router.add_post("/api/workspaces/{slug}/channels",create_channel)
 app.router.add_post("/api/channels/{id}/join",join); app.router.add_patch("/api/channels/{id}",patch_channel); app.router.add_post("/api/channels/{id}/archive",archive); app.router.add_post("/api/channels/{id}/unarchive",archive)
 app.router.add_post("/api/channels/{id}/messages",post_message); app.router.add_post("/api/messages/{id}/reactions",add_reaction); app.router.add_delete("/api/messages/{id}/reactions/{emoji}",remove_reaction); app.router.add_patch("/api/messages/{id}",edit_message); app.router.add_delete("/api/messages/{id}",delete_message); app.router.add_get("/api/channels/{id}/messages",get_messages); app.router.add_get("/api/messages/{id}/replies",replies); app.router.add_get("/api/ws",ws_handler)
 app.on_startup.append(on_start); app.on_cleanup.append(on_cleanup); return app
if __name__=="__main__":
 p=argparse.ArgumentParser(); p.add_argument("--port",type=int); p.add_argument("--node-id",type=int); a=p.parse_args(); NODE=a.node_id; web.run_app(build(),host="0.0.0.0",port=a.port)
