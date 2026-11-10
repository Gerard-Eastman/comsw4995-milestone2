import argparse, asyncio, json, os, re, secrets, base64, uuid, hashlib, sqlite3
from aiohttp import web, WSMsgType
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import db
C=db.connect(); NODE=0; SOCKS={}
class E(Exception):
 def __init__(self,s,m): self.s=s; self.m=m
@web.middleware
async def mw(r,handler):
 try:return await handler(r)
 except E as e:return web.json_response({'error':e.m},status=e.s)
 except Exception as e:
  return web.json_response({'error':str(e)},status=500)
def now(): return db.now_iso()
async def body(r):
 try:
  x=await r.json(); return x if isinstance(x,dict) else {}
 except:return {}
def uid(r):
 a=r.headers.get('Authorization','')
 token=a[7:] if a.startswith('Bearer ') else r.query.get('token','')
 if not token: raise E(401,'authentication required')
 q=C.execute('SELECT user_id FROM tokens WHERE token=?',(token,)).fetchone()
 if not q: raise E(401,'invalid token')
 return q[0]
def user(i):
 q=C.execute('SELECT * FROM users WHERE id=?',(i,)).fetchone()
 if not q: raise E(404,'user not found')
 return {'id':q['id'],'username':q['username'],'display_name':q['display_name'],'timezone':q['timezone'],'avatar_url':q['avatar_url'],'status_text':q['status_text'],'status_emoji':q['status_emoji']}
def lim(r):
 try:n=int(r.query.get('limit','50'))
 except:raise E(400,'invalid limit')
 if not 1<=n<=200:raise E(400,'invalid limit')
 return n
def cursor(s):
 if not s:return None
 try:
  x=json.loads(base64.urlsafe_b64decode(s+'===')); n=x['k']
  if not isinstance(n,int):raise ValueError()
  return n
 except:raise E(400,'invalid cursor')
def enc(n):return base64.urlsafe_b64encode(json.dumps({'k':n}).encode()).decode().rstrip('=')
def chrow(i):
 try:q=C.execute('SELECT * FROM channels WHERE id=?',(int(i),)).fetchone()
 except: q=None
 if not q:raise E(404,'channel not found')
 return q
def chjson(q):return {'id':q['id'],'workspace_id':q['workspace_id'],'name':q['name'],'is_private':bool(q['is_private']),'is_dm':bool(q['is_dm']),'topic':q['topic'] or '','is_archived':bool(q['is_archived']),'created_at':q['created_at']}
def role(cid,u):
 return C.execute('SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?',(cid,u)).fetchone()
def allowed(q,u):
 if role(q['id'],u):return True
 return bool(q['workspace_id'] and not q['is_private'] and C.execute('SELECT 1 FROM workspace_members WHERE workspace_id=? AND user_id=?',(q['workspace_id'],u)).fetchone())
def workspace(slug):
 q=C.execute('SELECT * FROM workspaces WHERE slug=?',(slug,)).fetchone()
 if not q:raise E(404,'workspace not found')
 return q
def emit(cid,kind,data):
 C.execute('BEGIN IMMEDIATE')
 try:
  C.execute('UPDATE channels SET last_event_id=last_event_id+1 WHERE id=?',(cid,))
  n=C.execute('SELECT last_event_id FROM channels WHERE id=?',(cid,)).fetchone()[0]
  p={'type':kind,'event_id':n,'channel_id':cid,**data}
  C.execute('INSERT INTO events(channel_id,event_id,payload) VALUES(?,?,?)',(cid,n,json.dumps(p)))
  C.execute('COMMIT');return n
 except:C.execute('ROLLBACK');raise
