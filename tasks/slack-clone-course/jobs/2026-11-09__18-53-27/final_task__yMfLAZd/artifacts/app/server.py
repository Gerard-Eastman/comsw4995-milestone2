import argparse, os
from aiohttp import web
import db
from common import error_middleware
import routes_auth, routes_workspaces, routes_channels, routes_messages, ws

def build_app(node_id):
    app=web.Application(middlewares=[error_middleware],client_max_size=20*1024*1024)
    app["node_id"]=node_id
    async def health(request):
        return web.json_response({"status":"ok","node_id":node_id})
    async def index(request):
        return web.Response(text="""<!doctype html><html><head><title>Huddle</title></head><body><h1>Huddle</h1></body></html>""",content_type="text/html")
    app.router.add_get("/api/health",health)
    app.router.add_get("/",index)
    routes_auth.setup(app)
    routes_workspaces.setup(app)
    routes_channels.setup(app)
    routes_messages.setup(app)
    ws.setup(app)
    return app

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--port",type=int,required=True)
    p.add_argument("--node-id",type=int,required=True)
    a=p.parse_args()
    db.init_db()
    web.run_app(build_app(a.node_id),host="0.0.0.0",port=a.port)
