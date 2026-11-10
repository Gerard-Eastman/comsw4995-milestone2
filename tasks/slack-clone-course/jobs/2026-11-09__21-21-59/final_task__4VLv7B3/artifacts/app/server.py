import argparse,asyncio,json,secrets,re,hashlib,base64,os
from aiohttp import web,WSMsgType
import db
P=argparse.ArgumentParser();P.add_argument('--port',type=int);P.add_argument('--node-id',type=int); a=P.parse_args()
C=db.connect(); NODE=a.node_id
def js(x, status=200): return web.json_response(x,status=status)
def err(s,m): return web.json_response({'error':m},status=s)
def user(r):
 h=r.headers.get('Authorization',''); t=h[7:] if h.startswith('Bearer ') else r.query.get('token','')
 if t.startswith('Bearer '): t=t[7:]
 x=C.execute('SELECT u.* FROM tokens t JOIN users u ON u.id=t.user_id WHERE t.token=?',(t,)).fetchone()
 return x
async def body(r):
 try:return await r.json()
 except:return {}
def U(x): return {k:x[k] for k in ['id','username','display_name','timezone','avatar_url','status_text','status_emoji']}
def ch(x): return {'id':x['id'],'workspace_id':x['workspace_id'],'name':x['name'],'is_private':bool(x['is_private']),'is_dm':bool(x['is_dm']),'topic':x['topic'] or '','is_archived':bool(x['is_archived']),'created_at':x['created_at']}
def auth(r):
 x=user(r)
 if not x: raise web.HTTPUnauthorized()
 return x
def access(uid,cid,write=False):
 x=C.execute('SELECT c.*,w.owner_id,w.join_mode FROM channels c LEFT JOIN workspaces w ON w.id=c.workspace_id WHERE c.id=?',(cid,)).fetchone()
 if not x:return None,False
 m=C.execute('SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?',(cid,uid)).fetchone()
 wm=C.execute('SELECT role FROM members WHERE workspace_id=? AND user_id=?',(x['workspace_id'],uid)).fetchone()
 return x,bool(m or (wm and not x['is_private']))
def msg(x):
 au=C.execute('SELECT * FROM users WHERE id=?',(x['author_id'],)).fetchone()
 rs=[]
 for z in C.execute('SELECT emoji,count(*),group_concat(user_id) ids FROM reactions WHERE message_id=? GROUP BY emoji',(x['id'],)):
  rs.append({'emoji':z[0],'count':z[1],'user_ids':[int(i) for i in z[2].split(',')]})
 rc=C.execute('SELECT count(*) FROM messages WHERE parent_id=? AND deleted=0',(x['id'],)).fetchone()[0]
 return {'id':x['id'],'channel_id':x['channel_id'],'author_id':x['author_id'],'author':U(au),'body':x['body'],'parent_id':x['parent_id'],'reply_count':rc,'created_at':x['created_at'],'edited_at':x['edited_at'],'files':[{'id':f['id'],'uploader_id':f['uploader_id'],'filename':f['filename'],'content_type':f['content_type'],'size':f['size'],'created_at':f['created_at']} for f in C.execute('SELECT * FROM files WHERE message_id=?',(x['id'],))],'reactions':rs,'mentions':mention_ids(x['body'],x['channel_id'],x['author_id'])}
def emit(cid,kind,data):
 C.execute('BEGIN IMMEDIATE'); n=C.execute('SELECT last_event_id FROM channels WHERE id=?',(cid,)).fetchone()[0]+1
 C.execute('UPDATE channels SET last_event_id=? WHERE id=?',(n,cid)); C.execute('INSERT INTO events(channel_id,event_id,kind,payload) VALUES(?,?,?,?)',(cid,n,kind,json.dumps(data))); C.execute('COMMIT')
async def health(r): return js({'status':'ok','node_id':NODE})
async def register(r):
 b=await body(r); name=b.get('username',''); pw=b.get('password','')
 if not re.fullmatch(r'[A-Za-z0-9_]{1,32}',name) or len(pw)<8:return err(400,'invalid')
 if C.execute('SELECT 1 FROM users WHERE username=?',(name,)).fetchone():return err(409,'duplicate')
 C.execute('INSERT INTO users(username,password,display_name,created_at) VALUES(?,?,?,?)',(name,pw,b.get('display_name') or name,db.now_iso()))
 x=C.execute('SELECT * FROM users WHERE username=?',(name,)).fetchone(); t=secrets.token_urlsafe(24);C.execute('INSERT INTO tokens VALUES(?,?)',(t,x['id']))
 return js({'user':U(x),'token':t},status=201)
async def login(r):
 b=await body(r);x=C.execute('SELECT * FROM users WHERE username=? AND password=?',(b.get('username'),b.get('password'))).fetchone()
 if not x:return err(401,'invalid credentials')
 t=secrets.token_urlsafe(24);C.execute('INSERT INTO tokens VALUES(?,?)',(t,x['id']));return js({'user':U(x),'token':t})
