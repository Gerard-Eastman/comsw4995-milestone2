"""Component E checks: message edit/delete, IRC gateway, web UI.
Usage: python3 e_checks.py <stage>   (stage 1..6, or nothing for all)"""
import os, sys, time, json, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import *  # noqa
set_comp("e")

MISSING = 999999999


def setup():
    o = new_user("own")
    ws = new_workspace(o)
    m = add_member(ws, o)
    ch = new_channel(ws, o)
    want(join(m, ch["id"]), 200, "setup: member joins the channel")
    return {"o": o, "m": m, "ws": ws, "ch": ch, "cid": ch["id"]}


def edit(user, mid, body, node=0):
    return call("PATCH", f"/api/messages/{mid}", None if body is None else {"body": body}, user and user["token"], node)


def delete(user, mid, node=0):
    return call("DELETE", f"/api/messages/{mid}", None, user and user["token"], node)


def listed(user, cid, node=0):
    r = want(call("GET", f"/api/channels/{cid}/messages", token=user["token"], node=node), 200, "list messages")
    return r["messages"]


def kinds(frames):
    return [f.get("type") for f in frames]


# ======================================================================= E1 edit / delete
@rule("E1.1", "PATCH /api/messages/{id} by the author -> 200 {message} with new body and edited_at; emits message.updated", 1)
def _():
    s = setup()
    msg = post(s["m"], s["cid"], "typo hree")
    c = ws_connect(s["o"]["token"], node=2)
    try:
        head = ws_subscribe(c, s["cid"])
        r = want(edit(s["m"], msg["id"], "typo here", node=1), 200, "author edit")
        e = r["message"]
        expect(e.get("body") == "typo here", f"body should be 'typo here': {r.text[:160]}")
        expect(isinstance(e.get("edited_at"), str) and e["edited_at"][:2] == "20", f"edited_at should be an ISO timestamp: {e.get('edited_at')}")
        f, seen = ws_recv_until(c, lambda f: f.get("type") == "message.updated", 3)
        expect(f is not None, f"no message.updated frame within 3s (saw {kinds(seen)})")
        expect(f.get("event_id") == head + 1 and (f.get("message") or {}).get("body") == "typo here",
               f"message.updated should carry event_id {head + 1} and the edited message: {str(f)[:200]}")
    finally:
        c.close()
    lm = next((x for x in listed(s["o"], s["cid"]) if same(x.get("id"), msg["id"])), {})
    expect(lm.get("body") == "typo here" and lm.get("edited_at"), f"edit not persisted in the list: {str(lm)[:160]}")


@rule("E1.2", "edit errors in order: 401, 404 never existed, 403 not author, 409 deleted, 400 empty, 423 archived", 1)
def _():
    s = setup()
    msg = post(s["m"], s["cid"], "original")
    want(edit(None, msg["id"], "x"), 401, "edit without a token")
    want(edit(s["m"], MISSING, "x"), 404, "edit of a message that never existed")
    want(edit(s["o"], msg["id"], "x"), 403, "edit by the workspace owner (not the author)")
    want(edit(s["m"], msg["id"], ""), 400, "empty body")
    want(edit(s["m"], msg["id"], "   "), 400, "whitespace-only body")
    want(edit(s["m"], msg["id"], None), 400, "missing body")
    gone = post(s["m"], s["cid"], "to delete")
    want(delete(s["m"], gone["id"]), 200, "setup: delete")
    want(edit(s["m"], gone["id"], "edit after delete"), 409, "edit of a deleted message")
    want(edit(s["o"], gone["id"], "edit after delete"), 403, "non-author edit of a deleted message (403 before 409)")
    want(call("POST", f"/api/channels/{s['cid']}/archive", None, s["o"]["token"]), 200, "setup: owner archives")
    want(edit(s["m"], msg["id"], "archived edit"), 423, "edit in an archived channel")


@rule("E1.3", "DELETE by author or workspace owner -> 200 {deleted: true}, emits message.deleted; others 403; unknown 404", 1)
def _():
    s = setup()
    x = add_member(s["ws"], s["o"])
    want(join(x, s["cid"]), 200, "setup: x joins")
    m1 = post(s["m"], s["cid"], "mine")
    m2 = post(s["m"], s["cid"], "owner removes this")
    want(delete(x, m1["id"]), 403, "delete by another member")
    want(delete(s["m"], MISSING), 404, "delete of a message that never existed")
    c = ws_connect(x["token"], node=1)
    try:
        head = ws_subscribe(c, s["cid"])
        r = want(delete(s["m"], m1["id"]), 200, "author delete")
        expect(r.body == {"deleted": True}, f"expected {{'deleted': true}}, got {r.text[:100]}")
        r = want(delete(s["o"], m2["id"], node=2), 200, "workspace owner deletes a member's message")
        expect(r.body == {"deleted": True}, f"expected {{'deleted': true}}, got {r.text[:100]}")
        _, seen = ws_recv_until(c, lambda f: False, 1.5)
        dels = [f for f in seen if f.get("type") == "message.deleted"]
        expect([str(f.get("message_id")) for f in dels] == [str(m1["id"]), str(m2["id"])],
               f"expected two message.deleted frames with message_id {m1['id']}, {m2['id']}; saw {[(f.get('type'), f.get('message_id')) for f in seen]}")
        expect([f.get("event_id") for f in dels] == [head + 1, head + 2], f"message.deleted event_ids should be {head + 1}, {head + 2}")
    finally:
        c.close()


@rule("E1.4", "deleting an already-deleted message -> 200 {deleted: true} again and emits nothing", 1)
def _():
    s = setup()
    msg = post(s["m"], s["cid"], "twice")
    want(delete(s["m"], msg["id"]), 200, "first delete")
    c = ws_connect(s["o"]["token"])
    try:
        ws_subscribe(c, s["cid"])
        r = want(delete(s["m"], msg["id"], node=1), 200, "second delete")
        expect(r.body == {"deleted": True}, f"expected {{'deleted': true}}, got {r.text[:100]}")
        marker = post(s["o"], s["cid"], "marker")
        f, seen = ws_recv_until(c, lambda f: f.get("type") == "message.created", 3)
        expect(f is not None, "no marker message.created")
        expect("message.deleted" not in kinds(seen), f"the repeated delete emitted a frame: {kinds(seen)}")
    finally:
        c.close()


@rule("E1.5", "deleted messages vanish from lists, stop counting in reply_count, and cannot get reactions (404)", 1)
def _():
    s = setup()
    parent = post(s["o"], s["cid"], "parent")
    r1 = post(s["m"], s["cid"], "reply one", parent_id=parent["id"])
    post(s["m"], s["cid"], "reply two", parent_id=parent["id"])
    gone = post(s["m"], s["cid"], "vanishing")
    want(delete(s["m"], gone["id"]), 200, "delete top-level")
    want(delete(s["m"], r1["id"]), 200, "delete a reply")
    msgs = listed(s["o"], s["cid"], node=2)
    expect(not any(same(x.get("id"), gone["id"]) for x in msgs), "a deleted message is still in GET .../messages")
    p = next((x for x in msgs if same(x.get("id"), parent["id"])), {})
    expect(p.get("reply_count") == 1, f"parent reply_count should drop to 1 after deleting a reply, got {p.get('reply_count')}")
    r = call("POST", f"/api/messages/{gone['id']}/reactions", {"emoji": "👍"}, s["o"]["token"])
    expect(r.status == 404, f"reacting to a deleted message: expected 404, got {r.short()}")


