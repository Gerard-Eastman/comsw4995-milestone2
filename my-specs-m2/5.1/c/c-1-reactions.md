# C1. Reactions (Spec C, step 1 of 6)

Check: `bash /spec/c/checks/check_c_1.sh` (rules C1.1-C1.6). Architecture, conventions and the basics: `/spec/base/base.md`.

Routes: `POST /api/messages/{id}/reactions`, `DELETE /api/messages/{id}/reactions/{emoji}`.
File: `/app/routes_messages.py`.

**Uses:** `require_user`, `HTTPError`, `read_json`, `emit_event` (common.py); the basics in
base.md section 8 (messages, channels, read access).

**Adds:**

| Function | What it does |
|---|---|
| `reactions_for(message_id)` | `[{emoji, count, user_ids}]`, one entry per emoji, in order of first use; `user_ids` in order of reacting; `count == len(user_ids)` |
| `message_by_id(id)` | Non-deleted message row or `HTTPError(404)` (non-integer id -> 404) |

Table: `reactions(message_id, user_id, emoji, created_at, PRIMARY KEY(message_id, user_id, emoji))`.

**Rules**

C1.1 `POST /api/messages/{id}/reactions` `{emoji}` -> `200 {reactions}` (not `201`), even on the
     first insert. `reactions` is the message's full list `[{emoji, count, user_ids}]`.
     `emoji` must be a non-empty string of at most 64 characters (else `400`).

C1.2 Idempotent per (user, emoji): reacting twice with the same emoji leaves `count` at 1. A
     second user reacting with the same emoji makes `count` 2 and adds their id to `user_ids`.

C1.3 `DELETE /api/messages/{id}/reactions/{emoji}` removes **only the caller's** reaction and
     returns `200 {reactions}`; removing a reaction you never added is still `200`. An emoji
     whose count drops to 0 disappears from the list.

C1.4 `message.reactions` in `GET /api/channels/{id}/messages` shows the same list.

C1.5 Errors: no token -> `401`; unknown message -> `404`; a user who cannot read the channel
     (e.g. a non-member of a private channel) -> `403`; channel archived -> `423`.

C1.6 Events: a new reaction emits `reaction.added`, a removal that changed something emits
     `reaction.removed`, both with `{"message_id", "emoji", "user_id", "reactions"}`. Repeats
     that change nothing emit nothing.
