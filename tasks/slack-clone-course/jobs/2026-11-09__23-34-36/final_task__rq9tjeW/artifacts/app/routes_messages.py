import json, re
from aiohttp import web
from db import connect, now_iso
from common import *
MENTION_RE=re.compile(r'(?<![A-Za-z0-9_@.])@([A-Za-z0-9_]+)(?![A-Za-z0-9_@])(?!\\.[A-Za-z0-9])')
def resolve_mentions(body,channel,author_id):
 c=connect(); out=[]
 for m in MENTION_RE.finditer(body):
  name=m.group(1)
  if name in ('channel','here'):
   if name=='here':
    ids=[x[0] for x in c.execute('SELECT DISTINCT user_id FROM ws_presence WHERE channel_id=?',(channel['id'],)).fetchall()]
   else:
    ids=[x[0] for x in c.execute('SELECT user_id FROM channel_members WHERE channel_id=?',(channel['id'],)).fetchall()]
   for uid in ids:
    if uid!=author_id and uid not in out: out.append(uid)
   continue
  r=c.execute('SELECT id FROM users WHERE username=?',(name,)).fetchone()
  if not r: continue
  uid=r[0]
  if uid==author_id or uid in out: continue
  if c.execute('SELECT 1 FROM workspace_members WHERE workspace_id=? AND user_id=?',(channel['workspace_id'],uid)).fetchone(): out.append(uid)
 return out

def read_state_for(cid,uid):
 c=connect(); r=c.execute('SELECT last_read_event_id FROM channel_members WHERE channel_id=? AND user_id=?',(cid,uid)).fetchone(); last=r[0] if r else 0
 rows=c.execute('SELECT m.author_id,m.mentions FROM messages m WHERE m.channel_id=? AND m.deleted=0 AND m.event_id>?',(cid,last)).fetchall()
 other=[x for x in rows if x['author_id']!=uid]; ment=sum(1 for x in other if uid in (json.loads(x['mentions'] or '[]')))
 return {'channel_id':cid,'last_read_event_id':last,'unread_count':len(other),'mention_count':ment}
def files_for(mid):
 c=connect(); rows=c.execute('SELECT * FROM files WHERE message_id=? ORDER BY id',(mid,)).fetchall()
 return [{k:x[k] for k in ('id','uploader_id','filename','content_type','size','created_at')} for x in rows]
def msg_json(r):
 c=connect(); u=user_by_id(r['author_id'])
 replies=c.execute('SELECT count(*) FROM messages WHERE parent_id=? AND deleted=0',(r['id'],)).fetchone()[0]
 return {'id':r['id'],'channel_id':r['channel_id'],'author_id':r['author_id'],'author':user_to_json(u),'body':r['body'],'parent_id':r['parent_id'],'reply_count':replies,'created_at':r['created_at'],'edited_at':r['edited_at'],'files':files_for(r['id']),'reactions':reactions(r['id']),'mentions':json.loads(r['mentions'] or '[]')}
def allowed(cid,uid):
 ch=channel_by_id(cid)
 if not is_channel_member(cid,uid): raise HTTPError(403,'not a channel member')
 if ch['is_archived']: raise HTTPError(423,'channel archived')
 return ch
def can_read(cid,uid):
 ch=channel_by_id(cid)
 if not is_channel_member(cid,uid): raise HTTPError(403,'not a channel member')
 return ch
