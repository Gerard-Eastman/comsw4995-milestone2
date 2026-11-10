# Base: architecture, cluster, basics, and API conventions

Every other spec file builds on this one. Read it fully before writing code.
Check: `bash /spec/base/checks/check_base.sh` (rules 0.1 to 0.13 in section 9).

## 1. Architecture you must use

Do not design your own architecture. Use exactly this one; it already satisfies the cluster
rules (shared ids, dense event ids, cross-node delivery, crash tolerance, Redis outages).

- **Python 3 + `aiohttp`** (HTTP and WebSocket in one server) + the stdlib **`sqlite3`**.
  `/app/requirements.txt` holds two lines: `aiohttp` and `tzdata`. Install them once at the
  start: `pip install aiohttp tzdata`.
- **One SQLite file, `/app/data/app.db`, shared by all three nodes** (and the IRC gateway).
  Every process opens its own connection with
  `sqlite3.connect(path, timeout=10, isolation_level=None, check_same_thread=False)`, then runs
  `PRAGMA journal_mode=WAL` and `PRAGMA busy_timeout=10000`, and sets `row_factory = sqlite3.Row`.
  All state (users, tokens, workspaces, channels, messages, files, events, ...) lives in this
  file, so a token, id or cursor from one node works on the others.
- **No in-memory state** except the WebSocket subscriber lists. Never cache rows in Python dicts.
- **Integer ids** from `INTEGER PRIMARY KEY` columns.
- **Redis is started but not used by the app.** The grading contract requires a local
  `redis-server` on 6379; `start.sh` runs and respawns it. The app never talks to it, so
  killing Redis cannot stop anything.
- **Cross-node WebSocket delivery = tables polled by every node.** See section 4.
- Create the app with `web.Application(middlewares=[error_middleware], client_max_size=20 * 1024 * 1024)`
  so file uploads up to 20 MiB reach your handler (the default limit is 1 MiB).

### Files

Keep each file under ~250 lines and write each one in its own step (a `cat > file <<'EOF'`
heredoc per file). Long single heredocs get cut off.

| File | Contents |
|---|---|
| `/app/start.sh` | Exactly the script in section 2 |
| `/app/requirements.txt` | `aiohttp` and `tzdata`, one per line |
| `/app/db.py` | `SCHEMA`, `connect()`, `init_db()`, `now_iso()` |
| `/app/common.py` | `HTTPError`, `error_middleware`, `read_json(request)`, `require_user(request)`, `user_to_json(row)`, `parse_limit(request)`, `encode_cursor(n)`, `decode_cursor(s)`, `emit_event(channel_id, kind, data)`, `broadcast_global(payload)` |
| `/app/routes_auth.py` | `setup(app)`: auth routes |
| `/app/routes_workspaces.py` | `setup(app)`: workspaces, members, roles, invitations, join mode |
| `/app/routes_channels.py` | `setup(app)`: channel create/join/leave/patch/members/archive |
| `/app/routes_messages.py` | `setup(app)`: messages (incl. slash commands), replies, edit/delete, reactions, pins, search, read state |
| `/app/routes_extras.py` | `setup(app)`: DMs, files, user groups, profiles |
| `/app/ws.py` | `setup(app)`: the `/api/ws` handler, presence, and the event pump |
| `/app/irc.py` | The IRC gateway, a separate process on port 6667 (Spec E) |
| `/app/static/index.html`, `app.js`, `style.css` | The web UI served at `GET /` (Spec E) |
| `/app/server.py` | parses `--port` and `--node-id`, builds the app, adds `/api/health`, calls each `setup(app)`, runs `web.run_app(app, host="0.0.0.0", port=port)` |

Each module gets the shared connection from `db.py` (one module-level connection per process,
opened before the app starts).

**Every table lives in `db.SCHEMA` and is created by `db.init_db()`**, which `start.sh` runs
before any node starts. When a step needs a new table or column, add it to `SCHEMA` (new columns:
`ALTER TABLE ... ADD COLUMN` inside `init_db()`, ignoring "duplicate column"). Never run
`CREATE TABLE` inside a route, the WebSocket handler or the IRC gateway: graders start from an
empty database, and a table that only appears after some other request makes every request
that reads it fail (for example, a pump that reads a table nobody has written yet stops
delivering events). Build only the files your run needs; `start.sh` already copes
with `irc.py` not existing yet.

