"""Kill every process that belongs to the app under test (cmdline mentions /app/ or redis-server), except us."""
import os, signal
me = {os.getpid(), os.getppid()}
for pid in filter(str.isdigit, os.listdir("/proc")):
    p = int(pid)
    if p in me or p == 1:
        continue
    try:
        cmd = open(f"/proc/{pid}/cmdline", "rb").read().replace(b"\0", b" ").decode()
        cwd = os.readlink(f"/proc/{pid}/cwd")
    except OSError:
        continue
    if ("/app/" in cmd or cwd.startswith("/app") or "redis-server" in cmd) and "killapp.py" not in cmd and "harness.py" not in cmd:
        try:
            os.kill(p, signal.SIGKILL)
        except OSError:
            pass
