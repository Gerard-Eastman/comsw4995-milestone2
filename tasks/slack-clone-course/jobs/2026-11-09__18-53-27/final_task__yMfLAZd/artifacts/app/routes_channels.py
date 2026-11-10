import re
from aiohttp import web
import db
from common import *

def setup(app):
 async def create(request):
  u=require_user(request); slug=request.match_info["slug"]; c=db.get_conn()
  w=c.execute("SELECT * FROM workspaces WHERE slug=?",(slug,)).fetchone()
  if not w: raise HTTPError(404,"workspace not found")
  role=c.execute("SELECT role FROM workspace_members WHERE workspace_id=? AND user_id=?",(w["id"],u["id"])).fetchone()
  if not role: raise HTTPError(403,"not a member")
  b=await read_json(request); name=b.get("name","")
  private=bool(b.get("is_private",False)); topic=b.get("topic","")
  if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*",name) or len(name)>32 or not isinstance(topic,str) or len(topic)>250: raise HTTPError(400,"invalid channel")
  if private and role["role"] not in ("owner","admin"): raise HTTPError(403,"forbidden")
  if c.execute("SELECT 1 FROM channels WHERE workspace_id=? AND name=?",(w["id"],name)).fetchone(): raise HTTPError(409,"channel exists")
  now=db.now_iso()
  try:
   cid=c.execute("INSERT INTO channels(workspace_id,name,is_private,topic,created_at) VALUES(?,?,?,?,?)",(w["id"],name,int(private),topic,now)).lastrowid
  except Exception: raise HTTPError(409,"channel exists")
  c.execute("INSERT INTO channel_members VALUES(?,?)",(cid,u["id"]))
  emit_event(cid,"member.joined",{"user_id":u["id"]})
  return web.json_response({"channel":channel_json(c.execute("SELECT * FROM channels WHERE id=?",(cid,)).fetchone())},status=201)
 async def join(request):
  u=require_user(request); c=db.get_conn()
  ch=c.execute("SELECT * FROM channels WHERE id=?",(request.match_info["id"],)).fetchone()
  if not ch: raise HTTPError(404,"channel not found")
  w=c.execute("SELECT * FROM workspaces WHERE id=?",(ch["workspace_id"],)).fetchone()
  m=c.execute("SELECT role FROM workspace_members WHERE workspace_id=? AND user_id=?",(w["id"],u["id"])).fetchone()
  if ch["is_private"]: raise HTTPError(403,"private channel")
  if not m:
   if w["join_mode"]!="open": raise HTTPError(403,"not a member")
   c.execute("INSERT INTO workspace_members VALUES(?,?,?)",(w["id"],u["id"],"member"))
  if not c.execute("SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?",(ch["id"],u["id"])).fetchone():
   c.execute("INSERT INTO channel_members VALUES(?,?)",(ch["id"],u["id"])); emit_event(ch["id"],"member.joined",{"user_id":u["id"]})
  return web.json_response({"channel":channel_json(ch)})
 async def leave(request):
  u=require_user(request); c=db.get_conn(); ch=c.execute("SELECT * FROM channels WHERE id=?",(request.match_info["id"],)).fetchone()
  if not ch: raise HTTPError(404,"channel not found")
  c.execute("DELETE FROM channel_members WHERE channel_id=? AND user_id=?",(ch["id"],u["id"]))
  emit_event(ch["id"],"member.left",{"user_id":u["id"]})
  return web.json_response({"channel":channel_json(ch)})
 async def patch(request):
  u=require_user(request); c=db.get_conn(); ch=c.execute("SELECT * FROM channels WHERE id=?",(request.match_info["id"],)).fetchone()
  if not ch: raise HTTPError(404,"channel not found")
  allowed=c.execute("SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?",(ch["id"],u["id"])).fetchone()
  owner=c.execute("SELECT 1 FROM workspaces WHERE id=? AND owner_id=?",(ch["workspace_id"],u["id"])).fetchone()
  if not allowed and not owner: raise HTTPError(403,"forbidden")
  b=await read_json(request); topic=b.get("topic")
  if not isinstance(topic,str) or len(topic)>250: raise HTTPError(400,"invalid topic")
  c.execute("UPDATE channels SET topic=? WHERE id=?",(topic,ch["id"])); ch=c.execute("SELECT * FROM channels WHERE id=?",(ch["id"],)).fetchone()
  emit_event(ch["id"],"channel.updated",{"channel":channel_json(ch)})
  return web.json_response({"channel":channel_json(ch)})
 async def archive(request):
  u=require_user(request); c=db.get_conn(); ch=c.execute("SELECT * FROM channels WHERE id=?",(request.match_info["id"],)).fetchone()
  if not ch: raise HTTPError(404,"channel not found")
  if not c.execute("SELECT 1 FROM workspaces WHERE id=? AND owner_id=?",(ch["workspace_id"],u["id"])).fetchone(): raise HTTPError(403,"forbidden")
  val=1 if request.path.endswith("/archive") else 0
  c.execute("UPDATE channels SET is_archived=? WHERE id=?",(val,ch["id"])); ch=c.execute("SELECT * FROM channels WHERE id=?",(ch["id"],)).fetchone()
  emit_event(ch["id"],"channel.archived" if val else "channel.unarchived",{"channel":channel_json(ch)})
  return web.json_response({"channel":channel_json(ch)})
 async def members(request):
  u=require_user(request); c=db.get_conn(); ch=c.execute("SELECT * FROM channels WHERE id=?",(request.match_info["id"],)).fetchone()
  if not ch: raise HTTPError(404,"channel not found")
  if not c.execute("SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?",(ch["id"],u["id"])).fetchone(): raise HTTPError(403,"forbidden")
  rows=c.execute("SELECT u.* FROM users u JOIN channel_members m ON m.user_id=u.id WHERE m.channel_id=?",(ch["id"],)).fetchall()
  return web.json_response({"members":[user_to_json(x) for x in rows]})
 app.router.add_post("/api/workspaces/{slug}/channels",create)
 app.router.add_post("/api/channels/{id}/join",join); app.router.add_post("/api/channels/{id}/leave",leave)
 app.router.add_patch("/api/channels/{id}",patch); app.router.add_post("/api/channels/{id}/archive",archive)
 app.router.add_post("/api/channels/{id}/unarchive",archive); app.router.add_get("/api/channels/{id}/members",members)
