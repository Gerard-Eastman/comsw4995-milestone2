import argparse,asyncio,os
from aiohttp import web
import db
from common import error_middleware,HTTPError,require_user
def main():
 p=argparse.ArgumentParser();p.add_argument('--port',type=int);p.add_argument('--node-id',type=int);a=p.parse_args()
 db.CONN=db.connect(); app=web.Application(middlewares=[error_middleware],client_max_size=20*1024*1024)
 app['node_id']=a.node_id
 async def health(r): return web.json_response({'status':'ok','node_id':a.node_id})
 async def index(r):
  f='/app/static/index.html'
  if os.path.exists(f): return web.FileResponse(f)
  return web.Response(text='Huddle',content_type='text/html')
 app.router.add_get('/api/health',health);app.router.add_get('/',index)
 try:
  import routes_auth,routes_workspaces
  routes_auth.setup(app);routes_workspaces.setup(app)
  try: import routes_channels;routes_channels.setup(app)
  except ImportError: pass
  try: import routes_messages;routes_messages.setup(app)
  except ImportError: pass
  try: import routes_extras;routes_extras.setup(app)
  except ImportError: pass
  try: import ws;ws.setup(app)
  except ImportError: pass
 except Exception: raise
 app.router.add_static('/static','/app/static',show_index=True)
 web.run_app(app,host='0.0.0.0',port=a.port)
if __name__=='__main__': main()
