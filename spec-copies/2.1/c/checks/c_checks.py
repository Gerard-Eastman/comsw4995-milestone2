"""Component C checks: reactions, DMs, files, slash commands, groups and mentions, profiles.
Usage: python3 c_checks.py <stage>   (stage 1..6, or nothing for all)"""
import os, sys, time, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import *  # noqa
set_comp("c")

MISSING = 999999999


def setup(private=False):
    """owner + member, a workspace, and a channel both are in. Returns dict."""
    o = new_user("own")
    ws = new_workspace(o)
    m = add_member(ws, o)
    ch = new_channel(ws, o, private=private)
    if not private:
        want(join(m, ch["id"]), 200, "setup: member joins the channel")
    return {"o": o, "m": m, "ws": ws, "ch": ch, "cid": ch["id"]}


def react(user, mid, emoji, node=0):
    return call("POST", f"/api/messages/{mid}/reactions", {"emoji": emoji}, user["token"], node)


def unreact(user, mid, emoji, node=0):
    import urllib.parse
    return call("DELETE", f"/api/messages/{mid}/reactions/{urllib.parse.quote(emoji, safe='')}", None, user["token"], node)


def entry(reactions, emoji):
    for r in reactions or []:
        if isinstance(r, dict) and r.get("emoji") == emoji:
            return r
    return None


def ids(lst):
    return sorted(str(x) for x in (lst or []))


def kinds(frames):
    return [f.get("type") for f in frames]


# ======================================================================= C1 reactions
@rule("C1.1", "POST reactions -> 200 {reactions: [{emoji, count, user_ids}]} on first insert; bad emoji -> 400", 1)
def _():
    s = setup()
    msg = post(s["o"], s["cid"], "react to me")
    r = react(s["o"], msg["id"], "👍")
    want(r, 200, "first reaction (must be 200, not 201)")
    e = entry(r["reactions"], "👍")
    expect(e is not None, f"reactions should contain an entry for 👍: {r.text[:160]}")
    expect(e.get("count") == 1 and ids(e.get("user_ids")) == ids([s["o"]["id"]]),
           f"expected {{emoji:'👍', count:1, user_ids:[{s['o']['id']}]}}, got {e}")
    want(react(s["o"], msg["id"], ""), 400, "empty emoji")
    want(react(s["o"], msg["id"], "x" * 65), 400, "65-character emoji")
    want(call("POST", f"/api/messages/{msg['id']}/reactions", {}, s["o"]["token"]), 400, "missing emoji")


@rule("C1.2", "reactions are idempotent per (user, emoji); a second user makes count 2", 1)
def _():
    s = setup()
    msg = post(s["o"], s["cid"], "idem")
    want(react(s["o"], msg["id"], "🎉"), 200, "first reaction")
    r = want(react(s["o"], msg["id"], "🎉", node=1), 200, "same reaction again (on 8001)")
    e = entry(r["reactions"], "🎉")
    expect(e and e.get("count") == 1, f"same user reacting twice must leave count 1, got {e}")
    r = want(react(s["m"], msg["id"], "🎉", node=2), 200, "second user's reaction")
    e = entry(r["reactions"], "🎉")
    expect(e and e.get("count") == 2 and ids(e.get("user_ids")) == ids([s["o"]["id"], s["m"]["id"]]),
           f"expected count 2 and both user ids, got {e}")


@rule("C1.3", "DELETE reactions/{emoji} removes only the caller's reaction -> 200 {reactions}", 1)
def _():
    s = setup()
    msg = post(s["o"], s["cid"], "unreact")
    react(s["o"], msg["id"], "👍")
    react(s["m"], msg["id"], "👍")
    r = want(unreact(s["o"], msg["id"], "👍"), 200, "remove own reaction")
    e = entry(r["reactions"], "👍")
    expect(e and e.get("count") == 1 and ids(e.get("user_ids")) == ids([s["m"]["id"]]),
           f"only the caller's reaction should go; expected count 1 with the other user, got {e}")
    want(unreact(s["o"], msg["id"], "👍"), 200, "removing a reaction you no longer have")
    r = want(unreact(s["m"], msg["id"], "👍"), 200, "last user removes theirs")
    expect(entry(r["reactions"], "👍") is None, f"an emoji with count 0 must disappear from the list: {r.text[:160]}")


