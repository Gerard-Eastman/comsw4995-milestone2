"""Component B checks: channels, message history & paging, pins, search, mentions, read state, events.
Usage: python3 channels_checks.py [stage]   (stage 1..5, or nothing for all)"""
import base64, json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import *  # noqa
set_comp("channels")

_c = {}


def ctx():
    """owner, workspace, and a second user 'bob' who is a workspace member."""
    if "ws" not in _c:
        _c["owner"] = new_user("own")
        _c["ws"] = new_workspace(_c["owner"])
        _c["bob"] = add_member(_c["ws"], _c["owner"])
    return _c["owner"], _c["ws"], _c["bob"]


def chan_with_bob(private=False):
    owner, ws, bob = ctx()
    ch = new_channel(ws, owner, private=private)
    if not private:
        want(join(bob, ch["id"]), 200, "bob joins channel")
    return ch


def msgs(user, ch_id, node=0, **params):
    return call("GET", f"/api/channels/{ch_id}/messages", token=user["token"], node=node, params=params or None)


def read_state(user, ch_id):
    r = want(call("GET", f"/api/channels/{ch_id}/read", token=user["token"]), 200, "GET read")
    return r["read_state"]


# ======================================================== B1 channel management
@rule("B1.1", "create channel 201 {channel{id,workspace_id,name,is_private,is_dm,topic:'',is_archived}}", 1)
def _():
    owner, ws, _ = ctx()
    name = "ch-" + rid(8)
    r = want(call("POST", f"/api/workspaces/{ws['slug']}/channels", {"name": name, "description": "ignored"}, owner["token"]), 201, "create")
    ch = r["channel"]
    for k in ("id", "workspace_id", "name", "is_private", "is_dm", "topic", "is_archived"):
        expect(k in ch, f"channel missing '{k}': {ch}")
    expect(ch["name"] == name and ch["is_private"] is False and ch["is_dm"] is False and ch["is_archived"] is False,
           f"wrong values: {ch}")
    expect(ch["topic"] == "", f"topic must default to '' (description must not fill it), got {ch['topic']!r}")
    expect(same(ch["workspace_id"], ws["id"]), "workspace_id wrong")


@rule("B1.2", "create with topic keeps it; topic > 250 chars 400; bad name 400; duplicate name 409", 1)
def _():
    owner, ws, _ = ctx()
    p = f"/api/workspaces/{ws['slug']}/channels"
    r = want(call("POST", p, {"name": "t-" + rid(6), "topic": "hello topic"}, owner["token"]), 201, "create with topic")
    expect(r["channel"].get("topic") == "hello topic", "topic not stored")
    want(call("POST", p, {"name": "t-" + rid(6), "topic": "x" * 251}, owner["token"]), 400, "251-char topic")
    for bad in ("Bad Name", "UPPER", "a" * 33, ""):
        want(call("POST", p, {"name": bad}, owner["token"]), 400, f"name {bad!r}")
    name = "d-" + rid(6)
    want(call("POST", p, {"name": name}, owner["token"]), 201, "create")
    want(call("POST", p, {"name": name}, owner["token"]), 409, "duplicate name")


@rule("B1.3", "GET /api/workspaces/{slug} 200 {workspace, channels, read_state}; hides others' private channels", 1)
def _():
    owner, ws, bob = ctx()
    pub = new_channel(ws, owner)
    priv = new_channel(ws, owner, private=True)
    r = want(call("GET", f"/api/workspaces/{ws['slug']}", token=bob["token"], node=1), 200, "workspace detail")
    expect("workspace" in r.body and "read_state" in r.body, f"missing workspace/read_state keys: {list(r.body)}")
    ids = {str(c.get("id")) for c in r["channels"]}
    expect(str(pub["id"]) in ids, "public channel missing from detail")
    expect(str(priv["id"]) not in ids, "a private channel bob is not in is listed for bob")
    r = want(call("GET", f"/api/workspaces/{ws['slug']}", token=owner["token"]), 200, "detail (owner)")
    expect(str(priv["id"]) in {str(c.get("id")) for c in r["channels"]}, "private channel missing for its member")


@rule("B1.4", "PATCH /api/channels/{id} {topic}: member 200 {channel}; non-member non-owner 403; 251 chars 400", 1)
def _():
    owner, ws, bob = ctx()
    ch = chan_with_bob()
    r = want(call("PATCH", f"/api/channels/{ch['id']}", {"topic": "new topic"}, bob["token"]), 200, "member sets topic")
    expect(r["channel"].get("topic") == "new topic", "topic not updated")
    out = add_member(ws, owner)
    want(call("PATCH", f"/api/channels/{ch['id']}", {"topic": "nope"}, out["token"]), 403, "non-member sets topic")
    want(call("PATCH", f"/api/channels/{ch['id']}", {"topic": "y" * 251}, bob["token"]), 400, "251-char topic")