def msgjson(q):
 fs=[dict(x) for x in C.execute('SELECT id,uploader_id,filename,content_type,size,created_at FROM files WHERE message_id=? ORDER BY id',(q['id'],))]
 rr=[]
 for x in C.execute('SELECT emoji,user_id FROM reactions WHERE message_id=? ORDER BY created_at',(q['id'],)):
  z=next((a for a in rr if a['emoji']==x['emoji']),None)
  if not z:z={'emoji':x['emoji'],'count':0,'user_ids':[]};rr.append(z)
  z['user_ids'].append(x['user_id']);z['count']+=1
 return {'id':q['id'],'channel_id':q['channel_id'],'author_id':q['author_id'],'author':user(q['author_id']),'body':q['body'],'parent_id':q['parent_id'],'reply_count':C.execute('SELECT count(*) FROM messages WHERE parent_id=? AND deleted=0',(q['id'],)).fetchone()[0],'created_at':q['created_at'],'edited_at':q['edited_at'],'files':fs,'reactions':rr,'mentions':json.loads(q['mentions'] or '[]')}
def mentions(text,q,author):
 out=[]
 members=[x[0] for x in C.execute('SELECT user_id FROM channel_members WHERE channel_id=?',(q['id'],))]
 ws=[x[0] for x in C.execute('SELECT user_id FROM workspace_members WHERE workspace_id=?',(q['workspace_id'],))] if q['workspace_id'] else members
 for n in re.findall(r'(?<![A-Za-z0-9_@.])@([A-Za-z0-9_](?:[A-Za-z0-9_-]*[A-Za-z0-9_])?)(?![A-Za-z0-9_@-])',text):
  if n=='channel': xs=members
  elif n=='here':xs=[x[0] for x in C.execute('SELECT DISTINCT user_id FROM ws_presence') if x[0] in members]
  else:
   x=C.execute('SELECT id FROM users WHERE username=?',(n,)).fetchone(); xs=[x[0]] if x and x[0] in ws else []
   if not xs and q['workspace_id']:
    g=C.execute('SELECT id FROM groups WHERE workspace_id=? AND handle=?',(q['workspace_id'],n)).fetchone()
    xs=[x[0] for x in C.execute('SELECT user_id FROM group_members WHERE group_id=?',(g[0],)) if x[0] in members] if g else []
  for x in xs:
   if x!=author and x not in out:out.append(x)
 return out
async def authreg(r):
 b=await body(r); n=b.get('username');p=b.get('password')
 if not isinstance(n,str) or not re.fullmatch(r'[A-Za-z0-9_]{1,32}',n) or not isinstance(p,str) or len(p)<8:raise E(400,'invalid registration')
 if C.execute('SELECT 1 FROM users WHERE username=?',(n,)).fetchone():raise E(409,'username exists')
 C.execute('INSERT INTO users(username,password,display_name) VALUES(?,?,?)',(n,p,b.get('display_name') or n));i=C.execute('SELECT last_insert_rowid()').fetchone()[0];t=secrets.token_urlsafe(24);C.execute('INSERT INTO tokens VALUES(?,?)',(t,i));return web.json_response({'user':user(i),'token':t},status=201)
async def login(r):
 b=await body(r);q=C.execute('SELECT * FROM users WHERE username=? AND password=?',(b.get('username'),b.get('password'))).fetchone()
 if not q:raise E(401,'invalid credentials')
 t=secrets.token_urlsafe(24);C.execute('INSERT INTO tokens VALUES(?,?)',(t,q['id']));return web.json_response({'user':user(q['id']),'token':t})
async def me(r):return web.json_response({'user':user(uid(r))})
async def health(r):return web.json_response({'status':'ok','node_id':NODE})
async def wss(r):
 u=uid(r); ws=web.WebSocketResponse();await ws.prepare(r); key=uuid.uuid4().hex;SOCKS[key]=(ws,u,set());C.execute('INSERT OR REPLACE INTO ws_presence VALUES(?,?,?)',(key,NODE,u))
 try:
  async for m in ws:
   if m.type!=WSMsgType.TEXT:continue
   x=json.loads(m.data);q=chrow(x.get('channel_id')); 
   if not allowed(q,u):raise E(403,'forbidden')
   if x.get('type')=='subscribe':SOCKS[key][2].add(q['id']);await ws.send_json({'type':'subscribed','channel_id':q['id'],'head_event_id':q['last_event_id']})
   elif x.get('type')=='resume':
    for z in C.execute('SELECT payload FROM events WHERE channel_id=? AND event_id>? ORDER BY event_id',(q['id'],x.get('since_event_id',0))):await ws.send_str(z[0])
    await ws.send_json({'type':'resumed','channel_id':q['id'],'head_event_id':C.execute('SELECT last_event_id FROM channels WHERE id=?',(q['id'],)).fetchone()[0]})
 except:pass
 finally:C.execute('DELETE FROM ws_presence WHERE conn_id=?',(key,));SOCKS.pop(key,None)
 return ws
