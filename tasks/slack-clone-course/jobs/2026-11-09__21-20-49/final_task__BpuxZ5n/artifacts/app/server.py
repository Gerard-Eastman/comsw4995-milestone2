import asyncio, os, re, json, sqlite3, secrets, hashlib, mimetypes, sys
from datetime import datetime, timezone
from aiohttp import web, WSMsgType
DB='/app/huddle.db'; NODE=int(os.getenv('NODE_ID','0'))
def now(): return datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
db=sqlite3.connect(DB,check_same_thread=False); db.row_factory=sqlite3.Row
db.executescript('''CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,username TEXT UNIQUE,password TEXT,display_name TEXT,timezone TEXT DEFAULT 'UTC',avatar_url TEXT DEFAULT '',status_text TEXT DEFAULT '',status_emoji TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS tokens(token TEXT PRIMARY KEY,user_id INTEGER);
CREATE TABLE IF NOT EXISTS workspaces(id INTEGER PRIMARY KEY,slug TEXT UNIQUE,name TEXT,owner_id INTEGER,join_mode TEXT DEFAULT 'open');
CREATE TABLE IF NOT EXISTS members(workspace_id INTEGER,user_id INTEGER,role TEXT,PRIMARY KEY(workspace_id,user_id));
CREATE TABLE IF NOT EXISTS channels(id INTEGER PRIMARY KEY,workspace_id INTEGER,name TEXT,is_private INTEGER DEFAULT 0,is_dm INTEGER DEFAULT 0,topic TEXT DEFAULT '',is_archived INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS cmembers(channel_id INTEGER,user_id INTEGER,PRIMARY KEY(channel_id,user_id));
CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY,channel_id INTEGER,author_id INTEGER,body TEXT,parent_id INTEGER,created_at TEXT,edited_at TEXT,deleted INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS events(channel_id INTEGER,event_id INTEGER,type TEXT,payload TEXT,PRIMARY KEY(channel_id,event_id));
CREATE TABLE IF NOT EXISTS reactions(message_id INTEGER,user_id INTEGER,emoji TEXT,PRIMARY KEY(message_id,user_id,emoji));
CREATE TABLE IF NOT EXISTS dms(a INTEGER,b INTEGER,channel_id INTEGER,UNIQUE(a,b));
CREATE TABLE IF NOT EXISTS files(id INTEGER PRIMARY KEY,uploader_id INTEGER,filename TEXT,content_type TEXT,size INTEGER,created_at TEXT,data BLOB,attached INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS attachments(message_id INTEGER,file_id INTEGER UNIQUE);
CREATE TABLE IF NOT EXISTS groups(id INTEGER PRIMARY KEY,workspace_id INTEGER,handle TEXT UNIQUE, name TEXT, creator_id INTEGER);
CREATE TABLE IF NOT EXISTS group_members(group_id INTEGER,user_id INTEGER,PRIMARY KEY(group_id,user_id));
CREATE TABLE IF NOT EXISTS presence(user_id INTEGER PRIMARY KEY,updated_at TEXT);
CREATE TABLE IF NOT EXISTS readstate(user_id INTEGER,channel_id INTEGER,last_read_event_id INTEGER DEFAULT 0,PRIMARY KEY(user_id,channel_id));
CREATE TABLE IF NOT EXISTS globalevents(id INTEGER PRIMARY KEY AUTOINCREMENT,payload TEXT);
'''); db.commit()
sockets=set()
def q(sql,args=()): return db.execute(sql,args).fetchall()
def one(sql,args=()): return db.execute(sql,args).fetchone()
def commit(): db.commit()
def userobj(x):
 return {k:x[k] for k in ('id','username','display_name','timezone','avatar_url','status_text','status_emoji')}
def auth(req):
 h=req.headers.get('Authorization','')
 if not h.startswith('Bearer '): return None
 x=one('SELECT u.* FROM tokens t JOIN users u ON u.id=t.user_id WHERE t.token=?',(h[7:],))
 return x
def out(x,status=200): return web.json_response(x,status=status)
def err(status,msg='error'): return out({'error':msg},status)
async def body(req):
 try:return await req.json()
 except:return {}
