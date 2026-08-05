import subprocess, collections
# All blob shas + paths ever under data/outputs/aus_agent, deduped.
out = subprocess.run(
    ["git","rev-list","--all","--objects","--","data/outputs/aus_agent"],
    capture_output=True, text=True).stdout
seen = {}
for ln in out.splitlines():
    parts = ln.split(" ", 1)
    if len(parts) != 2: continue
    sha, path = parts
    if path.endswith((".output.json", ".trajectory.json")):
        seen[sha] = path
print("unique blobs:", len(seen))
# batch-check sizes to skip 131-byte LFS pointers
inp = "".join(f"{s}\n" for s in seen)
sz = subprocess.run(["git","cat-file","--batch-check"], input=inp,
                    capture_output=True, text=True).stdout
real = []
for ln in sz.splitlines():
    f = ln.split()
    if len(f) >= 3 and f[1] == "blob" and int(f[2]) > 5000:
        real.append(f[0])
print("non-pointer blobs:", len(real))
with open("/tmp/real_blobs.txt","w") as fh:
    for s in real: fh.write(f"{s}\t{seen[s]}\n")
