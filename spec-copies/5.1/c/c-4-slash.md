# C4. Slash commands (Spec C, step 4 of 6)

Check: `bash /spec/c/checks/check_c_4.sh` (rules C4.1-C4.6). Architecture, conventions and the basics: `/spec/base/base.md`.

Start this step only after `bash /spec/c/checks/check_c_3.sh` reports `0 failed`. Call the functions listed under **Uses**; do not write second versions of them.

Route: `POST /api/channels/{id}/messages` when `body` starts with `/`. File:
`/app/routes_messages.py`.

**Uses:** the message post route, `emit_event`, the channel topic/archive/unarchive logic and
`add_channel_member` (or your equivalent) from the basics.

**Adds:**

| Function | What it does |
|---|---|
| `run_slash(user_id, channel_row, body)` | Returns `None` for a normal message, or the response dict for a side-effect command |

Parse `cmd, _, text = body[1:].partition(" ")` and `text = text.strip()`. Check the slash
command **before** the archived (`423`) check, because `/unarchive` must work in an archived
channel. Auth, channel existence and read access are checked first as usual.

**Rules**

C4.1 `//rest` is not a command: post a normal message whose `body` is `"/rest"` (one leading
     slash removed). `/me <text>` posts a normal message whose `body` is exactly `"/me <text>"`
     (unchanged). `/me` with no text -> `400`.

C4.2 `/shrug <text>` posts a normal message whose `body` is `"<text> ¯\_(ツ)_/¯"`; `/shrug`
     alone posts `"¯\_(ツ)_/¯"`. The emoticon has exactly one backslash:
     `"¯\\_(ツ)_/¯"` as a Python string literal.

C4.3 `/topic <text>` sets the channel topic (same rules as `PATCH /api/channels/{id}`: <= 250
     chars else `400`, emits `channel.updated`) and returns `201 {"message": null, "channel": ChannelObj}`.
     `/topic` with no text sets the topic to `""`.

C4.4 `/invite @username` adds that user to the channel (emits `member.joined`) and returns
     `201 {"message": null, "invited_user": UserObj}`. This is how users get into **private**
     channels. Only a channel member may invite (`403`). Missing `@username` -> `400`; unknown
     user -> `404`; a user who is not a member of the channel's workspace -> `400`. Inviting a
     current member is still `201`.

C4.5 `/archive` and `/unarchive` behave like the archive/unarchive routes (workspace owner
     only, else `403`) and return `201 {"message": null, "channel": ChannelObj}` with the new
     `is_archived`. `/unarchive` works in an archived channel; any other message or command
     posted to an archived channel -> `423`.

C4.6 Any other `/word` command (for example `/foo`) -> `400`, and nothing is posted.
     Normal messages from `/me`, `/shrug` and `//` are returned as `201 {message}` like any
     message and emit `message.created`.