def channelobj(c):
 r={k:c[k] for k in ('id','workspace_id','name','topic')}
 r.update({'is_private':bool(c['is_private']),'is_dm':bool(c['is_dm']),'is_archived':bool(c['is_archived'])})
 return r
def msgobj(m):
 r={'id':m['id'],'channel_id':m['channel_id'],'author_id':m['author_id'],'author':userobj(one('SELECT * FROM users WHERE id=?',(m['author_id'],))),'body':m['body'],'parent_id':m['parent_id'],'reply_count':one('SELECT count(*) n FROM messages WHERE parent_id=? AND deleted=0',(m['id'],))['n'],'created_at':m['created_at'],'edited_at':m['edited_at'],'files':[],'reactions':[],'mentions':[]}
 for f in q('SELECT id,uploader_id,filename,content_type,size,created_at FROM files WHERE id IN (SELECT file_id FROM attachments WHERE message_id=?)',(m['id'],)):
  r['files'].append(dict(f))
 for z in q('SELECT emoji,count(*) n FROM reactions WHERE message_id=? GROUP BY emoji',(m['id'],)):
  r['reactions'].append({'emoji':z['emoji'],'count':z['n'],'user_ids':[x['user_id'] for x in q('SELECT user_id FROM reactions WHERE message_id=? AND emoji=?',(m['id'],z['emoji']))]})
 return r
async def broadcast(cid,typ,data):
 e=one('SELECT coalesce(max(event_id),0)+1 n FROM events WHERE channel_id=?',(cid,))['n']
 payload={'type':typ,'event_id':e,'channel_id':cid}; payload.update(data)
 db.execute('INSERT INTO events VALUES(?,?,?,?)',(cid,e,typ,json.dumps(payload)));commit()
 return e
async def health(req):
 return out({'status':'ok','node_id':NODE})
async def register(req):
 b=await body(req); u=b.get('username',''); p=b.get('password','')
 if not re.fullmatch(r'[A-Za-z0-9_]+',u) or len(p)<8:return err(400)
 if one('SELECT id FROM users WHERE username=?',(u,)):return err(409)
 cur=db.execute('INSERT INTO users(username,password,display_name) VALUES(?,?,?)',(u,hashlib.sha256(p.encode()).hexdigest(),b.get('display_name') or u)); uid=cur.lastrowid
 t=secrets.token_urlsafe(24);db.execute('INSERT INTO tokens VALUES(?,?)',(t,uid));commit()
 return out({'user':userobj(one('SELECT * FROM users WHERE id=?',(uid,))),'token':t},201)
async def login(req):
 b=await body(req);u=one('SELECT * FROM users WHERE username=?',(b.get('username'),))
 if not u or u['password']!=hashlib.sha256(str(b.get('password','')).encode()).hexdigest():return err(401)
 t=secrets.token_urlsafe(24);db.execute('INSERT INTO tokens VALUES(?,?)',(t,u['id']));commit();return out({'user':userobj(u),'token':t})
async def me(req):
 u=auth(req);return out({'user':userobj(u)}) if u else err(401)
async def workspaces(req):
 u=auth(req)
 if not u:return err(401)
 if req.method=='POST':
  b=await body(req)
  if not re.fullmatch(r'[a-z0-9-]{2,32}',b.get('slug','')):return err(400)
  if one('SELECT id FROM workspaces WHERE slug=?',(b['slug'],)):return err(409)
  w=db.execute('INSERT INTO workspaces(slug,name,owner_id) VALUES(?,?,?)',(b['slug'],b.get('name',''),u['id'])).lastrowid
  c=db.execute('INSERT INTO channels(workspace_id,name) VALUES(?,?)',(w,'general')).lastrowid;db.execute('INSERT INTO members VALUES(?,?,?)',(w,u['id'],'owner'));db.execute('INSERT INTO cmembers VALUES(?,?)',(c,u['id']));commit()
  return out({'workspace':dict(one('SELECT * FROM workspaces WHERE id=?',(w,))),'general_channel':channelobj(one('SELECT * FROM channels WHERE id=?',(c,)))},201)
 a=[dict(x) for x in q('SELECT w.* FROM workspaces w JOIN members m ON m.workspace_id=w.id WHERE m.user_id=?',(u['id'],))]
 return out({'workspaces':a})
