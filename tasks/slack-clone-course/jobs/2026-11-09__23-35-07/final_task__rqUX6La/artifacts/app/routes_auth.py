import re,secrets,hashlib
from aiohttp import web
import db
from common import HTTPError,read_json,require_user,user_to_json,broadcast_global

def setup(app):
 async def register(req):
  b=await read_json(req); u=b.get('username',''); p=b.get('password','')
  if not isinstance(u,str) or not re.fullmatch(r'[A-Za-z0-9_]{1,32}',u) or not isinstance(p,str) or len(p)<8:
   raise HTTPError(400,'invalid registration')
  if db.CONN.execute('SELECT 1 FROM users WHERE username=?',(u,)).fetchone(): raise HTTPError(409,'username exists')
  now=db.now_iso(); name=b.get('display_name') or u
  cur=db.CONN.execute('INSERT INTO users(username,password,display_name,created_at) VALUES(?,?,?,?)',(u,hashlib.sha256(p.encode()).hexdigest(),name,now))
  uid=cur.lastrowid; tok=secrets.token_urlsafe(24)
  db.CONN.execute('INSERT INTO tokens(token,user_id) VALUES(?,?)',(tok,uid))
  return web.json_response({'user':user_to_json(db.CONN.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone()),'token':tok},status=201)
 async def login(req):
  b=await read_json(req); u=b.get('username',''); p=b.get('password','')
  r=db.CONN.execute('SELECT * FROM users WHERE username=?',(u,)).fetchone()
  if not r or r['password']!=hashlib.sha256(str(p).encode()).hexdigest(): raise HTTPError(401,'invalid credentials')
  tok=secrets.token_urlsafe(24); db.CONN.execute('INSERT INTO tokens(token,user_id) VALUES(?,?)',(tok,r['id']))
  return web.json_response({'user':user_to_json(r),'token':tok})
 async def user_get(req):
  require_user(req)
  try: uid=int(req.match_info['id'])
  except: raise HTTPError(404,'user not found')
  r=db.CONN.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone()
  if not r: raise HTTPError(404,'user not found')
  return web.json_response({'user':user_to_json(r)})
 async def me(req): return web.json_response({'user':user_to_json(require_user(req))})
 async def patch(req):
  u=require_user(req); b=await read_json(req)
  allowed={'display_name','timezone','avatar_url','status_text','status_emoji'}
  vals={k:v for k,v in b.items() if k in allowed}
  if 'timezone' in vals:
   try:
    from zoneinfo import ZoneInfo; ZoneInfo(vals['timezone'])
   except: raise HTTPError(400,'invalid timezone')
  limits={'display_name':80,'status_text':100,'status_emoji':64,'avatar_url':1024,'timezone':128}
  for k,v in vals.items():
   if not isinstance(v,str) or len(v)>limits[k] or (k=='display_name' and not v): raise HTTPError(400,'invalid profile')
  if vals:
   db.CONN.execute('UPDATE users SET '+','.join(k+'=?' for k in vals)+' WHERE id=?',tuple(vals.values())+(u['id'],))
   broadcast_global({'type':'user.updated','user':user_to_json(db.CONN.execute('SELECT * FROM users WHERE id=?',(u['id'],)).fetchone())})
  return web.json_response({'user':user_to_json(db.CONN.execute('SELECT * FROM users WHERE id=?',(u['id'],)).fetchone())})
 app.router.add_post('/api/auth/register',register); app.router.add_post('/api/auth/login',login)
 app.router.add_get('/api/auth/me',me); app.router.add_get('/api/users/{id}',user_get); app.router.add_patch('/api/users/me',patch)
