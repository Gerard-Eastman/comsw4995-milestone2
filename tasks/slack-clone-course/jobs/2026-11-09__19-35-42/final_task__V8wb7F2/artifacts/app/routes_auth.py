import re,secrets,hashlib
from aiohttp import web
import db
from common import *

def setup(app):
 async def register(request):
  b=await read_json(request); u=b.get('username'); p=b.get('password')
  if not isinstance(u,str) or not re.fullmatch(r'[A-Za-z0-9_]{1,32}',u) or not isinstance(p,str) or len(p)<8:
   raise HTTPError(400,'invalid registration')
  if db.CONN.execute('SELECT 1 FROM users WHERE username=?',(u,)).fetchone(): raise HTTPError(409,'username already exists')
  c=db.CONN; c.execute('INSERT INTO users(username,password,display_name) VALUES(?,?,?)',(u,hashlib.sha256(p.encode()).hexdigest(),b.get('display_name') or u))
  uid=c.execute('SELECT last_insert_rowid()').fetchone()[0]; tok=secrets.token_urlsafe(24)
  c.execute('INSERT INTO tokens(token,user_id) VALUES(?,?)',(tok,uid))
  return web.json_response({'user':user_to_json(c.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone()),'token':tok},status=201)
 async def login(request):
  b=await read_json(request); u=b.get('username'); p=b.get('password','')
  r=db.CONN.execute('SELECT * FROM users WHERE username=? AND password=?',(u,hashlib.sha256(str(p).encode()).hexdigest())).fetchone()
  if not r: raise HTTPError(401,'invalid credentials')
  tok=secrets.token_urlsafe(24); db.CONN.execute('INSERT INTO tokens(token,user_id) VALUES(?,?)',(tok,r['id']))
  return web.json_response({'user':user_to_json(r),'token':tok})
 async def me(request): return web.json_response({'user':user_to_json(require_user(request))})
 async def profile(request):
  u=require_user(request); b=await read_json(request); allowed={'display_name','timezone','avatar_url','status_text','status_emoji'}
  vals={k:b[k] for k in allowed if k in b}
  if len(str(vals.get('display_name','')))>100: raise HTTPError(400,'invalid profile')
  if vals:
   db.CONN.execute('UPDATE users SET '+','.join(k+'=?' for k in vals)+' WHERE id=?',tuple(vals.values())+(u['id'],))
  r=db.CONN.execute('SELECT * FROM users WHERE id=?',(u['id'],)).fetchone(); broadcast_global({'type':'user.updated','user':user_to_json(r)})
  return web.json_response({'user':user_to_json(r)})
 async def user(request):
  require_user(request)
  try: uid=int(request.match_info['id'])
  except: raise HTTPError(404,'not found')
  r=db.CONN.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone()
  if not r: raise HTTPError(404,'not found')
  return web.json_response({'user':user_to_json(r)})
 app.router.add_post('/api/auth/register',register); app.router.add_post('/api/auth/login',login)
 app.router.add_get('/api/auth/me',me); app.router.add_patch('/api/users/me',profile); app.router.add_get('/api/users/{id}',user)
