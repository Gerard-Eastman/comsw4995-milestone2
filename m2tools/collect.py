"""Collect every official run: tar its agent-built /app into ../m2-artifacts/<job>.app.tgz and write
../m2-artifacts/analysis.jsonl (one line per run/repeat/attempt, from analyze_job.py).
Runs that were not logged in runs-m2.log can be listed in ../m2-artifacts/extra_jobs.txt as "<run> <repeat> <job>"."""
import json, os, re, subprocess, sys
cm = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
art = os.path.join(os.path.dirname(cm), "m2-artifacts")
os.makedirs(art, exist_ok=True)
entries = []
for line in open(os.path.join(cm, "runs-m2.log")):
    if "tag=official" in line:
        run = re.search(r"run=(\S+)", line).group(1)
        rep = re.search(r"repeat=(\d+)", line).group(1)
        job = re.search(r"job=jobs/(\S+)", line)
        if job:
            entries.append((run, rep, job.group(1)))
extra = os.path.join(art, "extra_jobs.txt")
if os.path.exists(extra):
    for line in open(extra):
        p = line.split()
        if len(p) == 3 and not any(e[2] == p[2] for e in entries):   # only jobs runs-m2.log does not already list
            entries.append(tuple(p))
entries.sort(key=lambda e: e[2])
seen, out = {}, []
for run, rep, job in entries:
    jd = os.path.join(cm, "tasks/slack-clone-course/jobs", job)
    trials = sorted(d for d in os.listdir(jd) if d.startswith("final_task__"))
    if not trials:
        continue
    t = os.path.join(jd, trials[0])
    tgz = os.path.join(art, f"{job}.app.tgz")
    if not os.path.exists(tgz) and os.path.isdir(os.path.join(t, "artifacts", "app")):
        subprocess.run(["tar", "czf", tgz, "-C", os.path.join(t, "artifacts"), "app"], check=True)
    res = subprocess.run([sys.executable, os.path.join(cm, "m2tools/analyze_job.py"), jd], capture_output=True, text=True).stdout.splitlines()
    if not res:
        continue
    a = json.loads(res[0])
    attempt = seen.get((run, rep), 0) + 1
    seen[(run, rep)] = attempt
    a.update(run=run, rep=rep, attempt=attempt)
    out.append(a)
with open(os.path.join(art, "analysis.jsonl"), "w") as f:
    for a in out:
        f.write(json.dumps(a) + "\n")
for a in out:
    print(a["run"], a["rep"], a["attempt"], a["job"], f"${(a.get('cost') or 0):.2f}", a.get("steps"), a.get("minutes"), a.get("exit_status"))
