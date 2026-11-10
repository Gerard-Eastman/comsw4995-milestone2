## E2. IRC gateway: connection and registration

File: `/app/irc.py`, a separate process that `start.sh` already runs in a respawn loop (base.md
section 2). It listens on `0.0.0.0:6667` with `asyncio.start_server`, opens its own SQLite
connection (`db.connect()`), and uses the same tables and `emit_event` as the HTTP nodes.

Protocol basics: lines end in `\r\n` (accept `\n` too); the server name is `huddle`; every
server reply starts with `:huddle `. Commands are case-insensitive. A numeric reply looks like
`:huddle 001 <nick> :Welcome to Huddle, <nick>`. Before a nick is set, use `*` as the nick.

**Uses:** `connect()` (db.py), the `tokens` and `users` tables.

**Adds:**

| Function | What it does |
|---|---|
| `handle_client(reader, writer)` | One connection: reads lines, dispatches commands |
| `send(writer, line)` | Writes `line + "\r\n"` and drains |
| `NICKS` | dict lowercased nick -> connection, for collision checks (this process only) |

**Rules**

E2.1 `PASS <token>`, `NICK <nick>`, `USER <user> 0 * :<real name>` (PASS first) with a valid
     bearer token registers the client: the server sends numerics `001`, `002`, `003`, `004`,
     `005` (in that order), then `422` (`:huddle 422 <nick> :MOTD File is missing`). The
     connection is now logged in as the token's user. Registration completes when both NICK
     and USER have arrived.

E2.2 An unknown token (or no `PASS` at all) -> `:huddle 464 <nick> :Password incorrect` when
     registration would complete, then close the connection.

E2.3 `NICK <nick>` when another connected IRC client already uses that nick (case-insensitive)
     -> `:huddle 433 * <nick> :Nickname is already in use`, and the connection stays open: a
     following `NICK <other>` + `USER` completes registration normally.

E2.4 `PING <token>` -> `:huddle PONG huddle :<token>`. `PONG` is accepted silently. `QUIT`
     (with or without a message) closes the connection with no error reply and frees the nick.

E2.5 An unknown command (for example `FOOBAR`) -> `:huddle 421 <nick> FOOBAR :Unknown command`,
     and the connection stays open. Commands other than PASS/NICK/USER/PING/PONG/QUIT before
     registration -> `:huddle 451 * :You have not registered`.
