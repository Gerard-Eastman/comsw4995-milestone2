import argparse,asyncio,json,uuid
from aiohttp import web,WSMsgType
import db
from common import *
def app_create(node):
 a=web.Application(middlewares=[error_middleware],client_max_size=20*1024*1024); c=db.connect(); a['db']=c; a['node']=node; a['subs']={}; return a
def workspace(r):
 return {'id':r['id'],'slug':r['slug'],'name':r['name'],'owner_id':r['owner_id'],'join_mode':r['join_mode']}
async def health(q): return web.json_response({'status':'ok','node_id':q.app['node']})
async def register(q):
 c=q.app['db']; b=await read_json(q); u=b.get('username',''); p=b.get('password','')
 import re
 if not re.fullmatch(r'[A-Za-z0-9_]{1,32}',u) or len(p)<8: raise HTTPError(400,'invalid registration')
 if c.execute('SELECT 1 FROM users WHERE username=?',(u,)).fetchone(): raise HTTPError(409,'username already exists')
 c.execute('INSERT INTO users(username,password,display_name) VALUES(?,?,?)',(u,p,b.get('display_name') or u)); uid=c.execute('SELECT last_insert_rowid()').fetchone()[0]; tok=uuid.uuid4().hex+uuid.uuid4().hex
 c.execute('INSERT INTO tokens VALUES(?,?)',(tok,uid)); return web.json_response({'user':user_to_json(c.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone()),'token':tok},status=201)
async def login(q):
 c=q.app['db']; b=await read_json(q); r=c.execute('SELECT * FROM users WHERE username=? AND password=?',(b.get('username'),b.get('password'))).fetchone()
 if not r: raise HTTPError(401,'invalid credentials')
 tok=uuid.uuid4().hex+uuid.uuid4().hex;c.execute('INSERT INTO tokens VALUES(?,?)',(tok,r['id']))
 return web.json_response({'user':user_to_json(r),'token':tok})
async def me(q): return web.json_response({'user':user_to_json(require_user(q))})
async def create_ws(q):
 u=require_user(q);c=q.app['db'];b=await read_json(q); slug=b.get('slug','');name=b.get('name','')
 import re
 if not re.fullmatch(r'[a-z0-9-]{2,32}',slug) or not name: raise HTTPError(400,'invalid workspace')
 if c.execute('SELECT 1 FROM workspaces WHERE slug=?',(slug,)).fetchone(): raise HTTPError(409,'duplicate slug')
 now=db.now_iso();c.execute('INSERT INTO workspaces(slug,name,owner_id) VALUES(?,?,?)',(slug,name,u['id']));wid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
 c.execute('INSERT INTO members VALUES(?,?,?)',(wid,u['id'],'owner'));c.execute('INSERT INTO channels(workspace_id,name,created_at) VALUES(?,?,?)',(wid,'general',now));cid=c.execute('SELECT last_insert_rowid()').fetchone()[0];c.execute('INSERT INTO channel_members VALUES(?,?)',(cid,u['id']))
 return web.json_response({'workspace':workspace(c.execute('SELECT * FROM workspaces WHERE id=?',(wid,)).fetchone()),'general_channel':channel_json(c.execute('SELECT * FROM channels WHERE id=?',(cid,)).fetchone())},status=201)
async def list_ws(q):
 u=require_user(q);c=q.app['db'];rs=c.execute('SELECT w.* FROM workspaces w JOIN members m ON m.workspace_id=w.id WHERE m.user_id=?',(u['id'],)).fetchall()
 return web.json_response({'workspaces':[workspace(x) for x in rs]})
async def get_ws(q):
 u=require_user(q);c=q.app['db'];r=c.execute('SELECT * FROM workspaces WHERE slug=?',(q.match_info['slug'],)).fetchone()
 if not r: raise HTTPError(404,'workspace not found')
 if not c.execute('SELECT 1 FROM members WHERE workspace_id=? AND user_id=?',(r['id'],u['id'])).fetchone(): raise HTTPError(403,'not a member')
 cs=c.execute('SELECT * FROM channels WHERE workspace_id=? AND is_dm=0 AND is_archived=0',(r['id'],)).fetchall()
 return web.json_response({'workspace':workspace(r),'channels':[channel_json(x) for x in cs],'read_state':[]})
async def create_channel(q):
 u=require_user(q);c=q.app['db'];w=c.execute('SELECT * FROM workspaces WHERE slug=?',(q.match_info['slug'],)).fetchone()
 if not w: raise HTTPError(404,'workspace not found')
 if not c.execute('SELECT 1 FROM members WHERE workspace_id=? AND user_id=?',(w['id'],u['id'])).fetchone(): raise HTTPError(403,'not a member')
 b=await read_json(q);n=b.get('name',''); import re
 if not re.fullmatch(r'[a-z0-9]+(-[a-z0-9]+)*',n) or len(n)>32: raise HTTPError(400,'invalid channel')
 if c.execute('SELECT 1 FROM channels WHERE workspace_id=? AND name=?',(w['id'],n)).fetchone(): raise HTTPError(409,'duplicate channel')
 now=db.now_iso(); c.execute('INSERT INTO channels(workspace_id,name,is_private,topic,created_at) VALUES(?,?,?,?,?)',(w['id'],n,int(bool(b.get('is_private'))),b.get('topic',''),now));cid=c.execute('SELECT last_insert_rowid()').fetchone()[0];c.execute('INSERT INTO channel_members VALUES(?,?)',(cid,u['id']))
 return web.json_response({'channel':channel_json(c.execute('SELECT * FROM channels WHERE id=?',(cid,)).fetchone())},status=201)