@rule("B1.5", "leave 200 {channel}, twice is still 200; members list 200 {members:[UserObj]}", 1)
def _():
    owner, ws, bob = ctx()
    ch = chan_with_bob()
    r = want(call("GET", f"/api/channels/{ch['id']}/members", token=owner["token"]), 200, "members")
    us = r["members"]
    expect(any(same(u.get("id"), bob["id"]) for u in us), "bob missing from channel members")
    missing = [k for k in ("id", "username", "display_name", "timezone", "avatar_url", "status_text", "status_emoji") if k not in us[0]]
    expect(not missing, f"member UserObj missing {missing}")
    r = want(call("POST", f"/api/channels/{ch['id']}/leave", None, bob["token"]), 200, "leave")
    expect("channel" in r.body, "leave must return {channel}")
    want(call("POST", f"/api/channels/{ch['id']}/leave", None, bob["token"]), 200, "leave again")
    r = want(call("GET", f"/api/channels/{ch['id']}/members", token=owner["token"]), 200, "members")
    expect(not any(same(u.get("id"), bob["id"]) for u in r["members"]), "bob still listed after leaving")


@rule("B1.6", "archive/unarchive: owner-only (admin 403); archived -> post 423; unarchive restores posting", 1)
def _():
    owner, ws, bob = ctx()
    ch = chan_with_bob()
    adm = add_member(ws, owner, "admin")
    want(call("POST", f"/api/channels/{ch['id']}/archive", None, adm["token"]), 403, "admin archives")
    r = want(call("POST", f"/api/channels/{ch['id']}/archive", None, owner["token"]), 200, "owner archives")
    expect(r["channel"].get("is_archived") is True, "is_archived not true")
    want(call("POST", f"/api/channels/{ch['id']}/messages", {"body": "hi"}, bob["token"], node=2), 423, "post to archived")
    r = want(call("POST", f"/api/channels/{ch['id']}/unarchive", None, owner["token"]), 200, "unarchive")
    expect(r["channel"].get("is_archived") is False, "is_archived not false after unarchive")
    want(call("POST", f"/api/channels/{ch['id']}/messages", {"body": "hi"}, bob["token"]), 201, "post after unarchive")


@rule("B1.7", "archived channels hidden from workspace detail unless ?include_archived=1 (or true)", 1)
def _():
    owner, ws, _ = ctx()
    ch = new_channel(ws, owner)
    want(call("POST", f"/api/channels/{ch['id']}/archive", None, owner["token"]), 200, "archive")
    p = f"/api/workspaces/{ws['slug']}"
    ids = lambda r: {str(c.get("id")) for c in r["channels"]}
    expect(str(ch["id"]) not in ids(want(call("GET", p, token=owner["token"]), 200, "detail")), "archived channel listed by default")
    expect(str(ch["id"]) in ids(want(call("GET", p, token=owner["token"], params={"include_archived": "1"}), 200, "detail")), "missing with include_archived=1")
    expect(str(ch["id"]) in ids(want(call("GET", p, token=owner["token"], params={"include_archived": "true"}), 200, "detail")), "missing with include_archived=true")


@rule("B1.8", "workspace owner who is not a channel member may PATCH its topic -> 200", 1)
def _():
    owner, ws, bob = ctx()
    ch = new_channel(ws, bob)   # bob creates it; the owner never joins
    r = want(call("PATCH", f"/api/channels/{ch['id']}", {"topic": "set by owner"}, owner["token"], node=1), 200,
             "owner (not a member) sets topic")
    expect(r["channel"].get("topic") == "set by owner", "topic not updated")


# ======================================================== B2 messages & paging
@rule("B2.1", "post 201 {message} with all MessageObj keys; created_at is ISO-8601 UTC; empty body 400", 2)
def _():
    owner, ws, bob = ctx()
    ch = chan_with_bob()
    r = want(call("POST", f"/api/channels/{ch['id']}/messages", {"body": "hello world"}, bob["token"]), 201, "post")
    m = r["message"]
    keys = ("id", "channel_id", "author_id", "author", "body", "parent_id", "reply_count", "created_at",
            "edited_at", "files", "reactions", "mentions")
    missing = [k for k in keys if k not in m]
    expect(not missing, f"message missing {missing}")
    expect(m["body"] == "hello world" and same(m["author_id"], bob["id"]) and same(m["channel_id"], ch["id"]), f"wrong values {m}")
    expect(m["parent_id"] is None and m["reply_count"] == 0 and m["edited_at"] is None, "new message: parent_id/edited_at null, reply_count 0")
    expect(m["files"] == [] and m["reactions"] == [] and m["mentions"] == [], "files/reactions/mentions must be []")
    expect(isinstance(m["author"], dict) and same(m["author"].get("id"), bob["id"]), "author must be bob's UserObj")
    ts = str(m["created_at"])
    expect("T" in ts and (ts.endswith("Z") or ts.endswith("+00:00")), f"created_at not ISO UTC: {ts}")
    for empty in ("", "   "):
        want(call("POST", f"/api/channels/{ch['id']}/messages", {"body": empty}, bob["token"]), 400, f"body {empty!r}")
    want(call("POST", f"/api/channels/{ch['id']}/messages", {"body": "x"}), 401, "post without token")
    want(call("POST", "/api/channels/99999999/messages", {"body": "x"}, bob["token"]), 404, "post to unknown channel")


