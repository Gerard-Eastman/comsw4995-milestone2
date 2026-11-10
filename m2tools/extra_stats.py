"""Per-trial behaviour stats for report.md, from the trajectories listed in ../m2-artifacts/analysis.jsonl.
Prints one JSON line per run attempt: FAIL lines and distinct failing rules the agent saw, how often it read
check source or bypassed the feedback mode, regression-suite results seen, and first-try results per check."""
import json, os, re, glob
cm = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
art = os.path.join(os.path.dirname(cm), "m2-artifacts")
CHECK = re.compile(r"/spec/[\w/.-]*?(check_[a-z]+(?:_\d+)?|regression)\.sh")
for line in open(os.path.join(art, "analysis.jsonl")):
    a = json.loads(line)
    if not a.get("exit_status"):
        continue
    g = glob.glob(os.path.join(cm, "tasks/slack-clone-course/jobs", a["job"], "final_task__*"))
    if not g:
        continue
    t = g[0]
    d = json.load(open(os.path.join(t, "agent", "mini-swe-agent.trajectory.json")))
    fails, rules, bypass, src, regs, first, pending = 0, set(), 0, 0, [], {}, []
    timer = 0
    for m in d["messages"]:
        c = m.get("content", "")
        if m["role"] == "assistant":
            cmd = c[c.find("```"):] if "```" in c else ""
            if re.search(r"FEEDBACK=\w+", cmd) or re.search(r"python3?\s+[\w/.-]*_checks\.py|/bin/python\s+[\w/.-]*_checks\.py", cmd):
                bypass += 1
            if re.search(r"(cat|sed|grep|head|tail)[^|]*_checks\.py|(cat|sed|grep)[^|]*checks/lib\.(py|sh)", cmd):
                src += 1
            if "timer.sh" in cmd:
                timer += 1
            pending = [n for n in CHECK.findall(cmd)]
        elif m["role"] == "user":
            if "Read this first" in c:
                continue
            fl = re.findall(r"^(?:REGRESSION )?FAIL (?:\w+ )?([A-E]?\d+\.\d+|0)\b", c, re.M)
            fails += len(fl)
            rules.update(fl)
            for b in re.findall(r"REGRESSION: (\d+) broken", c):
                regs.append(int(b))
            res = re.findall(r"RESULT: (\d+) passed, (\d+) failed", c)
            names = [n for n in pending if n != "regression"]
            if len(names) == len(res):
                for n, (p, f) in zip(names, res):
                    first.setdefault(n, f"{p}/{int(p) + int(f)}")
            pending = []
    print(json.dumps({"run": a["run"], "rep": a["rep"], "attempt": a.get("attempt", 1), "job": a["job"], "fail_lines_seen": fails,
                      "distinct_rules_failed_seen": len(rules), "bypass_cmds": bypass, "check_source_reads": src, "timer_runs": timer,
                      "regression_results": regs, "first_try": first}))
