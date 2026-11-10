import re,json
from aiohttp import web
import db
from common import *

def msg(r):
 c=db.get(); a=c.execute("SELECT * FROM users WHERE id=?",(r["author_id"],)).fetchone()
 n=json.loads(r["mentions"] or "[]")
 rc=c.execute("SELECT COUNT(*) FROM messages WHERE parent_id=? AND deleted=0",(r["id"],)).fetchone()[0]
 rr=[]
 for x in c.execute("SELECT emoji,COUNT(*) n FROM reactions WHERE message_id=? GROUP BY emoji",(r["id"],)):
  ids=[z[0] for z in c.execute("SELECT user_id FROM reactions WHERE message_id=? AND emoji=?",(r["id"],x["emoji"]))]
  rr.append({"emoji":x["emoji"],"count":x["n"],"user_ids":ids})
 return {"id":r["id"],"channel_id":r["channel_id"],"author_id":r["author_id"],"author":user_to_json(a),"body":r["body"],"parent_id":r["parent_id"],"reply_count":rc,"created_at":r["created_at"],"edited_at":r["edited_at"],"files":[],"reactions":rr,"mentions":n}

def setup(app):
 async def post(request):
  u=require_user(request); c=db.get(); ch=c.execute("SELECT * FROM channels WHERE id=?",(request.match_info["id"],)).fetchone()
  if not ch: raise HTTPError(404,"channel not found")
  if ch["is_archived"]: raise HTTPError(423,"channel archived")
  if not c.execute("SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?",(ch["id"],u["id"])).fetchone():
   raise HTTPError(403,"not a channel member")
  b=await read_json(request); body=b.get("body")
  if not isinstance(body,str) or not body.strip(): raise HTTPError(400,"message body required")
  parent=b.get("parent_id"); p=None
  if parent is not None:
   p=c.execute("SELECT id FROM messages WHERE id=? AND channel_id=? AND deleted=0",(parent,ch["id"])).fetchone()
   if not p: raise HTTPError(404,"parent not found")
  ids=[]
  for name in re.findall(r"(?<![\w@])@([A-Za-z0-9_]+)",body):
   x=c.execute("SELECT u.id FROM users u JOIN workspace_members m ON m.user_id=u.id WHERE u.username=? AND m.workspace_id=?",(name,ch["workspace_id"])).fetchone()
   if x and x[0]!=u["id"] and x[0] not in ids: ids.append(x[0])
  if "@channel" in body:
   for x in c.execute("SELECT user_id FROM channel_members WHERE channel_id=? AND user_id!=?",(ch["id"],u["id"])):
    if x[0] not in ids: ids.append(x[0])
  now=db.now_iso(); c.execute("INSERT INTO messages(channel_id,author_id,body,parent_id,created_at,mentions) VALUES(?,?,?,?,?,?)",(ch["id"],u["id"],body,parent,now,json.dumps(ids)))
  mid=c.execute("SELECT last_insert_rowid()").fetchone()[0]; r=c.execute("SELECT * FROM messages WHERE id=?",(mid,)).fetchone()
  emit_event(ch["id"],"message.reply" if parent else "message.created",{"message":msg(r)})
  return web.json_response({"message":msg(r)},status=201)
 async def listing(request):
  u=require_user(request); c=db.get(); ch=c.execute("SELECT * FROM channels WHERE id=?",(request.match_info["id"],)).fetchone()
  if not ch: raise HTTPError(404,"channel not found")
  if not c.execute("SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?",(ch["id"],u["id"])).fetchone(): raise HTTPError(403,"not a member")
  n=parse_limit(request); q="SELECT * FROM messages WHERE channel_id=? AND parent_id IS NULL AND deleted=0"; args=[ch["id"]]
  if request.query.get("cursor"): q+=" AND id<?"; args.append(decode_cursor(request.query["cursor"]))
  q+=" ORDER BY id DESC LIMIT ?"; args.append(n+1); rs=c.execute(q,args).fetchall(); more=len(rs)>n; rs=rs[:n]
  return web.json_response({"messages":[msg(x) for x in rs],"next_cursor":encode_cursor(rs[-1]["id"]) if more else None})
 async def replies(request):
  u=require_user(request); c=db.get(); p=c.execute("SELECT * FROM messages WHERE id=?",(request.match_info["id"],)).fetchone()
  if not p: raise HTTPError(404,"message not found")
  n=parse_limit(request); q="SELECT * FROM messages WHERE parent_id=? AND deleted=0"; args=[p["id"]]
  if request.query.get("cursor"): q+=" AND id>?"; args.append(decode_cursor(request.query["cursor"]))
  q+=" ORDER BY id ASC LIMIT ?"; args.append(n+1); rs=c.execute(q,args).fetchall(); more=len(rs)>n; rs=rs[:n]
  return web.json_response({"replies":[msg(x) for x in rs],"next_cursor":encode_cursor(rs[-1]["id"]) if more else None})
 async def read(request):
  u=require_user(request); cid=int(request.match_info["id"]); r=db.get().execute("SELECT last_event_id FROM read_state WHERE user_id=? AND channel_id=?",(u["id"],cid)).fetchone()
  last=r[0] if r else 0
  return web.json_response({"read_state":{"channel_id":cid,"last_read_event_id":last,"unread_count":0,"mention_count":0}})
 app.router.add_post("/api/channels/{id}/messages",post); app.router.add_get("/api/channels/{id}/messages",listing)
 app.router.add_get("/api/messages/{id}/replies",replies); app.router.add_get("/api/channels/{id}/read",read)
