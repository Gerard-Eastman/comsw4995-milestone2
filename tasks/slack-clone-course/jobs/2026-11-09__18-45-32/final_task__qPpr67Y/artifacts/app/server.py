import argparse,asyncio,json,os,re,secrets,base64,urllib.parse,uuid
from aiohttp import web,WSMsgType
import db
C=db.connect(); NODE=0; sockets=set(); subscriptions={}
class E(Exception):
 def __init__(self,s,m): self.s=s; self.m=m
@web.middleware
async def mw(r,handler):
 try:return await handler(r)
 except E as e:return web.json_response({'error':e.m},status=e.s)
 except Exception as e:return web.json_response({'error':str(e)},status=500)
def userj(x):
 return {'id':x['id'],'username':x['username'],'display_name':x['display_name'],'timezone':x['timezone'],'avatar_url':x['avatar_url'],'status_text':x['status_text'],'status_emoji':x['status_emoji']}
def now(): return db.now_iso()
async def body(r):
 try:x=await r.json(); return x if isinstance(x,dict) else {}
 except:return {}
def auth(r):
 t=r.headers.get('Authorization','')
 if not t.startswith('Bearer '): raise E(401,'unauthorized')
 x=C.execute('select u.* from tokens t join users u on u.id=t.user_id where t.token=?',(t[7:],)).fetchone()
 if not x: raise E(401,'unauthorized')
 return x
def cur(s):
 if not s:return None
 try:
  x=json.loads(base64.urlsafe_b64decode(s+'===')); n=x['k']
  if not isinstance(n,int):raise ValueError()
  return n
 except:raise E(400,'invalid cursor')
def cursor(n):return base64.urlsafe_b64encode(json.dumps({'k':n}).encode()).decode().rstrip('=')
def lim(r):
 try:n=int(r.query.get('limit','50'))
 except:raise E(400,'invalid limit')
 if n<1 or n>200:raise E(400,'invalid limit')
 return n
def uj(id):
 x=C.execute('select * from users where id=?',(id,)).fetchone(); return userj(x) if x else None
def chj(x):
 return {'id':x['id'],'workspace_id':x['workspace_id'],'name':x['name'],'is_private':bool(x['is_private']),'is_dm':bool(x['is_dm']),'topic':x['topic'],'is_archived':bool(x['is_archived']),'created_at':x['created_at']}
def allowed(u,ch):
 if ch['is_dm']: return C.execute('select 1 from channel_members where channel_id=? and user_id=?',(ch['id'],u['id'])).fetchone() is not None
 return C.execute('select 1 from channel_members where channel_id=? and user_id=?',(ch['id'],u['id'])).fetchone() is not None or (not ch['is_private'] and C.execute('select 1 from members where workspace_id=? and user_id=?',(ch['workspace_id'],u['id'])).fetchone() is not None)
def emit(cid,kind,data):
 C.execute('begin immediate'); C.execute('update channels set last_event_id=last_event_id+1 where id=?',(cid,))
 n=C.execute('select last_event_id from channels where id=?',(cid,)).fetchone()[0]
 p={'type':kind,'event_id':n,'channel_id':cid,**data}; C.execute('insert into events(channel_id,event_id,payload) values(?,?,?)',(cid,n,json.dumps(p))); C.execute('commit'); return n
def msgj(x):
 a=uj(x['author_id']); rs=[]
 for q in C.execute('select emoji,count(*) n from reactions where message_id=? group by emoji',(x['id'],)):
  rs.append({'emoji':q['emoji'],'count':q['n'],'user_ids':[z[0] for z in C.execute('select user_id from reactions where message_id=? and emoji=?',(x['id'],q['emoji']))]})
 return {'id':x['id'],'channel_id':x['channel_id'],'author_id':x['author_id'],'author':a,'body':x['body'],'parent_id':x['parent_id'],'reply_count':C.execute('select count(*) from messages where parent_id=? and deleted=0',(x['id'],)).fetchone()[0],'created_at':x['created_at'],'edited_at':x['edited_at'],'files':[{'id':f['id'],'uploader_id':f['uploader_id'],'filename':f['filename'],'content_type':f['content_type'],'size':f['size'],'created_at':f['created_at']} for f in C.execute('select f.* from files f join attachments a on a.file_id=f.id where a.message_id=?',(x['id'],))],'reactions':rs,'mentions':json.loads(x['mentions'] or '[]')}
