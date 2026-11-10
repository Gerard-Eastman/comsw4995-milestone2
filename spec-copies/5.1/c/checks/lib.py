"""Shared helpers for the checks in this folder. Imported by the *_checks.py files; not run directly.

Each check prints one line per rule (PASS/FAIL <id> <description>) and ends with
`RESULT: <n> passed, <m> failed`. A whole check finishes in under 30 seconds.
How much is printed is set by FEEDBACK in this folder's lib.sh.
"""
import json, os, random, re, signal, socket, string, subprocess, sys, time, traceback

import requests

NODES = ["http://127.0.0.1:8000", "http://127.0.0.1:8001", "http://127.0.0.1:8002"]
WS_NODES = ["ws://127.0.0.1:8000", "ws://127.0.0.1:8001", "ws://127.0.0.1:8002"]
PW = "correct-horse-1"
def _feedback_mode():
    """The mode is the FEEDBACK= line of lib.sh in this folder (environment variables do not change it)."""
    try:
        for line in open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib.sh")):
            m = re.match(r"\s*FEEDBACK=(\w+)", line)
            if m:
                return m.group(1)
    except OSError:
        pass
    return "score_only"


FEEDBACK = _feedback_mode()                               # verbose | score_only (the FEEDBACK= line in lib.sh)
REGRESSION = os.environ.get("REGRESSION") == "1"         # regression-suite output format
COMP = "x"
_session = requests.Session()


class CheckFail(Exception):
    pass


def expect(cond, msg):
    """Fail the current rule with `msg` unless cond is true."""
    if not cond:
        raise CheckFail(msg)


def same(a, b):
    """Ids may be ints or strings; compare them as strings."""
    return a is not None and b is not None and str(a) == str(b)


def rid(n=6):
    return "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(n))


# ---------------------------------------------------------------- HTTP
class Resp:
    def __init__(self, status, body, text=""):
        self.status, self.body, self.text = status, body, text

    def __getitem__(self, k):
        if not isinstance(self.body, dict) or k not in self.body:
            raise CheckFail(f"response (status {self.status}) has no key '{k}': {self.text[:200]}")
        return self.body[k]

    def short(self):
        return f"status {self.status}, body {self.text[:160]}"


def call(method, path, body=None, token=None, node=0, params=None, raw=None):
    """Send one request to node 0/1/2. Returns Resp(status, json-or-None). status 0 = no answer."""
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        r = _session.request(method, NODES[node] + path, json=body, headers=headers,
                             params=params, data=raw, timeout=5)
    except requests.RequestException as e:
        return Resp(0, None, f"no answer: {type(e).__name__}")
    try:
        js = r.json()
    except ValueError:
        js = None
    return Resp(r.status_code, js, r.text)


def want(resp, status, what):
    """Fail unless resp.status == status."""
    expect(resp.status == status, f"{what}: expected {status}, got {resp.short()}")
    return resp


# ---------------------------------------------------------------- fixtures
def new_user(prefix="u", node=0):
    """Register a fresh user. Returns dict(id, username, token, user)."""
    name = f"{prefix}{rid(8)}"
    r = call("POST", "/api/auth/register", {"username": name, "password": PW}, node=node)
    expect(r.status == 201 and isinstance(r.body, dict) and r.body.get("token"),
           f"setup: register {name} failed ({r.short()})")
    u = r.body["user"]
    return {"id": u.get("id"), "username": name, "token": r.body["token"], "user": u}


def new_workspace(owner, node=0):
    """Create a workspace owned by `owner`. Returns dict(slug, id, workspace, general)."""
    slug = f"ws-{rid(8)}"
    r = call("POST", "/api/workspaces", {"slug": slug, "name": "Check WS " + slug}, owner["token"], node)
    expect(r.status == 201 and isinstance(r.body, dict) and "workspace" in r.body,
           f"setup: create workspace failed ({r.short()})")
    return {"slug": slug, "id": r.body["workspace"].get("id"), "workspace": r.body["workspace"],
            "general": r.body.get("general_channel") or {}}


def new_channel(ws, user, name=None, private=False, node=0):
    name = name or f"ch-{rid(8)}"
    r = call("POST", f"/api/workspaces/{ws['slug']}/channels", {"name": name, "is_private": private},
             user["token"], node)
    expect(r.status == 201 and isinstance(r.body, dict) and "channel" in r.body,
           f"setup: create channel failed ({r.short()})")
    return r.body["channel"]


def join(user, channel_id, node=0):
    return call("POST", f"/api/channels/{channel_id}/join", None, user["token"], node)


def add_member(ws, owner, role="member"):
    """New user who joins `ws` (open join via #general), then gets `role` set by the owner."""
    u = new_user("m")
    r = join(u, ws["general"].get("id"))
    expect(r.status == 200, f"setup: open-workspace join of #general failed ({r.short()})")
    if role != "member":
        r = call("PATCH", f"/api/workspaces/{ws['slug']}/members/{u['id']}", {"role": role}, owner["token"])
        expect(r.status == 200, f"setup: owner setting role {role} failed ({r.short()})")
    return u


