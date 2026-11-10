import sqlite3, os, json
from datetime import datetime, timezone

PATH='/app/data/app.db'
SCHEMA='''
CREATE TABLE IF NOT EXISTS users(
 id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, password TEXT NOT NULL,
 display_name TEXT NOT NULL, timezone TEXT NOT NULL DEFAULT 'UTC',
 avatar_url TEXT NOT NULL DEFAULT '', status_text TEXT NOT NULL DEFAULT '', status_emoji TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS tokens(token TEXT PRIMARY KEY,user_id INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS workspaces(
 id INTEGER PRIMARY KEY, slug TEXT UNIQUE NOT NULL, name TEXT NOT NULL, owner_id INTEGER NOT NULL,
 join_mode TEXT NOT NULL DEFAULT 'open'
);
CREATE TABLE IF NOT EXISTS workspace_members(workspace_id INTEGER,user_id INTEGER,role TEXT NOT NULL DEFAULT 'member',PRIMARY KEY(workspace_id,user_id));
CREATE TABLE IF NOT EXISTS channels(
 id INTEGER PRIMARY KEY,workspace_id INTEGER NOT NULL,name TEXT NOT NULL,is_private INTEGER NOT NULL DEFAULT 0,
 is_dm INTEGER NOT NULL DEFAULT 0,topic TEXT NOT NULL DEFAULT '',is_archived INTEGER NOT NULL DEFAULT 0,
 created_at TEXT NOT NULL,last_event_id INTEGER NOT NULL DEFAULT 0,
 UNIQUE(workspace_id,name)
);
CREATE TABLE IF NOT EXISTS channel_members(channel_id INTEGER,user_id INTEGER,joined_at TEXT,PRIMARY KEY(channel_id,user_id));
CREATE TABLE IF NOT EXISTS messages(
 id INTEGER PRIMARY KEY,channel_id INTEGER NOT NULL,author_id INTEGER NOT NULL,body TEXT NOT NULL,
 parent_id INTEGER,created_at TEXT NOT NULL,edited_at TEXT,deleted INTEGER NOT NULL DEFAULT 0,mentions TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS reactions(message_id INTEGER,user_id INTEGER,emoji TEXT,PRIMARY KEY(message_id,user_id,emoji));
CREATE TABLE IF NOT EXISTS pins(message_id INTEGER PRIMARY KEY,pinned_by INTEGER,pinned_at TEXT);
CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT,channel_id INTEGER,event_id INTEGER,payload TEXT);
CREATE TABLE IF NOT EXISTS broadcasts(seq INTEGER PRIMARY KEY AUTOINCREMENT,payload TEXT);
CREATE TABLE IF NOT EXISTS ws_presence(conn_id TEXT PRIMARY KEY,node_id INTEGER,user_id INTEGER);
CREATE TABLE IF NOT EXISTS read_state(user_id INTEGER,channel_id INTEGER,last_read_event_id INTEGER DEFAULT 0,PRIMARY KEY(user_id,channel_id));
'''
CONN=None
def connect():
 c=sqlite3.connect(PATH,timeout=10,isolation_level=None,check_same_thread=False)
 c.execute('PRAGMA journal_mode=WAL'); c.execute('PRAGMA busy_timeout=10000'); c.row_factory=sqlite3.Row
 return c
def init_db():
 global CONN
 os.makedirs('/app/data',exist_ok=True); CONN=connect()
 for s in SCHEMA.split(';'):
  if s.strip(): CONN.execute(s)
def now_iso():
 return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z')
def emit_event(channel_id,kind,data):
 c=CONN
 c.execute('BEGIN IMMEDIATE')
 try:
  c.execute('UPDATE channels SET last_event_id=last_event_id+1 WHERE id=?',(channel_id,))
  r=c.execute('SELECT last_event_id FROM channels WHERE id=?',(channel_id,)).fetchone()
  if not r: raise ValueError('channel')
  eid=r[0]; p={'type':kind,'event_id':eid,'channel_id':channel_id}; p.update(data)
  c.execute('INSERT INTO events(channel_id,event_id,payload) VALUES(?,?,?)',(channel_id,eid,json.dumps(p)))
  c.execute('COMMIT'); return eid
 except:
  c.execute('ROLLBACK'); raise
def broadcast_global(payload):
 CONN.execute('INSERT INTO broadcasts(payload) VALUES(?)',(json.dumps(payload),))
