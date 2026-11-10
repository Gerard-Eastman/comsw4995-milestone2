# Read this first: what to build in this run, in what order, and when to submit

This run builds the cluster base and the basics, plus Components C (features built on messages), D (cluster robustness) and E (IRC, web UI and message edits), from an empty `/app`. The task description you were given is still the grading contract; the files in `/spec` tell you **exactly** what to build now, in what order, and how to prove it works with real requests.

**Do not edit, move or delete anything in `/spec`.** Fix your code in `/app`, never a check.

## Files in /spec

| File | What it is |
|---|---|
| `README.md` | This file |
| `base/checks/check_base.sh` | Checks the baseline rules 0.1-0.13 (milestone 0 conditions and the basics) |
| `tools/restart.sh` | Restarts the cluster with your new code (`--full` after editing `start.sh`) |
| `c/checks/check_c_1.sh` | Checks rules C1.1-C1.6 |
| `c/checks/check_c_2.sh` | Checks rules C2.1-C2.5 |
| `c/checks/check_c_3.sh` | Checks rules C3.1-C3.5 |
| `c/checks/check_c_4.sh` | Checks rules C4.1-C4.6 |
| `c/checks/check_c_5.sh` | Checks rules C5.1-C5.5 |
| `c/checks/check_c_6.sh` | Checks rules C6.1-C6.4 |
| `d/checks/check_d_1.sh` | Checks rules D1.1-D1.4 |
| `d/checks/check_d_2.sh` | Checks rules D2.1-D2.4 |
| `d/checks/check_d_3.sh` | Checks rules D3.1-D3.3 |
| `e/checks/check_e_1.sh` | Checks rules E1.1-E1.5 |
| `e/checks/check_e_2.sh` | Checks rules E2.1-E2.5 |
| `e/checks/check_e_3.sh` | Checks rules E3.1-E3.6 |
| `e/checks/check_e_4.sh` | Checks rules E4.1-E4.5 |
| `e/checks/check_e_5.sh` | Checks rules E5.1-E5.7 |
| `e/checks/check_e_6.sh` | Checks rules E6.1-E6.7 |
| `*/checks/lib.sh`, `*/checks/*.py`, `tools/restart.py` | Helpers used by the scripts above. The `*_checks.py` files hold the exact requests each check sends; read one only if a check's output is not enough to fix a failure |

## Scope

Build the base and **only** the basics these components depend on, as the task description defines them: register/login/me, workspaces, channels (create, join, topic, archive), messages (post, list, threads), read state and WebSocket subscribe/resume, then the component(s) of this run. Do **not** build the rest of Components A and B (roles management, invitations, pins, search and so on) or any component not named above.

Pieces shared between components: IRC bridging that must keep working while a node is killed is built and checked in E.3 (Spec E), not in D. The web UI's reactions (E.6) use the two reaction routes of C.1; when Spec C is not part of this run, E.6 tells you to build just those two routes.

## The checks are the specification

This run has no written spec files. Each check prints, for every rule, the request it sent, what it expected and what came back. Use the task description and the check output to decide what to build. Every check starts the cluster with `/app/start.sh` if nothing answers on ports 8000-8002.

## Order of work

1. Build `/app/start.sh` (it must stay in the foreground and keep three HTTP nodes on 8000-8002, Redis on 6379 and, later, the IRC gateway on 6667 running, restarting any of them that dies) and the basics. Start the cluster with `bash /spec/tools/restart.sh`. Run `bash /spec/base/checks/check_base.sh` until it reports `0 failed`.
2. Make `bash /spec/c/checks/check_c_1.sh` report `0 failed` (restart after every code change).
3. Make `bash /spec/c/checks/check_c_2.sh` report `0 failed` (restart after every code change).
4. Make `bash /spec/c/checks/check_c_3.sh` report `0 failed` (restart after every code change).
5. Make `bash /spec/c/checks/check_c_4.sh` report `0 failed` (restart after every code change).
6. Make `bash /spec/c/checks/check_c_5.sh` report `0 failed` (restart after every code change).
7. Make `bash /spec/c/checks/check_c_6.sh` report `0 failed` (restart after every code change).
8. Make `bash /spec/d/checks/check_d_1.sh` report `0 failed` (restart after every code change).
9. Make `bash /spec/d/checks/check_d_2.sh` report `0 failed` (restart after every code change).
10. Make `bash /spec/d/checks/check_d_3.sh` report `0 failed` (restart after every code change).
11. Make `bash /spec/e/checks/check_e_1.sh` report `0 failed` (restart after every code change).
12. Make `bash /spec/e/checks/check_e_2.sh` report `0 failed` (restart after every code change).
13. Make `bash /spec/e/checks/check_e_3.sh` report `0 failed` (restart after every code change).
14. Make `bash /spec/e/checks/check_e_4.sh` report `0 failed` (restart after every code change).
15. Make `bash /spec/e/checks/check_e_5.sh` report `0 failed` (restart after every code change).
16. Make `bash /spec/e/checks/check_e_6.sh` report `0 failed` (restart after every code change).
17. Rerun every check once more, one command each, and fix what fails.

