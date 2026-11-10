"""Baseline checks: the four milestone 0 conditions plus cluster plumbing. Rules are in /spec/base.md."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import *  # noqa
set_comp("base")


@rule("0.1", "/app/start.sh is executable and /app/requirements.txt exists")
def _():
    expect(os.access("/app/start.sh", os.X_OK), "/app/start.sh missing or not executable (chmod +x)")
    expect(os.path.exists("/app/requirements.txt"), "/app/requirements.txt missing")


@rule("0.2", "GET /api/health on 8000 returns 200 {status: ok, node_id: 0}")
def _():
    r = want(call("GET", "/api/health"), 200, "health on 8000")
    expect(r.body == {"status": "ok", "node_id": 0} or (r["status"] == "ok" and r["node_id"] == 0),
           f"expected {{'status':'ok','node_id':0}}, got {r.text[:100]}")


@rule("0.3", "each node reports its own node_id (8000->0, 8001->1, 8002->2)")
def _():
    for i in range(3):
        r = want(call("GET", "/api/health", node=i), 200, f"health on {8000 + i}")
        expect(r["status"] == "ok" and r["node_id"] == i, f"port {8000 + i} answered {r.text[:100]}, want node_id {i} as an int")


@rule("0.4", "WebSocket with an invalid token is rejected at the handshake")
def _():
    try:
        c = ws_connect("not-a-real-token-000000")
    except Exception:
        return  # rejected: good
    c.close()
    raise CheckFail("the WebSocket handshake succeeded with a bogus token; reply 401 before upgrading instead")


@rule("0.5", "WebSocket with a valid token connects on all three nodes")
def _():
    u = new_user("wsok")
    for i in range(3):
        try:
            c = ws_connect(u["token"], node=i)
            c.close()
        except Exception as e:
            raise CheckFail(f"valid token rejected on port {8000 + i}: {type(e).__name__} {str(e)[:100]}")


@rule("0.6", "a token from one node works on the other two (shared state)")
def _():
    u = new_user("x", node=0)
    for i in (1, 2):
        want(call("GET", "/api/auth/me", token=u["token"], node=i), 200, f"/api/auth/me on {8000 + i}")


@rule("0.7", "redis-server is listening on 127.0.0.1:6379")
def _():
    expect(port_open(6379), "nothing listening on 6379; start.sh must start (and respawn) redis-server")


@rule("0.8", "after SIGKILL of node 1, nodes 0 and 2 keep answering and node 1 comes back by itself")
def _():
    pid = pid_on_port(8001)
    expect(pid is not None, "could not find the PID listening on 8001 with `ss -ltnp`")
    os.kill(pid, 9)
    time.sleep(0.5)
    for i in (0, 2):
        r = call("GET", "/api/health", node=i)
        expect(r.status == 200 and isinstance(r.body, dict) and r.body.get("status") == "ok",
               f"port {8000 + i} stopped answering after node 1 was killed ({r.short()})")
    end = time.time() + 12
    while time.time() < end:
        if healthy(1):
            return
        time.sleep(0.5)
    raise CheckFail("node 1 (8001) did not come back within 12s; start.sh must run each node in a respawn loop")


@rule("0.9", "basics: register 201 {user, token}, login 200, GET /api/auth/me 200 {user}")
def _():
    name = "b" + rid(8)
    r = want(call("POST", "/api/auth/register", {"username": name, "password": PW}), 201, "register")
    expect(isinstance(r["token"], str) and len(r["token"]) >= 16, f"token must be a string of >= 16 chars: {r.text[:120]}")
    expect(r["user"].get("username") == name, f"user.username should be {name}: {r.text[:120]}")
    r = want(call("POST", "/api/auth/login", {"username": name, "password": PW}), 200, "login")
    me = want(call("GET", "/api/auth/me", token=r["token"]), 200, "GET /api/auth/me with the login token")
    expect(me["user"].get("username") == name, f"me.user.username should be {name}: {me.text[:120]}")
    want(call("GET", "/api/auth/me"), 401, "GET /api/auth/me without a token")


@rule("0.10", "basics: POST /api/workspaces -> 201 {workspace, general_channel}; listed in GET /api/workspaces")
def _():
    u = new_user()
    ws = new_workspace(u)
    expect(ws["general"].get("name") == "general", f"general_channel.name should be 'general': {ws['general']}")
    r = want(call("GET", "/api/workspaces", token=u["token"], node=1), 200, "GET /api/workspaces on 8001")
    expect(any(w.get("slug") == ws["slug"] for w in r["workspaces"]), f"new workspace not in GET /api/workspaces: {r.text[:160]}")
    r = want(call("GET", f"/api/workspaces/{ws['slug']}", token=u["token"]), 200, "GET /api/workspaces/{slug}")
    expect(any(c.get("name") == "general" for c in r["channels"]), f"#general missing from workspace channels: {r.text[:160]}")


@rule("0.11", "basics: create channel 201 {channel}; another user joins it (200); duplicate name 409")
def _():
    u = new_user()
    ws = new_workspace(u)
    ch = new_channel(ws, u, name="room-" + rid(5))
    want(call("POST", f"/api/workspaces/{ws['slug']}/channels", {"name": ch["name"]}, u["token"]), 409, "duplicate channel name")
    v = new_user()
    want(join(v, ch["id"], node=2), 200, "join of a public channel by a new user (open workspace)")


@rule("0.12", "basics: post 201 {message}; GET messages lists it newest-first on another node")
def _():
    u = new_user()
    ws = new_workspace(u)
    cid = ws["general"]["id"]
    m1 = post(u, cid, "first")
    m2 = post(u, cid, "second", node=1)
    expect(m2.get("body") == "second" and same(m2.get("channel_id"), cid), f"message object wrong: {m2}")
    r = want(call("GET", f"/api/channels/{cid}/messages", token=u["token"], node=2), 200, "GET messages on 8002")
    ids = [m.get("id") for m in r["messages"]]
    expect(ids[:2] == [m2["id"], m1["id"]], f"expected newest-first ids {[m2['id'], m1['id']]}, got {ids[:4]}")
    want(call("POST", f"/api/channels/{cid}/messages", {"body": ""}, u["token"]), 400, "empty body")


@rule("0.13", "basics: WebSocket subscribe -> subscribed; a post on another node arrives as message.created")
def _():
    u = new_user()
    ws = new_workspace(u)
    cid = ws["general"]["id"]
    c = ws_connect(u["token"], node=0)
    try:
        head = ws_subscribe(c, cid)
        m = post(u, cid, "hello ws", node=2)
        f, seen = ws_recv_until(c, lambda f: f.get("type") == "message.created", 3)
        expect(f is not None, f"no message.created frame within 3s (frames seen: {[x.get('type') for x in seen]})")
        expect(f.get("event_id") == head + 1, f"event_id should be head_event_id+1 = {head + 1}, got {f.get('event_id')}")
        expect(same((f.get("message") or {}).get("id"), m["id"]), f"frame message.id should be {m['id']}: {str(f)[:160]}")
    finally:
        c.close()


if __name__ == "__main__":
    run()