async def workspaces(r):
 u=uid(r);a=[]
 for q in C.execute('SELECT w.* FROM workspaces w JOIN workspace_members m ON m.workspace_id=w.id WHERE m.user_id=?',(u,)):a.append({'id':q['id'],'slug':q['slug'],'name':q['name'],'owner_id':q['owner_id'],'join_mode':q['join_mode']})
 return web.json_response({'workspaces':a})
async def wcreate(r):
 u=uid(r);b=await body(r);s=b.get('slug');n=b.get('name')
 if not isinstance(s,str) or not re.fullmatch(r'[a-z0-9-]{2,32}',s) or not n:raise E(400,'invalid workspace')
 if C.execute('SELECT 1 FROM workspaces WHERE slug=?',(s,)).fetchone():raise E(409,'duplicate')
 C.execute('INSERT INTO workspaces(slug,name,owner_id) VALUES(?,?,?)',(s,n,u));wid=C.execute('SELECT last_insert_rowid()').fetchone()[0];C.execute('INSERT INTO workspace_members VALUES(?,?,?)',(wid,u,'owner'));C.execute('INSERT INTO channels(workspace_id,name,created_at) VALUES(?,?,?)',(wid,'general',now()));cid=C.execute('SELECT last_insert_rowid()').fetchone()[0];C.execute('INSERT INTO channel_members VALUES(?,?)',(cid,u));q=C.execute('SELECT * FROM channels WHERE id=?',(cid,)).fetchone();w=C.execute('SELECT * FROM workspaces WHERE id=?',(wid,)).fetchone();return web.json_response({'workspace':{'id':wid,'slug':s,'name':n,'owner_id':u,'join_mode':'open'},'general_channel':chjson(q)},status=201)
async def wdetail(r):
 u=uid(r);w=workspace(r.match_info['slug'])
 if not C.execute('SELECT 1 FROM workspace_members WHERE workspace_id=? AND user_id=?',(w['id'],u)).fetchone():raise E(403,'forbidden')
 cs=[chjson(x) for x in C.execute('SELECT * FROM channels WHERE workspace_id=? AND is_dm=0 AND is_archived=0',(w['id'],))]
 return web.json_response({'workspace':{'id':w['id'],'slug':w['slug'],'name':w['name'],'owner_id':w['owner_id'],'join_mode':w['join_mode']},'channels':cs,'read_state':{}})
async def ccreate(r):
 u=uid(r);w=workspace(r.match_info['slug'])
 if not C.execute('SELECT 1 FROM workspace_members WHERE workspace_id=? AND user_id=?',(w['id'],u)).fetchone():raise E(403,'forbidden')
 b=await body(r);n=b.get('name')
 if not isinstance(n,str) or not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*',n) or len(n)>32:raise E(400,'invalid channel')
 if C.execute('SELECT 1 FROM channels WHERE workspace_id=? AND name=?',(w['id'],n)).fetchone():raise E(409,'duplicate channel')
 C.execute('INSERT INTO channels(workspace_id,name,is_private,topic,created_at) VALUES(?,?,?,?,?)',(w['id'],n,int(bool(b.get('is_private'))),b.get('topic',''),now()));i=C.execute('SELECT last_insert_rowid()').fetchone()[0];C.execute('INSERT INTO channel_members VALUES(?,?)',(i,u));return web.json_response({'channel':chjson(chrow(i))},status=201)
