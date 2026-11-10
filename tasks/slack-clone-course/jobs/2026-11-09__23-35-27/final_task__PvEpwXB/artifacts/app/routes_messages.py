import json,re
from aiohttp import web
from db import conn,now_iso
from common import *
from routes_channels import access,get_channel
def msg(r):
    u=conn.execute("SELECT * FROM users WHERE id=?",(r["author_id"],)).fetchone()
    rc=conn.execute("SELECT count(*) n FROM messages WHERE parent_id=? AND deleted=0",(r["id"],)).fetchone()["n"]
    reactions=[]
    for x in conn.execute("SELECT emoji,count(*) n FROM reactions WHERE message_id=? GROUP BY emoji",(r["id"],)):
        ids=[z["user_id"] for z in conn.execute("SELECT user_id FROM reactions WHERE message_id=? AND emoji=?",(r["id"],x["emoji"]))]
        reactions.append({"emoji":x["emoji"],"count":x["n"],"user_ids":ids})
    fs=[]
    for f in conn.execute("SELECT f.id,f.uploader_id,f.filename,f.content_type,f.size,f.created_at FROM files f JOIN message_files mf ON mf.file_id=f.id WHERE mf.message_id=?",(r["id"],)):
        fs.append(dict(f))
    return {"id":r["id"],"channel_id":r["channel_id"],"author_id":r["author_id"],"author":user_to_json(u),
      "body":r["body"],"parent_id":r["parent_id"],"reply_count":rc,"created_at":r["created_at"],
      "edited_at":r["edited_at"],"files":fs,"reactions":reactions,"mentions":json.loads(r["mentions"] or "[]")}
def mentions(body,cid,uid):
    c=get_channel(cid); members=[x["user_id"] for x in conn.execute("SELECT user_id FROM channel_members WHERE channel_id=?",(cid,))]
    out=[]
    for m in re.finditer(r"(?<![A-Za-z0-9_@.])@([A-Za-z0-9_](?:[A-Za-z0-9_-]*[A-Za-z0-9_])?)(?![A-Za-z0-9_@-])(?!\\.[A-Za-z0-9])",body):
        n=m.group(1)
        if n=="here": out += [x["user_id"] for x in conn.execute("SELECT DISTINCT user_id FROM ws_presence WHERE user_id IN (%s)"%(",".join("?"*len(members)) if members else "0"),tuple(members))]
        elif n=="channel": out += members
        else:
            u=conn.execute("SELECT id FROM users WHERE username=? AND id IN (SELECT user_id FROM workspace_members WHERE workspace_id=?)",(n,c["workspace_id"])).fetchone()
            if u: out.append(u["id"])
            else:
                g=conn.execute("SELECT id FROM groups_tbl WHERE workspace_id=? AND handle=?",(c["workspace_id"],n)).fetchone()
                if g: out += [x["user_id"] for x in conn.execute("SELECT user_id FROM group_members WHERE group_id=? AND user_id IN (SELECT user_id FROM channel_members WHERE channel_id=?)",(g["id"],cid))]
    return list(dict.fromkeys(x for x in out if x!=uid))