## 2. `/app/start.sh` (copy this exactly)

```bash
#!/bin/bash
cd /app
mkdir -p /app/data/files
python3 -c 'import aiohttp, tzdata' 2>/dev/null || pip install -q -r /app/requirements.txt >/tmp/pip.log 2>&1
(while true; do redis-server --port 6379 --save '' --appendonly no >/tmp/redis.log 2>&1; sleep 1; done) &
python3 -c 'import sys; sys.path.insert(0, "/app"); import db; db.init_db()'
for i in 0 1 2; do
  (while true; do python3 /app/server.py --port $((8000+i)) --node-id $i >>/tmp/node$i.log 2>&1; sleep 1; done) &
done
(while true; do [ -f /app/irc.py ] && python3 /app/irc.py >>/tmp/irc.log 2>&1; sleep 1; done) &
wait
```

Then `chmod +x /app/start.sh`. The respawn loops are what make a killed node, a killed Redis
and a killed IRC gateway come back. When a node will not start, read `/tmp/node0.log`.

## 3. Restarting after a code change

Run `bash /spec/tools/restart.sh`. It kills the three node PIDs and the IRC gateway PID
(found by port, never by name); the respawn loops start them again with your new code in about
two seconds. It prints `RESTART OK` or `RESTART FAILED`. Use `bash /spec/tools/restart.sh --full`
only after you changed `start.sh` itself. If the cluster is not running at all, both commands
start it.

**Never** use `pkill`, `killall`, `pgrep -f`, or `kill` on a name, and never parse `ps`: that
can kill you (the agent). Never kill a process group. Only kill a PID that owns a port
(`ss -ltnp`) or a PID you saved yourself.

## 4. Events, broadcasts and presence (cross-node delivery)

Tables:

```sql
channels(..., last_event_id INTEGER NOT NULL DEFAULT 0)
events(seq INTEGER PRIMARY KEY AUTOINCREMENT, channel_id INTEGER, event_id INTEGER, payload TEXT)
broadcasts(seq INTEGER PRIMARY KEY AUTOINCREMENT, payload TEXT)
ws_presence(conn_id TEXT PRIMARY KEY, node_id INTEGER, user_id INTEGER)
```

`emit_event(channel_id, kind, data)` does all of this inside one `BEGIN IMMEDIATE` ...
`COMMIT` transaction (`ROLLBACK` on error):
1. `UPDATE channels SET last_event_id = last_event_id + 1 WHERE id = ?`
2. read the new `last_event_id` -> `event_id`
3. build `payload = {"type": kind, "event_id": event_id, "channel_id": channel_id, **data}`
4. `INSERT INTO events(channel_id, event_id, payload) VALUES (?, ?, json.dumps(payload))`
5. return `event_id`

Because the increment and the insert are one write transaction on the shared file,
`event_id` is dense (1, 2, 3, ...) per channel no matter which node (or the IRC gateway)
writes. Never read `last_event_id` in one statement and write it back outside that transaction.

Call `emit_event` for every durable change: `member.joined` (including the creator joining a
new channel), `member.left`, `message.created` (top-level), `message.reply` (has `parent_id`),
`message.updated`, `message.deleted`, `reaction.added`, `reaction.removed`, `channel.updated`
(topic change), `channel.archived`, `channel.unarchived`. Nothing else emits events.

`broadcast_global(payload)` inserts `json.dumps(payload)` into `broadcasts`. It is for
non-durable, non-channel frames (`user.updated`): they carry no `channel_id` and no `event_id`.

Delivery: each node runs one background task (start it in `app.on_startup`) that every 50 ms
1. selects `events WHERE seq > last_event_seq ORDER BY seq` and sends each payload to that
   node's local WebSocket subscribers of its `channel_id`; keep, per connection, the last
   `event_id` sent per channel and skip anything not newer (no duplicates);
2. selects `broadcasts WHERE seq > last_broadcast_seq ORDER BY seq` and sends each payload to
   **every** open WebSocket on that node, subscribed or not.

Start both `last_*_seq` at the current `MAX(seq)` when the node starts.

