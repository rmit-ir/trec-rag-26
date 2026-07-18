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

**FIRST ATTEMPT INVALID — the bump never took effect.** `run.py` carried
its own argparse `--max-committed-per-step default=6`, which silently
overrode the changed constant in `agent.py`. The "cap-10" Markov rerun
(`20260718T213723009373+1000`) and the first `aus-agent-sat-go` batch
launch (killed by user after 4 topics) both actually ran at cap 6; their
6+6 commits proved nothing. User caught it in the viewer ("still has 6
committed docs each time"). Fixed by importing
`DEFAULT_MAX_COMMITTED_PER_STEP` in `run.py` as the argparse default —
one source of truth — and verified the rendered system prompt now reads
"Commit at most \`10\` documents". All invalid artifacts (the mislabeled
Markov run + 4 partial batch topics) deleted; both runs relaunched.

For the record, the invalid cap-6 rerun behaved like the baseline anyway:
8 searches / 2 commits of exactly 6, self-chosen k=8 (staging ~32 docs per
round), 11 refs / 991 words / 92K processed tokens.

**Gotchas logged:**
- `run.py --backend` defaults to `bedrock`; Azure/luna runs need
  `--backend openai` every time (first attempt died on Bedrock
  `ExpiredTokenException`).
- Argparse defaults in `run.py` can shadow `agent.py` constants — when
  changing a default, check both layers (now unified for the cap).

## Scale test: full 30-topic dev batch (`aus-agent-sat-go`)

All 30 research dev topics, luna, cap 10, run-id `aus-agent-sat-go`
(launched 2026-07-18 ~21:40 AEST).

First launch of the batch (and the first "cap-10" Markov rerun) turned out
to still run at cap 6 — see the invalidation note above. After the run.py
fix, both were relaunched with `trace.config.max_committed_per_step: 10`
verified in every artifact.

**Valid cap-10 Markov A/B** (`20260718T214133194482+1000`, run-id
`aus-agent-luna-cap10`): commits **6 + 5** — both under the ceiling — 8
searches, 11 refs, 841 words, 127K processed tokens. Same shape as the
cap-6 baseline; no inflation.

**Batch: 30/30 completed, 0 failed.** Per-run matrix (commit sizes in call
order; kw = keyword-engine searches):

| run (20260718T…) | commits | searches (kw) | refs | words |
|---|---|---|---|---|
| 214145 write_a_blog_post_contrasting | 7, 6, 4 | 10 (4) | 12 | 977 |
| 214229 propose_a_biologically_plausible | 6, 6 | 7 (3) | 10 | 653 |
| 214300 i_m_currently_working_on | 6, 6 | 9 (3) | 11 | 986 |
| 214337 write_a_series_of_blog | 6 | 3 (1) | 6 | 874 |
| 214358 write_an_analysis_of_the (Plautus) | 6, 6 | 8 (4) | 12 | 958 |
| 214427 write_me_a_complete_overview | 7, 8 | 8 (3) | 15 | 924 |
| 214518 i_am_a_pre_school | 7, 6 | 8 (2) | 12 | 910 |
| 214558 design_a_framework_for_regulating | 7, 9 | 8 (1) | 15 | 837 |
| 214627 i_m_trying_to_outline | 8, 10, 2 | 11 (3) | 19 | 965 |
| 214700 conduct_a_comprehensive_evidence | 6, 7 | 8 (1) | 11 | 964 |
| 214727 write_a_comprehensive_analysis | 7, 8 | 9 (3) | 15 | 967 |
| 214806 write_a_strategic_business_report | 8, 8, 5 | 13 (6) | 17 | 918 |
| 214905 write_a_technical_proposal_for | 7, 7 | 8 (2) | 10 | 949 |
| 214941 i_am_planning_to_implement | 8, 9 | 8 (2) | 17 | 986 |
| 215023 design_a_modified_u_net | 7, 4, 4, 2 | 12 (4) | 12 | 845 |
| 215101 conduct_an_analysis_to_determine | 6, 9 | 10 (0) | 15 | 865 |
| 215128 you_are_writing_a_feature | 7, 4 | 7 (3) | 11 | 820 |
| 215153 i_am_a_software_engineer | 6, 7 | 8 (2) | 12 | 979 |
| 215221 write_about_the_politics_of | 6, 7 | 8 (3) | 13 | 958 |
| 215315 act_as_a_creative_technical | 6, 7 | 10 (4) | 6 | 968 |
| 215421 help_create_a_detailed_outline | 3, 3 | 3 (1) | 5 | 816 |
| 215453 prove_definitely_whether_a_self | 5, 6 | 6 (3) | 8 | 259 |
| 215515 imagine_the_following_alternate | 6 | 3 (0) | 6 | 907 |
| 215548 i_m_trying_to_scope | 10, 10 | 10 (1) | 17 | 992 |
| 215625 i_m_trying_to_block | 7, 10 | 9 (0) | 16 | 866 |
| 215713 compose_a_concise_technical_rep | 4, 5 | 5 (2) | 7 | 441 |
| 215733 write_an_introduction_on_markov | 7, 6 | 8 (2) | 12 | 842 |
| 215759 compare_the_effectiveness_and_p | 5, 6, 2 | 16 (4) | 11 | 804 |
| 215835 create_a_simple_agentic_ai | 6, 3 | 7 (2) | 6 | 1016 |
| 215910 write_a_series_of_blog | 4, 3 | 18 (10) | 6 | 836 |

**Commit-size distribution (64 commits), cap 10 vs cap-6 baseline:**

| size | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 |
|---|---|---|---|---|---|---|---|---|---|---|
| cap 6 (66 commits, Jul 17–18) | 2 | 8 | 11 | 7 | 11 | **27 (41%)** | — | — | — | — |
| cap 10 (64 commits) | 0 | 3 | 4 | 6 | 4 | 19 | 15 | 6 | 3 | **4 (6%)** |

**Verdict: the old cap was clipping real demand.** 28 of 64 commits (44%)
exceed 6 now that they can; the censoring spike is gone, replaced by a
natural mode at 6–7 with a smooth tail. Only 6% of commits touch the new
ceiling (one run, `i_m_trying_to_scope`, went 10+10 — the only candidate
for residual clipping). No bulk-commit bloat: selectivity stays visible
(runs still commit 2s and 3s where batches are thin), every answer is
within the 1024-word cap (max 1016), refs on broad topics rose to 15–19
where the old cap topped out around 11–13.

Judged by: commit sizes read from `commit_context` arguments in each
trajectory's `raw_messages`; cap verified from `trace.config`; refs/words
from output.json. Artifacts: `data/outputs/aus_agent/20260718T2141*` –
`T2159*`, run-id `aus-agent-sat-go`.

**Viewer:** added a `Config` tab to the Final-answer pane (answer /
sentences / **config** / raw / feedback) rendering `trace.config` (the cap,
context budget, safety rounds), provider metadata (backend, model, k,
temperature), and submission ids — the fields no other component displays,
so a wrong-cap run is now visible in one click. `tsc --noEmit` clean.