async def post(request):
    uid=require_user(request); cid=int(request.match_info["id"]); c=access(uid,cid,False); b=await read_json(request); body=b.get("body")
    if not isinstance(body,str) or not body.strip(): raise HTTPError(400,"empty body")
    if body.startswith("//"):
        body=body[1:]
    elif body.startswith("/"):
        if body.startswith("/shrug"):
            rest=body[6:].strip()
            body=(rest+" " if rest else "")+"¯\\_(ツ)_/¯"
        elif body.startswith("/me"):
            if not body[3:].strip(): raise HTTPError(400,"missing text")
        elif body.startswith("/topic"):
            text=body[6:].strip()
            if len(text)>250: raise HTTPError(400,"invalid topic")
            if not conn.execute("SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?",(cid,uid)).fetchone():
                raise HTTPError(403,"channel member required")
            conn.execute("UPDATE channels SET topic=? WHERE id=?",(text,cid))
            out=channel_json(get_channel(cid)); emit_event(cid,"channel.updated",{"channel":out})
            return web.json_response({"message":None,"channel":out},status=201)
        elif body.startswith("/invite"):
            m=re.fullmatch(r"/invite\s+@([A-Za-z0-9_]+)",body)
            if not m: raise HTTPError(400,"invalid invite")
            wr=conn.execute("SELECT owner_id FROM workspaces WHERE id=?",(c["workspace_id"],)).fetchone()
            if not wr or wr["owner_id"]!=uid: raise HTTPError(403,"owner only")
            target=conn.execute("SELECT * FROM users WHERE username=?",(m.group(1),)).fetchone()
            if not target: raise HTTPError(404,"user not found")
            if not conn.execute("SELECT 1 FROM workspace_members WHERE workspace_id=? AND user_id=?",(c["workspace_id"],target["id"])).fetchone():
                raise HTTPError(400,"user is not in workspace")
            conn.execute("INSERT OR IGNORE INTO channel_members VALUES(?,?)",(cid,target["id"]))
            return web.json_response({"message":None,"invited_user":user_to_json(target)},status=201)
        elif body in ("/archive","/unarchive"):
            wr=conn.execute("SELECT owner_id FROM workspaces WHERE id=?",(c["workspace_id"],)).fetchone()
            if not wr or wr["owner_id"]!=uid: raise HTTPError(403,"owner only")
            archived=1 if body=="/archive" else 0
            conn.execute("UPDATE channels SET is_archived=? WHERE id=?",(archived,cid))
            out=channel_json(get_channel(cid))
            kind="channel.archived" if archived else "channel.unarchived"
            emit_event(cid,kind,{"channel":out})
            return web.json_response({"message":None,"channel":out},status=201)
        else:
            raise HTTPError(400,"unknown command")
    c=access(uid,cid,True)
    parent=b.get("parent_id"); mm=mentions(body,cid,uid)
    file_ids=b.get("file_ids",[])
    if not isinstance(file_ids,list): raise HTTPError(400,"invalid files")
    for fid in file_ids:
        if isinstance(fid,bool) or not isinstance(fid,int): raise HTTPError(400,"invalid file")
        f=conn.execute("SELECT * FROM files WHERE id=?",(fid,)).fetchone()
        if not f or f["uploader_id"]!=uid or conn.execute("SELECT 1 FROM message_files WHERE file_id=?",(fid,)).fetchone(): raise HTTPError(400,"invalid file")
    cur=conn.execute("INSERT INTO messages(channel_id,author_id,body,parent_id,created_at,mentions) VALUES(?,?,?,?,?,?)",(cid,uid,body,parent,now_iso(),json.dumps(mm)))
    for fid in file_ids: conn.execute("INSERT INTO message_files(message_id,file_id) VALUES(?,?)",(cur.lastrowid,fid))
    r=conn.execute("SELECT * FROM messages WHERE id=?",(cur.lastrowid,)).fetchone()
    kind="message.reply" if parent else "message.created"; emit_event(cid,kind,{"message":msg(r)})
    return web.json_response({"message":msg(r)},status=201)

async def listing(request):
    uid=require_user(request); cid=int(request.match_info["id"]); access(uid,cid); lim=parse_limit(request); args=[cid]
    q="SELECT * FROM messages WHERE channel_id=? AND parent_id IS NULL AND deleted=0"
    if request.query.get("cursor"): q+=" AND id<?"; args.append(decode_cursor(request.query["cursor"]))
    rows=conn.execute(q+" ORDER BY id DESC LIMIT ?",args+[lim+1]).fetchall()
    return web.json_response({"messages":[msg(x) for x in rows[:lim]],"next_cursor":encode_cursor(rows[lim-1]["id"]) if len(rows)>lim else None})
async def replies(request):
    uid=require_user(request); p=conn.execute("SELECT * FROM messages WHERE id=?",(int(request.match_info["id"]),)).fetchone()
    if not p: raise HTTPError(404,"message not found")
    access(uid,p["channel_id"]); lim=parse_limit(request); args=[p["id"]]; q="SELECT * FROM messages WHERE parent_id=? AND deleted=0"
    if request.query.get("cursor"): q+=" AND id>?"; args.append(decode_cursor(request.query["cursor"]))
    rows=conn.execute(q+" ORDER BY id ASC LIMIT ?",args+[lim+1]).fetchall()
    return web.json_response({"replies":[msg(x) for x in rows[:lim]],"next_cursor":encode_cursor(rows[lim-1]["id"]) if len(rows)>lim else None})