async def post(req):
 u=require_user(req); cid=int(req.match_info['id']); ch=channel_by_id(cid)
 if not is_channel_member(cid,u['id']): raise HTTPError(403,'not a channel member')
 d=await read_json(req); body=d.get('body')
 if not isinstance(body,str) or not body.strip(): raise HTTPError(400,'empty body')
 if body.startswith('//'): body=body[1:]
 elif body.startswith('/'):
  cmd,_,text=body[1:].partition(' '); text=text.strip()
  if cmd=='unarchive':
   w=connect().execute('SELECT * FROM workspaces WHERE id=?',(ch['workspace_id'],)).fetchone()
   if not w or w['owner_id']!=u['id']: raise HTTPError(403,'owner only')
   connect().execute('UPDATE channels SET is_archived=0 WHERE id=?',(cid,)); emit_event(cid,'channel.unarchived',{'channel':channel_to_json(channel_by_id(cid))})
   return web.json_response({'message':None,'channel':channel_to_json(channel_by_id(cid))},status=201)
  if cmd=='archive':
   w=connect().execute('SELECT * FROM workspaces WHERE id=?',(ch['workspace_id'],)).fetchone()
   if not w or w['owner_id']!=u['id']: raise HTTPError(403,'owner only')
   connect().execute('UPDATE channels SET is_archived=1 WHERE id=?',(cid,)); emit_event(cid,'channel.archived',{'channel':channel_to_json(channel_by_id(cid))})
   return web.json_response({'message':None,'channel':channel_to_json(channel_by_id(cid))},status=201)
  if cmd=='me':
   if not text: raise HTTPError(400,'missing text')
  elif cmd=='shrug':
   body=(text+' ' if text else '')+'¯\\_(ツ)_/¯'
  elif cmd=='topic':
   if len(text)>250: raise HTTPError(400,'topic too long')
   connect().execute('UPDATE channels SET topic=? WHERE id=?',(text,cid)); emit_event(cid,'channel.updated',{'channel':channel_to_json(channel_by_id(cid))})
   return web.json_response({'message':None,'channel':channel_to_json(channel_by_id(cid))},status=201)
  elif cmd=='invite':
   if not text.startswith('@') or len(text)<2: raise HTTPError(400,'missing username')
   target=connect().execute('SELECT * FROM users WHERE username=?',(text[1:],)).fetchone()
   if not target: raise HTTPError(404,'user not found')
   if not connect().execute('SELECT 1 FROM workspace_members WHERE workspace_id=? AND user_id=?',(ch['workspace_id'],target['id'])).fetchone(): raise HTTPError(400,'not workspace member')
   add_channel_member(cid,target['id'])
   return web.json_response({'message':None,'invited_user':user_to_json(target)},status=201)
  else: raise HTTPError(400,'unknown command')
 if ch['is_archived']: raise HTTPError(423,'channel archived')
 parent=d.get('parent_id'); c=connect()
 if parent is not None and not c.execute('SELECT 1 FROM messages WHERE id=? AND channel_id=? AND deleted=0',(parent,cid)).fetchone(): raise HTTPError(400,'invalid parent')
 fids=d.get('file_ids',[])
 if not isinstance(fids,list) or any(not isinstance(x,int) for x in fids): raise HTTPError(400,'invalid files')
 files=connect().execute('SELECT * FROM files WHERE id IN (%s)'%(','.join('?'*len(fids)),),fids).fetchall() if fids else []
 if len(files)!=len(set(fids)) or any(x['uploader_id']!=u['id'] or x['message_id'] is not None for x in files): raise HTTPError(400,'invalid files')
 mentions=resolve_mentions(body,ch,u['id'])
 c.execute('INSERT INTO messages(channel_id,author_id,body,parent_id,created_at,mentions) VALUES(?,?,?,?,?,?)',(cid,u['id'],body,parent,now_iso(),json.dumps(mentions)))
 r=c.execute('SELECT * FROM messages WHERE id=last_insert_rowid()').fetchone()
 for x in files: c.execute('UPDATE files SET message_id=? WHERE id=?',(r['id'],x['id']))
 m=msg_json(r); eid=emit_event(cid,'message.reply' if parent else 'message.created',{'message':m}); c.execute('UPDATE messages SET event_id=? WHERE id=?',(eid,r['id'])); m=msg_json(c.execute('SELECT * FROM messages WHERE id=?',(r['id'],)).fetchone())
 return web.json_response({'message':m},status=201)

async def listing(req):
 u=require_user(req); cid=int(req.match_info['id']); can_read(cid,u['id']); n=parse_limit(req)
 before=decode_cursor(req.query['cursor']) if req.query.get('cursor') else None
 c=connect()
 if before is None:
  rows=c.execute('SELECT * FROM messages WHERE channel_id=? AND parent_id IS NULL AND deleted=0 ORDER BY id DESC LIMIT ?',(cid,n+1)).fetchall()
 else:
  rows=c.execute('SELECT * FROM messages WHERE channel_id=? AND parent_id IS NULL AND deleted=0 AND id<? ORDER BY id DESC LIMIT ?',(cid,before,n+1)).fetchall()
 more=len(rows)>n; shown=rows[:n]
 return web.json_response({'messages':[msg_json(x) for x in shown],'next_cursor':encode_cursor(shown[-1]['id']) if more and shown else None})

