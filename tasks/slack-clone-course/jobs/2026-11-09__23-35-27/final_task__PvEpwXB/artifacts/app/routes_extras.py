import os,secrets,re
from zoneinfo import ZoneInfo
from aiohttp import web
from db import conn,now_iso
from common import require_user,read_json,HTTPError
def group_json(r):
    ids=[x["user_id"] for x in conn.execute("SELECT user_id FROM group_members WHERE group_id=? ORDER BY user_id",(r["id"],))]
    return {"id":r["id"],"handle":r["handle"],"name":r["name"],"member_user_ids":ids}
def get_workspace(slug):
    r=conn.execute("SELECT * FROM workspaces WHERE slug=?",(slug,)).fetchone()
    if not r: raise HTTPError(404,"workspace not found")
    return r
def wrole(wid,uid):
    r=conn.execute("SELECT role FROM workspace_members WHERE workspace_id=? AND user_id=?",(wid,uid)).fetchone()
    return r["role"] if r else None
async def create_dm(request):
    uid=require_user(request); b=await read_json(request); target=b.get("user_id")
    if isinstance(target,bool) or not isinstance(target,int): raise HTTPError(400,"invalid user_id")
    if not conn.execute("SELECT 1 FROM users WHERE id=?",(target,)).fetchone(): raise HTTPError(404,"user not found")
    if target==uid: raise HTTPError(400,"cannot DM yourself")
    pair=sorted((uid,target))
    row=conn.execute("SELECT c.id FROM channels c JOIN channel_members a ON a.channel_id=c.id AND a.user_id=? JOIN channel_members b ON b.channel_id=c.id AND b.user_id=? WHERE c.is_dm=1 LIMIT 1",(pair[0],pair[1])).fetchone()
    if row:return web.json_response({"channel_id":row["id"]})
    w=conn.execute("SELECT workspace_id FROM workspace_members WHERE user_id=? AND workspace_id IN (SELECT workspace_id FROM workspace_members WHERE user_id=?) ORDER BY workspace_id LIMIT 1",(uid,target)).fetchone()
    if not w:
        w=conn.execute("SELECT id AS workspace_id FROM workspaces ORDER BY id LIMIT 1").fetchone()
        if not w: raise HTTPError(400,"no workspace")
    name="dm-%d-%d"%tuple(pair)
    cid=conn.execute("INSERT INTO channels(workspace_id,name,is_dm,is_private,created_at) VALUES(?,?,1,1,?)",(w["workspace_id"],name,now_iso())).lastrowid
    conn.execute("INSERT INTO channel_members VALUES(?,?)",(cid,uid)); conn.execute("INSERT INTO channel_members VALUES(?,?)",(cid,target))
    return web.json_response({"channel_id":cid})
async def upload(request):
    uid=require_user(request)
    try: data=await request.post()
    except Exception: raise HTTPError(400,"invalid upload")
    f=data.get("file")
    if not f or not hasattr(f,"file"): raise HTTPError(400,"file required")
    content=f.file.read()
    if len(content)>10*1024*1024: raise HTTPError(413,"file too large")
    fid=conn.execute("INSERT INTO files(uploader_id,filename,content_type,size,created_at,path) VALUES(?,?,?,?,?,?)",(uid,f.filename or "file",f.content_type or "application/octet-stream",len(content),now_iso(),"")).lastrowid
    path=f"/app/data/files/{fid}-{secrets.token_hex(8)}"
    with open(path,"wb") as out: out.write(content)
    conn.execute("UPDATE files SET path=? WHERE id=?",(path,fid))
    return web.json_response({"file":dict(conn.execute("SELECT id,uploader_id,filename,content_type,size,created_at FROM files WHERE id=?",(fid,)).fetchone())},status=201)
async def get_file(request):
    require_user(request); r=conn.execute("SELECT * FROM files WHERE id=?",(int(request.match_info["id"]),)).fetchone()
    if not r: raise HTTPError(404,"file not found")
    return web.json_response({"file":{k:r[k] for k in ("id","uploader_id","filename","content_type","size","created_at")}})
async def download(request):
    require_user(request); r=conn.execute("SELECT * FROM files WHERE id=?",(int(request.match_info["id"]),)).fetchone()
    if not r: raise HTTPError(404,"file not found")
    return web.FileResponse(r["path"],headers={"Content-Type":r["content_type"],"Content-Disposition":'attachment; filename="%s"'%r["filename"]})
async def groups(request):
    uid=require_user(request); w=get_workspace(request.match_info["slug"])
    if not wrole(w["id"],uid): raise HTTPError(403,"not a member")
    return web.json_response({"groups":[group_json(x) for x in conn.execute("SELECT * FROM groups_tbl WHERE workspace_id=? ORDER BY id",(w["id"],))]})
