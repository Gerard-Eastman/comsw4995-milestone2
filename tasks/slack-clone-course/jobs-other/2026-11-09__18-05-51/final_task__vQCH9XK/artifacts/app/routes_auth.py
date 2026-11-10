import secrets,re,hashlib
from aiohttp import web
from db import connect,now_iso
from common import *
def setup(app):
 async def register(r):
  d=await read_json(r); u=d.get('username','');pw=d.get('password','')
  if not re.fullmatch(r'[A-Za-z0-9_]{1,32}',u) or len(pw)<8: raise HTTPError(400,'invalid registration')
  c=connect()
  try:
   c.execute('INSERT INTO users(username,password,display_name,created_at) VALUES(?,?,?,?)',(u,hashlib.sha256(pw.encode()).hexdigest(),d.get('display_name') or u,now_iso()))
  except: c.close();raise HTTPError(409,'username exists')
  uid=c.execute('SELECT last_insert_rowid()').fetchone()[0];t=secrets.token_urlsafe(24);c.execute('INSERT INTO tokens VALUES(?,?)',(t,uid));x=c.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone();c.close()
  return web.json_response({'user':user_to_json(x),'token':t},status=201)
 async def login(r):
  d=await read_json(r);c=connect();x=c.execute('SELECT * FROM users WHERE username=? AND password=?',(d.get('username'),hashlib.sha256(d.get('password','').encode()).hexdigest())).fetchone()
  if not x:c.close();raise HTTPError(401,'wrong credentials')
  t=secrets.token_urlsafe(24);c.execute('INSERT INTO tokens VALUES(?,?)',(t,x['id']));c.close();return web.json_response({'user':user_to_json(x),'token':t})
 async def me(r): return web.json_response({'user':user_to_json(require_user(r))})
 app.router.add_post('/api/auth/register',register);app.router.add_post('/api/auth/login',login);app.router.add_get('/api/auth/me',me)