@rule("B2.2", "private channel: non-member post/read -> 403", 2)
def _():
    owner, ws, bob = ctx()
    priv = new_channel(ws, owner, private=True)
    want(call("POST", f"/api/channels/{priv['id']}/messages", {"body": "x"}, bob["token"]), 403, "non-member posts")
    want(msgs(bob, priv["id"]), 403, "non-member reads")


@rule("B2.3", "GET messages 200 {messages, next_cursor} newest-first; limit pages through all, last page next_cursor null", 2)
def _():
    owner, ws, bob = ctx()
    ch = chan_with_bob()
    ids = [post(bob, ch["id"], f"m{i}", node=i % 3)["id"] for i in range(5)]
    seen, cur, pages = [], None, 0
    while True:
        params = {"limit": 2}
        if cur:
            params["cursor"] = cur
        r = want(msgs(owner, ch["id"], node=pages % 3, **params), 200, f"page {pages + 1}")
        expect("next_cursor" in r.body, "envelope has no next_cursor key")
        seen += [m["id"] for m in r["messages"]]
        cur, pages = r["next_cursor"], pages + 1
        if cur is None or pages > 5:
            break
        expect(isinstance(cur, str), "next_cursor must be a string or null")
    expect([str(x) for x in seen] == [str(x) for x in reversed(ids)],
           f"paging limit=2 gave {seen}, want newest-first {list(reversed(ids))} with no gaps/dupes")
    expect(pages == 3, f"5 messages at limit=2 should take 3 pages, took {pages}")


@rule("B2.4", "cursor from one node works on another and is not shifted by new messages", 2)
def _():
    owner, ws, bob = ctx()
    ch = chan_with_bob()
    ids = [post(bob, ch["id"], f"c{i}")["id"] for i in range(4)]
    r = want(msgs(bob, ch["id"], node=0, limit=2), 200, "page 1")
    cur = r["next_cursor"]
    expect(isinstance(cur, str), "expected a next_cursor string after page 1")
    post(bob, ch["id"], "newer message")
    r = want(msgs(bob, ch["id"], node=2, limit=2, cursor=cur), 200, "page 2 on node 2")
    got = [str(m["id"]) for m in r["messages"]]
    expect(got == [str(ids[1]), str(ids[0])], f"page 2 after a new post gave {got}, want {[str(ids[1]), str(ids[0])]}")


@rule("B2.5", "bad cursor 400; limit 0, 201, 'abc' -> 400; limit 200 ok; default limit is 50", 2)
def _():
    owner, ws, bob = ctx()
    ch = chan_with_bob()
    want(msgs(bob, ch["id"], cursor="garbage!!"), 400, "malformed cursor")
    want(msgs(bob, ch["id"], cursor=base64.urlsafe_b64encode(b'{"zz":1}').decode()), 400, "unrecognized cursor")
    for bad in ("0", "201", "abc", "-1"):
        want(msgs(bob, ch["id"], limit=bad), 400, f"limit={bad}")
    want(msgs(bob, ch["id"], limit=200), 200, "limit=200")
    for i in range(51):
        call("POST", f"/api/channels/{ch['id']}/messages", {"body": f"n{i}"}, bob["token"], i % 3)
    r = want(msgs(bob, ch["id"]), 200, "default page")
    expect(len(r["messages"]) == 50 and isinstance(r["next_cursor"], str),
           f"default page should have 50 messages and a next_cursor, got {len(r['messages'])} and {r['next_cursor']!r}")


@rule("B2.6", "replies: parent_id makes a reply; parent reply_count rises; GET replies oldest-first; replies not in channel list", 2)
def _():
    owner, ws, bob = ctx()
    ch = chan_with_bob()
    parent = post(owner, ch["id"], "parent")
    r1 = post(bob, ch["id"], "reply one", parent_id=parent["id"])
    r2 = post(owner, ch["id"], "reply two", parent_id=parent["id"], node=1)
    expect(same(r1.get("parent_id"), parent["id"]), "reply has wrong parent_id")
    r = want(call("GET", f"/api/messages/{parent['id']}/replies", token=bob["token"], node=2), 200, "replies")
    expect([str(m["id"]) for m in r["replies"]] == [str(r1["id"]), str(r2["id"])], "replies not oldest-first")
    expect("next_cursor" in r.body, "replies envelope has no next_cursor")
    lst = want(msgs(bob, ch["id"]), 200, "list")["messages"]
    top = [m for m in lst if same(m["id"], parent["id"])]
    expect(top and top[0].get("reply_count") == 2, f"parent reply_count should be 2, got {top[0].get('reply_count') if top else 'missing'}")
    expect(not any(same(m["id"], r1["id"]) for m in lst), "thread replies must not appear in the channel message list")
    want(call("GET", "/api/messages/99999999/replies", token=bob["token"]), 404, "replies of unknown message")