def wsrow(slug):
 x=C.execute('select * from workspaces where slug=?',(slug,)).fetchone()
 if not x:raise E(404,'not found')
 return x
async def health(r):return web.json_response({'status':'ok','node_id':NODE})
async def register(r):
 b=await body(r); name=b.get('username',''); pw=b.get('password','')
 if not re.fullmatch(r'[A-Za-z0-9_]{1,32}',name) or not isinstance(pw,str) or len(pw)<8:raise E(400,'invalid registration')
 if C.execute('select 1 from users where username=?',(name,)).fetchone():raise E(409,'duplicate username')
 C.execute('insert into users(username,password,display_name) values(?,?,?)',(name,pw,b.get('display_name') or name)); u=C.execute('select * from users where username=?',(name,)).fetchone(); t=secrets.token_urlsafe(24); C.execute('insert into tokens values(?,?)',(t,u['id']))
 return web.json_response({'user':userj(u),'token':t},status=201)
async def login(r):
 b=await body(r); u=C.execute('select * from users where username=? and password=?',(b.get('username'),b.get('password'))).fetchone()
 if not u:raise E(401,'invalid credentials')
 t=secrets.token_urlsafe(24);C.execute('insert into tokens values(?,?)',(t,u['id']));return web.json_response({'user':userj(u),'token':t})
async def me(r):return web.json_response({'user':userj(auth(r))})
async def create_ws(r):
 u=auth(r);b=await body(r); slug=b.get('slug','')
 if not re.fullmatch(r'[a-z0-9-]{2,32}',slug) or not b.get('name'):raise E(400,'invalid workspace')
 if C.execute('select 1 from workspaces where slug=?',(slug,)).fetchone():raise E(409,'duplicate')
 C.execute('insert into workspaces(slug,name,owner_id) values(?,?,?)',(slug,b['name'],u['id'])); w=C.execute('select * from workspaces where slug=?',(slug,)).fetchone()
 C.execute('insert into members values(?,?,?)',(w['id'],u['id'],'owner'));C.execute('insert into channels(workspace_id,name,created_at) values(?,?,?)',(w['id'],'general',now()));q=C.execute('select * from channels where workspace_id=?',(w['id'],)).fetchone();C.execute('insert into channel_members values(?,?)',(q['id'],u['id']))
 return web.json_response({'workspace':dict(w),'general_channel':chj(q)},status=201)
async def workspaces(r):
 u=auth(r); xs=C.execute('select w.* from workspaces w join members m on m.workspace_id=w.id where m.user_id=?',(u['id'],)).fetchall();return web.json_response({'workspaces':[dict(x) for x in xs]})
async def workspace(r):
 u=auth(r);w=wsrow(r.match_info['slug'])
 if not C.execute('select 1 from members where workspace_id=? and user_id=?',(w['id'],u['id'])).fetchone():raise E(403,'forbidden')
 xs=C.execute('select * from channels where workspace_id=? and is_dm=0',(w['id'],)).fetchall();return web.json_response({'workspace':dict(w),'channels':[chj(x) for x in xs],'read_state':[]})
async def create_ch(r):
 u=auth(r);w=wsrow(r.match_info['slug']);b=await body(r);name=b.get('name','')
 role=C.execute('select role from members where workspace_id=? and user_id=?',(w['id'],u['id'])).fetchone()
 if not role:raise E(403,'forbidden')
 if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*',name) or len(name)>32:raise E(400,'invalid channel')
 if C.execute('select 1 from channels where workspace_id=? and name=?',(w['id'],name)).fetchone():raise E(409,'duplicate channel')
 C.execute('insert into channels(workspace_id,name,is_private,topic,created_at) values(?,?,?,?,?)',(w['id'],name,int(bool(b.get('is_private'))),b.get('topic',''),now()));q=C.execute('select * from channels where id=last_insert_rowid()').fetchone();C.execute('insert into channel_members values(?,?)',(q['id'],u['id']));emit(q['id'],'member.joined',{'user_id':u['id']});return web.json_response({'channel':chj(q)},status=201)
