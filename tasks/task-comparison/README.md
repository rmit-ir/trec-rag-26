# task-comparison — retrieval-backend comparison study

Code for the dense · keyword · ssr · lucene comparison. **Code lives here; all
artifacts/outputs live under `data/task-comparison/`** (per the repo's code-vs-data
split). Scripts write their results there.

## Envs (this task has no `.venv` of its own — it's glue over other tasks)

It deliberately borrows existing envs rather than owning one, because it spans
three dependency worlds:

| stage | env | why |
|---|---|---|
| judging, sub-query gen, per-engine runs, `fetch_doc` | root **`--group aus-agent`** | luna OpenAI client + `src/tools`, `src/utils` |
| doc embedding (`build_diversity_dataset.py`) | **`--project tasks/search_serve`** | jina-v5 + einops + peft |
| pure-metric scripts (`diversity_metrics.py`) | **`--no-project --with numpy`** | stdlib + numpy only |

Any stage that hits a hosted backend or Pyserini needs creds in the process env:
`set -a; source .env; set +a` before `uv run` (the `custom_index` subprocess does
NOT inherit them otherwise — silent fetch failures result).

## Layout

```
tasks/task-comparison/
  scripts/       analyze.py, selection_ratio.py, query_taxonomy.py, extract_ssr_stats.py   (behavioral cuts)
                 gen_per_engine_dev30.sh, build_diversity_dataset.py, diversity_metrics.py  (diversity study)
  rubric-judge/  common.py + pipeline: rubric_prep → gen_subqueries → retrieve → judge → score
                 (+ backfill_semantic); committed-doc study: judge_committed, score_committed, judge_answers
  logs/          run logs (gitignored)
data/task-comparison/            ← ARTIFACTS (not code)
  comparison_matrix.md           ← the living summary (Cuts 1–4)
  *.md / *.jsonl                 ← per-cut result docs
  rubric-judge/out/              ← judgments/, pools, matrices, answer_judgments/ (large → gitignored)
  diversity/                     ← embeddings.npy, doc_text.jsonl, *_metrics.json, committed_analysis.* …
```

## Cuts (see `data/task-comparison/comparison_matrix.md` for results)

- **Cut 1** — rubric-grounded LLM-judge over retrieval pools (ground truth).
- **Cuts 2–3** — behavioral agent-commit cuts (selection-ratio, intent-taxonomy commit-ratio).
- **Cut 4** — committed-doc diversity (Vendi), cross-engine complementarity, credibility
  proxies, rubric best-explanation, and answer-level RAGDOLL. Worklog:
  `worklogs/2026-07-27-committed-diversity-and-answer-ragdoll.md`.

## Run examples

```bash
# generate the 4 per-engine runs over 30 dev topics (paid; sequential)
bash tasks/task-comparison/scripts/gen_per_engine_dev30.sh 2>&1 | tee tasks/task-comparison/logs/gen.log

# build committed-doc text + jina-v5 embeddings (needs .env sourced for the Pyserini token)
set -a; source .env; set +a
PYTHONPATH=src uv run --project tasks/search_serve python tasks/task-comparison/scripts/build_diversity_dataset.py

# diversity metrics (free)
uv run --no-project --with numpy python tasks/task-comparison/scripts/diversity_metrics.py

# judge committed docs + score best-explanation/credibility + answer-level RAGDOLL
set -a; source .env; set +a
PYTHONPATH=src uv run --group aus-agent python tasks/task-comparison/rubric-judge/judge_committed.py
uv run --group aus-agent python tasks/task-comparison/rubric-judge/score_committed.py
PYTHONPATH=src uv run --group aus-agent python tasks/task-comparison/rubric-judge/judge_answers.py
```
