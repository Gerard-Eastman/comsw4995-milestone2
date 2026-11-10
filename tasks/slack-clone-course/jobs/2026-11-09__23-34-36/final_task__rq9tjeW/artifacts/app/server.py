import argparse
from aiohttp import web
from db import init_db
from common import error_middleware
from routes_auth import setup as auth_setup
from routes_workspaces import setup as workspace_setup
from routes_channels import setup as ch_setup
from routes_messages import setup as msg_setup
from ws import setup as websocket_setup
from routes_extras import setup as extras_setup
async def health(req): return web.json_response({'status':'ok','node_id':req.app['node_id']})
def build(node):
 app=web.Application(middlewares=[error_middleware],client_max_size=20*1024*1024); app['node_id']=node
 app.router.add_get('/api/health',health); app.router.add_get('/',lambda req:web.FileResponse('/app/static/index.html')); app.router.add_static('/static','/app/static'); auth_setup(app); workspace_setup(app); websocket_setup(app); ch_setup(app); msg_setup(app); extras_setup(app)
 return app
if __name__=='__main__':
 p=argparse.ArgumentParser(); p.add_argument('--port',type=int); p.add_argument('--node-id',type=int); a=p.parse_args()
 init_db(); web.run_app(build(a.node_id),host='0.0.0.0',port=a.port)
