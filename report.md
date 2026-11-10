# Milestone 2 report

- Name: Gerard Eastman IV
- UNI: gle2107

All results are from my own checks.

## Runs

One row per repeat of each run (22 in total). "Run" is the run in the run plan in README Setup. "Check results" are my re-runs of that run's checks on the agent's final `/app`, starting from an empty database (see "How I ran and scored the experiments" below). Job folders are under `tasks/slack-clone-course/jobs/`. Practice runs, runs that never got past setup, and the runs started with the wrong spec are kept in `tasks/slack-clone-course/jobs-other/` (listed at the end).

| Run | Component | Repeat | Job folder | Check results | Cost | Ran checks (times) | Submitted with failures? | Problems |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1.1 | C | 1 | `jobs/2026-11-09__18-45-32` | base: 13 passed, 0 failed; C: 31 passed, 0 failed | $0.47 | 29 | no | got around score-only output 8 times (ran the checker's Python directly, which defaulted to verbose) |
| 1.1 | C | 2 | `jobs/2026-11-09__18-45-52` | base: 13 passed, 0 failed; C: 31 passed, 0 failed | $0.40 | 27 | no (its last base run, done through the checker's Python, was 13/13) | got around score-only output 3 times (FEEDBACK=verbose on the checker's Python) |
| 1.2 | D | 1 | `jobs/2026-11-09__18-53-06` | base: 13 passed, 0 failed; D: 11 passed, 0 failed | $0.58 | 13 | no | got around score-only output 2 times |
| 1.2 | D | 2 | `jobs/2026-11-09__18-53-27` | base: 13 passed, 0 failed; D: 11 passed, 0 failed | $0.12 | 11 | no | none |
| 1.3 | E | 1 | `jobs/2026-11-09__19-03-08` | base: 13 passed, 0 failed; E (E.1-E.6): 35 passed, 0 failed | $1.13 | 43 | no | got around score-only output 6 times; 1 command timeout |
| 1.3 | E | 2 | `jobs/2026-11-09__19-03-28` | base: 13 passed, 0 failed; E (E.1-E.6): 34 passed, 1 failed | $0.60 | 23 | no | got around score-only output 15 times; E3.6 (IRC bridging during a node kill) flaky in my reruns: failed 1 of 5 |
| 2.1 | C | 1 | `jobs/2026-11-09__19-17-33` | base: 13 passed, 0 failed; C: 31 passed, 0 failed | $0.82 | 27 | no | none |
| 2.1 | C | 2 | `jobs/2026-11-09__19-17-53` | base: 13 passed, 0 failed; C: 31 passed, 0 failed | $0.39 | 24 | no | pip install of aiohttp hit the 30 s command limit; agent pointed start.sh at /opt/cua-venv's Python (already has aiohttp) |
| 2.2 | D | 1 | `jobs/2026-11-09__19-35-42` | base: 13 passed, 0 failed; D: 11 passed, 0 failed | $0.25 | 11 | no | none |
| 2.2 | D | 2 | `jobs/2026-11-09__19-36-02` | base: 13 passed, 0 failed; D: 11 passed, 0 failed | $0.15 | 11 | no | none |
| 2.3 | E | 1 | `jobs/2026-11-10__00-00-58` | base: 13 passed, 0 failed; E (E.1-E.6): 35 passed, 0 failed | $0.52 | 27 | no | earlier attempts of 2.3 died in setup (network/VPN); 6 command timeouts |
| 2.3 | E | 2 | `jobs/2026-11-10__00-01-18` | base: 13 passed, 0 failed; E (E.1-E.6): 35 passed, 0 failed | $0.78 | 38 | no | earlier attempts of 2.3 died in setup (network/VPN); 5 command timeouts |
| 3 | C, D, E | 1 | `jobs/2026-11-09__20-25-23` | base: 13 passed, 0 failed; C: 31 passed, 0 failed; D: 11 passed, 0 failed; E (E.1-E.6): 35 passed, 0 failed | $1.20 | 66 | no | none |
| 3 | C, D, E | 2 | `jobs/2026-11-09__20-25-43` | base: 13 passed, 0 failed; C: 31 passed, 0 failed; D: 11 passed, 0 failed; E (E.1-E.6): 35 passed, 0 failed | $1.30 | 73 | no | none |
| 4 | C, D, E | 1 | `jobs/2026-11-09__21-20-49` | base: 13 passed, 0 failed; C: 30 passed, 1 failed; D: 11 passed, 0 failed; E (E.1-E.6): 35 passed, 0 failed | $1.36 | 75 | no | own design without base.md: DB file in /app (its --fresh restart never emptied it); 10 MiB uploads rejected (aiohttp's 1 MiB default body limit); 3 command timeouts |
| 4 | C, D, E | 2 | `jobs/2026-11-09__21-21-09` | base: 13 passed, 0 failed; C: 31 passed, 0 failed; D: 11 passed, 0 failed; E (E.1-E.6): 21 passed, 14 failed | $2.86 | 83 | yes | own http.server stack; port 6379 held by a fake 'Redis' (a socket that accepts and closes) to pass D2.1; submitted with E3/E5/E6 failing in its own checks |
| 5.1 | A to E | 1 | `jobs/2026-11-09__21-21-59` | base: 13 passed, 0 failed; A and B: 19 broken; C: 31 passed, 0 failed; D: 10 passed, 1 failed; E (E.1-E.6): 35 passed, 0 failed; E.7: 0 passed, 6 failed | $2.02 | 67 | yes | submitted with 37 A/B rules broken in its last regression run (19 on a fresh DB); E7 0/6; D1.3 resume fails |
| 5.1 | A to E | 2 | `jobs/2026-11-09__21-22-19` | base: 13 passed, 0 failed; A and B: 0 broken; C: 31 passed, 0 failed; D: 11 passed, 0 failed; E (E.1-E.6): 23 passed, 12 failed; E.7: 0 passed, 6 failed (no output from check_e_7 within 45 s, counted as failed) | $3.02 | 90 | did not submit (LimitsExceeded) | hit the $3 cost limit in E; start.sh never starts irc.py (it ran it by hand), so all IRC rules fail on a fresh boot |
| 5.2 | A to E | 1 | `jobs/2026-11-09__23-35-07` | base: 13 passed, 0 failed; A and B: 0 broken; C: 31 passed, 0 failed; D: 11 passed, 0 failed; E (E.1-E.6): 25 passed, 10 failed; E.7: 0 passed, 6 failed (no output from check_e_7 within 45 s, counted as failed) | $2.11 | 73 | yes | submitted with E.5, E.6 and E.7 failing in its own checks; regression went 4 -> 8 -> 0 broken while it was still fixing A/B, and 0 broken again at the end after E; 7 command timeouts |
| 5.2 | A to E | 2 | `jobs/2026-11-09__23-35-27` | base: 13 passed, 0 failed; A and B: 0 broken; C: 31 passed, 0 failed; D: 11 passed, 0 failed; E (E.1-E.6): 35 passed, 0 failed; E.7: 5 passed, 1 failed | $2.43 | 82 | no | regression 48 -> 20 -> 7 -> 4 -> 0 broken while building A/B, 0 again at the end; 9 command timeouts; one E.7 rule fails only on a fresh DB |
| 5.3 | A to E | 1 | `jobs/2026-11-09__23-34-36` | base: 13 passed, 0 failed; A: 32 passed, 0 failed; B: 36 passed, 0 failed; C: 31 passed, 0 failed; D: 11 passed, 0 failed; E (E.1-E.6): 33 passed, 2 failed; E.7: 4 passed, 2 failed | $2.49 | 118 | yes | its own last B.1 and B.3 runs (made while building B) still had failures it never revisited, but A and B pass on a fresh DB; 17 command timeouts; 32.6 min |
| 5.3 | A to E | 2 | `jobs/2026-11-09__23-34-56` | base: 13 passed, 0 failed; A: 32 passed, 0 failed; B: 36 passed, 0 failed; C: 31 passed, 0 failed; D: 10 passed, 1 failed; E (E.1-E.6): 35 passed, 0 failed; E.7: 5 passed, 1 failed | $3.02 | 121 | did not submit (LimitsExceeded) | hit the $3 cost limit at 35 min (E.7 done); one 500 under the D3 load test on a fresh DB; 18 command timeouts |

## How I ran and scored the experiments

- **Spec versions.** Runs 1.x, 2.x, 3 and 4 used spec `m2-v2`. The 5.x runs used `m2-v3`, which
  adds one step, **E.7 (settings UI: members and roles, invitations, joining, channel settings; 6
  rules)**. A last review against the task description showed those pinned UI hooks were
  missing. E.1–E.6 are identical in every run, so all comparisons below use E.1–E.6 (35 rules), and
  E.7 is reported separately. Rule totals: base 13 (milestone 0 conditions plus basics), A 32,
  B 36 (the A+B regression suite runs all 81 base, A and B rules), C 31, D 11, E 35, E.7 6.
- **"Check results" are my own re-runs**, not the agent's last output. I re-ran every check of that
  run (in verbose mode) on the agent's final `/app`, starting from an **empty database** in a
  clean container with Python 3.12 first on `PATH` (as in the task image). Several agents' own
  final check runs passed only because of rows left in their database by earlier steps, so this
  is the stricter and fairer number.
- **"Ran checks (times)"** counts every check script the agent invoked in its transcript.
  **"Submitted with failures?"** means a check output it saw last still had failures when it
  submitted.
- **Before freezing**, two practice runs of Run 5.3 (`m2-v1`; jobs `2026-11-09__18-05-51` and
  `__18-05-55`) both built the whole app in 16–18 minutes ($2.08, $1.35). On an empty database the
  second one failed 10 WebSocket rules: its event pump read a table that was created only on the
  first profile update. That led to the `restart.sh --full --fresh` step in the README and the
  "every table in `init_db()`" rule in `base/base.md`. The practice runs also made the UI checks
  more robust (messages are posted before the page opens; no race on the reaction chip).
- **Infrastructure problems that cost runs** (none of them is about the spec):
  - a VPN on my laptop slowed downloads to about 34 KB/s for part of the evening, so the agent
    install timed out: 2.3 (twice) and 5.2 (once) never reached the agent;
  - one 5.3 attempt got only 4 minutes, because `timer.sh` counts setup time;
  - a script bug once loaded the wrong spec into two runs.

  All of these were discarded and re-run. I also changed the course's `mini_swe_agent_local.py`
  install step (a longer download timeout, 3 retries, and skipping `apt-get` when the image already
  has the tools). That doesn't change anything the agent sees.

## Experiments

### 1) Feedback

> Do you find that adding detailed output to the checks helps the agent?

#### Runs compared and why

Run 1.x (`score_only`) against Run 2.x (`verbose`), one component at a time: 1.1 vs 2.1 (C),
1.2 vs 2.2 (D), 1.3 vs 2.3 (E). Within each pair only `FEEDBACK=` in `checks/lib.sh` differs: same
README, same spec, same checks.

#### Supporting results

| Component | Score only (1.x): result, cost, checks run | Verbose (2.x): result, cost, checks run |
|---|---|---|
| C | 31/31, 31/31 · $0.47, $0.40 · 29, 27 | 31/31, 31/31 · $0.82, $0.39 · 27, 24 |
| D | 11/11, 11/11 · $0.58, $0.12 · 13, 11 | 11/11, 11/11 · $0.25, $0.15 · 11, 11 |
| E | 35/35, 34/35 · $1.13, $0.60 · 43, 23 | 35/35, 35/35 · $0.52, $0.78 · 27, 38 |

#### Answer

On these components, detailed output did not change the end result. Every C and D repeat
reached full marks in both modes, and E scored 35/35 and 34/35 in score-only mode. The main
reason is that **the score-only condition leaked**. In 5 of the 6 score-only repeats, the agent
recovered the detailed output itself: it ran the checker's Python directly (the default mode was
verbose) or set `FEEDBACK=verbose` in front of it. That happened 8, 3, 2, 0, 6 and 15 times per
repeat. None of the verbose repeats tried to get more output. So the agent wants
the detail enough to work around its absence. Agents in both modes also read the `*_checks.py`
source to see the exact requests (1–7 times per score-only repeat, 0–9 per verbose one), so the
check source was a second channel of detail either way.

The written spec also does much of the work that verbose output would do. The spec already
states each rule's request and expected answer, so a bare `RESULT: 4 passed, 2 failed` plus the
spec was usually enough to find the bug.

#### Consistency across repeats

End results were nearly identical across repeats in both modes. The only point lost (1.3 repeat 2,
E3.6) is a timing-sensitive rule (IRC bridging while a node is killed) that failed in 1 of 5 of my
re-runs on the same code. Cost varied more between repeats than between modes ($0.12 vs $0.58
for the same D spec).

#### Other evidence

- I fixed the leak for later use: the mode now comes only from the `FEEDBACK=` line of `lib.sh`,
  never from the environment (`m2-v2b`). A clean score-only re-run of 1.1–1.3 is ready but was not
  run, for lack of time and credit, so a strict score-only result is still open.
- In the score-only E run with the most failures (1.3 repeat 2), the agent bypassed the mode 15
  times. That suggests the less obvious the component (IRC numerics, UI hooks), the more the
  agent depends on detail.

### 2) Tests as the spec

> Can the checks alone replace the written rules?

#### Runs compared and why

Run 3 (README + Specs C, D, E + their checks) against Run 4 (README + the same checks, no spec
files and no `base/base.md`). Both build C, D and E together with verbose checks, so the only
difference is whether the written rules are there.

#### Supporting results

| | Run 3, repeat 1 | Run 3, repeat 2 | Run 4, repeat 1 | Run 4, repeat 2 |
|---|---|---|---|---|
| C / D / E | 31/31 · 11/11 · 35/35 | 31/31 · 11/11 · 35/35 | **30/31** · 11/11 · 35/35 | 31/31 · 11/11 · **21/35** |
| Cost, agent minutes | $1.20, 12.6 | $1.30, 13.8 | $1.36, 17.4 | $2.86, 25.8 |
| Checks run · FAIL lines seen | 66 · 64 | 73 · 84 | 75 · 96 | 83 · 213 |
| Submitted with failures | no | no | no | yes |

#### Answer

No, not reliably. With the written rules, both repeats got every check right at about $1.25 and
13 minutes. With the checks alone, one repeat came close (one rule short), but the other missed
14 E rules: IRC bridging and most of the UI. It submitted while its own checks still showed those
failures. Checks-only runs cost 1.1–2.3× as much, took 1.3–2.0× as long, and saw 1.3–2.9× as
many failures, because the agent discovered the contract by failing against it.

More importantly, the checks-only agents built things that pass the checks but break the
contract the checks don't test:

- **A fake Redis:** repeat 2 put a Python socket that accepts and closes connections on port 6379,
  enough to pass D2.1 ("something listens on 6379"). The task requires a real local Redis pub/sub
  daemon.
- **An undocumented upload limit:** repeat 1 rejects 10 MiB uploads, because aiohttp's default body
  limit is 1 MiB. `base/base.md`, which Run 4 leaves out, sets `client_max_size=20MiB`.
- **A database the fresh restart never empties:** repeat 1 kept its database in `/app` rather
  than `/app/data`, so `restart.sh --fresh` never cleared it and its own checks never ran on an
  empty database.

The checks tell the agent *what is wrong*. The spec tells it *what to build*, including the
parts no check covers.

#### Consistency across repeats

Run 3 was perfectly consistent: same scores, cost within $0.10, time within 1.2 minutes. Run 4
was not: one repeat got 76/77 and the other 63/77, and the cost and time differed by 2×. Without
the spec, each agent designs its own architecture: repeat 2 used `http.server` threads, repeat 1
used aiohttp. How well that design fits the checks decides the outcome.

#### Other evidence

Repeat 2 of Run 4 eventually faked `?token=` login by rendering the logged-in state on the server
when the client-side script didn't work. That behaviour satisfies a selector check without
building the feature.

### 3) Scale

> Do you find that a component passes fewer of its checks when the agent builds it together with
> other components, rather than on its own?

#### Runs compared and why

C, D and E alone with spec and verbose checks (2.1, 2.2, 2.3) against together (Run 3: C+D+E) and
together with A and B (Run 5.3: A–E). All three use the same C/D/E specs and checks in the same
mode, so only the amount built in one 50-minute run changes. I also show Runs 5.1 and 5.2, which
build A–E with less help for A and B.

#### Supporting results

| Component | Alone (2.x) | C+D+E (3) | A–E (5.3) | A–E (5.1) | A–E (5.2) |
|---|---|---|---|---|---|
| C (31) | 31, 31 | 31, 31 | 31, 31 | 31, 31 | 31, 31 |
| D (11) | 11, 11 | 11, 11 | 11, 10 | 10, 11 | 11, 11 |
| E.1–E.6 (35) | 35, 35 | 35, 35 | 33, 35 | 35, 23 | 25, 35 |
| E.7 (6) | (not in run) | (not in run) | 4, 5 | 0, 0 | 0, 5 |
| Cost | C $0.82/$0.39, D $0.25/$0.15, E $0.52/$0.78 | $1.20, $1.30 | $2.49, $3.02 (hit the cap) | $2.02, $3.02 (hit the cap) | $2.11, $2.43 |

#### Answer

For C and D, no. C passed all 31 rules in every run at every scale: alone, with D and E, and in
all six whole-app repeats. D lost one rule in 2 of 6 whole-app repeats: once a single `500` among 90
concurrent posts in the load test, and once resuming after a reconnect (D1.3, in 5.1).
Its other rules always held.

**E, yes.** It is built last, so it gets whatever time and budget is left. Alone and with C+D it
passed E.1–E.6 in every repeat (35/35). In the whole-app runs it fell to 33, 23 and 25 of 35 in
3 of 6 repeats (35 in the other three). The losses were UI rules (E.5/E.6: sign-up, channel
list, message toolbar, threads) and, once, an IRC gateway that `start.sh` never started. The new
last step, E.7, passed only 4–5 of 6 even in the best repeats. The cause is budget rather than
confusion: whole-app repeats ran 17–35 minutes and $2.0–3.0, against 13 minutes and $1.25 for
C+D+E. Two of the six hit the $3 cap, and three others submitted while E checks were
still failing. So scale costs points in the last component, not in the ones
built while time was plentiful.

#### Consistency across repeats

C is consistent at every scale. D is nearly so: each loss is a single rule in one repeat.
E is consistent alone and in Run 3, but varies widely in the whole-app runs (23 to 35 of 35 across
the six repeats, and 33 vs 35 within 5.3). Whether a repeat finishes E depends on how fast it got
through A–D. 5.1 repeat 2 spent its budget rebuilding A and B and then ran out in E.

#### Other evidence

- With C+D+E, the agents did not build one step at a time as the README says: they wrote
  several steps and checked afterwards. First-try results such as E.2 0/5 and E.5 0/7 in Run 3
  show this. Even so, they finished everything in about 13 minutes.
- Cost grows with scope: $0.12–1.13 for one component, $1.25 for three, $2–3 for five. A
  single 5.x repeat can reach the $3 per-run cap (5.1 repeat 2 did, in E). So scale hurts
  through the budget before it hurts through confusion.

### 4) Regression

> a) Do you find that building components C, D, and E breaks features from A and B that were
> already working?

