# 2026-07-18 — commit cap: 6 → 10 (`DEFAULT_MAX_COMMITTED_PER_STEP`)

**System:** `src/systems/aus_agent/`, luna via Azure.
**Change:** `agent.py` `DEFAULT_MAX_COMMITTED_PER_STEP = 6` → `10`. The
prompt's own wording ("Commit at most N documents from one staged batch;
usually commit fewer" — `prompts/system.md:141`) is untouched; N is injected
via `__MAX_COMMITTED_DOCS__`. 45/45 tests pass (they pin their own cap of 3,
so no fixture changes).

## Why: the cap was binding, and stale

User observation that runs kept committing exactly 6 (e.g. the Markov run
`20260718T010928526027+1000.write_an_introduction_on_markov`, both commits
n=6). Checked against all `data/outputs/aus_agent/2026071[78]T*` trajectories
(32 runs with commits, 66 `commit_context` calls), counting the `documents`
array length in each call's arguments:

| commit size | 1 | 2 | 3 | 4 | 5 | 6 |
|---|---|---|---|---|---|---|
| count | 2 | 8 | 11 | 7 | 11 | **27** |

- **41% of commits sit exactly at the cap** while sizes 1–5 are roughly
  flat — a right-censoring spike, not a natural tail. The model never once
  *attempted* >6 (no "selection exceeded per-step maximum" rejections
  anywhere), so it obeys the stated number and the spike is censored demand:
  how much more it wanted is invisible.
- **The cap predates the paired-engine search pattern.** Markov-run rounds
  staged ~24 docs each (4 queries × k=6, post-dedup 23–24), so cap 6 forced
  ~25% selectivity. When 6 was chosen, a round staged ~10 docs (one fused
  query, k=10) — 60% selectivity. Binary engines quadrupled per-round supply;
  the cap never moved.
- **Cost of raising is small.** The Markov run's own budget lines: 18,736 /
  500,000 tokens after commit 1, 38,743 after commit 2 — committed full
  texts run ~3K tokens each against a 500K budget. Cost of NOT raising is
  the expensive path: batch expiry is irreversible, so a wanted-but-dropped
  doc must be re-searched and re-staged.
- The anti-bulk-commit pressure is carried by the per-document
  "distinct contribution" reason requirement and "usually commit fewer",
  not by the specific integer, so both stay.

10 restores roughly the old 60% selectivity against ~24-doc rounds.

## Test: Markov topic rerun under cap 10

Same topic (qid `6847465956a0f6376a605493`, dev "Write an introduction on
Markov chains in the field of statistics/combinatorics…"), same model
(`gpt-5.6-luna`), run-id `aus-agent-luna-cap10`, vs baseline run
`aus-agent-luna-dev4` / `20260718T010928526027+1000` (8 searches, 2 commits
of exactly 6, 38.7K context after commits).

The decisive signal: commit sizes spreading into 7–10 means the demand was
real; staying ≤6 means the spike was anchoring on the stated number (and the
bump is free either way).

**Result (run `20260718T213723009373+1000`, completed):** 8 searches /
2 commits — and the commits are **exactly 6 + 6 again**, even though the
model raised its own `k` from 6 to 8 this run (staging ~32 docs per round,
selectivity ~19%). Output shape matches baseline: 11 refs, 36 sentences,
991 words, 92K processed tokens (baseline: 8 searches, 2×6 commits). On
this one topic the spike at 6 looks like genuine selectivity (or anchoring
on old habits), not clipped demand.

Query strings this run (all k=8): semantic "Markov chains genesis
statistics combinatorics history"; semantic "Markov chains contemporary
research applications literature review"; semantic "expected flips N heads
in a row Markov chain"; keyword "Markov chain definition transition
probabilities statistics combinatorics"; → commit 6; semantic "Markov
chains mixing times combinatorics statistical physics contemporary
research"; semantic "Markov chain Monte Carlo Bayesian statistics
contemporary research applications"; keyword "Andrey Markov 1906 Nekrasov
weak law independence motivation Markov chains"; semantic "Markov chains
combinatorial sampling counting algorithms random structures"; → commit 6.

**Gotcha logged:** first rerun attempt silently routed to Bedrock and died
on `ExpiredTokenException` — `run.py --backend` defaults to `bedrock`;
Azure/luna runs need `--backend openai` every time. Junk artifacts deleted.

## Scale test: full 30-topic dev batch (`aus-agent-sat-go`)

All 30 research dev topics, luna, cap 10, run-id `aus-agent-sat-go`
(launched 2026-07-18 ~21:40 AEST).

<!-- BATCH RESULTS -->

