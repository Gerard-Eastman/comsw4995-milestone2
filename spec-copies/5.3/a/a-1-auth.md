# A1. Auth: register, login, me (Spec A, step 1 of 4)

Check: `bash /spec/a/checks/check_a_1.sh` (rules A1.1-A1.6). Architecture, conventions and the basics: `/spec/base/base.md`.

Routes: `POST /api/auth/register`, `POST /api/auth/login`, `GET /api/auth/me`. File: `/app/routes_auth.py`.

**Uses:** `connect()`, `now_iso()` (db.py); `HTTPError`, `read_json`, `user_to_json` (common.py).

**Adds:**

| Function | What it does |
|---|---|
| `hash_password(pw)` | `hashlib.sha256` of a fixed salt + password, hex |
| `issue_token(user_id)` | `secrets.token_hex(24)` (48 chars), stored in `tokens`, returned |
| `require_user(request)` (common.py) | Reads `Authorization: Bearer <t>`, returns the user id, else `HTTPError(401)` |

Table: `users(id INTEGER PRIMARY KEY, username TEXT UNIQUE, password_hash TEXT, display_name TEXT, created_at TEXT)`.

**Rules**

A1.1 `POST /api/auth/register` `{username, password, display_name?}` -> `201 {user, token}`.
     `token` is >= 16 chars. `user` is a UserObj (base.md section 6) with the new `id`.

A1.2 The UserObj always has all seven keys: `id, username, display_name, timezone,
     avatar_url, status_text, status_emoji`.

A1.3 Registering a username that exists -> `409`.

A1.4 `username` must match `^[A-Za-z0-9_]{1,32}$` (so a space, a dash, or an empty string ->
     `400`). `password` shorter than 8 chars -> `400`. Missing fields -> `400`. There is no
     email field.

A1.5 `POST /api/auth/login` `{username, password}` -> `200 {user, token}` with a new token.
     Wrong password -> `401`. Unknown username -> `401`.

A1.6 `GET /api/auth/me` -> `200 {user}` for the token's owner. No header or unknown token -> `401`.
