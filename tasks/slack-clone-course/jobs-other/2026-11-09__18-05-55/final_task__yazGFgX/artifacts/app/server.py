import argparse
from aiohttp import web
from db import init_db
from common import error_middleware
import routes_auth,routes_workspaces,routes_channels,routes_messages,routes_extras,ws
def main():
 p=argparse.ArgumentParser(); p.add_argument('--port',type=int); p.add_argument('--node-id',type=int); a=p.parse_args(); init_db()
 app=web.Application(middlewares=[error_middleware],client_max_size=20*1024*1024)
 async def health(q): return web.json_response({'status':'ok','node_id':a.node_id})
 app.router.add_get('/api/health',health)
 app.router.add_get('/',lambda q:web.FileResponse('/app/static/index.html'))
 app.router.add_static('/static/','/app/static')
 routes_auth.setup(app); routes_workspaces.setup(app); routes_channels.setup(app); routes_messages.setup(app); routes_extras.setup(app); ws.setup(app)
 web.run_app(app,host='0.0.0.0',port=a.port)
if __name__=='__main__': main()
