# B2. Messages, threads, and paging (Spec B, step 2 of 5)

Check: `bash /spec/b/checks/check_b_2.sh` (rules B2.1-B2.7). Architecture, conventions and the basics: `/spec/base/base.md`.

Start this step only after `bash /spec/b/checks/check_b_1.sh` reports `0 failed`. Call the functions listed under **Uses**; do not write second versions of them.

Routes: `POST /api/channels/{id}/messages`, `GET /api/channels/{id}/messages`,
`GET /api/messages/{id}/replies`. File: `/app/routes_messages.py`.

**Uses:** `channel_by_id`, `can_read_channel`, `emit_event`, `user_to_json`, `parse_limit`,
`encode_cursor`, `decode_cursor`, `require_user`.

**Adds:**

| Function | What it does |
|---|---|
| `message_by_id(id)` | Non-deleted message row or `HTTPError(404)` |
| `message_to_json(row)` | MessageObj (below) |
| `resolve_mentions(body, channel_row, author_id)` | List of user ids (B4; until then return `[]`) |

Table: `messages(id INTEGER PRIMARY KEY, channel_id, author_id, body, parent_id, created_at, edited_at, deleted INTEGER DEFAULT 0, mentions TEXT, event_id INTEGER)`.
`mentions` is a JSON list; `event_id` is the id of the `message.created`/`message.reply` event
(internal, for read state; not part of MessageObj).

**MessageObj** = `{id, channel_id, author_id, author: UserObj, body, parent_id, reply_count,
created_at, edited_at, files: [], reactions: [{emoji, count, user_ids}], mentions: [user ids]}`.
`parent_id` and `edited_at` are `null` when unset; `reply_count` = number of non-deleted
replies.

**Rules**

B2.1 `POST /api/channels/{id}/messages` `{body, parent_id?}` -> `201 {message}`. `body` must be
     a string that is not empty or whitespace-only (`400`). No token -> `401`; unknown channel ->
     `404`; caller fails `can_read_channel` -> `403`; archived -> `423`. Store, then emit
     `message.created` (or `message.reply` if `parent_id` is set) with `{"message": MessageObj}`,
     and save the returned event id on the row.

B2.2 A user who is not a member of a private channel gets `403` on both posting and reading.

B2.3 `GET /api/channels/{id}/messages?limit=&cursor=` -> `200 {messages, next_cursor}`,
     **newest-first**, top-level messages only (`parent_id IS NULL`), non-deleted. Paging per
     base.md section 5: five messages at `limit=2` come back as pages of 2, 2, 1 with
     `next_cursor` `null` on the last page, no gaps, no duplicates.

B2.4 A cursor issued by one node works on another, and messages posted after the cursor was
     issued do not shift the next page (the cursor is an id, so this is automatic).

B2.5 Malformed cursor (not base64 JSON) -> `400`; a cursor that decodes but has no integer
     `"k"` -> `400`. `limit` of `0`, `201`, `-1` or `abc` -> `400`; `200` is fine. No `limit` ->
     50 messages per page.

B2.6 Threads: posting with `parent_id` (a non-deleted message in the same channel, else `404`)
     creates a reply. The parent's `reply_count` counts its replies. Replies never appear in
     `GET .../messages`. `GET /api/messages/{parent_id}/replies?limit=&cursor=` ->
     `200 {replies, next_cursor}` **oldest-first**; unknown parent -> `404`; caller must pass
     `can_read_channel` (`403`).

B2.7 **Replies page exactly like messages** (base.md section 5, oldest-first): five replies at
     `limit=2` come back as pages of 2, 2, 1 in posting order, the cursor works on any node,
     and the last page has `next_cursor: null`. A malformed cursor -> `400`; `limit` of `0` or
     `201` -> `400`.