async def workspace(req):
 u=auth(req)
 if not u:return err(401)
 w=one('SELECT * FROM workspaces WHERE slug=?',(req.match_info['slug'],))
 if not w:return err(404)
 cs=[channelobj(x) for x in q('SELECT * FROM channels WHERE workspace_id=? AND is_dm=0 AND (is_archived=0 OR ?)',(w['id'],req.query.get('include_archived') in ('1','true')))]
 return out({'workspace':dict(w),'channels':cs,'read_state':{}})
async def channels(req):
 u=auth(req)
 if not u:return err(401)
 w=one('SELECT * FROM workspaces WHERE slug=?',(req.match_info['slug'],))
 if not w:return err(404)
 if req.method=='POST':
  b=await body(req);name=b.get('name','')
  if not re.fullmatch(r'[a-z0-9-]{1,32}',name):return err(400)
  if one('SELECT id FROM channels WHERE workspace_id=? AND name=?',(w['id'],name)):return err(409)
  c=db.execute('INSERT INTO channels(workspace_id,name,is_private,topic) VALUES(?,?,?,?)',(w['id'],name,int(bool(b.get('is_private'))),b.get('topic',''))).lastrowid
  db.execute('INSERT INTO cmembers VALUES(?,?)',(c,u['id']));commit();return out({'channel':channelobj(one('SELECT * FROM channels WHERE id=?',(c,)))},201)
async def patchchannel(req):
 u=auth(req)
 if not u:return err(401)
 c=one('SELECT * FROM channels WHERE id=?',(req.match_info['id'],))
 if not c:return err(404)
 w=one('SELECT * FROM workspaces WHERE id=?',(c['workspace_id'],))
 if not one('SELECT 1 FROM cmembers WHERE channel_id=? AND user_id=?',(c['id'],u['id'])) and w['owner_id']!=u['id']:return err(403)
 b=await body(req); topic=b.get('topic','')
 if not isinstance(topic,str) or len(topic)>250:return err(400)
 db.execute('UPDATE channels SET topic=? WHERE id=?',(topic,c['id']));commit()
 return out({'channel':channelobj(one('SELECT * FROM channels WHERE id=?',(c['id'],)))})
async def join(req):
 u=auth(req)
 if not u:return err(401)
 c=one('SELECT * FROM channels WHERE id=?',(req.match_info['id'],))
 if not c:return err(404)
 w=one('SELECT * FROM workspaces WHERE id=?',(c['workspace_id'],))
 if c['is_private'] and not one('SELECT 1 FROM cmembers WHERE channel_id=? AND user_id=?',(c['id'],u['id'])):return err(403)
 db.execute('INSERT OR IGNORE INTO members VALUES(?,?,?)',(w['id'],u['id'],'member'));db.execute('INSERT OR IGNORE INTO cmembers VALUES(?,?)',(c['id'],u['id']));commit();return out({'channel':channelobj(c)})
async def upload(req):
 u=auth(req)
 if not u:return err(401)
 if not req.content_type.startswith('multipart/'):return err(400)
 reader=await req.multipart(); part=None
 async for x in reader:
  if x.name=='file': part=x; break
 if part is None:return err(400)
 data=await part.read()
 if len(data)>10*1024*1024:return err(413)
 fn=part.filename or 'file'; ct=part.headers.get('Content-Type') or 'application/octet-stream'
 fid=db.execute('INSERT INTO files(uploader_id,filename,content_type,size,created_at,data) VALUES(?,?,?,?,?,?)',(u['id'],fn,ct,len(data),now(),data)).lastrowid;commit()
 f=one('SELECT id,uploader_id,filename,content_type,size,created_at FROM files WHERE id=?',(fid,))
 return out({'file':dict(f)},201)
async def fileget(req):
 u=auth(req)
 if not u:return err(401)
 f=one('SELECT id,uploader_id,filename,content_type,size,created_at FROM files WHERE id=?',(req.match_info['id'],))
 return out({'file':dict(f)}) if f else err(404)