# ======================================================================= E2 IRC registration
def numerics(lines):
    return [num(l) for l in lines]


def need_irc():
    expect(port_open(6667), "nothing is listening on port 6667 (is /app/irc.py running? see /tmp/irc.log)")


@rule("E2.1", "PASS/NICK/USER with a valid token -> 001, 002, 003, 004, 005, then 422", 2)
def _():
    need_irc()
    u = new_user("ir")
    c = Irc()
    try:
        seen = c.register(u["token"], u["username"])
        ns = [n for n in numerics(seen) if n in ("001", "002", "003", "004", "005", "422")]
        expect(ns == ["001", "002", "003", "004", "005", "422"], f"expected numerics 001..005 then 422, got {numerics(seen)} ({seen[:3]})")
        expect(seen[0].startswith(":huddle 001 " + u["username"]), f"first line should start with ':huddle 001 {u['username']}': {seen[0]!r}")
    finally:
        c.close()


@rule("E2.2", "bad token (or no PASS) -> 464 then the connection is closed", 2)
def _():
    need_irc()
    for tok, what in (("not-a-token-" + rid(8), "bad token"), (None, "no PASS")):
        c = Irc()
        try:
            seen = c.register(tok, "nick" + rid(5))
            expect("464" in numerics(seen), f"{what}: expected 464, got {seen[:4]}")
            expect("001" not in numerics(seen), f"{what}: must not register")
            c.until(lambda l: False, 1.5)
            expect(c.closed, f"{what}: the server should close the connection after 464")
        finally:
            c.close()


@rule("E2.3", "NICK already in use -> 433 and the connection stays open; another NICK + USER then registers", 2)
def _():
    need_irc()
    u1, c1 = irc_user("ia")
    u2 = new_user("ib")
    c2 = Irc()
    try:
        c2.send(f"PASS {u2['token']}")
        c2.send(f"NICK {u1['username'].upper()}")
        ln, seen = c2.until(lambda l: num(l) in ("433", "001"), 3)
        expect(ln is not None and num(ln) == "433", f"NICK in use (case-insensitive) should get 433, got {seen[:3]}")
        expect(not c2.closed, "433 must not close the connection")
        c2.send(f"NICK {u2['username']}")
        c2.send(f"USER {u2['username']} 0 * :x")
        ln, seen = c2.until(lambda l: num(l) == "422", 3)
        expect(ln is not None and "001" in numerics(seen), f"after 433, a free NICK + USER should register: {seen[:4]}")
    finally:
        c1.close()
        c2.close()


@rule("E2.4", "PING x -> ':huddle PONG huddle :x'; QUIT closes without an error reply and frees the nick", 2)
def _():
    need_irc()
    u, c = irc_user("ip")
    try:
        c.send("PING tok123")
        ln, seen = c.until(lambda l: "PONG" in l, 2)
        expect(ln == ":huddle PONG huddle :tok123", f"expected ':huddle PONG huddle :tok123', got {seen[-2:]}")
        c.send("PONG whatever")
        c.send("QUIT :bye")
        _, seen = c.until(lambda l: False, 1.5)
        expect(c.closed, "QUIT should close the connection")
        bad = [l for l in seen if l.startswith("ERROR") or (num(l).isdigit() and int(num(l)) >= 400)]
        expect(not bad, f"QUIT must not get an error reply: {bad}")
    finally:
        c.close()
    c2 = Irc()
    try:
        seen = c2.register(u["token"], u["username"])
        expect("001" in numerics(seen), f"the nick should be free again after QUIT: {seen[:3]}")
    finally:
        c2.close()


@rule("E2.5", "unknown command -> 421 (connection stays open); commands before registration -> 451", 2)
def _():
    need_irc()
    u, c = irc_user("iu")
    try:
        c.send("FOOBAR baz")
        ln, seen = c.until(lambda l: num(l) == "421", 2)
        expect(ln is not None and "FOOBAR" in ln, f"expected ':huddle 421 {u['username']} FOOBAR :Unknown command', got {seen[:2]}")
        c.send("PING still")
        ln, _ = c.until(lambda l: "PONG" in l, 2)
        expect(ln is not None, "connection should stay open after 421")
    finally:
        c.close()
    c = Irc()
    try:
        c.send("JOIN #a/b")
        ln, seen = c.until(lambda l: num(l) == "451", 2)
        expect(ln is not None, f"JOIN before registration should get 451, got {seen[:2]}")
    finally:
        c.close()


# ======================================================================= E3 IRC channels and bridging
def irc_setup():
    o = new_user("io")
    ws = new_workspace(o)
    c = Irc()
    seen = c.register(o["token"], o["username"])
    expect("001" in numerics(seen), f"setup: IRC registration failed: {seen[:3]}")
    return o, ws, c, f"#{ws['slug']}/general", ws["general"]["id"]


@rule("E3.1", "JOIN #slug/channel -> JOIN echo, 332/331, 353 (with your nick), 366, in that order", 3)
def _():
    need_irc()
    o, ws, c, name, cid = irc_setup()
    try:
        seen = c.join(name)
        ns = numerics(seen)
        expect("JOIN" in ns and "353" in ns and "366" in ns, f"JOIN {name} should produce JOIN, 353, 366: {seen[:6]}")
        j = seen[ns.index("JOIN")]
        expect(j.startswith(f":{o['username']}!") and j.rstrip().endswith(name), f"JOIN line should be ':{o['username']}!{o['username']}@huddle JOIN {name}', got {j!r}")
        expect(ns.index("JOIN") < ns.index("353") < ns.index("366"), f"order should be JOIN, (332/331), 353, 366: {ns}")
        t = [i for i, n in enumerate(ns) if n in ("331", "332")]
        expect(t and ns.index("JOIN") < t[0] < ns.index("353"), f"332 or 331 should come between JOIN and 353: {ns}")
        expect(o["username"] in seen[ns.index("353")], f"353 should list your nick: {seen[ns.index('353')]!r}")
    finally:
        c.close()


@rule("E3.2", "JOIN unknown, hyphenated (#slug-general) or private-not-member channel -> 403", 3)
def _():
    need_irc()
    o, ws, c, name, cid = irc_setup()
    try:
        for bad in (f"#{ws['slug']}/nosuch", f"#{ws['slug']}-general", "#nosuchws/general"):
            seen = c.join(bad)
            expect("403" in numerics(seen), f"JOIN {bad} should get 403: {seen[:3]}")
    finally:
        c.close()
    x = new_user("ix")
    priv = new_channel(ws, o, private=True)
    want(join(x, ws["general"]["id"]), 200, "setup: x joins the workspace")
    c = Irc()
    try:
        c.register(x["token"], x["username"])
        seen = c.join(f"#{ws['slug']}/{priv['name']}")
        expect("403" in numerics(seen), f"JOIN of a private channel you are not in should get 403: {seen[:3]}")
    finally:
        c.close()