async def join(r):
 u=uid(r);q=chrow(r.match_info['id'])
 if q['is_private']:raise E(403,'private channel')
 if q['workspace_id'] and not C.execute('SELECT 1 FROM workspace_members WHERE workspace_id=? AND user_id=?',(q['workspace_id'],u)).fetchone():C.execute('INSERT OR IGNORE INTO workspace_members VALUES(?,?,?)',(q['workspace_id'],u,'member'))
 C.execute('INSERT OR IGNORE INTO channel_members VALUES(?,?)',(q['id'],u));return web.json_response({'channel':chjson(q)})
async def archive(r):
 u=uid(r); q=chrow(r.match_info['id'])
 if not q['workspace_id']: raise E(403,'forbidden')
 w=C.execute('SELECT owner_id FROM workspaces WHERE id=?',(q['workspace_id'],)).fetchone()
 if not w or w[0]!=u: raise E(403,'forbidden')
 C.execute('UPDATE channels SET is_archived=1 WHERE id=?',(q['id'],))
 emit(q['id'],'channel.archived',{'channel':chjson(chrow(q['id']))})
 return web.json_response({'channel':chjson(chrow(q['id']))})
async def unarchive(r):
 u=uid(r); q=chrow(r.match_info['id'])
 if not q['workspace_id']: raise E(403,'forbidden')
 w=C.execute('SELECT owner_id FROM workspaces WHERE id=?',(q['workspace_id'],)).fetchone()
 if not w or w[0]!=u: raise E(403,'forbidden')
 C.execute('UPDATE channels SET is_archived=0 WHERE id=?',(q['id'],))
 emit(q['id'],'channel.unarchived',{'channel':chjson(chrow(q['id']))})
 return web.json_response({'channel':chjson(chrow(q['id']))})
async def messages(r):
 u=uid(r);q=chrow(r.match_info['id'])
 if not allowed(q,u):raise E(403,'forbidden')
 k=cursor(r.query.get('cursor'));n=lim(r);sql='SELECT * FROM messages WHERE channel_id=? AND parent_id IS NULL AND deleted=0 '+('AND id<? ' if k else '')+'ORDER BY id DESC LIMIT ?';rows=list(C.execute(sql,((q['id'],k,n+1) if k else (q['id'],n+1))));more=len(rows)>n;rows=rows[:n];return web.json_response({'messages':[msgjson(x) for x in rows],'next_cursor':enc(rows[-1]['id']) if more else None})