async def join(r):
 u=auth(r);q=C.execute('select * from channels where id=?',(r.match_info['id'],)).fetchone()
 if not q:raise E(404,'not found')
 if q['is_private']:raise E(403,'forbidden')
 C.execute('insert or ignore into members values(?,?,?)',(q['workspace_id'],u['id'],'member'));C.execute('insert or ignore into channel_members values(?,?)',(q['id'],u['id']));return web.json_response({'channel':chj(q)})
async def channel(r):
 u=auth(r);q=C.execute('select * from channels where id=?',(r.match_info['id'],)).fetchone()
 if not q:raise E(404,'not found')
 if not allowed(u,q):raise E(403,'forbidden')
 return q
async def messages(r):
 u=auth(r);q=await channel(r); n=lim(r);k=cur(r.query.get('cursor')); sql='select * from messages where channel_id=? and parent_id is null and deleted=0 '+(('and id<? ') if k else '')+'order by id desc limit ?'; xs=C.execute(sql,(q['id'],k,n+1) if k else (q['id'],n+1)).fetchall();return web.json_response({'messages':[msgj(x) for x in xs[:n]],'next_cursor':cursor(xs[n-1]['id']) if len(xs)>n else None})
async def post(r):
 u=auth(r);q=await channel(r)
 b=await body(r);text=b.get('body','')
 if not isinstance(text,str) or not text.strip():raise E(400,'empty body')
 if text.startswith('//'): text=text[1:]
 elif text == '/me': raise E(400,'/me requires text')
 elif text.startswith('/topic'):
  topic=text[6:].strip()
  if len(topic)>250: raise E(400,'topic too long')
  C.execute('update channels set topic=? where id=?',(topic,q['id']))
  q=C.execute('select * from channels where id=?',(q['id'],)).fetchone(); emit(q['id'],'channel.updated',{'channel':chj(q)})
  return web.json_response({'message':None,'channel':chj(q)},status=201)
 elif text.startswith('/invite'):
  m=re.fullmatch(r'/invite\s+@([A-Za-z0-9_]+)',text)
  if not m: raise E(400,'invalid invite')
  v=C.execute('select * from users where username=?',(m.group(1),)).fetchone()
  if not v: raise E(404,'unknown user')
  if not C.execute('select 1 from members where workspace_id=? and user_id=?',(q['workspace_id'],v['id'])).fetchone(): raise E(400,'outside workspace')
  C.execute('insert or ignore into channel_members values(?,?)',(q['id'],v['id']))
  return web.json_response({'message':None,'invited_user':userj(v)},status=201)
 elif text in ('/archive','/unarchive'):
  role=C.execute('select role from members where workspace_id=? and user_id=?',(q['workspace_id'],u['id'])).fetchone()
  if not role or role['role']!='owner': raise E(403,'forbidden')
  val=1 if text=='/archive' else 0
  C.execute('update channels set is_archived=? where id=?',(val,q['id']))
  q=C.execute('select * from channels where id=?',(q['id'],)).fetchone();emit(q['id'],'channel.archived' if val else 'channel.unarchived',{'channel':chj(q)})
  return web.json_response({'message':None,'channel':chj(q)},status=201)
 elif text.startswith('/') and not text.startswith('/shrug') and not text.startswith('/me'):
  raise E(400,'unknown command')
 if q['is_archived']:raise E(423,'archived')
 if text.startswith('/shrug'):text=(text[6:].strip()+' ¯\\_(ツ)_/¯').strip()
 mentions=[]
 for x in re.findall(r'(?<![\w@.])@([A-Za-z0-9_][\w-]*)(?![\w@-])',text):
  ids=[]
  if x=='channel':
   ids=[z[0] for z in C.execute('select user_id from channel_members where channel_id=?',(q['id'],))]
  elif x=='here':
   ids=[z[0] for z in C.execute('select distinct cm.user_id from channel_members cm join ws_presence p on p.user_id=cm.user_id where cm.channel_id=?',(q['id'],))]
  else:
   z=C.execute('select u.id from users u join members m on m.user_id=u.id where u.username=? and m.workspace_id=?',(x,q['workspace_id'])).fetchone()
   if z: ids=[z[0]]
   else:
    g=C.execute('select id from groups where workspace_id=? and handle=?',(q['workspace_id'],x)).fetchone()
    if g: ids=[z[0] for z in C.execute('select gm.user_id from group_members gm join channel_members cm on cm.user_id=gm.user_id where gm.group_id=? and cm.channel_id=?',(g[0],q['id']))]
  for i in ids:
   if i!=u['id'] and i not in mentions: mentions.append(i)
 parent=b.get('parent_id'); fids=b.get('file_ids',[])
 if 'file_ids' in b and (not isinstance(fids,list) or len(set(fids))!=len(fids)): raise E(400,'invalid file_ids')
 for fid in fids:
  f=C.execute('select * from files where id=?',(fid,)).fetchone()
  if not f or f['uploader_id']!=u['id'] or C.execute('select 1 from attachments where file_id=?',(fid,)).fetchone(): raise E(400,'invalid file')
 C.execute('insert into messages(channel_id,author_id,body,parent_id,created_at,mentions) values(?,?,?,?,?,?)',(q['id'],u['id'],text,parent,now(),json.dumps(mentions)));x=C.execute('select * from messages where id=last_insert_rowid()').fetchone()
 for fid in fids: C.execute('insert into attachments values(?,?)',(x['id'],fid))
 emit(q['id'],'message.reply' if parent else 'message.created',{'message':msgj(x)});return web.json_response({'message':msgj(x)},status=201)
