"""Assemble the /spec folder for every run of the milestone 2 run plan from the fragments in m2src.
Output: /home/claude/m2build/<run>/   for run in 1.1 1.2 1.3 2.1 2.2 2.3 3 4 5.1 5.2 5.3"""
import os, shutil, stat, sys

SRC = os.path.dirname(os.path.abspath(__file__))
OUT = "/home/claude/m2build"
VERSION = sys.argv[1] if len(sys.argv) > 1 else "m2-v1"

COMP = {
    "a": dict(name="A", title="roles and invitations", frag="roles", py="roles_checks.py",
              steps=[("auth", "Auth: register, login, me", 6), ("workspaces", "Workspaces and joining", 7),
                     ("roles", "Roles and permissions", 8), ("invitations", "Invitations and join mode", 11)]),
    "b": dict(name="B", title="channels and message history", frag="channels", py="channels_checks.py",
              steps=[("channels", "Channel management", 8), ("messages", "Messages, threads, paging", 7),
                     ("pins-search", "Pins and search", 6), ("mentions-read", "Mentions and read state", 6),
                     ("events", "WebSocket events", 9)]),
    "c": dict(name="C", title="features built on messages", frag="c", py="c_checks.py",
              steps=[("reactions", "Reactions", 6), ("dms", "Direct messages", 5), ("files", "Files", 5),
                     ("slash", "Slash commands", 6), ("groups-mentions", "User groups, @group and @here", 5),
                     ("profiles", "Profiles", 4)]),
    "d": dict(name="D", title="cluster robustness", frag="d", py="d_checks.py",
              steps=[("node-kill", "A killed HTTP node", 4), ("redis-kill", "A killed Redis", 4),
                     ("load", "WebSocket delivery under load", 3)]),
    "e": dict(name="E", title="IRC, web UI and message edits", frag="e", py="e_checks.py",
              steps=[("edit-delete", "Message edit and delete", 5), ("irc-register", "IRC: connection and registration", 5),
                     ("irc-channels", "IRC: channels and bridging", 6), ("ui-page", "Web UI: served page and pinned hooks", 5),
                     ("ui-auth-channels", "Web UI: sign-up, login, workspace, channels", 7),
                     ("ui-messages", "Web UI: messages, threads, reactions, logout", 7),
                     ("ui-settings", "Web UI: workspace settings, invitations, joining, channel settings", 6)]),
}
BASE_RULES = 13

# run -> (feedback mode, components with spec+checks, A/B handling)
RUNS = {
    "1.1": ("score_only", ["c"], None), "1.2": ("score_only", ["d"], None), "1.3": ("score_only", ["e"], None),
    "2.1": ("verbose", ["c"], None), "2.2": ("verbose", ["d"], None), "2.3": ("verbose", ["e"], None),
    "3": ("verbose", ["c", "d", "e"], None), "4": ("verbose", ["c", "d", "e"], "checks-only"),
    "5.1": ("verbose", ["c", "d", "e"], "regression"), "5.2": ("verbose", ["c", "d", "e"], "regression+specs"),
    "5.3": ("verbose", ["c", "d", "e"], "plain"),
}

LIB_SH = """# Shared settings for the checks in this folder. Every check_*.sh here sources this file.
FEEDBACK={mode}
export FEEDBACK PYTHONDONTWRITEBYTECODE=1
PY=/opt/test-venv/bin/python; [ -x "$PY" ] || PY=python3
[ -z "$PLAYWRIGHT_BROWSERS_PATH" ] && [ -d /ms-playwright ] && export PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
"""
WRAP = """#!/usr/bin/env bash
# {doc}
cd "$(dirname "$0")" && source ./lib.sh
exec timeout 24 "$PY" ./{py} {arg}
"""
REG_SH = """#!/usr/bin/env bash
# The A and B regression suite: every base, Spec A and Spec B rule in one command (under 30 seconds).
# Prints only the rules that broke, then `REGRESSION: <n> broken`.
cd "$(dirname "$0")" && source ./lib.sh
REGRESSION=1 exec timeout 26 "$PY" ./regression.py
"""
REG_PY = '''"""Regression suite runner: base, roles (A) and channels (B) rules."""
import os, sys
os.environ["REGRESSION"] = "1"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib  # noqa
import base_checks, roles_checks, channels_checks  # noqa: registers the rules
lib.run(["regression", "all"], budget=24)
'''