@rule("E3.3", "NAMES, TOPIC, WHO, LIST, MODE are answered with their numerics and keep the connection open", 3)
def _():
    need_irc()
    o, ws, c, name, cid = irc_setup()
    try:
        c.join(name)
        checks = [(f"NAMES {name}", "366", ["353"]), (f"TOPIC {name}", None, ["331", "332"]),
                  (f"WHO {name}", "315", ["352"]), ("LIST", "323", ["321", "322"]),
                  (f"MODE {name}", None, ["324"]), (f"MODE {o['username']}", None, ["221"])]
        for cmd, end, need in checks:
            c.send(cmd)
            stop = (lambda l, e=end: num(l) == e) if end else (lambda l, nd=need: num(l) in nd)
            ln, seen = c.until(stop, 2)
            ns = numerics(seen)
            expect(ln is not None and any(n in ns for n in need) and (end is None or all(n in ns for n in need)),
                   f"{cmd} should answer {need + ([end] if end else [])}, got {seen[:4]}")
            if cmd == "LIST":
                expect(any(name in l for l in seen if num(l) == "322"), f"LIST should include a 322 line for {name}: {seen[:4]}")
        c.send("PING alive")
        ln, _ = c.until(lambda l: "PONG" in l, 2)
        expect(ln is not None, "connection should still be open")
    finally:
        c.close()


@rule("E3.4", "IRC PRIVMSG commits a message with the next dense event_id (mixed with web posts); not joined -> 442", 3)
def _():
    need_irc()
    o, ws, c, name, cid = irc_setup()
    w = ws_connect(o["token"], node=2)
    try:
        c.join(name)
        head = ws_subscribe(w, cid)
        c.send(f"PRIVMSG {name} :hello from irc")
        post(o, cid, "hello from web", node=1)
        c.send(f"PRIVMSG {name} :irc again")
        got, end = [], time.time() + 4
        while len(got) < 3 and time.time() < end:
            _, seen = ws_recv_until(w, lambda f: f.get("type") == "message.created", end - time.time())
            got += [f for f in seen if f.get("type") == "message.created"]
        bodies = [(f.get("message") or {}).get("body") for f in got]
        expect(sorted(bodies) == sorted(["hello from irc", "hello from web", "irc again"]), f"WebSocket on 8002 should get all three messages, got {bodies}")
        expect([f.get("event_id") for f in got] == [head + 1, head + 2, head + 3], f"event_ids should be dense {head + 1}..{head + 3}, got {[f.get('event_id') for f in got]}")
        irc_msg = next(f for f in got if (f.get("message") or {}).get("body") == "hello from irc")
        expect(same(irc_msg["message"].get("author_id"), o["id"]), f"author_id of the IRC message should be {o['id']}")
        other = new_channel(ws, o)
        c.send(f"PRIVMSG #{ws['slug']}/{other['name']} :not joined")
        ln, seen = c.until(lambda l: num(l) == "442", 2)
        expect(ln is not None, f"PRIVMSG to a channel you have not joined should get 442: {seen[:2]}")
    finally:
        w.close()
        c.close()


@rule("E3.5", "web posts reach joined IRC clients within 2s as ':<user>!<user>@huddle PRIVMSG #c :body'; no echo to the sender", 3)
def _():
    need_irc()
    o, ws, c1, name, cid = irc_setup()
    m = add_member(ws, o)
    c2 = Irc()
    try:
        c2.register(m["token"], m["username"])
        c1.join(name)
        c2.join(name)
        post(m, cid, "from the web", node=1)
        ln, seen = c1.until(lambda l: "PRIVMSG" in l, 2)
        want_ln = f":{m['username']}!{m['username']}@huddle PRIVMSG {name} :from the web"
        expect(ln == want_ln, f"expected {want_ln!r} within 2s, got {seen[-3:]}")
        c1.send(f"PRIVMSG {name} :irc to irc")
        ln, seen = c2.until(lambda l: "PRIVMSG" in l and "irc to irc" in l, 2)
        expect(ln is not None and ln.startswith(f":{o['username']}!"), f"the other IRC client should get the PRIVMSG with prefix :{o['username']}!..., got {seen[-3:]}")
        ln, seen = c1.until(lambda l: "irc to irc" in l, 1)
        expect(ln is None, f"the sender must not get its own PRIVMSG echoed: {ln!r}")
    finally:
        c1.close()
        c2.close()


@rule("E3.6", "with node 1 SIGKILLed, bridging still works both ways (8000 -> IRC, IRC -> WebSocket on 8002)", 3)
def _():
    need_irc()
    o, ws, c, name, cid = irc_setup()
    for i in range(3):
        end = time.time() + 12
        while not healthy(i) and time.time() < end:
            time.sleep(0.3)
    w = None
    try:
        c.join(name)
        pid = pid_on_port(8001)
        expect(pid is not None, "could not find the PID on 8001")
        os.kill(pid, 9)
        time.sleep(0.3)
        post(o, cid, "web while 8001 is down", node=0)
        ln, seen = c.until(lambda l: "PRIVMSG" in l, 2)
        expect(ln is not None and ln.endswith(":web while 8001 is down"), f"IRC client got no PRIVMSG for a post on 8000 while 8001 was down: {seen[-2:]}")
        w = ws_connect(o["token"], node=2)
        head = ws_subscribe(w, cid)
        c.send(f"PRIVMSG {name} :irc while 8001 is down")
        f, seen = ws_recv_until(w, lambda f: f.get("type") == "message.created", 3)
        expect(f is not None and f.get("event_id") == head + 1, f"WebSocket on 8002 got no message.created for the IRC PRIVMSG (saw {kinds(seen)})")
    finally:
        if w:
            w.close()
        c.close()


# ======================================================================= E4-E6 web UI
BASE = "http://127.0.0.1:8000"
_pw = {}

TESTIDS = """auth-form auth-submit auth-toggle workspace-create-form empty-state-create-workspace join-workspace-form
join-workspace-submit channel-list dms-list new-channel-btn current-user logout-btn workspace-header workspace-settings-btn
workspace-settings-close workspace-name-input workspace-join-mode workspace-general-submit channel-title channel-topic
channel-settings-btn channel-settings-title channel-settings-close channel-members-list channel-add-member-form
channel-add-member-input channel-add-member-submit channel-topic-input channel-topic-submit archive-channel-btn
unarchive-channel-btn create-channel-form create-channel-private create-channel-submit create-channel-cancel message-list
message-input send-btn thread-panel thread-input thread-send close-thread settings-tab-members settings-tab-invitations
settings-tab-general settings-pane-members settings-pane-invitations settings-pane-general create-invitation-btn
create-invitation-form create-invitation-submit invitations-list""".split()
DOM_IDS = ["auth-modal", "create-channel-modal", "channel-settings-modal", "workspace-settings-modal", "create-invitation-form"]
ROLES = {"primary": "auth-submit send-btn thread-send create-channel-submit join-workspace-submit workspace-general-submit "
                    "create-invitation-submit channel-topic-submit channel-add-member-submit".split(),
         "danger": ["archive-channel-btn", "logout-btn"],
         "secondary": "new-channel-btn create-invitation-btn unarchive-channel-btn create-channel-cancel close-thread "
                      "channel-settings-close workspace-settings-close channel-settings-btn workspace-settings-btn".split()}
