# 2026-08-09 — native RAGDoll arena: 4 new test119 submissions vs organizer baseline

Follow-up to Kun Ran's `worklogs/2026-08-07-ragdoll-arena-sol-runs-vs-organizer-baseline.md`
(2026-08-07), which compared the two already-submitted `aus_agent`/`aus_agent_v2`
test119 files against the organizer's own baseline. This run extends the
same organizer-baseline comparison to the four systems prepared
2026-08-08 (`worklogs/2026-08-08-test119-*-submission.md`):
`brief_revise_agent` base, `brief_revise_agent` hybrid-alone, `facets_agent`,
`facet_rag`.

**`aus_agent`/`aus_agent_v2`'s test119 submission files are not present on
this machine** (confirmed absent from both `data/outputs/submissions/` and
the internal `data/outputs/{aus_agent,aus_agent_v2}/*.output.json` artifacts
-- a data-sync gap, not a re-run decision). This run is therefore a
**5-way** comparison (organizer baseline + the 4 new systems, 10 pairs), not
the 7-way comparison originally priced. `aus_agent`/`aus_agent_v2`'s own
organizer-baseline numbers remain Kun's separate 3-pair result and are not
re-merged into this run's leaderboard.

## Exact inputs

All five files contain 119 official test topics
(`data/official/trec-rag-2026-data/trec-rag-2026/test-data/trec_rag_2026_queries.tsv`,
SHA-256 `72dc2fd358d3eeda973397ccd7a8775545b19a6deaefc67709167eee6a9f8a2c`).

