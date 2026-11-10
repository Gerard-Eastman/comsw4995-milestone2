## A2. Workspaces, membership, and joining channels

Routes: `POST /api/workspaces`, `GET /api/workspaces`, `GET /api/workspaces/{slug}/members`,
`POST /api/channels/{id}/join`. Files: `/app/routes_workspaces.py`, `/app/routes_channels.py`.

**Uses:** `require_user`, `HTTPError`, `read_json`, `user_to_json`, `emit_event` (common.py).

**Adds:**

| Function | What it does |
|---|---|
| `workspace_by_slug(slug)` | Row or `HTTPError(404)` |
| `workspace_to_json(row)` | `{id, slug, name, owner_id, join_mode, created_at}` |
| `role_of(workspace_id, user_id)` | `"owner"/"admin"/"member"/"guest"` or `None` if not a member |
| `add_workspace_member(workspace_id, user_id, role)` | Inserts into `workspace_members` if absent |
| `channel_by_id(id)` | Row or `HTTPError(404)` (non-integer id -> 404) |
| `channel_to_json(row)` | `{id, workspace_id, name, is_private, is_dm, topic, is_archived, created_at}` (booleans as `true/false`) |
| `create_channel(workspace_id, name, is_private, topic, creator_id)` | Inserts the channel, then `add_channel_member` for the creator; returns the row |
| `is_channel_member(channel_id, user_id)` | bool |
| `add_channel_member(channel_id, user_id)` | If not already a member: insert with `last_read_event_id` 0, `emit_event(channel_id, "member.joined", {"user_id": uid, "user": UserObj})`, then set the member's `last_read_event_id` to that event id |

Tables: `workspaces(id, slug UNIQUE, name, owner_id, join_mode, created_at)`,
`workspace_members(workspace_id, user_id, role, joined_at, PRIMARY KEY(workspace_id, user_id))`,
`channels(id, workspace_id, name, is_private, is_dm, topic, is_archived, last_event_id, created_at, UNIQUE(workspace_id, name))`,
`channel_members(channel_id, user_id, last_read_event_id, PRIMARY KEY(channel_id, user_id))`.

**Rules**

A2.1 `POST /api/workspaces` `{slug, name}` -> `201 {workspace, general_channel}`.
     `workspace` = `{id, slug, name, owner_id, join_mode}` with `owner_id` = caller and
     `join_mode` = `"open"`. The caller becomes a workspace member with role `owner`. A public
     channel named `general` is created (via `create_channel`, so the owner is its member) and
     returned as `general_channel` (a ChannelObj).

A2.2 `slug` must match `^[a-z0-9-]{2,32}$` (uppercase, `_`, 1 char, 33 chars -> `400`); `name`
     must be a non-empty string (`400`). A slug that exists -> `409`.

A2.3 All workspace routes need a token (`401`). An unknown slug -> `404`.

A2.4 `GET /api/workspaces` -> `200 {workspaces: [WorkspaceObj, ...]}` containing only
     workspaces where the caller is a member (any role).

A2.5 `GET /api/workspaces/{slug}/members` -> `200 {members: [{user_id, role, joined_at, user}]}`
     for every member. Caller must be a member (else `403`).

A2.6 `POST /api/channels/{id}/join` -> `200 {channel}`. Decide in this order:
     1. unknown channel -> `404`;
     2. caller already a channel member -> `200` (no new event);
     3. private channel -> `403` (nobody joins a private channel by this route);
     4. caller is a `guest` of the workspace -> `403`;
     5. caller is not a workspace member: if `join_mode == "open"`, add them as role `member`
        and continue; if `"invite_only"` -> `403`;
     6. `add_channel_member` -> `200`.

A2.7 Joining an unknown channel id -> `404`; joining a private channel -> `403`.
