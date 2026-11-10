# B5. WebSocket events and ordering (Spec B, step 5 of 5)

Rules B5.1-B5.9; the regression suite `bash /spec/checks/regression.sh` checks them. Architecture, conventions and the basics: `/spec/base/base.md`.

Start this step only after `bash /spec/checks/regression.sh` reports `0 failed` / `0 broken`. Call the functions listed under **Uses**; do not write second versions of them.

Route: `GET /api/ws?token=<bearer>` (WebSocket); plus `PATCH /api/messages/{id}`,
`DELETE /api/messages/{id}`, `POST /api/messages/{id}/reactions`,
`DELETE /api/messages/{id}/reactions/{emoji}` as event producers. File: `/app/ws.py` (and
`/app/routes_messages.py` for the four routes).

**Uses:** `emit_event` and the `events` table (base.md section 4), `can_read_channel`,
`channel_by_id`, `message_by_id`, `message_to_json`.

**Adds:**

| Function | What it does |
|---|---|
| `ws_handler(request)` | Token check before upgrade (bad -> plain HTTP `401`), then reads JSON frames |
| `event_pump(app)` | The 50 ms poller from base.md section 4 |
| `SUBSCRIBERS` | dict `channel_id -> set of ws`; plus per-ws dict `channel_id -> last event_id sent` |

**Rules**

B5.1 Client sends `{"type": "subscribe", "channel_id": <id>}`. If the user can read the
     channel, register the subscription, set "last sent" for it to the channel's current
     `last_event_id`, and reply `{"type": "subscribed", "channel_id": <id>, "head_event_id":
     <last_event_id>}`. Otherwise reply `{"type": "error", ...}`. From then on every durable
     event of that channel reaches the socket, whichever node committed it, as the stored
     payload `{"type", "event_id", "channel_id", ...}`; message events carry `"message":
     MessageObj`.

B5.2 `event_id` is dense: with posts on alternating nodes, a subscriber sees `head+1, head+2,
     ...` with no gaps and no duplicates (the "last sent" per channel prevents duplicates).

B5.3 Kinds and payloads: `message.created` / `message.reply` / `message.updated`
     `{"message": MessageObj}`; `message.deleted` `{"message_id"}`; `reaction.added` /
     `reaction.removed` `{"message_id", "emoji", "user_id", "reactions"}`; `member.joined`
     `{"user_id", "user"}`; `member.left` `{"user_id"}`; `channel.updated` /
     `channel.archived` / `channel.unarchived` `{"channel": ChannelObj}`.

B5.4 Client sends `{"type": "resume", "channel_id": <id>, "since_event_id": <n>}` (any node):
     register the subscription with "last sent" = a huge number (pauses live delivery), send
     every stored payload with `event_id > n` in order, set "last sent" to the last one
     replayed, send any events committed meanwhile, then send `{"type": "resumed",
     "channel_id": <id>, "head_event_id": <last event_id>}`. Live events continue afterwards.
     All events are kept, so `{"type": "resume.gap", "channel_id", "earliest_event_id"}` is
     only needed if `n` is negative.

B5.5 Event producers (simple routes, all emit one event each):
     - `PATCH /api/messages/{id}` `{body}` -> `200 {message}` with `edited_at` set; author only
       (`403`); never existed -> `404`; already deleted -> `409`; empty body `400`; emits
       `message.updated`.
     - `DELETE /api/messages/{id}` -> `200 {"deleted": true}`; author or workspace owner
       (`403`); idempotent (a second delete is `200` and emits nothing); marks `deleted = 1`;
       emits `message.deleted`.
     - `POST /api/messages/{id}/reactions` `{emoji}` -> `200 {reactions}`; idempotent per (user,
       emoji); emits `reaction.added` only when it was new.
     - `DELETE /api/messages/{id}/reactions/{emoji}` -> `200 {reactions}`; emits
       `reaction.removed` only when something was removed.

B5.6 **Archived channels are read-only.** While a channel is archived, these writes -> `423`:
     `POST /api/channels/{id}/messages`, `PATCH /api/messages/{id}` (edit),
     `PATCH /api/channels/{id}` (topic), `POST /api/messages/{id}/pin`,
     `POST /api/messages/{id}/reactions` (with valid bodies). Follow the order in base.md
     section 5: auth (401), existence (404), permission (403), body validation (400), then
     archived (423). Reads (`GET .../messages`, `GET .../pins`) still return `200`. After
     unarchive, every write works again.

B5.7 **Private channels stay private on the WebSocket.** `subscribe` or `resume` for a channel
     the user cannot read (`can_read_channel` is false, e.g. a private channel they are not in)
     -> reply `{"type": "error", "channel_id": <id>, "error": "forbidden"}`, do **not** register
     the subscription, and never send that channel's events to that socket. Check this in both
     the `subscribe` and the `resume` branch.

B5.8 **Dense under concurrency.** 30 posts sent at the same moment, spread over all three
     nodes, all return `201`, and a subscriber receives `message.created` with exactly
     `head+1 ... head+30`, in increasing order, no gaps, no duplicates. `emit_event`'s single
     `BEGIN IMMEDIATE` ... `COMMIT` (base.md section 4) is what guarantees this: never read
     `last_event_id` in one statement and write it back in another outside that transaction.

B5.9 **Every Component B route needs a token.** No header or an unknown token -> `401`, before
     anything else, on: `GET /api/workspaces/{slug}`, `PATCH /api/channels/{id}`,
     `POST /api/channels/{id}/leave`, `GET /api/channels/{id}/members`,
     `POST /api/channels/{id}/archive` and `/unarchive`, `POST` and
     `GET /api/channels/{id}/messages`, `GET /api/messages/{id}/replies`, `PATCH` and
     `DELETE /api/messages/{id}`, `POST /api/messages/{id}/reactions`,
     `DELETE /api/messages/{id}/reactions/{emoji}`, `POST` and `DELETE /api/messages/{id}/pin`,
     `GET /api/channels/{id}/pins`, `GET /api/search`, `GET` and `POST /api/channels/{id}/read`.