@rule("C1.4", "GET /api/channels/{id}/messages shows each message's reactions", 1)
def _():
    s = setup()
    msg = post(s["o"], s["cid"], "listed")
    react(s["m"], msg["id"], "🔥")
    r = want(call("GET", f"/api/channels/{s['cid']}/messages", token=s["o"]["token"], node=1), 200, "list messages")
    m = next((x for x in r["messages"] if same(x.get("id"), msg["id"])), None)
    expect(m is not None, "message missing from the list")
    e = entry(m.get("reactions"), "🔥")
    expect(e and e.get("count") == 1 and ids(e.get("user_ids")) == ids([s["m"]["id"]]),
           f"listed message.reactions should be [{{emoji:'🔥', count:1, user_ids:[{s['m']['id']}]}}], got {m.get('reactions')}")


@rule("C1.5", "reaction errors: 401 no token, 404 unknown message, 403 cannot read, 423 archived", 1)
def _():
    s = setup()
    msg = post(s["o"], s["cid"], "errs")
    r = call("POST", f"/api/messages/{msg['id']}/reactions", {"emoji": "👍"})
    want(r, 401, "no token")
    want(react(s["o"], MISSING, "👍"), 404, "unknown message id")
    priv = new_channel(s["ws"], s["o"], private=True)
    pm = post(s["o"], priv["id"], "secret")
    want(react(s["m"], pm["id"], "👍"), 403, "non-member of a private channel reacting")
    want(call("POST", f"/api/channels/{s['cid']}/archive", None, s["o"]["token"]), 200, "setup: owner archives the channel")
    want(react(s["o"], msg["id"], "👍"), 423, "reaction in an archived channel")


@rule("C1.6", "reaction.added / reaction.removed events with {message_id, emoji, user_id, reactions}; no-ops emit nothing", 1)
def _():
    s = setup()
    msg = post(s["o"], s["cid"], "events")
    c = ws_connect(s["m"]["token"], node=1)
    try:
        head = ws_subscribe(c, s["cid"])
        react(s["o"], msg["id"], "👍")
        react(s["o"], msg["id"], "👍")          # no-op
        unreact(s["o"], msg["id"], "👍")
        unreact(s["o"], msg["id"], "👍")        # no-op
        marker = post(s["o"], s["cid"], "marker", node=2)
        f, seen = ws_recv_until(c, lambda f: f.get("type") == "message.created" and same((f.get("message") or {}).get("id"), marker["id"]), 4)
        expect(f is not None, f"no message.created for the marker message within 4s (saw {kinds(seen)})")
        rx = [x for x in seen if str(x.get("type", "")).startswith("reaction.")]
        expect(kinds(rx) == ["reaction.added", "reaction.removed"],
               f"expected exactly [reaction.added, reaction.removed] (repeats emit nothing), got {kinds(rx)}")
        a = rx[0]
        for k in ("message_id", "emoji", "user_id", "reactions", "event_id", "channel_id"):
            expect(k in a, f"reaction.added frame is missing '{k}': {str(a)[:200]}")
        expect(same(a["message_id"], msg["id"]) and a["emoji"] == "👍" and same(a["user_id"], s["o"]["id"]),
               f"reaction.added has wrong message_id/emoji/user_id: {str(a)[:200]}")
        expect(a.get("event_id") == head + 1 and rx[1].get("event_id") == head + 2 and f.get("event_id") == head + 3,
               f"event_ids should be dense: {[x.get('event_id') for x in rx + [f]]} after head {head}")
    finally:
        c.close()


# ======================================================================= C2 DMs
def dm(a, b, node=0):
    return call("POST", "/api/dms", {"user_id": b["id"]}, a["token"], node)


@rule("C2.1", "POST /api/dms {user_id} -> 200 {channel_id}", 2)
def _():
    a, b = new_user("dma"), new_user("dmb")
    r = want(dm(a, b), 200, "POST /api/dms (200 also on the first call)")
    expect(r["channel_id"] is not None, f"channel_id must be set: {r.text[:120]}")