def chan(c,i):
 try:r=c.execute('SELECT * FROM channels WHERE id=?',(int(i),)).fetchone()
 except: r=None
 if not r: raise HTTPError(404,'channel not found')
 return r
async def join(q):
 u=require_user(q);c=q.app['db'];r=chan(c,q.match_info['id']);w=c.execute('SELECT * FROM workspaces WHERE id=?',(r['workspace_id'],)).fetchone()
 if r['is_private']: raise HTTPError(403,'private channel')
 if not c.execute('SELECT 1 FROM members WHERE workspace_id=? AND user_id=?',(w['id'],u['id'])).fetchone(): c.execute('INSERT INTO members VALUES(?,?,?)',(w['id'],u['id'],'member'))
 c.execute('INSERT OR IGNORE INTO channel_members VALUES(?,?)',(r['id'],u['id'])); return web.json_response({'channel':channel_json(r)})
async def post(q):
 u=require_user(q);c=q.app['db'];r=chan(c,q.match_info['id']);b=await read_json(q)
 if r['is_archived']: raise HTTPError(423,'channel archived')
 if not c.execute('SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?',(r['id'],u['id'])).fetchone(): raise HTTPError(403,'not a channel member')
 body=b.get('body','')
 if not isinstance(body,str) or not body.strip(): raise HTTPError(400,'empty message')
 now=db.now_iso();parent=b.get('parent_id');c.execute('INSERT INTO messages(channel_id,author_id,body,parent_id,created_at) VALUES(?,?,?,?,?)',(r['id'],u['id'],body,parent,now));mid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
 m=message_json(c,c.execute('SELECT * FROM messages WHERE id=?',(mid,)).fetchone());kind='message.reply' if parent else 'message.created';emit_event(c,r['id'],kind,{'message':m,'parent_id':parent})
 return web.json_response({'message':m},status=201)
async def messages(q):
 u=require_user(q);c=q.app['db'];r=chan(c,q.match_info['id']);limit=parse_limit(q);cur=decode_cursor(q.query['cursor']) if q.query.get('cursor') else None
 z='SELECT * FROM messages WHERE channel_id=? AND parent_id IS NULL AND deleted=0 '+(('AND id<?') if cur else '')+' ORDER BY id DESC LIMIT ?'; args=[r['id']]+(([cur] if cur else []))+[limit+1];rs=c.execute(z,args).fetchall(); nxt=encode_cursor(rs[limit-1]['id']) if len(rs)>limit else None
 return web.json_response({'messages':[message_json(c,x) for x in rs[:limit]],'next_cursor':nxt})
async def ws(q):
 require_user(q); c=q.app['db']; sock=web.WebSocketResponse();await sock.prepare(q); subs=set(); last= c.execute('SELECT COALESCE(MAX(seq),0) FROM events').fetchone()[0]
 try:
  async def pump():
   nonlocal last
   while not sock.closed:
    rows=c.execute('SELECT seq,payload FROM events WHERE seq>? ORDER BY seq',(last,)).fetchall()
    for x in rows:
     last=x['seq'];p=json.loads(x['payload'])
     if p['channel_id'] in subs: await sock.send_json(p)
    await asyncio.sleep(.05)
  task=asyncio.create_task(pump())
  async for msg in sock:
   if msg.type==WSMsgType.TEXT:
    b=json.loads(msg.data)
    if b.get('type')=='subscribe':
     cid=int(b['channel_id']);subs.add(cid);h=c.execute('SELECT last_event_id FROM channels WHERE id=?',(cid,)).fetchone()[0];await sock.send_json({'type':'subscribed','channel_id':cid,'head_event_id':h})
    elif b.get('type')=='resume':
     cid=int(b['channel_id']);n=int(b.get('since_event_id',0))
     for x in c.execute('SELECT payload FROM events WHERE channel_id=? AND event_id>? ORDER BY event_id',(cid,n)): await sock.send_json(json.loads(x['payload']))
     h=c.execute('SELECT last_event_id FROM channels WHERE id=?',(cid,)).fetchone()[0];subs.add(cid);await sock.send_json({'type':'resumed','channel_id':cid,'head_event_id':h})
 finally:
  if 'task' in locals(): task.cancel()
 return sock
def main():
 p=argparse.ArgumentParser();p.add_argument('--port',type=int);p.add_argument('--node-id',type=int);x=p.parse_args();a=app_create(x.node_id)
 a.router.add_get('/api/health',health);a.router.add_post('/api/auth/register',register);a.router.add_post('/api/auth/login',login);a.router.add_get('/api/auth/me',me)
 a.router.add_post('/api/workspaces',create_ws);a.router.add_get('/api/workspaces',list_ws);a.router.add_get('/api/workspaces/{slug}',get_ws);a.router.add_post('/api/workspaces/{slug}/channels',create_channel)
 a.router.add_post('/api/channels/{id}/join',join);a.router.add_post('/api/channels/{id}/messages',post);a.router.add_get('/api/channels/{id}/messages',messages);a.router.add_get('/api/ws',ws)
 web.run_app(a,host='0.0.0.0',port=x.port)
if __name__=='__main__': main()
