import re,secrets
from aiohttp import web
import db
from common import HTTPError,read_json,require_user,user_to_json,broadcast_global

def setup(app):
    async def register(request):
        b=await read_json(request); u=b.get("username",""); p=b.get("password","")
        if not re.fullmatch(r"[A-Za-z0-9_]{1,32}",u) or not isinstance(p,str) or len(p)<8: raise HTTPError(400,"invalid registration")
        c=db.get_conn()
        if c.execute("SELECT 1 FROM users WHERE username=?",(u,)).fetchone(): raise HTTPError(409,"username exists")
        now=db.now_iso(); cur=c.execute("INSERT INTO users(username,password,display_name,created_at) VALUES(?,?,?,?)",(u,p,b.get("display_name") or u,now))
        r=c.execute("SELECT * FROM users WHERE id=?",(cur.lastrowid,)).fetchone(); t=secrets.token_urlsafe(24)
        c.execute("INSERT INTO tokens(token,user_id) VALUES(?,?)",(t,r["id"]))
        return web.json_response({"user":user_to_json(r),"token":t},status=201)
    async def login(request):
        b=await read_json(request); r=db.get_conn().execute("SELECT * FROM users WHERE username=? AND password=?",(b.get("username",""),b.get("password",""))).fetchone()
        if not r: raise HTTPError(401,"invalid credentials")
        t=secrets.token_urlsafe(24); db.get_conn().execute("INSERT INTO tokens(token,user_id) VALUES(?,?)",(t,r["id"]))
        return web.json_response({"user":user_to_json(r),"token":t})
    async def me(request): return web.json_response({"user":user_to_json(require_user(request))})
    async def profile(request):
        r=require_user(request); b=await read_json(request); allowed={"display_name","timezone","avatar_url","status_text","status_emoji"}
        vals={k:b[k] for k in allowed if k in b}
        if any(not isinstance(v,str) or len(v)>250 for v in vals.values()): raise HTTPError(400,"invalid profile")
        if vals:
            c=db.get_conn(); c.execute("UPDATE users SET "+",".join(k+"=?" for k in vals)+" WHERE id=?",tuple(vals.values())+(r["id"],))
            r=c.execute("SELECT * FROM users WHERE id=?",(r["id"],)).fetchone()
            broadcast_global({"type":"user.updated","user":user_to_json(r)})
        return web.json_response({"user":user_to_json(r)})
    app.router.add_post("/api/auth/register",register); app.router.add_post("/api/auth/login",login)
    app.router.add_get("/api/auth/me",me); app.router.add_patch("/api/users/me",profile)

def workspace_json(r):
    return {"id":r["id"],"slug":r["slug"],"name":r["name"],"owner_id":r["owner_id"],"join_mode":r["join_mode"]}