@rule("C2.2", "the same DM channel_id comes back on repeats, in both directions, on any node", 2)
def _():
    a, b = new_user("dma"), new_user("dmb")
    c1 = want(dm(a, b), 200, "A->B")["channel_id"]
    c2 = want(dm(a, b, node=1), 200, "A->B again on 8001")["channel_id"]
    c3 = want(dm(b, a, node=2), 200, "B->A on 8002")["channel_id"]
    expect(same(c1, c2) and same(c1, c3), f"expected one channel id, got {c1}, {c2}, {c3}")
    c = new_user("dmc")
    c4 = want(dm(a, c), 200, "A->C")["channel_id"]
    expect(not same(c1, c4), "a different pair of users must get a different DM channel")


@rule("C2.3", "POST /api/dms errors: 400 missing/non-integer user_id, 404 unknown user, 401 no token", 2)
def _():
    a, b = new_user("dma"), new_user("dmb")
    want(call("POST", "/api/dms", {}, a["token"]), 400, "missing user_id")
    want(call("POST", "/api/dms", {"user_id": "abc"}, a["token"]), 400, "user_id 'abc'")
    want(call("POST", "/api/dms", {"user_id": MISSING}, a["token"]), 404, "unknown user")
    want(call("POST", "/api/dms", {"user_id": b["id"]}), 401, "no token")


@rule("C2.4", "both DM users can post and read via the message routes; a third user gets 403", 2)
def _():
    a, b, x = new_user("dma"), new_user("dmb"), new_user("dmx")
    cid = want(dm(a, b), 200, "create DM")["channel_id"]
    m1 = post(a, cid, "hi b")
    post(b, cid, "hi a", node=1)
    r = want(call("GET", f"/api/channels/{cid}/messages", token=b["token"], node=2), 200, "B reads the DM")
    expect(any(same(m.get("id"), m1["id"]) for m in r["messages"]), "B does not see A's DM message")
    want(call("GET", f"/api/channels/{cid}/messages", token=x["token"]), 403, "third user reads the DM")
    want(call("POST", f"/api/channels/{cid}/messages", {"body": "intrude"}, x["token"]), 403, "third user posts to the DM")


@rule("C2.5", "DM channels never appear in GET /api/workspaces/{slug} channels", 2)
def _():
    s = setup()
    cid = want(dm(s["o"], s["m"]), 200, "create DM between two workspace members")["channel_id"]
    for u in (s["o"], s["m"]):
        r = want(call("GET", f"/api/workspaces/{s['ws']['slug']}", token=u["token"]), 200, "GET workspace")
        bad = [c for c in r["channels"] if same(c.get("id"), cid) or c.get("is_dm")]
        expect(not bad, f"DM channel listed in workspace channels: {bad}")


# ======================================================================= C3 files
@rule("C3.1", "POST /api/files multipart 'file' -> 201 {file: {id, uploader_id, filename, content_type, size, created_at}}", 3)
def _():
    u = new_user("up")
    r = want(upload(u["token"], b"hello", "note.txt", "text/plain"), 201, "upload a 5-byte file")
    f = r["file"]
    for k in ("id", "uploader_id", "filename", "content_type", "size", "created_at"):
        expect(k in f, f"FileObj is missing '{k}': {r.text[:200]}")
    expect(same(f["uploader_id"], u["id"]) and f["filename"] == "note.txt" and f["content_type"] == "text/plain"
           and f["size"] == 5, f"FileObj fields wrong (want uploader {u['id']}, note.txt, text/plain, size 5): {f}")


@rule("C3.2", "upload limits: > 10 MiB -> 413, exactly 10 MiB -> 201, no 'file' part -> 400, no token -> 401", 3)
def _():
    u = new_user("up")
    big = b"\0" * (10 * 1024 * 1024)
    want(upload(u["token"], big + b"\0", "big.bin", "application/octet-stream"), 413, "10 MiB + 1 byte upload")
    r = want(upload(u["token"], big, "max.bin", "application/octet-stream"), 201, "exactly 10 MiB upload")
    expect(r["file"].get("size") == len(big), f"size should be {len(big)}: {r.text[:160]}")
    want(upload(u["token"], b"abc", "a.txt", "text/plain", field="other"), 400, "multipart without a 'file' part")
    want(call("POST", "/api/files", {"x": 1}, u["token"]), 400, "JSON body instead of multipart")
    want(upload(None, b"abc"), 401, "no token")