COLORS = {"primary": "rgb(0, 122, 90)", "danger": "rgb(224, 30, 90)", "secondary": "rgb(18, 100, 163)"}


def T(tid):
    return f'[data-testid="{tid}"]'


def browser():
    if "b" not in _pw:
        from playwright.sync_api import sync_playwright
        _pw["p"] = sync_playwright().start()
        _pw["b"] = _pw["p"].chromium.launch(args=["--no-sandbox"])
    return _pw["b"]


def page(token=None):
    """A fresh browser context at 1280x900 on /, optionally logged in with ?token=."""
    ctx = browser().new_context(viewport={"width": 1280, "height": 900})
    pg = ctx.new_page()
    pg.set_default_timeout(4000)
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)[:150]))
    pg.on("dialog", lambda d: (errors.append("dialog: " + d.type), d.dismiss()))
    pg.errors = errors
    pg.goto(BASE + "/" + (f"?token={token}" if token else ""), wait_until="domcontentloaded")
    if token:
        try:
            pg.wait_for_function("() => { const m = document.getElementById('auth-modal'); return m && (m.hidden || getComputedStyle(m).display === 'none'); }", timeout=4000)
        except Exception:
            raise CheckFail(f"opening /?token=<valid token> did not hide #auth-modal within 4s (page errors: {errors[:2]})")
    return pg


def close(pg):
    try:
        pg.context.close()
    except Exception:
        pass


def visible(pg, sel):
    try:
        return pg.locator(sel).first.is_visible()
    except Exception:
        return False


def wait_visible(pg, sel, what, timeout=4000):
    try:
        pg.locator(sel).first.wait_for(state="visible", timeout=timeout)
    except Exception:
        raise CheckFail(f"{what}: {sel} did not become visible within {timeout // 1000}s (page errors: {pg.errors[:2]})")


def wait_hidden(pg, sel, what, timeout=4000):
    try:
        pg.locator(sel).first.wait_for(state="hidden", timeout=timeout)
    except Exception:
        raise CheckFail(f"{what}: {sel} is still visible after {timeout // 1000}s")


def wait_text(pg, sel, text, what, timeout=4000):
    end = time.time() + timeout / 1000
    last = ""
    while time.time() < end:
        try:
            last = pg.locator(sel).first.inner_text(timeout=500)
            if text in last:
                return last
        except Exception:
            pass
        time.sleep(0.15)
    raise CheckFail(f"{what}: expected {sel} to contain {text!r}, got {last[:80]!r}")


def token_in_storage(pg):
    return pg.evaluate("() => { try { return localStorage.getItem('huddle.token') } catch (e) { return null } }")


def ui_world(channels=("alpha",)):
    """A user with a workspace (#general + channels) made through the API."""
    u = new_user("ui")
    ws = new_workspace(u)
    chans = {"general": ws["general"]}
    for n in channels:
        chans[n] = new_channel(ws, u, name=f"{n}-{rid(4)}")
    return u, ws, chans


def entry_sel(ch):
    return f'[data-testid="channel-entry"][data-channel-id="{ch["id"]}"]'


def open_channel(pg, ch):
    pg.locator(entry_sel(ch)).first.click()
    wait_text(pg, T("channel-title"), ch["name"], f"switching to #{ch['name']}")


def rows(pg):
    return pg.locator(f'{T("message-list")} [data-testid="message"]')


def row(pg, mid):
    return pg.locator(f'{T("message-list")} [data-testid="message"][data-message-id="{mid}"]')


def html():
    r = raw_get("/")
    return r.text


@rule("E4.1", "GET / on each node -> 200 text/html without a token", 4)
def _():
    for n in range(3):
        r = raw_get("/", node=n)
        expect(r.status_code == 200, f"GET / on {8000 + n}: expected 200, got {r.status_code}")
        expect(r.headers.get("Content-Type", "").startswith("text/html"), f"GET / on {8000 + n}: Content-Type should be text/html, got {r.headers.get('Content-Type')}")


@rule("E4.2", "the served HTML has every pinned data-testid and the pinned DOM ids", 4)
def _():
    h = html()
    miss = [t for t in TESTIDS if f'data-testid="{t}"' not in h]
    expect(not miss, f"missing data-testid in the served HTML: {miss[:10]}")
    miss = [i for i in DOM_IDS if not re.search(rf'\bid="{re.escape(i)}"', h)]
    expect(not miss, f"missing DOM ids in the served HTML: {miss}")


@rule("E4.3", "each pinned button carries its data-button-role in the served HTML", 4)
def _():
    h = html()
    bad = []
    for role, tids in ROLES.items():
        for t in tids:
            m = re.search(rf'<[^>]*data-testid="{re.escape(t)}"[^>]*>', h)
            if not m or f'data-button-role="{role}"' not in m.group(0):
                bad.append(f"{t} (want {role})")
    expect(not bad, f"wrong or missing data-button-role: {bad[:8]}")


@rule("E4.4", "pinned buttons have the exact resting colours (primary #007a5a, danger #e01e5a, secondary #1264a3, white text)", 4)
def _():
    pg = page()
    try:
        bad = []
        for role, tids in ROLES.items():
            for t in tids:
                st = pg.evaluate("""(sel) => { const e = document.querySelector(sel); if (!e) return null;
                    const s = getComputedStyle(e); return [s.backgroundColor, s.color]; }""", T(t))
                if not st or st[0] != COLORS[role] or st[1] != "rgb(255, 255, 255)":
                    bad.append(f"{t}: {st}")
        expect(not bad, f"want background {COLORS} and color rgb(255, 255, 255); wrong: {bad[:5]}")
    finally:
        close(pg)


@rule("E4.5", "app.js and style.css are served; / without a token shows #auth-modal with no JavaScript error", 4)
def _():
    for p in ("/static/app.js", "/static/style.css"):
        r = raw_get(p)
        expect(r.status_code == 200, f"GET {p}: expected 200, got {r.status_code}")
    pg = page()
    try:
        wait_visible(pg, "#auth-modal", "no token")
        wait_visible(pg, T("auth-form"), "no token")
        time.sleep(0.4)
        expect(not pg.errors, f"JavaScript errors on load: {pg.errors[:3]}")
    finally:
        close(pg)


def set_mode(pg, mode):
    for _ in range(3):
        if pg.get_attribute(T("auth-form"), "data-mode") == mode:
            return
        pg.click(T("auth-toggle"))
        time.sleep(0.1)
    raise CheckFail(f"auth-toggle did not switch auth-form to data-mode=\"{mode}\" (now {pg.get_attribute(T('auth-form'), 'data-mode')!r})")