def w(path, text, exe=False):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)
    if exe:
        os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def frag(comp, n):
    return open(f"{SRC}/{COMP[comp]['frag']}/stage{n}.md").read().strip() + "\n"


def step_file(comp, n):
    slug = COMP[comp]["steps"][n - 1][0]
    return f"{comp}/{comp}-{n}-{slug}.md"


def check_cmd(comp, n):
    return f"bash /spec/{comp}/checks/check_{comp}_{n}.sh"


def rule_range(comp, n):
    k = COMP[comp]["steps"][n - 1][2]
    return f"{COMP[comp]['name']}{n}.1-{COMP[comp]['name']}{n}.{k}"


def write_component(d, comp, mode, with_spec, with_checks):
    c = COMP[comp]
    n_steps = len(c["steps"])
    if with_checks:
        cd = f"{d}/{comp}/checks"
        os.makedirs(cd, exist_ok=True)
        w(f"{cd}/lib.sh", LIB_SH.format(mode=mode))
        shutil.copy(f"{SRC}/common/checks/lib.py", f"{cd}/lib.py")
        src_py = f"{SRC}/{c['frag']}/{c['py']}"
        shutil.copy(src_py, f"{cd}/{c['py']}")
        for n in range(1, n_steps + 1):
            w(f"{cd}/check_{comp}_{n}.sh", WRAP.format(doc=f"Spec {c['name']}, step {n}: rules {rule_range(comp, n)}",
                                                       py=c["py"], arg=n), True)
    if with_spec:
        for n in range(1, n_steps + 1):
            body = frag(comp, n)
            title_line, rest = body.split("\n", 1)
            title = title_line.lstrip("#").strip()
            head = f"# {title} (Spec {c['name']}, step {n} of {n_steps})\n\n"
            meta = (f"Check: `{check_cmd(comp, n)}` (rules {rule_range(comp, n)}). " if with_checks else
                    f"Rules {rule_range(comp, n)}; the regression suite `bash /spec/checks/regression.sh` checks them. ")
            meta += "Architecture, conventions and the basics: `/spec/base/base.md`.\n\n"
            if n > 1:
                prev = check_cmd(comp, n - 1) if with_checks else "bash /spec/checks/regression.sh"
                meta += (f"Start this step only after `{prev}` reports `0 failed`" + ("" if with_checks else " / `0 broken`")
                         + ". Call the functions listed under **Uses**; do not write second versions of them.\n\n")
            w(f"{d}/{step_file(comp, n)}", head + meta + rest.lstrip("\n"))
        if os.path.isdir(f"{SRC}/{c['frag']}/ui"):
            shutil.copytree(f"{SRC}/{c['frag']}/ui", f"{d}/{comp}/ui")


def read_cmds(d, rels):
    """Exact commands that print each spec file in chunks under ~7500 chars."""
    out = []
    for rel in rels:
        lines = open(f"{d}/{rel}").read().split("\n")
        start, size = 1, 0
        for i, ln in enumerate(lines, 1):
            size += len(ln) + 1
            if size > 7500:
                out.append(f"sed -n '{start},{i - 1}p' /spec/{rel}")
                start, size = i, len(ln) + 1
        out.append(f"sed -n '{start},{len(lines)}p' /spec/{rel}" if start > 1 else f"cat /spec/{rel}")
    return out


FULL_COMP = None
E7_RUNS = {"5.1", "5.2", "5.3"}   # E7 (settings UI) needs Spec A's routes: only in the whole-app runs