async def filedn(req):
 u=auth(req)
 if not u:return err(401)
 f=one('SELECT * FROM files WHERE id=?',(req.match_info['id'],))
 if not f:return err(404)
 return web.Response(body=f['data'],content_type=f['content_type'],headers={'Content-Disposition':'attachment; filename="'+f['filename']+'"'})
async def messages(req):
 u=auth(req)
 if not u:return err(401)
 cid=int(req.match_info['id']);c=one('SELECT * FROM channels WHERE id=?',(cid,))
 if not c:return err(404)
 if not one('SELECT 1 FROM cmembers WHERE channel_id=? AND user_id=?',(cid,u['id'])):return err(403)
 if req.method=='GET':
  a=[msgobj(x) for x in q('SELECT * FROM messages WHERE channel_id=? AND deleted=0 ORDER BY id DESC LIMIT 200',(cid,))]
  return out({'messages':a,'next_cursor':None})
 b=await body(req);text=b.get('body')
 if not isinstance(text,str) or not text.strip():return err(400)
 if c['is_archived'] and text not in ('/unarchive',):return err(423)
 ids=b.get('file_ids',[])
 if not isinstance(ids,list):return err(400)
 for fid in ids:
  f=one('SELECT * FROM files WHERE id=?',(fid,))
  if not f or f['uploader_id']!=u['id'] or f['attached']:return err(400)
 if text.startswith('/') and not text.startswith('//'):
  if text=='/me':return err(400)
  if text.startswith('/shrug'):
   text=text[6:].strip()
   text=(text+' ' if text else '')+'¯\\_(ツ)_/¯'
  elif text.startswith('/topic'):
   topic=text[6:].strip()
   if len(topic)>250:return err(400)
   db.execute('UPDATE channels SET topic=? WHERE id=?',(topic,cid));commit();return out({'message':None,'channel':channelobj(one('SELECT * FROM channels WHERE id=?',(cid,)))},201)
  elif text.startswith('/invite '):
   uname=text[8:].strip().lstrip('@')
   target=one('SELECT * FROM users WHERE username=?',(uname,))
   if not target:return err(404)
   if not one('SELECT 1 FROM members WHERE workspace_id=? AND user_id=?',(c['workspace_id'],target['id'])):return err(400)
   db.execute('INSERT OR IGNORE INTO cmembers VALUES(?,?)',(cid,target['id']));commit()
   return out({'message':None,'invited_user':userobj(target)},201)
  elif text=='/archive' or text=='/unarchive':
   w=one('SELECT * FROM workspaces WHERE id=?',(c['workspace_id'],))
   if w['owner_id']!=u['id']:return err(403)
   val=int(text=='/archive')
   db.execute('UPDATE channels SET is_archived=? WHERE id=?',(val,cid));commit()
   return out({'message':None,'channel':channelobj(one('SELECT * FROM channels WHERE id=?',(cid,)))},201)
  elif text.startswith('/me '):pass
  else:return err(400)
 if text.startswith('//'):text=text[1:]
 mentions=set()
 for x in re.findall(r'(?<![A-Za-z0-9_])@([A-Za-z0-9_-]+)',text):
  if x=='channel':
   mentions.update(z['user_id'] for z in q('SELECT user_id FROM cmembers WHERE channel_id=? AND user_id!=?',(cid,u['id'])))
  elif x=='here':
   mentions.update(z['user_id'] for z in q('SELECT cm.user_id FROM cmembers cm JOIN presence p ON p.user_id=cm.user_id WHERE cm.channel_id=? AND cm.user_id!=?',(cid,u['id'])))
  else:
   g=one('SELECT id FROM groups WHERE workspace_id=? AND handle=?',(c['workspace_id'],x))
   if g: mentions.update(z['user_id'] for z in q('SELECT gm.user_id FROM group_members gm JOIN cmembers cm ON cm.user_id=gm.user_id WHERE gm.group_id=? AND cm.channel_id=? AND gm.user_id!=?',(g['id'],cid,u['id'])))
   else:
    z=one('SELECT id FROM users WHERE username=?',(x,))
    if z and z['id']!=u['id'] and one('SELECT 1 FROM cmembers WHERE channel_id=? AND user_id=?',(cid,z['id'])): mentions.add(z['id'])
 mid=db.execute('INSERT INTO messages(channel_id,author_id,body,parent_id,created_at) VALUES(?,?,?,?,?)',(cid,u['id'],text,b.get('parent_id'),now())).lastrowid
 for fid in ids: db.execute('INSERT INTO attachments VALUES(?,?)',(mid,fid)); db.execute('UPDATE files SET attached=1 WHERE id=?',(fid,))
 commit();m=msgobj(one('SELECT * FROM messages WHERE id=?',(mid,)));m['mentions']=list(mentions)
 await broadcast(cid,'message.reply' if b.get('parent_id') else 'message.created',{'message':m});return out({'message':m},201)
