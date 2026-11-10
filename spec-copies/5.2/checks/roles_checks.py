"""Component A checks: auth, workspaces, roles, invitations, join mode. Rules are in the roles spec.
Usage: python3 roles_checks.py [stage]   (stage 1..4, or nothing for all)"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import *  # noqa
set_comp("roles")

_cache = {}


def ctx():
    """Shared fixture: owner + workspace (created once per check run)."""
    if "ws" not in _cache:
        owner = new_user("own")
        _cache["owner"] = owner
        _cache["ws"] = new_workspace(owner)
    return _cache["owner"], _cache["ws"]


def members(ws, token):
    r = want(call("GET", f"/api/workspaces/{ws['slug']}/members", token=token), 200, "GET members")
    return {str(m.get("user_id")): m.get("role") for m in r["members"]}


def set_role(ws, actor, target, role):
    return call("PATCH", f"/api/workspaces/{ws['slug']}/members/{target['id']}", {"role": role}, actor["token"])


# ======================================================== A1 auth
@rule("A1.1", "register returns 201 {user, token}; token >= 16 chars; user has id and username", 1)
def _():
    name = f"reg{rid(8)}"
    r = want(call("POST", "/api/auth/register", {"username": name, "password": PW, "display_name": "Reg"}), 201, "register")
    expect(len(str(r["token"])) >= 16, "token shorter than 16 chars")
    expect(r["user"].get("username") == name and r["user"].get("id") is not None, f"bad user object: {r['user']}")


@rule("A1.2", "UserObj has id, username, display_name, timezone, avatar_url, status_text, status_emoji", 1)
def _():
    u = new_user()
    missing = [k for k in ("id", "username", "display_name", "timezone", "avatar_url", "status_text", "status_emoji")
               if k not in u["user"]]
    expect(not missing, f"user object missing keys {missing}")


@rule("A1.3", "duplicate username -> 409", 1)
def _():
    u = new_user()
    want(call("POST", "/api/auth/register", {"username": u["username"], "password": PW}), 409, "duplicate register")


@rule("A1.4", "invalid username (space, dash, empty) -> 400; 7-char password -> 400", 1)
def _():
    for bad in (f"bad name{rid(3)}", f"bad-{rid(3)}", ""):
        want(call("POST", "/api/auth/register", {"username": bad, "password": PW}), 400, f"username {bad!r}")
    want(call("POST", "/api/auth/register", {"username": f"ok{rid(8)}", "password": "short77"}), 400, "7-char password")


@rule("A1.5", "login 200 {user, token}; wrong password 401; unknown user 401", 1)
def _():
    u = new_user()
    r = want(call("POST", "/api/auth/login", {"username": u["username"], "password": PW}, node=2), 200, "login")
    expect(len(str(r["token"])) >= 16 and r["user"].get("username") == u["username"], "login body wrong")
    want(call("POST", "/api/auth/login", {"username": u["username"], "password": "WRONG-pass-1"}), 401, "wrong password")
    want(call("POST", "/api/auth/login", {"username": "nobody" + rid(8), "password": PW}), 401, "unknown user")


@rule("A1.6", "GET /api/auth/me 200 {user}; missing or invalid token -> 401", 1)
def _():
    u = new_user()
    r = want(call("GET", "/api/auth/me", token=u["token"], node=1), 200, "me")
    expect(r["user"].get("username") == u["username"], "me returned another user")
    want(call("GET", "/api/auth/me"), 401, "me without token")
    want(call("GET", "/api/auth/me", token="garbage-token-123456789"), 401, "me with bad token")


# ======================================================== A2 workspaces
@rule("A2.1", "POST /api/workspaces 201 {workspace{id,slug,name,owner_id,join_mode:'open'}, general_channel{name:'general'}}", 2)
def _():
    owner, ws = ctx()
    w = ws["workspace"]
    for k in ("id", "slug", "name", "owner_id", "join_mode"):
        expect(k in w, f"workspace missing '{k}': {w}")
    expect(same(w["owner_id"], owner["id"]), "owner_id is not the creator")
    expect(w["join_mode"] == "open", f"join_mode should default to 'open', got {w['join_mode']!r}")
    expect(ws["general"].get("name") == "general" and ws["general"].get("id") is not None, f"general_channel wrong: {ws['general']}")


@rule("A2.2", "bad slug -> 400 (uppercase, underscore, 1 char, 33 chars); duplicate slug -> 409", 2)
def _():
    owner, ws = ctx()
    for bad in ("Bad-Slug", "bad_slug", "a", "a" * 33):
        want(call("POST", "/api/workspaces", {"slug": bad, "name": "x"}, owner["token"]), 400, f"slug {bad!r}")
    want(call("POST", "/api/workspaces", {"slug": ws["slug"], "name": "dup"}, owner["token"]), 409, "duplicate slug")


@rule("A2.3", "workspace routes need auth: no token -> 401; unknown slug -> 404", 2)
def _():
    owner, ws = ctx()
    want(call("POST", "/api/workspaces", {"slug": "x" + rid(6), "name": "x"}), 401, "create without token")
    want(call("GET", "/api/workspaces"), 401, "list without token")
    want(call("GET", f"/api/workspaces/{ws['slug']}/members"), 401, "members without token")
    want(call("GET", "/api/workspaces/no-such-ws-" + rid(6) + "/members", token=owner["token"]), 404, "unknown slug")


@rule("A2.4", "GET /api/workspaces lists only workspaces the caller belongs to", 2)
def _():
    owner, ws = ctx()
    r = want(call("GET", "/api/workspaces", token=owner["token"], node=1), 200, "list")
    expect(any(same(w.get("id"), ws["id"]) for w in r["workspaces"]), "owner's workspace not listed")
    stranger = new_user("s")
    r = want(call("GET", "/api/workspaces", token=stranger["token"]), 200, "list (stranger)")
    expect(not any(same(w.get("id"), ws["id"]) for w in r["workspaces"]), "a non-member sees the workspace")


@rule("A2.5", "GET members 200 {members:[{user_id, role}]}; creator has role 'owner'", 2)
def _():
    owner, ws = ctx()
    m = members(ws, owner["token"])
    expect(m.get(str(owner["id"])) == "owner", f"creator's role is {m.get(str(owner['id']))!r}, want 'owner'")


@rule("A2.6", "open workspace: non-member joins a public channel -> 200 and becomes role 'member'", 2)
def _():
    owner, ws = ctx()
    u = new_user("j")
    want(join(u, ws["general"]["id"], node=2), 200, "join #general on open workspace")
    m = members(ws, owner["token"])
    expect(m.get(str(u["id"])) == "member", f"joiner's role is {m.get(str(u['id']))!r}, want 'member'")
    r = want(call("GET", "/api/workspaces", token=u["token"]), 200, "list")
    expect(any(same(w.get("id"), ws["id"]) for w in r["workspaces"]), "joined workspace not in joiner's list")


@rule("A2.7", "join unknown channel -> 404; join private channel without invite -> 403", 2)
def _():
    owner, ws = ctx()
    u = add_member(ws, owner)
    want(join(u, 99999999), 404, "join unknown channel")
    priv = new_channel(ws, owner, private=True)
    want(join(u, priv["id"]), 403, "join private channel uninvited")


# ======================================================== A3 roles
@rule("A3.1", "owner promotes member -> admin: 200 {member:{user_id, role:'admin'}}", 3)
def _():
    owner, ws = ctx()
    u = add_member(ws, owner)
    r = want(set_role(ws, owner, u, "admin"), 200, "promote to admin")
    expect(same(r["member"].get("user_id"), u["id"]) and r["member"].get("role") == "admin", f"bad member body {r.text[:150]}")
    expect(members(ws, owner["token"]).get(str(u["id"])) == "admin", "role not persisted in GET members")


@rule("A3.2", "admin can set member <-> guest and promote member -> admin", 3)
def _():
    owner, ws = ctx()
    admin = add_member(ws, owner, "admin")
    u = add_member(ws, owner)
    want(set_role(ws, admin, u, "guest"), 200, "admin sets member->guest")
    want(set_role(ws, admin, u, "member"), 200, "admin sets guest->member")
    want(set_role(ws, admin, u, "admin"), 200, "admin promotes member->admin")


@rule("A3.3", "admin changing another admin -> 403; anyone changing the owner -> 403", 3)
def _():
    owner, ws = ctx()
    a1 = add_member(ws, owner, "admin")
    a2 = add_member(ws, owner, "admin")
    want(set_role(ws, a1, a2, "member"), 403, "admin demotes another admin")
    want(set_role(ws, a1, owner, "member"), 403, "admin changes the owner")
    want(set_role(ws, owner, owner, "admin"), 403, "owner changes own role via PATCH")


@rule("A3.4", "role 'owner' via PATCH -> 400; unknown role -> 400; member/guest calling PATCH -> 403", 3)
def _():
    owner, ws = ctx()
    u = add_member(ws, owner)
    v = add_member(ws, owner)
    want(set_role(ws, owner, u, "owner"), 400, "PATCH role=owner")
    want(set_role(ws, owner, u, "superuser"), 400, "PATCH role=superuser")
    want(set_role(ws, v, u, "guest"), 403, "member changes someone's role")


@rule("A3.5", "PATCH role of a user who is not in the workspace -> 404", 3)
def _():
    owner, ws = ctx()
    stranger = new_user("s")
    want(set_role(ws, owner, stranger, "admin"), 404, "PATCH non-member")


@rule("A3.6", "transfer_ownership: non-owner 403; target not admin 400; success swaps owner/admin", 3)
def _():
    owner = new_user("own")
    ws = new_workspace(owner)
    admin = add_member(ws, owner, "admin")
    mem = add_member(ws, owner)
    path = f"/api/workspaces/{ws['slug']}/transfer_ownership"
    want(call("POST", path, {"new_owner_id": mem["id"]}, admin["token"]), 403, "admin calls transfer")
    want(call("POST", path, {"new_owner_id": mem["id"]}, owner["token"]), 400, "transfer to a plain member")
    want(call("POST", path, {"new_owner_id": admin["id"]}, owner["token"], node=1), 200, "transfer to admin")
    m = members(ws, owner["token"])
    expect(m.get(str(admin["id"])) == "owner" and m.get(str(owner["id"])) == "admin",
           f"after transfer roles are new={m.get(str(admin['id']))!r} old={m.get(str(owner['id']))!r}")
    r = want(call("GET", "/api/workspaces", token=admin["token"]), 200, "list")
    w = [w for w in r["workspaces"] if same(w.get("id"), ws["id"])]
    expect(w and same(w[0].get("owner_id"), admin["id"]), "workspace.owner_id not updated after transfer")


@rule("A3.7", "guest: join public channel -> 403; create channel -> 403", 3)
def _():
    owner, ws = ctx()
    g = add_member(ws, owner, "guest")
    ch = new_channel(ws, owner)
    want(join(g, ch["id"]), 403, "guest joins public channel")
    want(call("POST", f"/api/workspaces/{ws['slug']}/channels", {"name": "g-" + rid(6)}, g["token"]), 403, "guest creates channel")


@rule("A3.8", "member: create public channel 201, private 403; admin and owner: private 201", 3)
def _():
    owner, ws = ctx()
    m = add_member(ws, owner)
    a = add_member(ws, owner, "admin")
    p = f"/api/workspaces/{ws['slug']}/channels"
    want(call("POST", p, {"name": "pub-" + rid(6)}, m["token"]), 201, "member creates public")
    want(call("POST", p, {"name": "prv-" + rid(6), "is_private": True}, m["token"]), 403, "member creates private")
    want(call("POST", p, {"name": "prv-" + rid(6), "is_private": True}, a["token"]), 201, "admin creates private")
    want(call("POST", p, {"name": "prv-" + rid(6), "is_private": True}, owner["token"]), 201, "owner creates private")


# ======================================================== A4 invitations & join mode
def invite(ws, actor, **body):
    return call("POST", f"/api/workspaces/{ws['slug']}/invitations", body, actor["token"])


def accept(user, code, node=0):
    return call("POST", f"/api/invitations/{code}/accept", None, user["token"], node)


@rule("A4.1", "admin/owner create invitation 201 {invitation{code}}; member -> 403", 4)
def _():
    owner, ws = ctx()
    a = add_member(ws, owner, "admin")
    m = add_member(ws, owner)
    r = want(invite(ws, owner), 201, "owner creates invitation")
    expect(r["invitation"].get("code"), "invitation has no code")
    want(invite(ws, a), 201, "admin creates invitation")
    want(invite(ws, m), 403, "member creates invitation")


@rule("A4.2", "accept 200 adds the user as 'member'; max_uses defaults to 1 (2nd user -> 404)", 4)
def _():
    owner, ws = ctx()
    code = want(invite(ws, owner), 201, "create")["invitation"]["code"]
    u1, u2 = new_user("i"), new_user("i")
    want(accept(u1, code, node=1), 200, "first accept")
    expect(members(ws, owner["token"]).get(str(u1["id"])) == "member", "accepting user is not a 'member'")
    want(accept(u2, code), 404, "second accept of a default (1-use) invite")


@rule("A4.3", "max_uses=2 allows exactly two accepts; unknown code -> 404", 4)
def _():
    owner, ws = ctx()
    code = want(invite(ws, owner, max_uses=2), 201, "create max_uses=2")["invitation"]["code"]
    want(accept(new_user("i"), code), 200, "accept 1")
    want(accept(new_user("i"), code), 200, "accept 2")
    want(accept(new_user("i"), code), 404, "accept 3 (exhausted)")
    want(accept(new_user("i"), "nosuchcode" + rid(8)), 404, "unknown code")


@rule("A4.4", "targeted invite (invited_user_id / invited_username): other user 403, target 200", 4)
def _():
    owner, ws = ctx()
    t1, t2, other = new_user("t"), new_user("t"), new_user("o")
    c1 = want(invite(ws, owner, invited_user_id=t1["id"]), 201, "create targeted by id")["invitation"]["code"]
    want(accept(other, c1), 403, "wrong user accepts id-targeted invite")
    want(accept(t1, c1), 200, "target accepts")
    c2 = want(invite(ws, owner, invited_username=t2["username"]), 201, "create targeted by username")["invitation"]["code"]
    want(accept(other, c2), 403, "wrong user accepts username-targeted invite")
    want(accept(t2, c2), 200, "target accepts")


@rule("A4.5", "expired invitation (expires_in_seconds=1, wait 2s) -> 404", 4)
def _():
    owner, ws = ctx()
    code = want(invite(ws, owner, expires_in_seconds=1), 201, "create expiring")["invitation"]["code"]
    time.sleep(2.1)
    want(accept(new_user("e"), code), 404, "accept after expiry")


@rule("A4.6", "GET invitations: admin/owner 200 {invitations:[...active]}; member 403", 4)
def _():
    owner, ws = ctx()
    m = add_member(ws, owner)
    code = want(invite(ws, owner, max_uses=5), 201, "create")["invitation"]["code"]
    r = want(call("GET", f"/api/workspaces/{ws['slug']}/invitations", token=owner["token"], node=2), 200, "list")
    expect(any(i.get("code") == code for i in r["invitations"]), "new invitation missing from list")
    want(call("GET", f"/api/workspaces/{ws['slug']}/invitations", token=m["token"]), 403, "member lists")


@rule("A4.7", "DELETE invitation: member 403; admin/owner 200 {deleted:true}; revoked code -> 404 on accept", 4)
def _():
    owner, ws = ctx()
    m = add_member(ws, owner)
    code = want(invite(ws, owner, max_uses=5), 201, "create")["invitation"]["code"]
    p = f"/api/workspaces/{ws['slug']}/invitations/{code}"
    want(call("DELETE", p, token=m["token"]), 403, "member revokes")
    r = want(call("DELETE", p, token=owner["token"]), 200, "owner revokes")
    expect(r.body == {"deleted": True}, f"expected {{'deleted': true}}, got {r.text[:80]}")
    want(accept(new_user("r"), code), 404, "accept revoked")
    r = want(call("GET", f"/api/workspaces/{ws['slug']}/invitations", token=owner["token"]), 200, "list")
    expect(not any(i.get("code") == code for i in r["invitations"]), "revoked invitation still listed")


@rule("A4.8", "PATCH /api/workspaces/{slug} {name, join_mode}: owner/admin 200 {workspace}; member 403; bad join_mode 400", 4)
def _():
    owner = new_user("own")
    ws = new_workspace(owner)
    m = add_member(ws, owner)
    a = add_member(ws, owner, "admin")
    p = f"/api/workspaces/{ws['slug']}"
    r = want(call("PATCH", p, {"name": "Renamed"}, owner["token"]), 200, "owner renames")
    expect(r["workspace"].get("name") == "Renamed", "name not updated in response")
    want(call("PATCH", p, {"join_mode": "invite_only"}, m["token"]), 403, "member patches")
    want(call("PATCH", p, {"join_mode": "secret"}, owner["token"]), 400, "bad join_mode")
    r = want(call("PATCH", p, {"join_mode": "invite_only"}, a["token"]), 200, "admin sets invite_only")
    expect(r["workspace"].get("join_mode") == "invite_only", "join_mode not updated in response")


@rule("A4.9", "invite_only: non-member join -> 403; after accepting an invite the join -> 200", 4)
def _():
    owner = new_user("own")
    ws = new_workspace(owner)
    want(call("PATCH", f"/api/workspaces/{ws['slug']}", {"join_mode": "invite_only"}, owner["token"]), 200, "set invite_only")
    ch = new_channel(ws, owner)
    u = new_user("n")
    want(join(u, ch["id"]), 403, "non-member joins channel in invite_only workspace")
    code = want(invite(ws, owner), 201, "create")["invitation"]["code"]
    want(accept(u, code), 200, "accept")
    want(join(u, ch["id"], node=1), 200, "join after accepting")


@rule("A4.10", "targeted invitation is single-use: max_uses forced to 1; target's second accept -> 404", 4)
def _():
    owner, ws = ctx()
    t = new_user("t")
    inv = want(invite(ws, owner, invited_user_id=t["id"], max_uses=5), 201, "create targeted with max_uses=5")["invitation"]
    expect(inv.get("max_uses") == 1, f"targeted invitation max_uses={inv.get('max_uses')!r}, want 1")
    want(accept(t, inv["code"]), 200, "target accepts")
    want(accept(t, inv["code"], node=2), 404, "target accepts a second time")


@rule("A4.11", "every Component A route: no token or bad token -> 401", 4)
def _():
    owner, ws = ctx()
    m = add_member(ws, owner)
    code = want(invite(ws, owner, max_uses=5), 201, "create")["invitation"]["code"]
    s_ = ws["slug"]
    routes = [("GET", "/api/workspaces"), ("POST", "/api/workspaces"), ("PATCH", f"/api/workspaces/{s_}"),
              ("GET", f"/api/workspaces/{s_}/members"), ("PATCH", f"/api/workspaces/{s_}/members/{m['id']}"),
              ("POST", f"/api/workspaces/{s_}/transfer_ownership"), ("POST", f"/api/workspaces/{s_}/invitations"),
              ("GET", f"/api/workspaces/{s_}/invitations"), ("DELETE", f"/api/workspaces/{s_}/invitations/{code}"),
              ("POST", f"/api/invitations/{code}/accept"), ("POST", f"/api/workspaces/{s_}/channels"),
              ("POST", f"/api/channels/{ws['general']['id']}/join")]
    bad = []
    for meth, path in routes:
        for tok in (None, "garbage-token-123456789"):
            r = call(meth, path, {"name": "x", "role": "admin"} if meth in ("POST", "PATCH") else None, tok)
            if r.status != 401:
                bad.append(f"{meth} {path} ({'no' if tok is None else 'bad'} token) -> {r.status}")
    expect(not bad, f"{len(bad)} route(s) not 401: " + "; ".join(bad[:5]))


if __name__ == "__main__":
    run()