| run_id | source | SHA-256 |
| --- | --- | --- |
| `piika-gpt56sol-medium-agentic-bm25-rag` (organizer baseline) | `data/official/trec-rag-2026-data/trec-rag-2026/baselines/rag/gpt-5.6-sol_medium_agentic-search_bm25_output-mode-answer.jsonl` | `73c31a411248cfefa8afe9a8c5fbceb6fa9a4f083a442cd92d7bfdbd04686649` (matches Kun's own recorded checksum -- same file) |
| `brief-base-t119` | `data/outputs/submissions/brief-base-t119/rag_output_trec_rag_2026.jsonl` | `291765f4665301330afdf013b30a78c7a36942345c0a1d7c15415d4196d1ddc3` |
| `brief-hybrid-t119` | `data/outputs/submissions/brief-hybrid-t119/rag_output_trec_rag_2026.jsonl` | `8a42c111ad33eec5e88d0901f8fb5bb60c123802bf8d9912405d58ea6415d5c8` |
| `facets-t119` | `data/outputs/submissions/facets-t119/rag_output_trec_rag_2026.jsonl` | `03c5fa7a7e728690c54dc8229b19876c3526b4d3725203dfecd93a0ff7f1f99e` |
| `facetrag-t119` | `data/outputs/submissions/facetrag-t119/rag_output_trec_rag_2026.jsonl` | `2171112c6c2f38eaaeea6c052ced6bcaa196e1e1bd5156529fb214101cc4ebd5` |

## Setup (matches Kun's 2026-08-07 run except where noted)

- `evaluation/ragdoll` pinned at `1f0671908ab6dc581a61648463e3566ba413b480`
  (identical commit to Kun's run -- confirmed via `git rev-parse HEAD`).
- Pi binary: `evaluation/ragdoll/env/bin/pi`, v0.83.0 (already installed in
  this repo's own `env/`, gitignored -- **not** Kun's exact v0.84.0, an
  ephemeral `/tmp` install of his own; the model/prompt/judge, not the CLI
  wrapper version, is what determines judgment content, so this difference
  is not expected to matter).
- Judge model: `mantle/gpt-5.6-luna` via a custom Pi provider entry
  (`api: openai-responses`, pointed at the same Azure OpenAI-compatible
  gateway/`OPENAI_API_KEY` used everywhere else this session), thinking
  level `medium`, matching Kun's setup exactly.
- **Two new setup gotchas found this run, not documented before:**
  1. Pi's `models.json` must live inside whatever directory `--agent-state-dir`
     points at (`/tmp/ragdoll-pi-agent/models.json` here), **not** the
     global `~/.pi/agent/models.json` -- a custom `--agent-state-dir`
     silently ignores the global config. `ragdoll doctor --probe` (which
     uses the default state dir when no `--agent-state-dir` is passed)
     passed fine while the real arena run failed every task with
     `Error: Model "mantle/gpt-5.6-luna" not found` until the config was
     copied into the custom state dir too.
  2. The model `id` in `models.json` must be the bare Azure deployment name
     (`gpt-5.6-luna`, matching `src/agent_harness/providers/openai.py`'s
     `DEFAULT_MODEL_ID`), **not** `openai.gpt-5.6-luna` (the Bedrock-style
     prefixed id used elsewhere in this repo for Bedrock models) -- the
     prefixed form 404s with Azure's `DeploymentNotFound`. Also had to
     hardcode `baseUrl` as a literal rather than `$OPENAI_BASE_URL` --
     `models.json`'s documented `$VAR` interpolation did not resolve for
     the `baseUrl` field specifically (produced `Invalid URL`), only for
     `apiKey`.
- `models.json` used (real committed Bedrock-equivalent Luna rates, so
  RAGDoll's own `judgments.jsonl.usage.cost_usd` is real, not the
  zero-valued placeholder Kun had to work around manually):
  ```json
  {
    "providers": {
      "mantle": {
        "baseUrl": "https://trec-rag-2026-llm-resource.openai.azure.com/openai/v1",
        "api": "openai-responses",
        "apiKey": "$OPENAI_API_KEY",
        "models": [{
          "id": "gpt-5.6-luna",
          "reasoning": true,
          "contextWindow": 272000,
          "maxTokens": 8000,
          "cost": {"input": 1.10, "output": 6.60, "cacheRead": 1.10, "cacheWrite": 1.10}
        }]
      }
    }
  }
  ```

## Doctor probe

```bash
UV_CACHE_DIR=/tmp/ragdoll-uv-cache uv run ragdoll doctor --probe \
  --agent-binary evaluation/ragdoll/env/bin/pi --model mantle/gpt-5.6-luna
```

`doctor: PASS` after the two fixes above -- model responded in 6.94s.

## Preflight

`--sample-topics-per-pair 1 --sampling-seed 13`, same seed as the full run:
10/10 tasks completed (5 files -> $binom(5,2)=10$ pairs), 0 errors, strict
`[[A]]`/`[[B]]` verdicts parsed for all 10. Log:
`/tmp/ragdoll-arena-preflight-6systems-20260809.log` (session-local, not
committed).

## Full command

Run from `evaluation/ragdoll`:

```bash
set -a; source ../../.env; set +a
export OPENAI_API_KEY="$AZURE_OPENAI_API_KEY"
UV_CACHE_DIR=/tmp/ragdoll-uv-cache PI_OFFLINE=1 uv run ragdoll arena compare-all \
  --answers ../../data/official/trec-rag-2026-data/trec-rag-2026/baselines/rag/gpt-5.6-sol_medium_agentic-search_bm25_output-mode-answer.jsonl \
  --answers ../../data/outputs/submissions/brief-base-t119/rag_output_trec_rag_2026.jsonl \
  --answers ../../data/outputs/submissions/brief-hybrid-t119/rag_output_trec_rag_2026.jsonl \
  --answers ../../data/outputs/submissions/facets-t119/rag_output_trec_rag_2026.jsonl \
  --answers ../../data/outputs/submissions/facetrag-t119/rag_output_trec_rag_2026.jsonl \
  --output-dir ../../data/outputs/ragdoll-arena/test119-5way-vs-organizer-baseline-20260809 \
  --agent-binary "$(pwd)/env/bin/pi" --agent-state-dir /tmp/ragdoll-pi-agent \
  --model mantle/gpt-5.6-luna --thinking medium --seed 13 \
  --max-concurrency 8 --timeout-seconds 300 --overwrite
```

No `--sample-topics-per-pair`/`--sample-battles-*` flags -- every one of the
10 pairs judged on all 119 shared topics, single deterministic randomized
A/B order per `(pair, qid)` (seed 13), matching native `compare-all`
semantics exactly as Kun's run did (not the older custom wrapper's
duplicate reverse-order calls).

## Integrity audit

- 1,190 task rows = 1,190 judgment rows = 10 pairs × 119 topics.
- 1,190/1,190 `status=completed`; 0 errors; 1,190 unique `task_id`s.
- All 10 `coverage.csv` rows report 119 shared topics, 0 one-sided topics.

## Full result matrix

```
run_a                                   run_b               A wins  B wins  ties  A pref   B pref
organizer baseline                      brief-base-t119     19      99      1     0.164    0.836
organizer baseline                      brief-hybrid-t119   18      101     0     0.151    0.849
organizer baseline                      facets-t119         105     13      1     0.887    0.113
organizer baseline                      facetrag-t119       119     0       0     1.000    0.000
brief-base-t119                         brief-hybrid-t119   57      58      4     0.496    0.504
brief-base-t119                         facets-t119         114     4       1     0.962    0.038
brief-base-t119                         facetrag-t119       119     0       0     1.000    0.000
brief-hybrid-t119                       facets-t119         116     2       1     0.979    0.021
brief-hybrid-t119                       facetrag-t119       119     0       0     1.000    0.000
facets-t119                             facetrag-t119       118     1       0     0.992    0.008
```

Arena-rank leaderboard (native `arena-rank`, ties count half):

| rank | run | arena score | judgments | wins | losses | ties |
| ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | `brief-hybrid-t119` | 1487.23 | 476 | 394 | 77 | 5 |
| 2 | `brief-base-t119` | 1477.28 | 476 | 389 | 81 | 6 |
| 3 | organizer baseline | 1195.77 | 476 | 261 | 213 | 2 |
| 4 | `facets-t119` | 849.45 | 476 | 137 | 336 | 3 |
| 5 | `facetrag-t119` | -9.72 | 476 | 1 | 475 | 0 |

**Both `brief_revise_agent` variants clearly beat the organizer baseline
(83.6%/84.9% preference). `facets_agent` LOSES to the organizer baseline
(88.7% baseline preference, only 11.3% for `facets_agent`). `facet_rag`
loses to everything, including the baseline, 100% of the time (0/119).**
This is new, real evidence that two of this report's six recommended
submissions (`facets_agent`, `facet_rag`) would likely lose against the
organizers' own reference system specifically -- their inclusion rationale
(§10.3) was architectural diversity and evaluation-method hedging, not an
expectation of winning, and this result does not change that rationale, but
it should not be read as "these are competitive" either.

## Position audit

`worklogs/assets/2026-08-07-ragdoll-arena-position-audit.py`, reused
unmodified against this run's `judgments.jsonl`:

- Every organizer-baseline-vs-system pair is **robust to display
  position** -- e.g. `brief-base-t119` wins 77.6% as A and 87.9% as B
  against the baseline (same winner both ways, some magnitude drift).
  `facetrag-t119` loses 0% as A and 0% as B (perfectly robust).
- **`brief-base-t119` vs `brief-hybrid-t119` is the one pair whose winner
  flips with display position**: `brief-base-t119` wins only 34.5% as A but
  63.9% as B -- the near-tie 49.6%/50.4% aggregate should not be read as
  evidence either variant beats the other, the same caution this report's
  §6/§10.5 already raise for the base-vs-hybrid comparison on a different
  judge pass.

## Cost

RAGDoll's own `judgments.jsonl.usage.cost_usd` is real this run (the
`models.json` cost rates are the real committed Bedrock-equivalent Luna
prices, not Kun's zero-valued placeholder) -- summed directly, no manual
recomputation needed: **1,190 judgments, \$5.91 total** (\$0.00497/judgment
average -- cheaper than the \$0.743/pair, \$7.43-total estimate from
`worklogs/assets/2026-08-07-factor-analysis-report/report.typ` §10.5,
because `facets_agent`/`facet_rag`'s shorter answers, §10.4, reduced average
judgment token cost below the rate that estimate was based on, exactly as
that section's own caveat predicted).

## Artifacts

`data/outputs/ragdoll-arena/test119-5way-vs-organizer-baseline-20260809/`:
`tasks.jsonl`, `judgments.jsonl`, `coverage.csv`, `pairwise.csv`,
`leaderboard.csv`, `raw-events/` (1,190 raw Pi event files). Machine-local
under the synced `data/outputs/` tree (see `CLAUDE.md`'s data-sync notes) --
not committed to git.