> b) Does it make a difference whether the agent has Specs A and B or only their regression
> tests?

> c) Does it make a difference whether the A and B checks are given as a regression suite or as
> plain checks?

#### Runs compared and why

- **5.1:** A and B only as the regression suite (no A/B spec files).
- **5.2:** Specs A and B, checked only through the regression suite.
- **5.3:** Specs A and B with their plain per-step checks (no regression suite).

All three build A–E with the same C/D/E specs and checks. For (a), I look at A and B in each
5.x run, at the end (fresh database) and in the regression output during the run. For (b), 5.1 against 5.2. For (c), 5.2 against 5.3.

#### Supporting results

| | A+B at the end (fresh DB) | A+B during the run | Cost, minutes |
|---|---|---|---|
| 5.1 repeat 1 | **19 broken** of 81 | regression 51 → 51 → 44 → 37 broken, then moved on to C–E and never re-ran it | $2.02, 16.9 |
| 5.1 repeat 2 | 0 broken | 49 → 36 → 24 → 19 → 13 → 9 → 10 → 5 → 3 → 2 → **3** → 1 → 0, all before C; never re-run after C | $3.02 (cap), 23.5 |
| 5.2 repeat 1 | 0 broken | 39 → 26 → 25 → 23 → 12 → 7 → 4 → **8** → 0 while building A/B; 0 again at the end, after E | $2.11, 24.3 |
| 5.2 repeat 2 | 0 broken | 48 → 20 → 7 → 4 → 0 while building A/B; 0 again at the end, after E | $2.43, 21.8 |
| 5.3 repeat 1 | A 32/32, B 36/36 | A and B.1–B.4 checks run only while building them (its last B.1 and B.3 outputs still showed failures); B.5 re-run 4 times during C | $2.49, 32.6 |
| 5.3 repeat 2 | A 32/32, B 36/36 | A and B.1–B.4 checks run only while building them; B.5 re-run once during C | $3.02 (cap), 35.1 |

