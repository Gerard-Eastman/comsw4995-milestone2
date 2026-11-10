import re
from aiohttp import web
import db
from common import *

def wjson(r):
 return {k:r[k] for k in ("id","slug","name","owner_id","join_mode","created_at")}

def cjson(r):
 return {k:(bool(r[k]) if k in ("is_private","is_dm","is_archived") else r[k]) for k in ("id","workspace_id","name","is_private","is_dm","topic","is_archived","created_at")}

def setup(app):
 async def create(request):
  u=require_user(request); b=await read_json(request); slug=b.get("slug"); name=b.get("name")
  if not isinstance(slug,str) or not re.fullmatch(r"[a-z0-9-]{2,32}",slug) or not isinstance(name,str) or not name.strip(): raise HTTPError(400,"invalid workspace")
  c=db.get()
  if c.execute("SELECT 1 FROM workspaces WHERE slug=?",(slug,)).fetchone(): raise HTTPError(409,"workspace exists")
  now=db.now_iso(); c.execute("INSERT INTO workspaces(slug,name,owner_id,created_at) VALUES(?,?,?,?)",(slug,name,u["id"],now))
  wid=c.execute("SELECT last_insert_rowid()").fetchone()[0]; c.execute("INSERT INTO workspace_members VALUES(?,?,?)",(wid,u["id"],"owner"))
  c.execute("INSERT INTO channels(workspace_id,name,created_at) VALUES(?,?,?)",(wid,"general",now))
  cid=c.execute("SELECT last_insert_rowid()").fetchone()[0]; c.execute("INSERT INTO channel_members VALUES(?,?)",(cid,u["id"]))
  r=c.execute("SELECT * FROM workspaces WHERE id=?",(wid,)).fetchone(); ch=c.execute("SELECT * FROM channels WHERE id=?",(cid,)).fetchone()
  return web.json_response({"workspace":wjson(r),"general_channel":cjson(ch)},status=201)
 async def listing(request):
  u=require_user(request); rows=db.get().execute("SELECT w.* FROM workspaces w JOIN workspace_members m ON m.workspace_id=w.id WHERE m.user_id=? ORDER BY w.id",(u["id"],)).fetchall()
  return web.json_response({"workspaces":[wjson(x) for x in rows]})
 async def detail(request):
  u=require_user(request); c=db.get(); w=c.execute("SELECT * FROM workspaces WHERE slug=?",(request.match_info["slug"],)).fetchone()
  if not w: raise HTTPError(404,"workspace not found")
  if not c.execute("SELECT 1 FROM workspace_members WHERE workspace_id=? AND user_id=?",(w["id"],u["id"])).fetchone(): raise HTTPError(403,"not a member")
  cs=c.execute("SELECT * FROM channels WHERE workspace_id=? AND is_dm=0 AND (is_archived=0 OR ?)",(w["id"],request.query.get("include_archived") in ("1","true"))).fetchall()
  return web.json_response({"workspace":wjson(w),"channels":[cjson(x) for x in cs],"read_state":[]})
 async def members(request):
  u=require_user(request); c=db.get(); w=c.execute("SELECT * FROM workspaces WHERE slug=?",(request.match_info["slug"],)).fetchone()
  if not w: raise HTTPError(404,"workspace not found")
  if not c.execute("SELECT 1 FROM workspace_members WHERE workspace_id=? AND user_id=?",(w["id"],u["id"])).fetchone(): raise HTTPError(403,"not a member")
  rs=c.execute("SELECT m.*,u.* FROM workspace_members m JOIN users u ON u.id=m.user_id WHERE m.workspace_id=?",(w["id"],)).fetchall()
  return web.json_response({"members":[{"user_id":r["user_id"],"role":r["role"],"user":user_to_json(r)} for r in rs]})
 async def newchannel(request):
  u=require_user(request); c=db.get(); w=c.execute("SELECT * FROM workspaces WHERE slug=?",(request.match_info["slug"],)).fetchone()
  if not w: raise HTTPError(404,"workspace not found")
  mem=c.execute("SELECT role FROM workspace_members WHERE workspace_id=? AND user_id=?",(w["id"],u["id"])).fetchone()
  if not mem: raise HTTPError(403,"not a member")
  b=await read_json(request); name=b.get("name","")
  if not isinstance(name,str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*",name) or len(name)>32: raise HTTPError(400,"invalid channel")
  if c.execute("SELECT 1 FROM channels WHERE workspace_id=? AND name=?",(w["id"],name)).fetchone(): raise HTTPError(409,"channel exists")
  private=bool(b.get("is_private",False))
  if private and mem["role"] not in ("owner","admin"): raise HTTPError(403,"forbidden")
  now=db.now_iso(); c.execute("INSERT INTO channels(workspace_id,name,is_private,topic,created_at) VALUES(?,?,?,?,?)",(w["id"],name,int(private),b.get("topic","") if isinstance(b.get("topic",""),str) else "",now))
  cid=c.execute("SELECT last_insert_rowid()").fetchone()[0]; c.execute("INSERT INTO channel_members VALUES(?,?)",(cid,u["id"]))
  emit_event(cid,"member.joined",{"user_id":u["id"]})
  return web.json_response({"channel":cjson(c.execute("SELECT * FROM channels WHERE id=?",(cid,)).fetchone())},status=201)
 async def join(request):
  u=require_user(request); c=db.get(); ch=c.execute("SELECT * FROM channels WHERE id=?",(request.match_info["id"],)).fetchone()
  if not ch: raise HTTPError(404,"channel not found")
  w=c.execute("SELECT * FROM workspaces WHERE id=?",(ch["workspace_id"],)).fetchone()
  if ch["is_private"]: raise HTTPError(403,"private channel")
  wm=c.execute("SELECT role FROM workspace_members WHERE workspace_id=? AND user_id=?",(w["id"],u["id"])).fetchone()
  if not wm:
   if w["join_mode"]!="open": raise HTTPError(403,"workspace invitation required")
   c.execute("INSERT INTO workspace_members VALUES(?,?,?)",(w["id"],u["id"],"member"))
  if not c.execute("SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?",(ch["id"],u["id"])).fetchone():
   c.execute("INSERT INTO channel_members VALUES(?,?)",(ch["id"],u["id"])); emit_event(ch["id"],"member.joined",{"user_id":u["id"]})
  return web.json_response({"channel":cjson(ch)})
 async def patch(request):
  u=require_user(request); c=db.get(); ch=c.execute("SELECT * FROM channels WHERE id=?",(request.match_info["id"],)).fetchone()
  if not ch: raise HTTPError(404,"channel not found")
  w=c.execute("SELECT * FROM workspaces WHERE id=?",(ch["workspace_id"],)).fetchone()
  if not c.execute("SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?",(ch["id"],u["id"])).fetchone() and w["owner_id"]!=u["id"]: raise HTTPError(403,"forbidden")
  b=await read_json(request)
  if not isinstance(b.get("topic"),str) or len(b["topic"])>250: raise HTTPError(400,"invalid topic")
  c.execute("UPDATE channels SET topic=? WHERE id=?",(b["topic"],ch["id"])); emit_event(ch["id"],"channel.updated",{"channel":cjson(c.execute("SELECT * FROM channels WHERE id=?",(ch["id"],)).fetchone())})
  return web.json_response({"channel":cjson(c.execute("SELECT * FROM channels WHERE id=?",(ch["id"],)).fetchone())})
 async def archive(request):
  u=require_user(request); c=db.get(); ch=c.execute("SELECT * FROM channels WHERE id=?",(request.match_info["id"],)).fetchone()
  if not ch: raise HTTPError(404,"channel not found")
  w=c.execute("SELECT owner_id FROM workspaces WHERE id=?",(ch["workspace_id"],)).fetchone()
  if w["owner_id"]!=u["id"]: raise HTTPError(403,"forbidden")
  val=1 if request.path.endswith("archive") else 0; c.execute("UPDATE channels SET is_archived=? WHERE id=?",(val,ch["id"]))
  emit_event(ch["id"],"channel.archived" if val else "channel.unarchived",{})
  return web.json_response({"channel":cjson(c.execute("SELECT * FROM channels WHERE id=?",(ch["id"],)).fetchone())})
 app.router.add_post("/api/workspaces",create)
 app.router.add_get("/api/workspaces",listing)
 app.router.add_get("/api/workspaces/{slug}",detail)
 app.router.add_get("/api/workspaces/{slug}/members",members)
 app.router.add_post("/api/workspaces/{slug}/channels",newchannel)
 app.router.add_post("/api/channels/{id}/join",join)
 app.router.add_patch("/api/channels/{id}",patch)
 app.router.add_post("/api/channels/{id}/archive",archive)
 app.router.add_post("/api/channels/{id}/unarchive",archive)
