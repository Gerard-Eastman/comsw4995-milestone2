import argparse
from aiohttp import web
import db
from common import error_middleware
async def health(r): return web.json_response({'status':'ok','node_id':r.app['node_id']})
def main():
 p=argparse.ArgumentParser(); p.add_argument('--port',type=int); p.add_argument('--node-id',type=int); a=p.parse_args()
 db.init_db(); app=web.Application(middlewares=[error_middleware],client_max_size=20*1024*1024); app['node_id']=a.node_id
 async def root(r): return web.FileResponse('/app/static/index.html')
 app.router.add_get('/',root); app.router.add_static('/static/','/app/static'); app.router.add_get('/api/health',health)
 import routes_auth, routes_workspaces, routes_channels, routes_messages, routes_extras, ws
 routes_auth.setup(app); routes_workspaces.setup(app); routes_channels.setup(app); routes_messages.setup(app); routes_extras.setup(app); ws.setup(app)
 web.run_app(app,host='0.0.0.0',port=a.port)
if __name__=='__main__': main()