async def react(r):
 u=auth(r);x=C.execute('select m.*,c.* from messages m join channels c on c.id=m.channel_id where m.id=? and m.deleted=0',(r.match_info['id'],)).fetchone()
 if not x:raise E(404,'not found')
 if not allowed(u,x):raise E(403,'forbidden')
 if x['is_archived']:raise E(423,'archived')
 b=await body(r);em=b.get('emoji')
 if not isinstance(em,str) or not em or len(em)>32:raise E(400,'invalid emoji')
 old=C.execute('select 1 from reactions where message_id=? and user_id=? and emoji=?',(x['id'],u['id'],em)).fetchone()
 if not old:C.execute('insert into reactions values(?,?,?)',(x['id'],u['id'],em));emit(x['channel_id'],'reaction.added',{'message_id':x['id'],'emoji':em,'user_id':u['id'],'reactions':msgj(x)['reactions']})
 return web.json_response({'reactions':msgj(x)['reactions']})
async def unreact(r):
 u=auth(r);x=C.execute('select m.*,c.* from messages m join channels c on c.id=m.channel_id where m.id=?',(r.match_info['id'],)).fetchone()
 if not x:raise E(404,'not found')
 em=urllib.parse.unquote(r.match_info['emoji']);old=C.execute('select 1 from reactions where message_id=? and user_id=? and emoji=?',(x['id'],u['id'],em)).fetchone()
 C.execute('delete from reactions where message_id=? and user_id=? and emoji=?',(x['id'],u['id'],em))
 if old: emit(x['channel_id'],'reaction.removed',{'message_id':x['id'],'emoji':em,'user_id':u['id'],'reactions':msgj(x)['reactions']})
 return web.json_response({'reactions':msgj(x)['reactions']})
async def replies(r):
 u=auth(r); n=lim(r); p=C.execute('select * from messages where id=?',(r.match_info['id'],)).fetchone()
 if not p:raise E(404,'not found')
 q=await channel(type('R',(),{'match_info':{'id':str(p['channel_id'])},'headers':r.headers,'query':r.query})())
 xs=C.execute('select * from messages where parent_id=? and deleted=0 order by id asc limit ?',(p['id'],n+1)).fetchall()
 return web.json_response({'replies':[msgj(x) for x in xs[:n]],'next_cursor':None})