def build(run):
    global COMP, FULL_COMP
    import copy
    if FULL_COMP is None:
        FULL_COMP = copy.deepcopy(COMP)
    COMP = copy.deepcopy(FULL_COMP)
    if run not in E7_RUNS:
        COMP["e"]["steps"] = COMP["e"]["steps"][:6]
    mode, comps, ab = RUNS[run]
    d = f"{OUT}/{run}"
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    specs = ab != "checks-only"
    # ---- base (architecture spec + baseline checks) and tools: in every run (base.md is a spec file: not in run 4)
    if specs:
        shutil.copy(f"{SRC}/common/base.md", f"{d}/base/base.md") if os.makedirs(f"{d}/base", exist_ok=True) is None else None
    bd = f"{d}/base/checks"
    os.makedirs(bd, exist_ok=True)
    w(f"{bd}/lib.sh", LIB_SH.format(mode=mode))
    shutil.copy(f"{SRC}/common/checks/lib.py", f"{bd}/lib.py")
    shutil.copy(f"{SRC}/common/checks/base_checks.py", f"{bd}/base_checks.py")
    w(f"{bd}/check_base.sh", WRAP.format(doc="Baseline rules 0.1-0.13 (milestone 0 conditions and the basics)", py="base_checks.py", arg=""), True)
    os.makedirs(f"{d}/tools", exist_ok=True)
    shutil.copy(f"{SRC}/common/tools/restart.py", f"{d}/tools/restart.py")
    w(f"{d}/tools/restart.sh", "#!/usr/bin/env bash\n# Restart the cluster with your latest code. See /spec/tools/restart.py for details.\n"
      'PY=/opt/test-venv/bin/python; [ -x "$PY" ] || PY=python3\nexec timeout 22 "$PY" /spec/tools/restart.py "$@"\n', True)

    # ---- A and B
    ab_comps = []
    if ab in ("regression", "regression+specs"):
        rd = f"{d}/checks"
        os.makedirs(rd, exist_ok=True)
        w(f"{rd}/lib.sh", LIB_SH.format(mode="verbose"))
        shutil.copy(f"{SRC}/common/checks/lib.py", f"{rd}/lib.py")
        shutil.copy(f"{SRC}/common/checks/base_checks.py", f"{rd}/base_checks.py")
        shutil.copy(f"{SRC}/roles/roles_checks.py", f"{rd}/roles_checks.py")
        shutil.copy(f"{SRC}/channels/channels_checks.py", f"{rd}/channels_checks.py")
        w(f"{rd}/regression.py", REG_PY)
        w(f"{rd}/regression.sh", REG_SH, True)
        if ab == "regression+specs":
            for c in ("a", "b"):
                write_component(d, c, mode, True, False)
            ab_comps = ["a", "b"]
    elif ab == "plain":
        for c in ("a", "b"):
            write_component(d, c, mode, True, True)
        ab_comps = ["a", "b"]
    for c in comps:
        write_component(d, c, mode, specs, True)

    w(f"{d}/README.md", readme(run, d, mode, comps, ab, ab_comps, specs))
    w(f"{d}/.version", f"{VERSION} run={run} feedback={mode}\n")


# ------------------------------------------------------------------ README
NAMES = {"a": "Spec A (roles and invitations)", "b": "Spec B (channels and message history)",
         "c": "Spec C (features built on messages: reactions, DMs, files, slash commands, groups and mentions, profiles)",
         "d": "Spec D (cluster robustness: a killed node, a killed Redis, delivery under load)",
         "e": "Spec E (message edit/delete, the IRC gateway, the web UI)"}


