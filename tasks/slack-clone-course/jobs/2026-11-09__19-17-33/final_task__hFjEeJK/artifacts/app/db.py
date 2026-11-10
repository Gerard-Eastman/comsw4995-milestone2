import sqlite3, os, datetime
DB='/app/data/app.db'
SCHEMA='''
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,username TEXT UNIQUE,password TEXT,display_name TEXT,timezone TEXT DEFAULT 'UTC',avatar_url TEXT DEFAULT '',status_text TEXT DEFAULT '',status_emoji TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS tokens(token TEXT PRIMARY KEY,user_id INTEGER);
CREATE TABLE IF NOT EXISTS workspaces(id INTEGER PRIMARY KEY,slug TEXT UNIQUE,name TEXT,owner_id INTEGER,join_mode TEXT DEFAULT 'open');
CREATE TABLE IF NOT EXISTS workspace_members(workspace_id INTEGER,user_id INTEGER,role TEXT DEFAULT 'member',PRIMARY KEY(workspace_id,user_id));
CREATE TABLE IF NOT EXISTS channels(id INTEGER PRIMARY KEY,workspace_id INTEGER,name TEXT,is_private INTEGER DEFAULT 0,is_dm INTEGER DEFAULT 0,topic TEXT DEFAULT '',is_archived INTEGER DEFAULT 0,created_at TEXT,last_event_id INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS channel_members(channel_id INTEGER,user_id INTEGER,PRIMARY KEY(channel_id,user_id));
CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY,channel_id INTEGER,author_id INTEGER,body TEXT,parent_id INTEGER,created_at TEXT,edited_at TEXT,deleted INTEGER DEFAULT 0,mentions TEXT DEFAULT '[]');
CREATE TABLE IF NOT EXISTS reactions(message_id INTEGER,user_id INTEGER,emoji TEXT,created_at TEXT,PRIMARY KEY(message_id,user_id,emoji));
CREATE TABLE IF NOT EXISTS files(id INTEGER PRIMARY KEY,uploader_id INTEGER,filename TEXT,content_type TEXT,size INTEGER,created_at TEXT,message_id INTEGER);
CREATE TABLE IF NOT EXISTS dm_pairs(user_low INTEGER,user_high INTEGER,channel_id INTEGER,PRIMARY KEY(user_low,user_high));
CREATE TABLE IF NOT EXISTS groups(id INTEGER PRIMARY KEY,workspace_id INTEGER,handle TEXT,name TEXT,created_by INTEGER,UNIQUE(workspace_id,handle));
CREATE TABLE IF NOT EXISTS group_members(group_id INTEGER,user_id INTEGER,PRIMARY KEY(group_id,user_id));
CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT,channel_id INTEGER,event_id INTEGER,payload TEXT);
CREATE TABLE IF NOT EXISTS broadcasts(seq INTEGER PRIMARY KEY AUTOINCREMENT,payload TEXT);
CREATE TABLE IF NOT EXISTS ws_presence(conn_id TEXT PRIMARY KEY,node_id INTEGER,user_id INTEGER);
CREATE TABLE IF NOT EXISTS pins(message_id INTEGER PRIMARY KEY,pinned_by INTEGER,pinned_at TEXT);
CREATE TABLE IF NOT EXISTS read_state(user_id INTEGER,channel_id INTEGER,last_read_event_id INTEGER DEFAULT 0,PRIMARY KEY(user_id,channel_id));
'''
_conn=None
def connect():
 global _conn
 if _conn is None:
  os.makedirs('/app/data',exist_ok=True)
  _conn=sqlite3.connect(DB,timeout=10,isolation_level=None,check_same_thread=False)
  _conn.row_factory=sqlite3.Row
  _conn.execute('PRAGMA journal_mode=WAL'); _conn.execute('PRAGMA busy_timeout=10000')
 return _conn
def init_db():
 c=connect()
 for s in SCHEMA.split(';'):
  if s.strip(): c.execute(s)
def now_iso():
 return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z')