def post(user, channel_id, body, node=0, parent_id=None):
    payload = {"body": body}
    if parent_id is not None:
        payload["parent_id"] = parent_id
    r = call("POST", f"/api/channels/{channel_id}/messages", payload, user["token"], node)
    expect(r.status == 201 and isinstance(r.body, dict) and "message" in r.body,
           f"setup: posting a message failed ({r.short()})")
    return r.body["message"]


# ---------------------------------------------------------------- WebSocket
def ws_connect(token, node=0, timeout=3):
    from websockets.sync.client import connect
    return connect(f"{WS_NODES[node]}/api/ws?token={token}", open_timeout=timeout, close_timeout=1)


def ws_recv_until(conn, pred, timeout=3.0):
    """Read frames until pred(frame) is true. Returns (frame, all_frames_seen). frame None on timeout."""
    seen, end = [], time.time() + timeout
    while time.time() < end:
        try:
            raw = conn.recv(timeout=max(0.05, end - time.time()))
        except TimeoutError:
            break
        except Exception:
            break
        try:
            f = json.loads(raw)
        except ValueError:
            continue
        seen.append(f)
        if pred(f):
            return f, seen
    return None, seen


def ws_subscribe(conn, channel_id, timeout=3.0):
    conn.send(json.dumps({"type": "subscribe", "channel_id": channel_id}))
    f, _ = ws_recv_until(conn, lambda f: f.get("type") == "subscribed" and same(f.get("channel_id"), channel_id), timeout)
    expect(f is not None, "no {type:'subscribed'} frame within 3s after subscribe")
    expect(isinstance(f.get("head_event_id"), int), f"subscribed frame has no integer head_event_id: {f}")
    return f["head_event_id"]


# ---------------------------------------------------------------- cluster
def healthy(node):
    try:
        return _session.get(NODES[node] + "/api/health", timeout=2).status_code == 200
    except requests.RequestException:
        return False


def boot():
    """Start /app/start.sh if the cluster is not answering. Waits up to 12s."""
    if all(healthy(i) for i in range(3)):
        return True
    if not any(healthy(i) for i in range(3)) and not os.path.exists("/app/start.sh"):
        return False
    if not any(healthy(i) for i in range(3)) and os.path.exists("/app/start.sh"):
        # stdin/stdout/stderr fully detached, so no child keeps the caller's output pipe open
        log = open("/tmp/start.log", "ab")
        subprocess.Popen(["bash", "/app/start.sh"], cwd="/app", stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                         start_new_session=True, close_fds=True)
        log.close()
    end = time.time() + 12
    while time.time() < end:
        if all(healthy(i) for i in range(3)):
            return True
        time.sleep(0.5)
    return all(healthy(i) for i in range(3))


def down_ports():
    return [8000 + i for i in range(3) if not healthy(i)]


def pid_on_port(port):
    """PID of the process listening on 127.0.0.1:<port>, via `ss -ltnp` (never by name)."""
    import re
    try:
        out = subprocess.run(["ss", "-ltnpH", f"sport = :{port}"], capture_output=True, text=True, timeout=3).stdout
        m = re.search(r"pid=(\d+)", out)
        if m:
            return int(m.group(1))
    except Exception:
        pass
    # fallback without ss: find the listening socket's inode in /proc/net/tcp*, then its owner
    inodes = set()
    for f in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            for line in open(f).readlines()[1:]:
                p = line.split()
                if p[3] == "0A" and int(p[1].split(":")[1], 16) == port:
                    inodes.add(p[9])
        except OSError:
            pass
    for pid in filter(str.isdigit, os.listdir("/proc")):
        try:
            for fd in os.listdir(f"/proc/{pid}/fd"):
                if os.readlink(f"/proc/{pid}/fd/{fd}") in {f"socket:[{i}]" for i in inodes}:
                    return int(pid)
        except OSError:
            continue
    return None


