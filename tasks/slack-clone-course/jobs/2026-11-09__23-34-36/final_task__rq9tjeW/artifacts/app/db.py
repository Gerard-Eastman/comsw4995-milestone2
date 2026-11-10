import sqlite3, os
from datetime import datetime, timezone
PATH='/app/data/app.db'
SCHEMA='''
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,username TEXT UNIQUE,password_hash TEXT,display_name TEXT,timezone TEXT DEFAULT 'UTC',avatar_url TEXT DEFAULT '',status_text TEXT DEFAULT '',status_emoji TEXT DEFAULT '',created_at TEXT);
CREATE TABLE IF NOT EXISTS tokens(token TEXT PRIMARY KEY,user_id INTEGER,created_at TEXT);
CREATE TABLE IF NOT EXISTS workspaces(id INTEGER PRIMARY KEY,slug TEXT UNIQUE,name TEXT,owner_id INTEGER,join_mode TEXT DEFAULT 'open',created_at TEXT);
CREATE TABLE IF NOT EXISTS workspace_members(workspace_id INTEGER,user_id INTEGER,role TEXT,joined_at TEXT,PRIMARY KEY(workspace_id,user_id));
CREATE TABLE IF NOT EXISTS channels(id INTEGER PRIMARY KEY,workspace_id INTEGER,name TEXT,is_private INTEGER DEFAULT 0,is_dm INTEGER DEFAULT 0,topic TEXT DEFAULT '',is_archived INTEGER DEFAULT 0,last_event_id INTEGER DEFAULT 0,created_at TEXT,UNIQUE(workspace_id,name));
CREATE TABLE IF NOT EXISTS channel_members(channel_id INTEGER,user_id INTEGER,last_read_event_id INTEGER DEFAULT 0,PRIMARY KEY(channel_id,user_id));\nCREATE TABLE IF NOT EXISTS dm_pairs(user_low INTEGER,user_high INTEGER,channel_id INTEGER,PRIMARY KEY(user_low,user_high));
CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY,channel_id INTEGER,author_id INTEGER,body TEXT,parent_id INTEGER,created_at TEXT,edited_at TEXT,deleted INTEGER DEFAULT 0,mentions TEXT DEFAULT '[]',event_id INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,channel_id INTEGER,event_id INTEGER,kind TEXT,data TEXT,created_at TEXT,UNIQUE(channel_id,event_id));
CREATE TABLE IF NOT EXISTS global_events(id INTEGER PRIMARY KEY,data TEXT,created_at TEXT);
CREATE TABLE IF NOT EXISTS ws_presence(socket_id TEXT,user_id INTEGER,channel_id INTEGER,created_at TEXT,PRIMARY KEY(socket_id,channel_id));
CREATE TABLE IF NOT EXISTS reactions(message_id INTEGER,user_id INTEGER,emoji TEXT,created_at TEXT,PRIMARY KEY(message_id,user_id,emoji));
CREATE TABLE IF NOT EXISTS pins(message_id INTEGER PRIMARY KEY,pinned_by INTEGER,pinned_at TEXT);
CREATE TABLE IF NOT EXISTS files(id INTEGER PRIMARY KEY,uploader_id INTEGER,filename TEXT,content_type TEXT,size INTEGER,data BLOB,created_at TEXT,message_id INTEGER);
CREATE TABLE IF NOT EXISTS groups_tbl(id INTEGER PRIMARY KEY,workspace_id INTEGER,handle TEXT,name TEXT,creator_id INTEGER,user_ids TEXT,UNIQUE(workspace_id,handle));
CREATE TABLE IF NOT EXISTS invitations(code TEXT PRIMARY KEY,workspace_id INTEGER,invited_user_id INTEGER,expires_at TEXT,max_uses INTEGER,uses INTEGER DEFAULT 0,revoked INTEGER DEFAULT 0);
'''
_conn=None
def connect():
 global _conn
 if _conn is None:
  os.makedirs('/app/data',exist_ok=True)
  _conn=sqlite3.connect(PATH,timeout=10,isolation_level=None,check_same_thread=False)
  _conn.row_factory=sqlite3.Row
  _conn.execute('PRAGMA journal_mode=WAL'); _conn.execute('PRAGMA busy_timeout=10000')
 return _conn
def init_db():
 c=connect()
 for s in SCHEMA.split(';'):
  if s.strip(): c.execute(s)
 for col,typ in [('mentions',"TEXT DEFAULT '[]'"),('event_id','INTEGER DEFAULT 0'),('message_id','INTEGER')]:
  try: c.execute('ALTER TABLE messages ADD COLUMN '+col+' '+typ)
  except sqlite3.OperationalError: pass
 try: c.execute('ALTER TABLE groups_tbl ADD COLUMN workspace_id INTEGER')
 except sqlite3.OperationalError: pass
def now_iso(): return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z')