def fill_auth(pg, username, password, display=None):
    f = T("auth-form")
    pg.fill(f'{f} input[name="username"]', username)
    pg.fill(f'{f} input[name="password"]', password)
    if display is not None and visible(pg, f'{f} input[name="display_name"]'):
        pg.fill(f'{f} input[name="display_name"]', display)
    pg.click(T("auth-submit"))


@rule("E5.1", "auth-form has data-mode login|signup; auth-toggle switches it and shows display_name only in signup", 5)
def _():
    pg = page()
    try:
        m0 = pg.get_attribute(T("auth-form"), "data-mode")
        expect(m0 in ("login", "signup"), f"auth-form data-mode should be 'login' or 'signup', got {m0!r}")
        set_mode(pg, "signup")
        expect(visible(pg, f'{T("auth-form")} input[name="display_name"]'), "display_name input should be visible in signup mode")
        set_mode(pg, "login")
        expect(not visible(pg, f'{T("auth-form")} input[name="display_name"]'), "display_name input should be hidden in login mode")
    finally:
        close(pg)


@rule("E5.2", "an invalid sign-up shows the error as visible text in the form's [role=alert]; stays logged out", 5)
def _():
    pg = page()
    try:
        set_mode(pg, "signup")
        fill_auth(pg, "bad name " + rid(3), "short")
        al = f'{T("auth-form")} [role="alert"]'
        end, txt = time.time() + 4, ""
        while time.time() < end:
            if visible(pg, al):
                txt = pg.inner_text(al).strip()
                if txt:
                    break
            time.sleep(0.15)
        expect(txt, "no visible, non-empty error text in auth-form [role=alert] within 4s")
        expect(not token_in_storage(pg), "an invalid sign-up must not store a token")
        expect(visible(pg, "#auth-modal"), "#auth-modal should stay visible after a failed sign-up")
    finally:
        close(pg)


@rule("E5.3", "valid sign-up auto-logs in (token in localStorage['huddle.token'], modal hidden, current-user); login and ?token= work", 5)
def _():
    name = "sg" + rid(8)
    pg = page()
    try:
        set_mode(pg, "signup")
        fill_auth(pg, name, PW, "Sign Up")
        wait_hidden(pg, "#auth-modal", "after a valid sign-up")
        wait_text(pg, T("current-user"), name, "current-user after sign-up")
        expect(token_in_storage(pg), "after sign-up, localStorage['huddle.token'] should hold the token")
    finally:
        close(pg)
    pg = page()
    try:
        set_mode(pg, "login")
        fill_auth(pg, name, PW)
        wait_hidden(pg, "#auth-modal", "after login")
        wait_text(pg, T("current-user"), name, "current-user after login")
    finally:
        close(pg)
    tok = want(call("POST", "/api/auth/login", {"username": name, "password": PW}), 200, "API login")["token"]
    pg = page(tok)
    try:
        wait_text(pg, T("current-user"), name, "current-user after /?token=")
    finally:
        close(pg)


@rule("E5.4", "a user with no workspace sees empty-state-create-workspace; creating one shows its name and #general", 5)
def _():
    u = new_user("nows")
    pg = page(u["token"])
    try:
        wait_visible(pg, T("empty-state-create-workspace"), "user with no workspace")
        expect(pg.inner_text(T("empty-state-create-workspace")).strip(), "the empty state needs visible copy")
        slug = "ui-" + rid(6)
        f = T("workspace-create-form")
        pg.fill(f'{f} input[name="slug"]', slug)
        pg.fill(f'{f} input[name="name"]', "UI Space " + slug)
        pg.locator(f'{f} [type="submit"]').first.click()
        wait_hidden(pg, T("empty-state-create-workspace"), "after creating a workspace")
        wait_text(pg, T("workspace-header"), "UI Space " + slug, "workspace-header after create")
        wait_visible(pg, '[data-testid="channel-entry"][data-channel-name="general"]', "#general in channel-list")
    finally:
        close(pg)


@rule("E5.5", "channel-list has one channel-entry per channel (data-channel-id/name, '#' prefix); one is selected after login", 5)
def _():
    u, ws, ch = ui_world(("alpha", "beta"))
    pg = page(u["token"])
    try:
        for c in ch.values():
            wait_visible(pg, entry_sel(c), f"entry for #{c['name']}")
            el = pg.locator(entry_sel(c)).first
            expect(el.get_attribute("data-channel-name") == c["name"], f"data-channel-name should be {c['name']!r}")
            expect("#" in el.inner_text(), f"entry text should show '#{c['name']}', got {el.inner_text()!r}")
        expect(pg.locator(f'{T("channel-list")} [data-testid="channel-entry"]').count() == 3, "channel-list should hold exactly 3 entries")
        wait_text(pg, T("channel-title"), "#", "a channel should be selected after login (channel-title shows '#name')")
    finally:
        close(pg)


@rule("E5.6", "new-channel-btn -> create-channel-modal; create switches to it; duplicate shows [role=alert]; cancel hides", 5)
def _():
    u, ws, ch = ui_world(())
    pg = page(u["token"])
    try:
        name = "made-" + rid(5)
        pg.click(T("new-channel-btn"))
        wait_visible(pg, "#create-channel-modal", "after clicking new-channel-btn")
        pg.fill(f'{T("create-channel-form")} input[name="name"]', name)
        pg.click(T("create-channel-submit"))
        wait_hidden(pg, "#create-channel-modal", "after creating a channel")
        wait_visible(pg, f'[data-testid="channel-entry"][data-channel-name="{name}"]', "new channel entry")
        wait_text(pg, T("channel-title"), name, "should switch to the new channel")
        pg.click(T("new-channel-btn"))
        wait_visible(pg, "#create-channel-modal", "reopen")
        pg.fill(f'{T("create-channel-form")} input[name="name"]', name)
        pg.click(T("create-channel-submit"))
        al = f'{T("create-channel-form")} [role="alert"]'
        end, txt = time.time() + 4, ""
        while time.time() < end and not txt:
            if visible(pg, al):
                txt = pg.inner_text(al).strip()
            time.sleep(0.15)
        expect(txt, "a duplicate channel name should show visible error text in create-channel-form [role=alert]")
        expect(visible(pg, "#create-channel-modal"), "the modal should stay open after the duplicate error")
        pg.click(T("create-channel-cancel"))
        wait_hidden(pg, "#create-channel-modal", "after cancel")
    finally:
        close(pg)