async def me(r): return js({'user':U(auth(r))})
async def workspaces(r):
 u=auth(r); rows=C.execute('SELECT w.* FROM workspaces w JOIN members m ON m.workspace_id=w.id WHERE m.user_id=?',(u['id'],)).fetchall()
 return js({'workspaces':[{'id':x['id'],'slug':x['slug'],'name':x['name'],'owner_id':x['owner_id'],'join_mode':x['join_mode']} for x in rows]})
async def create_ws(r):
 u=auth(r);b=await body(r);slug=b.get('slug','')
 if not re.fullmatch(r'[a-z0-9-]{2,32}',slug):return err(400,'invalid slug')
 if C.execute('SELECT 1 FROM workspaces WHERE slug=?',(slug,)).fetchone():return err(409,'duplicate')
 C.execute('INSERT INTO workspaces(slug,name,owner_id) VALUES(?,?,?)',(slug,b.get('name',''),u['id'])); w=C.execute('SELECT * FROM workspaces WHERE slug=?',(slug,)).fetchone()
 C.execute('INSERT INTO members VALUES(?,?,?)',(w['id'],u['id'],'owner'));C.execute('INSERT INTO channels(workspace_id,name,created_at) VALUES(?,?,?)',(w['id'],'general',db.now_iso())); q=C.execute('SELECT * FROM channels WHERE workspace_id=?',(w['id'],)).fetchone();C.execute('INSERT INTO channel_members VALUES(?,?)',(q['id'],u['id']))
 return js({'workspace':{'id':w['id'],'slug':slug,'name':w['name'],'owner_id':u['id'],'join_mode':'open'},'general_channel':ch(q)},status=201)
async def wsdetail(r):
 u=auth(r);w=C.execute('SELECT * FROM workspaces WHERE slug=?',(r.match_info['slug'],)).fetchone()
 if not w:return err(404,'not found')
 rows=C.execute('SELECT c.* FROM channels c JOIN channel_members cm ON cm.channel_id=c.id WHERE c.workspace_id=? AND cm.user_id=? AND c.is_dm=0',(w['id'],u['id'])).fetchall()
 return js({'workspace':{'id':w['id'],'slug':w['slug'],'name':w['name'],'owner_id':w['owner_id'],'join_mode':w['join_mode']},'channels':[ch(x) for x in rows],'read_state':{}})
async def channels(r):
 u=auth(r);w=C.execute('SELECT * FROM workspaces WHERE slug=?',(r.match_info['slug'],)).fetchone();b=await body(r)
 if not w:return err(404,'not found')
 role=C.execute('SELECT role FROM members WHERE workspace_id=? AND user_id=?',(w['id'],u['id'])).fetchone()
 if role and role['role']=='guest':return err(403,'guest')
 if b.get('is_private') and role and role['role'] not in ('owner','admin'):return err(403,'private')
 if C.execute('SELECT 1 FROM channels WHERE workspace_id=? AND name=?',(w['id'],b.get('name'))).fetchone():return err(409,'duplicate')
 if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*',b.get('name','')) or len(b.get('name',''))>32 or len(b.get('topic',''))>250:return err(400,'invalid name')
 C.execute('INSERT INTO channels(workspace_id,name,is_private,topic,created_at) VALUES(?,?,?,?,?)',(w['id'],b['name'],int(bool(b.get('is_private'))),b.get('topic',''),db.now_iso()));x=C.execute('SELECT * FROM channels WHERE id=last_insert_rowid()').fetchone();C.execute('INSERT OR IGNORE INTO channel_members VALUES(?,?)',(x['id'],u['id']));return js({'channel':ch(x)},status=201)
async def join(r):
 u=auth(r);x=C.execute('SELECT c.*,w.join_mode,w.id wid FROM channels c LEFT JOIN workspaces w ON w.id=c.workspace_id WHERE c.id=?',(r.match_info['id'],)).fetchone()
 if not x:return err(404,'not found')
 if x['is_private']:return err(403,'private')
 role=C.execute('SELECT role FROM members WHERE workspace_id=? AND user_id=?',(x['wid'],u['id'])).fetchone()
 if role and role['role']=='guest':return err(403,'guest')
 if x['join_mode']=='invite_only' and not role:return err(403,'invite only')
 C.execute('INSERT OR IGNORE INTO members VALUES(?,?,?)',(x['wid'],u['id'],'member'));C.execute('INSERT OR IGNORE INTO channel_members VALUES(?,?)',(x['id'],u['id']));return js({'channel':ch(x)})
