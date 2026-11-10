import re,hashlib,secrets
from aiohttp import web
import db
from common import *
def pw(x): return hashlib.sha256(('huddle:'+x).encode()).hexdigest()
def setup(app):
 async def register(q):
  x=await read_json(q); u=x.get('username'); p=x.get('password')
  if not isinstance(u,str) or not re.fullmatch(r'[A-Za-z0-9_]{1,32}',u) or not isinstance(p,str) or len(p)<8: raise HTTPError(400,'invalid credentials')
  if db.conn.execute('SELECT 1 FROM users WHERE username=?',(u,)).fetchone(): raise HTTPError(409,'username exists')
  t=db.now_iso(); cur=db.conn.execute('INSERT INTO users(username,password_hash,display_name,created_at) VALUES(?,?,?,?)',(u,pw(p),x.get('display_name') or u,t))
  r=db.conn.execute('SELECT * FROM users WHERE id=?',(cur.lastrowid,)).fetchone(); tok=secrets.token_hex(24); db.conn.execute('INSERT INTO tokens VALUES(?,?,?)',(tok,r['id'],t))
  return web.json_response({'user':user_to_json(r),'token':tok},status=201)
 async def login(q):
  x=await read_json(q); r=db.conn.execute('SELECT * FROM users WHERE username=? AND password_hash=?',(x.get('username'),pw(x.get('password','')))).fetchone()
  if not r: raise HTTPError(401,'invalid credentials')
  tok=secrets.token_hex(24); db.conn.execute('INSERT INTO tokens VALUES(?,?,?)',(tok,r['id'],db.now_iso()))
  return web.json_response({'user':user_to_json(r),'token':tok})
 async def me(q):
  uid=require_user(q); return web.json_response({'user':user_to_json(db.conn.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone())})
 app.router.add_post('/api/auth/register',register); app.router.add_post('/api/auth/login',login); app.router.add_get('/api/auth/me',me)