@rule("E5.7", "clicking an entry switches channel: title '#name', topic, its messages; an empty channel shows copy, no rows", 5)
def _():
    u, ws, ch = ui_world(("beta", "empty"))
    want(call("PATCH", f"/api/channels/{ch['beta']['id']}", {"topic": "Beta topic"}, u["token"]), 200, "setup: topic")
    post(u, ch["beta"]["id"], "beta hello")
    pg = page(u["token"])
    try:
        open_channel(pg, ch["beta"])
        wait_text(pg, T("channel-title"), "#" + ch["beta"]["name"], "channel-title")
        wait_text(pg, T("channel-topic"), "Beta topic", "channel-topic")
        wait_text(pg, T("message-list"), "beta hello", "message-list of #beta")
        open_channel(pg, ch["empty"])
        time.sleep(0.6)
        expect(rows(pg).count() == 0, "an empty channel should show no message rows")
        expect(pg.inner_text(T("message-list")).strip(), "an empty channel should show visible copy in message-list")
    finally:
        close(pg)


def send_ui(pg, text):
    pg.fill(T("message-input"), text)
    pg.click(T("send-btn"))


def last_body(pg):
    n = rows(pg).count()
    return rows(pg).nth(n - 1).locator('[data-testid="message-body"]').inner_text() if n else None


def wait_last_body(pg, text, what):
    end = time.time() + 4
    while time.time() < end:
        try:
            if last_body(pg) == text:
                return
        except Exception:
            pass
        time.sleep(0.15)
    raise CheckFail(f"{what}: the last message row should have message-body {text!r}, got {last_body(pg)!r}")


def ui_msg_world(bodies=()):
    """A user, a workspace, messages posted through the API first, then the page opened on #general."""
    u, ws, ch = ui_world(())
    msgs = [post(u, ch["general"]["id"], b) for b in bodies]
    pg = page(u["token"])
    open_channel(pg, ch["general"])
    return u, ws, ch["general"], pg, msgs


@rule("E6.1", "send-btn and Enter post a message (last row, input cleared); a blank message is not posted", 6)
def _():
    u, ws, g, pg, _ = ui_msg_world()
    try:
        send_ui(pg, "hello from the ui")
        wait_last_body(pg, "hello from the ui", "after send-btn")
        expect(pg.input_value(T("message-input")) == "", "message-input should clear after sending")
        pg.fill(T("message-input"), "second via enter")
        pg.press(T("message-input"), "Enter")
        wait_last_body(pg, "second via enter", "after Enter")
        n = rows(pg).count()
        send_ui(pg, "   ")
        time.sleep(0.8)
        expect(rows(pg).count() == n, "a whitespace-only message must not add a row")
        api = listed(u, g["id"])
        expect(len(api) == 2, f"the server should have exactly 2 messages, has {len(api)} (blank message posted?)")
    finally:
        close(pg)


@rule("E6.2", "hover toolbar [data-action=edit]: input[name=edit-body], Enter saves; '(edited)' shows and survives reload", 6)
def _():
    u, ws, g, pg, (m,) = ui_msg_world(["edit me"])
    try:
        wait_visible(pg, f'[data-testid="message"][data-message-id="{m["id"]}"]', "a message posted before the page opened is listed")
        r = row(pg, m["id"])
        r.hover()
        r.locator('[data-action="edit"]').first.click()
        inp = r.locator('input[name="edit-body"]').first
        try:
            inp.wait_for(state="visible", timeout=3000)
        except Exception:
            raise CheckFail("clicking [data-action=edit] should show input[name=edit-body] in the row")
        expect(inp.input_value() == "edit me", f"edit-body should start with the current text, got {inp.input_value()!r}")
        inp.fill("edited text")
        inp.press("Enter")
        wait_text(pg, f'[data-message-id="{m["id"]}"] [data-testid="message-body"]', "edited text", "after saving the edit")
        wait_visible(pg, f'[data-message-id="{m["id"]}"] .edited', "the edited indicator (class 'edited')")
        api = next(x for x in listed(u, g["id"]) if same(x["id"], m["id"]))
        expect(api.get("body") == "edited text" and api.get("edited_at"), "the edit was not saved on the server")
        pg.reload(wait_until="domcontentloaded")
        open_channel(pg, g)
        wait_text(pg, f'[data-message-id="{m["id"]}"] [data-testid="message-body"]', "edited text", "after reload")
        wait_visible(pg, f'[data-message-id="{m["id"]}"] .edited', "edited indicator after reload")
    finally:
        close(pg)


@rule("E6.3", "hover toolbar [data-action=delete] removes the row (no dialog); still gone after reload", 6)
def _():
    u, ws, g, pg, (keep, m) = ui_msg_world(["keep me", "delete me"])
    try:
        sel = f'[data-testid="message"][data-message-id="{m["id"]}"]'
        wait_visible(pg, sel, "a message posted before the page opened is listed")
        r = row(pg, m["id"])
        r.hover()
        r.locator('[data-action="delete"]').first.click()
        wait_hidden(pg, sel, "after delete", 4000)
        expect(not any("dialog" in e for e in pg.errors), "delete must not open a browser dialog")
        expect(not any(same(x["id"], m["id"]) for x in listed(u, g["id"])), "the message was not deleted on the server")
        pg.reload(wait_until="domcontentloaded")
        open_channel(pg, g)
        wait_visible(pg, f'[data-testid="message"][data-message-id="{keep["id"]}"]', "other message after reload")
        expect(row(pg, m["id"]).count() == 0, "the deleted message is back after reload")
    finally:
        close(pg)


@rule("E6.4", "open-thread-btn opens thread-panel; a reply appears there and the parent shows '1 reply' then '2 replies'", 6)
def _():
    u, ws, g, pg, (m,) = ui_msg_world(["thread parent"])
    try:
        sel = f'[data-testid="message"][data-message-id="{m["id"]}"]'
        wait_visible(pg, sel, "a message posted before the page opened is listed")
        r = row(pg, m["id"])
        r.hover()
        r.locator('[data-testid="open-thread-btn"]').first.click()
        wait_visible(pg, T("thread-panel"), "after open-thread-btn")
        wait_text(pg, T("thread-panel"), "thread parent", "thread-panel should show the parent")
        pg.fill(T("thread-input"), "first reply")
        pg.click(T("thread-send"))
        wait_text(pg, T("thread-panel"), "first reply", "reply in the thread panel")
        wait_text(pg, f'{sel} .reply-count', "1 reply", "parent reply-count")
        pg.fill(T("thread-input"), "second reply")
        pg.press(T("thread-input"), "Enter")
        wait_text(pg, f'{sel} .reply-count', "2 replies", "parent reply-count after the second reply")
        api = next(x for x in listed(u, g["id"]) if same(x["id"], m["id"]))
        expect(api.get("reply_count") == 2, f"server reply_count should be 2, got {api.get('reply_count')}")
        pg.click(T("close-thread"))
        wait_hidden(pg, T("thread-panel"), "after close-thread")
    finally:
        close(pg)