async def replies(req):
 u=auth(req)
 if not u:return err(401)
 m=one('SELECT * FROM messages WHERE id=?',(req.match_info['id'],))
 if not m:return err(404)
 return out({'replies':[msgobj(x) for x in q('SELECT * FROM messages WHERE parent_id=? AND deleted=0 ORDER BY id',(m['id'],))],'next_cursor':None})
async def react(req):
 u=auth(req)
 if not u:return err(401)
 m=one('SELECT * FROM messages WHERE id=?',(req.match_info['id'],))
 if not m or m['deleted']:return err(404)
 c=one('SELECT * FROM channels WHERE id=?',(m['channel_id'],))
 if not one('SELECT 1 FROM cmembers WHERE channel_id=? AND user_id=?',(c['id'],u['id'])):return err(403)
 if c['is_archived']:return err(423)
 emoji=(await body(req)).get('emoji','')
 if not emoji or len(emoji)>16:return err(400)
 exists=one('SELECT 1 FROM reactions WHERE message_id=? AND user_id=? AND emoji=?',(m['id'],u['id'],emoji))
 if not exists:
  db.execute('INSERT INTO reactions VALUES(?,?,?)',(m['id'],u['id'],emoji));commit()
  await broadcast(c['id'],'reaction.added',{'message_id':m['id'],'emoji':emoji,'user_id':u['id'],'reactions':msgobj(m)['reactions']})
 return out({'reactions':msgobj(one('SELECT * FROM messages WHERE id=?',(m['id'],)))['reactions']})
async def unreact(req):
 u=auth(req)
 if not u:return err(401)
 m=one('SELECT * FROM messages WHERE id=?',(req.match_info['id'],))
 if not m or m['deleted']:return err(404)
 c=one('SELECT * FROM channels WHERE id=?',(m['channel_id'],))
 cur=db.execute('DELETE FROM reactions WHERE message_id=? AND user_id=? AND emoji=?',(m['id'],u['id'],req.match_info['emoji']));commit()
 if cur.rowcount:
  await broadcast(c['id'],'reaction.removed',{'message_id':m['id'],'emoji':req.match_info['emoji'],'user_id':u['id'],'reactions':msgobj(one('SELECT * FROM messages WHERE id=?',(m['id'],)))['reactions']})
 return out({'reactions':msgobj(one('SELECT * FROM messages WHERE id=?',(m['id'],)))['reactions']})
async def edit(req):
 u=auth(req)
 if not u:return err(401)
 m=one('SELECT * FROM messages WHERE id=?',(req.match_info['id'],))
 if not m:return err(404)
 if m['author_id']!=u['id']:return err(403)
 if m['deleted']:return err(409)
 c=one('SELECT * FROM channels WHERE id=?',(m['channel_id'],))
 if c['is_archived']:return err(423)
 text=(await body(req)).get('body')
 if not isinstance(text,str) or not text.strip():return err(400)
 db.execute('UPDATE messages SET body=?,edited_at=? WHERE id=?',(text,now(),m['id']));commit()
 mm=msgobj(one('SELECT * FROM messages WHERE id=?',(m['id'],)))
 await broadcast(c['id'],'message.updated',{'message':mm});return out({'message':mm})