@rule("C3.3", "GET /api/files/{id} -> 200 {file} on every node; unknown -> 404", 3)
def _():
    u = new_user("up")
    f = want(upload(u["token"], b"data", "d.txt", "text/plain"), 201, "upload")["file"]
    for n in (0, 1, 2):
        r = want(call("GET", f"/api/files/{f['id']}", token=u["token"], node=n), 200, f"GET file on {8000 + n}")
        expect(same(r["file"].get("id"), f["id"]) and r["file"].get("filename") == "d.txt", f"wrong file: {r.text[:160]}")
    want(call("GET", f"/api/files/{MISSING}", token=u["token"]), 404, "unknown file")


@rule("C3.4", "download -> exact bytes, Content-Type = stored type, Content-Disposition attachment with filename", 3)
def _():
    u = new_user("up")
    data = bytes(range(256)) * 4
    f = want(upload(u["token"], data, "pic.png", "image/png"), 201, "upload")["file"]
    r = raw_get(f"/api/files/{f['id']}/download", u["token"], node=2)
    expect(r.status_code == 200, f"download: expected 200, got {r.status_code}")
    expect(r.content == data, f"downloaded bytes differ from the upload ({len(r.content)} vs {len(data)} bytes)")
    ct = r.headers.get("Content-Type", "").split(";")[0].strip()
    expect(ct == "image/png", f"Content-Type should be image/png, got {r.headers.get('Content-Type')}")
    cd = r.headers.get("Content-Disposition", "")
    expect("attachment" in cd and "pic.png" in cd and "filename" in cd,
           f"Content-Disposition should be attachment; filename=\"pic.png\", got {cd!r}")
    r = raw_get(f"/api/files/{MISSING}/download", u["token"])
    expect(r.status_code == 404, f"unknown download: expected 404, got {r.status_code}")


@rule("C3.5", "file_ids attach own unattached files to a message; foreign/attached/unknown -> 400 and nothing posted", 3)
def _():
    s = setup()
    f1 = want(upload(s["o"]["token"], b"one", "one.txt", "text/plain"), 201, "upload")["file"]
    r = want(call("POST", f"/api/channels/{s['cid']}/messages", {"body": "see file", "file_ids": [f1["id"]]}, s["o"]["token"]),
             201, "post with file_ids")
    files = r["message"].get("files") or []
    expect(len(files) == 1 and same(files[0].get("id"), f1["id"]) and files[0].get("filename") == "one.txt",
           f"message.files should hold the FileObj: {r.text[:200]}")
    lst = want(call("GET", f"/api/channels/{s['cid']}/messages", token=s["m"]["token"]), 200, "list")
    lm = next((x for x in lst["messages"] if same(x.get("id"), r["message"]["id"])), {})
    expect(len(lm.get("files") or []) == 1, f"listed message should carry its files: {str(lm)[:200]}")
    before = len(lst["messages"])
    mine = want(upload(s["m"]["token"], b"m", "m.txt", "text/plain"), 201, "member upload")["file"]
    cases = [([f1["id"]], "a file already attached"), ([mine["id"]], "someone else's file"),
             ([MISSING], "an unknown file id"), ("x", "file_ids not a list")]
    for fids, what in cases:
        want(call("POST", f"/api/channels/{s['cid']}/messages", {"body": "bad", "file_ids": fids}, s["o"]["token"]), 400, what)
    after = len(want(call("GET", f"/api/channels/{s['cid']}/messages", token=s["o"]["token"]), 200, "list")["messages"])
    expect(after == before, f"a rejected post must not create a message ({before} -> {after} messages)")


# ======================================================================= C4 slash commands
def slash(user, cid, body, node=0):
    return call("POST", f"/api/channels/{cid}/messages", {"body": body}, user["token"], node)


SHRUG = "¯\\_(ツ)_/¯"


@rule("C4.1", "'//rest' posts '/rest'; '/me waves' is kept literally; '/me' alone -> 400", 4)
def _():
    s = setup()
    r = want(slash(s["o"], s["cid"], "//rest of it"), 201, "//rest of it")
    expect(r["message"].get("body") == "/rest of it", f"body should be '/rest of it', got {r['message'].get('body')!r}")
    r = want(slash(s["o"], s["cid"], "/me waves"), 201, "/me waves")
    expect(r["message"].get("body") == "/me waves", f"body should stay '/me waves', got {r['message'].get('body')!r}")
    want(slash(s["o"], s["cid"], "/me"), 400, "/me with no text")