Do not move on while a rule of the current step fails, unless you have tried to fix it three times: then move on and come back at the end.

## Time plan (50 minutes in total)

You cannot see a clock. Run `bash /app/timer.sh` at the start of every step; it prints the time left.

| Time left | Be working on |
|---|---|
| 50 -> 45 | base and the basics |
| 45 -> 31 | C |
| 31 -> 26 | D |
| 26 -> 5 | E |
| 5 -> 0 | stop building; final checks; submit |

## How to work (each of these has wasted whole runs before)

- **One command block per reply.** Never put two command blocks in one reply.
- **One file per step.** Write each `/app/*.py` file with its own `cat > /app/x.py <<'EOF'` heredoc. To change a file, rewrite that whole file or use a short `python3` edit script; keep each file under ~250 lines.
- **After every code change:** `bash /spec/tools/restart.sh && bash <the check of this step>` as one command. If restart prints `RESTART FAILED`, run `tail -30 /tmp/node0.log` (or the log your `start.sh` writes) to see the error.
- **Start and restart the cluster only with `bash /spec/tools/restart.sh`.** Never run `/app/start.sh` yourself, not even with `&` or `nohup`: a background process that keeps your command's output open freezes your command forever.
- **Never kill by name**: no `pkill`, `killall`, `pgrep -f`, `kill` on a name, or parsing `ps`; that can kill you (the agent). Only kill a PID that owns a port (`ss -ltnp`) or a PID you saved yourself.
- Any process you start by hand for a quick test must have all output redirected: `cmd >/tmp/x.log 2>&1 </dev/null &`.
- Every command is cut off after 30 seconds. Every check finishes in under 30 seconds and starts the cluster itself if it is down.
- Keep `/app` working at all times: a half-finished feature must not break `start.sh` or earlier rules.
- Your database survives restarts, so a check can pass only because of data an earlier step created. When you finish a component, run `bash /spec/tools/restart.sh --full --fresh` (empty database) and that component's checks once more.

## How to verify

Each check tests its rules against the running cluster with real requests and ends with one line, for example

```text
RESULT: 6 passed, 0 failed
```

## Before you submit

You may run `echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT` only after, in output you actually saw:

1. `bash /spec/tools/restart.sh --full --fresh` printed `RESTART OK` (this restarts from an **empty database**, the way the graders start; a table created only inside a request handler shows up here), then each of these ran, one command each:

```bash
bash /spec/base/checks/check_base.sh
bash /spec/c/checks/check_c_1.sh
bash /spec/c/checks/check_c_2.sh
bash /spec/c/checks/check_c_3.sh
bash /spec/c/checks/check_c_4.sh
bash /spec/c/checks/check_c_5.sh
bash /spec/c/checks/check_c_6.sh
bash /spec/d/checks/check_d_1.sh
bash /spec/d/checks/check_d_2.sh
bash /spec/d/checks/check_d_3.sh
bash /spec/e/checks/check_e_1.sh
bash /spec/e/checks/check_e_2.sh
bash /spec/e/checks/check_e_3.sh
bash /spec/e/checks/check_e_4.sh
bash /spec/e/checks/check_e_5.sh
bash /spec/e/checks/check_e_6.sh
```

2. every one of them ended with `0 failed`, **or** `bash /app/timer.sh` shows `0:05` or less.

If the timer shows `0:05` or less, stop building: make sure `check_base.sh` still reports `0 failed` (the cluster must boot from `/app/start.sh`), then submit. Submitting late is worse than submitting with a few failures.

These checks are necessary, not sufficient: the grading contract in the task description still applies to everything you built.
