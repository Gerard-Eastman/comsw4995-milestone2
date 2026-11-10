# C2. Direct messages (Spec C, step 2 of 6)

Check: `bash /spec/c/checks/check_c_2.sh` (rules C2.1-C2.5). Architecture, conventions and the basics: `/spec/base/base.md`.

Start this step only after `bash /spec/c/checks/check_c_1.sh` reports `0 failed`. Call the functions listed under **Uses**; do not write second versions of them.

Route: `POST /api/dms`. File: `/app/routes_extras.py`.

**Uses:** `require_user`, `HTTPError`, `read_json`, `emit_event`, `user_to_json`; channel and
message routes from the basics.

**Adds:**

| Function | What it does |
|---|---|
| `dm_channel_for(user_a, user_b)` | Returns the id of the one DM channel between the two users, creating it on first use |

Store DMs as rows in `channels` with `is_dm = 1`, `is_private = 1`, `workspace_id = NULL`,
`name = "dm-<low id>-<high id>"`, and both users in `channel_members`. Keep the pair in a
`dm_pairs(user_low, user_high, channel_id, PRIMARY KEY(user_low, user_high))` table so the
lookup is a single primary-key read.

**Rules**

C2.1 `POST /api/dms` `{user_id}` -> `200 {channel_id}` (`200`, not `201`, also the first time).

C2.2 The same `channel_id` comes back on repeated calls and in both directions (A->B and B->A),
     on any node.

C2.3 `user_id` missing or not an integer -> `400`; unknown user -> `404`; no token -> `401`.

C2.4 Both users can post to and read the DM channel through the normal message routes
     (`POST`/`GET /api/channels/{channel_id}/messages`); a third user gets `403` on both.

C2.5 DM channels never appear in `GET /api/workspaces/{slug}` `channels`.