async def delete(req):
 u=auth(req); 
 if not u:return err(401)
 m=one('SELECT * FROM messages WHERE id=?',(req.match_info['id'],))
 if not m:return err(404)
 if m['deleted']:return out({'deleted':True})
 c=one('SELECT * FROM channels WHERE id=?',(m['channel_id'],));w=one('SELECT * FROM workspaces WHERE id=?',(c['workspace_id'],))
 if m['author_id']!=u['id'] and w['owner_id']!=u['id']:return err(403)
 db.execute('UPDATE messages SET deleted=1 WHERE id=?',(m['id'],));commit()
 await broadcast(c['id'],'message.deleted',{'message_id':m['id']});return out({'deleted':True})
async def readstate_api(req):
 u=auth(req)
 if not u:return err(401)
 cid=int(req.match_info['id'])
 c=one('SELECT * FROM channels WHERE id=?',(cid,))
 if not c:return err(404)
 if not one('SELECT 1 FROM cmembers WHERE channel_id=? AND user_id=?',(cid,u['id'])):return err(403)
 row=one('SELECT * FROM readstate WHERE user_id=? AND channel_id=?',(u['id'],cid))
 last=row['last_read_event_id'] if row else 0
 if req.method=='POST':
  b=await body(req); v=b.get('last_read_event_id')
  if not isinstance(v,int):return err(400)
  last=max(last,v)
  db.execute('INSERT OR REPLACE INTO readstate VALUES(?,?,?)',(u['id'],cid,last));commit()
 head=one('SELECT coalesce(max(event_id),0) n FROM events WHERE channel_id=?',(cid,))['n']
 mentions=0
 for m in q('SELECT body FROM messages WHERE channel_id=? AND author_id!=? AND deleted=0',(cid,u['id'])):
  if f'@{u["username"]}' in m['body'] or '@channel' in m['body'] or '@here' in m['body']: mentions+=1
 rs={'channel_id':cid,'last_read_event_id':last,'unread_count':max(0,head-last),'mention_count':mentions}
 return out({'read_state':rs})
async def groups(req):
 u=auth(req)
 if not u:return err(401)
 w=one('SELECT * FROM workspaces WHERE slug=?',(req.match_info['slug'],))
 if not w:return err(404)
 member=one('SELECT 1 FROM members WHERE workspace_id=? AND user_id=?',(w['id'],u['id']))
 if not member:return err(403)
 if req.method=='GET':
  out=[]
  for g in q('SELECT * FROM groups WHERE workspace_id=?',(w['id'],)):
   out.append({'id':g['id'],'handle':g['handle'],'name':g['name'],'member_user_ids':[x['user_id'] for x in q('SELECT user_id FROM group_members WHERE group_id=?',(g['id'],))]})
  return outjson({'groups':out})
 b=await body(req);h=b.get('handle',''); name=b.get('name',''); ids=b.get('user_ids',[])
 if not re.fullmatch(r'[a-z0-9][a-z0-9-]{1,31}',h) or h in ('here','channel') or not name or not isinstance(ids,list):return err(400)
 if one('SELECT id FROM groups WHERE workspace_id=? AND handle=?',(w['id'],h)):return err(409)
 for i in ids:
  if not one('SELECT 1 FROM members WHERE workspace_id=? AND user_id=?',(w['id'],i)):return err(400)
 gid=db.execute('INSERT INTO groups(workspace_id,handle,name,creator_id) VALUES(?,?,?,?)',(w['id'],h,name,u['id'])).lastrowid
 for i in set(ids):db.execute('INSERT INTO group_members VALUES(?,?)',(gid,i))
 commit();return outjson({'group':{'id':gid,'handle':h,'name':name,'member_user_ids':list(set(ids))}},201)