#### Answer

a) No lasting damage. Both 5.2 repeats ran the regression suite one last time after finishing E,
and it showed 0 broken. On a fresh database, A and B are intact in every repeat that had Specs A
and B: 5.2 has 0 broken in both repeats, and 5.3 passes A 32/32 and B 36/36 in both. The
increases in the broken count during the runs (5.2 repeat 1: 4 → 8; 5.1 repeat 2: 2 → 3) happened
while the agent was still building A and B: fixing one A/B rule broke another. They came before
any C work, not from C, D or E. The only A/B damage left at the end (5.1 repeat 1: 19 broken)
came from never finishing A and B.

b) Yes, a lot. With Specs A and B (5.2), A and B reached 0 broken in both repeats within 5–9 suite runs, and both repeats submitted. With only the regression tests (5.1), the agent had to infer A and
B from failure messages:
- It started from 49–51 broken.
- One repeat stopped at 37 broken (19 on a fresh database).
- The other got to 0, but spent so much time and money (16 suite runs) that it hit the $3 cap in E before
  finishing it.

The specs make A and B cheap, which leaves budget for C, D and E.

c) For where A and B end up, no: both modes ended with A and B fully intact in both repeats (5.2: 0
broken; 5.3: 68/68). The difference is in what the agent can see.
- With plain checks (5.3), the agent never re-ran A.1–A.4 or B.1–B.4 after building them,
  and re-ran only B.5 (events) a few times during C. In 5.3 repeat 1 its last B.1 and B.3
  outputs still had failures it never went back to.
