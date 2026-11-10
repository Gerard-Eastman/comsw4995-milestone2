import re,secrets
from aiohttp import web
from db import connect,now_iso
from common import HTTPError,read_json,require_user,user_to_json
def setup(app):
 async def register(req):
  d=await read_json(req); name=d.get('username',''); pw=d.get('password','')
  if not isinstance(name,str) or not re.fullmatch(r'[A-Za-z0-9_]{1,32}',name) or not isinstance(pw,str) or len(pw)<8:
   raise HTTPError(400,'invalid registration')
  c=connect()
  if c.execute('SELECT 1 FROM users WHERE username=?',(name,)).fetchone(): c.close(); raise HTTPError(409,'username already exists')
  c.execute('INSERT INTO users(username,password,display_name,created_at) VALUES(?,?,?,?)',(name,pw,d.get('display_name') or name,now_iso()))
  uid=c.execute('SELECT last_insert_rowid()').fetchone()[0]; tok=secrets.token_urlsafe(24)
  c.execute('INSERT INTO tokens VALUES(?,?)',(tok,uid)); u=c.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone(); c.close()
  return web.json_response({'user':user_to_json(u),'token':tok},status=201)
 async def login(req):
  d=await read_json(req); c=connect(); u=c.execute('SELECT * FROM users WHERE username=? AND password=?',(d.get('username'),d.get('password'))).fetchone()
  if not u: c.close(); raise HTTPError(401,'invalid credentials')
  tok=secrets.token_urlsafe(24); c.execute('INSERT INTO tokens VALUES(?,?)',(tok,u['id'],)); c.close()
  return web.json_response({'user':user_to_json(u),'token':tok})
 async def me(req): return web.json_response({'user':user_to_json(require_user(req))})
 app.router.add_post('/api/auth/register',register); app.router.add_post('/api/auth/login',login); app.router.add_get('/api/auth/me',me)