async def post(r):
 u=uid(r);q=chrow(r.match_info['id'])
 if not allowed(q,u):raise E(403,'forbidden')
 b=await body(r);text=b.get('body')
 if not isinstance(text,str) or not text.strip():raise E(400,'empty body')
 if q['is_archived'] and not text.startswith('/unarchive'):raise E(423,'archived')
 if text.startswith('//'):
  text=text[1:]
 elif text.startswith('/'):
  cmd,_,arg=text[1:].partition(' ');arg=arg.strip()
  if cmd=='shrug':text=(arg+' ' if arg else '')+'¯\\_(ツ)_/¯'
  elif cmd=='me':
   if not arg: raise E(400,'missing text')
  elif cmd=='topic':
   if len(arg)>250: raise E(400,'topic too long')
   if not role(q['id'],u): raise E(403,'forbidden')
   C.execute('UPDATE channels SET topic=? WHERE id=?',(arg,q['id']))
   cq=chjson(chrow(q['id']));emit(q['id'],'channel.updated',{'channel':cq})
   return web.json_response({'message':None,'channel':cq},status=201)
  elif cmd=='invite':
   if not q['workspace_id']: raise E(403,'forbidden')
   ow=C.execute('SELECT owner_id FROM workspaces WHERE id=?',(q['workspace_id'],)).fetchone()
   if not ow or ow[0]!=u: raise E(403,'forbidden')
   if not re.fullmatch(r'@[A-Za-z0-9_]{1,32}',arg): raise E(400,'invalid invite')
   iq=C.execute('SELECT * FROM users WHERE username=?',(arg[1:],)).fetchone()
   if not iq: raise E(404,'user not found')
   if not C.execute('SELECT 1 FROM workspace_members WHERE workspace_id=? AND user_id=?',(q['workspace_id'],iq['id'])).fetchone(): raise E(400,'user is not a workspace member')
   C.execute('INSERT OR IGNORE INTO channel_members VALUES(?,?)',(q['id'],iq['id']))
   return web.json_response({'message':None,'invited_user':user(iq['id'])},status=201)
  elif cmd in ('archive','unarchive'):
   if not q['workspace_id']: raise E(403,'forbidden')
   ow=C.execute('SELECT owner_id FROM workspaces WHERE id=?',(q['workspace_id'],)).fetchone()
   if not ow or ow[0]!=u: raise E(403,'forbidden')
   val=1 if cmd=='archive' else 0
   C.execute('UPDATE channels SET is_archived=? WHERE id=?',(val,q['id']))
   cq=chjson(chrow(q['id']));emit(q['id'],'channel.archived' if val else 'channel.unarchived',{'channel':cq})
   return web.json_response({'message':None,'channel':cq},status=201)
  else: raise E(400,'unknown command')
 file_ids=b.get('file_ids',[])
 if 'file_ids' in b and (not isinstance(file_ids,list) or any(not isinstance(f,int) or isinstance(f,bool) for f in file_ids)): raise E(400,'invalid file_ids')
 if len(set(file_ids)) != len(file_ids): raise E(400,'invalid file_ids')
 for f in file_ids:
  fq=C.execute('SELECT uploader_id,message_id FROM files WHERE id=?',(f,)).fetchone()
  if not fq or fq['uploader_id']!=u or fq['message_id'] is not None: raise E(400,'invalid file')
 mn=mentions(text,q,u);par=b.get('parent_id');C.execute('INSERT INTO messages(channel_id,author_id,body,parent_id,created_at,mentions) VALUES(?,?,?,?,?,?)',(q['id'],u,text,par,now(),json.dumps(mn)));i=C.execute('SELECT last_insert_rowid()').fetchone()[0]
 for f in file_ids:C.execute('UPDATE files SET message_id=? WHERE id=?',(i,f))
 m=msgjson(C.execute('SELECT * FROM messages WHERE id=?',(i,)).fetchone());emit(q['id'],'message.reply' if par else 'message.created',{'message':m});return web.json_response({'message':m},status=201)
async def replies(r):
 u=uid(r);m=C.execute('SELECT * FROM messages WHERE id=?',(r.match_info['id'],)).fetchone()
 if not m:raise E(404,'message not found')
 q=chrow(m['channel_id'])
 if not allowed(q,u):raise E(403,'forbidden')
 return web.json_response({'replies':[msgjson(x) for x in C.execute('SELECT * FROM messages WHERE parent_id=? AND deleted=0 ORDER BY id',(m['id'],))],'next_cursor':None})
async def react(r):
 u=uid(r);m=C.execute('SELECT * FROM messages WHERE id=? AND deleted=0',(r.match_info['id'],)).fetchone()
 if not m:raise E(404,'message not found')
 q=chrow(m['channel_id'])
 if not allowed(q,u):raise E(403,'forbidden')
 if q['is_archived']:raise E(423,'archived')
 b=await body(r);e=b.get('emoji')
 if not isinstance(e,str) or not e or len(e)>64:raise E(400,'invalid emoji')
 old=C.execute('SELECT 1 FROM reactions WHERE message_id=? AND user_id=? AND emoji=?',(m['id'],u,e)).fetchone();changed=not old
 C.execute('INSERT OR IGNORE INTO reactions VALUES(?,?,?,?)',(m['id'],u,e,now()));rj=msgjson(m)['reactions']
 if changed:emit(q['id'],'reaction.added',{'message_id':m['id'],'emoji':e,'user_id':u,'reactions':rj})
 return web.json_response({'reactions':rj})
async def unreact(r):
 u=uid(r);m=C.execute('SELECT * FROM messages WHERE id=? AND deleted=0',(r.match_info['id'],)).fetchone()
 if not m:raise E(404,'message not found')
 q=chrow(m['channel_id'])
 if not allowed(q,u):raise E(403,'forbidden')
 e=r.match_info['emoji'];old=C.execute('DELETE FROM reactions WHERE message_id=? AND user_id=? AND emoji=?',(m['id'],u,e)).rowcount;rj=msgjson(m)['reactions']
 if old:emit(q['id'],'reaction.removed',{'message_id':m['id'],'emoji':e,'user_id':u,'reactions':rj})
 return web.json_response({'reactions':rj})