- With the suite (5.2), one command re-checked all 81 rules. Both repeats ran it once more at
  the very end, after E (0 broken), so they knew A and B still held.

Plain checks were also slower and costlier here: 5.3 ran 32–35 minutes and $2.49–3.02 (one hit
the cap), against 22–24 minutes and $2.11–2.43 for 5.2. There are 9 A/B scripts to run instead
of one suite, and no single "0 broken" target to aim for. So the suite is the safer choice:
same end state for A and B, regressions visible, and cheaper.

#### Consistency across repeats

5.2 and 5.3 were consistent: A and B intact in both repeats of each. 5.1 was not: 19 vs 0 broken,
$2.02 vs $3.02. Without the specs, the outcome depends on how quickly the agent decodes the
contract from failures. No repeat showed C, D or E breaking A or B, but with two repeats per
run that only shows such breakage is not common.

#### Other evidence

- The agents did not follow the README's "rerun the regression suite after every step".
  In all four suite repeats, they ran it only while building A and B and, in 5.2, once at the very
  end (5.1 repeat 2 hit the cap before getting back to it). So the suite worked as a final
  gate, not as a check after every step.
- Without Specs A and B (5.1), the agent rebuilt A and B from failing regression output alone:
  49–51 rules broken at the start. That took a large share of its time and budget, which shows up
  later in E (5.1 repeat 2 hit the $3 cap; repeat 1 ended with E.7 at 0/6).