async def edit(request):
    uid=require_user(request); r=conn.execute("SELECT * FROM messages WHERE id=?",(int(request.match_info["id"]),)).fetchone()
    if not r: raise HTTPError(404,"message not found")
    c=access(uid,r["channel_id"],True)
    if r["author_id"]!=uid: raise HTTPError(403,"forbidden")
    if r["deleted"]: raise HTTPError(409,"deleted")
    b=await read_json(request)
    if not isinstance(b.get("body"),str) or not b["body"].strip(): raise HTTPError(400,"empty body")
    conn.execute("UPDATE messages SET body=?,edited_at=? WHERE id=?",(b["body"],now_iso(),r["id"]))
    x=conn.execute("SELECT * FROM messages WHERE id=?",(r["id"],)).fetchone(); emit_event(c["id"],"message.updated",{"message":msg(x)})
    return web.json_response({"message":msg(x)})
async def delete(request):
    uid=require_user(request); r=conn.execute("SELECT * FROM messages WHERE id=?",(int(request.match_info["id"]),)).fetchone()
    if not r: raise HTTPError(404,"message not found")
    c=access(uid,r["channel_id"],True); w=conn.execute("SELECT owner_id FROM workspaces WHERE id=?",(c["workspace_id"],)).fetchone()
    if uid!=r["author_id"] and uid!=w["owner_id"]: raise HTTPError(403,"forbidden")
    if r["deleted"]: return web.json_response({"deleted":True})
    conn.execute("UPDATE messages SET deleted=1 WHERE id=?",(r["id"],)); emit_event(c["id"],"message.deleted",{"message_id":r["id"]})
    return web.json_response({"deleted":True})
async def react(request):
    uid=require_user(request); r=conn.execute("SELECT * FROM messages WHERE id=?",(int(request.match_info["id"]),)).fetchone()
    if not r or r["deleted"]: raise HTTPError(404,"message not found")
    c=access(uid,r["channel_id"],True); e=(await read_json(request)).get("emoji")
    if not isinstance(e,str) or not e or len(e)>32: raise HTTPError(400,"invalid emoji")
    cur=conn.execute("INSERT OR IGNORE INTO reactions VALUES(?,?,?)",(r["id"],uid,e))
    current=msg(conn.execute("SELECT * FROM messages WHERE id=?",(r["id"],)).fetchone())["reactions"]
    if cur.rowcount:
        emit_event(c["id"],"reaction.added",{"message_id":r["id"],"emoji":e,"user_id":uid,"reactions":current})
    return web.json_response({"reactions":current})
async def unreact(request):
    uid=require_user(request); r=conn.execute("SELECT * FROM messages WHERE id=?",(int(request.match_info["id"]),)).fetchone()
    if not r: raise HTTPError(404,"message not found")
    c=access(uid,r["channel_id"],True); e=request.match_info["emoji"]
    cur=conn.execute("DELETE FROM reactions WHERE message_id=? AND user_id=? AND emoji=?",(r["id"],uid,e))
    current=msg(conn.execute("SELECT * FROM messages WHERE id=?",(r["id"],)).fetchone())["reactions"]
    if cur.rowcount:
        emit_event(c["id"],"reaction.removed",{"message_id":r["id"],"emoji":e,"user_id":uid,"reactions":current})
    return web.json_response({"reactions":current})
async def pin(request):
    uid=require_user(request); r=conn.execute("SELECT * FROM messages WHERE id=?",(int(request.match_info["id"]),)).fetchone()
    if not r: raise HTTPError(404,"message not found")
    c=access(uid,r["channel_id"],True); t=now_iso(); conn.execute("INSERT OR IGNORE INTO pins VALUES(?,?,?)",(r["id"],uid,t))
    x=conn.execute("SELECT * FROM pins WHERE message_id=?",(r["id"],)).fetchone(); return web.json_response({"pin":dict(x)})
async def unpin(request):
    uid=require_user(request); r=conn.execute("SELECT * FROM messages WHERE id=?",(int(request.match_info["id"]),)).fetchone()
    if not r: raise HTTPError(404,"message not found")
    access(uid,r["channel_id"],True); conn.execute("DELETE FROM pins WHERE message_id=?",(r["id"],)); return web.json_response({"unpinned":True})