async def messages(r):
 u=auth(r);cid=int(r.match_info['id']);x,ok=access(u['id'],cid)
 if not x:return err(404,'not found')
 if not ok:return err(403,'forbidden')
 if r.method=='GET':
  rows=C.execute('SELECT * FROM messages WHERE channel_id=? AND parent_id IS NULL AND deleted=0 ORDER BY id DESC',(cid,)).fetchall();return js({'messages':[msg(z) for z in rows],'next_cursor':None})
 b=await body(r); text=b.get('body','')
 if not isinstance(text,str) or not text.strip():return err(400,'empty')
 if text.startswith('/'):
  if text.startswith('//'): b['body']=text[1:]
  else:
   cmd,_,arg=text[1:].partition(' ');arg=arg.strip()
   if cmd=='me':
    if not arg:return err(400,'text')
    b['body']=text
   elif cmd=='shrug': b['body']=(arg+' ' if arg else '')+'¯\\_(ツ)_/¯'
   elif cmd=='topic':
    if len(arg)>250:return err(400,'topic')
    if not ok:return err(403,'forbidden')
    C.execute('UPDATE channels SET topic=? WHERE id=?',(arg,cid));x=C.execute('SELECT * FROM channels WHERE id=?',(cid,)).fetchone();emit(cid,'channel.updated',{'channel':ch(x)});return js({'message':None,'channel':ch(x)},status=201)
   elif cmd=='invite':
    if not arg.startswith('@') or len(arg)<2:return err(400,'username')
    if not ok:return err(403,'forbidden')
    v=C.execute('SELECT * FROM users WHERE username=?',(arg[1:],)).fetchone()
    if not v:return err(404,'user')
    if x['workspace_id'] is None or not C.execute('SELECT 1 FROM members WHERE workspace_id=? AND user_id=?',(x['workspace_id'],v['id'])).fetchone():return err(400,'workspace')
    C.execute('INSERT OR IGNORE INTO channel_members VALUES(?,?)',(cid,v['id']));emit(cid,'member.joined',{'user_id':v['id']});return js({'message':None,'invited_user':U(v)},status=201)
   elif cmd in ('archive','unarchive'):
    if u['id']!=x['owner_id']:return err(403,'forbidden')
    val=1 if cmd=='archive' else 0;C.execute('UPDATE channels SET is_archived=? WHERE id=?',(val,cid));x=C.execute('SELECT * FROM channels WHERE id=?',(cid,)).fetchone();emit(cid,'channel.archived' if val else 'channel.unarchived',{'channel':ch(x)});return js({'message':None,'channel':ch(x)},status=201)
   else:return err(400,'unknown command')
 if x['is_archived']:return err(423,'archived')
 fids=b.get('file_ids',[])
 if not isinstance(fids,list) or any(not isinstance(i,int) for i in fids):return err(400,'file_ids')
 for fid in fids:
  f=C.execute('SELECT * FROM files WHERE id=?',(fid,)).fetchone()
  if not f or f['uploader_id']!=u['id'] or f['message_id'] is not None:return err(400,'file')
 C.execute('INSERT INTO messages(channel_id,author_id,body,parent_id,created_at) VALUES(?,?,?,?,?)',(cid,u['id'],b['body'],b.get('parent_id'),db.now_iso()));z=C.execute('SELECT * FROM messages WHERE id=last_insert_rowid()').fetchone()
 for fid in fids:C.execute('UPDATE files SET message_id=? WHERE id=?',(z['id'],fid))
 o=msg(z);emit(cid,'message.reply' if z['parent_id'] else 'message.created',{'message':o});return js({'message':o},status=201)
async def ws_handler(r):
 u=auth(r); q=web.WebSocketResponse();await q.prepare(r); C.execute('INSERT OR REPLACE INTO ws_presence(user_id) VALUES(?)',(u['id'],)); subs=set();last={};global_last=0
 async def pump():
  nonlocal global_last
  while not q.closed:
   await asyncio.sleep(.15)
   for ge in C.execute('SELECT * FROM global_events WHERE id>? ORDER BY id',(global_last,)):
    await q.send_json(json.loads(ge['payload']));global_last=ge['id']
   for cid in list(subs):
    for e in C.execute('SELECT * FROM events WHERE channel_id=? AND event_id>? ORDER BY event_id',(cid,last.get(cid,0))):
     await q.send_json({'type':e['kind'],'event_id':e['event_id'],'channel_id':cid,**json.loads(e['payload'])});last[cid]=e['event_id']
 try:
  task=asyncio.create_task(pump())
  async for m in q:
   if m.type==WSMsgType.TEXT:
    b=json.loads(m.data);cid=int(b.get('channel_id',0))
    if b.get('type')=='subscribe':
     subs.add(cid);head=C.execute('SELECT last_event_id FROM channels WHERE id=?',(cid,)).fetchone();last[cid]=head[0] if head else 0;await q.send_json({'type':'subscribed','channel_id':cid,'head_event_id':last[cid]})
    elif b.get('type')=='resume':
     subs.add(cid);last[cid]=int(b.get('since_event_id',0));await q.send_json({'type':'resumed','channel_id':cid,'head_event_id':C.execute('SELECT last_event_id FROM channels WHERE id=?',(cid,)).fetchone()[0]})
 finally:
  task.cancel(); C.execute('DELETE FROM ws_presence WHERE user_id=?',(u['id'],))
 return q
async def wsmembers(r):
 u=auth(r); w=C.execute("SELECT * FROM workspaces WHERE slug=?",(r.match_info["slug"],)).fetchone()
 if not w:return err(404,"not found")
 return js({"members":[{"user_id":x["user_id"],"role":x["role"]} for x in C.execute("SELECT user_id,role FROM members WHERE workspace_id=?",(w["id"],))]})
