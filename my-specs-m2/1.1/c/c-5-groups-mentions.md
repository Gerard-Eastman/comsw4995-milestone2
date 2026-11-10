# C5. User groups, `@group-handle` and `@here` (Spec C, step 5 of 6)

Check: `bash /spec/c/checks/check_c_5.sh` (rules C5.1-C5.5). Architecture, conventions and the basics: `/spec/base/base.md`.

Start this step only after `bash /spec/c/checks/check_c_4.sh` reports `0 failed`. Call the functions listed under **Uses**; do not write second versions of them.

Routes: `GET`/`POST /api/workspaces/{slug}/groups`, `PATCH`/`DELETE
/api/workspaces/{slug}/groups/{handle}`; mention resolution in the message post route. File:
`/app/routes_extras.py` (and `routes_messages.py` for mentions).

**Uses:** `workspace_by_slug`, `role_of` (or your equivalent), the `ws_presence` table
(base.md section 4), the mention resolution from the basics.

**Adds:**

| Function | What it does |
|---|---|
| `group_to_json(row)` | `GroupObj = {id, handle, name, member_user_ids: [...]}` (sorted ids; the key is `member_user_ids`, never `members`) |
| `MENTION_RE` (replaces any earlier one) | `re.compile(r"(?<![A-Za-z0-9_@.])@([A-Za-z0-9_](?:[A-Za-z0-9_-]*[A-Za-z0-9_])?)(?![A-Za-z0-9_@-])(?!\.[A-Za-z0-9])")` |
| `resolve_mentions(body, channel_row, author_id)` | Returns the deduplicated list of mentioned user ids (rules below) |

Tables: `groups(id INTEGER PRIMARY KEY, workspace_id, handle, name, created_by, UNIQUE(workspace_id, handle))`,
`group_members(group_id, user_id, PRIMARY KEY(group_id, user_id))`.

**Rules**

C5.1 `POST /api/workspaces/{slug}/groups` `{handle, name, user_ids}` -> `201 {group}`. Any
     workspace member may create (non-member -> `403`, unknown slug -> `404`). `handle` must
     match `^[a-z0-9][a-z0-9-]{0,30}[a-z0-9]$` and must not be `here` or `channel` (`400`);
     `name` a non-empty string (`400`); `user_ids` a list of ids of workspace members (`400`
     otherwise; missing means `[]`). A duplicate handle in the workspace -> `409`.

C5.2 `GET /api/workspaces/{slug}/groups` -> `200 {groups: [GroupObj]}` for workspace members
     (`403` otherwise).

C5.3 `PATCH /api/workspaces/{slug}/groups/{handle}` with any subset of `{name, user_ids}` ->
     `200 {group}` with the change persisted. `DELETE` the same path -> `200 {"deleted": true}`.
     Both are allowed only for the group's creator or the workspace owner (`403` for anyone
     else). Unknown handle: `PATCH` -> `404`, `DELETE` -> `200 {"deleted": true}` (idempotent;
     deleting twice is fine).

C5.4 Mention resolution, for each `MENTION_RE` match `name` in the body:
     - `here`: every channel member who currently has a row in `ws_presence` (an open WebSocket
       on any node);
     - `channel`: every channel member;
     - a username of a member of the channel's workspace: that user;
     - otherwise a group handle in the channel's workspace: the group members **who are also
       channel members**.
     Then remove the author and deduplicate keeping first-seen order. Mentioning yourself (in
     any form) never adds you, so it never raises your own `mention_count`.

C5.5 So `@team` mentions only those group members who are in the channel, and `@here` only
     members with a live socket: a member who closes their socket is no longer mentioned by
     the next `@here`.