@rule("C4.2", "'/shrug ok' -> body 'ok ¯\\_(ツ)_/¯'; '/shrug' -> '¯\\_(ツ)_/¯' (one backslash)", 4)
def _():
    s = setup()
    r = want(slash(s["o"], s["cid"], "/shrug ok"), 201, "/shrug ok")
    expect(r["message"].get("body") == "ok " + SHRUG, f"body should be {('ok ' + SHRUG)!r}, got {r['message'].get('body')!r}")
    r = want(slash(s["o"], s["cid"], "/shrug"), 201, "/shrug")
    expect(r["message"].get("body") == SHRUG, f"body should be {SHRUG!r}, got {r['message'].get('body')!r}")


@rule("C4.3", "'/topic text' -> 201 {message: null, channel} with the topic set; '/topic' clears; > 250 chars -> 400", 4)
def _():
    s = setup()
    r = want(slash(s["m"], s["cid"], "/topic Ship it"), 201, "/topic Ship it")
    expect("message" in r.body and r.body["message"] is None, f"message must be null: {r.text[:160]}")
    expect(r["channel"].get("topic") == "Ship it", f"channel.topic should be 'Ship it': {r.text[:160]}")
    w = want(call("GET", f"/api/workspaces/{s['ws']['slug']}", token=s["o"]["token"], node=1), 200, "GET workspace")
    ch = next((c for c in w["channels"] if same(c.get("id"), s["cid"])), {})
    expect(ch.get("topic") == "Ship it", f"topic not persisted: {ch}")
    want(slash(s["m"], s["cid"], "/topic " + "t" * 251), 400, "/topic with 251 characters")
    r = want(slash(s["m"], s["cid"], "/topic"), 201, "/topic with no text")
    expect(r["channel"].get("topic") == "", f"'/topic' alone should set the topic to '': {r.text[:160]}")


@rule("C4.4", "'/invite @user' -> 201 {message: null, invited_user}; then they can read the private channel", 4)
def _():
    s = setup(private=True)
    v = add_member(s["ws"], s["o"])
    want(call("GET", f"/api/channels/{s['cid']}/messages", token=v["token"]), 403, "setup: non-member reads private channel")
    r = want(slash(s["o"], s["cid"], f"/invite @{v['username']}"), 201, "/invite @user")
    expect("message" in r.body and r.body["message"] is None, f"message must be null: {r.text[:160]}")
    expect(same(r["invited_user"].get("id"), v["id"]), f"invited_user.id should be {v['id']}: {r.text[:160]}")
    want(call("GET", f"/api/channels/{s['cid']}/messages", token=v["token"], node=1), 200, "invited user reads the channel")
    want(slash(s["o"], s["cid"], f"/invite @{v['username']}"), 201, "inviting a current member again")
    want(slash(s["m"], s["cid"], f"/invite @{v['username']}"), 403, "/invite by a non-member of the channel")
    want(slash(s["o"], s["cid"], "/invite"), 400, "/invite with no @user")
    want(slash(s["o"], s["cid"], "/invite @nosuchuser" + rid(5)), 404, "/invite of an unknown user")
    out = new_user("out")
    want(slash(s["o"], s["cid"], f"/invite @{out['username']}"), 400, "/invite of a user outside the workspace")


@rule("C4.5", "'/archive' and '/unarchive' (owner only) -> 201 {message: null, channel}; archived channel -> 423", 4)
def _():
    s = setup()
    want(slash(s["m"], s["cid"], "/archive"), 403, "/archive by a non-owner")
    r = want(slash(s["o"], s["cid"], "/archive"), 201, "/archive by the owner")
    expect(r.body.get("message", "x") is None and r["channel"].get("is_archived") is True, f"expected message null, is_archived true: {r.text[:160]}")
    want(slash(s["o"], s["cid"], "hello"), 423, "normal post to the archived channel")
    want(slash(s["o"], s["cid"], "/shrug"), 423, "/shrug in the archived channel")
    r = want(slash(s["o"], s["cid"], "/unarchive"), 201, "/unarchive in the archived channel")
    expect(r["channel"].get("is_archived") is False, f"is_archived should be false: {r.text[:160]}")
    want(slash(s["o"], s["cid"], "hello again"), 201, "post after /unarchive")