async def patchch(r):
 u=auth(r);x,ok=access(u["id"],int(r.match_info["id"]))
 if not x:return err(404,"not found")
 b=await body(r)
 if len(b.get("topic",""))>250:return err(400,"topic")
 if not ok and u["id"]!=x["owner_id"]:return err(403,"forbidden")
 C.execute("UPDATE channels SET topic=? WHERE id=?",(b.get("topic",""),x["id"]));x=C.execute("SELECT * FROM channels WHERE id=?",(x["id"],)).fetchone();emit(x["id"],"channel.updated",{"channel":ch(x)});return js({"channel":ch(x)})
async def chmembers(r):
 u=auth(r);x,ok=access(u["id"],int(r.match_info["id"]))
 if not x:return err(404,"not found")
 if not ok:return err(403,"forbidden")
 return js({"members":[U(z) for z in C.execute("SELECT u.* FROM users u JOIN channel_members m ON m.user_id=u.id WHERE m.channel_id=?",(x["id"],))]})
async def leave(r):
 u=auth(r);cid=int(r.match_info["id"]);x=C.execute("SELECT * FROM channels WHERE id=?",(cid,)).fetchone()
 if not x:return err(404,"not found")
 C.execute("DELETE FROM channel_members WHERE channel_id=? AND user_id=?",(cid,u["id"]));return js({"channel":ch(x)})
async def replies(r):
 u=auth(r);p=C.execute("SELECT * FROM messages WHERE id=?",(r.match_info["id"],)).fetchone()
 if not p:return err(404,"not found")
 x,ok=access(u["id"],p["channel_id"])
 if not ok:return err(403,"forbidden")
 return js({"replies":[msg(z) for z in C.execute("SELECT * FROM messages WHERE parent_id=? AND deleted=0 ORDER BY id",(p["id"],))],"next_cursor":None})
async def editmsg(r):
 u=auth(r);x=C.execute("SELECT m.*,w.owner_id,c.is_archived FROM messages m JOIN channels c ON c.id=m.channel_id JOIN workspaces w ON w.id=c.workspace_id WHERE m.id=?",(r.match_info["id"],)).fetchone()
 if not x:return err(404,"not found")
 if x["author_id"]!=u["id"]:return err(403,"forbidden")
 if x["deleted"]:return err(409,"deleted")
 if x["is_archived"]:return err(423,"archived")
 b=await body(r)
 if not isinstance(b.get("body"),str) or not b["body"].strip():return err(400,"empty")
 C.execute("UPDATE messages SET body=?,edited_at=? WHERE id=?",(b["body"],db.now_iso(),x["id"]))
 z=C.execute("SELECT * FROM messages WHERE id=?",(x["id"],)).fetchone();o=msg(z);emit(x["channel_id"],"message.updated",{"message":o});return js({"message":o})
async def delmsg(r):
 u=auth(r);x=C.execute("SELECT m.*,w.owner_id FROM messages m JOIN channels c ON c.id=m.channel_id JOIN workspaces w ON w.id=c.workspace_id WHERE m.id=?",(r.match_info["id"],)).fetchone()
 if not x:return err(404,"not found")
 if x["deleted"]:return js({"deleted":True})
 if x["author_id"]!=u["id"] and x["owner_id"]!=u["id"]:return err(403,"forbidden")
 C.execute("UPDATE messages SET deleted=1 WHERE id=?",(x["id"],));emit(x["channel_id"],"message.deleted",{"message_id":x["id"]});return js({"deleted":True})
async def react(r):
 u=auth(r);x=C.execute("SELECT m.*,c.is_archived FROM messages m JOIN channels c ON c.id=m.channel_id WHERE m.id=? AND m.deleted=0",(r.match_info["id"],)).fetchone()
 if not x:return err(404,"not found")
 chx,ok=access(u["id"],x["channel_id"])
 if not ok:return err(403,"forbidden")
 if x["is_archived"]:return err(423,"archived")
 if r.method=="POST":
  b=await body(r);em=b.get("emoji","")
  if not isinstance(em,str) or not em.strip() or len(em)>32:return err(400,"emoji")
  before=C.execute("SELECT 1 FROM reactions WHERE message_id=? AND user_id=? AND emoji=?",(x["id"],u["id"],em)).fetchone()
  if before:
   rs=[{"emoji":z[0],"count":z[1],"user_ids":[int(i) for i in z[2].split(",")]} for z in C.execute("SELECT emoji,count(*),group_concat(user_id) FROM reactions WHERE message_id=? GROUP BY emoji",(x["id"],))]
   return js({"reactions":rs})
  C.execute("INSERT INTO reactions VALUES(?,?,?)",(x["id"],u["id"],em));kind="reaction.added"
 else:
  em=r.match_info["emoji"];before=C.execute("SELECT 1 FROM reactions WHERE message_id=? AND user_id=? AND emoji=?",(x["id"],u["id"],em)).fetchone()
  if not before:
   rs=[{"emoji":z[0],"count":z[1],"user_ids":[int(i) for i in z[2].split(",")]} for z in C.execute("SELECT emoji,count(*),group_concat(user_id) FROM reactions WHERE message_id=? GROUP BY emoji",(x["id"],))]
   return js({"reactions":rs})
  C.execute("DELETE FROM reactions WHERE message_id=? AND user_id=? AND emoji=?",(x["id"],u["id"],em));kind="reaction.removed"
 rs=[{"emoji":z[0],"count":z[1],"user_ids":[int(i) for i in z[2].split(",")]} for z in C.execute("SELECT emoji,count(*),group_concat(user_id) FROM reactions WHERE message_id=? GROUP BY emoji",(x["id"],))]
 emit(x["channel_id"],kind,{"message_id":x["id"],"emoji":em,"user_id":u["id"],"reactions":rs})
 return js({"reactions":rs})
