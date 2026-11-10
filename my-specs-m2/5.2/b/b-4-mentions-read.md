# B4. Mentions and read state (Spec B, step 4 of 5)

Rules B4.1-B4.6; the regression suite `bash /spec/checks/regression.sh` checks them. Architecture, conventions and the basics: `/spec/base/base.md`.

Start this step only after `bash /spec/checks/regression.sh` reports `0 failed` / `0 broken`. Call the functions listed under **Uses**; do not write second versions of them.

Routes: `GET /api/channels/{id}/read`, `POST /api/channels/{id}/read`; mention resolution
inside `POST /api/channels/{id}/messages`. File: `/app/routes_messages.py`.

**Uses:** `resolve_mentions` (fill it in now), `read_state_for` (fill it in now),
`channel_by_id`, `can_read_channel`, `role_of`.

**Adds:**

| Function | What it does |
|---|---|
| `MENTION_RE` | `re.compile(r"(?<![A-Za-z0-9_@.])@([A-Za-z0-9_]+)(?![A-Za-z0-9_@])(?!\.[A-Za-z0-9])")` |

**Rules**

B4.1 `resolve_mentions(body, channel, author_id)`: for each `MENTION_RE` match, the name is
     looked up as a username; keep it only if that user is a member of the channel's
     workspace. The regex already rejects in-word (`x@bob`) and email-shaped (`bob@example.com`)
     forms. Remove the author's own id. Deduplicate, keeping first-seen order. Store the list
     on the message and return it as `mentions`.

B4.2 `@channel` expands to every current channel member, then the author is removed and the
     list deduplicated as above.

B4.3 `GET /api/channels/{id}/read` -> `200 {read_state: {channel_id, last_read_event_id,
     unread_count, mention_count}}` (caller must pass `can_read_channel`, `403`). A user who
     just joined has `unread_count` 0 and `mention_count` 0, because `add_channel_member` sets
     `last_read_event_id` to the `member.joined` event id.

B4.4 `read_state_for(channel_id, user_id)`: `last_read_event_id` = the stored value (0 if no
     membership row). `unread_count` = non-deleted messages in the channel (top-level and
     replies) with `event_id > last_read_event_id` and `author_id != user_id`.
     `mention_count` = those of them whose `mentions` contain `user_id`. Own messages and
     self-mentions never count.

B4.5 `POST /api/channels/{id}/read` `{last_read_event_id}` (integer >= 0, else `400`) ->
     `200 {read_state}`. Clamp the value to the channel's `last_event_id`, then store
     `MAX(old, new)` so it never moves backwards. Then counts drop to 0 when you mark the head
     as read. `GET /api/workspaces/{slug}` embeds the same objects in its `read_state` list (B1.3).

B4.6 **Dedup across mention forms.** A body containing both `@bob` and `@channel` lists bob's
     id exactly once, and never the author's.
