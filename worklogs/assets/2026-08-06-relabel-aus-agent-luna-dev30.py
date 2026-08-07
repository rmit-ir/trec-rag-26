"""Copy the 30 gpt-5.6-luna aus_agent dev30 outputs (currently sharing the
ambiguous run_id aus-agent-dev30-20260806 with a bedrock/claude-sonnet-5
batch) into new files tagged with an unambiguous run_id, so
load_answers_from_outputs (which raises on duplicate qid per run_id) works.
Non-destructive: originals untouched.
"""
import glob
import json
from pathlib import Path

SRC_DIR = Path("data/outputs/aus_agent")
OLD_RUN_ID = "aus-agent-dev30-20260806"
NEW_RUN_ID = "aus-agent-dev30-luna-e2708ab"
MODEL_MARK = "gpt-5.6-luna"

copied = 0
for out_path in sorted(SRC_DIR.glob("*.output.json")):
    obj = json.loads(out_path.read_text(encoding="utf-8"))
    meta = obj.get("metadata", {})
    if meta.get("run_id") != OLD_RUN_ID or MODEL_MARK not in meta.get("run_desc", ""):
        continue

    new_stem = out_path.stem.replace(".output", "") + f".{NEW_RUN_ID}"
    new_out = SRC_DIR / f"{new_stem}.output.json"
    obj["metadata"]["run_id"] = NEW_RUN_ID
    new_out.write_text(json.dumps(obj, indent=2), encoding="utf-8")

    traj_path = out_path.with_name(out_path.name.replace(".output.json", ".trajectory.json"))
    if traj_path.exists():
        traj = json.loads(traj_path.read_text(encoding="utf-8"))
        if isinstance(traj, dict) and "metadata" in traj:
            traj["metadata"]["run_id"] = NEW_RUN_ID
        new_traj = SRC_DIR / f"{new_stem}.trajectory.json"
        new_traj.write_text(json.dumps(traj, indent=2), encoding="utf-8")

    copied += 1

print(f"copied {copied} output(+trajectory) pairs to run_id={NEW_RUN_ID}")
