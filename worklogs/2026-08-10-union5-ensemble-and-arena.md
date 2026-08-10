# 2026-08-10 — 5-run extractive ensemble (`sol-union5-t119`) and sol-judged 5-way arena

Builds the candidate-union ensemble described in
`docs/extractive-eight-run-candidate-union.md` over the test119 runs available
on this box plus Oleg's, then compares it against three systems and the
organizer baseline with a native RAGDoll arena.

**Headline: the ensemble ranks first, and beats its own anchor 78.6% — but that
margin is substantially confounded by answer length (see §Length confound). Two
of its three inter-system margins flip with display position and are not
reliable.**

## Data-sync finding (acted on, not fixed)

`data/outputs` on this box is a **real directory, not the symlink** `CLAUDE.md`
describes. `evaluation-results` *is* correctly symlinked. Consequence: our
test119 runs and Oleg's have forked — his five full-coverage runs were invisible
to `union_run.py`'s scanner, which globs `data/outputs/*/*.output.json`.

Worked around by symlinking his two needed system dirs in (verified `Path.glob`
traverses symlinked dirs for non-`**` patterns):

```bash
ln -s /research/remote/petabyte/users/oleg/trec_rag_26_data/outputs/brief_revise_agent data/outputs/brief_revise_agent
ln -s /research/remote/petabyte/users/oleg/trec_rag_26_data/outputs/open_weight_agent  data/outputs/open_weight_agent
```

The underlying fork was **not** reconciled — that is a merge of two diverged
trees and needs an explicit decision.

## Source runs

Nine full-coverage (119-topic) test119 runs exist across both trees.
`candidate_union.py:28` caps `MAX_CANDIDATES = 8`, so "all runs" was not
possible. Operator chose the five strongest:

| run_id | tree | note |
| --- | --- | --- |
| `sol-aus-v2-research-first-test119-20260807` | ours | **anchor** |
| `sol-aus-default-test119-20260807` | ours | |
| `brief-revise-base-test119-20260808` | Oleg's | beat organizer 83.6% (08-09 arena) |
| `brief-revise-hybrid-test119-20260808` | Oleg's | arena #1 in 08-09 run |
| `open-weight-agent-glm5-test119-20260809` | Oleg's | unmeasured before this run |

Excluded: `facet-rag-test119-20260808` (0/119 vs everything, 08-09),
`facets-agent-test119-20260808` (loses to organizer baseline),
`test-keyword-119` / `test-semantic-119` (single-engine ablations, median 14/16
cited docs vs 28/29 for the sol runs).

## Union run

`--prepare-only` over all 119 topics first (free): 119/119 packets built, zero
failures. `request_chars` min/med/max 31,296 / 43,876 / 52,720;
`candidate_items` 82 / 109 / 192; `anchor_words` 731 / 951 / 1024.

Paid command (per-topic selector, one call each):

```bash
TOPICS=data/official/trec-rag-2026-data/trec-rag-2026/test-data/trec_rag_2026_queries.tsv
CANDIDATE_ARGS=(
  --candidate-run sol-aus-v2-research-first-test119-20260807
  --candidate-run sol-aus-default-test119-20260807
  --candidate-run brief-revise-base-test119-20260808
  --candidate-run brief-revise-hybrid-test119-20260808
  --candidate-run open-weight-agent-glm5-test119-20260809
  --anchor-run sol-aus-v2-research-first-test119-20260807
)
set -a; source .env; set +a
uv run --group aus-agent-v2 python src/systems/aus_agent_v2/union_run.py \
  --topics "$TOPICS" --all --skip-existing \
  --backend openai --model openai.gpt-5.6-sol \
  --run-id sol-union5-t119 \
  --run-desc "extractive candidate union over 5 complete test119 runs (anchor sol-aus-v2-research-first); immutable answer-item selection with deterministic citation remapping" \
  --budget-cap 1500 --per-topic-reserve-usd 10 \
  "${CANDIDATE_ARGS[@]}"
```

Result: **119/119 `accepted: true`** after retrying two topics. Answer words
min/med/max 821 / 1000 / 1024, none over the cap.

### Two fallbacks, retried

A fallback writes a `completed` artifact containing the anchor verbatim, so
`--skip-existing` silently keeps it. Both were deleted and re-run individually;
both then accepted. Verbatim selector errors:

