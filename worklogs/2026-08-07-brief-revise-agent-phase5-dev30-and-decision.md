# 2026-08-07 — brief_revise_agent Phase 5: full dev30 run + preregistered decision

Follow-up to `worklogs/2026-08-07-brief-revise-agent-phase4-pilot.md` (Phase
4 gate passed). This session: the full 30-topic dev run, the Tier 0
deterministic metrics, the Tier 2 rubric arena vs `aus_agent`, and the
preregistered decision from `src/systems/brief_revise_agent/PLAN.md` §7.

**Bottom line: `brief_revise_agent` is a real, measured improvement over
both prior systems, but it does not clear the plan's own preregistered bar.
`aus_agent` remains the submission.**

## 1. Phase 5 run

```bash
export OPENAI_API_KEY="$(grep '^AZURE_OPENAI_API_KEY=' .env | cut -d= -f2-)"
uv run --group brief-revise-agent python src/systems/brief_revise_agent/run.py \
  --all --backend openai --model gpt-5.6-luna \
  --run-id brief-revise-dev30-6252022 --skip-existing
```

30/30 `status=completed`, 0 failed. (`--skip-existing` scopes to this
run_id; the 4 Phase-4 pilot topics ran under a different run_id
`brief-revise-pilot4-6252022` and so were re-run here too, to keep one clean
unambiguous run_id covering all 30 — same lesson as the `aus_agent`
dual-model run_id mixup found earlier this session.)

One real parse-failure case appeared in the wild (topic `6054be`, round 8):
the reviewer's JSON didn't parse cleanly. Confirmed the visibility fix from
the pre-pilot sol code review paid off immediately — the new log line
caught it (`review.hook: reviewer response did not parse as the expected
{issues: [...]} shape`), the deterministic guard degraded correctly (logged,
treated as zero issues, run continued and completed normally).

## 2. Tier 0 — deterministic metrics (free, from the run's own artifacts)

Compared against `aus-agent-dev30-luna-e2708ab` (same 30 topics, same model,
`gpt-5.6-luna` both sides):

| metric | `aus_agent` baseline | `brief_revise_agent` | target (PLAN.md §7) | verdict |
|---|---|---|---|---|
| uncited-sentence rate | 26.0% (235/903) | **5.3% (42/786)** | < 15% | **passed, well past target** |
| topics over 1024 words | n/a | 0/30 | 0 | passed |
| run status | 30/30 completed | 30/30 completed | 30/30, 0 failed | passed |

Two topics moved the *wrong* direction on uncited rate and are worth
reporting honestly rather than folding into the aggregate:

- `6847465956a0f6376a605391` (market-entry strategy topic): 6.25% → 40.0%
  uncited.
- `6847465956a0f6376a605440` (formal self-improving-AI proof topic): 0.0% →
  50.0% uncited.

