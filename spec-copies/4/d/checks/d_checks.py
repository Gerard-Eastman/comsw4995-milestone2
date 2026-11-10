"""Component D checks: a killed HTTP node, a killed Redis, WebSocket delivery under load.
Usage: python3 d_checks.py <stage>   (stage 1..3, or nothing for all)"""
import os, sys, time, json, threading, statistics
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import *  # noqa
set_comp("d")


def setup():
    o = new_user("own")
    ws = new_workspace(o)
    ch = new_channel(ws, o)
    return o, ws, ch["id"]


def kill_port(port):
    pid = pid_on_port(port)
    expect(pid is not None, f"could not find the PID listening on {port} (ss -ltnp)")
    os.kill(pid, 9)
    end = time.time() + 3
    while time.time() < end and port_open(port):
        time.sleep(0.1)
    return pid


def wait_node(i, sec):
    end = time.time() + sec
    while time.time() < end:
        if healthy(i):
            return True
        time.sleep(0.3)
    return False


def ensure_all_up():
    for i in range(3):
        if not healthy(i):
            expect(wait_node(i, 6), f"node {i} (port {8000 + i}) is not up before the test: it did not come back after the last kill (respawn loop missing in start.sh?)")


def created_frames(frames):
    return [f for f in frames if f.get("type") == "message.created"]


# ======================================================================= D1 killed node
@rule("D1.1", "with node 1 SIGKILLed, nodes 0 and 2 still serve login, GET messages and POST messages", 1)
def _():
    ensure_all_up()
    o, ws, cid = setup()
    kill_port(8001)
    for n in (0, 2):
        want(call("POST", "/api/auth/login", {"username": o["username"], "password": PW}, node=n), 200, f"login on {8000 + n} while 8001 is down")
        want(call("GET", f"/api/channels/{cid}/messages", token=o["token"], node=n), 200, f"GET messages on {8000 + n} while 8001 is down")
        want(call("POST", f"/api/channels/{cid}/messages", {"body": f"while down {n}"}, o["token"], node=n), 201, f"POST message on {8000 + n} while 8001 is down")


@rule("D1.2", "with node 1 down, a subscriber on 8000 gets message.created (next dense event_id) for a post on 8002", 1)
def _():
    ensure_all_up()
    o, ws, cid = setup()
    kill_port(8001)
    c = ws_connect(o["token"], node=0)
    try:
        head = ws_subscribe(c, cid)
        m = post(o, cid, "cross while down", node=2)
        f, seen = ws_recv_until(c, lambda f: f.get("type") == "message.created", 3)
        expect(f is not None, f"no message.created on 8000 within 3s for a post on 8002 (saw {[x.get('type') for x in seen]})")
        expect(f.get("event_id") == head + 1 and same((f.get("message") or {}).get("id"), m["id"]),
               f"expected event_id {head + 1} for message {m['id']}, got {str(f)[:160]}")
    finally:
        c.close()


@rule("D1.3", "a client of the killed node reconnects to 8002, sends resume, gets every missed event in order then resumed", 1)
def _():
    ensure_all_up()
    o, ws, cid = setup()
    c = ws_connect(o["token"], node=1)
    try:
        ws_subscribe(c, cid)
        post(o, cid, "before kill", node=0)
        f, _ = ws_recv_until(c, lambda f: f.get("type") == "message.created", 3)
        expect(f is not None, "setup: subscriber on 8001 got no message.created")
        last = f["event_id"]
        kill_port(8001)
    finally:
        try:
            c.close()
        except Exception:
            pass
    missed = [post(o, cid, f"missed {i}", node=i % 2 * 2)["id"] for i in range(3)]
    c = ws_connect(o["token"], node=2)
    try:
        c.send(json.dumps({"type": "resume", "channel_id": cid, "since_event_id": last}))
        f, seen = ws_recv_until(c, lambda f: f.get("type") == "resumed", 4)
        expect(f is not None, f"no 'resumed' frame within 4s on 8002 (saw {[x.get('type') for x in seen]})")
        got = [x for x in seen if x.get("type") == "message.created"]
        expect([x.get("event_id") for x in got] == [last + 1, last + 2, last + 3],
               f"replay should be event_ids {[last + 1, last + 2, last + 3]}, got {[x.get('event_id') for x in got]}")
        expect([str((x.get("message") or {}).get("id")) for x in got] == [str(i) for i in missed], "replayed messages are not the missed ones, in order")
        expect(f.get("head_event_id") == last + 3, f"resumed.head_event_id should be {last + 3}: {f}")
    finally:
        c.close()