- `rag2026-21` — attempt 1: `anchor replacement row 1 names anchor item
  'C02:I15' as a replacement` (also `C02:I16`, `C02:I23`, `C02:I25`);
  attempt 2: `coverage row 1 must name 1-8 selected items`, `selected items
  lack coverage rows: C02:I01, C02:I02, C04:I02`. Retry: accepted, 979 words.
- `rag2026-44` — attempt 1: `coverage row 4 must name 1-8 selected items`,
  `coverage row 5 …`, `selected items lack coverage rows: C01:I09, C03:I15,
  C03:I16, C03:I17, C03:I18, C03:I21, C01:I18, C03:I22, C03:I23, C03:I24,
  C03:I25, C03:I26, C01:I28`; attempt 2: `compiled answer is 1040 words;
  maximum is 1024`. Retry: accepted, 1014 words.

An earlier smoke test failed with `anchor_after_invalid_union` from an expired
credential (`Signature expired: 20260807T160742Z`), $0 spent; that artifact was
deleted before the batch.

## Submission export and validation

```bash
uv run python scripts/export-rag-submission.py data/outputs/aus_agent_v2 \
  --output data/outputs/submissions/sol-union5-t119/rag_output_trec_rag_2026.jsonl \
  --run-id sol-union5-t119 --topics "$TOPICS"
```

119 rows. `run_id` is 15 chars, within rag26's 20-char run-tag limit, so no
`--output-run-id` rewrite was needed.

```bash
uv run --no-project --with "autojudge-base>=0.4.3" python -m autojudge_base.report_tool check \
  data/outputs/submissions/sol-union5-t119/rag_output_trec_rag_2026.jsonl \
  --spec rag26 --topics <Request-format topics JSONL>
```

→ `119/119 reports valid against rag26`, `[coverage] all 119 topics present`,
exit 0.

## Readability check (does splicing hurt prose?)

Measured over the 90 accepted topics available mid-batch. Provenance recovered
by matching union item text byte-for-byte against each source run's items.

- Anchor supplies ~88% of items. Median 25 items/answer, **3 imported**, 4 seams.
- Dangling-anaphora openers (`This|These|However|Instead|…`):
  **4.3%** (19/443) immediately after a seam, vs **5.8%** (104/1808) mid-run and
  **5.2%** (110/2123) in the anchor's own answers — i.e. *not* elevated.
- Redundancy: imported items' max token-Jaccard against any anchor item in the
  same answer — median 0.09, p90 0.15, max 0.47; only **1 of 331** ≥0.45.

Residual risk neither metric catches — adjacent inconsistent concrete advice.
Verbatim instance in `rag2026-0`:

> [anchor] …favor **two or three** deep partnerships with local community colleges…
> [imported] Choose **one or two** local nursing schools serving underrepresented students…

## Arena

Judge switched from luna (used by the 08-07 and 08-09 arenas) to **sol**, at
operator request. All five arms are sol-generated, so the sol-grading-sol
self-preference conflict flagged in `tasks/task-comparison/scripts/judge_client.py:93`
does not create asymmetry here. **These scores are therefore not comparable to
the 08-07/08-09 leaderboards.**

Setup: `evaluation/ragdoll` @ `1f06719`; pi `@earendil-works/pi-coding-agent@0.84.0`
in throwaway prefix `/tmp/ragdoll-pi-0.84.0`; provider `mantle` →
`https://bedrock-mantle.us-east-1.api.aws/openai/v1`, api `openai-responses`,
model `openai.gpt-5.6-sol`, reasoning true, `apiKey: "$OPENAI_API_KEY"`,
`models.json` inside the custom `--agent-state-dir`. `doctor --probe`: PASS.
Preflight `--sample-topics-per-pair 1 --sampling-seed 13`: 10/10 completed,
0 errors, all strict `[[A]]`/`[[B]]`.

Integrity: 1,190 tasks = 1,190 judgments = 10 pairs × 119 topics; 1,190 unique
task_ids; 1,190 `status=completed`; 0 errors. Verdicts A=491, B=668, Tie=21,
Tie (Both Bad)=10. Cost **$32.25** ($0.0271/judgment).

### Leaderboard (native `arena-rank`)

