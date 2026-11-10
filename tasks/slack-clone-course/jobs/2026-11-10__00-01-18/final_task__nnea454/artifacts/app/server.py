import argparse,asyncio,json,secrets,re,uuid
from aiohttp import web,WSMsgType
import db
from common import HTTPError,error_middleware,read_json,require_user,user_to_json,parse_limit,encode_cursor,decode_cursor,emit_event
db.init_db(); C=db._conn
NODE=0; sockets=set()
def channel(r):
 return {'id':r['id'],'workspace_id':r['workspace_id'],'name':r['name'],'is_private':bool(r['is_private']),'is_dm':bool(r['is_dm']),'topic':r['topic'] or '','is_archived':bool(r['is_archived']),'created_at':r['created_at']}
def msg(r):
 u=C.execute('SELECT * FROM users WHERE id=?',(r['author_id'],)).fetchone()
 reacts=[]
 for x in C.execute('SELECT emoji,COUNT(*) n FROM reactions WHERE message_id=? GROUP BY emoji',(r['id'],)):
  ids=[z[0] for z in C.execute('SELECT user_id FROM reactions WHERE message_id=? AND emoji=?',(r['id'],x['emoji']))]
  reacts.append({'emoji':x['emoji'],'count':x['n'],'user_ids':ids})
 replies=C.execute('SELECT COUNT(*) FROM messages WHERE parent_id=? AND deleted=0',(r['id'],)).fetchone()[0]
 return {'id':r['id'],'channel_id':r['channel_id'],'author_id':r['author_id'],'author':user_to_json(u),'body':r['body'],'parent_id':r['parent_id'],'reply_count':replies,'created_at':r['created_at'],'edited_at':r['edited_at'],'files':[],'reactions':reacts,'mentions':[]}
def member(uid,cid,write=False):
 r=C.execute('SELECT c.*,w.owner_id FROM channels c JOIN workspaces w ON w.id=c.workspace_id WHERE c.id=?',(cid,)).fetchone()
 if not r: raise HTTPError(404,'channel not found')
 m=C.execute('SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?',(cid,uid)).fetchone()
 wm=C.execute('SELECT 1 FROM workspace_members WHERE workspace_id=? AND user_id=?',(r['workspace_id'],uid)).fetchone()
 if not m and not (not r['is_private'] and wm): raise HTTPError(403,'not a channel member')
 if write and r['is_archived']: raise HTTPError(423,'channel is archived')
 return r
async def auth_register(q):
 if not re.fullmatch(r'[A-Za-z0-9_]{1,32}',q.get('username','')) or len(q.get('password',''))<8: raise HTTPError(400,'invalid registration')
 try:
  C.execute('INSERT INTO users(username,password,display_name) VALUES(?,?,?)',(q['username'],q['password'],q.get('display_name') or q['username']))
 except: raise HTTPError(409,'username exists')
 u=C.execute('SELECT * FROM users WHERE id=last_insert_rowid()').fetchone(); t=secrets.token_urlsafe(24)
 C.execute('INSERT INTO tokens VALUES(?,?)',(t,u['id'],)); return web.json_response({'user':user_to_json(u),'token':t},status=201)
async def register(r): return await auth_register(await read_json(r))
async def login(r):
 q=await read_json(r); u=C.execute('SELECT * FROM users WHERE username=? AND password=?',(q.get('username'),q.get('password'))).fetchone()
 if not u: raise HTTPError(401,'invalid credentials')
 t=secrets.token_urlsafe(24); C.execute('INSERT INTO tokens VALUES(?,?)',(t,u['id']))
 return web.json_response({'user':user_to_json(u),'token':t})
async def me(r): return web.json_response({'user':user_to_json(require_user(r))})
async def workspaces(r):
 u=require_user(r); rows=C.execute('SELECT w.* FROM workspaces w JOIN workspace_members m ON m.workspace_id=w.id WHERE m.user_id=?',(u['id'],)).fetchall()
 return web.json_response({'workspaces':[dict(x) for x in rows]})
async def workspace_create(r):
 u=require_user(r); q=await read_json(r)
 if not re.fullmatch(r'[a-z0-9-]{2,32}',q.get('slug','')): raise HTTPError(400,'invalid slug')
 try: C.execute('INSERT INTO workspaces(slug,name,owner_id) VALUES(?,?,?)',(q['slug'],q.get('name',''),u['id']))
 except: raise HTTPError(409,'workspace exists')
 w=C.execute('SELECT * FROM workspaces WHERE id=last_insert_rowid()').fetchone(); now=db.now_iso()
 C.execute('INSERT INTO workspace_members VALUES(?,?,?)',(w['id'],u['id'],'owner'))
 C.execute('INSERT INTO channels(workspace_id,name,created_at) VALUES(?,?,?)',(w['id'],'general',now))
 ch=C.execute('SELECT * FROM channels WHERE id=last_insert_rowid()').fetchone(); C.execute('INSERT INTO channel_members VALUES(?,?)',(ch['id'],u['id']))
 return web.json_response({'workspace':dict(w),'general_channel':channel(ch)},status=201)
