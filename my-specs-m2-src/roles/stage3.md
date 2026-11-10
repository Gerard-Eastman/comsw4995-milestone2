## A3. Roles, ownership transfer, and role-based channel permissions

Routes: `PATCH /api/workspaces/{slug}/members/{user_id}`,
`POST /api/workspaces/{slug}/transfer_ownership`, and the permission part of
`POST /api/workspaces/{slug}/channels` (the full channel-create rules are in B1).

**Uses:** `workspace_by_slug`, `role_of`, `workspace_to_json`, `create_channel`,
`channel_to_json`, `require_user`, `HTTPError`.

**Adds:**

| Function | What it does |
|---|---|
| `member_to_json(workspace_id, user_id)` | `{user_id, role, joined_at, user: UserObj}` |
| `require_role(workspace_id, user_id, allowed)` | `HTTPError(403)` unless `role_of(...)` is in `allowed` |

**Rules**

A3.1 `PATCH /api/workspaces/{slug}/members/{user_id}` `{role}` -> `200 {member: {user_id, role, ...}}`
     and the new role shows in `GET .../members`. Decide in this order:
     1. caller's role is not `owner` or `admin` -> `403`;
     2. `role` is `"owner"` -> `400` (use transfer_ownership); `role` not one of
        `admin/member/guest` -> `400`;
     3. target (`user_id` in the path) is not a workspace member -> `404`;
     4. target is the current owner -> `403` (nobody changes the owner by PATCH, not even the
        owner themself);
     5. caller is `admin` and target is another `admin` -> `403`;
     6. update and return `200`.

A3.2 So an admin may set any `member`/`guest` to `member`, `guest` or `admin`.

A3.3 Admin changing another admin -> `403`. Anyone changing the owner -> `403`.

A3.4 `role: "owner"` -> `400`; `role: "superuser"` -> `400`; a `member` or `guest` calling PATCH -> `403`.

A3.5 PATCH for a user who is not in the workspace -> `404`.

A3.6 `POST /api/workspaces/{slug}/transfer_ownership` `{new_owner_id}` -> `200 {workspace}`.
     Caller not the owner -> `403`. Target not currently an `admin` (including not a member) ->
     `400`. On success, in one step: target role -> `owner`, previous owner role -> `admin`,
     `workspaces.owner_id` -> target.

A3.7 A `guest`: `POST /api/channels/{id}/join` on a public channel -> `403`;
     `POST /api/workspaces/{slug}/channels` -> `403`.

A3.8 Channel creation permission: not a workspace member or `guest` -> `403`; `member` may
     create public channels but `{is_private: true}` -> `403`; `admin` and `owner` may create
     both. (Check permission before the 400/409 checks of B1.)
