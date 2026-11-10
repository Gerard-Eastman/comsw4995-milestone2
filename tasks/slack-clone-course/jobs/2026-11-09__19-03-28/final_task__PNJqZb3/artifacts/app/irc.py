import asyncio, json, server
clients = {}
state = {}
def send(w, line):
    w.write((line + "\r\n").encode())
    return w.drain()
def row_channel(name):
    if not name.startswith('#') or name[1:].count('/') != 1: return None
    slug, cname = name[1:].split('/')
    return server.con.execute("""SELECT c.*,w.slug,w.owner_id FROM channels c JOIN workspaces w ON w.id=c.workspace_id
      WHERE w.slug=? AND c.name=? AND c.is_dm=0""",(slug,cname)).fetchone()
def cname(c): return '#'+c['slug']+'/'+c['name']
def members(c):
    return server.con.execute("""SELECT u.* FROM users u JOIN cmembers m ON m.user_id=u.id
      WHERE m.channel_id=? ORDER BY u.username""",(c['id'],)).fetchall()
async def send_names(w,n,c):
    names=' '.join(x['username'] for x in members(c))
    await send(w,f':huddle 353 {n} = {cname(c)} :{names}')
    await send(w,f':huddle 366 {n} {cname(c)} :End of /NAMES list')
async def event_pump():
    last=server.con.execute('SELECT COALESCE(MAX(seq),0) FROM events').fetchone()[0]
    while True:
        try:
            for e in server.con.execute('SELECT * FROM events WHERE seq>? ORDER BY seq',(last,)):
                last=e['seq']; p=json.loads(e['payload'])
                if p.get('type')!='message.created': continue
                m=p.get('message') or {}; mid=m.get('id'); c=server.con.execute(
                    'SELECT c.*,w.slug FROM channels c JOIN workspaces w ON w.id=c.workspace_id WHERE c.id=?',
                    (p['channel_id'],)).fetchone()
                if not c: continue
                au=server.con.execute('SELECT username FROM users WHERE id=?',(m.get('author_id'),)).fetchone()
                if not au: continue
                line=f':{au["username"]}!{au["username"]}@huddle PRIVMSG {cname(c)} :{str(m.get("body","")).replace(chr(10)," ")}'
                for w,st in list(state.items()):
                    if c['id'] in st['joined'] and mid not in st['own']:
                        try: await send(w,line)
                        except: pass
        except Exception: pass
        await asyncio.sleep(.05)
