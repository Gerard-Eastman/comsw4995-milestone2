import sqlite3, os, datetime
PATH='/app/data/app.db'
SCHEMA='''CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,username TEXT UNIQUE,password TEXT,display_name TEXT); CREATE TABLE IF NOT EXISTS tokens(token TEXT PRIMARY KEY,user_id INTEGER); CREATE TABLE IF NOT EXISTS workspaces(id INTEGER PRIMARY KEY,slug TEXT UNIQUE,name TEXT,owner_id INTEGER); CREATE TABLE IF NOT EXISTS channels(id INTEGER PRIMARY KEY,workspace_id INTEGER,name TEXT,is_private INTEGER DEFAULT 0,topic TEXT DEFAULT ''); CREATE TABLE IF NOT EXISTS members(user_id INTEGER,workspace_id INTEGER,channel_id INTEGER,role TEXT); CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY,channel_id INTEGER,author_id INTEGER,body TEXT,created_at TEXT); CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,channel_id INTEGER,seq INTEGER,kind TEXT,payload TEXT,created_at TEXT);'''
def connect():
 c=sqlite3.connect(PATH,timeout=10,isolation_level=None,check_same_thread=False); c.row_factory=sqlite3.Row; c.execute('PRAGMA journal_mode=WAL'); c.execute('PRAGMA busy_timeout=10000'); return c
def init_db():
 os.makedirs('/app/data',exist_ok=True); c=connect()
 for x in SCHEMA.split(';'):
  if x.strip(): c.execute(x)
 c.close()
def now_iso(): return datetime.datetime.now(datetime.timezone.utc).isoformat().replace('+00:00','Z')
