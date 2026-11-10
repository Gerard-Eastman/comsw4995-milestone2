import secrets,re
from aiohttp import web
from db import connect,now_iso
from common import *
def setup(app):
 async def register(q):
  d=await read_json(q); u=d.get('username',''); p=d.get('password','')
  if not re.fullmatch(r'[A-Za-z0-9_]{1,32}',u) or len(p)<8: raise HTTPError(400,'invalid credentials')
  c=connect()
  try: c.execute('INSERT INTO users(username,password,display_name,created_at) VALUES(?,?,?,?)',(u,p,d.get('display_name') or u,now_iso()))
  except: raise HTTPError(409,'username already exists')
  r=c.execute('SELECT * FROM users WHERE username=?',(u,)).fetchone(); t=secrets.token_urlsafe(24); c.execute('INSERT INTO tokens VALUES(?,?)',(t,r['id']))
  return web.json_response({'user':user_to_json(r),'token':t},status=201)
 async def login(q):
  d=await read_json(q); r=connect().execute('SELECT * FROM users WHERE username=? AND password=?',(d.get('username'),d.get('password'))).fetchone()
  if not r: raise HTTPError(401,'wrong credentials')
  t=secrets.token_urlsafe(24); connect().execute('INSERT INTO tokens VALUES(?,?)',(t,r['id']))
  return web.json_response({'user':user_to_json(r),'token':t})
 async def me(q): return web.json_response({'user':user_to_json(require_user(q))})
 app.router.add_post('/api/auth/register',register); app.router.add_post('/api/auth/login',login); app.router.add_get('/api/auth/me',me)
