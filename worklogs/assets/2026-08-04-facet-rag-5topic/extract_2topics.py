import json, subprocess, pathlib
hits = json.load(open("/tmp/topic_hits.json"))
SLUG = {"684397d188c1deceb49af32d": "684397d188c1deceb49af32d__preschool-teacher-strategy",
        "6847465956a0f6376a60547e": "6847465956a0f6376a60547e__decentralized-swarm-proposal"}
root = pathlib.Path("tmp/aus-agent-traces")
new_manifest = []
for h in hits:
    d = root / SLUG[h["qid"]]
    d.mkdir(parents=True, exist_ok=True)
    # original filename minus the topic-slug segment, matching existing convention
    orig = pathlib.Path(h["path"]).name          # <ts>.<slug>.<kind>.json
    ts = orig.split(".", 1)[0]
    dest = d / f"{ts}.{h['kind']}.json"
    blob = subprocess.run(["git","cat-file","-p",h["sha"]], capture_output=True).stdout
    dest.write_bytes(blob)
    new_manifest.append({"narrative_id": h["qid"], "run": ts, "kind": h["kind"],
                         "file": f"{SLUG[h['qid']]}/{dest.name}", "blob": h["sha"],
                         "bytes": len(blob), "source_path": h["path"],
                         "run_id": h["run_id"], "status": h["status"]})
    print(f"{h['qid'][:8]} {h['kind']:10s} {h['run_id']:24s} -> {dest}  ({len(blob)} B)")
json.dump(new_manifest, open("/tmp/new_manifest_entries.json","w"), indent=2)
print("\nextracted:", len(new_manifest))
