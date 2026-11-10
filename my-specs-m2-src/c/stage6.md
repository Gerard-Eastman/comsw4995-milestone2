## C6. Profiles

Routes: `GET /api/users/{id}`, `PATCH /api/users/me`. File: `/app/routes_extras.py`.

**Uses:** `require_user`, `user_to_json`, `read_json`, `broadcast_global` (base.md section 4).

**Adds:**

| Function | What it does |
|---|---|
| `validate_profile(body)` | Returns the dict of fields to update, or raises `HTTPError(400)` |

**Rules**

C6.1 `GET /api/users/{id}` -> `200 {user: UserObj}`; unknown or non-integer id -> `404`;
     no token -> `401`.

C6.2 `PATCH /api/users/me` with any subset of `{display_name, timezone, avatar_url,
     status_text, status_emoji}` -> `200 {user}`; the values persist (visible in
     `GET /api/users/{id}` and `GET /api/auth/me` on every node). Unknown keys are ignored.
     `PATCH` with `{}` changes nothing and returns `200 {user}`.

C6.3 Validation (any failure -> `400`, nothing changes): every given field must be a string;
     `display_name` 1-80 characters; `status_text` <= 100; `status_emoji` <= 64;
     `avatar_url` <= 1024; `timezone` an IANA name that `zoneinfo.ZoneInfo(name)` accepts
     (e.g. `"America/New_York"`, `"UTC"`; `"Mars/Base"` -> `400`).

C6.4 A successful `PATCH /api/users/me` calls `broadcast_global({"type": "user.updated",
     "user": UserObj})`, so **every** open WebSocket on every node receives that frame, even
     sockets that subscribed to nothing. The frame has no `channel_id` and no `event_id`.
