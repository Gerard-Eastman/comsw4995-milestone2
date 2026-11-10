"""Summarize what the agent did in one job folder (or several), from its trajectory and result.json.
Usage: python3 m2tools/analyze_job.py tasks/slack-clone-course/jobs/<timestamp> [...]
Prints, per trial: cost, steps, minutes, how many times each check ran, the last result of each check
before the agent submitted, whether it submitted with failures, and problems seen."""
import glob, json, os, re, sys
from datetime import datetime

CHECK_RE = re.compile(r"(/spec/[\w/.-]*?(check_[a-z]+(?:_\d+)?|regression)\.sh)")
RES_RE = re.compile(r"RESULT: (\d+) passed, (\d+) failed")
REG_RE = re.compile(r"REGRESSION: (\d+) broken")


def extra(m):
    e = m.get("extra") or {}
    if isinstance(e, str):
        try:
            import ast
            e = ast.literal_eval(e)
        except Exception:
            e = {}
    return e


def analyze(trial):
    tj = os.path.join(trial, "agent", "mini-swe-agent.trajectory.json")
    out = {"trial": os.path.basename(trial)}
    try:
        r = json.load(open(os.path.join(trial, "result.json")))
        ar = r.get("agent_result") or {}
        out["cost"] = ar.get("cost_usd") if isinstance(ar, dict) else None
        if out["cost"] is None:
            out["cost"] = (r.get("stats") or {}).get("cost_usd")
        out["exception"] = (r.get("exception_info") or {}).get("exception_type") if r.get("exception_info") else None
    except Exception as e:
        out["cost"] = None
        out["exception"] = f"no result.json ({e})"
    if not os.path.exists(tj):
        out["error"] = "no trajectory"
        return out
    d = json.load(open(tj))
    msgs = d.get("messages", [])
    info = d.get("info", {})
    out["exit_status"] = info.get("exit_status")
    if out.get("cost") is None:
        out["cost"] = (info.get("model_stats") or {}).get("instance_cost")
    steps, runs, last, problems, times = 0, {}, {}, {}, []
    last_out_fail = False
    pending = []
    for m in msgs:
        role = m.get("role")
        e = extra(m)
        if role == "assistant":
            steps += 1
            resp = e.get("response") or {}
            if isinstance(resp, dict) and resp.get("created"):
                times.append(resp["created"])
            cmds = [a.get("command", "") for a in (e.get("actions") or []) if isinstance(a, dict)]
            pending = []
            for c in cmds:
                for full, name in CHECK_RE.findall(c):
                    if "cat " in c and "bash" not in c:
                        continue
                    runs[name] = runs.get(name, 0) + 1
                    pending.append(name)
        elif role == "user" and pending:
            txt = m.get("content", "")
            results = RES_RE.findall(txt)
            regs = REG_RE.findall(txt)
            names = [n for n in pending if n != "regression"]
            # map RESULT lines to the check scripts only when one RESULT line per script came back
            if len(names) == len(results):
                for n, (p, f) in zip(names, results):
                    last[n] = (int(p), int(f))
            if results or regs:
                last_out_fail = any(int(f) > 0 for _, f in results) or any(int(x) > 0 for x in regs)
            if "regression" in pending and regs:
                last["regression"] = ("broken", int(regs[-1]))
            pending = []
        if role == "user" and "Read this first" not in m.get("content", "") and "## How to work" not in m.get("content", ""):
            txt = m.get("content", "")
            for key, pat in (("RESTART FAILED", "RESTART FAILED"), ("timeout", "timed out"), ("Traceback", "Traceback (most recent call last)"),
                             ("format error", "Please always provide EXACTLY ONE action")):
                if pat in txt:
                    problems[key] = problems.get(key, 0) + 1
    out["steps"] = steps
    out["minutes"] = round((max(times) - min(times)) / 60, 1) if len(times) > 1 else None
    out["check_runs_total"] = sum(runs.values())
    out["check_runs"] = dict(sorted(runs.items()))
    out["last_results"] = {k: (f"{v[1]} broken" if v[0] == "broken" else f"{v[0]}/{v[0] + v[1]}") for k, v in sorted(last.items())}
    failing = [k for k, v in last.items() if (v[0] == "broken" and v[1] > 0) or (v[0] != "broken" and v[1] > 0)]
    out["submitted"] = out["exit_status"] == "Submitted"
    out["last_check_output_had_failures"] = last_out_fail
    out["submitted_with_failures"] = bool(out["submitted"] and (failing or last_out_fail))
    out["failing_at_end"] = sorted(failing)
    out["problems"] = problems
    return out


def main():
    for job in sys.argv[1:]:
        trials = sorted(glob.glob(os.path.join(job, "final_task__*"))) or [job]
        for t in trials:
            res = analyze(t)
            print(json.dumps({"job": os.path.basename(job.rstrip("/")), **res}))


if __name__ == "__main__":
    main()