async def dms(r):
 u=auth(r);b=await body(r); v=b.get('user_id')
 if not isinstance(v,int):raise E(400,'invalid user_id')
 if not C.execute('select id from users where id=?',(v,)).fetchone():raise E(404,'user not found')
 a,b2=sorted((u['id'],v)); z=C.execute('select channel_id from dm_pairs where a=? and b=?',(a,b2)).fetchone()
 if z:return web.json_response({'channel_id':z[0]})
 C.execute('insert into channels(workspace_id,name,is_dm,created_at) values(?,?,1,?)',(None,f'dm-{a}-{b2}',now())); cid=C.execute('select last_insert_rowid()').fetchone()[0]
 C.execute('insert into dm_pairs values(?,?,?)',(a,b2,cid));C.execute('insert into channel_members values(?,?)',(cid,a));C.execute('insert into channel_members values(?,?)',(cid,b2))
 return web.json_response({'channel_id':cid})
async def upload(r):
 u=auth(r)
 if not r.content_type.startswith('multipart/'): raise E(400,'multipart required')
 rd=await r.multipart(); part=None
 async for x in rd:
  if x.name=='file':part=x;break
 if not part:raise E(400,'missing file')
 data=await part.read()
 if len(data)>10*1024*1024:raise E(413,'file too large')
 C.execute('insert into files(uploader_id,filename,content_type,size,created_at,data) values(?,?,?,?,?,?)',(u['id'],part.filename,part.headers.get('Content-Type','application/octet-stream'),len(data),now(),data))
 x=C.execute('select * from files where id=last_insert_rowid()').fetchone()
 return web.json_response({'file':{k:x[k] for k in ('id','uploader_id','filename','content_type','size','created_at')}},status=201)
async def getfile(r):
 u=auth(r);x=C.execute('select * from files where id=?',(r.match_info['id'],)).fetchone()
 if not x:raise E(404,'not found')
 if r.path.endswith('/download'):return web.Response(body=x['data'],content_type=x['content_type'],headers={'Content-Disposition':f'attachment; filename="{x["filename"]}"'})
 return web.json_response({'file':{k:x[k] for k in ('id','uploader_id','filename','content_type','size','created_at')}})
async def profile(r):
 u=auth(r); ident=r.match_info.get('id')
 x=C.execute('select * from users where id=?',(u['id'] if ident is None else ident,)).fetchone()
 if not x:raise E(404,'not found')
 if r.method=='PATCH':
  b=await body(r); vals={}
  for k in ('display_name','timezone','avatar_url','status_text','status_emoji'):
   if k in b:
    if not isinstance(b[k],str):raise E(400,'invalid profile')
    if k=='display_name' and not 1<=len(b[k])<=80:raise E(400,'invalid profile')
    if len(b[k])>{'status_text':100,'status_emoji':64,'avatar_url':1024}.get(k,9999):raise E(400,'invalid profile')
    vals[k]=b[k]
  if 'timezone' in vals:
   try:__import__('zoneinfo').ZoneInfo(vals['timezone'])
   except:raise E(400,'invalid timezone')
  if vals:C.execute('update users set '+','.join(k+'=?' for k in vals)+' where id=?',tuple(vals.values())+(u['id'],))
  x=C.execute('select * from users where id=?',(u['id'],)).fetchone()
  C.execute('insert into broadcasts(payload) values(?)',(json.dumps({'type':'user.updated','user':userj(x)}),))
  return web.json_response({'user':userj(x)})
 return web.json_response({'user':userj(x)})
async def groups(r):
 u=auth(r);w=wsrow(r.match_info['slug'])
 if not C.execute('select 1 from members where workspace_id=? and user_id=?',(w['id'],u['id'])).fetchone():raise E(403,'forbidden')
 if r.method=='GET':
  out=[]
  for g in C.execute('select * from groups where workspace_id=?',(w['id'],)):
   ids=[x[0] for x in C.execute('select user_id from group_members where group_id=? order by user_id',(g['id'],))]
   out.append({'id':g['id'],'handle':g['handle'],'name':g['name'],'member_user_ids':ids})
  return web.json_response({'groups':out})
 b=await body(r);h=b.get('handle','')
 if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,30}[a-z0-9]',h) or h in ('here','channel') or not b.get('name'):raise E(400,'invalid group')
 if C.execute('select 1 from groups where workspace_id=? and handle=?',(w['id'],h)).fetchone():raise E(409,'duplicate')
 ids=b.get('user_ids',[])
 if any(not C.execute('select 1 from members where workspace_id=? and user_id=?',(w['id'],i)).fetchone() for i in ids):raise E(400,'invalid members')
 C.execute('insert into groups(workspace_id,handle,name,created_by) values(?,?,?,?)',(w['id'],h,b['name'],u['id']));gid=C.execute('select last_insert_rowid()').fetchone()[0]
 for i in ids:C.execute('insert into group_members values(?,?)',(gid,i))
 return web.json_response({'group':{'id':gid,'handle':h,'name':b['name'],'member_user_ids':sorted(ids)}},status=201)
