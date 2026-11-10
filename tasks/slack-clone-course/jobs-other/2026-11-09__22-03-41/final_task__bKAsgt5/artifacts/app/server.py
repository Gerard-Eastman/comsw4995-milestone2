import argparse,json,re,secrets,sys,asyncio
from aiohttp import web
import db
def user(r): 
 t=r.headers.get('Authorization','').removeprefix('Bearer ').strip() or r.query.get('token','')
 if not t:return None
 c=db.connect(); x=c.execute('select u.* from users u join tokens t on t.user_id=u.id where t.token=?',(t,)).fetchone(); c.close(); return x
def uj(x): return {'id':x['id'],'username':x['username'],'display_name':x['display_name'] or x['username'],'timezone':'UTC','avatar_url':'','status_text':'','status_emoji':''}
async def health(r): return web.json_response({'status':'ok','node_id':r.app['node']})
async def register(r):
 b=await r.json()
 if not re.fullmatch(r'[A-Za-z0-9_]{1,32}',b.get('username','')) or len(b.get('password',''))<8:return web.json_response({'error':'invalid'},status=400)
 c=db.connect()
 try:c.execute('insert into users(username,password,display_name) values(?,?,?)',(b['username'],b['password'],b.get('display_name') or b['username']))
 except: c.close(); return web.json_response({'error':'duplicate'},status=409)
 x=c.execute('select * from users where username=?',(b['username'],)).fetchone(); t=secrets.token_urlsafe(24); c.execute('insert into tokens values(?,?)',(t,x['id'])); c.close(); return web.json_response({'user':uj(x),'token':t},status=201)
async def login(r):
 b=await r.json(); c=db.connect(); x=c.execute('select * from users where username=? and password=?',(b.get('username'),b.get('password'))).fetchone()
 if not x:c.close(); return web.json_response({'error':'unauthorized'},status=401)
 t=secrets.token_urlsafe(24); c.execute('insert into tokens values(?,?)',(t,x['id'])); c.close(); return web.json_response({'user':uj(x),'token':t})
async def me(r):
 x=user(r)
 return web.json_response({'user':uj(x)}) if x else web.json_response({'error':'unauthorized'},status=401)

async def create_workspace(r):
 x=user(r)
 if not x:return web.json_response({'error':'unauthorized'},status=401)
 b=await r.json(); c=db.connect()
 try:c.execute('insert into workspaces(slug,name,owner_id) values(?,?,?)',(b['slug'],b['name'],x['id']))
 except: c.close(); return web.json_response({'error':'duplicate'},status=409)
 w=c.execute('select * from workspaces where slug=?',(b['slug'],)).fetchone()
 c.execute('insert into channels(workspace_id,name) values(?,?)',(w['id'],'general'))
 ch=c.execute('select * from channels where workspace_id=?',(w['id'],)).fetchone()
 c.execute('insert into members(user_id,workspace_id,channel_id,role) values(?,?,?,?)',(x['id'],w['id'],ch['id'],'owner')); c.close()
 return web.json_response({'workspace':{'id':w['id'],'slug':w['slug'],'name':w['name'],'owner_id':x['id'],'join_mode':'open'},'general_channel':{'id':ch['id'],'workspace_id':ch['workspace_id'],'name':'general','is_private':False,'is_dm':False,'topic':'','is_archived':False}},status=201)
async def list_workspaces(r):
 x=user(r)
 if not x:return web.json_response({'error':'unauthorized'},status=401)
 c=db.connect(); a=c.execute('select * from workspaces where owner_id=?',(x['id'],)).fetchall(); c.close()
 return web.json_response({'workspaces':[{'id':z['id'],'slug':z['slug'],'name':z['name'],'owner_id':z['owner_id'],'join_mode':'open'} for z in a]})


async def post_message(r):
 x=user(r)
 if not x:return web.json_response({'error':'unauthorized'},status=401)
 b=await r.json()
 if not b.get('body'):return web.json_response({'error':'empty'},status=400)
 c=db.connect();c.execute('insert into messages(channel_id,author_id,body,created_at) values(?,?,?,?)',(int(r.match_info['id']),x['id'],b['body'],db.now_iso())); m=c.execute('select * from messages order by id desc limit 1').fetchone(); c.execute('insert into events(channel_id,seq,kind,payload,created_at) values(?,?,?,?,?)',(int(r.match_info['id']),c.execute('select coalesce(max(seq),0)+1 from events where channel_id=?',(int(r.match_info['id']),)).fetchone()[0],'message.created',json.dumps({'message':{'id':m['id'],'channel_id':m['channel_id'],'author_id':m['author_id'],'body':m['body'],'parent_id':None,'reply_count':0,'created_at':m['created_at'],'edited_at':None,'files':[],'reactions':[],'mentions':[]}}),db.now_iso()));c.close()
 return web.json_response({'message':{'id':m['id'],'channel_id':m['channel_id'],'author_id':m['author_id'],'author':uj(x),'body':m['body'],'parent_id':None,'reply_count':0,'created_at':m['created_at'],'edited_at':None,'files':[],'reactions':[],'mentions':[]}},status=201)

