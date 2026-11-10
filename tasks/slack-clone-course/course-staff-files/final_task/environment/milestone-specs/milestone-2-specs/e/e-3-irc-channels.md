# E3. IRC gateway: channels and bridging (Spec E, step 3 of 7)

Check: `bash /spec/e/checks/check_e_3.sh` (rules E3.1-E3.6). Architecture, conventions and the basics: `/spec/base/base.md`.

Start this step only after `bash /spec/e/checks/check_e_2.sh` reports `0 failed`. Call the functions listed under **Uses**; do not write second versions of them.

File: `/app/irc.py`.

**Uses:** E2's connection handling, `emit_event` (common.py), the channel/membership tables,
the read-access rule from the basics.

**Adds:**

| Function | What it does |
|---|---|
| `irc_name(channel_row)` | `"#" + workspace.slug + "/" + channel.name` (DM channels have no IRC name) |
| `find_channel(irc_name)` | Parses `#<slug>/<name>` (exactly one `/`); returns the channel row or `None` |
| `irc_pump()` | Every 50 ms reads new rows of `events` (start at the current `MAX(seq)`) and relays `message.created` to joined IRC clients |

Each connection keeps the set of channel ids it joined and the ids of messages it posted
itself (so its own PRIVMSG is not echoed back to it).

**Rules**

E3.1 `JOIN #<workspace-slug>/<channel-name>` for a channel the user can read (joining a public
     channel adds the user as a member, like the HTTP join, and emits `member.joined`) sends,
     in this order: `:<nick>!<username>@huddle JOIN #slug/name`, then `332 <nick> #slug/name :<topic>`
     (or `331 <nick> #slug/name :No topic is set`), then `353 <nick> = #slug/name :<names>`
     (space-separated usernames of the channel members, using the caller's nick for the
     caller), then `366 <nick> #slug/name :End of /NAMES list`.

E3.2 `JOIN` of an unknown channel, a private channel the user is not in, or a hyphenated form
     such as `#acme-general` -> `:huddle 403 <nick> <name> :No such channel`.

E3.3 `NAMES #c` -> `353` + `366`; `TOPIC #c` -> `332` or `331`; `WHO #c` -> one `352` per member
     then `315`; `LIST` -> `321`, one `322 <nick> #slug/name <count> :<topic>` per readable
     non-DM channel in the user's workspaces, then `323`; `MODE #c` -> `324 <nick> #c +`; `MODE
     <nick>` -> `221 <nick> +`. None of these closes the connection.

E3.4 `PRIVMSG #slug/name :<text>` from a joined client inserts a normal top-level message
     (author = the connection's user) and calls `emit_event(channel_id, "message.created",
     {"message": MessageObj})`, exactly like `POST /api/channels/{id}/messages`. Web
     WebSocket subscribers receive it with the next dense `event_id`; mixed web and IRC writers
     keep the per-channel `event_id` dense. `PRIVMSG` to a channel the client has not joined
     -> `:huddle 442 <nick> #c :You're not on that channel`.

E3.5 A message posted through HTTP (on any node) reaches every IRC client joined to that
     channel, within 2 seconds, as `:<username>!<username>@huddle PRIVMSG #slug/name :<body>`
     (newlines in `body` replaced by spaces). Messages a client posted itself are not echoed to
     it; other IRC clients in the channel receive them with the sender's nick as prefix.

E3.6 Bridging survives a killed HTTP node: with node 1 `SIGKILL`ed, a message posted on port
     8000 still reaches IRC clients, and an IRC `PRIVMSG` still reaches WebSocket subscribers on
     port 8002 (the gateway never talks to the HTTP nodes, only to the database).