async def dm(r):
 u=uid(r);b=await body(r);v=b.get('user_id')
 if not isinstance(v,int):raise E(400,'invalid user_id')
 if not C.execute('SELECT 1 FROM users WHERE id=?',(v,)).fetchone():raise E(404,'user not found')
 a,z=sorted((u,v));x=C.execute('SELECT channel_id FROM dm_pairs WHERE user_low=? AND user_high=?',(a,z)).fetchone()
 if x:return web.json_response({'channel_id':x[0]})
 C.execute('INSERT INTO channels(name,is_private,is_dm,created_at) VALUES(?,?,?,?)',(f'dm-{a}-{z}',1,1,now()));cid=C.execute('SELECT last_insert_rowid()').fetchone()[0]
 C.execute('INSERT INTO dm_pairs VALUES(?,?,?)',(a,z,cid));C.execute('INSERT INTO channel_members VALUES(?,?),(?,?)',(cid,u,cid,v))
 return web.json_response({'channel_id':cid})
def fj(q):return {'id':q['id'],'uploader_id':q['uploader_id'],'filename':q['filename'],'content_type':q['content_type'],'size':q['size'],'created_at':q['created_at']}
async def upload(r):
 u=uid(r)
 if not r.content_type.startswith('multipart/'):raise E(400,'multipart required')
 rd=await r.multipart();part=None
 while True:
  try: p=await rd.next()
  except:break
  if p is None:break
  if p.name=='file':part=p;break
 if not part:raise E(400,'file required')
 name=part.filename or 'file';data=bytearray()
 while True:
  x=await part.read_chunk()
  if not x:break
  data.extend(x)
  if len(data)>10*1024*1024:raise E(413,'file too large')
 ct=part.headers.get('Content-Type','application/octet-stream')
 C.execute('INSERT INTO files(uploader_id,filename,content_type,size,created_at) VALUES(?,?,?,?,?)',(u,name,ct,len(data),now()));i=C.execute('SELECT last_insert_rowid()').fetchone()[0]
 open(f'/app/data/files/{i}','wb').write(data);return web.json_response({'file':fj(C.execute('SELECT * FROM files WHERE id=?',(i,)).fetchone())},status=201)
async def fileget(r):
 uid(r);q=C.execute('SELECT * FROM files WHERE id=?',(r.match_info['id'],)).fetchone()
 if not q:raise E(404,'file not found')
 return web.json_response({'file':fj(q)})
async def download(r):
 uid(r);q=C.execute('SELECT * FROM files WHERE id=?',(r.match_info['id'],)).fetchone()
 if not q:raise E(404,'file not found')
 return web.Response(body=open(f'/app/data/files/{q["id"]}','rb').read(),content_type=q['content_type'],headers={'Content-Disposition':f'attachment; filename="{q["filename"]}"'})
async def profile(r):
 u=uid(r);q=C.execute('SELECT * FROM users WHERE id=?',(r.match_info.get('id',u),)).fetchone()
 if not q:raise E(404,'user not found')
 return web.json_response({'user':user(q['id'])})
async def patchprofile(r):
 u=uid(r);b=await body(r);allowedf={'display_name':80,'status_text':100,'status_emoji':64,'avatar_url':1024,'timezone':128};sets=[];vals=[]
 for k,n in allowedf.items():
  if k in b:
   if not isinstance(b[k],str) or len(b[k])<1 and k=='display_name' or len(b[k])>n:raise E(400,'invalid profile')
   if k=='timezone':
    try:ZoneInfo(b[k])
    except:raise E(400,'invalid timezone')
   sets.append(k+'=?');vals.append(b[k])
 if sets:
  C.execute('UPDATE users SET '+','.join(sets)+' WHERE id=?',(*vals,u))
  C.execute('INSERT INTO broadcasts(payload) VALUES(?)',(json.dumps({'type':'user.updated','user':user(u)}),))
 return web.json_response({'user':user(u)})
