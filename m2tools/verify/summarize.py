"""Summarize a verify.sh output file per component: '<comp>: P passed, F failed'.
A check that printed no RESULT line (killed by the 45 s harness timeout) counts all its rules as failed."""
import re, sys
N = {"check_base": 13, "check_a_1": 6, "check_a_2": 7, "check_a_3": 8, "check_a_4": 11, "check_b_1": 8, "check_b_2": 7, "check_b_3": 6,
     "check_b_4": 6, "check_b_5": 9, "check_c_1": 6, "check_c_2": 5, "check_c_3": 5, "check_c_4": 6, "check_c_5": 5, "check_c_6": 4,
     "check_d_1": 4, "check_d_2": 4, "check_d_3": 3, "check_e_1": 5, "check_e_2": 5, "check_e_3": 6, "check_e_4": 5, "check_e_5": 7,
     "check_e_6": 7, "check_e_7": 6}
res, missing = {}, []
cur = name = None
got = True


def close():
    global got
    if name and not got and name in N:
        p, f = res.get(cur, (0, 0))
        res[cur] = (p, f + N[name])
        missing.append(name)


for line in open(sys.argv[1]):
    m = re.match(r"== /spec/(?:(\w+)/)?checks/(\w+)\.sh", line)
    if m:
        close()
        name = m.group(2)
        cur = {"check_base": "base", "regression": "A and B", "check_e_7": "E7"}.get(name) or name.split("_")[1].upper()
        got = False
        continue
    m = re.match(r"RESULT: (\d+) passed, (\d+) failed", line)
    if m and cur:
        p, f = res.get(cur, (0, 0))
        res[cur] = (p + int(m.group(1)), f + int(m.group(2)))
        got = True
    m = re.match(r"REGRESSION: (\d+) broken", line)
    if m:
        res["A and B"] = ("broken", int(m.group(1)))
        got = True
close()
order = ["base", "A and B", "A", "B", "C", "D", "E", "E7"]
parts = []
for k in order + [k for k in res if k not in order]:
    if k in res:
        a, b = res[k]
        parts.append(f"{k}: {b} broken" if a == "broken" else f"{k}: {a} passed, {b} failed")
print("SUMMARY " + "; ".join(parts) + (f"; no result (timed out): {', '.join(missing)}" if missing else ""))