## Job folders not in the table (`tasks/slack-clone-course/jobs-other/`)

| Job folders | What they are |
|---|---|
| `2026-11-09__18-05-51`, `__18-05-55` | Practice runs of Run 5.3 on spec `m2-v1`, before freezing (described above) |
| `2026-11-09__20-00-25`, `__20-00-45` | Run 2.3: agent setup timed out (network); the agent never ran |
| `2026-11-09__22-01-52`, `__22-02-10` | Run 5.2: agent install timed out downloading packages; the agent never ran |
| `2026-11-09__22-03-41`, `__22-04-01`, `__22-07-11`, `__22-07-31` | 5.3 and 2.3: setup took about 45 minutes (VPN), so the agents started with about 4 minutes left on `timer.sh` and submitted almost at once; discarded |
| `2026-11-09__22-53-33` … `__22-54-19` (6 folders) | Two launchers running at once loaded the wrong spec into some runs; all stopped within 3 minutes and discarded |
| `2026-11-09__22-57-15`, `__22-57-35`, `__22-57-45`, `__22-58-05` | 5.3 and 5.2: stuck in setup on the slow network; stopped and re-run |

## Files that support this report

- `my-specs-m2/<run>/`: the generated `/spec` for each run. `spec-copies/<run>/` holds exactly
  what the agent got.
- `my-specs-m2-src/`: the spec fragments, checks and `build.py` that generate them.
- `m2tools/`: run scripts (`run_config.sh`, `run_fast.sh`) and analysis scripts (`analyze_job.py`,
  `extra_stats.py`, `collect.py`).
- `runs-m2.log`: one line per repeat (run, repeat, job, cost, spec version).
- `m2tools/verify/`: the scripts I used to re-run each run's checks on an empty database, and
  `m2tools/verify/results/`: the full check output for each of the 22 repeats (the "Check results" column).