Presence (who has an open WebSocket, on any node): when a WebSocket is accepted, insert a row
`(conn_id = uuid4 hex, node_id, user_id)` into `ws_presence`; delete it when the socket closes
(`finally:`). When a node starts, first run `DELETE FROM ws_presence WHERE node_id = ?` (rows
left by a killed process).

## 5. API conventions (every endpoint in every spec)

- All routes are under `/api/...`, take and return JSON (except file upload/download and `GET /`).
- Auth: `Authorization: Bearer <token>`. Tokens live in a `tokens(token, user_id)` table.
  Missing or unknown token -> `401` on every route except register, login, health and `GET /`.
  Check the token **first**, before looking up anything else.
- Responses wrap the resource in one top-level key: `{"user": ...}`, `{"workspace": ...}`,
  `{"channels": [...]}`, `{"file": ...}`, `{"groups": [...]}`, etc. Errors:
  `{"error": "<short reason>"}` with the status code.
- Status codes: `200` read/update, `201` create, `400` validation, `401` auth, `403`
  forbidden, `404` unknown id, `409` conflict, `413` upload over limit, `423` write to an
  archived channel.
- Order of checks inside every handler: auth (401) -> resource exists (404) -> permission
  (403) -> body validation (400) -> conflict (409) -> archived (423). Exceptions are noted in
  the specs.
- Timestamps: `datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")`
  e.g. `2026-05-16T08:07:34.123Z`.
- A path id that is not an integer is an unknown id -> `404`.
- Read the body with `await request.json()` inside `try`; a missing or non-object body is `{}`.
- Implement errors as `raise HTTPError(status, reason)` caught by one aiohttp middleware that
  returns `web.json_response({"error": reason}, status=status)`. The middleware must turn any
  other exception into `500` with a JSON body, never crash the node.

### Pagination (every list endpoint that takes `limit`/`cursor`)

- `limit`: default `50`; must parse as an integer between `1` and `200`, else `400`.
- `cursor`: opaque. `encode_cursor(n)` = urlsafe-base64 of `json.dumps({"k": n})`, where `n` is
  the integer sort key (usually the row id) of the **last item on the page**.
  `decode_cursor(s)` returns `n`, or raises `HTTPError(400)` if `s` does not decode to a JSON
  object with an integer `"k"`.
- Fetch `limit + 1` rows. If you got more than `limit`, return the first `limit` and
  `next_cursor = encode_cursor(<key of the last returned row>)`; otherwise `next_cursor = null`.
- Newest-first lists: `WHERE id < :k ORDER BY id DESC`. Oldest-first lists: `WHERE id > :k
  ORDER BY id ASC`. Because the key is an id in the shared database, cursors work on every node
  and new rows never shift a page.
- `?page=` / `?offset=` are not supported (ignore them).

## 6. UserObj

`user_to_json(row)` returns `{id, username, display_name, timezone, avatar_url, status_text,
status_emoji}`, all stored as columns of `users`. Defaults: `display_name` = the registered
`display_name` or the username, `timezone` = `"UTC"`, the other three = `""`.

## 7. MessageObj and ChannelObj

- **MessageObj** = `{id, channel_id, author_id, author: UserObj, body, parent_id, reply_count,
  created_at, edited_at, files: [FileObj], reactions: [{emoji, count, user_ids}],
  mentions: [user ids]}`. `parent_id` and `edited_at` are `null` when unset. `files`,
  `reactions` and `mentions` are `[]` when empty. REST message objects do **not** carry an
  `event_id` (only WebSocket frames do).
- **ChannelObj** = `{id, workspace_id, name, is_private, is_dm, topic, is_archived, created_at}`
  (booleans as JSON `true`/`false`; `topic` defaults to `""`).

## 8. Basics every component needs

If this run has no Spec A or Spec B in `/spec`, build **only** these basics (the task
description has the full contracts) and then go straight to your components. If Specs A and B
are in `/spec`, they cover all of this in more detail; follow them instead.