@rule("B2.7", "replies paging: 5 replies at limit=2 -> 2,2,1 oldest-first across nodes; bad cursor/limit 400", 2)
def _():
    owner, ws, bob = ctx()
    ch = chan_with_bob()
    parent = post(owner, ch["id"], "paged parent")
    ids = [post(bob, ch["id"], f"pr{i}", node=i % 3, parent_id=parent["id"])["id"] for i in range(5)]
    seen, cur, pages = [], None, 0
    while pages < 6:
        params = {"limit": 2}
        if cur:
            params["cursor"] = cur
        r = want(call("GET", f"/api/messages/{parent['id']}/replies", token=bob["token"], params=params, node=pages % 3),
                 200, f"replies page {pages + 1}")
        seen += [x["id"] for x in r["replies"]]
        cur, pages = r["next_cursor"], pages + 1
        if cur is None:
            break
    expect([str(x) for x in seen] == [str(x) for x in ids] and pages == 3,
           f"limit=2 paging gave {seen} in {pages} pages, want {ids} in 3 pages (oldest-first)")
    want(call("GET", f"/api/messages/{parent['id']}/replies", token=bob["token"], params={"cursor": "garbage!!"}), 400, "malformed cursor")
    for bad in ("0", "201"):
        want(call("GET", f"/api/messages/{parent['id']}/replies", token=bob["token"], params={"limit": bad}), 400, f"limit={bad}")


# ======================================================== B3 pins & search
@rule("B3.1", "pin 200 {pin{message_id,pinned_by,pinned_at}}, idempotent; list {pins:[{message,pinned_by,pinned_at}], next_cursor} newest-first", 3)
def _():
    owner, ws, bob = ctx()
    ch = chan_with_bob()
    a, b = post(bob, ch["id"], "pin a"), post(bob, ch["id"], "pin b")
    r = want(call("POST", f"/api/messages/{a['id']}/pin", None, bob["token"]), 200, "pin a")
    p = r["pin"]
    expect(same(p.get("message_id"), a["id"]) and same(p.get("pinned_by"), bob["id"]) and p.get("pinned_at"), f"bad pin {p}")
    want(call("POST", f"/api/messages/{a['id']}/pin", None, bob["token"]), 200, "pin a again")
    time.sleep(0.01)
    want(call("POST", f"/api/messages/{b['id']}/pin", None, owner["token"], node=1), 200, "pin b")
    r = want(call("GET", f"/api/channels/{ch['id']}/pins", token=bob["token"], node=2), 200, "pins list")
    got = [str(x.get("message", {}).get("id")) for x in r["pins"]]
    expect(got == [str(b["id"]), str(a["id"])], f"pins should be [b, a] newest-first with no duplicates, got {got}")
    expect("next_cursor" in r.body and same(r["pins"][0].get("pinned_by"), owner["id"]), "pins envelope/pinned_by wrong")


@rule("B3.2", "unpin 200 {unpinned:true}; private-channel pins list for non-member 403", 3)
def _():
    owner, ws, bob = ctx()
    ch = chan_with_bob()
    a = post(bob, ch["id"], "to unpin")
    want(call("POST", f"/api/messages/{a['id']}/pin", None, bob["token"]), 200, "pin")
    r = want(call("DELETE", f"/api/messages/{a['id']}/pin", token=bob["token"]), 200, "unpin")
    expect(r.body == {"unpinned": True}, f"expected {{'unpinned': true}}, got {r.text[:80]}")
    r = want(call("GET", f"/api/channels/{ch['id']}/pins", token=bob["token"]), 200, "pins")
    expect(r["pins"] == [], "pin still listed after unpin")
    priv = new_channel(ws, owner, private=True)
    want(call("GET", f"/api/channels/{priv['id']}/pins", token=bob["token"]), 403, "non-member pins list")


@rule("B3.3", "search 200 {results, next_cursor} newest-first; excludes private channels the caller is not in", 3)
def _():
    owner, ws, bob = ctx()
    word = "zq" + rid(8)
    ch = chan_with_bob()
    priv = new_channel(ws, owner, private=True)
    m1 = post(bob, ch["id"], f"first {word}")
    m2 = post(owner, ch["id"], f"second {word.upper()} here")
    post(owner, priv["id"], f"secret {word}")
    r = want(call("GET", "/api/search", token=bob["token"], params={"q": word}, node=1), 200, "search")
    got = [str(m.get("id")) for m in r["results"]]
    expect(got == [str(m2["id"]), str(m1["id"])], f"search for bob should give [m2, m1] (newest-first, case-insensitive, no private), got {got}")
    expect("next_cursor" in r.body, "search envelope has no next_cursor")
    r = want(call("GET", "/api/search", token=owner["token"], params={"q": word}), 200, "search (owner)")
    expect(len(r["results"]) == 3, f"owner should find 3 results incl. private channel, got {len(r['results'])}")


