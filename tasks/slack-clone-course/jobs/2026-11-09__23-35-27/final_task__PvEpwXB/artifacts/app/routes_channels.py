import re
from aiohttp import web
from db import conn,now_iso
from common import *
def get_channel(cid):
    try: cid=int(cid)
    except: raise HTTPError(404,"channel not found")
    r=conn.execute("SELECT * FROM channels WHERE id=?",(cid,)).fetchone()
    if not r: raise HTTPError(404,"channel not found")
    return r
def wrole(wid,uid):
    r=conn.execute("SELECT role FROM workspace_members WHERE workspace_id=? AND user_id=?",(wid,uid)).fetchone()
    return r["role"] if r else None
def access(uid,cid,write=False):
    c=get_channel(cid); wr=wrole(c["workspace_id"],uid)
    member=conn.execute("SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?",(c["id"],uid)).fetchone()
    if c["is_private"] and not member: raise HTTPError(403,"not a channel member")
    if not member and not wr: raise HTTPError(403,"not a member")
    if write and c["is_archived"]: raise HTTPError(423,"channel archived")
    return c
async def create(request):
    uid=require_user(request); w=conn.execute("SELECT * FROM workspaces WHERE slug=?",(request.match_info["slug"],)).fetchone()
    if not w: raise HTTPError(404,"workspace not found")
    rr=wrole(w["id"],uid)
    if not rr: raise HTTPError(403,"not a member")
    b=await read_json(request); n=b.get("name"); topic=b.get("topic","")
    if not isinstance(n,str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*",n) or len(n)>32: raise HTTPError(400,"invalid channel")
    if not isinstance(topic,str) or len(topic)>250: raise HTTPError(400,"invalid topic")
    private=bool(b.get("is_private",False))
    if rr=="guest" or (private and rr not in ("owner","admin")): raise HTTPError(403,"forbidden")
    if conn.execute("SELECT 1 FROM channels WHERE workspace_id=? AND name=?",(w["id"],n)).fetchone(): raise HTTPError(409,"channel exists")
    cid=conn.execute("INSERT INTO channels(workspace_id,name,is_private,topic,created_at) VALUES(?,?,?,?,?)",(w["id"],n,int(private),topic,now_iso())).lastrowid
    conn.execute("INSERT INTO channel_members VALUES(?,?)",(cid,uid))
    emit_event(cid,"member.joined",{"user_id":uid})
    return web.json_response({"channel":channel_json(get_channel(cid))},status=201)
async def join(request):
    uid=require_user(request); c=get_channel(request.match_info["id"]); wr=wrole(c["workspace_id"],uid)
    if c["is_private"]: raise HTTPError(403,"private channel")
    if wr=="guest": raise HTTPError(403,"guest cannot join")
    if not wr:
        w=conn.execute("SELECT join_mode FROM workspaces WHERE id=?",(c["workspace_id"],)).fetchone()
        if not w or w["join_mode"]!="open": raise HTTPError(403,"invite required")
        conn.execute("INSERT INTO workspace_members VALUES(?,?,?)",(c["workspace_id"],uid,"member"))
    conn.execute("INSERT OR IGNORE INTO channel_members VALUES(?,?)",(c["id"],uid))
    emit_event(c["id"],"member.joined",{"user_id":uid})
    return web.json_response({"channel":channel_json(c)})
async def leave(request):
    uid=require_user(request); c=get_channel(request.match_info["id"])
    conn.execute("DELETE FROM channel_members WHERE channel_id=? AND user_id=?",(c["id"],uid))
    emit_event(c["id"],"member.left",{"user_id":uid})
    return web.json_response({"channel":channel_json(c)})
async def patch(request):
    uid=require_user(request); c=get_channel(request.match_info["id"])
    if not conn.execute("SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?",(c["id"],uid)).fetchone() and wrole(c["workspace_id"],uid)!="owner": raise HTTPError(403,"forbidden")
    b=await read_json(request); topic=b.get("topic")
    if not isinstance(topic,str) or len(topic)>250: raise HTTPError(400,"invalid topic")
    if c["is_archived"]: raise HTTPError(423,"channel archived")
    conn.execute("UPDATE channels SET topic=? WHERE id=?",(topic,c["id"]))
    out=channel_json(get_channel(c["id"])); emit_event(c["id"],"channel.updated",{"channel":out})
    return web.json_response({"channel":out})
async def members(request):
    uid=require_user(request); c=access(uid,request.match_info["id"])
    rows=conn.execute("SELECT u.* FROM channel_members m JOIN users u ON u.id=m.user_id WHERE m.channel_id=?",(c["id"],)).fetchall()
    return web.json_response({"members":[user_to_json(x) for x in rows]})
async def archive(request):
    uid=require_user(request); c=get_channel(request.match_info["id"])
    if wrole(c["workspace_id"],uid)!="owner": raise HTTPError(403,"owner only")
    conn.execute("UPDATE channels SET is_archived=1 WHERE id=?",(c["id"],))
    out=channel_json(get_channel(c["id"])); emit_event(c["id"],"channel.archived",{"channel":out})
    return web.json_response({"channel":out})
async def unarchive(request):
    uid=require_user(request); c=get_channel(request.match_info["id"])
    if wrole(c["workspace_id"],uid)!="owner": raise HTTPError(403,"owner only")
    conn.execute("UPDATE channels SET is_archived=0 WHERE id=?",(c["id"],))
    out=channel_json(get_channel(c["id"])); emit_event(c["id"],"channel.unarchived",{"channel":out})
    return web.json_response({"channel":out})
async def add_member(request):
    uid=require_user(request); c=get_channel(request.match_info["id"])
    access(uid,c["id"])
    target=(await read_json(request)).get("user_id")
    if isinstance(target,bool) or not isinstance(target,int): raise HTTPError(400,"invalid user_id")
    if not conn.execute("SELECT 1 FROM workspace_members WHERE workspace_id=? AND user_id=?",(c["workspace_id"],target)).fetchone(): raise HTTPError(400,"user not in workspace")
    conn.execute("INSERT OR IGNORE INTO channel_members VALUES(?,?)",(c["id"],target))
    return web.json_response({"channel":channel_json(get_channel(c["id"]))})

def setup(app):
    app.router.add_post("/api/workspaces/{slug}/channels",create)
    app.router.add_post("/api/channels/{id}/join",join)
    app.router.add_post("/api/channels/{id}/leave",leave)
    app.router.add_patch("/api/channels/{id}",patch)
    app.router.add_get("/api/channels/{id}/members",members); app.router.add_post("/api/channels/{id}/members",add_member)
    app.router.add_post("/api/channels/{id}/archive",archive)
    app.router.add_post("/api/channels/{id}/unarchive",unarchive)
