"""Restart the cluster so it runs your latest code. Usage:
    bash /spec/tools/restart.sh          # kill the 3 node PIDs and the IRC gateway PID; start.sh's respawn loops restart them (~2s)
    bash /spec/tools/restart.sh --full   # also kill start.sh and its loops, then launch /app/start.sh fresh
    bash /spec/tools/restart.sh --full --fresh   # as --full, and start from an EMPTY database, the way graders do
                                                 # (moves /app/data aside to /tmp/old-data-<time>/; nothing is deleted)
Never kills by name: PIDs come from the listening ports (ss -ltnp or /proc)."""
import os, re, signal, subprocess, sys, time, urllib.request

PORTS = [8000, 8001, 8002]
IRC = 6667


def healthy(node):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{8000 + node}/api/health", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def pid_on_port(port):
    """PID listening on <port>, via `ss -ltnp` or /proc (never by name)."""
    try:
        out = subprocess.run(["ss", "-ltnpH", f"sport = :{port}"], capture_output=True, text=True, timeout=3).stdout
        m = re.search(r"pid=(\d+)", out)
        if m:
            return int(m.group(1))
    except Exception:
        pass
    inodes = set()
    for f in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            for line in open(f).readlines()[1:]:
                p = line.split()
                if p[3] == "0A" and int(p[1].split(":")[1], 16) == port:
                    inodes.add(f"socket:[{p[9]}]")
        except OSError:
            pass
    for pid in filter(str.isdigit, os.listdir("/proc")):
        try:
            for fd in os.listdir(f"/proc/{pid}/fd"):
                if os.readlink(f"/proc/{pid}/fd/{fd}") in inodes:
                    return int(pid)
        except OSError:
            continue
    return None


def ppid(pid):
    try:
        return int(open(f"/proc/{pid}/stat").read().rsplit(")", 1)[1].split()[1])
    except Exception:
        return None


def cmdline(pid):
    try:
        return open(f"/proc/{pid}/cmdline", "rb").read().replace(b"\0", b" ").decode()
    except Exception:
        return ""


def kill(pid):
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass


def launch():
    # Start start.sh directly with every std stream detached from our caller. Never via `bash -c "... &"`:
    # a helper subshell would keep the caller's output pipe open and hang the agent's command forever.
    log = open("/tmp/start.log", "ab")
    subprocess.Popen(["bash", "/app/start.sh"], cwd="/app", stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                     start_new_session=True, close_fds=True)
    log.close()


def wait_healthy(sec):
    end = time.time() + sec
    while time.time() < end:
        if all(healthy(i) for i in range(3)):
            return True
        time.sleep(0.3)
    return False


fresh = "--fresh" in sys.argv
full = "--full" in sys.argv or fresh
pids = {p: pid_on_port(p) for p in PORTS + [IRC, 6379]}
if full:
    # kill each listener's respawn-loop parent and start.sh grandparent, but only if they really are start.sh shells
    me = {os.getpid(), os.getppid()}
    for p, pid in pids.items():
        if not pid:
            continue
        for anc in (ppid(pid), ppid(ppid(pid) or 0)):
            if anc and anc > 1 and anc not in me and "start.sh" in cmdline(anc):
                kill(anc)
for p in PORTS + [IRC] + ([6379] if full else []):
    if pids.get(p):
        kill(pids[p])
if fresh:
    time.sleep(1)
    if os.path.isdir("/app/data"):
        dest = f"/tmp/old-data-{int(time.time())}"
        import shutil
        shutil.move("/app/data", dest)
        print(f"moved the old database folder to {dest}")
    os.makedirs("/app/data/files", exist_ok=True)
if full or not any(pids[p] for p in PORTS):
    time.sleep(1)
    launch()
    ok = wait_healthy(15)
else:
    ok = wait_healthy(8)
    if not ok:  # start.sh has no respawn loop: launch it fresh
        launch()
        ok = wait_healthy(12)
print("RESTART OK: 8000, 8001, 8002 healthy" if ok else
      "RESTART FAILED: cluster not healthy; read /tmp/start.log and /tmp/node*.log")
sys.exit(0 if ok else 1)