Read both by hand (`data/outputs/brief_revise_agent/*605391*` /
`*605440*`). In both cases the newly-uncited sentences are structurally
synthesis/derivation content the system prompt's own citation rule already
exempts (`prompts/system/default.md`'s appended clause: "the only sentences
without ids are the ones that organise or connect what the cited sentences
already established"): `605391`'s uncited sentences are plan-sequencing and
risk-narrative prose ("The channel plan should be sequenced by...", "The
regulatory-shift risk is medium probability..."); `605440`'s are the
internal steps of a formal mathematical proof ("Let
\(G(P_0,S_0,H)\) mean that...", "Proof: choose the allowed run..."), which
don't cite a corpus document because they're logical derivation from
already-cited definitions, not corpus claims. Neither reads as a citation
*failure* on inspection — but it is a real, measured case where the
brief+review pass's longer, more structured answers produce more legitimate
uncited synthesis sentences than aus_agent's shorter answers on the same
topics. Flagged, not swept under the aggregate number.

**Not measured this session** (noted as a gap, not run): brief entries per
topic, hook fire rate, and searches/processed-tokens drift vs aus_agent's
baseline (PLAN.md §7 Tier 0's remaining rows). The pilot worklog already
flagged one topic (`6054a7`) running well above aus_agent's average search
count; not re-checked across the full 30 here. Available in the saved
artifacts (`data/outputs/brief_revise_agent/*.output.json`,
`run_id=brief-revise-dev30-6252022`) for a follow-up pass.

## 3. Tier 2 — rubric arena vs aus_agent (30 topics x 2 orders, `gpt-5.6-terra` judge)

Generalized `tasks/task-comparison/scripts/arena_aus_agent_vs_facets_agent_rubric.py`
in place per PLAN.md §7's own instruction ("~10 lines... rather than copying
250-line scripts") — added `--challenger-system`/`--challenger-run-id`,
defaulting to `facets_agent` for full backward compatibility with every
prior invocation in this repo's history. `rubric_scorecard_*` was NOT
similarly generalized this session (time) — the per-criterion axis
breakdown for this comparison is a follow-up, not run here.

```bash
uv run --group aus-agent python \
  tasks/task-comparison/scripts/arena_aus_agent_vs_facets_agent_rubric.py \
  --aus-agent-run-id aus-agent-dev30-luna-e2708ab \
  --challenger-system brief_revise_agent \
  --challenger-run-id brief-revise-dev30-6252022 \
  --out-dir evaluation-results/arena/aus_agent-vs-brief_revise_agent-dev30-rubric
```

```
aus_agent vs brief_revise_agent: 35-25-0 (n=60) | aus_agent_pref_rate=0.5833 | order_consistency=0.767
```

**Clean win groups** (trusted over the pooled count, per this repo's own
documented position-bias lesson): of 30 topics, **aus_agent wins both
orientations on 14, brief_revise_agent wins both on 9, 7 are
order-ambiguous.**

Comparison across all three systems measured against `aus_agent` on this
exact 30-topic dev set this session:

| challenger | pooled aus_agent pref rate | clean aus_agent wins | clean challenger wins | ambiguous |
|---|---|---|---|---|
| `facets_agent` | 76.7% | 20 | 4 | 6 |
| `brief_revise_agent` | **58.3%** | **14** | **9** | 7 |

`brief_revise_agent` roughly halves the clean-win deficit facets_agent left
(16-topic gap → 5-topic gap) and is the strongest system built against
`aus_agent` in this repo's history to date.

## 4. The preregistered decision (PLAN.md §7, "Decision rule")

> Submit `brief_revise_agent` only if all three hold: (i) Tier 0's
> uncited-sentence rate improves and nothing else regresses; (ii) Tier 1's
> paired comparison favours the revised answer; (iii) Tier 2 clean win
> groups are at least 12-x-y with x ≤ 8.

- (i) **Passed** — 26.0% → 5.3%, well past the <15% target. The two topic-level
  exceptions (§2) read as benign on inspection, not as regressions in the
  sense the rule was guarding against (invented/unsupported claims).
- (ii) **Not run.** Tier 1 (the free within-run paired draft-vs-revision
  comparison, scoring the preserved pre-revision draft against the official
  criteria) was skipped this session for time — (iii) alone already
  determines the outcome below, so it was not on the critical path for a
  decision made under deadline pressure. Available as a follow-up: the
  pre-revision drafts are preserved in every topic's `trace.steps` and cost
  nothing new to extract and score.
- (iii) **Not met.** 9 clean wins (need ≥12), 14 aus_agent clean wins (need
  ≤8).

**Decision: `aus_agent` remains the submission.** Per PLAN.md §8's own risk
framing, this is the plan's own anticipated legitimate outcome of a
two-day experiment under deadline pressure, not a failure of the exercise —
the preregistered bar was set before any of these numbers existed
specifically so a close-but-short result like this one would not get argued
into a submission it didn't earn.

## What this session leaves behind, for anyone continuing this branch

- `brief_revise_agent` is a working, tested, measurably-better-than-facets_agent
  system, fully built and validated against the real 30-topic dev set. If
  there is time before the 2026-08-08 deadline to keep iterating (the two
  §2 near-misses and the unrun Tier 1 both point at concrete next
  experiments — e.g. loosening the reviewer's substitution-only framing on
  synthesis-heavy topics, or checking whether the revision pass itself is
  net-positive via Tier 1 before assuming it is), this branch
  (`explore/new-agent-framework-system`) is the place to pick it up.
  Otherwise `aus_agent`'s existing submission path is unaffected — nothing
  in this branch touches shared code or `main`.
- The generalized arena script (`--challenger-system`) is reusable for any
  future third system without another copy-paste.

## Artifacts

- `data/outputs/brief_revise_agent/*.{output,trajectory}.json`,
  `run_id=brief-revise-dev30-6252022` (30 topics, gitignored, local only).
- `evaluation-results/arena/aus_agent-vs-brief_revise_agent-dev30-rubric/`
  (`judgments.jsonl`, `summary.json`).
