from aiohttp import web
from db import connect,now_iso
from common import *
def setup(app):
 def access(c,u,ch):
  return c.execute('SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?',(ch['id'],u['id'])).fetchone() or c.execute('SELECT 1 FROM workspace_members WHERE workspace_id=? AND user_id=?',(ch['workspace_id'],u['id'])).fetchone()
 async def create(req):
  u=require_user(req); d=await read_json(req); c=connect(); ch=c.execute('SELECT * FROM channels WHERE id=?',(req.match_info['id'],)).fetchone()
  if not ch: raise HTTPError(404,'not found')
  if not access(c,u,ch): raise HTTPError(403,'forbidden')
  body=d.get('body')
  if not isinstance(body,str) or not body.strip(): raise HTTPError(400,'empty body')
  if ch['is_archived']: raise HTTPError(423,'channel archived')
  pid=d.get('parent_id'); c.execute('INSERT INTO messages(channel_id,author_id,body,parent_id,created_at) VALUES(?,?,?,?,?)',(ch['id'],u['id'],body,pid,now_iso()))
  mid=c.execute('SELECT last_insert_rowid()').fetchone()[0]; r=c.execute('SELECT * FROM messages WHERE id=?',(mid,)).fetchone(); m=message_json(c,r); c.close()
  emit_event(ch['id'],'message.reply' if pid else 'message.created',{'message':m}); return web.json_response({'message':m},status=201)
 async def listing(req):
  u=require_user(req); c=connect(); ch=c.execute('SELECT * FROM channels WHERE id=?',(req.match_info['id'],)).fetchone()
  if not ch: raise HTTPError(404,'not found')
  if not access(c,u,ch): raise HTTPError(403,'forbidden')
  lim=parse_limit(req); k=decode_cursor(req.query['cursor']) if req.query.get('cursor') else None
  q='SELECT * FROM messages WHERE channel_id=? AND parent_id IS NULL AND deleted=0'
  args=[ch['id']]
  if k is not None:q+=' AND id<?';args.append(k)
  q+=' ORDER BY id DESC LIMIT ?';args.append(lim+1); rows=c.execute(q,args).fetchall(); more=len(rows)>lim; rows=rows[:lim]; out=[message_json(c,x) for x in rows]; c.close()
  return web.json_response({'messages':out,'next_cursor':encode_cursor(rows[-1]['id']) if more else None})
 async def replies(req):
  u=require_user(req); c=connect(); p=c.execute('SELECT * FROM messages WHERE id=? AND deleted=0',(req.match_info['id'],)).fetchone()
  if not p: raise HTTPError(404,'not found')
  lim=parse_limit(req); rows=c.execute('SELECT * FROM messages WHERE parent_id=? AND deleted=0 ORDER BY id ASC LIMIT ?',(p['id'],lim+1)).fetchall(); more=len(rows)>lim; rows=rows[:lim]; out=[message_json(c,x) for x in rows]; c.close()
  return web.json_response({'replies':out,'next_cursor':encode_cursor(rows[-1]['id']) if more else None})
 async def edit(req):
  u=require_user(req); c=connect(); r=c.execute('SELECT m.*,w.owner_id FROM messages m JOIN channels ch ON ch.id=m.channel_id JOIN workspaces w ON w.id=ch.workspace_id WHERE m.id=?',(req.match_info['id'],)).fetchone()
  if not r: raise HTTPError(404,'not found')
  if r['author_id']!=u['id']: raise HTTPError(403,'forbidden')
  if r['deleted']: raise HTTPError(409,'message deleted')
  d=await read_json(req); body=d.get('body')
  if not isinstance(body,str) or not body.strip(): raise HTTPError(400,'empty body')
  if c.execute('SELECT is_archived FROM channels WHERE id=?',(r['channel_id'],)).fetchone()[0]: raise HTTPError(423,'channel archived')
  t=now_iso(); c.execute('UPDATE messages SET body=?,edited_at=? WHERE id=?',(body,t,r['id'])); r=c.execute('SELECT * FROM messages WHERE id=?',(r['id'],)).fetchone(); m=message_json(c,r); c.close(); emit_event(r['channel_id'],'message.updated',{'message':m}); return web.json_response({'message':m})
 async def delete(req):
  u=require_user(req); c=connect(); r=c.execute('SELECT m.*,w.owner_id FROM messages m JOIN channels ch ON ch.id=m.channel_id JOIN workspaces w ON w.id=ch.workspace_id WHERE m.id=?',(req.match_info['id'],)).fetchone()
  if not r: raise HTTPError(404,'not found')
  if r['author_id']!=u['id'] and r['owner_id']!=u['id']: raise HTTPError(403,'forbidden')
  if not r['deleted']: c.execute('UPDATE messages SET deleted=1 WHERE id=?',(r['id'],)); c.close(); emit_event(r['channel_id'],'message.deleted',{'message_id':r['id']})
  else:c.close()
  return web.json_response({'deleted':True})
 async def react(req):
  u=require_user(req); d=await read_json(req); c=connect(); r=c.execute('SELECT * FROM messages WHERE id=? AND deleted=0',(req.match_info['id'],)).fetchone()
  if not r: raise HTTPError(404,'not found')
  c.execute('INSERT OR IGNORE INTO reactions VALUES(?,?,?)',(r['id'],u['id'],d.get('emoji',''))); c.close(); return web.json_response({'reactions':[]})
 async def unreact(req):
  u=require_user(req); c=connect(); c.execute('DELETE FROM reactions WHERE message_id=? AND user_id=? AND emoji=?',(req.match_info['id'],u['id'],req.match_info['emoji'])); c.close(); return web.json_response({'reactions':[]})
 app.router.add_post('/api/channels/{id}/messages',create); app.router.add_get('/api/channels/{id}/messages',listing); app.router.add_get('/api/messages/{id}/replies',replies); app.router.add_patch('/api/messages/{id}',edit); app.router.add_delete('/api/messages/{id}',delete); app.router.add_post('/api/messages/{id}/reactions',react); app.router.add_delete('/api/messages/{id}/reactions/{emoji}',unreact)