async def pin(r):
 u=auth(r);x=C.execute("SELECT * FROM messages WHERE id=?",(r.match_info["id"],)).fetchone()
 if not x:return err(404,"not found")
 if r.method=="POST":
  C.execute("INSERT OR IGNORE INTO pins VALUES(?,?,?)",(x["id"],u["id"],db.now_iso()));z=C.execute("SELECT * FROM pins WHERE message_id=?",(x["id"],)).fetchone();return js({"pin":{"message_id":x["id"],"pinned_by":z["pinned_by"],"pinned_at":z["pinned_at"]}})
 C.execute("DELETE FROM pins WHERE message_id=?",(x["id"],));return js({"unpinned":True})


async def rolepatch(r):
 u=auth(r);w=C.execute("SELECT * FROM workspaces WHERE slug=?",(r.match_info["slug"],)).fetchone()
 if not w:return err(404,"not found")
 me=C.execute("SELECT role FROM members WHERE workspace_id=? AND user_id=?",(w["id"],u["id"])).fetchone()
 if not me or me["role"] not in ("owner","admin"):return err(403,"forbidden")
 b=await body(r);role=b.get("role")
 if role not in ("admin","member","guest"):return err(400,"invalid role")
 uid=int(r.match_info["user_id"]);target=C.execute("SELECT role FROM members WHERE workspace_id=? AND user_id=?",(w["id"],uid)).fetchone()
 if not target:return err(404,"member")
 if target["role"]=="owner" or (me["role"]=="admin" and target["role"]=="admin"):return err(403,"forbidden")
 C.execute("UPDATE members SET role=? WHERE workspace_id=? AND user_id=?",(role,w["id"],uid));return js({"member":{"user_id":uid,"role":role}})
async def wsedit(r):
 u=auth(r);w=C.execute("SELECT * FROM workspaces WHERE slug=?",(r.match_info["slug"],)).fetchone()
 if not w:return err(404,"not found")
 me=C.execute("SELECT role FROM members WHERE workspace_id=? AND user_id=?",(w["id"],u["id"])).fetchone()
 if not me or me["role"] not in ("owner","admin"):return err(403,"forbidden")
 b=await body(r)
 if b.get("join_mode") not in (None,"open","invite_only"):return err(400,"join_mode")
 C.execute("UPDATE workspaces SET name=COALESCE(?,name),join_mode=COALESCE(?,join_mode) WHERE id=?",(b.get("name"),b.get("join_mode"),w["id"]))
 w=C.execute("SELECT * FROM workspaces WHERE id=?",(w["id"],)).fetchone()
 return js({"workspace":{"id":w["id"],"slug":w["slug"],"name":w["name"],"owner_id":w["owner_id"],"join_mode":w["join_mode"]}})
async def archive(r):
 u=auth(r);x=C.execute("SELECT c.*,w.owner_id FROM channels c LEFT JOIN workspaces w ON w.id=c.workspace_id WHERE c.id=?",(r.match_info["id"],)).fetchone()
 if not x:return err(404,"not found")
 if x["owner_id"]!=u["id"]:return err(403,"forbidden")
 val=1 if r.match_info["action"]=="archive" else 0;C.execute("UPDATE channels SET is_archived=? WHERE id=?",(val,x["id"]));x=C.execute("SELECT * FROM channels WHERE id=?",(x["id"],)).fetchone();emit(x["id"],"channel.archived" if val else "channel.unarchived",{"channel":ch(x)});return js({"channel":ch(x)})
async def pinlist(r):
 u=auth(r);x,ok=access(u["id"],int(r.match_info["id"]))
 if not x:return err(404,"not found")
 if not ok:return err(403,"forbidden")
 rows=C.execute("SELECT p.*,m.* FROM pins p JOIN messages m ON m.id=p.message_id WHERE m.channel_id=? ORDER BY p.message_id DESC",(x["id"],)).fetchall()
 return js({"pins":[{"message":msg(z),"pinned_by":z["pinned_by"],"pinned_at":z["pinned_at"]} for z in rows],"next_cursor":None})


async def search(r):
 u=auth(r);q=r.query.get('q','').strip()
 if not q:return err(400,'q')
 rows=C.execute("SELECT m.* FROM messages m JOIN channels c ON c.id=m.channel_id JOIN channel_members cm ON cm.channel_id=c.id AND cm.user_id=? WHERE m.deleted=0 AND m.body LIKE ? ORDER BY m.id DESC",(u['id'],'%'+q+'%')).fetchall()
 return js({'results':[msg(x) for x in rows],'next_cursor':None})
