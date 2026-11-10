"""Copy every file of an update tarball over course_milestone_2 without deleting anything (overwrites in place).
Usage: python3 sync_in.py <update.tgz> <course_milestone_2 dir>"""
import os, shutil, sys, tarfile, tempfile
tgz, dst = sys.argv[1], sys.argv[2]
tmp = tempfile.mkdtemp()
tarfile.open(tgz).extractall(tmp)
src = os.path.join(tmp, "course_milestone_2")
n = 0
for root, dirs, files in os.walk(src):
    rel = os.path.relpath(root, src)
    os.makedirs(os.path.join(dst, rel), exist_ok=True)
    for f in files:
        s, d = os.path.join(root, f), os.path.join(dst, rel, f)
        shutil.copyfile(s, d)
        shutil.copymode(s, d)
        n += 1
print("copied", n, "files")