@rule("D1.4", "node 1 comes back by itself within 15s, serves what was posted meanwhile, and delivers new events", 1)
def _():
    ensure_all_up()
    o, ws, cid = setup()
    kill_port(8001)
    m = post(o, cid, "posted while 8001 was down", node=0)
    t0 = time.time()
    expect(wait_node(1, 15), "node 1 (8001) did not come back within 15s; run each node in a respawn loop in start.sh")
    r = want(call("GET", "/api/health", node=1), 200, "health on 8001")
    expect(r.body.get("node_id") == 1, f"8001 should report node_id 1: {r.text[:80]}")
    r = want(call("GET", f"/api/channels/{cid}/messages", token=o["token"], node=1), 200, "GET messages on the restarted node")
    expect(any(same(x.get("id"), m["id"]) for x in r["messages"]), "the restarted node does not show the message posted while it was down")
    c = ws_connect(o["token"], node=1)
    try:
        head = ws_subscribe(c, cid)
        post(o, cid, "after restart", node=2)
        f, seen = ws_recv_until(c, lambda f: f.get("type") == "message.created", 3)
        expect(f is not None and f.get("event_id") == head + 1,
               f"a subscriber on the restarted node should get message.created with event_id {head + 1} (saw {[(x.get('type'), x.get('event_id')) for x in seen]})")
    finally:
        c.close()


# ======================================================================= D2 killed Redis
@rule("D2.1", "redis-server is listening on 127.0.0.1:6379", 2)
def _():
    end = time.time() + 5
    while time.time() < end and not port_open(6379):
        time.sleep(0.3)
    expect(port_open(6379), "nothing is listening on 6379: start.sh must run (and respawn) redis-server --port 6379")


@rule("D2.2", "right after redis-server is SIGKILLed, posts on each of the three nodes return 201 within 5s", 2)
def _():
    ensure_all_up()
    expect(port_open(6379), "redis is not running before the test (see D2.1)")
    o, ws, cid = setup()
    kill_port(6379)
    t0 = time.time()
    for n in range(3):
        r = call("POST", f"/api/channels/{cid}/messages", {"body": f"no redis {n}"}, o["token"], node=n)
        expect(r.status == 201, f"post on {8000 + n} during the Redis outage: expected 201, got {r.short()}")
    expect(time.time() - t0 < 5, f"the three posts took {time.time() - t0:.1f}s (limit 5s): do requests wait on Redis?")


@rule("D2.3", "during the Redis outage a subscriber on another node gets those message.created frames, dense, within 5s", 2)
def _():
    ensure_all_up()
    o, ws, cid = setup()
    c = ws_connect(o["token"], node=1)
    try:
        head = ws_subscribe(c, cid)
        if port_open(6379):
            kill_port(6379)
        for n in (0, 2, 0):
            want(call("POST", f"/api/channels/{cid}/messages", {"body": f"outage {n}"}, o["token"], node=n), 201, f"post on {8000 + n} during outage")
        got, end = [], time.time() + 5
        while len(got) < 3 and time.time() < end:
            f, seen = ws_recv_until(c, lambda f: f.get("type") == "message.created", end - time.time())
            got += created_frames(seen)
        evs = [g.get("event_id") for g in got]
        expect(evs == [head + 1, head + 2, head + 3], f"subscriber on 8001 should get event_ids {[head + 1, head + 2, head + 3]} within 5s, got {evs}")
    finally:
        c.close()


@rule("D2.4", "start.sh respawns Redis within 10s, and delivery keeps working afterwards", 2)
def _():
    ensure_all_up()
    if port_open(6379):
        kill_port(6379)
    end = time.time() + 10
    while time.time() < end and not port_open(6379):
        time.sleep(0.3)
    expect(port_open(6379), "redis-server did not come back within 10s: run it in a respawn loop in start.sh")
    o, ws, cid = setup()
    c = ws_connect(o["token"], node=2)
    try:
        head = ws_subscribe(c, cid)
        post(o, cid, "after redis is back", node=0)
        f, seen = ws_recv_until(c, lambda f: f.get("type") == "message.created", 3)
        expect(f is not None and f.get("event_id") == head + 1, f"no message.created after Redis came back (saw {[x.get('type') for x in seen]})")
    finally:
        c.close()


# ======================================================================= D3 load
_load = {}


