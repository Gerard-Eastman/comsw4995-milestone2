import argparse,asyncio
from aiohttp import web
import db
from common import error_middleware
import routes_auth, routes_workspaces, routes_channels, routes_messages, routes_extras
try:
    import ws
except ImportError:
    ws=None
async def health(request):
    return web.json_response({"status":"ok","node_id":request.app["node_id"]})
async def pump(app):
    db.conn.execute("DELETE FROM ws_presence WHERE node_id=?",(app["node_id"],))
    app["event_seq"]=db.conn.execute("SELECT COALESCE(MAX(seq),0) FROM events").fetchone()[0]
    app["broadcast_seq"]=db.conn.execute("SELECT COALESCE(MAX(seq),0) FROM broadcasts").fetchone()[0]
    while True:
        await asyncio.sleep(.2)
def make_app(node):
    app=web.Application(middlewares=[error_middleware],client_max_size=20*1024*1024)
    app["node_id"]=node
    app.router.add_get("/api/health",health)
    app.router.add_get("/",lambda r:web.FileResponse("/app/static/index.html"))
    app.router.add_static("/static/","/app/static")
    routes_auth.setup(app)
    routes_workspaces.setup(app)
    routes_channels.setup(app)
    routes_messages.setup(app)
    routes_extras.setup(app)
    if ws: ws.setup(app)
    async def startup(a):
        a["pump_task"]=asyncio.create_task(pump(a))
    async def cleanup(a):
        a["pump_task"].cancel()
    app.on_startup.append(startup)
    app.on_cleanup.append(cleanup)
    return app
if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--port",type=int,required=True); p.add_argument("--node-id",type=int,required=True)
    x=p.parse_args(); db.init_db()
    web.run_app(make_app(x.node_id),host="0.0.0.0",port=x.port)