async def groupitem(req):
 u=auth(req); 
 if not u:return err(401)
 w=one('SELECT * FROM workspaces WHERE slug=?',(req.match_info['slug'],));g=one('SELECT * FROM groups WHERE workspace_id=? AND handle=?',(w['id'],req.match_info['handle'])) if w else None
 if not w:return err(404)
 if not g:
  if req.method=='DELETE': return outjson({'deleted':True})
  return err(404)
 owner=one('SELECT 1 FROM members WHERE workspace_id=? AND user_id=? AND role=?',(w['id'],u['id'],'owner'))
 if req.method=='DELETE':
  if u['id']!=g['creator_id'] and not owner:return err(403)
  db.execute('DELETE FROM groups WHERE id=?',(g['id'],));commit();return outjson({'deleted':True})
 if u['id']!=g['creator_id'] and not owner:return err(403)
 b=await body(req);name=b.get('name',g['name']);ids=b.get('user_ids')
 if ids is not None:
  for i in ids:
   if not one('SELECT 1 FROM members WHERE workspace_id=? AND user_id=?',(w['id'],i)):return err(400)
  db.execute('DELETE FROM group_members WHERE group_id=?',(g['id'],))
  for i in set(ids):db.execute('INSERT INTO group_members VALUES(?,?)',(g['id'],i))
 db.execute('UPDATE groups SET name=? WHERE id=?',(name,g['id']));commit()
 return outjson({'group':{'id':g['id'],'handle':g['handle'],'name':name,'member_user_ids':[x['user_id'] for x in q('SELECT user_id FROM group_members WHERE group_id=?',(g['id'],))]}})
def outjson(x,status=200): return web.json_response(x,status=status)
async def archive(req):
 u=auth(req)
 if not u:return err(401)
 c=one('SELECT * FROM channels WHERE id=?',(req.match_info['id'],))
 if not c:return err(404)
 w=one('SELECT * FROM workspaces WHERE id=?',(c['workspace_id'],))
 if w['owner_id']!=u['id']:return err(403)
 val=1 if req.path.endswith('/archive') else 0
 db.execute('UPDATE channels SET is_archived=? WHERE id=?',(val,c['id']));commit()
 await broadcast(c['id'],'channel.archived' if val else 'channel.unarchived',{'channel':channelobj(one('SELECT * FROM channels WHERE id=?',(c['id'],)))})
 return out({'channel':channelobj(one('SELECT * FROM channels WHERE id=?',(c['id'],)))})
async def dms(req):
 u=auth(req)
 if not u:return err(401)
 b=await body(req); tid=b.get('user_id')
 if not isinstance(tid,int):return err(400)
 if not one('SELECT id FROM users WHERE id=?',(tid,)):return err(404)
 a,bid=sorted((u['id'],tid));x=one('SELECT channel_id FROM dms WHERE a=? AND b=?',(a,bid))
 if x:return out({'channel_id':x['channel_id']})
 cid=db.execute('INSERT INTO channels(name,is_dm) VALUES(?,1)',(f'dm-{a}-{bid}',)).lastrowid
 db.execute('INSERT INTO dms VALUES(?,?,?)',(a,bid,cid));db.execute('INSERT INTO cmembers VALUES(?,?)',(cid,a));db.execute('INSERT INTO cmembers VALUES(?,?)',(cid,bid));commit()
 return out({'channel_id':cid})
async def ws_handler(req):
 token=req.query.get('token','')
 u=one('SELECT u.* FROM tokens t JOIN users u ON u.id=t.user_id WHERE t.token=?',(token,))
 if not u:return web.Response(status=401)
 ws=web.WebSocketResponse();await ws.prepare(req)
 db.execute('INSERT OR REPLACE INTO presence VALUES(?,?)',(u['id'],now()));commit()
 cursors={}; global_cursor=one('SELECT coalesce(max(id),0) n FROM globalevents')['n']
 async def pump():
  nonlocal global_cursor
  while not ws.closed:
   try:
    for ge in q('SELECT id,payload FROM globalevents WHERE id>? ORDER BY id',(global_cursor,)):
     await ws.send_str(ge['payload']); global_cursor=ge['id']
    for cid,last in list(cursors.items()):
     for e in q('SELECT event_id,payload FROM events WHERE channel_id=? AND event_id>? ORDER BY event_id',(cid,last)):
      await ws.send_str(e['payload']); cursors[cid]=e['event_id']
    await asyncio.sleep(.05)
   except Exception: return
 task=asyncio.create_task(pump())
 try:
  async for m in ws:
   if m.type!=WSMsgType.TEXT: continue
   try:b=json.loads(m.data)
   except:continue
   cid=int(b.get('channel_id',0)); typ=b.get('type')
   if typ=='subscribe':
    head=one('SELECT coalesce(max(event_id),0) n FROM events WHERE channel_id=?',(cid,))['n']
    cursors[cid]=head
    await ws.send_json({'type':'subscribed','channel_id':cid,'head_event_id':head})
   elif typ=='resume':
    since=int(b.get('since_event_id',0)); cursors[cid]=since
    for e in q('SELECT event_id,payload FROM events WHERE channel_id=? AND event_id>? ORDER BY event_id',(cid,since)):
     await ws.send_str(e['payload']); cursors[cid]=e['event_id']
    head=one('SELECT coalesce(max(event_id),0) n FROM events WHERE channel_id=?',(cid,))['n']
    await ws.send_json({'type':'resumed','channel_id':cid,'head_event_id':head})
 finally:
  db.execute('DELETE FROM presence WHERE user_id=?',(u['id'],));commit();task.cancel()
 return ws