def load_test():
    """3 subscribers (one per node), 3 writers x 30 posts concurrently. Cached for D3.1-D3.3."""
    if _load:
        return _load
    ensure_all_up()
    o, ws, cid = setup()
    writers = [o] + [add_member(ws, o) for _ in range(2)]
    for w in writers[1:]:
        want(join(w, cid), 200, "setup: writer joins channel")
    subs, frames, stop = [], [[] for _ in range(3)], threading.Event()
    heads = []
    for n in range(3):
        c = ws_connect(o["token"], node=n)
        heads.append(ws_subscribe(c, cid))
        subs.append(c)

    def reader(i):
        c = subs[i]
        while not stop.is_set():
            try:
                raw = c.recv(timeout=0.2)
            except TimeoutError:
                continue
            except Exception:
                break
            try:
                f = json.loads(raw)
            except ValueError:
                continue
            if f.get("type") == "message.created":
                frames[i].append((time.time(), f))

    readers = [threading.Thread(target=reader, args=(i,), daemon=True) for i in range(3)]
    for t in readers:
        t.start()
    sent, statuses, lock = {}, [], threading.Lock()

    def writer(i):
        import requests as rq
        s = rq.Session()
        for k in range(30):
            body = f"load w{i} #{k} {rid(4)}"
            t0 = time.time()
            try:
                r = s.post(f"{NODES[i]}/api/channels/{cid}/messages", json={"body": body},
                           headers={"Authorization": f"Bearer {writers[i]['token']}"}, timeout=5)
                st = r.status_code
                mid = r.json().get("message", {}).get("id") if st == 201 else None
            except Exception:
                st, mid = 0, None
            with lock:
                statuses.append(st)
                if mid is not None:
                    sent[str(mid)] = t0

    ws_threads = [threading.Thread(target=writer, args=(i,)) for i in range(3)]
    for t in ws_threads:
        t.start()
    for t in ws_threads:
        t.join(20)
    time.sleep(1.5)
    stop.set()
    for t in readers:
        t.join(1)
    for c in subs:
        try:
            c.close()
        except Exception:
            pass
    lat, missing, order_ok, why = [], 0, True, ""
    for i in range(3):
        got = {}
        for t, f in frames[i]:
            mid = str((f.get("message") or {}).get("id"))
            if mid in sent and mid not in got:
                got[mid] = t
                lat.append((t - sent[mid]) * 1000)
        missing += sum(1 for mid in sent if mid not in got)
        evs = [f.get("event_id") for _, f in frames[i]]
        if evs != list(range(heads[i] + 1, heads[i] + 1 + len(evs))) and order_ok:
            order_ok = False
            bad = next((j for j in range(len(evs)) if evs[j] != heads[i] + 1 + j), 0)
            why = f"subscriber on {8000 + i}: event_ids around position {bad}: {evs[max(0, bad - 2):bad + 3]} (expected {heads[i] + 1 + bad} at {bad})"
    _load.update(statuses=statuses, sent=len(sent), missing=missing, expected=len(sent) * 3, lat=sorted(lat),
                 order_ok=order_ok, why=why, counts=[len(f) for f in frames])
    return _load


@rule("D3.1", "3 writers x 30 concurrent posts: every post 201, each of 3 subscribers misses at most 1% of message.created", 3)
def _():
    L = load_test()
    bad = [s for s in L["statuses"] if s != 201]
    expect(not bad, f"{len(bad)} of {len(L['statuses'])} posts did not return 201 (statuses {sorted(set(bad))})")
    expect(L["expected"] > 0 and L["missing"] <= 0.01 * L["expected"],
           f"{L['missing']} of {L['expected']} expected deliveries missing (limit 1%); frames per subscriber {L['counts']}")


@rule("D3.2", "delivery latency POST -> subscriber: median <= 300 ms, p95 <= 800 ms", 3)
def _():
    L = load_test()
    lat = L["lat"]
    expect(lat, "no deliveries measured")
    med = statistics.median(lat)
    p95 = lat[min(len(lat) - 1, int(round(0.95 * len(lat))) - 1)]
    expect(med <= 300 and p95 <= 800, f"median {med:.0f} ms (limit 300), p95 {p95:.0f} ms (limit 800)")


@rule("D3.3", "each subscriber gets the channel's frames in strictly increasing, dense event_id order, no duplicates", 3)
def _():
    L = load_test()
    expect(L["order_ok"], L["why"] or "event_ids out of order")


if __name__ == "__main__":
    run()