async def workspace(r):
 u=require_user(r); w=C.execute('SELECT * FROM workspaces WHERE slug=?',(r.match_info['slug'],)).fetchone()
 if not w: raise HTTPError(404,'workspace not found')
 if not C.execute('SELECT 1 FROM workspace_members WHERE workspace_id=? AND user_id=?',(w['id'],u['id'])).fetchone(): raise HTTPError(403,'not a member')
 cs=C.execute('SELECT * FROM channels WHERE workspace_id=? AND is_dm=0 AND is_archived=0',(w['id'],)).fetchall()
 return web.json_response({'workspace':dict(w),'channels':[channel(x) for x in cs],'read_state':[]})
async def channels_create(r):
 u=require_user(r); w=C.execute('SELECT * FROM workspaces WHERE slug=?',(r.match_info['slug'],)).fetchone()
 if not w: raise HTTPError(404,'workspace not found')
 if not C.execute('SELECT 1 FROM workspace_members WHERE workspace_id=? AND user_id=?',(w['id'],u['id'])).fetchone(): raise HTTPError(403,'not a member')
 q=await read_json(r); name=q.get('name','')
 if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*',name) or len(name)>32: raise HTTPError(400,'invalid channel name')
 if C.execute('SELECT 1 FROM channels WHERE workspace_id=? AND name=?',(w['id'],name)).fetchone(): raise HTTPError(409,'channel exists')
 C.execute('INSERT INTO channels(workspace_id,name,is_private,topic,created_at) VALUES(?,?,?,?,?)',(w['id'],name,int(bool(q.get('is_private'))),q.get('topic',''),db.now_iso()))
 ch=C.execute('SELECT * FROM channels WHERE id=last_insert_rowid()').fetchone(); C.execute('INSERT INTO channel_members VALUES(?,?)',(ch['id'],u['id']))
 return web.json_response({'channel':channel(ch)},status=201)
async def channel_patch(r):
 u=require_user(r); cid=int(r.match_info['id'])
 ch=C.execute('SELECT c.*,w.owner_id FROM channels c JOIN workspaces w ON w.id=c.workspace_id WHERE c.id=?',(cid,)).fetchone()
 if not ch: raise HTTPError(404,'channel not found')
 if not (C.execute('SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?',(cid,u['id'])).fetchone() or ch['owner_id']==u['id']): raise HTTPError(403,'forbidden')
 q=await read_json(r)
 if not isinstance(q.get('topic'),str) or len(q['topic'])>250: raise HTTPError(400,'invalid topic')
 C.execute('UPDATE channels SET topic=? WHERE id=?',(q['topic'],cid))
 out=C.execute('SELECT * FROM channels WHERE id=?',(cid,)).fetchone()
 emit_event(cid,'channel.updated',{'channel':channel(out)})
 return web.json_response({'channel':channel(out)})
async def archive(r):
 u=require_user(r); cid=int(r.match_info['id'])
 ch=C.execute('SELECT c.*,w.owner_id FROM channels c JOIN workspaces w ON w.id=c.workspace_id WHERE c.id=?',(cid,)).fetchone()
 if not ch: raise HTTPError(404,'channel not found')
 if ch['owner_id']!=u['id']: raise HTTPError(403,'forbidden')
 C.execute('UPDATE channels SET is_archived=1 WHERE id=?',(cid,))
 return web.json_response({'channel':channel(C.execute('SELECT * FROM channels WHERE id=?',(cid,)).fetchone())})
async def unarchive(r):
 u=require_user(r); cid=int(r.match_info['id'])
 ch=C.execute('SELECT c.*,w.owner_id FROM channels c JOIN workspaces w ON w.id=c.workspace_id WHERE c.id=?',(cid,)).fetchone()
 if not ch: raise HTTPError(404,'channel not found')
 if ch['owner_id']!=u['id']: raise HTTPError(403,'forbidden')
 C.execute('UPDATE channels SET is_archived=0 WHERE id=?',(cid,))
 return web.json_response({'channel':channel(C.execute('SELECT * FROM channels WHERE id=?',(cid,)).fetchone())})
