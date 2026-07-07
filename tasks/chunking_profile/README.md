# ClimbMix Chunking Profile

Task-local tooling for comparing chunking strategies over the sampled ClimbMix
corpus profile before embedding or index construction.

The experiment plan and checklist live in:

```text
tasks/chunking_profile/EXPERIMENT_PLAN.md
```

## Environment

Use this task's own uv environment:

```bash
uv sync --project tasks/chunking_profile
uv run --project tasks/chunking_profile python --version
```

Do not use the repo root environment for this task.

## Inputs

The planned baseline input is the completed 1% corpus profile:

```text
data/climbmix-profile-sample/manifests/onepct/sample_manifest.jsonl
data/climbmix-profile-sample/raw/
data/climbmix-profile-sample/stats/onepct/corpus_stats.json
```

## Outputs

Shareable outputs are written under this task directory:

```text
tasks/chunking_profile/reports/
  chunking_comparison.md
  teams_post.md
  figures/<run_id>/
  examples/<run_id>/
```

Large intermediate data is written under:

```text
data/chunking-profile/
  manifests/<run_id>/
  samples/<run_id>/
  stats/<run_id>/
```

## Planned Run Modes

| mode | target docs | purpose |
|---|---:|---|
| `smoke` | 500 | validate scripts and report rendering |
| `sample` | 5,000 | inspect examples and first comparison |
| `onepct` | 660,000 | final local stats over the 1% corpus sample |

## Planned Wrapper

The unattended wrapper will be:

```bash
CHUNK_PROFILE_RUN=smoke \
RUN_ID=smoke \
SEED=20260703 \
  ./tasks/chunking_profile/scripts/run_chunking_profile.sh \
  2>&1 | tee /tmp/climbmix-chunking-smoke.log
```

See `EXPERIMENT_PLAN.md` for the authoritative design and checklist.