@rule("B3.4", "search workspace_id filter and paging with limit/cursor", 3)
def _():
    owner, ws, bob = ctx()
    word = "wq" + rid(8)
    ws2 = new_workspace(owner)
    ch = new_channel(ws, owner)
    post(owner, ch["id"], f"{word} one")
    post(owner, ch["id"], f"{word} two")
    post(owner, ws2["general"]["id"], f"{word} other ws")
    r = want(call("GET", "/api/search", token=owner["token"], params={"q": word, "workspace_id": ws["id"]}), 200, "search filtered")
    expect(len(r["results"]) == 2, f"workspace_id filter should give 2 results, got {len(r['results'])}")
    r = want(call("GET", "/api/search", token=owner["token"], params={"q": word, "limit": 2}), 200, "search page 1")
    expect(len(r["results"]) == 2 and isinstance(r["next_cursor"], str), "limit=2 of 3 results should give 2 and a cursor")
    r = want(call("GET", "/api/search", token=owner["token"], params={"q": word, "limit": 2, "cursor": r["next_cursor"]}, node=2), 200, "search page 2")
    expect(len(r["results"]) == 1 and r["next_cursor"] is None, "page 2 should have 1 result and next_cursor null")


@rule("B3.5", "pins paging: 3 pins at limit=2 -> 2 newest, then 1 with next_cursor null; bad cursor/limit 400", 3)
def _():
    owner, ws, bob = ctx()
    ch = chan_with_bob()
    ms = [post(bob, ch["id"], f"pp{i}") for i in range(3)]
    for m in ms:
        want(call("POST", f"/api/messages/{m['id']}/pin", None, bob["token"]), 200, "pin")
    r = want(call("GET", f"/api/channels/{ch['id']}/pins", token=bob["token"], params={"limit": 2}), 200, "pins page 1")
    p1 = [str(x.get("message", {}).get("id")) for x in r["pins"]]
    expect(isinstance(r["next_cursor"], str), f"page 1 of 3 pins at limit=2 needs a next_cursor, got {r['next_cursor']!r}")
    r2 = want(call("GET", f"/api/channels/{ch['id']}/pins", token=bob["token"], params={"limit": 2, "cursor": r["next_cursor"]}, node=2),
              200, "pins page 2")
    p2 = [str(x.get("message", {}).get("id")) for x in r2["pins"]]
    want_ids = [str(m["id"]) for m in reversed(ms)]
    expect(p1 + p2 == want_ids and r2["next_cursor"] is None,
           f"pages {p1} then {p2} (next_cursor {r2['next_cursor']!r}), want {want_ids[:2]} then {want_ids[2:]} then null")
    want(call("GET", f"/api/channels/{ch['id']}/pins", token=bob["token"], params={"cursor": "garbage!!"}), 400, "malformed cursor")
    want(call("GET", f"/api/channels/{ch['id']}/pins", token=bob["token"], params={"limit": "201"}), 400, "limit=201")


@rule("B3.6", "search validation: bad cursor 400; limit 0/abc 400; missing or empty q 400", 3)
def _():
    owner, ws, bob = ctx()
    want(call("GET", "/api/search", token=bob["token"], params={"q": "x", "cursor": "garbage!!"}), 400, "malformed cursor")
    for bad in ("0", "abc"):
        want(call("GET", "/api/search", token=bob["token"], params={"q": "x", "limit": bad}), 400, f"limit={bad}")
    want(call("GET", "/api/search", token=bob["token"]), 400, "missing q")
    want(call("GET", "/api/search", token=bob["token"], params={"q": ""}), 400, "empty q")


# ======================================================== B4 mentions & read state
@rule("B4.1", "mentions: @username resolves; dedup; no self; no email/in-word; non-workspace user excluded", 4)
def _():
    owner, ws, bob = ctx()
    ch = chan_with_bob()
    outsider = new_user("out")
    m = post(owner, ch["id"], f"hi @{bob['username']} and @{bob['username']}, me @{owner['username']}")
    expect([str(x) for x in m["mentions"]] == [str(bob["id"])], f"want mentions [bob], got {m['mentions']}")
    m = post(owner, ch["id"], f"mail x@{bob['username']} and {bob['username']}@example.com")
    expect(m["mentions"] == [], f"email/in-word must not mention, got {m['mentions']}")
    m = post(owner, ch["id"], f"hey @{outsider['username']}")
    expect(m["mentions"] == [], f"non-workspace user must be excluded, got {m['mentions']}")


@rule("B4.2", "@channel expands to every channel member except the author", 4)
def _():
    owner, ws, bob = ctx()
    ch = chan_with_bob()
    carl = add_member(ws, owner)
    want(join(carl, ch["id"]), 200, "carl joins")
    m = post(bob, ch["id"], "attention @channel please")
    expect(sorted(str(x) for x in m["mentions"]) == sorted([str(owner["id"]), str(carl["id"])]),
           f"@channel by bob should mention owner+carl, got {m['mentions']}")


@rule("B4.3", "GET /api/channels/{id}/read 200 {read_state{channel_id,last_read_event_id,unread_count,mention_count}}", 4)
def _():
    owner, ws, bob = ctx()
    ch = chan_with_bob()
    rs = read_state(bob, ch["id"])
    for k in ("channel_id", "last_read_event_id", "unread_count", "mention_count"):
        expect(k in rs, f"read_state missing '{k}': {rs}")
    expect(same(rs["channel_id"], ch["id"]) and rs["unread_count"] == 0 and rs["mention_count"] == 0, f"fresh read_state should be 0/0: {rs}")


