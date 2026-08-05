import subprocess, json
WANT = {"684397d188c1deceb49af32d":"PRESCHOOL", "6847465956a0f6376a60547e":"SWARM"}
rows = [l.split("\t") for l in open("/tmp/real_blobs.txt").read().splitlines() if l.strip()]
hits = []
for sha, path in rows:
    blob = subprocess.run(["git","cat-file","-p",sha], capture_output=True).stdout
    head = blob[:4000].decode("utf-8","replace")
    for qid, name in WANT.items():
        if qid in head:
            try:
                d = json.loads(blob.decode("utf-8","replace"))
            except Exception:
                d = {}
            md = d.get("metadata") or {}
            tr = d.get("trace") or {}
            rid = md.get("run_id") or d.get("run_id")
            status = tr.get("status") or d.get("status")
            nref = len(d.get("references") or [])
            tcc = d.get("tool_call_counts") or tr.get("tool_call_counts") or {}
            ndoc = len(d.get("retrieved_docids") or [])
            kind = "trajectory" if path.endswith(".trajectory.json") else "output"
            hits.append((name, qid, sha, path, kind, rid, status, nref, tcc, ndoc, len(blob)))
            break
print("matches:", len(hits))
for h in sorted(hits, key=lambda r:(r[0], r[3])):
    print(f"{h[0]:9s} {h[4]:10s} rid={str(h[5]):26s} status={str(h[6]):9s} refs={h[7]:3d} docids={h[9]:4d} tcc={json.dumps(h[8])} bytes={h[10]}")
    print(f"          sha={h[2]} path={h[3]}")
json.dump([{"name":h[0],"qid":h[1],"sha":h[2],"path":h[3],"kind":h[4],"run_id":h[5],
            "status":h[6],"refs":h[7],"tool_call_counts":h[8],"docids":h[9],"bytes":h[10]}
           for h in hits], open("/tmp/topic_hits.json","w"), indent=2)
