# 2026-08-07 — native RAGDoll arena: two Sol runs vs organizer Sol baseline

## Objective

Run the two 119-topic Sol submissions through the native RAGDoll arena and
compare both with the organizer's **Sol agentic-search BM25** baseline. The
organizer single-pass baseline was deliberately excluded.

## Exact inputs

All three files contain 119 official test topics. The exact narrative and both
answers for every judgment are preserved verbatim in `tasks.jsonl`; the Pi
event stream containing the same rendered prompts is preserved under
`raw-events/`.

| role | run_id | source | SHA-256 |
|---|---|---|---|
| organizer Sol baseline | `piika-gpt56sol-medium-agentic-bm25-rag` | `data/official/trec-rag-2026-data/trec-rag-2026/baselines/rag/gpt-5.6-sol_medium_agentic-search_bm25_output-mode-answer.jsonl` | `73c31a411248cfefa8afe9a8c5fbceb6fa9a4f083a442cd92d7bfdbd04686649` |
| verified research-first control | `sol-aus-v2-research-first-test119-20260807` | `data/outputs/submissions/sol-aus-v2-research-first-test119-20260807/rag_output_trec_rag_2026.jsonl` | `744c2d0624a1b834b94ad87fbc50548b1957f22a09beb1903230da72fe4986d8` |
| Sol default method | `sol-aus-default-test119-20260807` | `data/outputs/submissions/sol-aus-default-test119-20260807/rag_output_trec_rag_2026.jsonl` | `d6fcf2c14bb48dfc3f7476032ecf79c6d2704664434266efabe383dcace10fc5` |

## RAGDoll adoption audit

- `evaluation/ragdoll` was pinned at `1f0671908ab6dc581a61648463e3566ba413b480`.
  `git ls-remote` returned the same commit for official
  `https://github.com/castorini/RAGDoll.git` `main` on the run date.
- The run used RAGDoll's native `ragdoll arena compare-all`, not the older
  `tasks/task-comparison/scripts/judge_test119_arena.py` wrapper that only
  borrowed RAGDoll's prompt.
- Native RAGDoll loaded official organizer rows directly, concatenated
  `answer[].text`, and did not render references or citations into the judge
  prompt.
- The prompt was `PAIRWISE_ANSWER_COMPARISON_NAIVE`, with an empty system
  prompt. Test topics have no organizer rubrics, so the rubric-guided arena was
  not applicable.
- Native semantics were preserved: one deterministic randomized A/B order per
  shared `(pair, qid)` using seed 13. The older custom wrapper's duplicate
  reverse-order calls were not carried forward.
- RAGDoll materialized 357 tasks: 119 shared topics times all three system
  pairs. The third, ours-vs-ours edge is part of native `compare-all` and makes
  the three-system leaderboard connected; the two organizer-baseline rows are
  the requested comparisons.
- RAGDoll produced the native `tasks.jsonl`, `judgments.jsonl`, `coverage.csv`,
  `pairwise.csv`, `leaderboard.csv`, and `raw-events/` artifacts, with
  `arena-rank` producing the leaderboard.
- Pi was absent on this host. The current supported package
  `@earendil-works/pi-coding-agent@0.84.0` was installed into the throwaway
  prefix `/tmp/ragdoll-pi-0.84.0`; no global or project Node environment was
  modified.
- The Bedrock Mantle route was registered in a temporary Pi `models.json` as
  provider `mantle`, API `openai-responses`, model
  `openai.gpt-5.6-luna`, `reasoning: true`, 272K context, 8K maximum output,
  and `apiKey: "$OPENAI_API_KEY"`. No credential was written into an artifact.
- `ragdoll doctor --probe` passed for native Pi, model routing, auth-state
  copying, and response parsing. Log:
  `worklogs/assets/2026-08-07-ragdoll-doctor-probe.log`.
- RAGDoll arena contract, materialization, strict parsing, fake-Pi execution,
  resume-manifest, and answers-directory tests all displayed passing results
  across split invocations. The combined invocation was split because the
  command-session transport stopped returning output during repeated JAX
  leaderboard fits; no RAGDoll code was changed.

## Preflight

The full dry run reported exactly 357 tasks. A paid one-topic-per-pair preflight
used `--sample-topics-per-pair 1 --sampling-seed 13` and produced:

| pair | qid | verdict | preferred run |
|---|---|---|---|
| organizer baseline vs research-first | `rag2026-68` | `B` | research-first |
| organizer baseline vs default | `rag2026-61` | `A` | default |
| research-first vs default | `rag2026-43` | `B` | default |

All 3 judgments had `status=completed`, strict parsed verdicts, provider `pi`,
model `mantle/openai.gpt-5.6-luna`, thinking `medium`, no error, and a raw event
ending in a single verdict with `stop`. The exact preflight log is
`worklogs/assets/2026-08-07-ragdoll-arena-preflight.log`; prompts and raw events
were kept in `/tmp/ragdoll-arena-preflight-20260807` for the session.

## Full command

Run from `evaluation/ragdoll`:

