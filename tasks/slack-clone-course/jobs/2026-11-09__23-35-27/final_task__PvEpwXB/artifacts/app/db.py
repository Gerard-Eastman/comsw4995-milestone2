import sqlite3, os, datetime
DB_PATH="/app/data/app.db"
SCHEMA="""
CREATE TABLE IF NOT EXISTS users(
 id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL,
 display_name TEXT NOT NULL, created_at TEXT NOT NULL, timezone TEXT DEFAULT 'UTC',
 avatar_url TEXT DEFAULT '', status_text TEXT DEFAULT '', status_emoji TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS tokens(token TEXT PRIMARY KEY,user_id INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS workspaces(
 id INTEGER PRIMARY KEY, slug TEXT UNIQUE NOT NULL, name TEXT NOT NULL, owner_id INTEGER NOT NULL,
 join_mode TEXT NOT NULL DEFAULT 'open', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workspace_members(
 workspace_id INTEGER,user_id INTEGER,role TEXT NOT NULL DEFAULT 'member',
 PRIMARY KEY(workspace_id,user_id)
);
CREATE TABLE IF NOT EXISTS channels(
 id INTEGER PRIMARY KEY,workspace_id INTEGER NOT NULL,name TEXT NOT NULL,is_private INTEGER DEFAULT 0,
 is_dm INTEGER DEFAULT 0,topic TEXT DEFAULT '',is_archived INTEGER DEFAULT 0,
 created_at TEXT NOT NULL,last_event_id INTEGER NOT NULL DEFAULT 0,
 UNIQUE(workspace_id,name)
);
CREATE TABLE IF NOT EXISTS channel_members(channel_id INTEGER,user_id INTEGER,PRIMARY KEY(channel_id,user_id));
CREATE TABLE IF NOT EXISTS messages(
 id INTEGER PRIMARY KEY,channel_id INTEGER NOT NULL,author_id INTEGER NOT NULL,body TEXT NOT NULL,
 parent_id INTEGER,created_at TEXT NOT NULL,edited_at TEXT,deleted INTEGER DEFAULT 0,
 mentions TEXT DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS reactions(message_id INTEGER,user_id INTEGER,emoji TEXT,
 PRIMARY KEY(message_id,user_id,emoji));
CREATE TABLE IF NOT EXISTS pins(message_id INTEGER PRIMARY KEY,pinned_by INTEGER,pinned_at TEXT);
CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT,channel_id INTEGER,event_id INTEGER,payload TEXT);
CREATE TABLE IF NOT EXISTS broadcasts(seq INTEGER PRIMARY KEY AUTOINCREMENT,payload TEXT);
CREATE TABLE IF NOT EXISTS ws_presence(conn_id TEXT PRIMARY KEY,node_id INTEGER,user_id INTEGER);
CREATE TABLE IF NOT EXISTS read_state(user_id INTEGER,channel_id INTEGER,last_read_event_id INTEGER DEFAULT 0,
 PRIMARY KEY(user_id,channel_id));
CREATE TABLE IF NOT EXISTS files(id INTEGER PRIMARY KEY,uploader_id INTEGER,filename TEXT,content_type TEXT,
 size INTEGER,created_at TEXT,path TEXT);
CREATE TABLE IF NOT EXISTS message_files(message_id INTEGER,file_id INTEGER,PRIMARY KEY(message_id,file_id));
CREATE TABLE IF NOT EXISTS groups_tbl(id INTEGER PRIMARY KEY,workspace_id INTEGER,handle TEXT,name TEXT,
 creator_id INTEGER, UNIQUE(workspace_id,handle));
CREATE TABLE IF NOT EXISTS group_members(group_id INTEGER,user_id INTEGER,PRIMARY KEY(group_id,user_id));
CREATE TABLE IF NOT EXISTS invitations(code TEXT PRIMARY KEY,workspace_id INTEGER,created_by INTEGER,
 invited_user_id INTEGER,expires_at TEXT,max_uses INTEGER,uses INTEGER DEFAULT 0,revoked INTEGER DEFAULT 0);
"""
def connect():
    c=sqlite3.connect(DB_PATH,timeout=10,isolation_level=None,check_same_thread=False)
    c.execute("PRAGMA journal_mode=WAL"); c.execute("PRAGMA busy_timeout=10000")
    c.row_factory=sqlite3.Row
    return c
conn=connect()
def init_db():
    os.makedirs(os.path.dirname(DB_PATH),exist_ok=True)
    c=connect()
    for s in SCHEMA.split(";"):
        if s.strip(): c.execute(s)
    c.close()
def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00","Z")