async def groups(r):
 u=uid(r);w=workspace(r.match_info['slug'])
 if not C.execute('SELECT 1 FROM workspace_members WHERE workspace_id=? AND user_id=?',(w['id'],u)).fetchone():raise E(403,'forbidden')
 out=[]
 for g in C.execute('SELECT * FROM groups WHERE workspace_id=?',(w['id'],)):
  out.append({'id':g['id'],'handle':g['handle'],'name':g['name'],'member_user_ids':[x[0] for x in C.execute('SELECT user_id FROM group_members WHERE group_id=? ORDER BY user_id',(g['id'],))]})
 return web.json_response({'groups':out})
async def groupcreate(r):
 u=uid(r);w=workspace(r.match_info['slug'])
 if not C.execute('SELECT 1 FROM workspace_members WHERE workspace_id=? AND user_id=?',(w['id'],u)).fetchone():raise E(403,'forbidden')
 b=await body(r);h=b.get('handle');n=b.get('name','');ids=b.get('user_ids',[])
 if not isinstance(h,str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,30}[a-z0-9]',h) or h in ('here','channel') or not isinstance(n,str) or not n or not isinstance(ids,list):raise E(400,'invalid group')
 if C.execute('SELECT 1 FROM groups WHERE workspace_id=? AND handle=?',(w['id'],h)).fetchone():raise E(409,'duplicate')
 C.execute('INSERT INTO groups(workspace_id,handle,name,created_by) VALUES(?,?,?,?)',(w['id'],h,n,u));i=C.execute('SELECT last_insert_rowid()').fetchone()[0]
 for x in ids:
  if not C.execute('SELECT 1 FROM workspace_members WHERE workspace_id=? AND user_id=?',(w['id'],x)).fetchone():raise E(400,'invalid member')
  C.execute('INSERT INTO group_members VALUES(?,?)',(i,x))
 g=C.execute('SELECT * FROM groups WHERE id=?',(i,)).fetchone();return web.json_response({'group':{'id':i,'handle':h,'name':n,'member_user_ids':ids}},status=201)
async def grouppatch(r):
 u=uid(r); w=workspace(r.match_info['slug'])
 g=C.execute('SELECT * FROM groups WHERE workspace_id=? AND handle=?',(w['id'],r.match_info['handle'])).fetchone()
 if not g: raise E(404,'group not found')
 owner=C.execute('SELECT 1 FROM workspace_members WHERE workspace_id=? AND user_id=? AND role="owner"',(w['id'],u)).fetchone()
 if g['created_by']!=u and not owner: raise E(403,'forbidden')
 b=await body(r)
 if 'name' in b and (not isinstance(b['name'],str) or not b['name']): raise E(400,'invalid name')
 ids=b.get('user_ids')
 if ids is not None:
  if not isinstance(ids,list) or any(not isinstance(x,int) or isinstance(x,bool) for x in ids): raise E(400,'invalid user_ids')
  for x in ids:
   if not C.execute('SELECT 1 FROM workspace_members WHERE workspace_id=? AND user_id=?',(w['id'],x)).fetchone(): raise E(400,'invalid member')
 if 'name' in b: C.execute('UPDATE groups SET name=? WHERE id=?',(b['name'],g['id']))
 if ids is not None:
  C.execute('DELETE FROM group_members WHERE group_id=?',(g['id'],))
  for x in sorted(set(ids)): C.execute('INSERT INTO group_members VALUES(?,?)',(g['id'],x))
 g=C.execute('SELECT * FROM groups WHERE id=?',(g['id'],)).fetchone()
 return web.json_response({'group':{'id':g['id'],'handle':g['handle'],'name':g['name'],'member_user_ids':[x[0] for x in C.execute('SELECT user_id FROM group_members WHERE group_id=? ORDER BY user_id',(g['id'],))]}})