@rule("E6.5", "reaction-button opens emoji-picker (>= 8 emoji-option); picking one shows a reaction-chip with count; clicking it removes", 6)
def _():
    u, ws, g, pg, (m,) = ui_msg_world(["react here"])
    try:
        sel = f'[data-testid="message"][data-message-id="{m["id"]}"]'
        wait_visible(pg, sel, "a message posted before the page opened is listed")
        r = row(pg, m["id"])
        r.hover()
        r.locator('[data-testid="reaction-button"]').first.click()
        wait_visible(pg, T("emoji-picker"), "after reaction-button")
        opts = pg.locator(f'{T("emoji-picker")} [data-testid="emoji-option"]')
        expect(opts.count() >= 8, f"emoji-picker should offer at least 8 emoji-option buttons, has {opts.count()}")
        emoji = opts.first.inner_text().strip()
        opts.first.click()
        chip = f'{sel} [data-testid="reaction-chip"]'
        wait_visible(pg, chip, "after picking an emoji")
        txt = pg.locator(chip).first.inner_text()
        expect("1" in txt, f"reaction-chip should show the count 1, got {txt!r}")
        api = next(x for x in listed(u, g["id"]) if same(x["id"], m["id"]))
        expect(api.get("reactions") and api["reactions"][0].get("count") == 1, f"server should have the reaction: {api.get('reactions')}")
        pg.locator(chip).first.click()
        end = time.time() + 4
        while time.time() < end:
            try:
                texts = pg.locator(chip).all_inner_texts()
            except Exception:
                texts = []
            if not any("1" in t for t in texts):
                break
            time.sleep(0.15)
        api = next(x for x in listed(u, g["id"]) if same(x["id"], m["id"]))
        expect(not api.get("reactions"), f"clicking your own chip should remove the reaction: {api.get('reactions')}")
    finally:
        close(pg)


@rule("E6.6", "logout-btn clears localStorage['huddle.token'] and shows #auth-modal; logging in again restores the workspace", 6)
def _():
    u, ws, ch = ui_world(("gamma",))
    pg = page(u["token"])
    try:
        wait_text(pg, T("workspace-header"), ws["workspace"].get("name", ""), "workspace-header")
        pg.click(T("logout-btn"))
        wait_visible(pg, "#auth-modal", "after logout")
        expect(not token_in_storage(pg), "logout should remove localStorage['huddle.token']")
        set_mode(pg, "login")
        fill_auth(pg, u["username"], PW)
        wait_hidden(pg, "#auth-modal", "after logging in again")
        wait_text(pg, T("workspace-header"), ws["workspace"].get("name", ""), "workspace-header after logging in again")
        wait_visible(pg, entry_sel(ch["gamma"]), "channel entries after logging in again")
    finally:
        close(pg)


@rule("E6.7", "layout: coloured sidebar, message pane and thread panel side by side; others' new messages appear live", 6)
def _():
    u, ws, g, pg, (m,) = ui_msg_world(["parent for layout"])
    try:
        other = add_member(ws, u)
        bg = pg.evaluate("""() => { const l = document.querySelector('[data-testid="channel-list"]');
            let e = l; while (e && e !== document.body) { const c = getComputedStyle(e).backgroundColor;
            if (c && c !== 'rgba(0, 0, 0, 0)' && c !== 'transparent') return c; e = e.parentElement; } return null; }""")
        expect(bg and bg not in ("rgb(255, 255, 255)",), f"the sidebar (around channel-list) should have a coloured background, got {bg}")
        wait_visible(pg, f'[data-message-id="{m["id"]}"]', "message appears")
        r = row(pg, m["id"])
        r.hover()
        r.locator('[data-testid="open-thread-btn"]').first.click()
        wait_visible(pg, T("thread-panel"), "thread panel")
        boxes = [pg.locator(T(t)).first.bounding_box() for t in ("channel-list", "message-list", "thread-panel")]
        expect(all(boxes), f"panes have no layout box: {boxes}")
        xs = [b["x"] for b in boxes]
        expect(xs[0] < xs[1] < xs[2] and boxes[1]["x"] + boxes[1]["width"] <= boxes[2]["x"] + 2,
               f"sidebar, message list and thread panel should sit left to right without overlap; x = {xs}")
        post(other, g["id"], "live from someone else", node=2)
        wait_text(pg, T("message-list"), "live from someone else", "a message posted by another user should appear within 4s", 5000)
    finally:
        close(pg)


# ======================================================================= E7 settings UI
def ws_role(owner, ws, uid):
    r = want(call("GET", f"/api/workspaces/{ws['slug']}/members", token=owner["token"]), 200, "GET members")
    return next((m.get("role") for m in r["members"] if same(m.get("user_id"), uid)), None)


def open_ws_settings(pg):
    pg.click(T("workspace-settings-btn"))
    wait_visible(pg, "#workspace-settings-modal", "after workspace-settings-btn")


def tab(pg, name):
    pg.click(T(f"settings-tab-{name}"))
    wait_visible(pg, T(f"settings-pane-{name}"), f"after settings-tab-{name}")


def wait_count(pg, sel, n, what, timeout=4000):
    end, c = time.time() + timeout / 1000, 0
    while time.time() < end:
        c = pg.locator(sel).count()
        if c >= n:
            return c
        time.sleep(0.15)
    raise CheckFail(f"{what}: expected at least {n} x {sel}, found {c}")


@rule("E7.1", "workspace settings: member-row + role-badge per member; tabs show exactly one pane; close hides", 7)
def _():
    u, ws, ch = ui_world(())
    v = add_member(ws, u)
    pg = page(u["token"])
    try:
        open_ws_settings(pg)
        wait_visible(pg, T("settings-pane-members"), "Members pane on open")
        wait_count(pg, f'{T("settings-pane-members")} [data-testid="member-row"]', 2, "member rows")
        own = pg.locator(f'[data-testid="member-row"][data-user-id="{u["id"]}"] [data-testid="role-badge"]')
        expect(own.count() == 1 and "owner" in own.first.inner_text().lower(), "the owner's member-row should hold a role-badge reading 'owner'")
        mem = pg.locator(f'[data-testid="member-row"][data-user-id="{v["id"]}"] [data-testid="role-badge"]')
        expect(mem.count() == 1 and "member" in mem.first.inner_text().lower(), "the member's member-row should hold a role-badge reading 'member'")
        for name in ("invitations", "general", "members"):
            tab(pg, name)
            vis = [p for p in ("members", "invitations", "general") if visible(pg, T(f"settings-pane-{p}"))]
            expect(vis == [name], f"after settings-tab-{name}, exactly settings-pane-{name} should be visible, visible: {vis}")
        pg.click(T("workspace-settings-close"))
        wait_hidden(pg, "#workspace-settings-modal", "after workspace-settings-close")
    finally:
        close(pg)


@rule("E7.2", "as owner, role-select -> admin PATCHes the role; the role-badge and the server show admin", 7)
def _():
    u, ws, ch = ui_world(())
    v = add_member(ws, u)
    pg = page(u["token"])
    try:
        open_ws_settings(pg)
        row = f'[data-testid="member-row"][data-user-id="{v["id"]}"]'
        wait_visible(pg, f'{row} [data-testid="role-select"]', "role-select in the member's row")
        expect(pg.locator(f'[data-testid="member-row"][data-user-id="{u["id"]}"] [data-testid="role-select"]').count() == 0,
               "the owner's own row must not have a role-select")
        pg.locator(f'{row} [data-testid="role-select"]').first.select_option("admin")
        wait_text(pg, f'{row} [data-testid="role-badge"]', "admin", "role-badge after choosing admin")
        end = time.time() + 3
        while time.time() < end and ws_role(u, ws, v["id"]) != "admin":
            time.sleep(0.2)
        expect(ws_role(u, ws, v["id"]) == "admin", f"the server should now have role admin, has {ws_role(u, ws, v['id'])}")
    finally:
        close(pg)