@rule("C4.6", "unknown '/foo' -> 400 and nothing posted; /me, /shrug, // emit message.created", 4)
def _():
    s = setup()
    before = len(want(call("GET", f"/api/channels/{s['cid']}/messages", token=s["o"]["token"]), 200, "list")["messages"])
    want(slash(s["o"], s["cid"], "/foo bar"), 400, "/foo bar")
    after = len(want(call("GET", f"/api/channels/{s['cid']}/messages", token=s["o"]["token"]), 200, "list")["messages"])
    expect(after == before, "an unknown command must not post a message")
    c = ws_connect(s["m"]["token"], node=2)
    try:
        ws_subscribe(c, s["cid"])
        slash(s["o"], s["cid"], "/me dances")
        f, seen = ws_recv_until(c, lambda f: f.get("type") == "message.created", 3)
        expect(f is not None and (f.get("message") or {}).get("body") == "/me dances",
               f"expected message.created with body '/me dances', saw {[(x.get('type'), (x.get('message') or {}).get('body')) for x in seen]}")
    finally:
        c.close()


# ======================================================================= C5 groups and mentions
def mk_group(user, ws, handle, user_ids, name="Team", node=0):
    return call("POST", f"/api/workspaces/{ws['slug']}/groups", {"handle": handle, "name": name, "user_ids": user_ids}, user["token"], node)


@rule("C5.1", "POST groups -> 201 {group: {id, handle, name, member_user_ids}}; bad input 400; duplicate 409; non-member 403", 5)
def _():
    s = setup()
    h = "team-" + rid(5)
    r = want(mk_group(s["m"], s["ws"], h, [s["o"]["id"], s["m"]["id"]]), 201, "member creates a group")
    g = r["group"]
    expect(g.get("handle") == h and g.get("name") == "Team" and g.get("id") is not None, f"GroupObj wrong: {g}")
    expect(ids(g.get("member_user_ids")) == ids([s["o"]["id"], s["m"]["id"]]),
           f"member_user_ids should be both ids (key 'member_user_ids'): {g}")
    want(mk_group(s["o"], s["ws"], h, []), 409, "duplicate handle")
    for bad, what in (("Bad_Handle", "handle with uppercase/underscore"), ("here", "handle 'here'"),
                      ("channel", "handle 'channel'"), ("-x", "handle starting with '-'")):
        want(mk_group(s["o"], s["ws"], bad, []), 400, what)
    want(mk_group(s["o"], s["ws"], "ok-" + rid(4), [], name=""), 400, "empty name")
    out = new_user("out")
    want(mk_group(s["o"], s["ws"], "ok-" + rid(4), [out["id"]]), 400, "user_ids with a non-member")
    want(mk_group(out, s["ws"], "ok-" + rid(4), []), 403, "non-member creates a group")
    want(call("POST", "/api/workspaces/nosuch-" + rid(5) + "/groups", {"handle": "abc", "name": "x"}, s["o"]["token"]), 404, "unknown workspace")


@rule("C5.2", "GET groups -> 200 {groups}; non-member -> 403", 5)
def _():
    s = setup()
    h = "grp-" + rid(5)
    want(mk_group(s["o"], s["ws"], h, [s["m"]["id"]]), 201, "create group")
    r = want(call("GET", f"/api/workspaces/{s['ws']['slug']}/groups", token=s["m"]["token"], node=1), 200, "list groups")
    g = next((x for x in r["groups"] if x.get("handle") == h), None)
    expect(g is not None and ids(g.get("member_user_ids")) == ids([s["m"]["id"]]), f"group missing or wrong in list: {r.text[:200]}")
    out = new_user("out")
    want(call("GET", f"/api/workspaces/{s['ws']['slug']}/groups", token=out["token"]), 403, "non-member lists groups")


