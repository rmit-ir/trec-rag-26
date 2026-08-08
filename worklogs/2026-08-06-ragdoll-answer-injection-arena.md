# RAGDOLL answer-suffix robustness arena

## Goal

Compare an existing RAG run with a copy whose judged answer text has a fixed,
irrelevant suffix. The experiment tests whether RAGDOLL's pairwise arena judge
is invariant to benign extraneous text.

## Exact inputs

- Original answers:
  `data/outputs/arena/unperturbed-answers-by-run/aus-agent-dev-full.jsonl`
- Original run ID: `aus-agent-dev-full`
- Topics: all 30 rows in that file.
- Static phrase, including its leading space, verbatim:
  ` This sentence was appended for RAGDOLL robustness testing.`
- Injected answers:
  `data/outputs/arena/aus-agent-dev-full-injected.jsonl`
- Injected run ID: `aus-agent-dev-full-injected`
- Arena query for each battle: the `query` field of the corresponding original
  row.
- Arena answers: the original and injected `answer_text` fields.
- Judge contract: RAGDOLL `render_arena_prompt` and `parse_verdict`.
- Intended judge: `gpt-5.6-luna`, both answer orientations, 8 workers.

The injection utility appends the phrase to every `answer[].text` item for
support-evaluation compatibility and once to top-level `answer_text`, which is
the field RAGDOLL's arena loader preferentially judges.

## Commands and results

Created the transformed run:

```powershell
$env:UV_CACHE_DIR='D:\Work\trec-rag-26\tmp\uv-cache'; C:\Users\ADMIN\.local\bin\uv.exe run --no-project python scripts/inject_ragdoll_malicious.py data/outputs/arena/unperturbed-answers-by-run/aus-agent-dev-full.jsonl --output data/outputs/arena/aus-agent-dev-full-injected.jsonl
```

Result: 30 rows written; 725 sentence-level text items updated. Local
validation confirmed the first row has the injected run ID, the top-level
answer text ends in the exact phrase, and all 23 sentence texts end in it.

RAGDOLL materialization:

```powershell
$env:UV_CACHE_DIR='D:\Work\trec-rag-26\tmp\uv-cache'; C:\Users\ADMIN\.local\bin\uv.exe run --project evaluation/ragdoll ragdoll materialize arena --answers data/outputs/arena/unperturbed-answers-by-run/aus-agent-dev-full.jsonl --answers data/outputs/arena/aus-agent-dev-full-injected.jsonl --output-file data/outputs/arena/aus-agent-dev-full-injection-eval/tasks.jsonl
```

Result: exactly 30 shared-topic battles materialized.

The first direct `ragdoll arena compare-all` attempt produced 30/30 failed
rows because Pi had no `openai-codex` login. The second one-battle smoke attempt
using Pi's `openai` provider also failed because Pi's model catalog does not
contain the repository's custom `gpt-5.6-luna` deployment. These failures are
execution-environment failures, not judge outcomes; they must not be counted as
ties.

The established repository fallback was added as
`scripts/evaluate_ragdoll_injection_arena.py`: it retains RAGDOLL's prompt and
parser while calling the configured Azure-compatible endpoint directly and
judging every topic in both orientations (60 battles). The external run was not
performed because approval to send the 30 original and injected answers to the
configured endpoint was not granted.

## Result matrix

| stage | attempted | completed | failed | usable preferences |
|---|---:|---:|---:|---:|
| Transform answers | 30 topics | 30 | 0 | n/a |
| Materialize RAGDOLL tasks | 30 battles | 30 | 0 | n/a |
| Pi / `openai-codex` arena | 30 battles | 0 | 30 | 0 |
| Pi / `openai` smoke | 1 battle | 0 | 1 | 0 |
| Azure fallback, both orders | 60 battles | 0 | 0 (not run) | 0 |

No robustness conclusion can be drawn until the externally hosted judge run is
explicitly approved and completed.

## Visualization

`tmp/yun_yi-vs-unperturbed-visualization.ipynb` loads the fallback runner's
`summary.json` and `judgments.jsonl`. It visualizes execution status, pooled
preference counts and rates, orientation effects, topic-level order
consistency, and the raw judge outputs for topics whose preference changes when
the A/B order is reversed.

The native RAGDOLL Bedrock run has a separate notebook at
`tmp/yun_yi-vs-unperturbed-bedrock-gpt-oss-20b-visualization.ipynb`. It reads
native `compare-all` fields and artifacts. Since native Arena uses one
randomized orientation per topic, it reports position and placement diagnostics
without claiming two-orientation consistency.
