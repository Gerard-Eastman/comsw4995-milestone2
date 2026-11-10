# B3. Pins and search (Spec B, step 3 of 5)

Check: `bash /spec/b/checks/check_b_3.sh` (rules B3.1-B3.6). Architecture, conventions and the basics: `/spec/base/base.md`.

Start this step only after `bash /spec/b/checks/check_b_2.sh` reports `0 failed`. Call the functions listed under **Uses**; do not write second versions of them.

Routes: `POST /api/messages/{id}/pin`, `DELETE /api/messages/{id}/pin`,
`GET /api/channels/{id}/pins`, `GET /api/search`. File: `/app/routes_messages.py`.

**Uses:** `message_by_id`, `message_to_json`, `channel_by_id`, `can_read_channel`,
`parse_limit`, `encode_cursor`, `decode_cursor`.

**Adds:**

| Function | What it does |
|---|---|
| `pin_to_json(row)` | `{message: MessageObj, pinned_by, pinned_at}` |

Table: `pins(id INTEGER PRIMARY KEY, message_id UNIQUE, channel_id, pinned_by, pinned_at)`.
The pin's own `id` is the paging key (newest pin = highest id).

**Rules**

B3.1 `POST /api/messages/{id}/pin` -> `200 {pin: {message_id, pinned_by, pinned_at}}`. Pinning
     an already-pinned message is `200` and changes nothing (same `pinned_by`/`pinned_at`, no
     duplicate). `GET /api/channels/{id}/pins?limit=&cursor=` ->
     `200 {pins: [{message, pinned_by, pinned_at}, ...], next_cursor}`, **newest pin first**.
     Unknown message -> `404`; caller must pass `can_read_channel` (`403`); archived -> `423`.

B3.2 `DELETE /api/messages/{id}/pin` -> `200 {"unpinned": true}` (also when it was not
     pinned). The pin disappears from the list. A non-member of a private channel gets `403` on
     that channel's pin list.

B3.3 `GET /api/search?q=<text>&limit=&cursor=` -> `200 {results: [MessageObj, ...], next_cursor}`,
     **newest-first** by message id. Matching is case-insensitive substring
     (`instr(lower(body), lower(?)) > 0`). Only non-deleted messages in channels the caller can
     read: workspaces the caller is a member of, and either public channels or private
     channels the caller is a member of. Includes thread replies. Empty or missing `q` -> `400`.

B3.4 Optional `workspace_id=<id>` limits results to that workspace. Paging per base.md section 5.

B3.5 **Pins page.** `GET /api/channels/{id}/pins?limit=&cursor=` pages per base.md section 5,
     newest-first, with the pin row's own `id` as the key (`WHERE id < :k ORDER BY id DESC`):
     three pins at `limit=2` -> the two newest, then the oldest with `next_cursor: null`. The
     cursor must be honoured, so page 2 never repeats page 1. Malformed cursor -> `400`;
     `limit=201` -> `400`.

B3.6 **Search validates its inputs like every list.** `GET /api/search`: malformed cursor ->
     `400`; `limit` of `0` or `abc` -> `400`; missing or empty `q` -> `400`.