async def client(reader,writer):
    nick='*'; user=None; token=None; registered=False
    joined=set(); own=set(); state[writer]={'joined':joined,'own':own}
    try:
      while (raw:=await reader.readline()):
        z=raw.decode(errors='ignore').strip('\r\n'); q=z.split(); cmd=q[0].upper() if q else ''
        if cmd=='PASS': token=q[1] if len(q)>1 else ''
        elif cmd=='NICK':
            n=q[1] if len(q)>1 else '*'
            if n.lower() in clients and clients[n.lower()] is not writer:
                await send(writer,f':huddle 433 * {n} :Nickname is already in use'); continue
            if nick.lower() in clients and clients[nick.lower()] is writer: clients.pop(nick.lower(),None)
            nick=n
            if registered: clients[nick.lower()]=writer
        elif cmd=='USER':
            x=server.con.execute('SELECT u.* FROM users u JOIN tokens t ON t.user_id=u.id WHERE t.token=?',(token,)).fetchone() if token else None
            if not x: await send(writer,f':huddle 464 {nick} :Password incorrect'); return
            user=x; registered=True; clients[nick.lower()]=writer
            for n in ('001','002','003','004','005'): await send(writer,f':huddle {n} {nick} :Welcome to Huddle')
            await send(writer,f':huddle 422 {nick} :MOTD File is missing')
        elif cmd=='PING': await send(writer,':huddle PONG huddle :'+(q[1] if len(q)>1 else ''))
        elif cmd=='PONG': pass
        elif cmd=='QUIT': return
        elif not registered: await send(writer,f':huddle 451 {nick} :You have not registered')
        elif cmd=='JOIN':
            name=q[1] if len(q)>1 else ''; c=row_channel(name)
            if not c or (c['is_private'] and not server.con.execute('SELECT 1 FROM cmembers WHERE channel_id=? AND user_id=?',(c['id'],user['id'])).fetchone()):
                await send(writer,f':huddle 403 {nick} {name} :No such channel'); continue
            server.con.execute('INSERT OR IGNORE INTO members VALUES(?,?,?)',(c['workspace_id'],user['id'],'member'))
            server.con.execute('INSERT OR IGNORE INTO cmembers VALUES(?,?)',(c['id'],user['id']))
            joined.add(c['id']); await send(writer,f':{nick}!{user["username"]}@huddle JOIN {name}')
            if c['topic']: await send(writer,f':huddle 332 {nick} {name} :{c["topic"]}')
            else: await send(writer,f':huddle 331 {nick} {name} :No topic is set')
            await send_names(writer,nick,c)
        elif cmd=='NAMES':
            c=row_channel(q[1] if len(q)>1 else '')
            if c: await send_names(writer,nick,c)
        elif cmd=='TOPIC':
            c=row_channel(q[1] if len(q)>1 else '')
            if c:
                if c['topic']: await send(writer,f':huddle 332 {nick} {q[1]} :{c["topic"]}')
                else: await send(writer,f':huddle 331 {nick} {q[1]} :No topic is set')
        elif cmd=='WHO':
            c=row_channel(q[1] if len(q)>1 else '')
            if c:
                for x in members(c): await send(writer,f':huddle 352 {nick} {q[1]} huddle huddle {x["username"]} H :0 {x["display_name"]}')
                await send(writer,f':huddle 315 {nick} {q[1]} :End of /WHO list')
        elif cmd=='LIST':
            await send(writer,f':huddle 321 {nick} Channel :Users Name')
            for c in server.con.execute('SELECT c.*,w.slug FROM channels c JOIN workspaces w ON w.id=c.workspace_id WHERE c.is_dm=0'):
                await send(writer,f':huddle 322 {nick} {cname(c)} 0 :{c["topic"] or ""}')
            await send(writer,f':huddle 323 {nick} :End of /LIST')
        elif cmd=='MODE':
            target=q[1] if len(q)>1 else ''
            if target.startswith('#'): await send(writer,f':huddle 324 {nick} {target} +')
            else: await send(writer,f':huddle 221 {nick} +')
        elif cmd=='PRIVMSG':
            name=q[1] if len(q)>1 else ''; c=row_channel(name)
            if not c or c['id'] not in joined:
                await send(writer,f":huddle 442 {nick} {name} :You're not on that channel"); continue
            text=z.split(' :',1)[1] if ' :' in z else ''
            server.con.execute('INSERT INTO messages(channel_id,author_id,body,created_at) VALUES(?,?,?,server.now())' if False else 'INSERT INTO messages(channel_id,author_id,body,created_at) VALUES(?,?,?,datetime("now"))',(c['id'],user['id'],text))
            mid=server.con.execute('SELECT last_insert_rowid()').fetchone()[0]; own.add(mid)
            r=server.con.execute('SELECT * FROM messages WHERE id=?',(mid,)).fetchone()
            server.emit(c['id'],'message.created',{'message':server.msg(r)})
        else: await send(writer,f':huddle 421 {nick} {cmd} :Unknown command')
    finally:
      clients.pop(nick.lower(),None); state.pop(writer,None); writer.close()
async def main():
    server.init_db()
    asyncio.create_task(event_pump())
    srv=await asyncio.start_server(client,'0.0.0.0',6667)
    async with srv: await srv.serve_forever()
asyncio.run(main())
