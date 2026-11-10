## A4. Invitations and join mode

Routes: `POST/GET /api/workspaces/{slug}/invitations`,
`DELETE /api/workspaces/{slug}/invitations/{code}`, `POST /api/invitations/{code}/accept`,
`PATCH /api/workspaces/{slug}`.

**Uses:** `workspace_by_slug`, `role_of`, `require_role`, `add_workspace_member`,
`add_channel_member`, `member_to_json`, `workspace_to_json`.

**Adds:**

| Function | What it does |
|---|---|
| `invitation_to_json(row)` | `{code, workspace_id, created_by, max_uses, uses, expires_at, invited_user_id, created_at}` |
| `invitation_is_active(row)` | not revoked, `uses < max_uses`, and not expired |

Table: `invitations(code TEXT PRIMARY KEY, workspace_id, created_by, max_uses, uses, expires_at REAL, invited_user_id, revoked INTEGER DEFAULT 0, created_at)`.
Store `expires_at` as a unix time (`time.time() + expires_in_seconds`) or NULL.

**Rules**

A4.1 `POST /api/workspaces/{slug}/invitations` `{expires_in_seconds?, max_uses?, invited_username?, invited_user_id?}`
     -> `201 {invitation}` with a random `code` (`secrets.token_urlsafe(12)`). Only `owner`/`admin`
     (else `403`). `max_uses` must be an integer >= 1 (`400`). `invited_username` is resolved to
     a user id (unknown username -> `400`).

A4.2 `POST /api/invitations/{code}/accept` -> `200 {workspace, member}`: consumes one use, adds
     the caller as role `member` (if not already a member) and joins them to `#general` with
     `add_channel_member`. `max_uses` defaults to `1`, so a second user accepting the same
     default invitation -> `404`.

A4.3 With `max_uses: 2`, exactly two accepts succeed; the third -> `404`. An unknown code -> `404`.

A4.4 A targeted invitation (`invited_user_id` or `invited_username`) always has `max_uses` 1.
     Accept by a different user -> `403` (and does not consume it); by the target -> `200`.
     Order on accept: unknown/expired/exhausted/revoked -> `404`, then wrong user -> `403`.

A4.5 With `expires_in_seconds: 1`, accepting 2 seconds later -> `404`.

A4.6 `GET /api/workspaces/{slug}/invitations` -> `200 {invitations: [...]}` listing only active
     invitations. Only `owner`/`admin` (else `403`).

A4.7 `DELETE /api/workspaces/{slug}/invitations/{code}` -> `200 {"deleted": true}` and the code
     is revoked: accepting it -> `404`, and it is no longer listed. Only `owner`/`admin` (`403`);
     unknown code -> `404`.

A4.8 `PATCH /api/workspaces/{slug}` with any subset of `{name, join_mode}` -> `200 {workspace}`
     with the new values. Only `owner`/`admin` (`403` first). `join_mode` not `"open"` or
     `"invite_only"` -> `400`; empty `name` -> `400`.

A4.9 In an `invite_only` workspace a non-member joining a public channel -> `403`. After that
     user accepts an invitation, the same join -> `200`.

A4.10 **Targeted invitations are single-use.** When `invited_user_id` or `invited_username` is
     set, store `max_uses = 1` whatever the body says, so the returned `invitation.max_uses` is
     `1` even for `{"invited_user_id": X, "max_uses": 5}`. After the target accepts once, a
     second accept by the same user -> `404`.

A4.11 **Every Component A route needs a token.** With no `Authorization` header, or with an
     unknown token, each of these returns `401`, checked before anything else (even when the
     slug, id or code exists): `GET` and `POST /api/workspaces`, `PATCH /api/workspaces/{slug}`,
     `GET /api/workspaces/{slug}/members`, `PATCH /api/workspaces/{slug}/members/{user_id}`,
     `POST /api/workspaces/{slug}/transfer_ownership`, `POST` and
     `GET /api/workspaces/{slug}/invitations`, `DELETE /api/workspaces/{slug}/invitations/{code}`,
     `POST /api/invitations/{code}/accept`, `POST /api/workspaces/{slug}/channels`,
     `POST /api/channels/{id}/join`. The simplest way: call `require_user(request)` on the first
     line of every handler.