async def archive(r):
 u=auth(r); x=C.execute('select * from channels where id=?',(r.match_info['id'],)).fetchone()
 if not x: raise E(404,'not found')
 role=C.execute('select role from members where workspace_id=? and user_id=?',(x['workspace_id'],u['id'])).fetchone()
 if not role or role['role']!='owner': raise E(403,'forbidden')
 val=1 if r.path.endswith('/archive') else 0
 C.execute('update channels set is_archived=? where id=?',(val,x['id']))
 emit(x['id'],'channel.archived' if val else 'channel.unarchived',{'channel':chj(C.execute('select * from channels where id=?',(x['id'],)).fetchone())})
 return web.json_response({'channel':chj(C.execute('select * from channels where id=?',(x['id'],)).fetchone())})
async def group_item(r):
 u=auth(r); w=wsrow(r.match_info['slug']); h=r.match_info['handle']
 g=C.execute('select * from groups where workspace_id=? and handle=?',(w['id'],h)).fetchone()
 if r.method=='DELETE':
  if not g:return web.json_response({'deleted':True})
  role=C.execute('select role from members where workspace_id=? and user_id=?',(w['id'],u['id'])).fetchone()
  if not role or (g['created_by']!=u['id'] and role['role']!='owner'):raise E(403,'forbidden')
  C.execute('delete from group_members where group_id=?',(g['id'],));C.execute('delete from groups where id=?',(g['id'],))
  return web.json_response({'deleted':True})
 if not g:raise E(404,'not found')
 role=C.execute('select role from members where workspace_id=? and user_id=?',(w['id'],u['id'])).fetchone()
 if not role or (g['created_by']!=u['id'] and role['role']!='owner'):raise E(403,'forbidden')
 b=await body(r)
 if 'name' in b:
  if not isinstance(b['name'],str) or not b['name']:raise E(400,'invalid name')
  C.execute('update groups set name=? where id=?',(b['name'],g['id']))
 if 'user_ids' in b:
  ids=b['user_ids']
  if not isinstance(ids,list) or any(not C.execute('select 1 from members where workspace_id=? and user_id=?',(w['id'],i)).fetchone() for i in ids):raise E(400,'invalid members')
  C.execute('delete from group_members where group_id=?',(g['id'],))
  for i in ids:C.execute('insert into group_members values(?,?)',(g['id'],i))
 g=C.execute('select * from groups where id=?',(g['id'],)).fetchone()
 return web.json_response({'group':{'id':g['id'],'handle':g['handle'],'name':g['name'],'member_user_ids':[x[0] for x in C.execute('select user_id from group_members where group_id=? order by user_id',(g['id'],))]}})
async def readstate(r):
 u=auth(r);q=await channel(r)
 x=C.execute('select last_read_event_id from reads where user_id=? and channel_id=?',(u['id'],q['id'])).fetchone()
 last=x[0] if x else 0
 unread=C.execute('select count(*) from messages where channel_id=? and author_id<>? and deleted=0',(q['id'],u['id'])).fetchone()[0]
 mention=C.execute('select count(*) from messages where channel_id=? and author_id<>? and id>? and mentions like ?', (q['id'],u['id'],0,'%'+str(u['id'])+'%')).fetchone()[0]
 return web.json_response({'read_state':{'channel_id':q['id'],'last_read_event_id':last,'unread_count':unread,'mention_count':mention}})