| rank | run | arena score | judgments | wins | losses | ties |
| ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | `sol-union5-t119` | 1157.63 | 476 | 338 | 127 | 11 |
| 2 | `sol-aus-default-test119-20260807` | 1099.47 | 476 | 294 | 164 | 18 |
| 3 | `sol-aus-v2-research-first-test119-20260807` | 1064.89 | 476 | 273 | 193 | 10 |
| 4 | `brief-base-t119` | 974.62 | 476 | 204 | 255 | 17 |
| 5 | `piika-gpt56sol-medium-agentic-bm25-rag` (organizer) | 703.38 | 476 | 50 | 420 | 6 |

### Full pairwise matrix

```
run_a                        run_b                     A wins B wins ties  A pref  B pref
sol-union5-t119              sol-aus-v2-research-first   91    23     5    0.786   0.214
sol-union5-t119              sol-aus-default             65    51     3    0.559   0.441
sol-union5-t119              brief-base-t119             78    39     2    0.664   0.336
sol-union5-t119              organizer                  104    14     1    0.878   0.122
sol-aus-v2-research-first    sol-aus-default             61    56     2    0.521   0.479
sol-aus-v2-research-first    brief-base-t119             81    36     2    0.689   0.311
sol-aus-v2-research-first    organizer                  108    10     1    0.912   0.088
sol-aus-default              brief-base-t119             74    34    11    0.668   0.332
sol-aus-default              organizer                  113     4     2    0.958   0.042
brief-base-t119              organizer                   95    22     2    0.807   0.193
```

### Position audit — three pairs FLIP

Win rate of the alphabetically-first run of each pair, by display slot:

```
pair                                              X as A   X as B  flip?
brief-base            vs organizer                 80.9%    81.6%
brief-base            vs sol-aus-default           17.8%    41.3%
brief-base            vs sol-aus-v2-research-first 15.3%    46.6%
brief-base            vs sol-union5-t119           14.5%    54.5%   FLIP
organizer             vs sol-aus-default            4.6%     1.9%
organizer             vs sol-aus-v2-research-first  5.9%    12.0%
organizer             vs sol-union5-t119            4.4%    16.4%
sol-aus-default       vs sol-aus-v2-research-first 33.3%    61.7%   FLIP
sol-aus-default       vs sol-union5-t119           30.2%    60.4%   FLIP
sol-aus-v2-research-first vs sol-union5-t119       22.2%    18.3%
```

**Union vs its anchor is robust** (anchor wins 22.2% as A, 18.3% as B — same
winner both ways). **Union vs `sol-aus-default` and union vs `brief-base` both
flip** and must not be read as evidence the union is better than either. The
overall B-lean (668 vs 491) shows a systematic second-position preference in
this judge configuration.

### Length confound — the important caveat

The union packs to the word ceiling (median 1000 words vs the anchor's 949) and
is longer on 98 of 113 decided union-vs-anchor topics.

```
longer answer won overall (union vs anchor): 93/113 = 82.3%

union LONGER  than anchor : union wins 84/98 = 85.7%
union SHORTER than anchor : union wins  6/15 = 40.0%
union EQUAL               : union wins   1/1
```

When the union is shorter it *loses*. The 78.6% headline is therefore not
cleanly attributable to better content selection; pairwise preference here
tracks length closely. `n=15` for the shorter bucket is small, but the contrast
is stark and the direction is unambiguous.

**This is not settled by an arena.** Disentangling needs a criterion-referenced
instrument rather than a preference vote — AutoNuggetizer-style nugget coverage,
or the rubric/entailment grading `judge_client.py` documents as not exhibiting
the self-preference that "dominated the arena". Recommend running one before
treating `sol-union5-t119` as better than `sol-aus-default`.

## Spend

Session start $1,356.44 → **$1,372.78** tracked (authorised absolute cap
$1,500). Union selector $0.21/call. Arena's own $32.25 is recorded in
`judgments.jsonl.usage.cost_usd` and is not part of that ledger's total.

## Artifacts

- `data/outputs/submissions/sol-union5-t119/rag_output_trec_rag_2026.jsonl`
- `data/outputs/aus_agent_v2/*.output.json` @ `run_id=sol-union5-t119` (119 rich)
- `data/outputs/aus_agent_v2/test-candidate-union-packets.jsonl` (119 packets)
- `data/outputs/ragdoll-arena/union5-vs-4systems-20260810/` — `tasks.jsonl`,
  `judgments.jsonl`, `coverage.csv`, `pairwise.csv`, `leaderboard.csv`,
  `raw-events/`

All under the machine-local `data/outputs/` fork, not committed.