async def pins(request):
    uid=require_user(request); c=access(uid,request.match_info["id"]); lim=parse_limit(request); args=[c["id"]]; q="SELECT p.*,m.* FROM pins p JOIN messages m ON m.id=p.message_id WHERE m.channel_id=?"
    if request.query.get("cursor"): q+=" AND p.message_id<?"; args.append(decode_cursor(request.query["cursor"]))
    rows=conn.execute(q+" ORDER BY p.message_id DESC LIMIT ?",args+[lim+1]).fetchall()
    return web.json_response({"pins":[{"message":msg(x),"pinned_by":x["pinned_by"],"pinned_at":x["pinned_at"]} for x in rows[:lim]],"next_cursor":encode_cursor(rows[lim-1]["message_id"]) if len(rows)>lim else None})
async def search(request):
    uid=require_user(request); q=request.query.get("q","").strip()
    if not q: raise HTTPError(400,"missing query")
    lim=parse_limit(request); args=[uid,"%"+q+"%"]; where="m.deleted=0 AND m.body LIKE ?"
    if request.query.get("workspace_id"):
        try: wid=int(request.query["workspace_id"])
        except: raise HTTPError(400,"invalid workspace_id")
        where+=" AND c.workspace_id=?"; args.append(wid)
    if request.query.get("cursor"):
        where+=" AND m.id<?"; args.append(decode_cursor(request.query["cursor"]))
    rows=conn.execute("SELECT m.* FROM messages m JOIN channels c ON c.id=m.channel_id JOIN channel_members cm ON cm.channel_id=c.id AND cm.user_id=? WHERE "+where+" ORDER BY m.id DESC LIMIT ?",args+[lim+1]).fetchall()
    return web.json_response({"results":[msg(x) for x in rows[:lim]],"next_cursor":encode_cursor(rows[lim-1]["id"]) if len(rows)>lim else None})
async def read(request):
    uid=require_user(request); c=access(uid,request.match_info["id"]); x=conn.execute("SELECT * FROM read_state WHERE user_id=? AND channel_id=?",(uid,c["id"])).fetchone()
    last=x["last_read_event_id"] if x else 0
    rows=conn.execute("SELECT e.event_id,e.payload FROM events e WHERE e.channel_id=? AND e.event_id>?",(c["id"],last)).fetchall()
    unread=mentions_n=0
    for z in rows:
        try:
            f=json.loads(z["payload"]); m=f.get("message") or {}
            if f.get("type") in ("message.created","message.reply") and m.get("author_id") != uid:
                unread+=1
                if uid in (m.get("mentions") or []): mentions_n+=1
        except: pass
    return web.json_response({"read_state":{"channel_id":c["id"],"last_read_event_id":last,"unread_count":unread,"mention_count":mentions_n}})
async def markread(request):
    uid=require_user(request); c=access(uid,request.match_info["id"]); n=(await read_json(request)).get("last_read_event_id",0)
    old=conn.execute("SELECT last_read_event_id FROM read_state WHERE user_id=? AND channel_id=?",(uid,c["id"])).fetchone(); n=max(n,old[0] if old else 0)
    conn.execute("INSERT OR REPLACE INTO read_state VALUES(?,?,?)",(uid,c["id"],n)); return await read(request)
def setup(app):
    app.router.add_post("/api/channels/{id}/messages",post); app.router.add_get("/api/channels/{id}/messages",listing)
    app.router.add_get("/api/messages/{id}/replies",replies); app.router.add_patch("/api/messages/{id}",edit); app.router.add_delete("/api/messages/{id}",delete)
    app.router.add_post("/api/messages/{id}/reactions",react); app.router.add_delete("/api/messages/{id}/reactions/{emoji}",unreact)
    app.router.add_post("/api/messages/{id}/pin",pin); app.router.add_delete("/api/messages/{id}/pin",unpin); app.router.add_get("/api/channels/{id}/pins",pins)
    app.router.add_get("/api/search",search); app.router.add_get("/api/channels/{id}/read",read); app.router.add_post("/api/channels/{id}/read",markread)
