import sqlite3, os, datetime
PATH='/app/data/app.db'
SCHEMA='''
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,username TEXT UNIQUE,password TEXT,display_name TEXT,timezone TEXT DEFAULT 'UTC',avatar_url TEXT DEFAULT '',status_text TEXT DEFAULT '',status_emoji TEXT DEFAULT '',created_at TEXT);
CREATE TABLE IF NOT EXISTS tokens(token TEXT PRIMARY KEY,user_id INTEGER);
CREATE TABLE IF NOT EXISTS workspaces(id INTEGER PRIMARY KEY,slug TEXT UNIQUE,name TEXT,owner_id INTEGER,join_mode TEXT DEFAULT 'open');
CREATE TABLE IF NOT EXISTS members(workspace_id INTEGER,user_id INTEGER,role TEXT,PRIMARY KEY(workspace_id,user_id));
CREATE TABLE IF NOT EXISTS channels(id INTEGER PRIMARY KEY,workspace_id INTEGER,name TEXT,is_private INTEGER DEFAULT 0,is_dm INTEGER DEFAULT 0,topic TEXT DEFAULT '',is_archived INTEGER DEFAULT 0,created_at TEXT,last_event_id INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS channel_members(channel_id INTEGER,user_id INTEGER,PRIMARY KEY(channel_id,user_id));
CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY,channel_id INTEGER,author_id INTEGER,body TEXT,parent_id INTEGER,created_at TEXT,edited_at TEXT,deleted INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,channel_id INTEGER,event_id INTEGER,kind TEXT,payload TEXT,UNIQUE(channel_id,event_id));
CREATE TABLE IF NOT EXISTS reactions(message_id INTEGER,user_id INTEGER,emoji TEXT,PRIMARY KEY(message_id,user_id,emoji));
CREATE TABLE IF NOT EXISTS pins(message_id INTEGER PRIMARY KEY,pinned_by INTEGER,pinned_at TEXT);
CREATE TABLE IF NOT EXISTS files(id INTEGER PRIMARY KEY,uploader_id INTEGER,filename TEXT,content_type TEXT,size INTEGER,data BLOB,created_at TEXT,message_id INTEGER);
CREATE TABLE IF NOT EXISTS dm_pairs(user_low INTEGER,user_high INTEGER,channel_id INTEGER,PRIMARY KEY(user_low,user_high));
CREATE TABLE IF NOT EXISTS invitations(id INTEGER PRIMARY KEY,workspace_id INTEGER,code TEXT UNIQUE,created_by INTEGER,expires_at TEXT,max_uses INTEGER DEFAULT 1,uses INTEGER DEFAULT 0,target_user_id INTEGER,revoked INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS groups_(id INTEGER PRIMARY KEY,workspace_id INTEGER,handle TEXT,name TEXT,creator_id INTEGER,user_ids TEXT);
'''
def connect():
 c=sqlite3.connect(PATH,timeout=10,isolation_level=None,check_same_thread=False); c.row_factory=sqlite3.Row
 c.execute('PRAGMA journal_mode=WAL'); c.execute('PRAGMA busy_timeout=10000'); return c
def init_db():
 os.makedirs('/app/data',exist_ok=True); c=connect()
 for s in SCHEMA.split(';'):
  if s.strip(): c.execute(s)
 c.execute('CREATE TABLE IF NOT EXISTS global_events(id INTEGER PRIMARY KEY,payload TEXT)')
 c.execute('CREATE TABLE IF NOT EXISTS invitations(id INTEGER PRIMARY KEY,workspace_id INTEGER,code TEXT UNIQUE,created_by INTEGER,expires_at TEXT,max_uses INTEGER DEFAULT 1,uses INTEGER DEFAULT 0,target_user_id INTEGER,revoked INTEGER DEFAULT 0)')
 c.execute('CREATE TABLE IF NOT EXISTS ws_presence(user_id INTEGER PRIMARY KEY)')
 c.execute('CREATE TABLE IF NOT EXISTS dm_pairs(user_low INTEGER,user_high INTEGER,channel_id INTEGER,PRIMARY KEY(user_low,user_high))')
 try: c.execute('ALTER TABLE files ADD COLUMN message_id INTEGER')
 except sqlite3.OperationalError: pass
 c.close()
def now_iso(): return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z')