async def join(r):
 u=require_user(r); ch=C.execute('SELECT c.*,w.join_mode FROM channels c JOIN workspaces w ON w.id=c.workspace_id WHERE c.id=?',(int(r.match_info['id']),)).fetchone()
 if not ch: raise HTTPError(404,'channel not found')
 if ch['is_private']: raise HTTPError(403,'private channel')
 C.execute('INSERT OR IGNORE INTO workspace_members VALUES(?,?,?)',(ch['workspace_id'],u['id'],'member')); C.execute('INSERT OR IGNORE INTO channel_members VALUES(?,?)',(ch['id'],u['id']))
 return web.json_response({'channel':channel(ch)})
async def post(r):
 u=require_user(r); cid=int(r.match_info['id']); ch=member(u['id'],cid,True); q=await read_json(r); body=q.get('body','')
 if not isinstance(body,str) or not body.strip(): raise HTTPError(400,'empty body')
 p=q.get('parent_id'); now=db.now_iso(); C.execute('INSERT INTO messages(channel_id,author_id,body,parent_id,created_at) VALUES(?,?,?,?,?)',(cid,u['id'],body,p,now))
 m=C.execute('SELECT * FROM messages WHERE id=last_insert_rowid()').fetchone(); mo=msg(m); emit_event(cid,'message.reply' if p else 'message.created',{'message':mo})
 return web.json_response({'message':mo},status=201)
async def messages(r):
 u=require_user(r); cid=int(r.match_info['id']); member(u['id'],cid)
 lim=parse_limit(r); k=decode_cursor(r.query['cursor']) if r.query.get('cursor') else 10**18
 rows=C.execute('SELECT * FROM messages WHERE channel_id=? AND parent_id IS NULL AND deleted=0 AND id<? ORDER BY id DESC LIMIT ?',(cid,k,lim+1)).fetchall()
 nxt=encode_cursor(rows[lim-1]['id']) if len(rows)>lim else None
 return web.json_response({'messages':[msg(x) for x in rows[:lim]],'next_cursor':nxt})
async def replies(r):
 u=require_user(r); mid=int(r.match_info['id']); p=C.execute('SELECT * FROM messages WHERE id=? AND deleted=0',(mid,)).fetchone()
 if not p: raise HTTPError(404,'message not found')
 member(u['id'],p['channel_id']); rows=C.execute('SELECT * FROM messages WHERE parent_id=? AND deleted=0 ORDER BY id',(mid,)).fetchall()
 return web.json_response({'replies':[msg(x) for x in rows],'next_cursor':None})
async def edit(r):
 u=require_user(r); mid=int(r.match_info['id']); m=C.execute('SELECT * FROM messages WHERE id=?',(mid,)).fetchone()
 if not m: raise HTTPError(404,'message not found')
 if m['author_id']!=u['id']: raise HTTPError(403,'forbidden')
 if m['deleted']: raise HTTPError(409,'message deleted')
 ch=member(u['id'],m['channel_id'],True); q=await read_json(r)
 if not isinstance(q.get('body'),str) or not q['body'].strip(): raise HTTPError(400,'empty body')
 C.execute('UPDATE messages SET body=?,edited_at=? WHERE id=?',(q['body'],db.now_iso(),mid))
 mo=msg(C.execute('SELECT * FROM messages WHERE id=?',(mid,)).fetchone()); emit_event(m['channel_id'],'message.updated',{'message':mo})
 return web.json_response({'message':mo})
async def delete(r):
 u=require_user(r); mid=int(r.match_info['id']); m=C.execute('SELECT * FROM messages WHERE id=?',(mid,)).fetchone()
 if not m: raise HTTPError(404,'message not found')
 w=C.execute('SELECT w.owner_id FROM channels c JOIN workspaces w ON w.id=c.workspace_id WHERE c.id=?',(m['channel_id'],)).fetchone()
 if m['author_id']!=u['id'] and w['owner_id']!=u['id']: raise HTTPError(403,'forbidden')
 if not m['deleted']:
  C.execute('UPDATE messages SET deleted=1 WHERE id=?',(mid,)); emit_event(m['channel_id'],'message.deleted',{'message_id':mid})
 return web.json_response({'deleted':True})
async def react(r):
 u=require_user(r); mid=int(r.match_info['id']); m=C.execute('SELECT * FROM messages WHERE id=? AND deleted=0',(mid,)).fetchone()
 if not m: raise HTTPError(404,'message not found')
 member(u['id'],m['channel_id']); q=await read_json(r); e=q.get('emoji','')
 if not e: raise HTTPError(400,'emoji required')
 C.execute('INSERT OR IGNORE INTO reactions VALUES(?,?,?)',(mid,u['id'],e))
 mo=msg(C.execute('SELECT * FROM messages WHERE id=?',(mid,)).fetchone()); emit_event(m['channel_id'],'reaction.added',{'message':mo})
 return web.json_response({'reactions':mo['reactions']})
