# Read this first: what to build in this run, in what order, and when to submit

This run builds the whole app: the cluster base, Components A and B, and Components C, D and E, from an empty `/app`. The task description you were given is still the grading contract; the files in `/spec` tell you **exactly** what to build now, in what order, and how to prove it works with real requests.

**Do not edit, move or delete anything in `/spec`.** Fix your code in `/app`, never a check.

## Files in /spec

| File | What it is |
|---|---|
| `README.md` | This file |
| `base/base.md` | **Read second.** The architecture you must use, `start.sh`, events, API and paging conventions, the basics, baseline rules 0.1-0.13 |
| `base/checks/check_base.sh` | Checks the baseline rules 0.1-0.13 (milestone 0 conditions and the basics) |
| `tools/restart.sh` | Restarts the cluster with your new code (`--full` after editing `start.sh`) |
| `checks/regression.sh` | The A and B regression suite: every base, Spec A and Spec B rule in one command; prints what broke and `REGRESSION: <n> broken` |
| `c/c-1-reactions.md` | C.1: Reactions (rules C1.1-C1.6) |
| `c/checks/check_c_1.sh` | Checks rules C1.1-C1.6 |
| `c/c-2-dms.md` | C.2: Direct messages (rules C2.1-C2.5) |
| `c/checks/check_c_2.sh` | Checks rules C2.1-C2.5 |
| `c/c-3-files.md` | C.3: Files (rules C3.1-C3.5) |
| `c/checks/check_c_3.sh` | Checks rules C3.1-C3.5 |
| `c/c-4-slash.md` | C.4: Slash commands (rules C4.1-C4.6) |
| `c/checks/check_c_4.sh` | Checks rules C4.1-C4.6 |
| `c/c-5-groups-mentions.md` | C.5: User groups, @group and @here (rules C5.1-C5.5) |
| `c/checks/check_c_5.sh` | Checks rules C5.1-C5.5 |
| `c/c-6-profiles.md` | C.6: Profiles (rules C6.1-C6.4) |
| `c/checks/check_c_6.sh` | Checks rules C6.1-C6.4 |
| `d/d-1-node-kill.md` | D.1: A killed HTTP node (rules D1.1-D1.4) |
| `d/checks/check_d_1.sh` | Checks rules D1.1-D1.4 |
| `d/d-2-redis-kill.md` | D.2: A killed Redis (rules D2.1-D2.4) |
| `d/checks/check_d_2.sh` | Checks rules D2.1-D2.4 |
| `d/d-3-load.md` | D.3: WebSocket delivery under load (rules D3.1-D3.3) |
| `d/checks/check_d_3.sh` | Checks rules D3.1-D3.3 |
| `e/e-1-edit-delete.md` | E.1: Message edit and delete (rules E1.1-E1.5) |
| `e/checks/check_e_1.sh` | Checks rules E1.1-E1.5 |
| `e/e-2-irc-register.md` | E.2: IRC: connection and registration (rules E2.1-E2.5) |
| `e/checks/check_e_2.sh` | Checks rules E2.1-E2.5 |
| `e/e-3-irc-channels.md` | E.3: IRC: channels and bridging (rules E3.1-E3.6) |
| `e/checks/check_e_3.sh` | Checks rules E3.1-E3.6 |
| `e/e-4-ui-page.md` | E.4: Web UI: served page and pinned hooks (rules E4.1-E4.5) |
| `e/checks/check_e_4.sh` | Checks rules E4.1-E4.5 |
| `e/ui/index.html`, `e/ui/style.css` | Starter files for the web UI (E.4 says how to use them) |
| `e/e-5-ui-auth-channels.md` | E.5: Web UI: sign-up, login, workspace, channels (rules E5.1-E5.7) |
| `e/checks/check_e_5.sh` | Checks rules E5.1-E5.7 |
| `e/e-6-ui-messages.md` | E.6: Web UI: messages, threads, reactions, logout (rules E6.1-E6.7) |
| `e/checks/check_e_6.sh` | Checks rules E6.1-E6.7 |
| `e/e-7-ui-settings.md` | E.7: Web UI: workspace settings, invitations, joining, channel settings (rules E7.1-E7.6) |
| `e/checks/check_e_7.sh` | Checks rules E7.1-E7.6 |
| `*/checks/lib.sh`, `*/checks/*.py`, `tools/restart.py` | Helpers used by the scripts above. The `*_checks.py` files hold the exact requests each check sends; read one only if a check's output is not enough to fix a failure |

## Scope

Build everything: the base, Components A and B (users, workspaces, roles, invitations, channels, messages, threads, pins, search, mentions, read state, WebSocket events), then C, D and E. Do not build anything the task description does not ask for.

Pieces shared between components: IRC bridging that must keep working while a node is killed is built and checked in E.3 (Spec E), not in D. The web UI's reactions (E.6) use the two reaction routes of C.1; when Spec C is not part of this run, E.6 tells you to build just those two routes.

## Reading the spec

Your command output is cut off after 10,000 characters, so read each spec file with exactly these commands, **one command per step**. Read `base/base.md` first, and each step's file when you reach that step:

```bash
sed -n '1,126p' /spec/base/base.md
sed -n '127,232p' /spec/base/base.md
sed -n '233,257p' /spec/base/base.md
cat /spec/c/c-1-reactions.md
cat /spec/c/c-2-dms.md
cat /spec/c/c-3-files.md
cat /spec/c/c-4-slash.md
cat /spec/c/c-5-groups-mentions.md
cat /spec/c/c-6-profiles.md
cat /spec/d/d-1-node-kill.md
cat /spec/d/d-2-redis-kill.md
cat /spec/d/d-3-load.md
cat /spec/e/e-1-edit-delete.md
cat /spec/e/e-2-irc-register.md
cat /spec/e/e-3-irc-channels.md
cat /spec/e/e-4-ui-page.md
cat /spec/e/e-5-ui-auth-channels.md
cat /spec/e/e-6-ui-messages.md
cat /spec/e/e-7-ui-settings.md
```

## Order of work

1. Build the base from `base/base.md`: `requirements.txt`, `start.sh`, `db.py`, `common.py`, `server.py` with `/api/health`. Start the cluster with `bash /spec/tools/restart.sh`. Run `bash /spec/base/checks/check_base.sh` until rules 0.1-0.8 pass (0.9-0.13 pass once the A and B steps below are built).
2. Build Components A and B from the task description until `bash /spec/checks/regression.sh` reports `REGRESSION: 0 broken`. Its output names each broken rule, the request, the expected and the actual result.
3. Read `/spec/c/c-1-reactions.md`, build it, restart, run `bash /spec/c/checks/check_c_1.sh` until it reports `0 failed`.
4. Read `/spec/c/c-2-dms.md`, build it, restart, run `bash /spec/c/checks/check_c_2.sh` until it reports `0 failed`.
5. Read `/spec/c/c-3-files.md`, build it, restart, run `bash /spec/c/checks/check_c_3.sh` until it reports `0 failed`.
6. Read `/spec/c/c-4-slash.md`, build it, restart, run `bash /spec/c/checks/check_c_4.sh` until it reports `0 failed`.
7. Read `/spec/c/c-5-groups-mentions.md`, build it, restart, run `bash /spec/c/checks/check_c_5.sh` until it reports `0 failed`.
8. Read `/spec/c/c-6-profiles.md`, build it, restart, run `bash /spec/c/checks/check_c_6.sh` until it reports `0 failed`.
9. Read `/spec/d/d-1-node-kill.md`, build it, restart, run `bash /spec/d/checks/check_d_1.sh` until it reports `0 failed`.
10. Read `/spec/d/d-2-redis-kill.md`, build it, restart, run `bash /spec/d/checks/check_d_2.sh` until it reports `0 failed`.
11. Read `/spec/d/d-3-load.md`, build it, restart, run `bash /spec/d/checks/check_d_3.sh` until it reports `0 failed`.
12. Read `/spec/e/e-1-edit-delete.md`, build it, restart, run `bash /spec/e/checks/check_e_1.sh` until it reports `0 failed`.
13. Read `/spec/e/e-2-irc-register.md`, build it, restart, run `bash /spec/e/checks/check_e_2.sh` until it reports `0 failed`.
14. Read `/spec/e/e-3-irc-channels.md`, build it, restart, run `bash /spec/e/checks/check_e_3.sh` until it reports `0 failed`.
15. Read `/spec/e/e-4-ui-page.md`, build it, restart, run `bash /spec/e/checks/check_e_4.sh` until it reports `0 failed`.
16. Read `/spec/e/e-5-ui-auth-channels.md`, build it, restart, run `bash /spec/e/checks/check_e_5.sh` until it reports `0 failed`.
17. Read `/spec/e/e-6-ui-messages.md`, build it, restart, run `bash /spec/e/checks/check_e_6.sh` until it reports `0 failed`.
18. Read `/spec/e/e-7-ui-settings.md`, build it, restart, run `bash /spec/e/checks/check_e_7.sh` until it reports `0 failed`.
19. Rerun every check of C, D and E once more, one command each, and fix what fails.

**After every step above (every C, D and E step too), run `bash /spec/checks/regression.sh` and fix anything it reports before you move on.** New code can break rules that already passed (for example, `@here` adds to the same `mentions` list as `@username`).

Do not move on while a rule of the current step fails, unless you have tried to fix it three times: then move on and come back at the end.

## Time plan (50 minutes in total)

You cannot see a clock. Run `bash /app/timer.sh` at the start of every step; it prints the time left.

| Time left | Be working on |
|---|---|
| 50 -> 42 | base, A |
| 42 -> 34 | B |
| 34 -> 24 | C |
| 24 -> 20 | D |
| 20 -> 5 | E |
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

The regression suite ends with `REGRESSION: <n> broken`; `REGRESSION: 0 broken` means every A and B rule still holds.

## Before you submit

You may run `echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT` only after, in output you actually saw:

1. `bash /spec/tools/restart.sh --full --fresh` printed `RESTART OK` (this restarts from an **empty database**, the way the graders start; a table created only inside a request handler shows up here), then each of these ran, one command each:

```bash
bash /spec/base/checks/check_base.sh
bash /spec/checks/regression.sh
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
bash /spec/e/checks/check_e_7.sh
```

2. every one of them ended with `0 failed` (the regression suite with `REGRESSION: 0 broken`), **or** `bash /app/timer.sh` shows `0:05` or less.

If the timer shows `0:05` or less, stop building: make sure `check_base.sh` still reports `0 failed` (the cluster must boot from `/app/start.sh`), then submit. Submitting late is worse than submitting with a few failures.

These checks are necessary, not sufficient: the grading contract in the task description still applies to everything you built.
