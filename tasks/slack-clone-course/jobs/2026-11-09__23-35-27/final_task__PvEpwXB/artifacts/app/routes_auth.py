import re,hashlib,secrets
from aiohttp import web
from db import conn,now_iso
from common import HTTPError,read_json,require_user,user_to_json
SALT="huddle-local-salt"
def hash_password(pw): return hashlib.sha256((SALT+pw).encode()).hexdigest()
def issue_token(uid):
    t=secrets.token_hex(24); conn.execute("INSERT INTO tokens(token,user_id) VALUES(?,?)",(t,uid)); return t
async def register(request):
    b=await read_json(request); u=b.get("username"); p=b.get("password")
    if not isinstance(u,str) or not re.fullmatch(r"[A-Za-z0-9_]{1,32}",u) or not isinstance(p,str) or len(p)<8:
        raise HTTPError(400,"invalid registration")
    if conn.execute("SELECT 1 FROM users WHERE username=?",(u,)).fetchone(): raise HTTPError(409,"username exists")
    d=b.get("display_name") or u
    if not isinstance(d,str) or len(d)>100: raise HTTPError(400,"invalid display name")
    cur=conn.execute("INSERT INTO users(username,password_hash,display_name,created_at) VALUES(?,?,?,?)",
                     (u,hash_password(p),d,now_iso()))
    row=conn.execute("SELECT * FROM users WHERE id=?",(cur.lastrowid,)).fetchone()
    return web.json_response({"user":user_to_json(row),"token":issue_token(cur.lastrowid)},status=201)
async def login(request):
    b=await read_json(request); u=b.get("username"); p=b.get("password")
    r=conn.execute("SELECT * FROM users WHERE username=? AND password_hash=?",(u,hash_password(p or ""))).fetchone()
    if not r: raise HTTPError(401,"invalid credentials")
    return web.json_response({"user":user_to_json(r),"token":issue_token(r["id"])})
async def me(request):
    uid=require_user(request); r=conn.execute("SELECT * FROM users WHERE id=?",(uid,)).fetchone()
    return web.json_response({"user":user_to_json(r)})
def setup(app):
    app.router.add_post("/api/auth/register",register)
    app.router.add_post("/api/auth/login",login)
    app.router.add_get("/api/auth/me",me)