async def readstate(r):
 u=auth(r);cid=int(r.match_info['id']);x,ok=access(u['id'],cid)
 if not x:return err(404,'not found')
 if not ok:return err(403,'forbidden')
 last=C.execute('SELECT last_event_id FROM channels WHERE id=?',(cid,)).fetchone()[0]
 rows=C.execute('SELECT * FROM messages WHERE channel_id=? AND deleted=0 AND author_id<>?',(cid,u['id'])).fetchall()
 unread=len(rows); mention=sum(1 for z in rows if u['id'] in mention_ids(z['body'],cid,z['author_id']))
 rs={'channel_id':cid,'last_read_event_id':last,'unread_count':unread,'mention_count':mention}
 return js({'read_state':rs})


async def dms(r):
 u=auth(r);b=await body(r);uid=b.get('user_id')
 if not isinstance(uid,int):return err(400,'user_id')
 v=C.execute('SELECT id FROM users WHERE id=?',(uid,)).fetchone()
 if not v:return err(404,'user')
 if uid==u['id']:return err(400,'user_id')
 lo,hi=sorted((u['id'],uid));z=C.execute('SELECT channel_id FROM dm_pairs WHERE user_low=? AND user_high=?',(lo,hi)).fetchone()
 if z:return js({'channel_id':z[0]})
 C.execute('INSERT INTO channels(workspace_id,name,is_private,is_dm,created_at) VALUES(NULL,?,?,1,?)',(f'dm-{lo}-{hi}',1,db.now_iso()))
 cid=C.execute('SELECT last_insert_rowid()').fetchone()[0];C.execute('INSERT INTO dm_pairs VALUES(?,?,?)',(lo,hi,cid))
 C.execute('INSERT INTO channel_members VALUES(?,?)',(cid,lo));C.execute('INSERT INTO channel_members VALUES(?,?)',(cid,hi));return js({'channel_id':cid})
async def upload(r):
 u=auth(r)
 if not r.content_type.startswith('multipart/'):return err(400,'multipart')
 try: rd=await r.multipart()
 except:return err(400,'multipart')
 part=None
 while True:
  try: q=await rd.next()
  except: break
  if q is None:break
  if q.name=='file':part=q;break
 if not part:return err(400,'file')
 data=await part.read()
 if len(data)>10*1024*1024:return err(413,'too large')
 C.execute('INSERT INTO files(uploader_id,filename,content_type,size,data,created_at,message_id) VALUES(?,?,?,?,?,?,NULL)',(u['id'],part.filename or 'file',part.headers.get('Content-Type','application/octet-stream'),len(data),data,db.now_iso()))
 x=C.execute('SELECT * FROM files WHERE id=last_insert_rowid()').fetchone()
 return js({'file':{'id':x['id'],'uploader_id':x['uploader_id'],'filename':x['filename'],'content_type':x['content_type'],'size':x['size'],'created_at':x['created_at']}},status=201)
async def getfile(r):
 auth(r);x=C.execute('SELECT * FROM files WHERE id=?',(r.match_info['id'],)).fetchone()
 if not x:return err(404,'file')
 return js({'file':{'id':x['id'],'uploader_id':x['uploader_id'],'filename':x['filename'],'content_type':x['content_type'],'size':x['size'],'created_at':x['created_at']}})
async def download(r):
 auth(r);x=C.execute('SELECT * FROM files WHERE id=?',(r.match_info['id'],)).fetchone()
 if not x:return err(404,'file')
 return web.Response(body=x['data'],content_type=x['content_type'],headers={'Content-Disposition':'attachment; filename="'+x['filename']+'"'} )


async def getuser(r):
 u=auth(r); ident=r.match_info['id']
 if not ident.isdigit():return err(404,'user')
 x=C.execute('SELECT * FROM users WHERE id=?',(int(ident),)).fetchone()
 if not x:return err(404,'user')
 return js({'user':U(x)})
async def patchprofile(r):
 u=auth(r);b=await body(r)
 allowed={'display_name','timezone','avatar_url','status_text','status_emoji'}
 vals={k:b[k] for k in allowed if k in b}
 for k,v in vals.items():
  if not isinstance(v,str):return err(400,k)
 if 'display_name' in vals and not 1<=len(vals['display_name'])<=80:return err(400,'display_name')
 if 'status_text' in vals and len(vals['status_text'])>100:return err(400,'status_text')
 if 'status_emoji' in vals and len(vals['status_emoji'])>64:return err(400,'status_emoji')
 if 'avatar_url' in vals and len(vals['avatar_url'])>1024:return err(400,'avatar_url')
 if 'timezone' in vals:
  try:
   from zoneinfo import ZoneInfo
   ZoneInfo(vals['timezone'])
  except: return err(400,'timezone')
 if vals:
  C.execute('UPDATE users SET '+','.join(k+'=?' for k in vals)+' WHERE id=?',tuple(vals.values())+(u['id'],))
 x=C.execute('SELECT * FROM users WHERE id=?',(u['id'],)).fetchone()
 C.execute('INSERT INTO global_events(payload) VALUES(?)',(json.dumps({'type':'user.updated','user':U(x)}),))
 return js({'user':U(x)})

