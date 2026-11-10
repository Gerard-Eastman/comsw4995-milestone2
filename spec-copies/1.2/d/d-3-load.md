# D3. WebSocket delivery under load (Spec D, step 3 of 3)

Check: `bash /spec/d/checks/check_d_3.sh` (rules D3.1-D3.3). Architecture, conventions and the basics: `/spec/base/base.md`.

Start this step only after `bash /spec/d/checks/check_d_2.sh` reports `0 failed`. Call the functions listed under **Uses**; do not write second versions of them.

What this step checks: latency and loss of `message.created` delivery while all three nodes
take writes at the same time.

**Uses:** `emit_event`, the event pump (base.md section 4), WebSocket `subscribe`.

**Adds:**

| Function | What it does |
|---|---|
| `send_to_subscribers(payload)` (ws.py) | Sends one frame to every local subscriber of its channel; a failed send to one socket is caught and must not stop delivery to the others |

Keep the pump interval at 50 ms, read new events in one query per tick, and never block the
event loop on slow work inside the pump. Each POST must commit its event before returning.

**Rules**

D3.1 Three subscribers (one per node) on one channel, while 3 writers (one per node) post 30
     messages each at the same time: every subscriber receives every `message.created`
     (at most 1% missing), and each post returns `201`.

D3.2 Over all those deliveries, the time from sending the POST to the subscriber receiving the
     frame has a median of at most 300 ms and a 95th percentile of at most 800 ms.

D3.3 Each subscriber receives the frames of the channel in strictly increasing, dense
     `event_id` order with no duplicates.