```bash
set -o pipefail
set -a
source ../../.env
set +a
UV_CACHE_DIR=/tmp/ragdoll-uv-cache PI_OFFLINE=1 uv run ragdoll arena compare-all --answers ../../data/official/trec-rag-2026-data/trec-rag-2026/baselines/rag/gpt-5.6-sol_medium_agentic-search_bm25_output-mode-answer.jsonl --answers ../../data/outputs/submissions/sol-aus-v2-research-first-test119-20260807/rag_output_trec_rag_2026.jsonl --answers ../../data/outputs/submissions/sol-aus-default-test119-20260807/rag_output_trec_rag_2026.jsonl --output-dir ../../data/outputs/ragdoll-arena/sol-test119-vs-organizer-sol-agentic-bm25-20260807 --agent-binary /tmp/ragdoll-pi-0.84.0/node_modules/.bin/pi --agent-state-dir /tmp/ragdoll-pi-agent --model mantle/openai.gpt-5.6-luna --thinking medium --seed 13 --max-concurrency 8 --timeout-seconds 300 --overwrite 2>&1 | tee /tmp/ragdoll-arena-sol-test119-20260807.log
```

The first launch targeted the repository's `evaluation-results` symlink, but
the remote target lacked group write permission. It failed before task
materialization and made zero API calls. The command above is the successful
launch under the writable `data/outputs/` tree.

## Integrity audit

- 357 task rows, 357 judgment rows, 357 unique task IDs, 119 unique qids.
- 357/357 `status=completed`; zero errors, null verdicts, or failed tasks.
- Verdicts: 155 `A`, 199 `B`, 3 `Tie (Both Bad)`, 0 plain `Tie`.
- 357 raw-event files; every final assistant event contained exactly one strict
  verdict and ended with `stop`.
- All three coverage rows report 119 shared topics and zero one-sided topics.
- All task metadata names `PAIRWISE_ANSWER_COMPARISON_NAIVE`; all task system
  prompts are empty.
- Full log: `worklogs/assets/2026-08-07-ragdoll-arena-full.log`.

Artifact hashes:

| artifact | SHA-256 |
|---|---|
| `tasks.jsonl` | `4203a3f972689be3d7bcf3619bb96edd1c75c9c0f5029efa62b5f8d5dda0fe98` |
| `judgments.jsonl` | `ae9fb24359160339b1cca208df9f605e2847a6bd339328f7b2d5ab25d1d0e2f8` |
| `pairwise.csv` | `f846d5adc41921cc6882c556d46e8a92acbdaadac0a07d5d3c80320e647e705b` |
| `coverage.csv` | `ebe1a526c6ebedd9313ed492524103a645259c3f51a974832a9c75be87c222bb` |
| `leaderboard.csv` | `6eebb56d77105549f453b966ffbeebe4d990bded3d17ae17ad88808e80fc87c1` |

## Full result matrix

Ties count as half a win in the preference rate, matching RAGDoll.

| run A | run B | judgments | A wins | B wins | ties | A preference | B preference |
|---|---|---:|---:|---:|---:|---:|---:|
| organizer Sol agentic-BM25 | research-first | 119 | 10 | 108 | 1 | 0.088235 | **0.911765** |
| organizer Sol agentic-BM25 | default | 119 | 11 | 107 | 1 | 0.096639 | **0.903361** |
| research-first | default | 119 | 67 | 51 | 1 | **0.567227** | 0.432773 |

Native arena-rank leaderboard:

| rank | run | arena score | judgments | wins | losses | ties |
|---:|---|---:|---:|---:|---:|---:|
| 1 | research-first | 1153.981249 | 238 | 175 | 61 | 2 |
| 2 | default | 1111.272707 | 238 | 158 | 78 | 2 |
| 3 | organizer Sol agentic-BM25 | 734.746044 | 238 | 21 | 215 | 2 |

## Position audit and interpretation

The deterministic seed balanced but did not duplicate orientations. The judge
showed a substantial preference for the answer displayed as B, especially on
the close ours-vs-ours pair. Exact audit script:
`worklogs/assets/2026-08-07-ragdoll-arena-position-audit.py`.

| comparison | candidate | shown as A | shown as B |
|---|---|---:|---:|
| research-first vs baseline | research-first | 0.882353 (n=68) | 0.950980 (n=51) |
| default vs baseline | default | 0.848485 (n=66) | 0.971698 (n=53) |
| research-first vs default | research-first | 0.377049 (n=61) | 0.767241 (n=58) |

Therefore the requested conclusion is robust within this judge pass: **both
new runs beat the organizer Sol agentic-BM25 baseline regardless of display
position**. The research-first-vs-default ordering is not robust to display
position, so the 0.567 aggregate and 42.7-point arena gap should not be treated
as evidence that research-first is truly better without reverse-order judging
or an independent judge pass.

## Usage and cost accounting

The 357 authoritative raw Pi events report:

| calls | input | cache write | cache read | output | reasoning within output | total tokens |
|---:|---:|---:|---:|---:|---:|---:|
| 357 | 714 | 1,214,660 | 0 | 135,033 | 131,812 | 1,350,407 |

Pi treats the long prompt as cache-write input and the two-token file reference
as ordinary input. The temporary custom model entry had zero-valued Pi pricing,
so RAGDoll's `judgments.jsonl` reports `$0`; that is a reporting limitation, not
free usage. Applying the committed us-east-1 Luna prices ($1.10/M input,
$6.60/M output) to `(input + cacheWrite)` and output gives approximately
**$2.23**. Raw events retain the complete counters even though RAGDoll's compact
judgment usage object omits `cacheWrite`.

## Artifacts

Canonical result directory:

`data/outputs/ragdoll-arena/sol-test119-vs-organizer-sol-agentic-bm25-20260807/`

It contains the exact prompts, judgments, coverage, pairwise matrix,
arena-rank leaderboard, and all raw Pi event traces.
