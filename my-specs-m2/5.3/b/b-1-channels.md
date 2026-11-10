# B1. Channel management (Spec B, step 1 of 5)

Check: `bash /spec/b/checks/check_b_1.sh` (rules B1.1-B1.8). Architecture, conventions and the basics: `/spec/base/base.md`.

Routes: `POST /api/workspaces/{slug}/channels`, `GET /api/workspaces/{slug}`,
`PATCH /api/channels/{id}`, `POST /api/channels/{id}/leave`, `GET /api/channels/{id}/members`,
`POST /api/channels/{id}/archive`, `POST /api/channels/{id}/unarchive`. File: `/app/routes_channels.py`.

**Uses:** `workspace_by_slug`, `role_of`, `create_channel`, `channel_by_id`, `channel_to_json`,
`is_channel_member`, `add_channel_member`, `emit_event`, `user_to_json`, `require_user`.

**Adds:**

| Function | What it does |
|---|---|
| `can_read_channel(channel_row, user_id)` | True if a channel member, or (channel is public and the user is any workspace member) |
| `read_state_for(channel_id, user_id)` | `{channel_id, last_read_event_id, unread_count, mention_count}` (filled in by B4; until then return the stored `last_read_event_id` and zeros) |

**Rules**

B1.1 `POST /api/workspaces/{slug}/channels` `{name, is_private?, topic?}` -> `201 {channel}`, a
     ChannelObj `{id, workspace_id, name, is_private, is_dm: false, topic, is_archived: false}`.
     `topic` defaults to `""`. Any other body field (e.g. `description`) is ignored and never
     fills `topic`. The creator becomes a channel member (`create_channel`).

B1.2 `name` must match `^[a-z0-9]+(-[a-z0-9]+)*$` and be <= 32 chars (space, uppercase, 33
     chars, empty -> `400`). `topic` longer than 250 chars -> `400`. A name that exists in the
     workspace -> `409`. Permission rules (A3.8) are checked first.

B1.3 `GET /api/workspaces/{slug}` -> `200 {workspace, channels, read_state}`. Caller must be a
     workspace member (`403`). `channels` lists the workspace's channels **except** private
     channels the caller is not a member of, and **except** archived channels unless the query
     has `include_archived=1` or `include_archived=true`. `read_state` is a **list** with one
     `read_state_for(channel_id, caller)` object per listed channel.

B1.4 `PATCH /api/channels/{id}` `{topic}` -> `200 {channel}` and
     `emit_event(id, "channel.updated", {"channel": ChannelObj})`. Caller must be a channel
     member or the workspace owner (`403`). `topic` must be a string <= 250 chars (`400`).
     Archived channel -> `423`.

B1.5 `POST /api/channels/{id}/leave` -> `200 {channel}`; if the caller was a member, delete
     the membership and `emit_event(id, "member.left", {"user_id": uid})`. Leaving again is
     still `200` (no event). `GET /api/channels/{id}/members` -> `200 {members: [UserObj, ...]}`
     (full UserObjs of current channel members); caller must pass `can_read_channel` (`403`).

B1.6 `POST /api/channels/{id}/archive` and `/unarchive` -> `200 {channel}` with `is_archived`
     `true` / `false`. Workspace **owner only** (admins -> `403`). Emit `channel.archived` /
     `channel.unarchived` with `{"channel": ChannelObj}` only when the flag actually changes.
     While archived, every write -> `423`: posting a message, editing a message, `PATCH`
     topic, pinning, adding a reaction (B5.6 checks all of them). Unarchive restores writes.

B1.7 Archived channels are hidden from `GET /api/workspaces/{slug}` unless
     `include_archived=1` (or `true`).

B1.8 **The workspace owner may set any topic.** The workspace owner can
     `PATCH /api/channels/{id}` `{topic}` on a channel they are **not** a member of -> `200
     {channel}`. Any other non-member -> `403` (B1.4).