def mention_ids(body,cid,author):
 x=C.execute("SELECT * FROM channels WHERE id=?",(cid,)).fetchone()
 if not x or x["workspace_id"] is None:return []
 names=re.findall(r"(?<![A-Za-z0-9_@.])@([A-Za-z0-9_](?:[A-Za-z0-9_-]*[A-Za-z0-9_])?)(?![A-Za-z0-9_@-])(?!\.[A-Za-z0-9])",body)
 ids=[]
 members=[z["user_id"] for z in C.execute("SELECT user_id FROM channel_members WHERE channel_id=?",(cid,))]
 for n in names:
  if n=="channel": got=members
  elif n=="here": got=[v for v in members if C.execute("SELECT 1 FROM ws_presence WHERE user_id=?",(v,)).fetchone()]
  else:
   z=C.execute("SELECT id FROM users WHERE username=?",(n,)).fetchone()
   if z and C.execute("SELECT 1 FROM members WHERE workspace_id=? AND user_id=?",(x["workspace_id"],z["id"])).fetchone():got=[z["id"]]
   else:
    g=C.execute("SELECT id FROM groups_ WHERE workspace_id=? AND handle=?",(x["workspace_id"],n)).fetchone()
    got=[int(v) for v in (json.loads(C.execute("SELECT user_ids FROM groups_ WHERE id=?",(g["id"],)).fetchone()[0]) if g else [])]
    got=[v for v in got if v in members]
  for v in got:
   if v!=author and v not in ids:ids.append(v)
 return ids
def groupjson(g):
 return {"id":g["id"],"handle":g["handle"],"name":g["name"],"member_user_ids":sorted(json.loads(g["user_ids"] or "[]"))}
async def groups(r):
 u=auth(r);w=C.execute("SELECT * FROM workspaces WHERE slug=?",(r.match_info["slug"],)).fetchone()
 if not w:return err(404,"workspace")
 if not C.execute("SELECT 1 FROM members WHERE workspace_id=? AND user_id=?",(w["id"],u["id"])).fetchone():return err(403,"forbidden")
 if r.method=="GET":
  return js({"groups":[groupjson(g) for g in C.execute("SELECT * FROM groups_ WHERE workspace_id=?",(w["id"],))]})
 b=await body(r);h=b.get("handle","");name=b.get("name","");uids=b.get("user_ids",[])
 if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,30}[a-z0-9]",h) or h in ("here","channel") or not isinstance(name,str) or not name or not isinstance(uids,list):return err(400,"invalid")
 for v in uids:
  if not isinstance(v,int) or not C.execute("SELECT 1 FROM members WHERE workspace_id=? AND user_id=?",(w["id"],v)).fetchone():return err(400,"user_ids")
 if C.execute("SELECT 1 FROM groups_ WHERE workspace_id=? AND handle=?",(w["id"],h)).fetchone():return err(409,"duplicate")
 C.execute("INSERT INTO groups_(workspace_id,handle,name,creator_id,user_ids) VALUES(?,?,?,?,?)",(w["id"],h,name,u["id"],json.dumps(uids)))
 return js({"group":groupjson(C.execute("SELECT * FROM groups_ WHERE id=last_insert_rowid()").fetchone())},status=201)
async def grouph(r):
 u=auth(r);w=C.execute("SELECT * FROM workspaces WHERE slug=?",(r.match_info["slug"],)).fetchone()
 if not w:return err(404,"workspace")
 g=C.execute("SELECT * FROM groups_ WHERE workspace_id=? AND handle=?",(w["id"],r.match_info["handle"])).fetchone()
 if r.method=="DELETE":
  if not g:return js({"deleted":True})
  if not C.execute("SELECT 1 FROM members WHERE workspace_id=? AND user_id=?",(w["id"],u["id"])).fetchone():return err(403,"forbidden")
  if u["id"]!=g["creator_id"] and u["id"]!=w["owner_id"]:return err(403,"forbidden")
  C.execute("DELETE FROM groups_ WHERE id=?",(g["id"],));return js({"deleted":True})
 if not g:return err(404,"group")
 if not C.execute("SELECT 1 FROM members WHERE workspace_id=? AND user_id=?",(w["id"],u["id"])).fetchone():return err(403,"forbidden")
 if u["id"]!=g["creator_id"] and u["id"]!=w["owner_id"]:return err(403,"forbidden")
 b=await body(r);name=b.get("name",g["name"]);uids=b.get("user_ids",json.loads(g["user_ids"] or "[]"))
 if not isinstance(name,str) or not name or not isinstance(uids,list):return err(400,"invalid")
 C.execute("UPDATE groups_ SET name=?,user_ids=? WHERE id=?",(name,json.dumps(uids),g["id"]))
 return js({"group":groupjson(C.execute("SELECT * FROM groups_ WHERE id=?",(g["id"],)).fetchone())})


