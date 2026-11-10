from aiohttp import web
import re, json
import db
from common import *

def setup(app):
 def msg(c,r):
  author=c.execute("SELECT * FROM users WHERE id=?",(r["author_id"],)).fetchone()
  replies=c.execute("SELECT count(*) FROM messages WHERE parent_id=? AND deleted=0",(r["id"],)).fetchone()[0]
  return {"id":r["id"],"channel_id":r["channel_id"],"author_id":r["author_id"],
   "author":user_to_json(author),"body":r["body"],"parent_id":r["parent_id"],
   "reply_count":replies,"created_at":r["created_at"],"edited_at":r["edited_at"],
   "files":[],"reactions":[],"mentions":[]}
 def access(c,ch,u,write=False):
  if not ch: raise HTTPError(404,"channel not found")
  if not c.execute("SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?",(ch["id"],u["id"])).fetchone():
   if ch["is_private"] or not c.execute("SELECT 1 FROM workspace_members WHERE workspace_id=? AND user_id=?",(ch["workspace_id"],u["id"])).fetchone(): raise HTTPError(403,"forbidden")
  if write and ch["is_archived"]: raise HTTPError(423,"channel archived")
 async def create(request):
  u=require_user(request); c=db.get_conn(); ch=c.execute("SELECT * FROM channels WHERE id=?",(request.match_info["id"],)).fetchone(); access(c,ch,u,True)
  b=await read_json(request); body=b.get("body")
  if not isinstance(body,str) or not body.strip(): raise HTTPError(400,"empty message")
  parent=b.get("parent_id"); parentrow=None
  if parent is not None:
   parentrow=c.execute("SELECT * FROM messages WHERE id=? AND deleted=0",(parent,)).fetchone()
   if not parentrow or parentrow["channel_id"]!=ch["id"]: raise HTTPError(400,"invalid parent")
  if body.startswith("/") and not body.startswith("//"):
   if body.startswith("/shrug"): body=body[6:].strip()+" ¯\\_(ツ)_/¯"
   elif body.startswith("/me") and len(body.strip())<=3: raise HTTPError(400,"missing text")
   elif body.startswith("/") and not body.startswith("/me"): raise HTTPError(400,"unknown command")
  now=db.now_iso(); mid=c.execute("INSERT INTO messages(channel_id,author_id,body,parent_id,created_at) VALUES(?,?,?,?,?)",(ch["id"],u["id"],body,parent,now)).lastrowid
  r=c.execute("SELECT * FROM messages WHERE id=?",(mid,)).fetchone(); obj=msg(c,r)
  emit_event(ch["id"],"message.reply" if parent is not None else "message.created",{"message":obj})
  return web.json_response({"message":obj},status=201)
 async def listing(request):
  u=require_user(request); c=db.get_conn(); ch=c.execute("SELECT * FROM channels WHERE id=?",(request.match_info["id"],)).fetchone(); access(c,ch,u)
  n=parse_limit(request); q="SELECT * FROM messages WHERE channel_id=? AND parent_id IS NULL AND deleted=0"; args=[ch["id"]]
  if "cursor" in request.query: q+=" AND id<?"; args.append(decode_cursor(request.query["cursor"]))
  rows=c.execute(q+" ORDER BY id DESC LIMIT ?",args+[n+1]).fetchall(); more=len(rows)>n; rows=rows[:n]
  return web.json_response({"messages":[msg(c,x) for x in rows],"next_cursor":encode_cursor(rows[-1]["id"]) if more else None})
 async def replies(request):
  u=require_user(request); c=db.get_conn(); p=c.execute("SELECT * FROM messages WHERE id=?",(request.match_info["id"],)).fetchone()
  if not p: raise HTTPError(404,"message not found")
  ch=c.execute("SELECT * FROM channels WHERE id=?",(p["channel_id"],)).fetchone(); access(c,ch,u); n=parse_limit(request)
  q="SELECT * FROM messages WHERE parent_id=? AND deleted=0"; args=[p["id"]]
  if "cursor" in request.query: q+=" AND id>?"; args.append(decode_cursor(request.query["cursor"]))
  rows=c.execute(q+" ORDER BY id ASC LIMIT ?",args+[n+1]).fetchall(); more=len(rows)>n; rows=rows[:n]
  return web.json_response({"replies":[msg(c,x) for x in rows],"next_cursor":encode_cursor(rows[-1]["id"]) if more else None})
 app.router.add_post("/api/channels/{id}/messages",create)
 app.router.add_get("/api/channels/{id}/messages",listing)
 app.router.add_get("/api/messages/{id}/replies",replies)