async def workspace_detail(r):
 x=user(r)
 if not x:return web.json_response({'error':'unauthorized'},status=401)
 c=db.connect(); w=c.execute('select * from workspaces where slug=?',(r.match_info['slug'],)).fetchone()
 if not w:c.close();return web.Response(status=404)
 a=c.execute('select * from channels where workspace_id=?',(w['id'],)).fetchall();c.close()
 return web.json_response({'workspace':{'id':w['id'],'slug':w['slug'],'name':w['name'],'owner_id':w['owner_id'],'join_mode':'open'},'channels':[{'id':z['id'],'workspace_id':z['workspace_id'],'name':z['name'],'is_private':bool(z['is_private']),'is_dm':False,'topic':z['topic'],'is_archived':False} for z in a],'read_state':{}})
async def make_channel(r):
 x=user(r)
 if not x:return web.json_response({'error':'unauthorized'},status=401)
 b=await r.json();c=db.connect();w=c.execute('select * from workspaces where slug=?',(r.match_info['slug'],)).fetchone()
 if not w:c.close();return web.Response(status=404)
 if c.execute('select 1 from channels where workspace_id=? and name=?',(w['id'],b['name'])).fetchone(): c.close(); return web.json_response({'error':'duplicate'},status=409)
 try:c.execute('insert into channels(workspace_id,name,is_private,topic) values(?,?,?,?)',(w['id'],b['name'],int(b.get('is_private',False)),b.get('topic','')))
 except:c.close();return web.json_response({'error':'duplicate'},status=409)
 z=c.execute('select * from channels where workspace_id=? and name=?',(w['id'],b['name'])).fetchone();c.execute('insert into members values(?,?,?,?)',(x['id'],w['id'],z['id'],'member'));c.close()
 return web.json_response({'channel':{'id':z['id'],'workspace_id':z['workspace_id'],'name':z['name'],'is_private':bool(z['is_private']),'is_dm':False,'topic':z['topic'],'is_archived':False}},status=201)
async def join_channel(r):
 x=user(r)
 if not x:return web.json_response({'error':'unauthorized'},status=401)
 c=db.connect();z=c.execute('select * from channels where id=?',(r.match_info['id'],)).fetchone()
 if not z:c.close();return web.Response(status=404)
 c.execute('insert into members(user_id,workspace_id,channel_id,role) values(?,?,?,?)',(x['id'],z['workspace_id'],z['id'],'member'));c.close()
 return web.json_response({'channel':{'id':z['id'],'workspace_id':z['workspace_id'],'name':z['name'],'is_private':bool(z['is_private']),'is_dm':False,'topic':z['topic'],'is_archived':False}})
async def list_messages(r):
 x=user(r)
 if not x:return web.json_response({'error':'unauthorized'},status=401)
 c=db.connect();a=c.execute('select * from messages where channel_id=? order by id desc',(r.match_info['id'],)).fetchall();c.close()
 return web.json_response({'messages':[{'id':z['id'],'channel_id':z['channel_id'],'author_id':z['author_id'],'body':z['body'],'parent_id':None,'reply_count':0,'created_at':z['created_at'],'edited_at':None,'files':[],'reactions':[],'mentions':[]} for z in a],'next_cursor':None})

async def ws(r):
 if not user(r): return web.Response(status=401)
 w=web.WebSocketResponse(); await w.prepare(r); await w.send_json({'type':'ready'}); last=0; qchan=0 
 async def pump():
  nonlocal last
  while not w.closed:
   c=db.connect(); rows=c.execute('select * from events where channel_id=? and seq>? order by seq',(qchan,last)).fetchall(); c.close()
   for e in rows:
    last=e['seq']; await w.send_json({'type':e['kind'],'event_id':e['seq'],'channel_id':e['channel_id'],**json.loads(e['payload'])})
   await asyncio.sleep(.05)
 task=asyncio.create_task(pump())
 async for m in w:
  if m.type==web.WSMsgType.TEXT:
   try:
    q=json.loads(m.data)
    if q.get('type')=='subscribe':
     qchan=int(q.get('channel_id')); c=db.connect(); head=c.execute('select coalesce(max(seq),0) from events where channel_id=?',(qchan,)).fetchone()[0]; c.close(); last=head; await w.send_json({'type':'subscribed','channel_id':qchan,'head_event_id':head})
    elif q.get('type')=='resume': await w.send_json({'type':'resumed','channel_id':q.get('channel_id'),'head_event_id':0})
   except: pass
 task.cancel(); return w
async def root(r): return web.Response(text='<!doctype html><html><body><h1>Huddle</h1></body></html>',content_type='text/html')
def main():
 p=argparse.ArgumentParser();p.add_argument('--port',type=int);p.add_argument('--node-id',type=int);a=p.parse_args(); db.init_db()
 app=web.Application(client_max_size=20*1024*1024);app['node']=a.node_id
 app.router.add_get('/api/health',health);app.router.add_post('/api/auth/register',register);app.router.add_post('/api/auth/login',login);app.router.add_get('/api/auth/me',me);app.router.add_get('/api/ws',ws);app.router.add_post('/api/workspaces',create_workspace);app.router.add_get('/api/workspaces',list_workspaces);app.router.add_get('/api/workspaces/{slug}',workspace_detail);app.router.add_post('/api/workspaces/{slug}/channels',make_channel);app.router.add_post('/api/channels/{id}/join',join_channel);app.router.add_get('/api/channels/{id}/messages',list_messages);app.router.add_post('/api/channels/{id}/messages',post_message);app.router.add_get('/',root)
 web.run_app(app,host='0.0.0.0',port=a.port)
if __name__=='__main__':main()
