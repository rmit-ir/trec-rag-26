# 2026-08-06 — facets_agent Phase 4a (post-bugfix v2) vs aus_agent, full 30-topic dev set

Follow-up to `worklogs/2026-08-06-facets-agent-phase4a-coverage-gate.md`
(Phase 4a: `pre_final_hook` coverage gate, shipped commit `e2708ab`, one real
bug caught and fixed mid-implementation before that commit). This session
ran the first full-dev-set (30/30 topics, not the earlier 15-topic subset)
rubric arena of facets_agent-v2 against aus_agent, both on `gpt-5.6-luna`.

## Inputs

- **facets_agent answers**: `data/outputs/facets_agent/*.output.json`,
  `run_id=facets-agent-dev30-e2708ab`, 30/30 topics, generated at commit
  `e2708ab` (current HEAD's ancestor at session start) — already existed in
  the synced `data/outputs/` dir from an earlier same-day run, reused as-is
  (no rerun, no cost).
- **aus_agent answers**: `data/outputs/aus_agent/*.output.json` originally
  under `run_id=aus-agent-dev30-20260806`, but that id ambiguously mixed
  **two models' 30-topic batches** (`bedrock/au.anthropic.claude-sonnet-5`
  and `openai/gpt-5.6-luna`), which would have made
  `load_answers_from_outputs` raise (`duplicate qid ... for run_id`). Since
  the rubric-arena convention holds the model fixed across systems (per
  `arena_aus_agent_vs_facets_agent_rubric.py`'s own docstring — both ran
  `gpt-5.6-luna` for the 15-topic comparison too), the `gpt-5.6-luna` batch
  is the correct one to use. Relabelled those 30 files (output + trajectory
  pairs) into new files with `metadata.run_id` rewritten to
  `aus-agent-dev30-luna-e2708ab`, originals untouched, zero API cost. Script:
  `worklogs/assets/2026-08-06-relabel-aus-agent-luna-dev30.py`.
  Caveat: those aus_agent answers were generated ~2h before the
  `agent_harness` extraction refactor (commit `3d5d745`, 2026-08-06
  01:56:24-0400) landed; that refactor's own worklog claims byte-identical
  behaviour, verified by the full offline suite, so treated as equivalent —
  not independently re-verified against the reran state.
- **Rubric source**:
  `data/official/trec-rag-2026-data/trec-rag-2026/development-data/researchrubrics-dev-rubrics/research-rubrics-dev-rubrics.jsonl`
  (~31 weighted criteria/topic, official ResearchRubrics dev set).
- **Judge**: `gpt-5.6-terra` (generated neither system's answers — no
  self-preference confound), pairwise + rubric-guided
  (`PAIRWISE_ANSWER_COMPARISON_W_RUBRICS`), both battle orders judged and
  pooled, plus a separate per-criterion scorecard pass.

## Commands run

```bash
uv run --group aus-agent python \
  tasks/task-comparison/scripts/arena_aus_agent_vs_facets_agent_rubric.py \
  --aus-agent-run-id aus-agent-dev30-luna-e2708ab \
  --facets-agent-run-id facets-agent-dev30-e2708ab \
  --out-dir evaluation-results/arena/aus_agent-vs-facets_agent-dev30-rubric

uv run --group aus-agent python \
  tasks/task-comparison/scripts/rubric_scorecard_aus_agent_vs_facets_agent.py \
  --aus-agent-run-id aus-agent-dev30-luna-e2708ab \
  --facets-agent-run-id facets-agent-dev30-e2708ab \
  --out-dir evaluation-results/arena/aus_agent-vs-facets_agent-dev30-rubric
```

Artifacts: `evaluation-results/arena/aus_agent-vs-facets_agent-dev30-rubric/`
(`judgments.jsonl`, `summary.json`, `criterion_scorecard_summary.json`,
`criterion-scores/`, `raw-events/`).

## Result: pairwise arena (30 shared topics x 2 orders = 60 battles)

```
aus_agent vs facets_agent: 46-14-0 (n=60) | aus_agent_pref_rate=0.7667 | order_consistency=0.8
```

**Clean win/loss groups** (per PLAN.md's own methodology — trust this over
the pooled count, given the documented position bias): of 30 topics,
**aus_agent wins both orientations on 20, facets_agent wins both on 4, 6 are
order-ambiguous (split verdict)**.

Comparison point: the pre-Phase-4a 15-topic run (`2026-08-06-facets-agent-loss-factor-analysis.md`)
measured aus_agent winning **86.7%** of rubric battles. This 30-topic
post-Phase-4a run measures **76.7%** — a directional improvement, but not a
controlled A/B (different topic set, n doubled) and Phase 4a's own worklog
never ran this comparison, so treat this as suggestive, not confirmed.
facets_agent is still clearly behind.

### Full per-topic table (o0/o1 = judge's preferred system under each battle order; group = clean win / ambiguous)

