import argparse, os
from aiohttp import web
import db
from common import error_middleware
import routes_auth, routes_workspaces, routes_messages, ws

def build(port,node_id):
    db.init_db()
    app=web.Application(middlewares=[error_middleware],client_max_size=20*1024*1024)
    app["node_id"]=node_id
    async def health(request):
        return web.json_response({"status":"ok","node_id":node_id})
    async def root(request):
        p="/app/static/index.html"
        if os.path.exists(p): return web.FileResponse(p)
        return web.Response(text="Huddle")
    app.router.add_get("/api/health",health)
    app.router.add_get("/",root)
    routes_auth.setup(app)
    routes_workspaces.setup(app)
    routes_messages.setup(app)
    ws.setup(app)
    return app

if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--port",type=int,required=True)
    ap.add_argument("--node-id",type=int,required=True)
    a=ap.parse_args()
    web.run_app(build(a.port,a.node_id),host="0.0.0.0",port=a.port)
