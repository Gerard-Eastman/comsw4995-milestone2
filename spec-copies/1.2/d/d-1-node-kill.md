# D1. A killed HTTP node (Spec D, step 1 of 3)

Check: `bash /spec/d/checks/check_d_1.sh` (rules D1.1-D1.4). Architecture, conventions and the basics: `/spec/base/base.md`.

What this step checks: the cluster from base.md keeps working when one HTTP node is
`SIGKILL`ed. If you followed base.md (shared SQLite file, events table polled by every node,
respawn loops in `start.sh`), most of this already works; this step proves it and makes you
fix what does not.

**Uses:** `start.sh` (base.md section 2), `emit_event` and the event pump (base.md section 4),
WebSocket `subscribe`/`resume`, the message routes from the basics.

**Adds:**

| Function | What it does |
|---|---|
| `cleanup_presence(node_id)` (ws.py) | Deletes this node's leftover `ws_presence` rows at startup (base.md section 4) |

Nothing in a request handler may depend on another node being alive: no node calls another
node, and each node only reads and writes the shared database.

**Rules**

D1.1 With node 1 (port 8001) `SIGKILL`ed, ports 8000 and 8002 still answer: login (`200`),
     `GET /api/channels/{id}/messages` (`200`) and `POST /api/channels/{id}/messages` (`201`).

D1.2 With node 1 down, a WebSocket subscriber on port 8000 receives `message.created` for a
     message posted on port 8002, with the next dense `event_id`.

D1.3 With node 1 down, a client that was subscribed on node 1 reconnects to port 8002 and
     sends `resume` with the last `event_id` it saw: it receives every missed event in order,
     then `resumed`.

D1.4 Node 1 comes back by itself (the respawn loop) and answers `GET /api/health` with
     `node_id: 1` well within 60 seconds (the check waits at most 15). Afterwards it serves
     the messages posted while it was down, and its WebSocket subscribers receive new events.