async def replies(req):
 u=require_user(req); r=connect().execute('SELECT * FROM messages WHERE id=?',(req.match_info['id'],)).fetchone()
 if not r: raise HTTPError(404,'message not found')
 allowed(r['channel_id'],u['id']); n=parse_limit(req); off=decode_cursor(req.query['cursor']) if req.query.get('cursor') else 0
 rows=connect().execute('SELECT * FROM messages WHERE parent_id=? AND deleted=0 ORDER BY id LIMIT ? OFFSET ?',(r['id'],n+1,off)).fetchall()
 return web.json_response({'replies':[msg_json(x) for x in rows[:n]],'next_cursor':encode_cursor(off+n) if len(rows)>n else None})
async def edit(req):
 u=require_user(req); c=connect(); r=c.execute('SELECT * FROM messages WHERE id=?',(req.match_info['id'],)).fetchone()
 if not r: raise HTTPError(404,'message not found')
 if channel_by_id(r['channel_id'])['is_archived']: raise HTTPError(423,'channel archived')
 if r['author_id']!=u['id']: raise HTTPError(403,'forbidden')
 if r['deleted']: raise HTTPError(409,'deleted')
 d=await read_json(req); body=d.get('body')
 if not isinstance(body,str) or not body.strip(): raise HTTPError(400,'empty body')
 c.execute('UPDATE messages SET body=?,edited_at=? WHERE id=?',(body,now_iso(),r['id']))
 m=msg_json(c.execute('SELECT * FROM messages WHERE id=?',(r['id'],)).fetchone()); emit_event(r['channel_id'],'message.updated',{'message':m})
 return web.json_response({'message':m})
async def delete(req):
 u=require_user(req); c=connect(); r=c.execute('SELECT * FROM messages WHERE id=?',(req.match_info['id'],)).fetchone()
 if not r: raise HTTPError(404,'message not found')
 if r['deleted']: return web.json_response({'deleted':True})
 w=c.execute('SELECT w.* FROM workspaces w JOIN channels ch ON ch.workspace_id=w.id WHERE ch.id=?',(r['channel_id'],)).fetchone()
 if r['author_id']!=u['id'] and w['owner_id']!=u['id']:raise HTTPError(403,'forbidden')
 c.execute('UPDATE messages SET deleted=1 WHERE id=?',(r['id'],)); emit_event(r['channel_id'],'message.deleted',{'message_id':r['id']})
 return web.json_response({'deleted':True})
def setup(app):
 app.router.add_post('/api/channels/{id}/messages',post); app.router.add_get('/api/channels/{id}/messages',listing)
 app.router.add_get('/api/messages/{id}/replies',replies); app.router.add_patch('/api/messages/{id}',edit); app.router.add_delete('/api/messages/{id}',delete)

def reactions(cid):
 rows=connect().execute('SELECT emoji,user_id FROM reactions WHERE message_id=?',(cid,)).fetchall(); out={}
 for r in rows: out.setdefault(r['emoji'],[]).append(r['user_id'])
 return [{'emoji':e,'count':len(v),'user_ids':v} for e,v in out.items()]
async def react(req):
 u=require_user(req); c=connect(); r=c.execute('SELECT * FROM messages WHERE id=?',(req.match_info['id'],)).fetchone()
 if not r or r['deleted']: raise HTTPError(404,'message not found')
 allowed(r['channel_id'],u['id']); d=await read_json(req); emoji=d.get('emoji')
 if not isinstance(emoji,str) or not emoji or len(emoji)>64: raise HTTPError(400,'invalid emoji')
 old=c.execute('SELECT 1 FROM reactions WHERE message_id=? AND user_id=? AND emoji=?',(r['id'],u['id'],emoji)).fetchone()
 c.execute('INSERT OR IGNORE INTO reactions(message_id,user_id,emoji,created_at) VALUES(?,?,?,?)',(r['id'],u['id'],emoji,now_iso()))
 if not old: emit_event(r['channel_id'],'reaction.added',{'message_id':r['id'],'emoji':emoji,'user_id':u['id'],'reactions':reactions(r['id'])})
 return web.json_response({'reactions':reactions(r['id'])})
async def unreact(req):
 u=require_user(req); c=connect(); r=c.execute('SELECT * FROM messages WHERE id=?',(req.match_info['id'],)).fetchone()
 if not r: raise HTTPError(404,'message not found')
 allowed(r['channel_id'],u['id']); emoji=req.match_info['emoji']; old=c.execute('SELECT 1 FROM reactions WHERE message_id=? AND user_id=? AND emoji=?',(r['id'],u['id'],emoji)).fetchone()
 if not old: return web.json_response({'reactions':reactions(r['id'])})
 c.execute('DELETE FROM reactions WHERE message_id=? AND user_id=? AND emoji=?',(r['id'],u['id'],emoji))
 emit_event(r['channel_id'],'reaction.removed',{'message_id':r['id'],'emoji':emoji,'user_id':u['id'],'reactions':reactions(r['id'])})
 return web.json_response({'reactions':reactions(r['id'])})