def port_open(port):
    s = socket.socket()
    s.settimeout(1)
    try:
        s.connect(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


# ---------------------------------------------------------------- runner
_RULES = []


def set_comp(name):
    """Label for the rules registered after this call (used by the regression suite output)."""
    global COMP
    COMP = name


def rule(rule_id, desc, stage=None):
    def deco(fn):
        _RULES.append((rule_id, desc, stage, fn, COMP))
        return fn
    return deco


def _report(ok, comp, rule_id, desc, why=""):
    if REGRESSION:
        if not ok:
            print(f"REGRESSION FAIL {comp} {rule_id} {desc}: {why}", flush=True)
    elif FEEDBACK == "verbose":
        print(f"PASS {rule_id} {desc}" if ok else f"FAIL {rule_id} {desc}: {why}", flush=True)


def run(argv=None, budget=22, need_boot=True, comps=None):
    """Run the rules. argv[1] (optional) = stage number(s) to run, e.g. 2 or 1,2."""
    argv = argv if argv is not None else sys.argv
    budget = float(os.environ.get("CHECK_BUDGET", budget))
    stages = None
    if len(argv) > 1 and argv[1] not in ("all", ""):
        stages = {s for s in argv[1].split(",")}
    passed = failed = 0
    deadline = time.time() + budget

    def on_alarm(*_):
        raise TimeoutError("check ran out of its time budget")
    signal.signal(signal.SIGALRM, on_alarm)

    def finish():
        if REGRESSION:
            print(f"REGRESSION: {failed} broken")
        else:
            print(f"RESULT: {passed} passed, {failed} failed")
        sys.stdout.flush()
        os._exit(0 if failed == 0 else 1)

    if need_boot and not boot():
        down = down_ports()
        why = ("/app/start.sh does not exist" if len(down) == 3 and not os.path.exists("/app/start.sh") else
               "nothing answers GET /api/health on 8000, 8001 and 8002 after starting /app/start.sh (see /tmp/start.log)"
               if len(down) == 3 else f"port(s) {down} do not answer GET /api/health (a node died and was not restarted? "
               "start.sh must run each node in a respawn loop)")
        _report(False, "base", "0", "cluster is up", why)
        failed = 1
        finish()
    for rule_id, desc, stage, fn, comp in _RULES:
        if stages is not None and str(stage) not in stages:
            continue
        if comps is not None and comp not in comps:
            continue
        left = int(deadline - time.time())
        if left <= 0:
            _report(False, comp, rule_id, desc, "not run, check time budget used up (a slow endpoint?)")
            failed += 1
            continue
        signal.alarm(max(1, left))
        try:
            fn()
            signal.alarm(0)
            _report(True, comp, rule_id, desc)
            passed += 1
        except CheckFail as e:
            signal.alarm(0)
            _report(False, comp, rule_id, desc, str(e))
            failed += 1
        except TimeoutError:
            signal.alarm(0)
            _report(False, comp, rule_id, desc, "timed out (an endpoint took too long or hung)")
            failed += 1
        except Exception as e:  # a crash in the check means the app returned something unexpected
            signal.alarm(0)
            _report(False, comp, rule_id, desc, f"unexpected response ({type(e).__name__}: {str(e)[:150]})")
            failed += 1
    finish()


# ---------------------------------------------------------------- files
def upload(token, data, filename="note.txt", ctype="text/plain", node=0, field="file"):
    """multipart/form-data POST /api/files. Returns Resp."""
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        r = _session.post(NODES[node] + "/api/files", files={field: (filename, data, ctype)},
                          headers=headers, timeout=20)
    except requests.RequestException as e:
        return Resp(0, None, f"no answer: {type(e).__name__}")
    try:
        js = r.json()
    except ValueError:
        js = None
    return Resp(r.status_code, js, r.text)


def raw_get(path, token=None, node=0):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return _session.get(NODES[node] + path, headers=headers, timeout=10)


# ---------------------------------------------------------------- IRC
class Irc:
    """Minimal IRC client for the gateway on 127.0.0.1:6667."""

    def __init__(self, timeout=3):
        self.sock = socket.create_connection(("127.0.0.1", 6667), timeout=timeout)
        self.buf = b""
        self.closed = False

    def send(self, line):
        self.sock.sendall((line + "\r\n").encode())

    def read_line(self, timeout):
        end = time.time() + timeout
        while b"\n" not in self.buf:
            left = end - time.time()
            if left <= 0:
                return None
            self.sock.settimeout(left)
            try:
                chunk = self.sock.recv(4096)
            except socket.timeout:
                return None
            except OSError:
                self.closed = True
                return None
            if not chunk:
                self.closed = True
                return None
            self.buf += chunk
        line, self.buf = self.buf.split(b"\n", 1)
        return line.decode("utf-8", "replace").rstrip("\r")

    def until(self, pred, timeout=3.0):
        """Read lines until pred(line). Returns (line or None, lines seen)."""
        seen, end = [], time.time() + timeout
        while time.time() < end:
            ln = self.read_line(end - time.time())
            if ln is None:
                if self.closed:
                    break
                continue
            seen.append(ln)
            if pred(ln):
                return ln, seen
        return None, seen

    def register(self, token, nick, user=None):
        """PASS/NICK/USER. Returns the lines up to 422/464 (or what arrived in 3s)."""
        if token is not None:
            self.send(f"PASS {token}")
        self.send(f"NICK {nick}")
        self.send(f"USER {user or nick} 0 * :{nick}")
        _, seen = self.until(lambda l: num(l) in ("422", "464", "433"), 3)
        return seen

    def join(self, name):
        self.send(f"JOIN {name}")
        _, seen = self.until(lambda l: num(l) in ("366", "403", "442", "451"), 3)
        return seen

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


def num(line):
    """The command/numeric of a server line (':huddle 001 nick ...' -> '001')."""
    p = line.split(" ")
    if p and p[0].startswith(":") and len(p) > 1:
        return p[1].upper()
    return p[0].upper() if p else ""


def irc_user(prefix="irc"):
    """A registered IRC connection for a fresh user. Returns (user, Irc)."""
    u = new_user(prefix)
    c = Irc()
    seen = c.register(u["token"], u["username"])
    expect(any(num(l) == "001" for l in seen), f"setup: IRC registration of {u['username']} got no 001: {seen[:6]}")
    return u, c