async def invitations(r):
 u=auth(r);w=C.execute("SELECT * FROM workspaces WHERE slug=?",(r.match_info["slug"],)).fetchone()
 if not w:return err(404,"workspace")
 me=C.execute("SELECT role FROM members WHERE workspace_id=? AND user_id=?",(w["id"],u["id"])).fetchone()
 if not me or me["role"] not in ("owner","admin"):return err(403,"forbidden")
 if r.method=="GET":
  rows=C.execute("SELECT * FROM invitations WHERE workspace_id=? AND revoked=0",(w["id"],)).fetchall()
  return js({"invitations":[{"code":z["code"],"max_uses":z["max_uses"],"uses":z["uses"]} for z in rows]})
 b=await body(r);import datetime
 code=secrets.token_urlsafe(10); exp=None
 if b.get("expires_in_seconds"): exp=(datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(seconds=int(b["expires_in_seconds"]))).isoformat()
 target=b.get("invited_user_id")
 if target is None and b.get("invited_username"):
  q=C.execute("SELECT id FROM users WHERE username=?",(b["invited_username"],)).fetchone();target=q["id"] if q else None
 C.execute("INSERT INTO invitations(workspace_id,code,created_by,expires_at,max_uses,target_user_id) VALUES(?,?,?,?,?,?)",(w["id"],code,u["id"],exp,int(b.get("max_uses",1)),target))
 return js({"invitation":{"code":code,"max_uses":int(b.get("max_uses",1))}},status=201)
async def accept_inv(r):
 u=auth(r);z=C.execute("SELECT * FROM invitations WHERE code=? AND revoked=0",(r.match_info["code"],)).fetchone()
 if not z:return err(404,"invitation")
 if z["expires_at"] and z["expires_at"]<db.now_iso():return err(404,"invitation")
 if z["uses"]>=z["max_uses"]:return err(404,"invitation")
 if z["target_user_id"] and z["target_user_id"]!=u["id"]:return err(403,"target")
 C.execute("INSERT OR IGNORE INTO members VALUES(?,?,?)",(z["workspace_id"],u["id"],"member"));C.execute("UPDATE invitations SET uses=uses+1 WHERE id=?",(z["id"],));return js({"workspace_id":z["workspace_id"]})
async def del_inv(r):
 u=auth(r);w=C.execute("SELECT * FROM workspaces WHERE slug=?",(r.match_info["slug"],)).fetchone();me=C.execute("SELECT role FROM members WHERE workspace_id=? AND user_id=?",(w["id"],u["id"])).fetchone() if w else None
 if not me or me["role"] not in ("owner","admin"):return err(403,"forbidden")
 C.execute("UPDATE invitations SET revoked=1 WHERE code=?",(r.match_info["code"],));return js({"deleted":True})

async def init(app):
 app.router.add_get('/api/health',health);app.router.add_route('*','/api/workspaces/{slug}/invitations',invitations);app.router.add_post('/api/invitations/{code}/accept',accept_inv);app.router.add_delete('/api/workspaces/{slug}/invitations/{code}',del_inv);app.router.add_route('*','/api/workspaces/{slug}/groups',groups);app.router.add_route('*','/api/workspaces/{slug}/groups/{handle}',grouph);app.router.add_get('/api/users/{id}',getuser);app.router.add_patch('/api/users/me',patchprofile);app.router.add_post('/api/auth/register',register);app.router.add_post('/api/auth/login',login);app.router.add_get('/api/auth/me',me)
 app.router.add_get('/api/workspaces',workspaces);app.router.add_post('/api/workspaces',create_ws);app.router.add_get('/api/workspaces/{slug}',wsdetail);app.router.add_post('/api/workspaces/{slug}/channels',channels)
 app.router.add_post('/api/channels/{id}/join',join);app.router.add_route('*','/api/channels/{id}/messages',messages);app.router.add_get('/api/ws',ws_handler)
 app.router.add_get('/api/workspaces/{slug}/members',wsmembers);app.router.add_patch('/api/workspaces/{slug}/members/{user_id}',rolepatch);app.router.add_patch('/api/workspaces/{slug}',wsedit);app.router.add_post('/api/channels/{id}/{action}',archive);app.router.add_get('/api/channels/{id}/pins',pinlist);app.router.add_patch('/api/channels/{id}',patchch);app.router.add_get('/api/channels/{id}/members',chmembers);app.router.add_post('/api/channels/{id}/leave',leave)
 app.router.add_get('/api/messages/{id}/replies',replies);app.router.add_patch('/api/messages/{id}',editmsg);app.router.add_delete('/api/messages/{id}',delmsg);app.router.add_post('/api/messages/{id}/reactions',react);app.router.add_delete('/api/messages/{id}/reactions/{emoji}',react);app.router.add_post('/api/messages/{id}/pin',pin);app.router.add_delete('/api/messages/{id}/pin',pin)
 app.router.add_get('/api/search',search);app.router.add_get('/api/channels/{id}/read',readstate);app.router.add_post('/api/channels/{id}/read',readstate);app.router.add_post('/api/dms',dms);app.router.add_post('/api/files',upload);app.router.add_get('/api/files/{id}',getfile);app.router.add_get('/api/files/{id}/download',download)
app=web.Application(client_max_size=20*1024*1024);app.router.add_get('/',lambda r:web.FileResponse('/app/static/index.html'));app.router.add_static('/static/','/app/static');asyncio.get_event_loop().run_until_complete(init(app));web.run_app(app,host='0.0.0.0',port=a.port)