async def profile(req):
 u=auth(req)
 if not u:return err(401)
 b=await body(req)
 allowed=('display_name','timezone','status_text','status_emoji','avatar_url')
 for k in b:
  if k not in allowed: continue
  v=b[k]
  if not isinstance(v,str): return err(400)
  limits={'display_name':80,'status_text':100,'status_emoji':64,'avatar_url':1024}
  if k in limits and (not v or len(v)>limits[k]): return err(400)
 if 'timezone' in b:
  try:
   from zoneinfo import ZoneInfo
   ZoneInfo(b['timezone'])
  except Exception:return err(400)
 sets=[]; vals=[]
 for k in allowed:
  if k in b: sets.append(k+'=?');vals.append(b[k])
 if sets:
  vals.append(u['id']);db.execute('UPDATE users SET '+','.join(sets)+' WHERE id=?',vals);commit()
 nu=one('SELECT * FROM users WHERE id=?',(u['id'],)); payload={'type':'user.updated','user':userobj(nu)}
 db.execute('INSERT INTO globalevents(payload) VALUES(?)',(json.dumps(payload),));commit()
 return out({'user':userobj(nu)})
async def getuser(req):
 u=auth(req)
 if not u:return err(401)
 x=one('SELECT * FROM users WHERE id=?',(req.match_info['id'],))
 return out({'user':userobj(x)}) if x else err(404)
app=web.Application();app.router.add_get('/',lambda r:web.FileResponse('/app/index.html'));app.router.add_get('/static/app.js',lambda r:web.FileResponse('/app/app.js'));app.router.add_get('/static/style.css',lambda r:web.FileResponse('/app/style.css'))
app.router.add_get('/api/health',health);app.router.add_post('/api/auth/register',register);app.router.add_post('/api/auth/login',login);app.router.add_get('/api/auth/me',me)
app.router.add_route('*','/api/workspaces',workspaces);app.router.add_route('*','/api/workspaces/{slug}/channels',channels);app.router.add_post('/api/channels/{id}/join',join);app.router.add_patch('/api/channels/{id}',patchchannel);app.router.add_post('/api/channels/{id}/archive',archive);app.router.add_post('/api/channels/{id}/unarchive',archive)
app.router.add_route('*','/api/channels/{id}/messages',messages);app.router.add_get('/api/messages/{id}/replies',replies);app.router.add_post('/api/messages/{id}/reactions',react);app.router.add_delete('/api/messages/{id}/reactions/{emoji}',unreact)
app.router.add_patch('/api/messages/{id}',edit);app.router.add_delete('/api/messages/{id}',delete);app.router.add_post('/api/dms',dms);app.router.add_post('/api/files',upload);app.router.add_get('/api/files/{id}',fileget);app.router.add_get('/api/files/{id}/download',filedn);app.router.add_get('/api/users/{id}',getuser);app.router.add_get('/api/ws',ws_handler)
app.router.add_get('/api/workspaces/{slug}',workspace);app.router.add_patch('/api/users/me',profile);app.router.add_route('*','/api/channels/{id}/read',readstate_api);app.router.add_route('*','/api/workspaces/{slug}/groups',groups);app.router.add_route('*','/api/workspaces/{slug}/groups/{handle}',groupitem)
if __name__=='__main__': web.run_app(app,host='127.0.0.1',port=8000+NODE)