def readme(run, d, mode, comps, ab, ab_comps, specs):
    whole = ab is not None and ab != "checks-only"
    t = []
    t.append("# Read this first: what to build in this run, in what order, and when to submit\n")
    if whole:
        what = "the whole app: the cluster base, Components A and B, and Components C, D and E"
    else:
        parts = [f"{COMP[c]['name']} ({COMP[c]['title']})" for c in comps]
        what = "the cluster base and the basics, plus " + (f"Component {parts[0]}" if len(parts) == 1 else
                                                            "Components " + ", ".join(parts[:-1]) + " and " + parts[-1])
    t.append(f"This run builds {what}, from an empty `/app`. The task description you were given is still the "
             "grading contract; the files in `/spec` tell you **exactly** what to build now, in what order, and how to "
             "prove it works with real requests.\n")
    t.append("**Do not edit, move or delete anything in `/spec`.** Fix your code in `/app`, never a check.\n")

    # ---- files
    t.append("## Files in /spec\n")
    t.append("| File | What it is |\n|---|---|")
    t.append("| `README.md` | This file |")
    if specs:
        t.append("| `base/base.md` | **Read second.** The architecture you must use, `start.sh`, events, API and paging conventions, the basics, baseline rules 0.1-0.13 |")
    t.append(f"| `base/checks/check_base.sh` | Checks the baseline rules 0.1-0.13 (milestone 0 conditions and the basics) |")
    t.append("| `tools/restart.sh` | Restarts the cluster with your new code (`--full` after editing `start.sh`) |")
    if ab in ("regression", "regression+specs"):
        t.append("| `checks/regression.sh` | The A and B regression suite: every base, Spec A and Spec B rule in one command; prints what broke and `REGRESSION: <n> broken` |")
    for c in ab_comps + comps:
        C = COMP[c]
        has_checks = not (c in ("a", "b") and ab == "regression+specs")
        for n in range(1, len(C["steps"]) + 1):
            if specs:
                t.append(f"| `{step_file(c, n)}` | {C['name']}.{n}: {C['steps'][n - 1][1]} (rules {rule_range(c, n)}) |")
            if has_checks:
                t.append(f"| `{c}/checks/check_{c}_{n}.sh` | Checks rules {rule_range(c, n)} |")
            if specs and c == "e" and n == 4:
                t.append("| `e/ui/index.html`, `e/ui/style.css` | Starter files for the web UI (E.4 says how to use them) |")
    t.append("| `*/checks/lib.sh`, `*/checks/*.py`, `tools/restart.py` | Helpers used by the scripts above. The `*_checks.py` files hold the exact requests each check sends; read one only if a check's output is not enough to fix a failure |")
    t.append("")

    # ---- scope
    t.append("## Scope\n")
    if whole:
        t.append("Build everything: the base, Components A and B (users, workspaces, roles, invitations, channels, "
                 "messages, threads, pins, search, mentions, read state, WebSocket events), then C, D and E. "
                 "Do not build anything the task description does not ask for.\n")
    else:
        basics = ("the basics in `base/base.md` section 8" if specs else
                  "the basics these components depend on, as the task description defines them: register/login/me, "
                  "workspaces, channels (create, join, topic, archive), messages (post, list, threads), read state and "
                  "WebSocket subscribe/resume")
        t.append(f"Build the base and **only** {basics}, then the component(s) of this run. Do **not** build the rest of "
                 "Components A and B (roles management, invitations, pins, search and so on) or any component not "
                 "named above.\n")
    t.append("Pieces shared between components: IRC bridging that must keep working while a node is killed is built "
             "and checked in E.3 (Spec E), not in D. The web UI's reactions (E.6) use the two reaction routes of C.1; "
             "when Spec C is not part of this run, E.6 tells you to build just those two routes.\n")

    # ---- reading
    if specs:
        rels = ["base/base.md"] + [step_file(c, n) for c in ab_comps + comps for n in range(1, len(COMP[c]["steps"]) + 1)]
        t.append("## Reading the spec\n")
        t.append("Your command output is cut off after 10,000 characters, so read each spec file with exactly these "
                 "commands, **one command per step**. Read `base/base.md` first, and each step's file when you reach that step:\n")
        t.append("```bash\n" + "\n".join(read_cmds(d, rels)) + "\n```\n")
    else:
        t.append("## The checks are the specification\n")
        t.append("This run has no written spec files. Each check prints, for every rule, the request it sent, what it "
                 "expected and what came back. Use the task description and the check output to decide what to build. "
                 "Every check starts the cluster with `/app/start.sh` if nothing answers on ports 8000-8002.\n")

    # ---- order of work
    t.append("## Order of work\n")
    order = []
    if specs:
        order.append("Build the base from `base/base.md`: `requirements.txt`, `start.sh`, `db.py`, `common.py`, `server.py` with "
                     "`/api/health`" + (", then the basics of section 8" if not whole else "") +
                     ". Start the cluster with `bash /spec/tools/restart.sh`. Run `bash /spec/base/checks/check_base.sh` " +
                     ("until it reports `0 failed`." if not whole else "until rules 0.1-0.8 pass (0.9-0.13 pass once the A and B steps below are built)."))
    else:
        order.append("Build `/app/start.sh` (it must stay in the foreground and keep three HTTP nodes on 8000-8002, Redis on 6379 "
                     "and, later, the IRC gateway on 6667 running, restarting any of them that dies) and the basics. Start the "
                     "cluster with `bash /spec/tools/restart.sh`. Run `bash /spec/base/checks/check_base.sh` until it reports `0 failed`.")
    if ab in ("regression", "regression+specs"):
        if ab == "regression":
            order.append("Build Components A and B from the task description until `bash /spec/checks/regression.sh` reports "
                         "`REGRESSION: 0 broken`. Its output names each broken rule, the request, the expected and the actual result.")
        else:
            order.append("Build Spec A (`a/a-1-...` to `a/a-4-...`) and then Spec B (`b/b-1-...` to `b/b-5-...`), one step at a "
                         "time, until `bash /spec/checks/regression.sh` reports `REGRESSION: 0 broken`. Run the suite after every step.")
    for c in ab_comps if ab == "plain" else []:
        for n in range(1, len(COMP[c]["steps"]) + 1):
            order.append(f"Read `/spec/{step_file(c, n)}`, build it, restart, run `{check_cmd(c, n)}` until it reports `0 failed`.")
    for c in comps:
        for n in range(1, len(COMP[c]["steps"]) + 1):
            if specs:
                order.append(f"Read `/spec/{step_file(c, n)}`, build it, restart, run `{check_cmd(c, n)}` until it reports `0 failed`.")
            else:
                order.append(f"Make `{check_cmd(c, n)}` report `0 failed` (restart after every code change).")
    if ab in ("regression", "regression+specs"):
        order.append("Rerun every check of C, D and E once more, one command each, and fix what fails.")
    else:
        order.append("Rerun every check once more, one command each, and fix what fails.")
    for i, s in enumerate(order, 1):
        t.append(f"{i}. {s}")
    t.append("")
    if ab in ("regression", "regression+specs"):
        t.append("**After every step above (every C, D and E step too), run `bash /spec/checks/regression.sh` and fix anything "
                 "it reports before you move on.** New code can break rules that already passed (for example, `@here` adds to "
                 "the same `mentions` list as `@username`).\n")
    t.append("Do not move on while a rule of the current step fails, unless you have tried to fix it three times: then "
             "move on and come back at the end.\n")

    # ---- time
    t.append("## Time plan (50 minutes in total)\n")
    t.append("You cannot see a clock. Run `bash /app/timer.sh` at the start of every step; it prints the time left.\n")
    t.append("| Time left | Be working on |\n|---|---|")
    if whole:
        rows = [("50 -> 42", "base, A"), ("42 -> 34", "B"), ("34 -> 24", "C"), ("24 -> 20", "D"), ("20 -> 5", "E"),
                ("5 -> 0", "stop building; final checks; submit")]
    elif len(comps) == 3:
        rows = [("50 -> 45", "base and the basics"), ("45 -> 31", "C"), ("31 -> 26", "D"), ("26 -> 5", "E"),
                ("5 -> 0", "stop building; final checks; submit")]
    else:
        c = comps[0]
        rows = [("50 -> 42", "base and the basics"), ("42 -> 8", f"{COMP[c]['name']}.1 to {COMP[c]['name']}.{len(COMP[c]['steps'])}"),
                ("8 -> 3", "fix every remaining failure"), ("3 -> 0", "final checks; submit")]
    for a, b in rows:
        t.append(f"| {a} | {b} |")
    t.append("")

    # ---- how to work
    t.append("## How to work (each of these has wasted whole runs before)\n")
    t.append("- **One command block per reply.** Never put two command blocks in one reply.")
    t.append("- **One file per step.** Write each `/app/*.py` file with its own `cat > /app/x.py <<'EOF'` heredoc. To change "
             "a file, rewrite that whole file or use a short `python3` edit script; keep each file under ~250 lines.")
    t.append("- **After every code change:** `bash /spec/tools/restart.sh && bash <the check of this step>` as one command. "
             "If restart prints `RESTART FAILED`, run `tail -30 /tmp/node0.log` (or the log your `start.sh` writes) to see the error.")
    t.append("- **Start and restart the cluster only with `bash /spec/tools/restart.sh`.** Never run `/app/start.sh` yourself, "
             "not even with `&` or `nohup`: a background process that keeps your command's output open freezes your command forever.")
    t.append("- **Never kill by name**: no `pkill`, `killall`, `pgrep -f`, `kill` on a name, or parsing `ps`; that can kill you "
             "(the agent). Only kill a PID that owns a port (`ss -ltnp`) or a PID you saved yourself.")
    t.append("- Any process you start by hand for a quick test must have all output redirected: `cmd >/tmp/x.log 2>&1 </dev/null &`.")
    t.append("- Every command is cut off after 30 seconds. Every check finishes in under 30 seconds and starts the cluster itself if it is down.")
    t.append("- Keep `/app` working at all times: a half-finished feature must not break `start.sh` or earlier rules.")
    t.append("- Your database survives restarts, so a check can pass only because of data an earlier step created. When you "
             "finish a component, run `bash /spec/tools/restart.sh --full --fresh` (empty database) and that component's checks once more.\n")

    # ---- verify
    t.append("## How to verify\n")
    t.append("Each check tests its rules against the running cluster with real requests and ends with one line, for example\n")
    t.append("```text\nRESULT: 6 passed, 0 failed\n```\n")
    if ab in ("regression", "regression+specs"):
        t.append("The regression suite ends with `REGRESSION: <n> broken`; `REGRESSION: 0 broken` means every A and B rule still holds.\n")

    # ---- submit
    final = ["bash /spec/base/checks/check_base.sh"]
    if ab in ("regression", "regression+specs"):
        final.append("bash /spec/checks/regression.sh")
    for c in (ab_comps if ab == "plain" else []) + comps:
        for n in range(1, len(COMP[c]["steps"]) + 1):
            final.append(check_cmd(c, n))
    t.append("## Before you submit\n")
    t.append("You may run `echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT` only after, in output you actually saw:\n")
    t.append("1. `bash /spec/tools/restart.sh --full --fresh` printed `RESTART OK` (this restarts from an **empty database**, "
             "the way the graders start; a table created only inside a request handler shows up here), then each of these ran, "
             "one command each:\n")
    t.append("```bash\n" + "\n".join(final) + "\n```\n")
    t.append("2. every one of them ended with `0 failed`" + (" (the regression suite with `REGRESSION: 0 broken`)" if ab in ("regression", "regression+specs") else "")
             + ", **or** `bash /app/timer.sh` shows `0:05` or less.\n")
    t.append("If the timer shows `0:05` or less, stop building: make sure `check_base.sh` still reports `0 failed` (the cluster "
             "must boot from `/app/start.sh`), then submit. Submitting late is worse than submitting with a few failures.\n")
    t.append("These checks are necessary, not sufficient: the grading contract in the task description still applies to everything you built.\n")
    return "\n".join(t)


if __name__ == "__main__":
    for r in RUNS:
        build(r)
    print("built", sorted(os.listdir(OUT)))