| Route | Result |
|---|---|
| `POST /api/auth/register` `{username, password, display_name?}` | `201 {user, token}`; username `^[A-Za-z0-9_]{1,32}$`, password >= 8 chars (else `400`); duplicate -> `409` |
| `POST /api/auth/login` `{username, password}` | `200 {user, token}`; wrong password -> `401` |
| `GET /api/auth/me` | `200 {user}` |
| `POST /api/workspaces` `{slug, name}` | `201 {workspace, general_channel}`; slug `^[a-z0-9-]{2,32}$`; caller becomes role `owner`; `#general` is created and the owner joins it; `join_mode` `"open"` |
| `GET /api/workspaces` | `200 {workspaces}` the caller belongs to |
| `GET /api/workspaces/{slug}` | `200 {workspace, channels, read_state}` (no DM channels in `channels`) |
| `GET /api/workspaces/{slug}/members` | `200 {members: [{user_id, role, user}]}` |
| `POST /api/workspaces/{slug}/channels` `{name, is_private?, topic?}` | `201 {channel}`; name `^[a-z0-9]+(-[a-z0-9]+)*$` <= 32; duplicate -> `409`; creator joins it |
| `POST /api/channels/{id}/join` | `200 {channel}`; a non-member of an `open` workspace becomes role `member`; private -> `403` |
| `PATCH /api/channels/{id}` `{topic}` | `200 {channel}`, emits `channel.updated`; topic <= 250 chars |
| `POST /api/channels/{id}/archive`, `/unarchive` | `200 {channel}`; workspace owner only; writes to an archived channel -> `423` |
| `POST /api/channels/{id}/messages` `{body, parent_id?, file_ids?}` | `201 {message}`; empty body -> `400`; emits `message.created` / `message.reply` |
| `GET /api/channels/{id}/messages?limit=&cursor=` | `200 {messages, next_cursor}` newest-first, top-level only |
| `GET /api/messages/{id}/replies?limit=&cursor=` | `200 {replies, next_cursor}` oldest-first (the thread of a message) |
| `GET /api/channels/{id}/read` | `200 {read_state: {channel_id, last_read_event_id, unread_count, mention_count}}` |
| `ws://...:800N/api/ws?token=<token>` | Client sends `{"type":"subscribe","channel_id":<id>}` -> server replies `{"type":"subscribed","channel_id":<id>,"head_event_id":<channel's last_event_id>}`, then sends that channel's event frames (section 4). Client sends `{"type":"resume","channel_id":<id>,"since_event_id":<n>}` -> server sends every stored event of that channel with `event_id > n` in order, then `{"type":"resumed","channel_id":<id>,"head_event_id":<last event_id>}`, then live events |

A user may read and post in a channel if they are a channel member, or if the channel is
public and they are a member of its workspace. **Mentions:** `@username` (a member of the
channel's workspace) and `@channel` (every channel member) resolve to user ids in
`message.mentions`, deduplicated, never the author. `mention_count` counts unread messages by
others that mention the reader.

## 9. Rules (milestone 0 baseline and the basics, checked by `check_base.sh`)

0.1 `/app/start.sh` is executable and `/app/requirements.txt` exists.

0.2 `GET /api/health` on port 8000 returns `200` and exactly `{"status": "ok", "node_id": 0}`.

0.3 Port 8001 answers `node_id: 1` and port 8002 answers `node_id: 2` (integers).

0.4 A WebSocket to `ws://127.0.0.1:8000/api/ws?token=<invalid>` is rejected **at the
    handshake**: look the token up before upgrading and return HTTP `401` instead of upgrading.

0.5 A WebSocket with a valid token connects on all three ports.

0.6 A token issued by one node works on the other two (shared database).

0.7 `redis-server` is listening on `127.0.0.1:6379`.

0.8 After `SIGKILL` of the node on 8001, ports 8000 and 8002 keep answering health, and 8001
    comes back by itself within 12 seconds (the respawn loop).

0.9 Basics: register -> `201 {user, token}`, login -> `200 {user, token}`, `GET /api/auth/me` ->
    `200 {user}` (no token -> `401`).

0.10 `POST /api/workspaces` -> `201 {workspace, general_channel}` (`general_channel.name` is
     `"general"`); the workspace is listed by `GET /api/workspaces` on every node, and
     `GET /api/workspaces/{slug}` lists `#general`.

0.11 Creating a channel -> `201 {channel}`; the same name again -> `409`; another user can join
     the public channel (`200`).

0.12 Posting -> `201 {message}`; `GET /api/channels/{id}/messages` on another node lists it
     newest-first; an empty body -> `400`.

0.13 A WebSocket subscriber gets `message.created` with `event_id = head_event_id + 1` for a
     post made on another node.