@rule("B4.4", "others' messages raise unread_count; mentions raise mention_count; own messages and self-mentions do not", 4)
def _():
    owner, ws, bob = ctx()
    ch = chan_with_bob()
    post(owner, ch["id"], "one")
    post(owner, ch["id"], f"two @{bob['username']}", node=1)
    post(owner, ch["id"], "three @channel", node=2)
    post(bob, ch["id"], f"my own @{bob['username']}")
    rs = read_state(bob, ch["id"])
    expect(rs["unread_count"] == 3 and rs["mention_count"] == 2, f"bob should have unread 3, mentions 2; got {rs}")
    rs = read_state(owner, ch["id"])
    expect(rs["mention_count"] == 0, f"owner mentioned nobody -> mention_count 0, got {rs}")


@rule("B4.5", "POST read {last_read_event_id} clears counts, never moves backwards; workspace detail embeds read_state", 4)
def _():
    owner, ws, bob = ctx()
    ch = chan_with_bob()
    c = ws_connect(bob["token"])
    try:
        post(owner, ch["id"], f"ping @{bob['username']}")
        head = ws_subscribe(c, ch["id"])
    finally:
        c.close()
    r = want(call("POST", f"/api/channels/{ch['id']}/read", {"last_read_event_id": head}, bob["token"], node=1), 200, "mark read")
    rs = r["read_state"]
    expect(rs["last_read_event_id"] == head and rs["unread_count"] == 0 and rs["mention_count"] == 0, f"after marking read at head {head}: {rs}")
    r = want(call("POST", f"/api/channels/{ch['id']}/read", {"last_read_event_id": 1}, bob["token"]), 200, "mark read backwards")
    expect(r["read_state"]["last_read_event_id"] == head, f"cursor moved backwards to {r['read_state']['last_read_event_id']}")
    post(owner, ch["id"], "after read")
    expect(read_state(bob, ch["id"])["unread_count"] == 1, "one new message should give unread_count 1")
    d = want(call("GET", f"/api/workspaces/{ws['slug']}", token=bob["token"]), 200, "workspace detail")
    rsl = d["read_state"]
    entries = rsl if isinstance(rsl, list) else list(rsl.values()) if isinstance(rsl, dict) else []
    e = [x for x in entries if isinstance(x, dict) and same(x.get("channel_id"), ch["id"])]
    expect(e and e[0].get("unread_count") == 1, f"workspace detail read_state has no entry for the channel with unread_count 1: {str(rsl)[:200]}")


@rule("B4.6", "mentions dedup across forms: '@bob ... @channel' lists bob once, never the author", 4)
def _():
    owner, ws, bob = ctx()
    ch = chan_with_bob()
    m = post(owner, ch["id"], f"hi @{bob['username']} and also @channel")
    ids = [str(x) for x in m["mentions"]]
    expect(ids.count(str(bob["id"])) == 1 and str(owner["id"]) not in ids, f"mentions {m['mentions']}: want bob exactly once, no author")


# ======================================================== B5 WebSocket events
def kinds(frames):
    return [f.get("type") for f in frames]


@rule("B5.1", "subscribe -> {type:'subscribed', channel_id, head_event_id}; a post on another node arrives as message.created", 5)
def _():
    owner, ws, bob = ctx()
    ch = chan_with_bob()
    c = ws_connect(bob["token"], node=0)
    try:
        head = ws_subscribe(c, ch["id"])
        m = post(owner, ch["id"], "over the wire", node=2)
        f, seen = ws_recv_until(c, lambda f: f.get("type") == "message.created")
        expect(f is not None, f"no message.created within 3s on node 0 for a post on node 2 (saw {kinds(seen)})")
        expect(f.get("event_id") == head + 1 and same(f.get("channel_id"), ch["id"]), f"want event_id {head + 1}, got {f.get('event_id')}")
        expect(isinstance(f.get("message"), dict) and same(f["message"].get("id"), m["id"]), "frame must carry the message object")
    finally:
        c.close()


@rule("B5.2", "event_id is dense across nodes: 6 posts on alternating nodes -> head+1..head+6, no gaps or dupes", 5)
def _():
    owner, ws, bob = ctx()
    ch = chan_with_bob()
    c = ws_connect(bob["token"], node=1)
    try:
        head = ws_subscribe(c, ch["id"])
        for i in range(6):
            post(owner if i % 2 else bob, ch["id"], f"d{i}", node=i % 3)
        got, end = [], time.time() + 4
        while len(got) < 6 and time.time() < end:
            f, _ = ws_recv_until(c, lambda f: "event_id" in f, timeout=end - time.time())
            if f is None:
                break
            got.append(f["event_id"])
        expect(got == list(range(head + 1, head + 7)), f"event_ids {got}, want {list(range(head + 1, head + 7))}")
    finally:
        c.close()