@rule("C5.3", "PATCH/DELETE groups/{handle}: creator or owner only (403); unknown PATCH 404; DELETE idempotent 200", 5)
def _():
    s = setup()
    x = add_member(s["ws"], s["o"])
    h = "grp-" + rid(5)
    want(mk_group(s["m"], s["ws"], h, []), 201, "member creates group")
    path = f"/api/workspaces/{s['ws']['slug']}/groups/{h}"
    r = want(call("PATCH", path, {"name": "Renamed", "user_ids": [s["m"]["id"], x["id"]]}, s["m"]["token"]), 200, "creator PATCH")
    expect(r["group"].get("name") == "Renamed" and ids(r["group"].get("member_user_ids")) == ids([s["m"]["id"], x["id"]]),
           f"PATCH not applied: {r.text[:200]}")
    want(call("PATCH", path, {"name": "Hijack"}, x["token"]), 403, "PATCH by another member")
    want(call("PATCH", path, {"name": "ByOwner"}, s["o"]["token"], node=1), 200, "PATCH by the workspace owner")
    lst = want(call("GET", f"/api/workspaces/{s['ws']['slug']}/groups", token=x["token"]), 200, "list")
    g = next((q for q in lst["groups"] if q.get("handle") == h), {})
    expect(g.get("name") == "ByOwner", f"PATCH not persisted: {g}")
    want(call("PATCH", f"/api/workspaces/{s['ws']['slug']}/groups/nosuch-{rid(4)}", {"name": "z"}, s["o"]["token"]), 404, "PATCH unknown handle")
    want(call("DELETE", path, None, x["token"]), 403, "DELETE by another member")
    r = want(call("DELETE", path, None, s["m"]["token"]), 200, "DELETE by creator")
    expect(r.body == {"deleted": True}, f"expected {{'deleted': true}}, got {r.text[:100]}")
    r = want(call("DELETE", path, None, s["m"]["token"]), 200, "DELETE again (idempotent)")
    expect(r.body == {"deleted": True}, f"expected {{'deleted': true}}, got {r.text[:100]}")


@rule("C5.4", "@group expands to group members in the channel; @channel/@username; deduplicated; never the author", 5)
def _():
    s = setup()
    a = add_member(s["ws"], s["o"])
    b = add_member(s["ws"], s["o"])          # b is in the workspace, not in the channel
    want(join(a, s["cid"]), 200, "setup: a joins")
    h = "crew-" + rid(4)
    want(mk_group(s["o"], s["ws"], h, [s["o"]["id"], a["id"], b["id"]]), 201, "create group")
    m = post(s["o"], s["cid"], f"hey @{h} and @{a['username']} again @{h}")
    expect(ids(m.get("mentions")) == ids([a["id"]]),
           f"@{h} should mention only group members in the channel minus the author (just {a['id']}), deduplicated; got {m.get('mentions')}")
    m = post(a, s["cid"], f"@channel and @{a['username']}")
    expect(ids(m.get("mentions")) == ids([s["o"]["id"], s["m"]["id"]]),
           f"@channel from a should be the other channel members {[s['o']['id'], s['m']['id']]}, got {m.get('mentions')}")
    m = post(s["m"], s["cid"], f"ping @{s['m']['username']}")
    expect(m.get("mentions") == [], f"mentioning yourself must not add you: {m.get('mentions')}")
    r = want(call("GET", f"/api/channels/{s['cid']}/read", token=s["m"]["token"]), 200, "read state")
    rs = r.body.get("read_state", r.body) if isinstance(r.body, dict) else {}
    expect(rs.get("mention_count") == 1, f"m was mentioned once by others (@channel) so mention_count should be 1, got {rs}")


@rule("C5.5", "@here mentions channel members with an open WebSocket (any node), and stops after they disconnect", 5)
def _():
    s = setup()
    y = add_member(s["ws"], s["o"])
    want(join(y, s["cid"]), 200, "setup: y joins")
    c = ws_connect(s["m"]["token"], node=2)
    try:
        time.sleep(0.3)
        msg = post(s["o"], s["cid"], "@here standup", node=1)
        expect(ids(msg.get("mentions")) == ids([s["m"]["id"]]),
               f"@here should mention only the member with an open socket ({s['m']['id']}), not the author or y; got {msg.get('mentions')}")
    finally:
        c.close()
    end = time.time() + 3
    while True:
        time.sleep(0.4)
        msg = post(s["o"], s["cid"], "@here again")
        if msg.get("mentions") == [] or time.time() > end:
            break
    expect(msg.get("mentions") == [], f"after the socket closed, @here should mention nobody, got {msg.get('mentions')}")


# ======================================================================= C6 profiles
KEYS = ("id", "username", "display_name", "timezone", "avatar_url", "status_text", "status_emoji")


