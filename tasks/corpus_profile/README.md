# ClimbMix Corpus Profiling

Task-local tooling for sampling a small subset of
`karpathy/climbmix-400b-shuffle`, profiling document length and structure, and
rendering a shareable Markdown report with figures.

This task is intentionally separate from `tasks/custom_index/`. The custom
index task builds the full retrieval index; this task only samples and profiles
the corpus so we can make evidence-based chunking decisions.

## Outputs

Generated sample artifacts are written under the gitignored directory:

```text
data/climbmix-profile-sample/
  raw/                 # sampled parquet shards
  manifests/<run_id>/  # shard sample, download status, config, errors
  stats/<run_id>/      # per-shard metrics + aggregate stats
  examples/<run_id>/   # representative text examples by category
```

Reports and figures are task-local outputs:

```text
tasks/corpus_profile/reports/
  corpus_profile.md
  figures/<run_id>/
```

The main shareable report is:

```text
tasks/corpus_profile/reports/corpus_profile.md
```

## Run Modes

The wrapper sets safe defaults by `PROFILE_RUN`:

| mode | sampled shards | max docs per shard | purpose |
|---|---:|---:|---|
| `smoke` | 1 | 1000 | script/report validation |
| `pilot` | 10 | 10000 | first shareable report |
| `onepct` | 66 | 10000 | approximately 1% corpus profile |
| `report` | 40 | 25000 | larger group-facing report |

Every setting can be overridden with environment variables.

## Unattended tmux Run

Start with a smoke run:

```bash
tmux new -s climbmix-profile

PROFILE_RUN=smoke \
SEED=20260703 \
  ./tasks/corpus_profile/scripts/run_profile.sh \
  2>&1 | tee /tmp/climbmix-profile-smoke.log
```

Detach with `Ctrl-b d`, then monitor from another shell:

```bash
tail -f /tmp/climbmix-profile-smoke.log
tail -f tasks/corpus_profile/logs/<run_id>.log
```

After smoke passes, run a pilot:

```bash
PROFILE_RUN=pilot \
SEED=20260703 \
  ./tasks/corpus_profile/scripts/run_profile.sh \
  2>&1 | tee /tmp/climbmix-profile-pilot.log
```

For the original 1% corpus-profiling TODO, run:

```bash
PROFILE_RUN=onepct \
RUN_ID=onepct \
SEED=20260703 \
  ./tasks/corpus_profile/scripts/run_profile.sh \
  2>&1 | tee /tmp/climbmix-profile-onepct.log
```

## Useful Environment Variables

| variable | default | meaning |
|---|---|---|
| `PROFILE_RUN` | `smoke` | `smoke`, `pilot`, `onepct`, or `report` |
| `RUN_ID` | timestamped from mode | output subdirectory name |
| `SEED` | `20260703` | shard sampling seed |
| `TOTAL_SHARDS` | `6543` | ClimbMix shard count |
| `SAMPLE_SHARDS` | mode-specific | number of shards to sample |
| `MAX_DOCS_PER_SHARD` | mode-specific | per-shard row cap for profiling |
| `SAMPLE_ROOT` | `data/climbmix-profile-sample` | sample artifact root for raw/manifests/stats/examples |
| `REPORTS_DIR` | `tasks/corpus_profile/reports` | report and figure output directory |
| `REPO_ID` | `karpathy/climbmix-400b-shuffle` | Hugging Face dataset repo |
| `SKIP_DOWNLOAD` | `0` | set `1` to profile existing parquet only |
| `FORCE_DOWNLOAD` | `0` | set `1` to redownload existing shards |
| `FORCE_PROFILE` | `0` | set `1` to reprocess existing per-shard metrics |
| `EXAMPLES_PER_CATEGORY` | `20` | number of examples to keep per structure category |
| `EXAMPLE_CHARS` | `6000` | max characters stored in each example file |
| `EXAMPLE_SEED` | same as `SEED` | reproducible per-category reservoir sampling seed |

## Failure Behavior

The wrapper is designed for unattended runs:

- Fatal setup failures stop the run with a clear log message.
- Per-shard download/profile failures are recorded and the run continues.
- Existing downloaded parquet shards are reused.
- Existing per-shard metrics are reused unless `FORCE_PROFILE=1`.
- Examples are sampled while profiling. To regenerate examples for an existing
  run after changing sampling logic, use `FORCE_PROFILE=1` or create a new
  `RUN_ID`.
- Per-shard metrics are written through temporary files and atomically renamed.
- Final aggregate stats and report are rebuilt at the end.

Main debug files:

```text
tasks/corpus_profile/logs/<run_id>.log
data/climbmix-profile-sample/manifests/<run_id>/download_status.jsonl
data/climbmix-profile-sample/manifests/<run_id>/profile_errors.jsonl
data/climbmix-profile-sample/manifests/<run_id>/run_config.json
data/climbmix-profile-sample/manifests/<run_id>/run_summary.json
```

## What The Report Measures

- Document length: chars, bytes, words, lines, paragraphs, approximate tokens.
- Primary structure categories: clean text, HTML/markup-like,
  outline/Markdown-like, strong code-like, table/record-like, empty/tiny.
- Non-exclusive noise signals: URL-heavy, boilerplate signal, long-tail
  outlier, plus the primary structure signals.
- Other indicators: URL count, HTML tag count, boilerplate hits, non-ASCII
  ratio, control-character ratio, duplicate-line ratio, and code-shaped line
  counts.
- Strong code-like matching is intentionally conservative: programming
  keywords are case-sensitive except SQL, so prose headings such as `Class 3:`
  do not count as code.
- Current report output uses the stable rule set name `tightened-primary`.
- First-window quality: whether the first 500 chars look like body text or
  mostly markup/boilerplate.
- Representative examples for each primary structure category, using per-category
  reservoir sampling.

Token counts are approximate in the first version: `ceil(char_count / 4)`.
Use this for profiling and chunking design, not for exact model budgeting.
