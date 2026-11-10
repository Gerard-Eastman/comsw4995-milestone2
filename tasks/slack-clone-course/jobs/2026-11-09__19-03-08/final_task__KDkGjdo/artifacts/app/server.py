import argparse,asyncio
from aiohttp import web
import db
from common import error_middleware
import routes_auth,routes_workspaces,routes_channels,routes_messages,ws
def main():
 p=argparse.ArgumentParser(); p.add_argument('--port',type=int,default=8000); p.add_argument('--node-id',type=int,default=0); a=p.parse_args()
 app=web.Application(middlewares=[error_middleware],client_max_size=20*1024*1024); app['node_id']=a.node_id
 async def health(req): return web.json_response({'status':'ok','node_id':a.node_id})
 async def index(req): return web.FileResponse('/app/static/index.html')
 app.router.add_get('/api/health',health); app.router.add_get('/',index); app.router.add_static('/static/','/app/static')
 for mod in (routes_auth,routes_workspaces,routes_channels,routes_messages,ws): mod.setup(app)
 web.run_app(app,host='0.0.0.0',port=a.port)
if __name__=='__main__': main()
