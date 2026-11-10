import re, hashlib, secrets
from aiohttp import web
from db import connect, now_iso
from common import HTTPError, read_json, require_user, user_to_json
def pw(s): return hashlib.sha256(s.encode()).hexdigest()
async def register(req):
 d=await read_json(req); u=d.get('username'); p=d.get('password')
 if not isinstance(u,str) or not re.fullmatch(r'[A-Za-z0-9_]{1,32}',u) or not isinstance(p,str) or len(p)<8: raise HTTPError(400,'invalid registration')
 c=connect()
 if c.execute('SELECT 1 FROM users WHERE username=?',(u,)).fetchone(): raise HTTPError(409,'username exists')
 t=secrets.token_urlsafe(24); name=d.get('display_name') or u
 c.execute('INSERT INTO users(username,password_hash,display_name,created_at) VALUES(?,?,?,?)',(u,pw(p),name,now_iso()))
 uid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
 c.execute('INSERT INTO tokens(token,user_id,created_at) VALUES(?,?,?)',(t,uid,now_iso()))
 return web.json_response({'user':user_to_json(c.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone()),'token':t},status=201)
async def login(req):
 d=await read_json(req); c=connect(); r=c.execute('SELECT * FROM users WHERE username=?',(d.get('username'),)).fetchone()
 if not r or not isinstance(d.get('password'),str) or pw(d['password'])!=r['password_hash']: raise HTTPError(401,'invalid credentials')
 t=secrets.token_urlsafe(24); c.execute('INSERT INTO tokens(token,user_id,created_at) VALUES(?,?,?)',(t,r['id'],now_iso()))
 return web.json_response({'user':user_to_json(r),'token':t})
async def me(req): return web.json_response({'user':user_to_json(require_user(req))})
def setup(app):
 app.router.add_post('/api/auth/register',register); app.router.add_post('/api/auth/login',login); app.router.add_get('/api/auth/me',me)
