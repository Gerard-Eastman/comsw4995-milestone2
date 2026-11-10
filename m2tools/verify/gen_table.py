"""Build the 22-row runs table of report.md from analysis.jsonl (transcripts) and results/*.sum (fresh-DB reruns)."""
import json, os, re
COMP = {"1.1": "C", "1.2": "D", "1.3": "E", "2.1": "C", "2.2": "D", "2.3": "E", "3": "C, D, E", "4": "C, D, E",
        "5.1": "A to E", "5.2": "A to E", "5.3": "A to E"}
ORDER = ["1.1", "1.2", "1.3", "2.1", "2.2", "2.3", "3", "4", "5.1", "5.2", "5.3"]
TOTAL = {"base": 13, "A": 32, "B": 36, "C": 31, "D": 11, "E": 35, "E7": 6}
rows = {}
CHOSEN = json.load(open("/home/claude/m2verify/chosen.json"))
byjob = {}
for l in open("/home/claude/m2art/analysis.jsonl"):
    a = json.loads(l)
    byjob[a["job"]] = a
for k, job in CHOSEN.items():
    if k.startswith("_") or job not in byjob:
        continue
    run, rep = k.rsplit("-", 1)
    a = dict(byjob[job]); a["run"], a["rep"] = run, rep
    rows[(run, rep)] = a
NOTES = {}
if os.path.exists("/home/claude/m2verify/notes.json"):
    NOTES = json.load(open("/home/claude/m2verify/notes.json"))
OVR = {}
if os.path.exists("/home/claude/m2verify/overrides.json"):
    OVR = json.load(open("/home/claude/m2verify/overrides.json"))


def results_job(job):
    import glob
    for p in glob.glob("/home/claude/m2verify/results/*.txt.sum"):
        txt = open(p.replace(".sum", "")).readline()
        if job in txt:
            return results_file(p)
    return None


def results_file(p):
    s = open(p).read().replace("SUMMARY ", "").strip()
    keep = [part for part in s.split("; ") if not part.startswith("no result")]
    note = [part for part in s.split("; ") if part.startswith("no result")]
    return "; ".join(keep).replace("E7:", "E.7:").replace("E:", "E (E.1-E.6):", 1) + (f" ({note[0].replace('no result (timed out): ', 'no output from ')} within 45 s, counted as failed)" if note else "")


def results(run, rep, att=1):
    p = f"/home/claude/m2verify/results/{run}-rep{rep}-a{att}.txt.sum"
    if not os.path.exists(p):
        return None
    s = open(p).read().replace("SUMMARY ", "").strip()
    out = []
    for part in s.split("; "):
        m = re.match(r"(.+?): (\d+) passed, (\d+) failed", part)
        if m:
            out.append(f"{m.group(1)} {m.group(2)}/{int(m.group(2)) + int(m.group(3))}")
        m = re.match(r"A and B: (\d+) broken", part)
        if m:
            out.append(f"A+B regression {m.group(1)} broken")
    return "; ".join(out)


print("| Run | Component | Repeat | Job folder | Check results | Cost | Ran checks (times) | Submitted with failures? | Problems |")
print("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
for run in ORDER:
    for rep in ("1", "2"):
        a = rows.get((run, rep))
        if not a:
            print(f"| {run} | {COMP[run]} | {rep} | | | | | | |")
            continue
        res = results_job(a["job"]) or ("(not verified yet)" if a.get("exit_status") else "(agent never started)")
        prob = NOTES.get(f"{run}-{rep}", "")
        if not prob:
            p = a.get("problems") or {}
            bits = []
            if p.get("timeout"):
                bits.append(f"{p['timeout']} command timeout(s)")
            prob = ", ".join(bits) or "none"
        sub = "yes" if a.get("submitted_with_failures") else ("no" if a.get("submitted") else f"did not submit ({a.get('exit_status')})")
        sub = OVR.get(f"{run}-{rep}", {}).get("sub", sub)
        print(f"| {run} | {COMP[run]} | {rep} | `jobs/{a['job']}` | {res} | ${(a.get('cost') or 0):.2f} | {a.get('check_runs_total', 0)} | {sub} | {prob} |")