async def unreact(r):
 u=require_user(r); mid=int(r.match_info['id']); m=C.execute('SELECT * FROM messages WHERE id=? AND deleted=0',(mid,)).fetchone()
 if not m: raise HTTPError(404,'message not found')
 C.execute('DELETE FROM reactions WHERE message_id=? AND user_id=? AND emoji=?',(mid,u['id'],r.match_info['emoji']))
 return web.json_response({'reactions':msg(C.execute('SELECT * FROM messages WHERE id=?',(mid,)).fetchone())['reactions']})
async def read_state(r):
 u=require_user(r); cid=int(r.match_info['id']); member(u['id'],cid)
 x=C.execute('SELECT last_read_event_id FROM read_state WHERE user_id=? AND channel_id=?',(u['id'],cid)).fetchone()
 last=x[0] if x else 0
 return web.json_response({'read_state':{'channel_id':cid,'last_read_event_id':last,'unread_count':0,'mention_count':0}})
async def ws_handler(r):
 tok=r.query.get('token','')
 if tok:
  u=C.execute('SELECT u.* FROM tokens t JOIN users u ON u.id=t.user_id WHERE t.token=?',(tok,)).fetchone()
  if not u: raise HTTPError(401,'invalid token')
 else: require_user(r)
 ws=web.WebSocketResponse(); await ws.prepare(r); subscribed=set(); seen={}
 async def send_events():
  while not ws.closed:
   await asyncio.sleep(.05)
   for cid in list(subscribed):
    k=seen.get(cid,0); rows=C.execute('SELECT event_id,payload FROM events WHERE channel_id=? AND event_id>? ORDER BY event_id',(cid,k)).fetchall()
    for x in rows:
     await ws.send_str(x['payload']); seen[cid]=x['event_id']
 try:
  task=asyncio.create_task(send_events())
  async for m in ws:
   if m.type==WSMsgType.TEXT:
    q=json.loads(m.data); typ=q.get('type'); cid=int(q.get('channel_id',0))
    if typ=='subscribe':
     subscribed.add(cid); head=C.execute('SELECT last_event_id FROM channels WHERE id=?',(cid,)).fetchone()
     seen[cid]=head[0] if head else 0; await ws.send_json({'type':'subscribed','channel_id':cid,'head_event_id':seen[cid]})
    elif typ=='resume':
     subscribed.add(cid); since=int(q.get('since_event_id',0))
     rows=C.execute('SELECT payload FROM events WHERE channel_id=? AND event_id>? ORDER BY event_id',(cid,since)).fetchall()
     for x in rows: await ws.send_str(x['payload'])
     head=C.execute('SELECT last_event_id FROM channels WHERE id=?',(cid,)).fetchone()[0]; seen[cid]=head
     await ws.send_json({'type':'resumed','channel_id':cid,'head_event_id':head})
 finally:
  task.cancel()
 return ws
async def health(r): return web.json_response({'status':'ok','node_id':NODE})
def setup():
 app=web.Application(middlewares=[error_middleware],client_max_size=20*1024*1024)
 app.router.add_get('/api/health',health); app.router.add_post('/api/auth/register',register); app.router.add_post('/api/auth/login',login); app.router.add_get('/api/auth/me',me)
 app.router.add_get('/api/workspaces',workspaces); app.router.add_post('/api/workspaces',workspace_create); app.router.add_get('/api/workspaces/{slug}',workspace)
 app.router.add_post('/api/workspaces/{slug}/channels',channels_create); app.router.add_post('/api/channels/{id}/join',join); app.router.add_patch('/api/channels/{id}',channel_patch); app.router.add_post('/api/channels/{id}/archive',archive); app.router.add_post('/api/channels/{id}/unarchive',unarchive)
 app.router.add_post('/api/channels/{id}/messages',post); app.router.add_get('/api/channels/{id}/messages',messages); app.router.add_get('/api/messages/{id}/replies',replies)
 app.router.add_patch('/api/messages/{id}',edit); app.router.add_delete('/api/messages/{id}',delete)
 app.router.add_post('/api/messages/{id}/reactions',react); app.router.add_delete('/api/messages/{id}/reactions/{emoji}',unreact)
 app.router.add_get('/api/channels/{id}/read',read_state); app.router.add_get('/api/ws',ws_handler)
 app.router.add_get('/',lambda r:web.FileResponse('/app/static/index.html',headers={'Content-Type':'text/html'}))
 app.router.add_static('/static/','/app/static')
 return app
if __name__=='__main__':
 p=argparse.ArgumentParser(); p.add_argument('--port',type=int); p.add_argument('--node-id',type=int,default=0); a=p.parse_args(); NODE=a.node_id
 web.run_app(setup(),host='0.0.0.0',port=a.port)
