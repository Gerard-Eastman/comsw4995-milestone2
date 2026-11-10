# D2. A killed Redis (Spec D, step 2 of 3)

Check: `bash /spec/d/checks/check_d_2.sh` (rules D2.1-D2.4). Architecture, conventions and the basics: `/spec/base/base.md`.

Start this step only after `bash /spec/d/checks/check_d_1.sh` reports `0 failed`. Call the functions listed under **Uses**; do not write second versions of them.

What this step checks: `start.sh` runs Redis on `127.0.0.1:6379` and respawns it, and the app
does not depend on it (base.md section 1: events travel through the shared SQLite file, not
Redis pub/sub).

**Uses:** `start.sh` (base.md section 2), the event pump, WebSocket `subscribe`.

**Adds:** nothing new if you followed base.md. If your app imports a Redis client anywhere,
remove that dependency: a request or the pump must never wait on Redis.

**Rules**

D2.1 `redis-server` is listening on `127.0.0.1:6379`.

D2.2 Right after `redis-server` is `SIGKILL`ed, posts on **each** of the three nodes still
     return `201` within 5 seconds.

D2.3 During the Redis outage, a WebSocket subscriber on another node still receives those
     `message.created` frames within 5 seconds, with dense `event_id`s (no gap, no duplicate).

D2.4 `start.sh` respawns Redis: port 6379 is listening again within 10 seconds, and delivery
     keeps working afterwards.
