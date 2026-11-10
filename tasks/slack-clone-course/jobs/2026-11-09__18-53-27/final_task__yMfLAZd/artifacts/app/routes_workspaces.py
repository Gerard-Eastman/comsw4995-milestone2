import re
from aiohttp import web
import db
from common import *
from routes_auth import workspace_json

def setup(app):
 async def create(request):
  u=require_user(request); b=await read_json(request); slug=b.get("slug",""); name=b.get("name","")
  if not re.fullmatch(r"[a-z0-9-]{2,32}",slug) or not isinstance(name,str) or not name: raise HTTPError(400,"invalid workspace")
  c=db.get_conn()
  if c.execute("SELECT 1 FROM workspaces WHERE slug=?",(slug,)).fetchone(): raise HTTPError(409,"workspace exists")
  now=db.now_iso(); w=c.execute("INSERT INTO workspaces(slug,name,owner_id,created_at) VALUES(?,?,?,?)",(slug,name,u["id"],now)).lastrowid
  c.execute("INSERT INTO workspace_members VALUES(?,?,?)",(w,u["id"],"owner"))
  ch=c.execute("INSERT INTO channels(workspace_id,name,created_at) VALUES(?,?,?)",(w,"general",now)).lastrowid
  c.execute("INSERT INTO channel_members VALUES(?,?)",(ch,u["id"]))
  wr=c.execute("SELECT * FROM workspaces WHERE id=?",(w,)).fetchone(); cr=c.execute("SELECT * FROM channels WHERE id=?",(ch,)).fetchone()
  return web.json_response({"workspace":workspace_json(wr),"general_channel":channel_json(cr)},status=201)
 async def lists(request):
  u=require_user(request); rows=db.get_conn().execute("SELECT w.* FROM workspaces w JOIN workspace_members m ON m.workspace_id=w.id WHERE m.user_id=? ORDER BY w.id",(u["id"],)).fetchall()
  return web.json_response({"workspaces":[workspace_json(x) for x in rows]})
 async def detail(request):
  u=require_user(request); c=db.get_conn(); w=c.execute("SELECT * FROM workspaces WHERE slug=?",(request.match_info["slug"],)).fetchone()
  if not w: raise HTTPError(404,"workspace not found")
  mem=c.execute("SELECT 1 FROM workspace_members WHERE workspace_id=? AND user_id=?",(w["id"],u["id"])).fetchone()
  if not mem: raise HTTPError(403,"not a member")
  cs=c.execute("SELECT * FROM channels WHERE workspace_id=? AND is_dm=0 AND (is_archived=0 OR ?)",(w["id"],request.query.get("include_archived") in ("1","true"))).fetchall()
  rs=[{"channel_id":x["id"],"last_read_event_id":0,"unread_count":0,"mention_count":0} for x in cs]
  return web.json_response({"workspace":workspace_json(w),"channels":[channel_json(x) for x in cs],"read_state":rs})
 async def members(request):
  u=require_user(request); c=db.get_conn(); w=c.execute("SELECT * FROM workspaces WHERE slug=?",(request.match_info["slug"],)).fetchone()
  if not w: raise HTTPError(404,"workspace not found")
  if not c.execute("SELECT 1 FROM workspace_members WHERE workspace_id=? AND user_id=?",(w["id"],u["id"])).fetchone(): raise HTTPError(403,"not a member")
  rows=c.execute("SELECT m.*,u.* FROM workspace_members m JOIN users u ON u.id=m.user_id WHERE m.workspace_id=?",(w["id"],)).fetchall()
  return web.json_response({"members":[{"user_id":x["user_id"],"role":x["role"],"user":user_to_json(x)} for x in rows]})
 app.router.add_post("/api/workspaces",create); app.router.add_get("/api/workspaces",lists)
 app.router.add_get("/api/workspaces/{slug}",detail); app.router.add_get("/api/workspaces/{slug}/members",members)