async def pin(req):
 u=require_user(req); c=connect(); r=c.execute('SELECT * FROM messages WHERE id=?',(req.match_info['id'],)).fetchone()
 if not r: raise HTTPError(404,'message not found')
 allowed(r['channel_id'],u['id']); c.execute('INSERT OR IGNORE INTO pins(message_id,pinned_by,pinned_at) VALUES(?,?,?)',(r['id'],u['id'],now_iso()))
 x=c.execute('SELECT * FROM pins WHERE message_id=?',(r['id'],)).fetchone()
 return web.json_response({'pin':{'message_id':x['message_id'],'pinned_by':x['pinned_by'],'pinned_at':x['pinned_at']}})
async def unpin(req):
 u=require_user(req); c=connect(); r=c.execute('SELECT * FROM messages WHERE id=?',(req.match_info['id'],)).fetchone()
 if not r: raise HTTPError(404,'message not found')
 allowed(r['channel_id'],u['id']); c.execute('DELETE FROM pins WHERE message_id=?',(r['id'],)); return web.json_response({'unpinned':True})
async def pinlist(req):
 u=require_user(req); ch=channel_by_id(req.match_info['id']); can_read(ch['id'],u['id']); n=parse_limit(req); off=decode_cursor(req.query['cursor']) if req.query.get('cursor') else 0
 rows=connect().execute('SELECT p.*,m.* FROM pins p JOIN messages m ON m.id=p.message_id WHERE m.channel_id=? ORDER BY p.message_id DESC LIMIT ? OFFSET ?',(ch['id'],n+1,off)).fetchall()
 return web.json_response({'pins':[{'message':msg_json(x),'pinned_by':x['pinned_by'],'pinned_at':x['pinned_at']} for x in rows[:n]],'next_cursor':encode_cursor(off+n) if len(rows)>n else None})
async def search(req):
 u=require_user(req); q=req.query.get('q','')
 if not q.strip(): raise HTTPError(400,'missing q')
 n=parse_limit(req); off=decode_cursor(req.query['cursor']) if req.query.get('cursor') else 0
 extra=''; args=[u['id'],'%'+q+'%'];
 if req.query.get('workspace_id'): extra=' AND m.channel_id IN (SELECT id FROM channels WHERE workspace_id=?)'; args.append(int(req.query['workspace_id']))
 args += [n+1,off]
 rows=connect().execute("SELECT m.* FROM messages m JOIN channel_members cm ON cm.channel_id=m.channel_id AND cm.user_id=? WHERE m.deleted=0 AND m.body LIKE ?"+extra+" ORDER BY m.id DESC LIMIT ? OFFSET ?",args).fetchall()
 return web.json_response({'results':[msg_json(x) for x in rows[:n]],'next_cursor':encode_cursor(off+n) if len(rows)>n else None})
async def getread(req):
 u=require_user(req); ch=channel_by_id(req.match_info['id']); can_read(ch['id'],u['id']); return web.json_response({'read_state':read_state_for(ch['id'],u['id'])})
async def markread(req):
 u=require_user(req); ch=channel_by_id(req.match_info['id']); can_read(ch['id'],u['id']); d=await read_json(req); eid=int(d.get('last_read_event_id',-1));
 if eid<0: raise HTTPError(400,'invalid event id')
 head=connect().execute('SELECT last_event_id FROM channels WHERE id=?',(ch['id'],)).fetchone()[0]; eid=min(eid,head); c=connect(); c.execute('UPDATE channel_members SET last_read_event_id=MAX(last_read_event_id,?) WHERE channel_id=? AND user_id=?',(eid,ch['id'],u['id']))
 return await getread(req)
_prev_msg_setup=setup
def setup(app):
 _prev_msg_setup(app)
 for method,path,fn in [('post','/api/messages/{id}/reactions',react),('delete','/api/messages/{id}/reactions/{emoji}',unreact),('post','/api/messages/{id}/pin',pin),('delete','/api/messages/{id}/pin',unpin),('get','/api/channels/{id}/pins',pinlist),('get','/api/search',search),('get','/api/channels/{id}/read',getread),('post','/api/channels/{id}/read',markread)]: getattr(app.router,'add_'+method)(path,fn)