async def ws(r):
 t=r.query.get('token',''); x=C.execute('select user_id from tokens where token=?',(t.replace('Bearer ',''),)).fetchone()
 if not x:raise E(401,'unauthorized')
 w=web.WebSocketResponse();await w.prepare(r); sockets.add(w); subscriptions[id(w)]={}; cid=uuid.uuid4().hex;C.execute('insert into ws_presence values(?,?,?)',(cid,NODE,x[0]))
 try:
  async for m in w:
   if m.type==WSMsgType.TEXT:
    b=json.loads(m.data)
    if b.get('type') in ('subscribe','resume'):
     ch=C.execute('select last_event_id from channels where id=?',(b.get('channel_id'),)).fetchone(); head=ch[0] if ch else 0
     subscriptions[id(w)][b['channel_id']]=True
     if b['type']=='resume':
      since=int(b.get('since_event_id',0))
      for e in C.execute('select payload from events where channel_id=? and event_id>? order by event_id',(b['channel_id'],since)):await w.send_str(e[0])
      await w.send_json({'type':'resumed','channel_id':b['channel_id'],'head_event_id':head})
     else:await w.send_json({'type':'subscribed','channel_id':b['channel_id'],'head_event_id':head})
 finally:
  sockets.discard(w); subscriptions.pop(id(w),None); C.execute('delete from ws_presence where conn_id=?',(cid,))
 return w
async def pump(app):
 seen=C.execute('select coalesce(max(seq),0) from events').fetchone()[0]; bseen=C.execute('select coalesce(max(seq),0) from broadcasts').fetchone()[0]
 while True:
  for e in C.execute('select seq,channel_id,payload from events where seq>? order by seq',(seen,)):
   seen=e['seq']
   for w in list(sockets):
    if not subscriptions.get(id(w),{}).get(e['channel_id'],False): continue
    try: await w.send_str(e['payload'])
    except: pass
  for e in C.execute('select seq,payload from broadcasts where seq>? order by seq',(bseen,)):
   bseen=e['seq']
   for w in list(sockets):
    try:await w.send_str(e['payload'])
    except:pass
  await asyncio.sleep(.05)
async def start(app):app['pump']=asyncio.create_task(pump(app))
async def stop(app):app['pump'].cancel()
def main():
 global NODE
 p=argparse.ArgumentParser();p.add_argument('--port',type=int);p.add_argument('--node-id',type=int);a=p.parse_args();NODE=a.node_id;db.init_db()
 app=web.Application(middlewares=[mw],client_max_size=20*1024*1024)
 app.router.add_get('/api/health',health);app.router.add_post('/api/auth/register',register);app.router.add_post('/api/auth/login',login);app.router.add_get('/api/auth/me',me)
 app.router.add_get('/api/users/{id}',profile);app.router.add_patch('/api/users/me',profile)
 app.router.add_post('/api/workspaces',create_ws);app.router.add_get('/api/workspaces',workspaces);app.router.add_get('/api/workspaces/{slug}',workspace);app.router.add_post('/api/workspaces/{slug}/channels',create_ch)
 app.router.add_get('/api/workspaces/{slug}/groups',groups);app.router.add_post('/api/workspaces/{slug}/groups',groups);app.router.add_patch('/api/workspaces/{slug}/groups/{handle}',group_item);app.router.add_delete('/api/workspaces/{slug}/groups/{handle}',group_item)
 app.router.add_post('/api/channels/{id}/join',join);app.router.add_post('/api/channels/{id}/archive',archive);app.router.add_post('/api/channels/{id}/unarchive',archive);app.router.add_get('/api/channels/{id}/messages',messages);app.router.add_get('/api/channels/{id}/read',readstate);app.router.add_post('/api/channels/{id}/messages',post)
 app.router.add_get('/api/messages/{id}/replies',replies);app.router.add_post('/api/messages/{id}/reactions',react);app.router.add_delete('/api/messages/{id}/reactions/{emoji}',unreact)
 app.router.add_post('/api/dms',dms);app.router.add_post('/api/files',upload);app.router.add_get('/api/files/{id}',getfile);app.router.add_get('/api/files/{id}/download',getfile);app.router.add_get('/api/ws',ws)
 app.on_startup.append(start);app.on_cleanup.append(stop);web.run_app(app,host='0.0.0.0',port=a.port)
if __name__=='__main__':main()
