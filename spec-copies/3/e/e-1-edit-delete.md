# E1. Message edit and delete (Spec E, step 1 of 6)

Check: `bash /spec/e/checks/check_e_1.sh` (rules E1.1-E1.5). Architecture, conventions and the basics: `/spec/base/base.md`.

Routes: `PATCH /api/messages/{id}`, `DELETE /api/messages/{id}`. File: `/app/routes_messages.py`.

**Uses:** `emit_event`, `message_to_json` (or your equivalent), the message routes from the
basics; workspace ownership (`workspaces.owner_id`).

**Adds:**

| Function | What it does |
|---|---|
| `message_any(id)` | The message row **including** deleted ones, or `HTTPError(404)` if it never existed |

Delete is a soft delete: set `messages.deleted = 1`. Every read path filters `deleted = 0`.

**Rules**

E1.1 `PATCH /api/messages/{id}` `{body}` by the author -> `200 {message}` with the new `body`
     and `edited_at` set to the edit time (ISO-8601 UTC); emits `message.updated` with
     `{"message": MessageObj}`.

E1.2 Edit errors, checked in this order: no token `401`; message never existed `404`; not the
     author `403` (also for the workspace owner); message deleted `409`; `body` missing,
     empty or whitespace-only `400`; channel archived `423`.

E1.3 `DELETE /api/messages/{id}` by the author **or the workspace owner** -> `200 {"deleted": true}`
     and emits `message.deleted` with `{"message_id": id}`. Anyone else -> `403`. Never
     existed -> `404`.

E1.4 Delete is idempotent: deleting an already-deleted message returns `200 {"deleted": true}`
     again and emits nothing.

E1.5 A deleted message disappears from `GET /api/channels/{id}/messages` (and from replies,
     search and pins, where those routes exist); a deleted reply no longer counts in its
     parent's `reply_count`. Reacting to a deleted message -> `404`, so its reactions no longer
     count anywhere.
