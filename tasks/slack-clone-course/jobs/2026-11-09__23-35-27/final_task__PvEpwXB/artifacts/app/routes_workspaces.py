import re,secrets,datetime
from aiohttp import web
from db import conn,now_iso
from common import *
def workspace(slug):
    r=conn.execute("SELECT * FROM workspaces WHERE slug=?",(slug,)).fetchone()
    if not r: raise HTTPError(404,"workspace not found")
    return r
def role(wid,uid):
    r=conn.execute("SELECT role FROM workspace_members WHERE workspace_id=? AND user_id=?",(wid,uid)).fetchone()
    return r["role"] if r else None
def admin(wid,uid):
    return role(wid,uid) in ("owner","admin")
async def create(request):
    uid=require_user(request); b=await read_json(request); slug=b.get("slug"); name=b.get("name")
    if not isinstance(slug,str) or not re.fullmatch(r"[a-z0-9-]{2,32}",slug) or not isinstance(name,str) or not name: raise HTTPError(400,"invalid workspace")
    if conn.execute("SELECT 1 FROM workspaces WHERE slug=?",(slug,)).fetchone(): raise HTTPError(409,"workspace exists")
    conn.execute("BEGIN")
    try:
        wid=conn.execute("INSERT INTO workspaces(slug,name,owner_id,created_at) VALUES(?,?,?,?)",(slug,name,uid,now_iso())).lastrowid
        conn.execute("INSERT INTO workspace_members VALUES(?,?,?)",(wid,uid,"owner"))
        cid=conn.execute("INSERT INTO channels(workspace_id,name,created_at) VALUES(?,?,?)",(wid,"general",now_iso())).lastrowid
        conn.execute("INSERT INTO channel_members VALUES(?,?)",(cid,uid)); conn.execute("COMMIT")
    except: conn.execute("ROLLBACK"); raise
    return web.json_response({"workspace":dict(conn.execute("SELECT * FROM workspaces WHERE id=?",(wid,)).fetchone()),"general_channel":channel_json(conn.execute("SELECT * FROM channels WHERE id=?",(cid,)).fetchone())},status=201)
async def listing(request):
    uid=require_user(request)
    rows=conn.execute("SELECT w.* FROM workspaces w JOIN workspace_members m ON m.workspace_id=w.id WHERE m.user_id=?",(uid,)).fetchall()
    return web.json_response({"workspaces":[dict(x) for x in rows]})
async def detail(request):
    uid=require_user(request); w=workspace(request.match_info["slug"])
    if not role(w["id"],uid): raise HTTPError(403,"not a member")
    inc=request.query.get("include_archived") in ("1","true")
    q="SELECT * FROM channels WHERE workspace_id=? AND is_dm=0"; args=[w["id"]]
    if not inc:q+=" AND is_archived=0"
    cs=conn.execute(q+" AND (is_private=0 OR id IN (SELECT channel_id FROM channel_members WHERE user_id=?))",args+[uid]).fetchall()
    states=[]
    for x in cs:
        z=conn.execute("SELECT last_read_event_id FROM read_state WHERE user_id=? AND channel_id=?",(uid,x["id"])).fetchone()
        last=z["last_read_event_id"] if z else 0
        unread=mentions_n=0
        import json
        for ev in conn.execute("SELECT payload FROM events WHERE channel_id=? AND event_id>?",(x["id"],last)):
            try:
                f=json.loads(ev["payload"]); m=f.get("message") or {}
                if f.get("type") in ("message.created","message.reply") and m.get("author_id") != uid:
                    unread+=1
                    if uid in (m.get("mentions") or []): mentions_n+=1
            except Exception: pass
        states.append({"channel_id":x["id"],"last_read_event_id":last,"unread_count":unread,"mention_count":mentions_n})
    return web.json_response({"workspace":dict(w),"channels":[channel_json(x) for x in cs],"read_state":states})
async def members(request):
    uid=require_user(request); w=workspace(request.match_info["slug"])
    if not role(w["id"],uid): raise HTTPError(403,"not a member")
    rows=conn.execute("SELECT m.*,u.* FROM workspace_members m JOIN users u ON u.id=m.user_id WHERE m.workspace_id=?",(w["id"],)).fetchall()
    return web.json_response({"members":[{"user_id":x["user_id"],"role":x["role"],"user":user_to_json(x)} for x in rows]})
async def patch(request):
    uid=require_user(request); w=workspace(request.match_info["slug"])
    if not admin(w["id"],uid): raise HTTPError(403,"forbidden")
    b=await read_json(request)
    if "join_mode" in b and b["join_mode"] not in ("open","invite_only"): raise HTTPError(400,"invalid join mode")
    sets=[]; vals=[]
    for k in ("name","join_mode"):
        if k in b: sets.append(k+"=?"); vals.append(b[k])
    if sets: conn.execute("UPDATE workspaces SET "+",".join(sets)+" WHERE id=?",vals+[w["id"]])
    return web.json_response({"workspace":dict(conn.execute("SELECT * FROM workspaces WHERE id=?",(w["id"],)).fetchone())})