@rule("B5.3", "event kinds: message.reply, member.joined, member.left, channel.updated, channel.archived, channel.unarchived", 5)
def _():
    owner, ws, bob = ctx()
    ch = new_channel(ws, owner)
    carl = add_member(ws, owner)
    c = ws_connect(owner["token"], node=2)
    try:
        ws_subscribe(c, ch["id"])
        parent = post(owner, ch["id"], "parent")
        post(owner, ch["id"], "a reply", parent_id=parent["id"], node=1)
        want(join(carl, ch["id"]), 200, "carl joins")
        want(call("PATCH", f"/api/channels/{ch['id']}", {"topic": "t1"}, owner["token"]), 200, "topic")
        want(call("POST", f"/api/channels/{ch['id']}/leave", None, carl["token"]), 200, "carl leaves")
        want(call("POST", f"/api/channels/{ch['id']}/archive", None, owner["token"]), 200, "archive")
        want(call("POST", f"/api/channels/{ch['id']}/unarchive", None, owner["token"]), 200, "unarchive")
        want_k = ["message.created", "message.reply", "member.joined", "channel.updated", "member.left",
                  "channel.archived", "channel.unarchived"]
        _, seen = ws_recv_until(c, lambda f: f.get("type") == "channel.unarchived", timeout=4)
        got = [f for f in seen if "event_id" in f]
        expect(kinds(got) == want_k, f"durable frames {kinds(got)}, want {want_k}")
        ev = [f["event_id"] for f in got]
        expect(ev == list(range(ev[0], ev[0] + len(ev))), f"event_ids not dense: {ev}")
    finally:
        c.close()


@rule("B5.4", "resume on a different node replays events after since_event_id in order, then {type:'resumed', head_event_id}", 5)
def _():
    owner, ws, bob = ctx()
    ch = chan_with_bob()
    c = ws_connect(bob["token"], node=0)
    try:
        head = ws_subscribe(c, ch["id"])
    finally:
        c.close()
    for i in range(3):
        post(owner, ch["id"], f"missed {i}", node=i % 3)
    c = ws_connect(bob["token"], node=2)
    try:
        c.send(json.dumps({"type": "resume", "channel_id": ch["id"], "since_event_id": head}))
        f, seen = ws_recv_until(c, lambda f: f.get("type") == "resumed")
        expect(f is not None, f"no 'resumed' frame within 3s (saw {kinds(seen)})")
        replay = [x["event_id"] for x in seen if x.get("type") == "message.created"]
        expect(replay == [head + 1, head + 2, head + 3], f"replayed event_ids {replay}, want {[head + 1, head + 2, head + 3]}")
        expect(f.get("head_event_id") == head + 3 and same(f.get("channel_id"), ch["id"]), f"resumed frame wrong: {f}")
        post(owner, ch["id"], "live after resume", node=1)
        g, _ = ws_recv_until(c, lambda f: f.get("type") == "message.created")
        expect(g is not None and g.get("event_id") == head + 4, "after resume, live events must keep flowing")
    finally:
        c.close()


@rule("B5.5", "edit/delete/reactions emit message.updated, reaction.added, reaction.removed, message.deleted", 5)
def _():
    owner, ws, bob = ctx()
    ch = chan_with_bob()
    m = post(bob, ch["id"], "edit me")
    c = ws_connect(owner["token"], node=1)
    try:
        ws_subscribe(c, ch["id"])
        r = want(call("PATCH", f"/api/messages/{m['id']}", {"body": "edited"}, bob["token"], node=2), 200, "edit")
        expect(r["message"].get("edited_at"), "edited_at not set")
        want(call("POST", f"/api/messages/{m['id']}/reactions", {"emoji": "thumbsup"}, owner["token"]), 200, "react")
        want(call("DELETE", f"/api/messages/{m['id']}/reactions/thumbsup", token=owner["token"]), 200, "unreact")
        want(call("DELETE", f"/api/messages/{m['id']}", token=bob["token"]), 200, "delete")
        want_k = ["message.updated", "reaction.added", "reaction.removed", "message.deleted"]
        _, seen = ws_recv_until(c, lambda f: f.get("type") == "message.deleted", timeout=4)
        got = [f.get("type") for f in seen if "event_id" in f]
        expect(got == want_k, f"durable frames {got}, want {want_k}")
    finally:
        c.close()


@rule("B5.6", "archived channel is read-only: post, edit, topic, pin, react -> 423; reads 200; unarchive restores", 5)
def _():
    owner, ws, bob = ctx()
    ch = chan_with_bob()
    m = post(bob, ch["id"], "written before archive")
    want(call("POST", f"/api/channels/{ch['id']}/archive", None, owner["token"]), 200, "archive")
    writes = {
        "post": lambda: call("POST", f"/api/channels/{ch['id']}/messages", {"body": "x"}, bob["token"], 1).status,
        "edit": lambda: call("PATCH", f"/api/messages/{m['id']}", {"body": "edited"}, bob["token"], 2).status,
        "topic": lambda: call("PATCH", f"/api/channels/{ch['id']}", {"topic": "t"}, bob["token"]).status,
        "pin": lambda: call("POST", f"/api/messages/{m['id']}/pin", None, bob["token"]).status,
        "react": lambda: call("POST", f"/api/messages/{m['id']}/reactions", {"emoji": "x"}, bob["token"]).status,
    }
    got = {k: f() for k, f in writes.items()}
    expect(all(v == 423 for v in got.values()), f"while archived: {got} (want 423 for each)")
    reads = {"messages": msgs(bob, ch["id"]).status, "pins": call("GET", f"/api/channels/{ch['id']}/pins", token=bob["token"]).status}
    expect(all(v == 200 for v in reads.values()), f"reads while archived: {reads} (want 200)")
    want(call("POST", f"/api/channels/{ch['id']}/unarchive", None, owner["token"]), 200, "unarchive")
    got = {k: f() for k, f in writes.items()}
    expect(all(v == 200 or v == 201 for v in got.values()), f"after unarchive: {got} (want 200/201 for each)")