| topic_id | o0 pref | o1 pref | group |
|---|---|---|---|
| 683a58c9a7e7fe4e7695846f | aus_agent | aus_agent | aus_agent |
| 683a58c9a7e7fe4e76958488 | aus_agent | aus_agent | aus_agent |
| 683a58c9a7e7fe4e7695848b | facets_agent | facets_agent | facets_agent |
| 683a58c9a7e7fe4e76958498 | facets_agent | facets_agent | facets_agent |
| 684397d188c1deceb49af31d | aus_agent | aus_agent | aus_agent |
| 684397d188c1deceb49af325 | aus_agent | aus_agent | aus_agent |
| 684397d188c1deceb49af32d | aus_agent | aus_agent | aus_agent |
| 6847465956a0f6376a60535d | aus_agent | aus_agent | aus_agent |
| 6847465956a0f6376a605360 | aus_agent | aus_agent | aus_agent |
| 6847465956a0f6376a605367 | aus_agent | aus_agent | aus_agent |
| 6847465956a0f6376a605387 | facets_agent | aus_agent | ambiguous |
| 6847465956a0f6376a605391 | aus_agent | aus_agent | aus_agent |
| 6847465956a0f6376a6053a0 | facets_agent | aus_agent | ambiguous |
| 6847465956a0f6376a6053c9 | facets_agent | facets_agent | facets_agent |
| 6847465956a0f6376a6053ca | aus_agent | facets_agent | ambiguous |
| 6847465956a0f6376a6053fb | aus_agent | aus_agent | aus_agent |
| 6847465956a0f6376a605404 | aus_agent | aus_agent | aus_agent |
| 6847465956a0f6376a60542a | aus_agent | aus_agent | aus_agent |
| 6847465956a0f6376a60542d | aus_agent | aus_agent | aus_agent |
| 6847465956a0f6376a605433 | facets_agent | aus_agent | ambiguous |
| 6847465956a0f6376a60543d | aus_agent | facets_agent | ambiguous |
| 6847465956a0f6376a605440 | aus_agent | aus_agent | aus_agent |
| 6847465956a0f6376a605476 | facets_agent | aus_agent | ambiguous |
| 6847465956a0f6376a60547e | aus_agent | aus_agent | aus_agent |
| 6847465956a0f6376a60547f | aus_agent | aus_agent | aus_agent |
| 6847465956a0f6376a605492 | aus_agent | aus_agent | aus_agent |
| 6847465956a0f6376a605493 | aus_agent | aus_agent | aus_agent |
| 6847465956a0f6376a6054a7 | facets_agent | facets_agent | facets_agent |
| 6847465956a0f6376a6054ad | aus_agent | aus_agent | aus_agent |
| 6847465956a0f6376a6054be | aus_agent | aus_agent | aus_agent |

## Result: per-criterion scorecard

Overall grade (0-3) by arena-outcome group:

```
aus_agent      n=20  aus_agent=2.10  facets_agent=1.85
facets_agent   n= 4  aus_agent=1.50  facets_agent=1.50
ambiguous      n= 6  aus_agent=1.67  facets_agent=1.33
```

`criterion_tally` (differing criteria summed across all criteria in the
group, not averaged per topic — the script's own documented "trust this over
per-topic average on sparse axes" lesson):

**aus_agent-clean-win topics (n=20):**

| axis | n | tied | aus_better | facets_better |
|---|---|---|---|---|
| Implicit Criteria | 204 | 140 | 38 (w=66.5) | 26 (w=46.0) |
| Explicit Criteria | 149 | 112 | 23 (w=55.0) | 14 (w=28.0) |
| Synthesis of Information | 76 | 54 | 14 (w=21.0) | 8 (w=9.5) |
| Communication Quality | 35 | 26 | 3 (w=9.0) | 6 (w=7.5) |
| Instruction Following | 22 | 19 | 3 (w=4.5) | 0 (w=0.0) |
| References & Citation Quality | 12 | 8 | 1 (w=2.5) | 3 (w=11.0) |
| Miscellaneous | 1 | 1 | 0 | 0 |

**facets_agent-clean-win topics (n=4):**

| axis | n | tied | aus_better | facets_better |
|---|---|---|---|---|
| Implicit Criteria | 54 | 40 | 4 (w=6.0) | 10 (w=22.0) |
| Explicit Criteria | 24 | 15 | 6 (w=12.5) | 3 (w=6.0) |
| Communication Quality | 12 | 12 | 0 | 0 |
| Synthesis of Information | 8 | 6 | 0 | 2 (w=3.0) |
| Instruction Following | 7 | 7 | 0 | 0 |
| References & Citation Quality | 3 | 3 | 0 | 0 |

**ambiguous topics (n=6):**

| axis | n | tied | aus_better | facets_better |
|---|---|---|---|---|
| Implicit Criteria | 57 | 41 | 9 (w=18.5) | 7 (w=10.5) |
| Explicit Criteria | 38 | 28 | 3 (w=7.0) | 7 (w=15.5) |
| Synthesis of Information | 24 | 15 | 7 (w=11.5) | 2 (w=2.0) |
| Instruction Following | 14 | 10 | 0 | 4 (w=5.5) |
| Communication Quality | 12 | 10 | 1 (w=4.0) | 1 (w=0.5) |
| References & Citation Quality | 3 | 3 | 0 | 0 |

## Reading

`Implicit Criteria` and `Explicit Criteria` still carry the most weight and
the most differing calls in both directions, on every group — consistent
with the loss-factor-analysis diagnosis (`not_decomposed` +
`covered_but_shallow`, ~47% each) not being fully closed by Phase 4a's
coverage gate alone. `Synthesis of Information` is the one axis where
facets_agent's 4 clean wins show a real edge (2/8 facets-better, 0
aus-better) even though the same axis favours aus_agent everywhere else —
too small an n (4 topics) to generalize from.

## Not done this session

- No fresh Tier-2 LLM diagnosis (root-cause classification of the remaining
  losses) — this worklog only reports the arena/scorecard numbers, it
  doesn't re-run `worklogs/assets/2026-08-05-llm-diagnosis.py`-style
  classification against the new losses.
- The 15-vs-30-topic comparison above is not a controlled Phase-4a A/B (no
  pre-Phase-4a 30-topic baseline exists) — if a clean before/after number is
  needed, aus_agent's dev30-luna answers already exist and only
  facets_agent would need a pre-`e2708ab` 30-topic rerun.