async def setrole(request):
    uid=require_user(request); w=workspace(request.match_info["slug"]); target=int(request.match_info["user_id"])
    rr=role(w["id"],uid); b=await read_json(request); nr=b.get("role")
    if nr not in ("admin","member","guest"): raise HTTPError(400,"invalid role")
    if rr not in ("owner","admin") or target==w["owner_id"] or (rr=="admin" and role(w["id"],target)=="admin"): raise HTTPError(403,"forbidden")
    if not role(w["id"],target): raise HTTPError(404,"member not found")
    conn.execute("UPDATE workspace_members SET role=? WHERE workspace_id=? AND user_id=?",(nr,w["id"],target))
    return web.json_response({"member":{"user_id":target,"role":nr}})
async def transfer(request):
    uid=require_user(request); w=workspace(request.match_info["slug"])
    if uid!=w["owner_id"]: raise HTTPError(403,"forbidden")
    target=(await read_json(request)).get("new_owner_id")
    if role(w["id"],target)!="admin": raise HTTPError(400,"target must be admin")
    conn.execute("UPDATE workspace_members SET role='admin' WHERE workspace_id=? AND user_id=?",(w["id"],uid))
    conn.execute("UPDATE workspace_members SET role='owner' WHERE workspace_id=? AND user_id=?",(w["id"],target))
    conn.execute("UPDATE workspaces SET owner_id=? WHERE id=?",(target,w["id"]))
    return web.json_response({"workspace":dict(conn.execute("SELECT * FROM workspaces WHERE id=?",(w["id"],)).fetchone())})
async def invite(request):
    uid=require_user(request); w=workspace(request.match_info["slug"])
    if not admin(w["id"],uid): raise HTTPError(403,"forbidden")
    b=await read_json(request); target=b.get("invited_user_id")
    if not target and b.get("invited_username"):
        x=conn.execute("SELECT id FROM users WHERE username=?",(b["invited_username"],)).fetchone(); target=x["id"] if x else None
    maxu=1 if target else int(b.get("max_uses",1)); exp=int(b.get("expires_in_seconds",86400))
    code=secrets.token_urlsafe(18)
    conn.execute("INSERT INTO invitations VALUES(?,?,?,?,?,?,?,?)",(code,w["id"],uid,target,(datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(seconds=exp)).isoformat(),maxu,0,0))
    return web.json_response({"invitation":{"code":code,"workspace_id":w["id"],"max_uses":maxu}},status=201)
async def accept(request):
    uid=require_user(request); r=conn.execute("SELECT * FROM invitations WHERE code=?",(request.match_info["code"],)).fetchone()
    if not r or r["revoked"] or r["uses"]>=r["max_uses"] or r["expires_at"]<datetime.datetime.now(datetime.timezone.utc).isoformat(): raise HTTPError(404,"invitation not found")
    if r["invited_user_id"] and r["invited_user_id"]!=uid: raise HTTPError(403,"targeted invitation")
    conn.execute("INSERT OR IGNORE INTO workspace_members VALUES(?,?,?)",(r["workspace_id"],uid,"member")); conn.execute("UPDATE invitations SET uses=uses+1 WHERE code=?",(r["code"],))
    return web.json_response({"workspace":dict(conn.execute("SELECT * FROM workspaces WHERE id=?",(r["workspace_id"],)).fetchone())})
async def invlist(request):
    uid=require_user(request); w=workspace(request.match_info["slug"])
    if not admin(w["id"],uid): raise HTTPError(403,"forbidden")
    return web.json_response({"invitations":[dict(x) for x in conn.execute("SELECT * FROM invitations WHERE workspace_id=? AND revoked=0",(w["id"],))]})
async def invdelete(request):
    uid=require_user(request); w=workspace(request.match_info["slug"])
    if not admin(w["id"],uid): raise HTTPError(403,"forbidden")
    conn.execute("UPDATE invitations SET revoked=1 WHERE code=? AND workspace_id=?",(request.match_info["code"],w["id"]))
    return web.json_response({"deleted":True})
def setup(app):
    app.router.add_post("/api/workspaces",create); app.router.add_get("/api/workspaces",listing)
    app.router.add_get("/api/workspaces/{slug}",detail); app.router.add_get("/api/workspaces/{slug}/members",members)
    app.router.add_patch("/api/workspaces/{slug}",patch); app.router.add_patch("/api/workspaces/{slug}/members/{user_id}",setrole)
    app.router.add_post("/api/workspaces/{slug}/transfer_ownership",transfer)
    app.router.add_post("/api/workspaces/{slug}/invitations",invite); app.router.add_get("/api/workspaces/{slug}/invitations",invlist)
    app.router.add_delete("/api/workspaces/{slug}/invitations/{code}",invdelete)
    app.router.add_post("/api/invitations/{code}/accept",accept)