@rule("E7.3", "Invitations tab: create-invitation-btn -> form; submit adds an invitation-code that another user can accept", 7)
def _():
    u, ws, ch = ui_world(())
    pg = page(u["token"])
    try:
        open_ws_settings(pg)
        tab(pg, "invitations")
        before = pg.locator(f'{T("invitations-list")} [data-testid="invitation-code"]').count()
        pg.click(T("create-invitation-btn"))
        wait_visible(pg, "#create-invitation-form", "after create-invitation-btn")
        pg.click(T("create-invitation-submit"))
        wait_count(pg, f'{T("invitations-list")} [data-testid="invitation-code"]', before + 1, "after creating an invitation")
        codes = [t.strip() for t in pg.locator(f'{T("invitations-list")} [data-testid="invitation-code"]').all_inner_texts()]
        r = want(call("GET", f"/api/workspaces/{ws['slug']}/invitations", token=u["token"]), 200, "list invitations")
        server = {i.get("code") for i in r["invitations"]}
        new = [c for c in codes if c in server]
        expect(new, f"invitation-code text should be exactly a server invitation code; UI shows {codes[:3]}, server has {sorted(server)[:3]}")
        x = new_user("inv")
        want(call("POST", f"/api/invitations/{new[-1]}/accept", None, x["token"]), 200, "another user accepts the code shown in the UI")
    finally:
        close(pg)


@rule("E7.4", "General tab: name + join mode prefilled; workspace-general-submit saves; header shows the new name after reload", 7)
def _():
    u, ws, ch = ui_world(())
    pg = page(u["token"])
    try:
        open_ws_settings(pg)
        tab(pg, "general")
        cur = pg.input_value(T("workspace-name-input"))
        expect(cur == ws["workspace"]["name"], f"workspace-name-input should hold the current name {ws['workspace']['name']!r}, holds {cur!r}")
        expect(pg.input_value(T("workspace-join-mode")) == "open", "workspace-join-mode should show 'open'")
        new = "Renamed " + rid(5)
        pg.fill(T("workspace-name-input"), new)
        pg.select_option(T("workspace-join-mode"), "invite_only")
        pg.click(T("workspace-general-submit"))
        wait_text(pg, T("workspace-header"), new, "workspace-header after saving")
        r = want(call("GET", f"/api/workspaces/{ws['slug']}", token=u["token"]), 200, "GET workspace")
        expect(r["workspace"].get("name") == new and r["workspace"].get("join_mode") == "invite_only",
               f"server should have the new name and join_mode invite_only: {r['workspace']}")
        pg.reload(wait_until="domcontentloaded")
        wait_text(pg, T("workspace-header"), new, "workspace-header after reload")
    finally:
        close(pg)


@rule("E7.5", "join-workspace-form: a valid code joins and switches workspace; an unknown code shows join-workspace-error", 7)
def _():
    u, ws, ch = ui_world(())
    code = want(call("POST", f"/api/workspaces/{ws['slug']}/invitations", {"max_uses": 1}, u["token"]), 201, "create invitation")["invitation"]["code"]
    x = new_user("jn")
    pg = page(x["token"])
    try:
        f = T("join-workspace-form")
        pg.fill(f'{f} input[name="code"]', "nope-" + rid(8))
        pg.click(T("join-workspace-submit"))
        err = T("join-workspace-error")
        end, txt = time.time() + 4, ""
        while time.time() < end and not txt:
            if visible(pg, err):
                txt = pg.inner_text(err).strip()
            time.sleep(0.15)
        expect(txt, "an unknown code should show visible, non-empty text in join-workspace-error")
        pg.fill(f'{f} input[name="code"]', code)
        pg.click(T("join-workspace-submit"))
        wait_text(pg, T("workspace-header"), ws["workspace"]["name"], "workspace-header after joining")
        wait_visible(pg, entry_sel(ch["general"]), "#general of the joined workspace in channel-list")
        r = want(call("GET", "/api/workspaces", token=x["token"]), 200, "GET workspaces")
        expect(any(w.get("slug") == ws["slug"] for w in r["workspaces"]), "the server should list the joined workspace")
    finally:
        close(pg)


@rule("E7.6", "channel settings: title, channel-member-rows, add member, topic, archive then unarchive (modal stays open), close", 7)
def _():
    u, ws, ch = ui_world(("cfg",))
    v = add_member(ws, u)
    c = ch["cfg"]
    pg = page(u["token"])
    try:
        open_channel(pg, c)
        pg.click(T("channel-settings-btn"))
        wait_visible(pg, "#channel-settings-modal", "after channel-settings-btn")
        wait_text(pg, T("channel-settings-title"), "#" + c["name"], "channel-settings-title")
        rows_sel = f'{T("channel-members-list")} [data-testid="channel-member-row"]'
        wait_count(pg, rows_sel, 1, "channel-member-row for the creator")
        n0 = pg.locator(rows_sel).count()
        pg.fill(T("channel-add-member-input"), v["username"])
        pg.click(T("channel-add-member-submit"))
        wait_count(pg, rows_sel, n0 + 1, "after adding a member")
        r = want(call("GET", f"/api/channels/{c['id']}/members", token=u["token"]), 200, "channel members")
        expect(any(same(m.get("id"), v["id"]) for m in r["members"]), "the server should list the added user as a channel member")
        pg.fill(T("channel-topic-input"), "Settings topic")
        pg.click(T("channel-topic-submit"))
        wait_text(pg, T("channel-topic"), "Settings topic", "channel-topic in the header")

        def archived():
            w = want(call("GET", f"/api/workspaces/{ws['slug']}?include_archived=1", token=u["token"]), 200, "workspace")
            return next((x.get("is_archived") for x in w["channels"] if same(x.get("id"), c["id"])), None)
        pg.click(T("archive-channel-btn"))
        end = time.time() + 4
        while time.time() < end and archived() is not True:
            time.sleep(0.2)
        expect(archived() is True, "archive-channel-btn should archive the channel on the server")
        wait_visible(pg, T("unarchive-channel-btn"), "after archiving, the open modal should show unarchive-channel-btn")
        expect(not visible(pg, T("archive-channel-btn")), "after archiving, archive-channel-btn should be hidden")
        pg.click(T("unarchive-channel-btn"))
        end = time.time() + 4
        while time.time() < end and archived() is not False:
            time.sleep(0.2)
        expect(archived() is False, "unarchive-channel-btn should unarchive the channel on the server")
        if visible(pg, "#channel-settings-modal"):
            pg.click(T("channel-settings-close"))
        wait_hidden(pg, "#channel-settings-modal", "after channel-settings-close")
    finally:
        close(pg)


if __name__ == "__main__":
    run()
