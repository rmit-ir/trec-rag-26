# facet_rag §3.1 verification (DEFAULT_TOP_N + formatter floor), noise check, and §6.1/§6.2 shared infra

2026-08-05, same day as `2026-08-05-facet-rag-honest-rebaseline.md` and
`2026-08-05-facet-rag-maxchars-verification.md`. Two unrelated pieces of work
landed back to back: finishing PLAN.md §3.1's verification (the `--max-chars`
attempt alone didn't help; this is the follow-up raising `DEFAULT_TOP_N` and
adding a formatter length floor), and building the shared cost/timing
infrastructure from PLAN.md §6.1/§6.2.

## Part 1: DEFAULT_TOP_N 3->5 + formatter length floor

Code changes (commit `0f11a86`): `curator.py` `DEFAULT_TOP_N` 3->5;
`ali_deepresearch/prompts.py` `FORMAT_ANSWER_PROMPT` gained "preserve every
specific fact, figure, date, and name... a longer, fact-dense answer is
preferred" and "use as much of that budget as the DRAFT ANSWER's content
supports; do not artificially shorten it" (citation-attachment wording left
unchanged). Full suite green (1534 passed) before proceeding.

### Run

```sh
for q in 6847465956a0f6376a605404 6847465956a0f6376a60542a 683a58c9a7e7fe4e76958498 \
         684397d188c1deceb49af32d 6847465956a0f6376a60547e; do
  uv run --group facet-rag python src/systems/facet_rag/run.py --qid "$q" \
    --run-id facet_rag.top5floor_5topic \
    --run-desc "PLAN.md §3.1 verification: DEFAULT_TOP_N 3->5 + formatter length floor"
done
```

First attempt hung on CSGO (25 min, zero progress, one open-but-idle network
connection, no client-side timeout on that path) -- killed and relaunched
clean; second attempt completed all 5 in ~19 min. SCALING's first successful
run came back `status=no_references, refs=0, 0/60 sentences cited` despite
curation keeping 19/13/16/17/23 items across facets (all `covered=True`) --
retried once (`20260805T150247657382+1000...`), got `status=completed,
refs=20`. See "no_references anomaly" below.

Also ran 2 extra trials each on CSGO and SWARM (the two topics with the
biggest swings in the earlier `--max-chars`-only verification) for a noise
check under this same code.

### Resolve, UMBRELA, support (main 5-topic set)

Same pattern as the prior two verifications: `--doc-url` with
`--trajectory-dir` pointed at an empty directory to force the full-document
fallback. The Pyserini doc API was heavily rate-limited this session (429s on
first ~7 attempts on every resolve call today) -- resolved on retry with
20-30s backoff each time.

```sh
python3 scripts/resolve-rag-output-references.py data/outputs/facet_rag/<5-topic-set>/ \
    --trajectory-dir /tmp/no-trajectories-3 \
    --ragdoll-output evaluation-results/facet_rag/top5floor_5topic/answers.resolved.jsonl
# n=103, median=3853, pinned at 2000: 0

python3 scripts/ragdoll-answers-to-umbrela.py .../answers.resolved.jsonl \
    --output .../umbrela.input.jsonl
cd evaluation/ragdoll && uv run ragdoll umbrela judge \
    --provider amazon-bedrock --model openai.gpt-oss-120b-1:0 \
    --input-file .../umbrela.input.jsonl --output-file .../umbrela-bedrock-120/judgments.jsonl
# processed=103

uv run ragdoll support judge \
    --provider amazon-bedrock --model openai.gpt-oss-120b-1:0 \
    --input-file .../answers.resolved.jsonl \
    --output-file .../support-bedrock-120/judgments.jsonl \
    --raw-events-dir .../support-bedrock-120/raw-events
# processed=201
python3 scripts/ragdoll-support-to-csv.py .../judgments.jsonl \
    --output .../judgments.csv --summary-output .../judgments.summary.csv
```

### Result matrix: three facet_rag variants + aus_agent

```
                 words  words  words | cited%  cited%  cited% | UMBRELA mean         | support p_o_f
topic          (2k/t3)(20k/t3)(20k/t5+fl) (2k/t3)(20k/t3)(20k/t5+fl)  (2k/t3)(20k/t3)(20k/t5+fl)  aus_agent | (20k/t5+fl)
CSGO             365    317    571     100%    94%    86%      1.643  1.636  1.650   2.083     | 0.923
SCALING          460    591    987     100%    94%    73%      1.067  1.133  1.300   1.667     | 0.759
RETIRE           734    437    733     100%   100%    97%      1.417  1.500  1.579   1.583     | 1.000
PRESCHOOL        437    613    722      94%   100%   100%      0.857  0.800  0.762   1.467     | 0.807
SWARM            363    346    539      90%   100%   100%      1.200  0.800  1.087   1.294     | 0.783
mean             471.8  460.8  710.4
```