@rule("C6.1", "GET /api/users/{id} -> 200 {user}; unknown or non-integer -> 404; no token -> 401", 6)
def _():
    u, v = new_user("pa"), new_user("pb")
    r = want(call("GET", f"/api/users/{v['id']}", token=u["token"], node=1), 200, "GET another user")
    for k in KEYS:
        expect(k in r["user"], f"UserObj is missing '{k}': {r.text[:200]}")
    expect(r["user"]["username"] == v["username"], f"wrong user: {r.text[:160]}")
    want(call("GET", f"/api/users/{MISSING}", token=u["token"]), 404, "unknown id")
    want(call("GET", "/api/users/abc", token=u["token"]), 404, "non-integer id")
    want(call("GET", f"/api/users/{v['id']}"), 401, "no token")


@rule("C6.2", "PATCH /api/users/me persists any subset of profile fields (visible on every node)", 6)
def _():
    u = new_user("pp")
    body = {"display_name": "Ada L", "timezone": "America/New_York", "status_text": "in a meeting",
            "status_emoji": "📅", "avatar_url": "https://example.com/a.png", "shoe_size": 9}
    r = want(call("PATCH", "/api/users/me", body, u["token"]), 200, "PATCH /api/users/me")
    for k in ("display_name", "timezone", "status_text", "status_emoji", "avatar_url"):
        expect(r["user"].get(k) == body[k], f"user.{k} should be {body[k]!r}: {r.text[:200]}")
    r = want(call("GET", f"/api/users/{u['id']}", token=u["token"], node=1), 200, "GET user on 8001")
    expect(r["user"].get("timezone") == "America/New_York", f"timezone not persisted: {r.text[:200]}")
    r = want(call("GET", "/api/auth/me", token=u["token"], node=2), 200, "me on 8002")
    expect(r["user"].get("display_name") == "Ada L", f"display_name not persisted: {r.text[:200]}")
    r = want(call("PATCH", "/api/users/me", {"status_text": "back"}, u["token"]), 200, "PATCH one field")
    expect(r["user"].get("status_text") == "back" and r["user"].get("display_name") == "Ada L", f"subset PATCH wrong: {r.text[:200]}")
    want(call("PATCH", "/api/users/me", {}, u["token"]), 200, "PATCH {}")


@rule("C6.3", "profile validation -> 400 and nothing changes", 6)
def _():
    u = new_user("pv")
    want(call("PATCH", "/api/users/me", {"display_name": "Good"}, u["token"]), 200, "valid PATCH")
    bad = [({"display_name": ""}, "empty display_name"), ({"display_name": "x" * 81}, "81-char display_name"),
           ({"status_text": "x" * 101}, "101-char status_text"), ({"status_emoji": "x" * 65}, "65-char status_emoji"),
           ({"avatar_url": "x" * 1025}, "1025-char avatar_url"), ({"timezone": "Mars/Base"}, "timezone Mars/Base"),
           ({"display_name": 123}, "non-string display_name"), ({"display_name": "Changed", "timezone": "Nope/Nope"}, "valid name + bad timezone")]
    for b, what in bad:
        want(call("PATCH", "/api/users/me", b, u["token"]), 400, what)
    r = want(call("GET", "/api/auth/me", token=u["token"]), 200, "me")
    expect(r["user"].get("display_name") == "Good" and r["user"].get("timezone") == "UTC",
           f"a rejected PATCH must change nothing: {r.text[:200]}")
    want(call("PATCH", "/api/users/me", {"timezone": "UTC"}, u["token"]), 200, "timezone UTC")


@rule("C6.4", "PATCH /api/users/me broadcasts {type: user.updated, user} to every socket on every node, no channel_id/event_id", 6)
def _():
    u = new_user("pw")
    obs = new_user("obs")
    c1 = ws_connect(obs["token"], node=1)
    c2 = ws_connect(obs["token"], node=2)
    try:
        time.sleep(0.2)
        want(call("PATCH", "/api/users/me", {"status_text": "broadcast " + rid(4)}, u["token"]), 200, "PATCH")
        for c, n in ((c1, 8001), (c2, 8002)):
            f, seen = ws_recv_until(c, lambda f: f.get("type") == "user.updated" and same((f.get("user") or {}).get("id"), u["id"]), 3)
            expect(f is not None, f"unsubscribed socket on {n} got no user.updated within 3s (saw {kinds(seen)})")
            expect("channel_id" not in f and "event_id" not in f, f"user.updated must not carry channel_id/event_id: {str(f)[:200]}")
    finally:
        c1.close()
        c2.close()


if __name__ == "__main__":
    run()