async def group_create(request):
    uid=require_user(request); w=get_workspace(request.match_info["slug"])
    if not wrole(w["id"],uid): raise HTTPError(403,"not a member")
    b=await read_json(request); h=b.get("handle"); name=b.get("name"); ids=b.get("user_ids",[])
    if not isinstance(h,str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,30}[a-z0-9]",h) or h in ("here","channel") or not isinstance(name,str) or not name or not isinstance(ids,list): raise HTTPError(400,"invalid group")
    members={x["user_id"] for x in conn.execute("SELECT user_id FROM workspace_members WHERE workspace_id=?",(w["id"],))}
    if any(isinstance(x,bool) or not isinstance(x,int) or x not in members for x in ids): raise HTTPError(400,"invalid members")
    if conn.execute("SELECT 1 FROM groups_tbl WHERE workspace_id=? AND handle=?",(w["id"],h)).fetchone(): raise HTTPError(409,"group exists")
    gid=conn.execute("INSERT INTO groups_tbl(workspace_id,handle,name,creator_id) VALUES(?,?,?,?)",(w["id"],h,name,uid)).lastrowid
    for x in sorted(set(ids)): conn.execute("INSERT INTO group_members VALUES(?,?)",(gid,x))
    return web.json_response({"group":group_json(conn.execute("SELECT * FROM groups_tbl WHERE id=?",(gid,)).fetchone())},status=201)
async def group_patch(request):
    uid=require_user(request); w=get_workspace(request.match_info["slug"]); r=conn.execute("SELECT * FROM groups_tbl WHERE workspace_id=? AND handle=?",(w["id"],request.match_info["handle"])).fetchone()
    if not r: raise HTTPError(404,"group not found")
    if uid!=r["creator_id"] and uid!=w["owner_id"]: raise HTTPError(403,"forbidden")
    b=await read_json(request)
    if "name" in b:
        if not isinstance(b["name"],str) or not b["name"]: raise HTTPError(400,"invalid name")
        conn.execute("UPDATE groups_tbl SET name=? WHERE id=?",(b["name"],r["id"]))
    if "user_ids" in b:
        ids=b["user_ids"]; members={x["user_id"] for x in conn.execute("SELECT user_id FROM workspace_members WHERE workspace_id=?",(w["id"],))}
        if not isinstance(ids,list) or any(x not in members or isinstance(x,bool) for x in ids): raise HTTPError(400,"invalid members")
        conn.execute("DELETE FROM group_members WHERE group_id=?",(r["id"],))
        for x in sorted(set(ids)): conn.execute("INSERT INTO group_members VALUES(?,?)",(r["id"],x))
    return web.json_response({"group":group_json(conn.execute("SELECT * FROM groups_tbl WHERE id=?",(r["id"],)).fetchone())})
async def group_delete(request):
    uid=require_user(request); w=get_workspace(request.match_info["slug"]); r=conn.execute("SELECT * FROM groups_tbl WHERE workspace_id=? AND handle=?",(w["id"],request.match_info["handle"])).fetchone()
    if r and uid!=r["creator_id"] and uid!=w["owner_id"]: raise HTTPError(403,"forbidden")
    if r: conn.execute("DELETE FROM groups_tbl WHERE id=?",(r["id"],))
    return web.json_response({"deleted":True})
async def get_user(request):
    require_user(request)
    try: uid=int(request.match_info["id"])
    except: raise HTTPError(404,"user not found")
    r=conn.execute("SELECT * FROM users WHERE id=?",(uid,)).fetchone()
    if not r: raise HTTPError(404,"user not found")
    from common import user_to_json
    return web.json_response({"user":user_to_json(r)})
async def patch_me(request):
    uid=require_user(request); b=await read_json(request)
    allowed=("display_name","timezone","avatar_url","status_text","status_emoji")
    sets=[]; vals=[]
    for k in allowed:
        if k not in b: continue
        v=b[k]
        if not isinstance(v,str) or len(v)>250 or (k=="display_name" and (not v.strip() or len(v)>80)) or (k=="status_text" and len(v)>100) or (k=="status_emoji" and len(v)>64): raise HTTPError(400,"invalid profile")
        if k=="timezone":
            try: ZoneInfo(v)
            except Exception: raise HTTPError(400,"invalid timezone")
        sets.append(k+"=?"); vals.append(v)
    if sets:
        conn.execute("UPDATE users SET "+",".join(sets)+" WHERE id=?",vals+[uid])
    r=conn.execute("SELECT * FROM users WHERE id=?",(uid,)).fetchone()
    from common import broadcast_global,user_to_json
    broadcast_global({"type":"user.updated","user":user_to_json(r)})
    return web.json_response({"user":user_to_json(r)})

def setup(app):
    app.router.add_post("/api/dms",create_dm)
    app.router.add_post("/api/files",upload); app.router.add_get("/api/files/{id}",get_file); app.router.add_get("/api/files/{id}/download",download)
    app.router.add_get("/api/users/{id}",get_user)
    app.router.add_patch("/api/users/me",patch_me)
    app.router.add_get("/api/workspaces/{slug}/groups",groups); app.router.add_post("/api/workspaces/{slug}/groups",group_create)
    app.router.add_patch("/api/workspaces/{slug}/groups/{handle}",group_patch); app.router.add_delete("/api/workspaces/{slug}/groups/{handle}",group_delete)