("2k/t3" = opus_plan_5topic baseline, 2000-char/top_n=3; "20k/t3" =
maxchars20k_5topic, 20000-char/top_n=3; "20k/t5+fl" = this run,
20000-char/top_n=5/formatter-floor.)

Aggregate support: `total=201, full_support=82, partial_support=87,
no_support=23, judge_errors=9, full_support_rate=0.407960,
partial_or_full_rate=0.840796` (vs opus_plan_5topic's 0.443/0.826 and
aus_agent-dev-full's 0.347/0.868).

**Verdict: this is the fix that actually worked, on 3 of 5 topics, at a real
cost.** Mean words jumped 461 -> 710 (the flat/mixed `--max-chars`-only
attempt never moved this). UMBRELA improved on CSGO/SCALING/RETIRE (RETIRE
1.579 vs aus_agent's 1.583 -- essentially matched) but PRESCHOOL got *worse*
(0.857 -> 0.762, now the worst of all three facet_rag variants) and SWARM only
partially recovered (0.800 -> 1.087, still below the 2k baseline's 1.200). The
cost is citation coverage: CSGO dropped to 86% cited, SCALING to 73% --both
now below the plan's >=95% target (A5), confirming §5's precision-vs-recall
tension is real and load-bearing, not theoretical. `DEFAULT_TOP_N`/formatter
floor bought words and (on most topics) UMBRELA at the price of A5's
citation-coverage lead.

### The no_references anomaly -- flagged, not fixed

SCALING's first `top5floor_5topic` attempt: curator kept plenty of evidence
per facet (19/13/16/17/23 items, all facets `covered=True`), the draft and
fact-check stages ran normally (visible in the trace as markdown-formatted
prose, ~1200 words), but the format-answer LLM call attached **zero
citations to all 60 sentences** -> `status=no_references`. Root-caused (not
fixed): `ali_deepresearch.answer_format.format_answer` passes the formatter
only bare docid *strings* as `ALLOWED DOCIDS` (`pipeline.py`'s
`docids = [e["docid"] for e in evidence]`) -- the model never sees the
evidence *text* at formatting time, so on this run it apparently judged (with
this session's stricter "GENUINELY AND DIRECTLY support" instruction,
unchanged from before) that it could not verify any citation against opaque
IDs alone, and correctly-by-its-own-logic cited nothing rather than guess.
This is PLAN.md §3.4's already-named gap ("a lossy re-write by a model that
never saw the evidence text") surfacing as a first real all-zero-citation
failure rather than just thin content. Retried the topic once (succeeded);
did not change the formatter's design this session -- that's §3.4's larger,
separate fix (parser not rewriter, or give the formatter the evidence text).

### Noise check

Word/cited%/refs computed directly from each run's `output.json` (no judging
needed) across 3 trials per topic (the `top5floor_5topic` run + 2 extra):

```
CSGO   trial1: words=571 cited%=86% refs=20
CSGO   trial2: words=536 cited%=100% refs=20
CSGO   trial3: words=547 cited%=91% refs=21
  -> words range 35 (~6% of mean 551.3); cited% range 14pts

SWARM  trial1: words=539 cited%=100% refs=23
SWARM  trial2: words=719 cited%=88% refs=20
SWARM  trial3: words=662 cited%=96% refs=21
  -> words range 180 (~29% of mean 640); cited% range 12pts
```

UMBRELA-level noise (judging the 2 extra trials) could not be completed: the
Pyserini doc API resolve for the noise-trial set failed all 30 retry attempts
(30s backoff, ~15 min) with persistent 429s -- this was a sustained outage,
not the usual transient flakiness (the main 5-topic set's resolve succeeded
on attempt ~7-8 earlier the same session). Not re-attempted further; the
word/cited%/refs spread above is what's available for the noise
characterization this session.

**Reading:** generation quantities (word count, reference count) are
reasonably stable run-to-run for a "narrower" topic (CSGO) but swing by
~30% for a "broader" one (SWARM) -- consistent with SWARM's already-noted
higher search-count variance (§3.3's "effort scales with the question").
Citation coverage (cited%) swings by 12-14 points on both regardless of
topic breadth. This means: a single-trial delta smaller than ~15 points of
cited% or ~30% of word count is not yet distinguishable from noise on these
two topics -- several of the deltas in the main comparison table above
(e.g. CSGO cited% 100%->86%, a 14-point drop) are right at that noise
boundary and should not be over-read without more trials.

## Part 2: shared cost + timing infrastructure (PLAN.md §6.1/§6.2)

Triggered by the user noticing no cost or wall-clock figure was visible for
any of today's runs. Confirmed live against a real Bedrock `converse()` call
that the response never carries a dollar figure -- only
`usage.{input,output,cacheRead,cacheWrite}Tokens` (top-level response keys:
`ResponseMetadata`, `output`, `stopReason`, `usage`, `metrics` -- no billing
field anywhere) -- so cost must always be *computed* from a committed rate
table, never read off a response. User separately asked for an "empirical"
cost pulled from the response; corrected that no such field exists, and
scoped out AWS Cost Explorer/CUR reconciliation (24-48h lag, daily account
aggregate, not per-call) as a deliberately-skipped follow-up rather than
building it blind.

### What was built

- `src/ragrun/pricing.py` -- `Rates`/`load_rates`/`call_cost`/
  `cost_for_provider`, ported from `tasks/bm25_tune/bm25tune/pricing.py`
  (budget-ceiling/ledger machinery left behind per PLAN.md §6.1's own
  guidance). `load_rates` matches by table *content* (`model_id`/`region`
  fields), not filename, so a caller never needs a dated table id.
  `call_cost` bills `input_uncached + cache_write` at the input rate and
  treats `cache_read` as free (documented `# ponytail:` comment -- no
  separate cache-read rate exists in the committed tables).
- Two rate tables fetched from the real AWS Pricing API and committed:
  `src/ragrun/prices/bedrock-openai-gpt-oss-120b-1-0-apsoutheast2-2026-08-05.json`,
  `...-qwen-qwen3-next-80b-a3b-useast1-2026-08-05.json` -- facet_rag's two
  models, the ones actually driving today's spend.
- `BedrockProvider.region` (`aus_agent/providers/bedrock.py`) -- previously
  the region was passed straight into the boto3 client constructor and
  discarded; now stored so cost/provenance code can read it off a live
  provider the same way `.model_id` already worked.
- `TrajectoryBuilder.finalize()` (`ragrun/trajectory.py`) gained two pure
  rollups, both zero-wiring for any system that doesn't opt in:
  - `trace.summary.cost = {usd, priced_calls, unpriced_calls}` -- sums every
    step's `stats.cost.usd`; a step with tokens but no cost block counts as
    "unpriced" rather than silently vanishing from the total.
  - `trace.summary.duration = {total_ms, by_type_ms, steps_with_duration,
    steps_total}` -- sums `stats.duration_ms` by step `type`; the coverage
    counts exist because most systems only timestamp a subset of steps today.
- facet_rag wired end-to-end (`pipeline.py`): `run_one` gained
  `orchestrator_region`/`analyzer_region` params (threaded from `run.py`'s
  existing `--orchestrator-region`/`--analyzer-region` flags, defaults
  `ap-southeast-2`/`us-east-1` matching the CLI's own defaults), builds two
  `Rates` objects once up front, and a `_stats(tokens, rates)` helper attaches
  `cost` at all 6 call sites (plan, per-facet orchestrator turns, per-facet
  analyzer/curator turns, draft, fact-check).
  **Bonus fix found while wiring this:** the format-answer LLM call
  (`_ProviderLLM(make_orchestrator())`) had no trace step at all before
  today -- its tokens and cost were completely invisible, not just unpriced.
  It now gets its own `"format"` step (`turn` bumped accordingly; fact_check
  and the final `output_text` step no longer silently share a turn number
  with each other or with format).

### Verification

Live run (2-facet CSGO, cheap): `trace.summary.cost = {"usd": 0.031069,
"priced_calls": 16, "unpriced_calls": 0}`, `trace.summary.duration =
{"total_ms": 135784, "by_type_ms": {"reasoning": 1706, "generation": 25543,
"output_text": 19211}, "steps_with_duration": 5, "steps_total": 30}`. Every
model call in that run priced; the duration rollup's own coverage counts
(5/30) re-confirm PLAN.md §6.2's already-known gap that `_replay_events`'
per-facet steps still don't set `t_start`/`t_end` -- the rollup surfaces that
gap rather than hiding it.

Tests: `tests/shared/test_pricing.py` (7 tests -- rate matching, unit-guard
against a per-token/per-1K-token 1000x mispricing bug, cost arithmetic worked
out by hand, unpriced model degrades to `None` not a crash) and 4 new tests
in `tests/contract/test_output_trajectory.py` (duration/cost rollup presence
and absence). Full suite: 1545 passed (was 1534), 0 skipped.

### Still open

- Per-role cost/time rollup (orchestrator vs. analyzer vs. curator) -- the
  total exists, nothing yet slices it by role. This is what's actually needed
  to answer §4 item 2.2 ("was the curator's extra call worth it") with a
  number.
- The per-stage timing coverage gap itself (only 5/30 steps timestamped on a
  real run) -- fixing `_replay_events` to carry real `t_start`/`t_end`
  through from the loop events is separate from the rollup built today.
- aus_agent and the other 3 systems don't attach `stats.cost` yet -- the
  rollup mechanism is generic and ready, but only facet_rag is wired.

## Artifacts

- `evaluation-results/facet_rag/top5floor_5topic/` (resolved answers, UMBRELA
  and support judgments)
- `evaluation-results/facet_rag/top5floor_noise/` -- resolve never completed
  (persistent 429s), directory absent
- `src/ragrun/pricing.py`, `src/ragrun/prices/*.json`
- `tests/shared/test_pricing.py`