async def groupdelete(r):
 u=uid(r); w=workspace(r.match_info['slug'])
 g=C.execute('SELECT * FROM groups WHERE workspace_id=? AND handle=?',(w['id'],r.match_info['handle'])).fetchone()
 if not g: return web.json_response({'deleted':True})
 owner=C.execute('SELECT 1 FROM workspace_members WHERE workspace_id=? AND user_id=? AND role="owner"',(w['id'],u)).fetchone()
 if g['created_by']!=u and not owner: raise E(403,'forbidden')
 C.execute('DELETE FROM group_members WHERE group_id=?',(g['id'],)); C.execute('DELETE FROM groups WHERE id=?',(g['id'],))
 return web.json_response({'deleted':True})
async def readstate(r):
 u=uid(r); q=chrow(r.match_info['id'])
 if not allowed(q,u): raise E(403,'forbidden')
 rows=C.execute('SELECT mentions FROM messages WHERE channel_id=? AND deleted=0 AND author_id<>?',(q['id'],u))
 mentions=sum(1 for x in rows if u in json.loads(x['mentions'] or '[]'))
 total=C.execute('SELECT count(*) FROM messages WHERE channel_id=? AND deleted=0 AND author_id<>?',(q['id'],u)).fetchone()[0]
 return web.json_response({'read_state':{'channel_id':q['id'],'last_read_event_id':0,'unread_count':total,'mention_count':mentions}})
async def poll(app):
 last=C.execute('SELECT coalesce(max(seq),0) FROM events').fetchone()[0]
 blast=C.execute('SELECT coalesce(max(seq),0) FROM broadcasts').fetchone()[0]
 while True:
  for e in C.execute('SELECT * FROM events WHERE seq>? ORDER BY seq',(last,)):
   last=e['seq'];p=json.loads(e['payload'])
   for ws,u,subs in list(SOCKS.values()):
    if p['channel_id'] in subs:
     try: await ws.send_str(e['payload'])
     except: pass
  for e in C.execute('SELECT * FROM broadcasts WHERE seq>? ORDER BY seq',(blast,)):
   blast=e['seq']; payload=e['payload']
   for ws,u,subs in list(SOCKS.values()):
    try: await ws.send_str(payload)
    except: pass
  await asyncio.sleep(.05)
def setup():
 app=web.Application(middlewares=[mw],client_max_size=20*1024*1024)
 app.router.add_get('/api/health',health);app.router.add_post('/api/auth/register',authreg);app.router.add_post('/api/auth/login',login);app.router.add_get('/api/auth/me',me)
 app.router.add_get('/api/ws',wss);app.router.add_get('/api/workspaces',workspaces);app.router.add_post('/api/workspaces',wcreate);app.router.add_get('/api/workspaces/{slug}',wdetail);app.router.add_post('/api/workspaces/{slug}/channels',ccreate)
 app.router.add_post('/api/channels/{id}/join',join); app.router.add_post('/api/channels/{id}/archive',archive);app.router.add_post('/api/channels/{id}/unarchive',unarchive);app.router.add_get('/api/channels/{id}/messages',messages); app.router.add_get('/api/channels/{id}/read',readstate);app.router.add_post('/api/channels/{id}/messages',post);app.router.add_get('/api/messages/{id}/replies',replies)
 app.router.add_post('/api/messages/{id}/reactions',react);app.router.add_delete('/api/messages/{id}/reactions/{emoji}',unreact)
 app.router.add_post('/api/dms',dm);app.router.add_post('/api/files',upload);app.router.add_get('/api/files/{id}',fileget);app.router.add_get('/api/files/{id}/download',download)
 app.router.add_get('/api/users/{id}',profile);app.router.add_patch('/api/users/me',patchprofile);app.router.add_get('/api/workspaces/{slug}/groups',groups);app.router.add_post('/api/workspaces/{slug}/groups',groupcreate);app.router.add_patch('/api/workspaces/{slug}/groups/{handle}',grouppatch);app.router.add_delete('/api/workspaces/{slug}/groups/{handle}',groupdelete)
 async def start_poll(a): asyncio.create_task(poll(a))
 app.on_startup.append(start_poll);return app
if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('--port',type=int);ap.add_argument('--node-id',type=int);x=ap.parse_args();NODE=x.node_id;web.run_app(setup(),host='0.0.0.0',port=x.port)