@rule("B5.7", "non-member subscribe/resume on a private channel -> error frame and no events", 5)
def _():
    owner, ws, bob = ctx()
    priv = new_channel(ws, owner, private=True)
    for kind in ("subscribe", "resume"):
        c = ws_connect(bob["token"], node=1)
        try:
            frame = {"type": kind, "channel_id": priv["id"]}
            if kind == "resume":
                frame["since_event_id"] = 0
            c.send(json.dumps(frame))
            f, seen = ws_recv_until(c, lambda f: f.get("type") in ("error", "subscribed", "resumed"), timeout=2)
            expect(f is not None and f.get("type") == "error",
                   f"{kind} on a private channel by a non-member: want an error frame, got {[x.get('type') for x in seen]}")
            post(owner, priv["id"], f"secret after {kind}")
            leak, seen = ws_recv_until(c, lambda f: "event_id" in f, timeout=1.0)
            if leak is not None:
                raise CheckFail(f"non-member received {leak.get('type')} event {leak.get('event_id')} after {kind}")
        finally:
            c.close()


def _post_bg(token, ch_id, body, node, out, i):
    import requests
    try:
        out[i] = requests.post(f"{NODES[node]}/api/channels/{ch_id}/messages", json={"body": body},
                               headers={"Authorization": f"Bearer {token}"}, timeout=10).status_code
    except Exception as e:
        out[i] = type(e).__name__


@rule("B5.8", "30 concurrent posts over 3 nodes: all 201; subscriber sees exactly head+1..head+30 in order", 5)
def _():
    import threading
    owner, ws, bob = ctx()
    ch = chan_with_bob()
    c = ws_connect(owner["token"], node=0)
    try:
        head = ws_subscribe(c, ch["id"])
        out = [None] * 30
        ts = [threading.Thread(target=_post_bg, args=(bob["token"] if i % 2 else owner["token"], ch["id"], f"cc{i}", i % 3, out, i))
              for i in range(30)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        expect(all(s == 201 for s in out), f"concurrent post statuses: {sorted(set(map(str, out)))} (want all 201)")
        got, end = [], time.time() + 6
        while len(got) < 30 and time.time() < end:
            f, _ = ws_recv_until(c, lambda f: f.get("type") == "message.created", timeout=end - time.time())
            if f is None:
                break
            got.append(f.get("event_id"))
        want_ids = list(range(head + 1, head + 31))
        expect(got == want_ids, f"got {len(got)} events; first/last {got[:3]}..{got[-3:]}; duplicates {len(got) - len(set(got))}; "
                                f"want exactly {head + 1}..{head + 30} in order")
    finally:
        c.close()


@rule("B5.9", "every Component B route: no token or bad token -> 401", 5)
def _():
    owner, ws, bob = ctx()
    ch = chan_with_bob()
    m = post(bob, ch["id"], "auth target")
    c_, i_ = ch["id"], m["id"]
    routes = [("GET", f"/api/workspaces/{ws['slug']}"), ("PATCH", f"/api/channels/{c_}"), ("POST", f"/api/channels/{c_}/leave"),
              ("GET", f"/api/channels/{c_}/members"), ("POST", f"/api/channels/{c_}/archive"), ("POST", f"/api/channels/{c_}/unarchive"),
              ("POST", f"/api/channels/{c_}/messages"), ("GET", f"/api/channels/{c_}/messages"), ("GET", f"/api/messages/{i_}/replies"),
              ("PATCH", f"/api/messages/{i_}"), ("DELETE", f"/api/messages/{i_}"), ("POST", f"/api/messages/{i_}/reactions"),
              ("DELETE", f"/api/messages/{i_}/reactions/x"), ("POST", f"/api/messages/{i_}/pin"), ("DELETE", f"/api/messages/{i_}/pin"),
              ("GET", f"/api/channels/{c_}/pins"), ("GET", "/api/search?q=x"), ("GET", f"/api/channels/{c_}/read"),
              ("POST", f"/api/channels/{c_}/read")]
    bad = []
    for meth, path in routes:
        for tok in (None, "garbage-token-123456789"):
            r = call(meth, path, {"body": "x", "topic": "x", "emoji": "x", "last_read_event_id": 0} if meth in ("POST", "PATCH") else None, tok)
            if r.status != 401:
                bad.append(f"{meth} {path.split('?')[0]} ({'no' if tok is None else 'bad'} token) -> {r.status}")
    expect(not bad, f"{len(bad)} route(s) not 401: " + "; ".join(bad[:5]))


if __name__ == "__main__":
    run()
