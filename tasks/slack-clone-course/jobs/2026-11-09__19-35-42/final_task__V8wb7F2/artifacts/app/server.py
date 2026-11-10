import argparse,sys,os
from aiohttp import web
import db
from common import error_middleware
import routes_auth,routes_workspaces,routes_channels,routes_messages,ws

def main():
 p=argparse.ArgumentParser(); p.add_argument('--port',type=int,required=True); p.add_argument('--node-id',type=int,required=True)
 a=p.parse_args(); db.init_db()
 app=web.Application(middlewares=[error_middleware],client_max_size=20*1024*1024)
 app['node_id']=a.node_id
 async def health(request): return web.json_response({'status':'ok','node_id':a.node_id})
 app.router.add_get('/api/health',health)
 routes_auth.setup(app); routes_workspaces.setup(app); routes_channels.setup(app); routes_messages.setup(app); ws.setup(app)
 async def index(request):
  path='/app/static/index.html'
  if os.path.exists(path): return web.FileResponse(path)
  return web.Response(text='Huddle',content_type='text/html')
 app.router.add_get('/',index)
 web.run_app(app,host='0.0.0.0',port=a.port)
if __name__=='__main__': main()
