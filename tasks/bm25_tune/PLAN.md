# BM25 k1/b Tuning Harness — Implementation Plan

Repo: `/home/el7/E103037/repos/trec-rag-26` (all paths below relative to repo root unless absolute).
Status: PLAN ONLY. Subagents execute this verbatim. All facts marked **[measured]** are empirically
verified — do not re-verify.

## 0. Objective and settled decisions

Tune BM25 `k1`/`b` on the ClimbMix **chunked** index (921,892,634 chunks) to maximize **nDCG@10**
over the **1063 keyword queries** aus_agent actually issued (119 official topics), judged 0–3 by
**`openai.gpt-oss-20b-1:0` on Bedrock**, with every judgment cached on disk keyed by
`(prompt_version, topic_id, chunk_id)`.

Settled by the user — design to these, do not re-open:

- Judge target = the **topic narrative** (the labeled file's `topic` field), not the keyword string.
- **Pooled judgments**: retrieve depth 30 per config, judge the per-topic UNION once, score every
  config against the shared qrel. Never judge one config's hits alone.
- **Two-stage sweep**: (A) coarse grid over a stratified ~250-query subsample (~2 queries/topic);
  (B) top configs + the k1=0.9/b=0.4 baseline over all 1063 queries with a paired significance test.
- Metric nDCG@10, graded 0–3, disk cache.
- Baseline to beat: **k1=0.9, b=0.4** (pyserini default; **[measured]** reproduces the hosted
  production server's scores to 5 decimals — the local index is score-identical to what aus_agent saw).
- **Hard budget ceiling: US$50 for the entire process**, enforced in code (§5.7) — not a
  documented aspiration. Every judge call's cost is computed from its `usage` block and accumulated;
  the driver refuses to start, and aborts mid-run, rather than exceed it.
  *(Lowered from $200 to $50 on 2026-07-31 at the user's direction. The projection is unchanged at
  ≈$8–14, so this remains a circuit breaker with ~4–6× headroom, not a scope limiter — see below.)*
- **The ceiling is passed in per run, never defaulted** (user requirement, 2026-07-31):
  `BM25_TUNE_BUDGET_USD` has **no default in code**. Every subcommand that can spend — `judge-pool`,
  `calibrate`, `smoke` without `--search-only` — and every one that reports against the cap
  (`budget`, `cost-report`) calls `Config.require_budget_usd()` and exits 1 with the export to run if
  it is unset. `config.APPROVED_BUDGET_USD = 50.0` exists **only** so that message can quote the
  approved figure. Rationale: an unattended multi-hour job must be bounded by a decision a human made
  *this* run, and money is the one resource the harness cannot roll back. The commands that cannot
  spend (`verify-inputs`, `extract-queries`, `search-sweep`, `score`, `stats`, `rebuild-cache`,
  `smoke --search-only`) never ask for it, so the refusal is never noise to be worked around.
- **Every cost is recorded and persisted** for the scientific report: per-call token counts and
  US$ in the judgment log, per-stage and cumulative totals in `manifest.json` and a dedicated
  `costs.json`/`costs.md`, and the verbatim price table committed alongside (§5.7, §7.2).
- **Pilot before scale, always**: WP0 calibration is a mandatory gate, and each of Stage A and
  Stage B is preceded by a small `--pilot N` run whose *measured* per-call cost recalibrates the
  projection before the full spend is authorized (§5.7, §9).

One **mandatory gate** was added after calibration probes (§3): the full sweep must not launch until
a judge prompt variant passes the grade-spread gate in Work Package 0. That gate is **two-sided as of
2026-07-31** (user requirement): a judge that grades almost everything relevant is rejected as firmly
as one that grades almost nothing (§3.3). Its bounds are **deliberately loose**, set from a hand-graded
read of 22 real hits (§3.3b) rather than a priori — a tighter band would have rejected that human
reading, which would test the gate's assumptions rather than the judge.

**Budget reality check [measured pricing, §5.7]:** the whole plan as written — ~49 k judge calls
including the continuity pass (~30–36 k without it), at ~900 input / ~300 output tokens typical —
prices at **≈ $8 (typical) to ≈ $14 (worst case)** on ap-southeast-2 standard on-demand (§6.2b).
The $50 cap therefore has **~4–6× headroom** and is still not a
binding design constraint: it is a runaway-cost circuit breaker (a prompt-length blow-up, an
accidental un-cached re-judge, a retry storm), not a scope limiter. Executors must not shrink the
grid or the query set to "save budget" — the plan as written fits, and a refusal means a bug.

What the lower cap *does* change: the discretionary extras in §6.2b are no longer free. The full
plan (≈$8–14) plus the optional 3-sample self-consistency vote (≈$16) plus a finer grid (≈+$1) would
total ≈$25–31 — still inside $50, but no longer with an order of magnitude to spare. So those extras
now need the user's explicit go-ahead with a cost line attached, rather than being waved through as
noise against the ceiling. Order of preference if only one can be afforded: the self-consistency vote
(it addresses R1, the one risk that could invalidate the whole result) over the finer grid (which
buys resolution the labels probably cannot support anyway).

## 1. Key measured facts the design rests on

(All **[measured]**; carried here so executors don't have to re-derive them.)

- **Search is cheap.** `batch_search(20 queries, k=30, threads=16)`: first call 9.4 s (JVM warmup +
  mmap faulting), every subsequent call 1.3–1.6 s ⇒ **~13 queries/s (~75 ms/query amortized)**.
  250 queries × 26 configs ≈ 6,500 executions ≈ **8–10 min**; 1063 × 26 ≈ **~21 min**. Search is
  NOT the bottleneck; do not engineer multi-process JVM parallelism.
- **`set_bm25(k1, b)` flipped repeatedly on one live `LuceneSearcher` works correctly** (6 configs
  run sequentially on one instance, each producing distinct, self-consistent rankings). Constraint:
  never flip it while a `batch_search` is in flight — config changes are strictly sequential;
  parallelism lives *inside* a config via `threads=16`.
- **Judging dominates by 2–3 orders of magnitude.** ~1.1 calls/s at concurrency 12; concurrency 20
  completed 40 calls with zero throttling; per-call latency 6.0–10.9 s (median ~6.5 s). Tokens per
  judgment: ~760–1040 in, 58–648 out (output includes the reasoning block).
- **`maxTokens=1024`**, not 512: output up to 648 tokens observed; 512 risks truncation before the
  `text` block. gpt-oss-20b emits a `reasoningContent` block *before* `text` — parse by **iterating
  content blocks**, never `content[0]["text"]`. Use the **bare** model id
  `openai.gpt-oss-20b-1:0` (`au.*`/`us.*` profile prefixes raise ValidationException). Region
  passed explicitly; prefer `ap-southeast-2`.
- **Configs genuinely move rankings**: top-10 overlap with baseline drops to 0.72 at k1=1.2/b=0.75
  (0.88 at k1=0.9/b=0.6; 0.83 at k1=1.2/b=0.4; 0.77 at k1=1.5/b=0.3; 0.83 at k1=0.6/b=0.5). There
  IS signal for the sweep to find — the counterweight to the judge-calibration risk in §3.
- **Pool inflation is modest and sublinear**: union over 6 configs @ k=30 = mean 43.3 chunks/query
  vs 30 for one config (**1.44×**). Extrapolation for a ~26-cell grid: **~1.7–2.2×, i.e. ~50–65
  unique chunks/query** — configs mostly reorder a shared candidate set.
- **Verbatim UMBRELA + narrative is badly miscalibrated** (n=40, temp 0): grades
  `{0:7, 1:29, 2:2, 3:2}` — 72.5 % graded exactly 1; agent-`positive` vs `negative` nearly
  indistinguishable. Controlled diagnostic shows the judge itself discriminates fine
  ("capital of France" + answer → 3); the **narrative target + factoid-style rubric** is the
  problem: no single 2.4 kB chunk can "contain the exact answer" to a multi-facet narrative, so the
  ceiling collapses to 1.
- **The adapted multi-facet rubric (variant `facet-v1`, §3.2) is a real but partial fix** (n=60,
  temp 0): grades `{0:7, 1:8, 2:36, 3:9}` — full range used, 75 % at ≥2, but still mode-dominated
  (60 % at grade 2) and agent-positive vs agent-negative means 1.88 vs 1.79 (negligible separation —
  though agent labels are a weak proxy; see §3.4).
- Credentials are an **SSO assumed-role session token that expires** mid-run
  (`AWSReservedSSO_RMIT-ResearchAdmin`); the harness must survive `ExpiredTokenException` on a
  multi-hour job without losing or re-judging work.
- The index lives under **another user's home** (read-only):
  `/home/eh6/E128356/projects/trec-rag-26/data/built-indexes/climbmix-bm25-chunked`. Its path is an
  env var (`BM25_TUNE_INDEX_DIR`), never a hardcoded constant. `doc(id).contents()` returns stored
  chunk text; `.raw()` is None/False. Chunk ids `<docid>_p<page>`;
  `parent = chunk_id.rsplit("_p", 1)[0]`.
- JDK 21 already installed at `tasks/bm25_tune/env` (conda prefix env);
  `JAVA_HOME` must be `<repo>/tasks/bm25_tune/env/lib/jvm`. pyserini 2.3.0 works with it
  (requires-python ≥3.12; pulls torch/transformers, ~153 packages). `pyserini.__version__` does
  not exist — never rely on it.
- **The `/tmp` input has already been secured** (I verified during planning): the labeled file is
  copied to `data/bm25-tune/inputs/trec-rag26-test119-search-labeled.jsonl` with
  `SHA256SUMS` (`9bb4bae7…c6c1a`), matching the `/tmp` original byte-for-byte. WP1 only needs to
  *verify* the checksum, not re-copy.

## 2. Inputs

### 2.1 Primary query source (use this)

`data/bm25-tune/inputs/trec-rag26-test119-search-labeled.jsonl` (durable copy; original
`/tmp/trec-rag26-test119-search-labeled.jsonl` is volatile and not ours). 2143 rows; **filter to
`engine == "keyword"`** → 1070 rows, all `run_id == "test-keyword-119"`, `query_id` =
`rag2026-0 … rag2026-118` (119 topics), **1063 unique (topic, query) pairs**, 3–16 queries/topic
(median 8). `topic` carries the full narrative inline. 9208 hits, all with inline `text`
(356–4825 chars, median 2449); 8551 unique chunk ids, **8580 unique (topic, chunk) pairs**.

- `label`/`reason` are **agent-selection labels, not relevance judgments** (`committed` 2368,
  `not selected…` 6604, `voided…` 202, `not retained` 34). Never ground truth; used only as a
  secondary agreement smell test (§3.4).
- `prefix_chars`: 3890/9208 hits have `prefix_chars > 0`; `text[prefix_chars:]` strips the leaked
  `"Page N of document: <title>\n\n"` header. **[measured, WP1 — corrects an earlier planning
  figure]** ALL **3890/3890** keyword hits match the header regex with `match.end() == prefix_chars`
  exactly — there are **zero** outliers (8359/8359 across all engines; five regex variants tried).
  The "31 outliers" claimed in an earlier draft is **not reproducible** on the committed input and
  must not be treated as a fact. The passthrough branch and the `[PREFIX-MISS]` counter are retained
  anyway (a future re-export could reintroduce a mismatch), but nothing may depend on a nonzero
  count. Judge always receives the stripped text.

### 2.2 Secondary source — provenance only, headline EXCLUDES it

`/home/eh6/E128356/projects/trec-rag-26/data/outputs/aus_agent` trajectory mining yields 1160
unique keyword (topic, query) pairs = the 1063 **plus ~97** from whole-doc-era runs (`cmp-keyword`
75, `cmp-trio-ssr` 9, `cmp-trio-lucene` 8, `cmp-base-densesparse` 8).

**Decision: EXCLUDE the ~97 from the headline result.** They were issued against a whole-document
retrieval regime, never validated against the chunked index, and their inclusion would mix two
query-generation distributions while adding <10 % volume. The extractor script
(`bm25tune/extract_trajectories.py`, WP2) is still written — for provenance and an optional
appendix run — with its three known gotchas baked in: (1) single-engine runs omit both
`arguments.search_engine` and `output.engine` (1986 calls) so attribution is by `run_id` only;
(2) `it["output"]` may carry trailing data — use `json.JSONDecoder().raw_decode()`, never
`json.loads()`; (3) match topic→file via `metadata.narrative_id`, never the filename slug.

## 3. Work Package 0 — Judge calibration (MANDATORY, blocks the sweep)

Cheap (1,450 calls, ~20–25 min at concurrency 16) and decisive: the verbatim-UMBRELA-on-narrative
judge is measured-degenerate (§1), and even the improved adapted rubric hasn't yet met the gate.
The sweep must not spend 30k+ Bedrock calls on labels with no discriminative power.

### 3.1 Calibration set

`bm25tune/extract.py::calibration_sample(labeled_rows, n=280, seed=7)`: stratified over the 8580
observed (topic, chunk) pairs — ~2–3 per topic, stratified by agent label (positive/negative/
unjudged proportional to their global 2368/6638/202 mix) so the agreement smell test has both
classes at every topic where possible. Persist the sample to
`data/bm25-tune/calibration/sample-280.jsonl` so all variants judge the *same* pairs.

### 3.2 Prompt variants (registry in `bm25tune/prompts.py`, each with a frozen `prompt_version` id)

| version | Query slot | Rubric |
|---|---|---|
| `umbrela-v1` | full narrative | **verbatim** UMBRELA text from `evaluation-results/aus-agent/umbrela-bedrock/tasks.jsonl` (`instruction` field, copied character-for-character) — kept for continuity with the team's prior umbrela-bedrock runs; **[measured]** degenerate on narratives |
| `umbrela-kw-v1` | the keyword `search_query` | verbatim UMBRELA |
| `facet-v1` | full narrative | the adapted multi-facet rubric, **verbatim as already measured** (see below) — the going-in PRIMARY candidate |
| `facet-name-v1` | full narrative | `facet-v1` wording **plus**: before scoring, the judge must name in ≤10 words which facet of the need the passage addresses (or "none"); grade-2 wording tightened ("2 = relevant background or a partial treatment an answer would cite but could not rely on alone") and grade-3 tightened ("3 = a passage an answer writer would quote or directly build a section from"). Output format: `##facet: <words>` then `##final score: <0-3>`. Purpose: break the grade-2 pile-up by forcing a discrimination step |
| `facet-rare3-v1` | full narrative | `facet-name-v1` wording **plus an explicit base-rate anchor**, added **2026-07-31 at the user's direction** ("most of the documents in the collection are not relevant, and only very few should receive the highest score… it shouldn't be too harsh either, as it wouldn't be very useful"). A `Calibration —` paragraph precedes the rubric: the passages come from a broad web crawl, so most are not useful evidence — expect 0/1 for the majority, 2 for a substantial minority, 3 for only a small minority; do not reward topicality alone; **and do not be stingy** — a passage that really would help an answer writer must not be pushed to 1 for being imperfect. Grade 3 relabelled "excellent and uncommon"; grade 0 extended to cover navigational/boilerplate/promotional text. Purpose: make grade *frequency* something the prompt states rather than an accident of rubric wording |

The percentages in that paragraph are deliberately soft ("the majority", "a small minority") rather
than a quota. Each call sees **one** passage with no batch to rank against, so an instruction like
"grade exactly 20 % as 3" is unsatisfiable locally and would only add noise.

`facet-v1` text, verbatim (already measured at n=60: `{0:7, 1:8, 2:36, 3:9}`):

```
You are judging whether a retrieved passage is useful evidence for answering a complex, multi-part information need. The need is a narrative that usually spans several facets; no single passage is expected to cover all of it.
Score on an integer scale of 0 to 3:
3 = the passage directly and substantially addresses one or more facets of the need, with specific, concrete, usable content (data, methods, recommendations, or detailed explanation).
2 = the passage partially addresses a facet, or gives clearly relevant background an answer would draw on, but is thin, generic, or tangential in places.
1 = the passage is on the same broad topic but contributes little an answer could actually use.
0 = the passage is unrelated to the need.
Judge usefulness for one or more facets, NOT whether the passage answers the whole need. A passage that thoroughly covers a single facet deserves 3.
Information need: {q}
Passage: {p}
Decide the final score. Provide it in exactly this format and nothing else: ##final score: <0-3>
```

Each `PromptSpec` carries `{version_id, template, sha256(template)}`; a unit test pins the hashes so
any silent edit forces a new version id (the cache key depends on it — §5.3).

### 3.3 Selection criteria and gate

Run all five variants over the same 280 pairs (temp 0, maxTokens 1024), plus a **stability probe**:
re-judge 50 random pairs of the winning variant a second time at temp 0 and report exact-match rate
(require ≥90 %). The probe **must bypass the cache lookup** (a `calibrate`-internal force-fresh
path — without it the "re-judge" is a cache hit and the probe trivially reports 100 %); both calls
are logged normally and latest-successful-wins applies, which is harmless at temp 0.

- **Primary criterion: grade spread, bounded on BOTH sides.** Gate to launch the sweep — all four
  conditions, evaluated on the 280-pair sample:

  1. **modal grade ≤ 60 %** (relaxed from "modal ≤50 %", which neither measured variant meets and a
     perfectly flat distribution is not realistic);
  2. **all four grades used** (each ≥ 1 pair);
  3. **20 % ≤ share at grade ≥ 2 ≤ 90 %**;
  4. **share at grade 3 ≤ 50 %**.

  **Every bound is inclusive** — this is not pedantry: `facet-v1`'s measured modal share is *exactly*
  60 %, so a strict `<` would flip condition 1 for the going-in candidate on a rounding convention
  rather than on evidence.

  Conditions 3–4 are two-sided as of **2026-07-31**, at the user's direction: *"most of the documents
  in the collection are not relevant, and only very few should receive the highest score. Of course,
  it shouldn't be too harsh either."* The earlier one-sided form (`≥ 20 % at grade ≥ 2`, no ceiling)
  is a **real defect**: the distribution `{0:1, 1:1, 2:50, 3:48}` — 98 % of passages relevant, 48 % of
  them maximally so — satisfies modal-≤60 %, all-four-grades, and ≥20 %-at-≥2, so a judge that calls
  almost everything relevant was admitted while the harsh failure mode was correctly caught. The
  ceiling exists to catch **that** case and the degenerate ones next to it (all-grade-2, all-grade-3),
  and nothing narrower — see the calibration read-through in §3.3b for why the first draft of these
  numbers (65 % / 25 %) was too tight and had to be widened.

  **The band applies to the sample, which is deliberately not the pool.** §3.1 over-samples positives
  so the agreement smell test has both classes per topic: the 280 pairs are **42.5 % agent-positive /
  54.6 % negative / 2.9 % unjudged**, against **23.8 % / 73.9 % / 2.4 %** across the 8580 observed
  pairs — positives enriched ~1.8×. Any share-at-≥2 read off the sample is therefore *higher* than
  the same judge would produce on the pool, and the two must never be compared as though they were
  the same quantity. Do **not** re-use these constants for a differently-stratified sample without
  re-deriving them; `calibrate` prints both the sample's own label mix and the pool's alongside the
  band, and reports share-at-≥2 **both raw and class-reweighted to the pool mix**, so the comparison
  is auditable rather than assumed.

  **Going-in expectation.** `umbrela-v1` fails on its measured prior (modal 72.5 %, and 10 % at ≥2 is
  below the floor). `facet-v1`'s measured 75 % at ≥2 now **passes** — it sits inside the widened band
  and exactly on the modal bound — so it remains a live candidate rather than a presumed failure.
  Treat the n=60 figures as priors, not verdicts: they came from an ad-hoc sample, not from
  `sample-280.jsonl`, so WP0 re-measures all five on identical pairs before anything is concluded.
- **Secondary smell test only: agent-label agreement.** Report AUC of grade separating
  agent-positive from agent-negative, and mean grade per class. **Caveat stated in the report, now
  quantified (§3.3b):** `committed` vs `not selected` is a weak relevance proxy — the agent selects
  for non-duplication and context budget, not pure topical relevance. **[measured]** 93.9 % of
  rejected keyword hits come from a query that *did* commit something else, and 76.9 % were outranked
  by a committed chunk from the same query, so "not selected" overwhelmingly means "we already had
  this facet covered", not "this is irrelevant". On a hand-read sample, **53 % of rejected passages
  were still grade ≥ 2**. So poor separation on this axis is not by itself proof the judge is bad, and
  **a judge scoring well above the agent's positive rate is expected, not a red flag.** A judge that
  *anti-correlates* with `committed` is suspect; mere overlap is not disqualifying.
- Report per-variant: full grade distribution, modal share, entropy, **share ≥2 and share =3 with the
  band each is checked against**, agent-label cross-tab + AUC, stability match rate, parse-failure
  count, token usage, and a per-condition pass/fail line for the four gate conditions (so a failure
  says *which* bound was missed and in which direction, not just "gated").

**Decision rule:** among gate-passing variants, pick the lowest modal share, tie-broken by AUC.
`umbrela-v1` is scored on the winner's pool during the sweep regardless of whether it passes (cache
makes this a pure re-prompt cost — see §6 budget) so results stay comparable with prior
umbrela-bedrock runs; passing the gate is a condition for being the *judge*, not for being *reported*.
Going-in expectation: `facet-v1`, `facet-name-v1`, and `facet-rare3-v1` are all plausible passes and
the choice between them is what WP0 is for. **The gate is a floor on usability, not the selection
criterion** — §3.3b's read-through found that a distribution close to `facet-v1`'s is defensible on
the evidence, so do not treat `facet-rare3-v1` as the presumed winner merely because it states a base
rate. `umbrela-v1` is the one variant expected to fail.

**Fallback if no variant passes the gate:** `calibrate` exits **code 6** so the launching agent
escalates to the user rather than auto-launching the sweep. The report must rank the failures by *how
far outside* the band each fell, in which direction, and name the least-bad candidate rather than just
declaring "no pass". "Best variant" below means: closest
to the band on condition 3, tie-broken by lowest modal share. On the user's confirmation the
experiment proceeds with that variant but demotes graded nDCG@10; the **pre-registered** headline becomes **nDCG@10 with binarized relevance (grade ≥ 2)**,
with Recall@10 and MAP (binarized ≥1 and ≥2) as secondaries. This is stated *now*, before any sweep
result exists, so a null graded result stays interpretable rather than a dead end.

**Pre-registered family, for the record.** The confirmatory metric family is exactly the six above:
`ndcg10_exp` (primary), `ndcg10_lin`, `ndcg10_bin2`, `recall10_bin2`, `map30_bin1`, `map30_bin2`
(`metrics.PRE_REGISTERED_METRICS`). Two further columns — `gp10` and `p10_bin2` (§5.5) — were added
**2026-07-31, after this plan was written, at the user's request** and are **secondary /
exploratory**: reported in every score table because they cost nothing to compute from the same
cached grades, explicitly *not* confirmatory, and their addition does **not** change §6.4's
Bonferroni family (which counts the 3 candidate-vs-baseline comparisons, not metrics). A p-value
quoted for either must be labeled exploratory.

**Gate constants are code, not prose (WP6 contract).** `calibrate` must not re-key these numbers by
hand. Define them once as module constants and expose a pure function that WP6's tests can drive with
synthetic distributions, so each bound is independently exercised:

```python
GATE_MAX_MODAL_SHARE   = 0.60
GATE_MIN_SHARE_GE2     = 0.20
GATE_MAX_SHARE_GE2     = 0.90
GATE_MAX_SHARE_EQ3     = 0.50
GATE_REQUIRE_ALL_GRADES = True

def evaluate_gate(counts: Mapping[int, int]) -> GateResult:  # per-condition verdicts, not one bool
```

`GateResult` carries a verdict **per condition** with the observed value and the bound it was checked
against, because "gated" alone does not tell an operator whether to reach for a stricter or a looser
prompt. Required test cases, all **[verified]** against these constants:

| distribution | modal | ≥2 | =3 | required verdict |
|---|---|---|---|---|
| `{0:1, 1:1, 2:50, 3:48}` saturated | 0.500 | 0.980 | 0.480 | **FAIL** cond. 3 — the defect that motivated the change; it passed the pre-2026-07-31 gate |
| `{0:7, 1:29, 2:2, 3:2}` `umbrela-v1` measured | 0.725 | 0.100 | 0.050 | **FAIL** cond. 1 and 3-from-below |
| `{0:0, 1:0, 2:100, 3:0}` all-grade-2 | 1.000 | 1.000 | 0.000 | **FAIL** cond. 1, 2, 3 |
| `{0:0, 1:0, 2:0, 3:100}` all-grade-3 | 1.000 | 1.000 | 1.000 | **FAIL** all four |
| `{0:7, 1:8, 2:36, 3:9}` `facet-v1` measured | 0.600 | 0.750 | 0.150 | **PASS** — on the modal bound, inside the band |
| `{0:32, 1:28, 2:29, 3:11}` mid-band | 0.321 | 0.398 | 0.107 | **PASS** |
| §3.3b's hand-read distribution, pool-reweighted | 0.402 | 0.653 | 0.250 | **PASS** — the gate must not reject a human reading of this collection |

### 3.3b Calibration read-through: what the collection actually looks like [measured, 2026-07-31]

The gate constants above are not a priori. They were set by hand-grading 22 keyword hits sampled from
`trec-rag26-test119-search-labeled.jsonl` (seeds 1729 and 90210, blind to the agent's label at grading
time, then compared) — the "sample a few and judge them yourself" pass the user asked for. Full
per-passage records, verbatim texts, per-grade reasoning, and the result matrix are in
`worklogs/2026-07-30-bm25-tune-harness-implementation.md` §4; the raw samples are
`worklogs/assets/2026-07-31-judge-sample-{14-stratified,neg8}.json` and every figure below is
recomputed by `worklogs/assets/2026-07-31-hand-grade-tally.py`. This section carries only what the
plan depends on.

**Finding 1 — the agent's `label` is a *staging* decision, not a relevance judgment, and the
difference is large.** **[measured]** of 6,638 rejected keyword hits, **93.9 %** came from a query that
committed something else and **76.9 %** were outranked by a committed chunk from that same query. On
the hand-read sample, **8 of 15 rejected passages (53 %) were grade ≥ 2** — several were solid
evidence the agent had simply already covered from a higher-ranked hit. Mean grade was 2.60 for
committed vs 1.47 for rejected: the signal is real and correctly *ordered*, but the rejected class is
roughly half relevant. **Consequence:** treating `not selected` as "irrelevant" would understate the
true relevant share by about a factor of two, and any gate ceiling calibrated against the agent's
23.8 % positive rate is calibrated against the wrong quantity. This is why condition 3's ceiling is
90 % and not 65 %.

**Finding 2 — a defensible reading of this collection is *not* mostly-irrelevant at depth 10.** My 22
grades were `{0:3, 1:5, 2:9, 3:5}`; reweighted to the pool's real class mix (2368/6638/202) that is
**`{0:14 %, 1:20 %, 2:40 %, 3:25 %}` — 65 % at ≥2, 25 % at grade 3**. The first draft of this gate
(65 % / 25 % ceilings, committed earlier the same day) would have **failed my own hand-grading**, and a
gate that rejects a careful human read of the data is measuring the gate's assumptions rather than the
judge. The reason the base rate is this high is structural: these are **BM25 top-4-to-10 hits for
agent-authored keyword queries on broad multi-facet narratives**, not random crawl documents. The
user's "most documents are not relevant" is true of *ClimbMix as a corpus* and remains the right
instinct for grade 3 specifically; it is not true of *this pool*, and the pool is what gets judged.
Confidence intervals are wide at n=22 (Wilson 95 % CI on the raw stratified tally — share ≥2 = 14/22:
**0.43–0.80**; grade 3 = 5/22: **0.10–0.43**), which is a further argument for loose bounds — the band
must not be tighter than the evidence that set it.

**Finding 3 — saturation, not leniency, is what actually costs the experiment, and it costs less than
first stated.** The earlier claim in this plan (mean |ΔnDCG@10| 0.069 at 98 % relevant vs 0.105 at
25 %) came from a simulation with **randomly assigned** grades, where relevance was uncorrelated with
retrieval rank. Re-run with grades correlated to rank (the realistic case) and mean |Δ| **rises** as
labels get harsher — 0.150 for an `umbrela-v1`-like distribution vs 0.050 for a saturated one — so mean
|Δ| conflates signal with variance and is the wrong statistic. Measuring **power** instead (paired
t-test at Bonferroni 0.05/3 detecting a genuinely better ranker): at topic level n=119 with a small
effect, power is ≤ 0.03 for **every** distribution tested, harsh and saturated alike; at n=825 with a
large effect it is ≥ 0.99 for every one of them. All three probes are reproducible —
`worklogs/assets/2026-07-31-label-distribution-sim.py`. The honest
conclusion is narrower than the one this plan previously asserted: **the label distribution is not the
binding constraint on power — sample size and effect size are.** §3.4's warning stands on its own
evidence and does not need the saturation argument. What the ceiling still buys is the genuinely
degenerate corner (all-grade-2, all-grade-3, ~98 % relevant), where IDCG and DCG converge and nDCG@10
approaches 1 for every config — hence 90 % / 50 % rather than nothing at all.

**Finding 4 — the prompts must not be over-corrected.** Because of findings 1–3, `facet-rare3-v1`'s
base-rate anchor is a **hypothesis to be tested, not a fix to be assumed**. Its "MOST of them are not
useful evidence" instruction is a statement about the corpus that is *false of the judged pool* (where
~65 % may be genuinely useful), so it may well push the judge below the floor. That is exactly what
WP0's 280-pair measurement is for, and it is why all three facet variants stay in contention. **The
'do not be stingy' counterweight is what keeps this variant viable; do not remove it.**

### 3.4 Honest consequence for the metric (goes in README + worklog verbatim)

With a mode-dominated label set, nDCG@10 differences between neighbouring k1/b cells will be small.
Therefore: (a) the paired test matters more than the point estimate; (b) report effect sizes and
bootstrap confidence intervals, not just p-values; (c) the secondary metrics above are
pre-registered. The counterweight: configs measurably reorder the top-10 (overlap down to 0.72), so
rank movement exists for good labels to reward.

## 4. Task layout, env, artifacts

### 4.1 `tasks/bm25_tune/` (code, configs, logs only — no data artifacts)

```
tasks/bm25_tune/
├── env/                      # JDK 21 conda prefix env (EXISTS — do not touch)
├── pyproject.toml            # NEW
├── README.md                 # NEW (contents: §7.1)
└── bm25tune/                 # NEW package
    ├── __init__.py
    ├── config.py             # env-var config; no side effects at import
    ├── logging_setup.py      # logging config + heartbeat thread
    ├── extract.py            # labeled-JSONL → queries/pairs; subsampling; prefix stripping
    ├── extract_trajectories.py  # secondary-source miner (provenance; §2.2)
    ├── prompts.py            # PromptSpec registry (§3.2)
    ├── searcher.py           # ChunkSearcher over pyserini (lazy import)
    ├── judge.py              # Bedrock Converse client: retries, cred expiry, parsing
    ├── store.py              # JudgmentLog (append-only) + JudgmentCache (§5.3)
    ├── pool.py               # per-topic union pooling
    ├── metrics.py            # nDCG@10 (both gains), P@10 + graded P@10, Recall@10, MAP — stdlib
    ├── stats.py              # paired t, Wilcoxon (normal approx), bootstrap CI — pure stdlib
    ├── pricing.py            # frozen rate table + CostMeter + BudgetGuard (§5.7) — pure stdlib
    ├── prices/bedrock-gpt-oss-20b-aps2-2026-07-30.json   # verbatim AWS Pricing API extract
    └── cli.py                # `python -m bm25tune <subcommand>` driver (§5.6)
```

**Import discipline (this is what makes the tests hermetic, §7.3):** `pyserini` is imported only
inside `ChunkSearcher._open()`; `boto3` only inside `BedrockJudge._client()` and inside the
`refresh-prices` subcommand body in `cli.py` (the one other place that needs it — `pricing.py`
itself never imports boto3; the rate file is data). Every other module is
stdlib-only at import time. `metrics.py`/`stats.py` deliberately avoid numpy/scipy (1063 floats —
pure Python is fine) so the root test env needs no new dependency group.

`tasks/bm25_tune/pyproject.toml` — **as built in WP1. An earlier draft specified
`[tool.uv] package = false`; that is wrong and was replaced**, because with nothing installed the
plan's own canonical invocation (`uv run --project tasks/bm25_tune python -m bm25tune …` *from the
repo root*) puts the **repo root** on `sys.path[0]` and fails with `No module named bm25tune`.
Installing the package editable into its own `.venv` is the minimal fix and preserves the isolation
CLAUDE.md requires (that isolation is the per-task `.venv`, which is untouched). The alternatives —
`cd tasks/bm25_tune` or an exported `PYTHONPATH` — would make every command in the plan, the README
and the worklogs differ from what actually runs.

```toml
[project]
name = "trec-rag-26-task-bm25-tune"
version = "0.0.0"
description = "BM25 k1/b tuning on the chunked ClimbMix index with an LLM judge."
requires-python = ">=3.12"
dependencies = [
  "pyserini==2.3.0",
  "boto3>=1.40",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["bm25tune"]   # ships prices/*.json, which pricing.py loads at runtime (§5.7)
```

Canonical invocation (all commands run from repo root):

```bash
export JAVA_HOME="$PWD/tasks/bm25_tune/env/lib/jvm"
export BM25_TUNE_INDEX_DIR=/home/eh6/E128356/projects/trec-rag-26/data/built-indexes/climbmix-bm25-chunked
export AWS_REGION=ap-southeast-2   # judge region — passed explicitly to boto3 regardless
uv run --project tasks/bm25_tune python -m bm25tune <subcommand> ...
```

`config.py` reads: `BM25_TUNE_INDEX_DIR` (required for search subcommands; fail fast with a clear
error if unset/unreadable), `BM25_TUNE_DATA_DIR` (default `<repo>/data/bm25-tune`),
`BM25_TUNE_JUDGE_MODEL` (default `openai.gpt-oss-20b-1:0`), `BM25_TUNE_JUDGE_REGION` (default
`ap-southeast-2`), `BM25_TUNE_JUDGE_CONCURRENCY` (default `16`),
**`BM25_TUNE_BUDGET_USD` (the hard ceiling, §5.7 — *no default*; required by every command
that can spend or that reports against the cap, via `Config.require_budget_usd()`, which refuses with
exit 1 and quotes `export BM25_TUNE_BUDGET_USD=50.0`)**, and
**`BM25_TUNE_PRICING_TIER` (default `standard`; one of `standard|batch|flex|priority`)**.
The tier only selects which committed rate is used for *accounting* — the Converse path always
bills at standard, so setting any other tier under-records real spend; `judge-pool` warns loudly
(`[COST] tier != standard — metered figures will not match the AWS bill`) if it is changed.
The budget is cumulative across the whole experiment, not per-run (§5.7).

### 4.2 `data/bm25-tune/` (artifacts — gitignored by `data/*`, synced via rsync like other outputs)

```
data/bm25-tune/
├── inputs/                                # EXISTS: labeled jsonl + SHA256SUMS
├── queries/
│   ├── keyword-1063.jsonl                 # {topic_id, topic, query, k_orig} — the full set
│   └── subsample-250.jsonl                # stratified 2/topic, seed 13 — **238 rows** [measured, WP1]
│                                          # (119 topics × 2; filename kept as the published name)
├── calibration/
│   ├── sample-280.jsonl
│   └── report.md + report.json            # §3.3 outputs
├── judgments/
│   ├── log/events-<UTCts>-<host>-<pid>.jsonl   # append-only audit segments (§5.3)
│   └── cache/qrels-<prompt_version>.jsonl      # rebuildable snapshot (§5.3)
├── costs/
│   ├── ledger.jsonl                       # append-only: one line per meter checkpoint (§5.7)
│   └── totals.json                        # cumulative spend across ALL runs — the budget state
└── runs/<run_id>/                         # run_id = YYYYMMDDTHHMMSS-<stage>, e.g. 20260730T120000-stageA
    ├── manifest.json                      # §7.2
    ├── sweep.log                          # the run's logfile (also tee'd to /tmp)
    ├── trecruns/k1_<k1>__b_<b>.txt        # TREC 6-col run files, depth 30
    ├── pool.jsonl                         # {topic_id, chunk_id, text_sha256, first_seen_config}
    ├── scores.csv + scores.md             # full per-config matrix (§5.5)
    ├── costs.json + costs.md              # this run's cost breakdown (§5.7)
    └── stats.json                         # Stage B tests (§6.4)
```

**`costs/totals.json` is the budget's durable state** and lives *outside* `runs/` deliberately: the
$50 ceiling spans the whole experiment (calibration + Stage A + Stage B + any continuity pass), so
it must survive a crash, a re-run, and a new `run_id`. It is rebuildable from `costs/ledger.jsonl`,
which is itself rebuildable from the judgment log (`usage` is recorded per call, §5.3) — three
levels of derivability so a lost file never loses the accounting.

Published (committed) subset → `evaluation-results/bm25-tune/<run_id>/`: see §7.4.

## 5. Module-by-module design

### 5.1 `extract.py`

```python
@dataclass(frozen=True)
class QueryRec:
    topic_id: str      # "rag2026-17"
    topic: str         # full narrative
    query: str         # keyword string
    qkey: str          # f"{topic_id}::{sha1(query)[:12]}" — stable per (topic,query) run tag

def load_keyword_queries(path: Path) -> list[QueryRec]           # engine=="keyword", dedupe (topic,query) → 1063
def stratified_subsample(qs: list[QueryRec], per_topic: int = 2, seed: int = 13) -> list[QueryRec]
def load_observed_hits(path: Path) -> list[ObservedHit]          # for calibration + agreement checks
def strip_page_prefix(text: str, prefix_chars: int | None) -> tuple[str, bool]
```

`strip_page_prefix` (**as implemented in WP1 — this supersedes the earlier "slice unconditionally"
wording, which contradicted R4**): `prefix_chars` is used **only when the header regex
`re.match(r"Page \d+ of document: [^\n]*\n\n", text)` corroborates it** (`match.end() ==
prefix_chars`). If `prefix_chars` is absent (pool chunks fetched from the index) the regex match
alone drives the strip. **If neither applies, pass the text through unmodified and count it**
(logged under `[PREFIX-MISS]`, reported in the manifest — §8 R4).

Why corroborate rather than trust `prefix_chars` blindly: an unconditional slice would consume any
future uncorroborated offset **silently**, and would make the `[PREFIX-MISS]` counter vacuously 0
forever — an unfalsifiable check. The failure modes are asymmetric: a leaked header line is bounded,
visible noise, whereas a wrong slice amputates real passage text undetectably. A companion
`prefix_anomaly()` makes the "counter reads 0" assertion falsifiable. **On the committed input the
two readings are behaviourally identical** (all 3890 corroborate), so this costs nothing today and
protects a re-export tomorrow.

`stratified_subsample` sorts topics, seeds `random.Random(13)`, picks 2/topic (topics with <2 keep
all) → **exactly 238 queries [measured, WP1]** (all 119 topics have ≥2, so 119×2; the file is still
named `subsample-250.jsonl` because that is the published name). sha256
`edd21e43…67b9fc`, stable across re-runs — the exact list is persisted so Stage A is reproducible
byte-for-byte. Wherever this plan says "~250 Stage-A queries", read **238**; the held-out Stage-B
complement is therefore **825**, not 813 (§6.4).

### 5.2 `searcher.py`

```python
class ChunkSearcher:
    def __init__(self, index_dir: str, threads: int = 16): ...   # lazy: no pyserini import here
    def set_config(self, k1: float, b: float) -> None            # wraps LuceneSearcher.set_bm25
    def run_config(self, queries: list[QueryRec], k: int = 30) -> dict[str, list[tuple[str, float]]]
        # qkey -> [(chunk_id, score)]; internally batch_search(texts, qids, k=k, threads=self.threads)
    def fetch_texts(self, chunk_ids: list[str]) -> dict[str, str]  # doc(id).contents(); .raw() unusable
    def warmup(self) -> None                                     # one throwaway batch; logged [WARMUP]
```

- **One `LuceneSearcher` instance for the whole sweep**, configs applied strictly sequentially via
  `set_config` (**[measured]** safe sequentially; the docstring warns never to flip while a
  `batch_search` is in flight — shared mutable similarity on the instance). Parallelism is
  *within* a config via `threads=16`; JVM does the fan-out, so the GIL is irrelevant here.
- `warmup()` runs before timing anything and its 9.4 s cold cost is logged explicitly so the first
  config's wall time isn't mistaken for a regression.
- Queries are batched 64 at a time to keep heartbeat progress granular.

### 5.3 `store.py` — judgment LOG vs CACHE (user-flagged as first-class)

**Cache key: `(prompt_version, topic_id, chunk_id)`.** The prompt-version component is mandatory:
WP0 judges the same pairs under four prompts, and without it calibration judgments would poison the
sweep. A key helper `jkey(prompt_version, topic_id, chunk_id) -> str` is the only way keys are made.
`run_id` and `stage` (below) are cost-attribution metadata and are **deliberately NOT key
components** — the whole reuse economy (§6.2) depends on a Stage-A judgment satisfying a Stage-B
lookup; `test_store.py` pins this with a cross-run cache-hit case.

**Append-only judgment LOG** — the permanent audit record; source of truth:

- One segment file per writer process: `judgments/log/events-<UTCts>-<host>-<pid>.jsonl`, opened
  `"a"`; every record written as one line, `flush()` per line, `os.fsync()` every 10 lines **or**
  every 5 seconds, whichever comes first (rationale in §5.8), and on close/drain. Per-process
  segment naming means concurrent writers **never share a file handle** — safe
  under concurrent writers by construction, no locking.
- **Every attempt is logged, including failures and retries** — a throttle, a parse failure, and
  the retry that fixed it are three records.
- Records are never rewritten: re-runs append new segments. Raw judgments can never be silently
  overwritten.
- Crash mid-write leaves at most one truncated final line; the reader tolerates and counts a
  malformed tail line per segment (`[LOG-TAIL]` warning), errors on malformed interior lines.

Record schema (one JSON object per line):

```json
{
  "kind": "judgment",                       // or "attempt_error"
  "jkey": "facet-v1::rag2026-17::shard_00122_5199_p1",
  "prompt_version": "facet-v1",
  "topic_id": "rag2026-17",
  "chunk_id": "shard_00122_5199_p1",
  "parent_docid": "shard_00122_5199",
  "narrative_sha256": "…",                  // full text lives once per topic in queries/keyword-1063.jsonl
  "passage_text": "…",                      // the EXACT text sent (post prefix-strip)
  "passage_sha256": "…",
  "prompt_sha256": "…",                     // hash of the fully rendered prompt
  "raw_text": "##final score: 2",           // the model's text block, verbatim
  "raw_reasoning": "…",                     // the reasoningContent block, verbatim
  "grade": 2,                               // null on parse failure
  "facet": "hiring and promotion",          // facet-name-v1 only, else null
  "model_id": "openai.gpt-oss-20b-1:0",
  "region": "ap-southeast-2",
  "stop_reason": "end_turn",
  "usage": {"inputTokens": 934, "outputTokens": 212},
  "cost": {                                 // §5.7 — recorded per call, never recomputed from memory
    "usd": 0.00013285,
    "input_usd": 0.00006734,
    "output_usd": 0.00006551,
    "tier": "standard",
    "rate_table_id": "bedrock-gpt-oss-20b-aps2-2026-07-30"   // same field name as pricing.py/manifest
  },
  "run_id": "20260730T120000-stageA",       // which run billed this call (cost attribution per stage)
  "stage": "A",                             // "calib" | "A" | "B" | "continuity" | "smoke"
                                            // run_id/stage are BILLING metadata ONLY — NOT part of
                                            // jkey; a pair judged in Stage A is a cache hit in Stage B
  "latency_ms": 6480,
  "attempt": 1,
  "error": null,                            // "throttle" | "expired_token" | "parse_failure" | ...
  "ts": "2026-07-30T12:00:00.123Z"
}
```

**Cost is recorded on every attempt record, including failures**, because a call that returned a
`stopReason=max_tokens` empty text or an unparseable grade **was still billed**. Summing `cost.usd`
over the log — including `kind: "attempt_error"` rows — is the ground-truth spend, and the plan's
reconciliation check (§5.7) asserts it matches `costs/totals.json`. Rows whose call never reached the
model (throttle before send, credential rejection) carry `usage: null, cost: null`.

**CACHE** — a lookup structure, always rebuildable:

```python
class JudgmentCache:
    @classmethod
    def load(cls, log_dir: Path) -> "JudgmentCache"   # scan ALL segments; keep latest successful grade per jkey
    def get(self, key: str) -> int | None
    def snapshot(self, path: Path) -> None            # cache/qrels-<pv>.jsonl via tmp-file + os.rename (atomic)
```

Startup loads the snapshot if present *and then replays only segments newer than the snapshot's
recorded high-water timestamp*; if the snapshot is missing or corrupt, a full log rescan rebuilds
it (~seconds for <100k lines). The log is the only source of truth; the snapshot is a pure
accelerator. A `python -m bm25tune rebuild-cache` subcommand forces a full rescan.

**Publication tension, resolved:** `evaluation-results/README.md` states raw judge events, caches
and logs are *deliberately excluded* there. We keep that rule. Raw log segments (which embed full
passage texts + reasoning — est. 50–150 MB) stay under `data/bm25-tune/judgments/` (gitignored via
`data/*`, rsync-synced between servers like all other outputs). What gets **committed** to
`evaluation-results/bm25-tune/<run_id>/` is the small reviewable layer: TREC-format qrels per
prompt version (~1–2 MB), the score matrices, the calibration report, and the manifest (§7.4).

### 5.4 `judge.py`

```python
@dataclass
class JudgeResult:
    grade: int | None; raw_text: str; raw_reasoning: str; facet: str | None
    stop_reason: str; usage: dict; latency_ms: int; attempts: int; error: str | None

class BedrockJudge:
    def __init__(self, model_id: str, region: str, max_tokens: int = 1024,
                 temperature: float = 0.0, max_attempts: int = 8): ...
    def judge(self, prompt: str) -> JudgeResult

def parse_grade(content_blocks: list[dict]) -> tuple[int | None, str, str, str | None]
def classify_error(exc: Exception) -> str   # "throttle" | "expired_token" | "other"
```

- **Converse** API, bare model id, explicit `region_name`, `inferenceConfig={"maxTokens": 1024,
  "temperature": 0.0}`.
- `parse_grade` **iterates** `output.message.content`, concatenating every block's `text` key and
  every `reasoningContent.reasoningText.text`; grade = last regex match of
  `##\s*final score:\s*([0-3])` (case-insensitive) in the text blocks; `##facet:` captured when
  present. Empty text with `stopReason == "max_tokens"` → `parse_failure` (the maxTokens=64 trap,
  pinned by a test).
- **Throttling** (`ThrottlingException`/`TooManyRequestsException`/HTTP 429 via
  `getattr(exc, "response", {}).get("Error", {}).get("Code")`): exponential backoff with full
  jitter, base 1 s, cap 30 s, up to `max_attempts`; every retry logged
  `[THROTTLE] attempt=N sleep=S.Ss`. Measured reality: zero throttles seen at concurrency 20, so
  default concurrency 16 leaves headroom.
- **Credential expiry** (`ExpiredTokenException`/`ExpiredToken`/`InvalidClientTokenId`): the worker
  raises `CredentialsExpired` up to the driver, which runs the **shared drain routine (§5.8)** with
  trigger `cred_expiry`, logs
  `[CRED] session token expired — refresh SSO creds and re-run the same command; resume is automatic`
  and **exits with code 3**. Resume is free: on restart the cache already contains every completed
  judgment, so only unfinished pairs are sent. One client-recreate is attempted first (covers
  profile/credential-file refresh); env-var creds can't self-heal inside a running process, hence
  exit-and-resume rather than a polling loop.
- **Parse failure**: retry once with the line
  `Reply with exactly one line: ##final score: <0-3>` appended; if still unparseable, record
  `grade=null, error="parse_failure"` and continue (never crash the run). Parse-failed pairs are
  excluded from qrels and counted in the manifest; >1 % parse failures aborts with `[PARSE-FAIL]`
  summary (indicates a prompt/model regression, not noise).
- `classify_error` reads exception attributes defensively (no boto3 import needed), so it is
  testable hermetically with fake exception objects.

Concurrency model: `ThreadPoolExecutor(max_workers=concurrency)` for Converse calls (I/O-bound;
boto3 clients are thread-safe for calls), workers put finished records on a `queue.Queue`, **one
dedicated writer thread** appends to the single per-process log segment — serialization without
locks.

### 5.5 `pool.py`, `metrics.py`

```python
def build_pool(runs: dict[config_key, dict[qkey, list[tuple[str, float]]]],
               queries: list[QueryRec], depth: int = 30) -> dict[topic_id, set[chunk_id]]
```

Pooling unions per **topic** (cache key is topic-level): every chunk any config returns at depth
≤30 for any of the topic's queries. **Depth 30 justification [measured]:** metric is nDCG@10;
depth 30 gives 3× headroom for rank movement between configs while union inflation stays modest
(1.44× at 6 configs; expected ~1.7–2.2× ⇒ ~50–65 unique chunks/query at 26 configs).

`metrics.py` — exact conventions, stated once and pinned by tests:

- **Primary: nDCG@10 with exponential gain** `(2^g − 1)` and discount `1/log2(rank + 1)`
  (rank 1-based; Burges convention). Chosen because the calibrated label set concentrates at grade
  2 (§3.4) and exponential gain triples the 3-vs-2 reward (7 vs 3), preserving what discriminative
  power the judge achieves.
- **Also reported: linear-gain nDCG@10** (`gain = g`, same discount — trec_eval `ndcg_cut_10`
  semantics) for comparability with TREC practice. Both columns appear in every score table.
- **Unjudged = gain 0.** With pooled judging every chunk any swept config retrieves to depth 30 is
  judged, so unjudged@10 occurs only via parse failures (rare) — per-config judged@10 coverage is
  reported so silent penalization is visible.
- **Ideal DCG from the topic-level qrel**: all judged (topic, chunk) grades for the query's topic,
  sorted descending, top 10. Stable across configs and across a topic's queries, which keeps
  per-query nDCG comparable and the paired test clean. Consequence stated in the README: absolute
  nDCG values are deflated (the ideal may contain chunks a given keyword query cannot retrieve);
  only *relative* comparisons between configs are meaningful, which is the entire purpose.
- Secondaries (pre-registered, §3.3): nDCG@10 binarized at ≥2, Recall@10 (binarized ≥2, denominator
  = topic's judged-relevant count), MAP@30 (binarized at ≥1 and at ≥2 — both thresholds, matching
  §3.3's pre-registration).
- **Secondary / exploratory — "how much relevant material is in the top 10", added 2026-07-31 at
  the user's request; NOT part of §3.3's pre-registered confirmatory family.** Two columns, both
  computed in the *same* scoring pass as nDCG@10 and persisted in `scores.csv` /
  `scores-per-query.csv`, so re-optimizing the grid for either later needs **no re-judging and no
  re-run**:
  - `p10_bin2` — plain **Precision@10 binarized at grade ≥ 2**: `#{top-10 grades ≥ 2} / 10`. The
    legible form of "how many relevant docs are in the top 10", and equal to `trec_eval`'s `P_10`.
  - `gp10` — **graded precision@10**: `sum(top-10 grades) / (10 × 3)`, i.e. the mean of `grade/3`
    over the ten slots. Bounded [0,1]; reduces to P@10 when every relevant chunk is grade 3;
    retains the signal `p10_bin2` discards (a top-10 of grade-1s scores 0 on `p10_bin2` but >0
    here); **not** normalized by any ideal, so unlike every other column its absolute value is
    interpretable and comparable across topics. Rejected alternatives: mean exponential gain
    `(2^g−1)/7` (dominated by grade 3s, and §3.4 says the labels pile at 2, so it compresses the
    region where all the between-config movement is), and normalizing by the topic's best
    achievable top-10 (reintroduces the very deflation that makes nDCG's absolutes unquotable).
  - **Denominator: a flat 10, not `min(retrieved, 10)`.** A config that retrieved 4 chunks left six
    slots empty and that is a property of the config; `min(retrieved, 10)` would let one relevant
    hit out of one retrieved score 1.0 and beat a config that filled all ten with nine relevant
    ones. (`judged@10` coverage keeps `min(retrieved, 10)` — it asks "of what was shown, how much
    was judged", where a slot that was never filled cannot be unjudged.)
  - **Both are rank-indifferent within the cutoff, deliberately.** nDCG@10 is the rank-sensitive
    measure; a rank-flat companion isolates *set quality* from *ordering*, so a cell where nDCG
    moves and these do not merely reshuffled the same ten chunks. Pinned by a rank-permutation test
    in `test_metrics.py`.
  - The `stats` subcommand tests them by default (it iterates every metric), but §6.4's Bonferroni
    family stays at **3** — it counts candidate *configs*, not metrics — and any p-value quoted for
    these two must be labeled exploratory.
- Aggregation: mean over queries (primary), plus mean-of-topic-means (robustness — topics
  contribute 3–16 queries each).

### 5.6 `cli.py` — subcommands and resumability

```
python -m bm25tune verify-inputs      # sha256 check of inputs/ against SHA256SUMS; row/count asserts (§2.1 numbers)
python -m bm25tune extract-queries    # → queries/keyword-1063.jsonl + subsample-250.jsonl
python -m bm25tune calibrate          # WP0: 5 variants × 280 pairs + stability probe → calibration/report.{md,json}
python -m bm25tune search-sweep  --stage A|B [--configs ...]   # run files + pool.jsonl (search only; minutes)
python -m bm25tune judge-pool    --run-id <id> --prompt-version <pv> [--pilot N]  # the long job; fully resumable
python -m bm25tune score         --run-id <id> --prompt-version <pv>  # scores.csv/.md from cache
python -m bm25tune stats         --run-id <idA> --run-id-b <idB>       # Stage B paired tests → stats.json
python -m bm25tune rebuild-cache
python -m bm25tune cost-report [--run-id <id>]   # costs.md/.json + experiment roll-up + reconciliation (§5.7)
python -m bm25tune budget                         # print spent / cap / remaining and exit; no API calls
python -m bm25tune refresh-prices                 # re-fetch AWS Pricing → a NEW dated prices/ file
python -m bm25tune smoke [--search-only]  # 3 real queries + 1 real judgment; the live end-to-end check
```

Even `smoke`'s single judgment goes through the metered path (`stage: "smoke"` in the log record,
added to the meter) — there is no unmetered way to call Bedrock in this codebase, which is what
makes the §5.7 accounting trustworthy.

Every subcommand is idempotent: `search-sweep` skips a config whose run file exists (unless
`--force`), `judge-pool` consults the cache before every call — **resume after any crash, cred
expiry, budget stop, or signalled drain is "re-run the same command"**. Stage separation (search vs judge vs score) means the cheap
parts are re-runnable without touching Bedrock.

`logging_setup.py`: root logger, format
`%(asctime)s %(levelname)s %(name)s %(message)s` (UTC, ISO-8601 timestamps), INFO to console AND to
`data/bm25-tune/runs/<run_id>/sweep.log`. Stable greppable prefixes:
`[LOAD] [WARMUP] [SEARCH] [POOL] [CACHE] [JUDGE] [THROTTLE] [CRED] [PARSE-FAIL] [PREFIX-MISS]
[LOG-TAIL] [NDCG] [HEARTBEAT] [BUDGET] [COST] [SIGNAL] [SUMMARY]`.
Logged per stage: queries loaded (counts, topics),
per-config search progress (`[SEARCH] k1=1.2 b=0.4 done 250q in 19.4s`), pool size per topic and
total, **cache hit/miss ratio at judge start and in every heartbeat**, every retry with backoff
taken, every parse failure with the raw text, per-config nDCG as scoring completes, and a final
`[SUMMARY]` table. **Heartbeat thread, every 60 s** — spend is a first-class heartbeat field so the
operator watching `tail -f` sees cost accrue in real time, never only at the end:
`[HEARTBEAT] judged 4312/11250 (38.3%) rate=1.52/s cache_hits=2103 throttles=0 parse_fails=3
spent=$0.68 proj=$1.94 cap=$50.00 eta=76m`.
The `[BUDGET]` pre-flight line is logged before the first call and repeated in the final `[SUMMARY]`;
`[COST]` carries the per-stage roll-up at shutdown (clean or aborted).

Long-job launch, verbatim (tracked background task per CLAUDE.md, `tee` to /tmp, the runner must
print this fenced in chat when kicking it off):

```bash
JAVA_HOME="$PWD/tasks/bm25_tune/env/lib/jvm" \
BM25_TUNE_INDEX_DIR=/home/eh6/E128356/projects/trec-rag-26/data/built-indexes/climbmix-bm25-chunked \
BM25_TUNE_JUDGE_REGION=ap-southeast-2 \
uv run --project tasks/bm25_tune python -m bm25tune judge-pool \
  --run-id 20260730T120000-stageA --prompt-version facet-v1 \
  2>&1 | tee /tmp/bm25-tune-judge-stageA.log
# then: tail -f /tmp/bm25-tune-judge-stageA.log
```

### 5.7 `pricing.py` — cost recording and the hard $50 ceiling

Two user requirements land here: *"this entire process should not cost more than \$50"* and
*"ensure that the costs are recorded and stored — we will need the cost analysis for later for the
scientific report."* They are one module because the ceiling is enforced from the same numbers the
report is written from.

**The rate table is frozen data, not a constant in code.**
`bm25tune/prices/bedrock-gpt-oss-20b-aps2-2026-07-30.json` **ALREADY EXISTS** — it was fetched and
committed during planning (8 rate entries + the raw `PriceList` for audit). Do **not** re-fetch it;
just load it. It holds the verbatim extract from the AWS Pricing API
(`boto3.client("pricing", region_name="us-east-1")`, ServiceCode `AmazonBedrock`, regionCode filter
`ap-southeast-2`), **[measured] 2026-07-30**. The API's own `unit` field reads `"1K tokens"` for every
entry, so US$ per 1 000 tokens:

| usagetype (`APS2-openai.gpt-oss-20b-mantle-…`) | US$ / 1K tokens |
|---|---|
| `input-tokens-standard`  | 0.0000721 |
| `output-tokens-standard` | 0.0003090 |
| `input-tokens-batch`     | 0.00003605 |
| `output-tokens-batch`    | 0.0001545 |
| `input-tokens-flex`      | 0.00003605 |
| `output-tokens-flex`     | 0.0001545 |
| `input-tokens-priority`  | 0.000126175 |
| `output-tokens-priority` | 0.00054075 |

We use **standard on-demand** (the Converse path). The file records `retrieved_utc`, the region, the
model id, and the raw Pricing API `PriceList` entries so the cost analysis is reproducible without a
live API call; `pricing.py` loads it and **fails fast if the requested (model, region, tier) is
absent** — never silently falls back to a guessed rate, because a wrong rate would corrupt both the
report and the ceiling. A `python -m bm25tune refresh-prices` subcommand re-fetches and writes a
*new* dated file (never overwrites), and the manifest records which dated table a run used, so a
mid-experiment price change is visible rather than retroactive.

```python
RATE_TABLE_ID = "bedrock-gpt-oss-20b-aps2-2026-07-30"

@dataclass(frozen=True)
class Rates:
    input_per_1k: float; output_per_1k: float; tier: str; table_id: str

def load_rates(model_id: str, region: str, tier: str = "standard") -> Rates   # raises UnknownRate

def call_cost(usage: dict, rates: Rates) -> dict      # -> the "cost" block of §5.3, or None if usage is None

class CostMeter:
    """Cumulative spend across the whole experiment. Durable, crash-safe, reconcilable."""
    @classmethod
    def load(cls, costs_dir: Path) -> "CostMeter"     # totals.json, else replay ledger.jsonl, else 0
    def add(self, cost: dict | None, usage: dict | None, *, run_id: str, stage: str) -> None
        # usage feeds the token-count running means in totals.json (the pre-flight basis, layer 1)
    def spent_usd(self) -> float                      # experiment-wide
    def spent_by_stage(self) -> dict[str, float]
    def checkpoint(self) -> None                      # append ledger line + atomic totals.json rewrite
    def reconcile(self, log_dir: Path) -> tuple[float, float]  # (ledger total, judgment-log total)

class BudgetExceeded(RuntimeError): ...

class BudgetGuard:
    def __init__(self, meter: CostMeter, cap_usd: float, concurrency: int): ...
    def preflight(self, est_calls: int, est_in: int, est_out: int) -> dict   # returns the estimate dict; raises if it can't fit
    def check(self) -> None    # raises BudgetExceeded when spent + reserve >= cap (see layer 2)
```

**Thread-safety by construction, not locks:** `CostMeter.add()` and `BudgetGuard.check()` are
called **only from the single writer thread** (§5.4's concurrency model — workers put finished
records on the queue; the writer thread is the sole consumer). One mutating thread ⇒ no lock needed
and no torn float; worker threads never touch the meter. The pre-flight runs on the main thread
before any worker exists. `test_pricing.py` need not test locking — it pins the single-writer
contract instead (the CLI wiring is asserted in `test_cli.py`'s budget-stop case).

**Checkpoint cadence and reconciliation semantics.** `checkpoint()` runs on the writer thread on
the same 10-record/5-second cadence as the log fsync (§5.3) and unconditionally in the drain
(§5.8), so ledger and log can never drift by more than one cadence window. A crash inside that
window leaves the ledger *behind* the log — that gap is inherent, bounded, and self-healing: the
**judgment log is authoritative** (it is written first, per call), so `judge-pool` startup runs
`meter.reconcile(log_dir)` and, if the log total exceeds the ledger total, the meter adopts the
log total and appends a `{"kind": "heal"}` ledger line. The reverse — ledger total > log total by
more than $0.001 — cannot arise from a crash and is reported as an integrity error (a doctored
ledger or lost log segment).

**Enforcement, three layers:**

1. **Pre-flight (before any Bedrock call in a stage).** The driver estimates
   `est_calls × (mean_in × input_rate + mean_out × output_rate)`. The mean token counts come from
   `costs/totals.json`, which the meter maintains alongside the dollar totals:
   `{"calls", "input_tokens", "output_tokens", "max_call_usd", ...}` — so once WP0 has run, every
   later pre-flight automatically uses the *measured* means (`input_tokens / calls` etc.); with an
   empty meter it falls back to the **[measured]** 900 in / 300 out priors and says so in the
   `[BUDGET]` line (`basis=prior` vs `basis=measured`). It logs, and writes to `costs.json`:
   `[BUDGET] stage=A est_calls=12500 basis=measured est_usd=$1.97 spent=$0.18 cap=$50.00 remaining=$49.82 → OK`.
   If `spent + est > cap`, it **refuses to start**, prints the shortfall and the exact env var to
   raise, and exits **code 4** — before spending anything.
2. **Continuous, on every completed call.** There is no "batch" in the judging loop — the
   `ThreadPoolExecutor` is continuously fed — so the check runs where every result already flows
   through one thread: the **writer thread** calls `meter.add(...)` then `guard.check()` per
   record (a float compare — computationally free). `check()` raises `BudgetExceeded` when
   `spent + reserve ≥ cap`, where **`reserve = concurrency × max_observed_cost_per_call`** (floored
   at the **[measured]** worst-case prior, $0.000275): at the moment the check can trip, at most
   `concurrency` calls are in flight and each can bill at most about the worst call seen so far, so
   the reserve provably covers the overshoot the drain will still record — at concurrency 16 that
   is ~$0.005, not a meaningful bite out of the cap. (A fixed 2 % fraction — an earlier draft — was
   simultaneously ~900× too large at this cap and not actually tied to what is in flight.) Because
   the reserve tracks the *observed* per-call maximum, a prompt-length blow-up both raises the
   reserve and accelerates spend, so it trips within seconds rather than at the end. Because the
   raise happens on the writer thread, it does not propagate by magic: the writer catches
   `BudgetExceeded`, sets `stop_requested` with trigger `budget`, and keeps consuming the queue
   (draining, not judging); the main thread notices the flag and runs `drain_and_checkpoint`
   (§5.8), which also stops the feeder racing new work in.
3. **On `BudgetExceeded`**: the driver runs the **shared drain routine (§5.8)** with trigger
   `budget` — in-flight calls are drained, not discarded (they are already billed; dropping them
   would waste money *and* lose judgments) — then logs
   `[BUDGET] HARD STOP — spent=$X of cap=$Y; N pairs unjudged; raise BM25_TUNE_BUDGET_USD and re-run
   the same command to resume`, and exits **code 5**. Partial results remain scoreable: `score` reports
   per-config judged@10 coverage, so a budget-truncated run yields an honest, clearly-caveated matrix
   rather than nothing.

Exit codes are distinct on purpose — `0` ok, `1` unexpected, `3` credential expiry, `4` pre-flight
budget refusal, `5` mid-run budget stop, `6` calibration gate failure, `130`/`143` signalled drain
(§5.8) — so the launching agent can react without parsing logs. This table is the single canonical
list; §7.1's README section and §5.8's drain table must match it.

**Pilot-then-calibrate, enforced by a flag.** `judge-pool --pilot N` judges only N pooled pairs
(default N=200 when the flag is bare), **sampled evenly across topics with `random.Random(13)`** —
not the first N, which would be topic-clustered and bias the token-count basis toward whichever
narratives sort first — then **stops and prints the measured cost basis**:
observed mean input/output tokens, US$/call, the extrapolation to the full pool, and the updated
remaining budget. The full run is a separate invocation. WP7/WP8 both require the pilot line to be
pasted into chat before the multi-hour job is launched, and the pilot's judgments are cached, so the
pilot costs nothing extra — it is 200 of the calls the full run would make anyway.

**Cost reporting for the paper** — `costs.md` per run, and an experiment-wide roll-up written by
`python -m bm25tune cost-report`:

- total US$ and total calls, split by stage (calib / A / B / continuity) and by prompt version;
- mean/median/p95 input and output tokens per call, and US$/call, with the cache-hit count and
  **US$ saved by the cache** (cache hits × observed mean cost per call — an *estimate*, labeled as
  such in `costs.md`: the avoided calls' true token counts are unknowable) — the caching design's
  payoff, quantified, which is exactly the kind of number the report needs;
- cost per judged pair, cost per query, and cost per grid cell evaluated — "judged pair" =
  unique `jkey`, i.e. prompt-version-qualified, so a pair judged under two prompt versions counts
  twice and the denominator matches what was actually billed;
- billed-but-wasted spend: parse failures, retries, and max-token truncations, in US$;
- the rate table id and tier, so every figure is traceable to the committed price file;
- a reconciliation line asserting ledger total == judgment-log total (±$0.001; the log is
  authoritative and a lagging ledger self-heals on load — see the checkpoint semantics above), so
  a genuine mismatch flags an integrity problem, not a crash artifact.

`pricing.py` is pure stdlib and has no boto3 import (the rate file is data), so all of the above is
hermetically testable — see the `test_pricing.py` cases in §7.3.

### 5.8 The shared drain routine, signal handling, crash windows, and clobber protection

Three robustness gaps, closed here because each one can destroy already-paid-for work:

- **ONE drain routine, three triggers.** Credential expiry (§5.4), `BudgetExceeded` (§5.7), and
  signals all funnel into a single `drain_and_checkpoint(trigger: str)` in the driver — never three
  parallel implementations, because a shutdown path that only fires in rare conditions is exactly
  the code that rots. The routine: (1) set the `stop_requested` event so the feeder submits no new
  work; (2) await in-flight futures (bounded by a 60 s drain timeout, then abandoned — they are
  already billed, so we *want* their results); (3) join the writer thread after the queue empties,
  flush + fsync the log segment; (4) snapshot the cache; (5) checkpoint the cost meter and write
  `costs.json`/`costs.md`; (6) log the trigger-specific line; (7) exit with the trigger's code:

  | trigger | log prefix | exit code |
  |---|---|---|
  | `cred_expiry` | `[CRED]` | 3 |
  | `budget` | `[BUDGET]` | 5 |
  | SIGINT | `[SIGNAL]` | 130 |
  | SIGTERM | `[SIGNAL]` | 143 |

  The drain itself is trigger-agnostic and covered once by the `test_cli.py` drain test.
- **`SIGINT`/`SIGTERM` graceful drain.** A bare Ctrl-C or a job-scheduler kill during
  `judge-pool` would tear down the `ThreadPoolExecutor` and discard every in-flight judgment —
  each of which has *already been billed*. The signal handler only sets the `stop_requested` flag
  plus the pending exit code — no I/O in the handler itself; the main thread notices and runs
  `drain_and_checkpoint`, logging `[SIGNAL] SIGTERM — drained N in-flight, checkpointed, resume
  with the same command` and exiting via `sys.exit(130/143)` after the drain completes (the
  conventional 128+signum codes; we exit cleanly rather than re-raising the default handler
  precisely because a clean checkpoint is the point). A second
  signal during the drain exits immediately (so a hung call can't trap the operator).
- **`fsync` cadence (rationale for §5.3's rule).** A pure line-count cadence (an earlier draft said
  "every 25 lines") leaves minutes of already-billed work exposed to a machine crash whenever the
  call rate is low. Hence §5.3's rule: **`flush()` per line plus `os.fsync()` every 10 lines *or*
  every 5 seconds, whichever comes first** (the writer thread already wakes on a queue timeout, so
  the time-based branch is free), and unconditionally on drain/shutdown. At ~2 calls/s that is an
  fsync every ~5 s — negligible I/O against 6.5 s calls.
- **`--fresh` clobber protection.** Any subcommand offering `--fresh`/`--force` must never delete
  raw judgment segments or the cost ledger — those are append-only audit records by definition.
  `--fresh` is scoped to *derived* artifacts only (run dir, cache snapshot, score files) and works
  by **renaming** the existing run dir to `<run_id>.superseded-<UTCts>` rather than deleting it.
  Attempting `--fresh` on `judgments/log/` or `costs/` is a hard error naming `rebuild-cache` as the
  intended tool. Without `--fresh`, a subcommand that would overwrite an existing non-empty output
  refuses and prints the path.

## 6. The grid, volumes, wall-clock, statistics

### 6.1 Grid (Stage A): 5×5 + baseline = 26 configs

```
k1 ∈ {0.5, 0.7, 0.9, 1.2, 1.6}
b  ∈ {0.2, 0.35, 0.5, 0.65, 0.8}
+ baseline (0.9, 0.4) as the 26th cell
```

Justification: chunks are length-controlled by the chunker (median ~2.4 kB), so lower `b`
(length normalization matters less) and lower `k1` (tf saturates fast in short texts) are the
plausible winning direction — the grid extends 2 steps below the pyserini default on both axes
while still covering Lucene's 1.2/0.75 corner (which **[measured]** reorders results materially,
top-10 overlap 0.72). Step sizes ≈0.2–0.3 in k1 and 0.15 in b are finer than the expected
effect-size resolution given mode-dominated labels; a finer grid would multiply judge cost for
differences the labels can't resolve. **RM3 is OUT of scope**: it's an orthogonal
query-expansion knob that would double-to-quadruple the grid and change the latency profile;
flagged as a follow-up experiment once k1/b are pinned.

Stage B: **top 3 Stage-A configs + baseline** over all 1063 queries.

### 6.2 Volume arithmetic (show in README/worklog)

Reuse comes from the topic-level cache key: ~2 subsample queries/topic (Stage A) and 3–16
queries/topic (Stage B) all share one narrative. For the *observed* hits alone the ratio is
9208 hits → 8580 unique (topic, chunk) pairs; pooling is where dedup pays.

- **Stage A**: 250 queries × ~50–65 unique pooled chunks/query (**[measured]** 1.44× inflation at
  6 configs, extrapolated 1.7–2.2× at 26), deduped within topic (2 queries/topic overlap ~15–25 %)
  ⇒ **~10,000–13,000 unique (topic, chunk) pairs**.
- **Stage A search**: 26 × 250 = 6,500 executions @ ~13 q/s ⇒ **~8–10 min** (+9.4 s cold start).
- **Stage A judging**: at concurrency 16, median 6.5 s/call ⇒ sustained ~1.5–2.0 calls/s ⇒
  **~2–3.5 h**. Judging exceeds search cost by ~20×; **judging dominates** — all engineering effort
  goes to judge throughput, caching, resumability, none to search parallelism.
- **Stage B search**: 4 × 1063 ≈ 4,250 executions ⇒ **~6 min**.
- **Stage B judging**: 119 topics × ~8–9 queries × ~40 unique union chunks/query (4 configs) with
  heavy intra-topic overlap ⇒ ~25,000–30,000 unique pairs, of which the ~10–13k Stage-A pairs
  (drawn from the same topics and the densest configs) are already cached ⇒ **~15,000–22,000 new
  calls ⇒ ~2.5–4 h**. The cache delta is reported at judge start (`[CACHE] hits=…`), not assumed.
- **Calibration**: 5 × 280 + 50 stability = 1,450 calls ⇒ **~20–25 min** (five variants as of
  2026-07-31 — `facet-rare3-v1` added, §3.2).
- **umbrela-v1 continuity scoring** on the Stage-B pool (optional, decided post-WP0): a second
  prompt version over the same pool = a full extra pass (~25–30k calls, ~4 h). Default: run it on
  the Stage-A pool only (~10–13k calls) unless the user asks for full coverage.
- **Total Bedrock volume** (without any continuity pass; the Stage-A-only default adds ~10–13k
  more — §6.2b's TOTAL row includes it): ≈ 30,000–36,000 calls,
  ≈ 27–36 M input tokens, ≈ 10–14 M output tokens (**[measured]** ~760–1040 in / 58–648 out per
  call). Wall-clock end-to-end: **one working day**, dominated by two 2.5–4 h judge jobs.

### 6.2b Cost arithmetic against the $50 ceiling [measured rates, §5.7]

At standard on-demand ap-southeast-2 rates, a typical call (900 in / 300 out) costs
**$0.000158** — i.e. **$0.158 per 1 000 judgments**. Worst case (1040 in / 648 out): $0.000275/call.

| Stage | calls | typical US$ | worst-case US$ |
|---|---|---|---|
| WP0 calibration (5 × 280 + 50 stability) | 1,450 | $0.23 | $0.40 |
| Stage A judging (upper est.) | 13,000 | $2.05 | $3.58 |
| Stage B judging, new pairs (upper est.) | 22,000 | $3.47 | $6.05 |
| umbrela-v1 continuity on the Stage-A pool | 13,000 | $2.05 | $3.58 |
| **TOTAL (everything, upper estimates)** | **49,450** | **$7.80** | **$13.61** |

**$50 buys ~182,000 worst-case calls — 3.7× the entire plan.** Two consequences the executors must
internalize: (a) the ceiling will not be reached by the plan as designed, so any `[BUDGET]` trip is
*prima facie* a bug (runaway prompt length, cache miss storm, retry loop) and must be investigated,
not worked around by raising the cap; (b) there is no cost argument for cutting corners — judge the
full pool, keep depth 30, run the continuity pass. The plan costs **16 % of the cap typical, 27 %
worst case**.

**Optional spends, and what the $50 cap does to them** (user's call, not the executor's). At $200
these were rounding errors; at $50 they are real fractions of the ceiling and must be requested with
a cost line, not assumed:

| optional extra | ≈ cost | cumulative with the base plan | % of $50 cap (worst case) |
|---|---|---|---|
| 7×7 grid instead of 5×5 | +$1 | $8.75 / $14.53 | 29 % |
| full-pool umbrela-v1 continuity instead of Stage-A-only | +$4 | $11.75 / $17.53 | 35 % |
| **3-sample self-consistency vote (attacks R1)** | **+$16** | **$23.75 / $29.53** | **59 %** |
| all three together | +$21 | $28.75 / $34.53 | 69 % |

Even all three at once fits inside $50 with ~30 % to spare, so the cap does not force a choice —
but it does mean the executor must **ask, with the number, rather than proceed**. If only one can be
justified, take the self-consistency vote: it is the only one that addresses R1, the single risk that
could invalidate the entire result. Surface this table to the user with the WP0 report.

### 6.3 Throughput/throttling posture

Default concurrency **16** (measured safe at 20 with zero throttles; 16 leaves headroom for the
account's other users), exponential-backoff-with-jitter on any throttle, and the heartbeat exposes
the achieved rate so a human can bump `BM25_TUNE_JUDGE_CONCURRENCY` if Bedrock proves generous.
The budget guard's reserve scales with concurrency automatically (§5.7 layer 2), so raising it
needs no other change.

### 6.4 Statistics (Stage B)

- **Primary test: two-sided paired t-test** on per-query nDCG@10 deltas (candidate − baseline),
  α = 0.05, **Bonferroni-corrected across the 3 candidate-vs-baseline comparisons**
  (per-comparison α = 0.0167). Wilcoxon signed-rank (normal approximation, n > 100) reported
  alongside as the distribution-free check.
- **Multiple-comparisons / selection-bias handling**: the top-3 were *selected* on the Stage-A
  subsample, so the confirmatory p-values are computed on the **825 held-out queries**
  (**[measured, WP1]** 1063 − 238; an earlier draft said 813 off the ~250 estimate). Full-1063 point
  estimates are reported too, clearly labeled descriptive. The held-out list is derived by set
  difference against the persisted subsample file, never recomputed from the seed.
- **Effect sizes and CIs, not just p-values** (mandatory given mode-dominated labels): mean delta,
  Cohen's d on deltas, and a 95 % bootstrap CI (10,000 resamples over queries, seed 13).
- **Clustering robustness**: queries within a topic are correlated, so a topic-level paired t-test
  (per-topic mean deltas, n = 119) is reported as a robustness line; if query-level significance
  vanishes at topic level, the topic-level result is the honest headline.
- All of the above per metric: primary exp-gain nDCG@10, plus the pre-registered secondaries.

## 7. Documentation, manifest, publication

### 7.1 `tasks/bm25_tune/README.md` — required contents

Purpose and one-paragraph result summary (filled post-run); JDK/pyserini setup (the exact conda
create command for the record, `JAVA_HOME` value, `pyserini==2.3.0` + the `pyserini.__version__`
AttributeError gotcha); the canonical env-var block and every subcommand with a copy-paste example;
artifact layout map (§4.2) and where the durable copy of the /tmp input lives; **how to resume**
(re-run the same command; the exit-code table — 3 = refresh SSO creds, 4/5 = budget, 6 = calibration
gate, 130/143 = signalled drain); **the budget and cost section**: the $50 approved cap, the fact that
`BM25_TUNE_BUDGET_USD` has no default and must be exported per run (a spending command exits 1 without
it), `python -m bm25tune budget` to check spend before launching anything, the
committed rate table and how to refresh it, where costs are recorded (log → ledger → totals →
`costs.md`), the measured $0.158/1000-judgments basis, and the standing instruction that a
`[BUDGET]` trip means *investigate a bug*, not raise the cap (§6.2b);
**how to read the logs** (the grep-prefix table, the heartbeat format); gotchas: `maxTokens=1024` (the 512/64 truncation trap),
bare model id only, block-iteration parsing, never flip `set_bm25` mid-batch, 9.4 s cold start,
index is read-only under another user's home; the metric conventions (§5.5) and the §3.4 honesty
paragraph verbatim.

### 7.2 Run manifest — `data/bm25-tune/runs/<run_id>/manifest.json`

`{run_id, stage, git_sha, created_utc, index_dir, index_num_docs (asserted 921892634),
input_file, input_sha256, query_count, topic_count, subsample_seed, subsample_size, grid (full
list), depth, prompt_version(s), judge_model_id, region, max_tokens, temperature, concurrency,
pool_stats {unique_pairs, per_query_mean, inflation_vs_single}, cache {hits, misses},
judge_stats {calls, parse_failures, throttles, cred_expiries, input_tokens, output_tokens},
cost {rate_table_id, tier, preflight_estimate_usd, actual_usd, usd_by_stage, usd_per_judged_pair
(judged pair = unique jkey, per §5.7), cache_hits, usd_saved_by_cache,
wasted_usd {retries, parse_failures, truncations}},
budget {cap_usd, spent_before_usd, spent_after_usd, remaining_usd, tripped (bool)},
prefix_miss_count, timings {search_s, judge_s}, exit_code, resumed_from (list of prior
pids/segments)}` — everything needed to reproduce or audit the run **and to write the cost section of
the report** without reading code. `preflight_estimate_usd` next to `actual_usd` is deliberate: the
ratio between them is the estimator's accuracy, which is itself a reportable number and the thing
that makes the *next* experiment's budgeting trustworthy.

### 7.3 Tests — `tests/bm25_tune/` (hermetic; runs in root env with zero new deps)

Wiring: `tests/bm25_tune/conftest.py` does
`sys.path.insert(0, str(REPO_ROOT / "tasks" / "bm25_tune"))` — localized, no root `pyproject.toml`
change (its `pythonpath` stays `["src", "src/systems", "tests"]`;
`--import-mode=importlib` makes this safe). Because every `bm25tune` module is stdlib-only at
import time (§4.1), **no `importorskip` is added anywhere ⇒ no changes to `scripts/test.sh`
dep groups, `.github/workflows/tests.yml`, or `scripts/git-hooks/pre-commit`, and the suite stays
skip-free on a JVM-less CI runner.** Root-conftest autouse fixtures (`no_network`,
`no_ambient_creds`, `isolated_data_dir`) apply automatically and are exactly what we want: a test
that accidentally reaches Bedrock or the real index fails loudly. `stub_search_tool` /
`scripted_provider` are for the `src/` layers and are NOT reused here — this task has its own seams.

How the 900M-doc index is faked: **no tiny Lucene index, no JVM in tests.** The seam is
`ChunkSearcher`'s public surface; tests inject a `FakeSearcher` (same four methods, driven by a
dict of scripted rankings that shift when `set_config` changes) into `pool`/`cli` code paths. The
real pyserini path is covered by the `smoke` subcommand (§5.6) and one `@pytest.mark.live` test
for the judge (real single Converse call; boto3 arrives via the existing `aus-agent` dep group that
`scripts/test.sh` already passes — reusing `test_aus_agent.py`'s exact precedent, so still no
config changes). The searcher's live path cannot run under the root env (pyserini isn't installed
there) — it is exercised by `python -m bm25tune smoke` under the task env instead, and the README
says so.

Files and load-bearing cases (every test gets a docstring saying something its name does not —
why the behaviour matters or what breaks; module docstrings carry the "what this file defends"
prose, per CLAUDE.md):

- `tests/bm25_tune/data/mini-labeled.jsonl` — 6 handcrafted rows (2 topics, keyword+semantic mix,
  one `prefix_chars>0` hit, one prefix outlier, one voided hit) mirroring the real schema.
- `test_extract.py` — keyword filtering drops semantic rows; (topic, query) dedupe; subsample
  determinism under seed 13; `strip_page_prefix` slice-vs-regex-vs-passthrough including the
  outlier passthrough (defends the judge's input fidelity — a regression here silently corrupts
  every judgment).
- `test_prompts.py` — registry sha256 pins for all four versions (a silent prompt edit MUST fail a
  test, because the cache key depends on the version id honestly naming the text); template
  rendering with narrative/passage.
- `test_judge.py` — `parse_grade` on real-shaped Converse payloads: reasoning-before-text block
  order; empty text at `stopReason=max_tokens` (pins the maxTokens=64 trap); `##facet:` capture;
  malformed output → None; `classify_error` on fake exceptions carrying
  `response["Error"]["Code"]`; backoff sequence with a fake clock; `CredentialsExpired`
  propagation. Judge object takes an injected fake `converse` callable — no boto3 import needed.
- `test_store.py` — append/replay round-trip; truncated-tail-line tolerance (crash safety);
  latest-successful-wins on re-judge; **prompt_version keying isolation** (a `umbrela-v1` grade
  must never satisfy a `facet-v1` lookup — the poisoning bug WP0 exists to prevent) and its dual,
  the **cross-run cache hit** (same jkey, different `run_id`/`stage` → hit; pins that billing
  metadata never leaks into the key, §5.3); snapshot
  atomicity (tmp+rename); rebuild-from-log equals incremental state; two writer segments merge.
- `test_pool.py` — per-topic union across configs and across a topic's queries; depth cutoff.
- `test_metrics.py` — hand-computed nDCG@10 for both gain conventions (a 3-doc worked example in
  the docstring); unjudged→0; ideal-from-topic-qrel (a chunk judged for the topic but absent from
  this query's ranking still shapes the ideal — the deflation property §5.5 documents); perfect
  ranking scores 1.0; Recall/MAP binarization thresholds; the two precision@10 columns (§5.5)
  hand-computed, their flat-10 denominator pinned from the direction it can be got wrong, a
  **rank-permutation test** (shuffling the top 10 moves nDCG and leaves both precisions fixed), and a
  grade-1-only ranking where `p10_bin2` is 0 while `gp10` is not (the signal binarization discards).
- `test_stats.py` — paired t on a known-answer vector; Wilcoxon normal-approx sanity; bootstrap CI
  determinism under seed; Bonferroni threshold.
- `test_pricing.py` — `call_cost` against a hand-computed figure from the committed rate file (pins
  that a rate-table edit or a units slip — per-token vs per-1K — fails a test rather than silently
  mis-reporting the paper's cost section by 1000×); `load_rates` raises `UnknownRate` for an unknown
  model/region/tier instead of defaulting; `CostMeter` load→add→checkpoint→reload round-trip;
  ledger-replay equals `totals.json` (the crash-recovery path); a log total ahead of the ledger
  self-heals on load while `reconcile` still flags a ledger *ahead* of the log (the two §5.7
  reconciliation semantics); **`BudgetGuard.preflight` raises when the estimate exceeds the cap**
  (the CLI maps it to exit 4) and `check` raises `BudgetExceeded` once
  `spent + concurrency × max_observed_cost ≥ cap` — fed fake usage blocks with inflated token
  counts, pinning that both the spend and the reserve track *observed* reality, not the prior;
  `usage: null` rows cost nothing and don't crash the meter.
- `test_cli.py` — end-to-end tiny sweep with `FakeSearcher` + fake judge over the mini fixture:
  run files written, pool built, judgments logged, scores produced; **resume test**: kill the fake
  judge after N calls, re-invoke, assert zero re-judged keys (the property the whole cred-expiry
  design rests on); **budget-stop test**: a cap set below the fake run's cost aborts with exit 5,
  and the *already-judged* pairs survive in the cache so the follow-up run with a raised cap judges
  only the remainder (pins that a budget stop costs no money twice); **`--fresh` protection test**:
  `--fresh` renames the run dir and never touches `judgments/log/` or `costs/`, and refuses outright
  when pointed at them; **drain test**: setting the `stop_requested` event mid-run flushes every
  completed judgment and checkpoints the meter (signal handling itself is tested by invoking the
  handler function directly — no real signals in pytest).

Also: add the `bm25-tune` shorthand → `tests/bm25_tune` to the case list in `scripts/test.sh`
(shorthand only; DEP_GROUPS untouched). Run `bash scripts/test.sh` (full suite) before every
commit.

### 7.4 Publication, worklog, CLAUDE.md

- **Publish (committed)** → `evaluation-results/bm25-tune/<run_id>/`: `manifest.json`,
  `calibration-report.md`, `scores.csv` + `scores.md` (full per-config matrix — every grid cell,
  both gain conventions, all secondaries — never just the winner), `stats.json`,
  `qrels-<prompt_version>.txt` (TREC 4-col format, ~25–30k lines ≈ 1–2 MB — committable),
  **`costs.json` + `costs.md` and the dated `prices/bedrock-gpt-oss-20b-aps2-*.json` rate table**
  (small, and required for the report's cost analysis to be reproducible — this is the one part of
  the cost trail that gets *committed*, not just rsync-synced), and a
  short `README.md` stating that raw judge events/logs are excluded per the `evaluation-results`
  convention and live under `data/bm25-tune/judgments/` (rsync-synced). A tiny
  `tasks/bm25_tune/scripts/publish_results.py` mirrors the `scripts/publish-ragdoll-results.py`
  pattern (copy + manifest with `excluded` list).
- **Worklog** `worklogs/2026-07-30-bm25-tune-harness.md` (code) and
  `worklogs/<run-date>-bm25-tune-sweep.md` (experiment — self-contained per CLAUDE.md): the
  **verbatim** prompt texts of all five variants, query-set provenance (file, sha256, the
  keyword-filter and dedupe counts, subsample seed), the calibration result matrix, the **full**
  grid result matrix, how relevance was judged (model, region, maxTokens, temp, parsing rule),
  the statistics with effect sizes/CIs, **the complete cost accounting** (the §6.2b table with
  *actual* alongside estimated, rate table id and tier, US$/1000 judgments, cost per judged pair,
  US$ saved by the cache, billed-but-wasted spend, and total spend against the $50 cap — this is
  the source material for the report's cost section, so it goes in verbatim rather than summarized),
  artifact paths, and copies of the raw sweep log into
  `worklogs/assets/2026-07-XX-bm25-tune-stageA.log` (+ stageB) and of `costs.md`.
- **CLAUDE.md "Active Tasks"**: yes, add an entry (one bullet, same style as siblings):
  *"BM25 k1/b tuning — working in `tasks/bm25_tune/`. Tunes BM25 on the chunked ClimbMix index
  (read-only, under `BM25_TUNE_INDEX_DIR`) against aus_agent's 1063 keyword queries with a
  gpt-oss-20b Bedrock judge (pooled 0–3 qrels, cached under `data/bm25-tune/judgments/`).
  JDK 21 conda env in-folder; `JAVA_HOME=tasks/bm25_tune/env/lib/jvm`."*

## 8. Risks and mitigations

- **R1 — Judge grade compression (the primary threat, [measured]).** Mode-dominated labels flatten
  DCG and IDCG; neighbouring cells tie; the paired test may find nothing. **It threatens from both
  ends**: a harsh judge (umbrela-v1, 10 % at ≥2, mode 72.5 %) leaves too few relevant chunks to
  separate configs, and a fully saturated one (~98 % at ≥2) drives IDCG toward DCG so nDCG@10
  approaches 1 for every config. The gate became two-sided on 2026-07-31 to bound both. **Do not
  over-claim the saturation half:** §3.3b measured power to be ≤0.03 for *every* label distribution
  tested at a small effect and n=119, harsh and lenient alike, so the binding constraint on power is
  sample size and effect size, not the grade distribution. Mitigations: the WP0 gate (§3.3) before any
  sweep spend; exponential gain as primary; effect sizes + CIs + pre-registered binarized/Recall/MAP
  secondaries so a null is interpretable; the measured 0.72 top-10 overlap floor proves rank movement
  exists for labels to reward. Honest framing pre-committed in §3.4.
- **R2 — UMBRELA-on-narrative soundness.** Confirmed unsound in its verbatim form (§1); the design
  answer is the adapted rubric family + calibration gate, with verbatim UMBRELA retained as a
  comparability column, and the agent-label caveat (§3.3) preventing over-reading the smell test.
- **R3 — Mid-run credential expiry.** Detect → drain → flush → exit 3 → re-run; cache guarantees
  zero re-judging (tested in `test_cli.py` resume case).
- **R4 — prefix outliers: RETIRED as a live risk.** **[measured, WP1]** there are none — all
  3890/3890 keyword hits (8359/8359 all-engine) corroborate `prefix_chars` against the header regex
  exactly. The earlier "31 outliers" figure is not reproducible (§2.1). The passthrough branch, the
  `[PREFIX-MISS]` counter and the manifest field stay as cheap insurance against a future re-export;
  the residual risk is now the *opposite* one — a silent blind slice — which §5.1's corroboration
  rule closes.
- **R5 — 202 voided/`unjudged` agent hits.** Irrelevant as ground truth (agent labels aren't
  ground truth at all); they participate in calibration strata like any hit and are simply excluded
  from the positive/negative agreement cross-tab.
- **R6 — The ~97 whole-doc-era queries.** Excluded from the headline (§2.2): different retrieval
  regime, never validated against the chunked index, <10 % volume. Extractor kept for provenance;
  optional appendix run if the user wants it.
- **R7 — Index under another user's home.** Read-only, env-var path, fail-fast on open with a
  clear message; `num_docs` asserted (921,892,634) and recorded in the manifest so a moved/rebuilt
  index can't silently change the experiment.
- **R8 — /tmp input volatility.** Already neutralized: durable checksummed copy in
  `data/bm25-tune/inputs/`; `verify-inputs` re-checks before every stage.
- **R9 — Concurrent `set_bm25`.** Prevented by design: single searcher, sequential configs,
  documented warning; parallelism only via `batch_search(threads=16)`.
- **R10 — Bedrock throttling under sustained multi-hour load** (unseen so far at C=20, but the
  probes were short). Backoff+jitter, heartbeat-visible rate, tunable concurrency env var.
- **R11 — Runaway spend.** The named risk behind the $50 cap. Plausible mechanisms: a cache-key bug
  re-judging everything (would cost 2× — still trivial), a prompt-assembly bug pasting the whole
  narrative *per passage* into a batch (10–100× input tokens), or a retry loop billing every attempt.
  Mitigated by the three-layer guard (§5.7) whose per-call check keys off *observed* cost, so any of
  these trips within seconds rather than at the end. Because expected spend is ~16 % of the cap
  (§6.2b), a trip is a **bug signal**: the runbook says investigate before raising
  `BM25_TUNE_BUDGET_USD`.
- **R12 — Wrong price rates silently corrupting the cost analysis.** A per-token/per-1K units slip
  would misreport the paper's cost figure by 1000× and disable the ceiling. Mitigated by committing
  the verbatim Pricing API extract as data, pinning a hand-computed cost in `test_pricing.py`,
  refusing unknown (model, region, tier) rather than defaulting, recording the rate-table id in every
  judgment record and the manifest, and reconciling ledger totals against the judgment log.
- **R13 — Losing already-billed work to an ungraceful stop.** A Ctrl-C, scheduler kill, or budget
  trip that dropped in-flight judgments would waste money and force re-judging. Mitigated by §5.8:
  signal-handled drain, 10-line/5-second fsync, meter checkpointing, and append-only artifacts that
  `--fresh` is structurally forbidden from deleting.

## 9. Work packages (subagent execution plan)

Dependency graph — WP1 first; WP2/WP3/WP3b/WP4 in parallel; WP5 with them; WP6 gates WP7; WP8
after WP7; WP9 finalizes.

- **WP1 — Scaffolding** (blocking everything): `tasks/bm25_tune/pyproject.toml`, `config.py`,
  `logging_setup.py`, `prompts.py`, `extract.py`, `cli.py` skeleton with `verify-inputs` +
  `extract-queries`; verify the existing `data/bm25-tune/inputs/` checksum (already copied —
  §1 last bullet); `uv sync --project tasks/bm25_tune` and a `python -m bm25tune verify-inputs`
  green run. Deliverables include `queries/keyword-1063.jsonl` and `subsample-250.jsonl`.
- **WP2 — Searcher + pooling** (needs WP1): `searcher.py`, `pool.py`, `search-sweep` subcommand,
  `extract_trajectories.py`; live sanity via `smoke --search-only` (3 queries, warmup logged — the
  judgment half of `smoke` needs WP3+WP3b, so full `smoke` first runs once all three have landed,
  before WP6 spends on calibration). Runs concurrently with WP3/WP4.
- **WP3 — Judge + store** (needs WP1, parallel with WP2): `judge.py`, `store.py`, `judge-pool` +
  `rebuild-cache` subcommands, cred-expiry drain/exit path, heartbeat integration, **the §5.8
  signal-drain handler, fsync cadence, and `--fresh` protection**.
- **WP3b — Pricing, cost recording, budget guard** (needs WP1; can run parallel with WP2/WP3, but
  **WP3 must integrate it before `judge-pool` makes a single real call** — no Bedrock spend happens
  in an un-metered code path): `pricing.py` loading the **already-committed** dated rate file
  (§5.7 — do not re-fetch it), `cost-report` / `budget` / `refresh-prices` subcommands, the `cost`/`run_id`/`stage` fields in the log record, the pre-flight
  and per-call checks, the `--pilot N` flag, `costs.json`/`costs.md` writers, and `test_pricing.py`.
- **WP4 — Metrics + stats** (needs WP1, parallel with WP2/WP3): `metrics.py`, `stats.py`, `score` +
  `stats` subcommands.
- **WP5 — Tests** (per-module, written alongside WP2–4 by the same agents; `test_cli.py` after all
  three land): everything in §7.3 + the `scripts/test.sh` shorthand; `bash scripts/test.sh` full
  suite green.
- **WP6 — Calibration (= Work Package 0 of the science, §3)** (needs WP1+WP3+WP3b): this is the
  **pilot** the user asked for — smallest real spend first (1,450 calls, ~$0.23, ~20–25 min). Run
  `calibrate`, produce `calibration/report.md`, apply the **two-sided** §3.3 gate (four conditions;
  a variant may fail from either direction, and both measured variants are expected to), report
  `[BUDGET]`/`[COST]` lines and
  the **measured** mean token counts (persisted in `costs/totals.json`, whence every later
  pre-flight reads them in place of the priors — §5.7 layer 1),
  and **the user reviews the report and confirms the prompt version before WP7 launches**. Surface
  the §6.2b headroom options (finer grid / self-consistency vote) with the report.
- **WP7 — Stage A** (needs WP2–6 + gate): `search-sweep --stage A` (~10 min), then
  **`judge-pool --pilot 200` first** — paste its measured cost basis and updated projection into chat
  — then the full `judge-pool` (~2–3.5 h, ~$2, tracked background + tee, command verbatim in chat
  per §5.6), then `score` and `cost-report`; commit the Stage-A score matrix and cost breakdown.
- **WP8 — Stage B + statistics** (needs WP7): top-3 + baseline over 1063, `judge-pool --pilot 200`
  then the cache delta (~2.5–4 h, ~$3.50), `score`, `stats` (held-out 825, Bonferroni, bootstrap),
  `cost-report`, optional umbrela-v1 continuity pass on the Stage-A pool.
- **WP9 — Docs + publication** (needs WP8): README final (incl. the budget/cost section and exit-code
  table), both worklogs + `worklogs/assets/` log and `costs.md` copies, the experiment-wide
  `cost-report` roll-up with its reconciliation line, `publish_results.py` run into
  `evaluation-results/bm25-tune/<run_id>/` (including `costs.*` and the rate table), CLAUDE.md Active
  Tasks entry, final `bash scripts/test.sh`, commit.

Commit checkpoints: after WP5 (harness + tests), after WP6 (calibration report), after WP7
(Stage A results), after WP9 (final). Each commit runs the full offline suite via the pre-commit
hook; no commit touches `src/` so the architecture-diagram check never fires.

**Standing rule for every executing agent:** `export BM25_TUNE_BUDGET_USD=50.0` (it has no default
— every spending command refuses without it, §0), run `python -m bm25tune budget` before launching any
job that calls Bedrock, and include the `[BUDGET]` pre-flight line in the chat message that reports
the launch. No agent may raise `BM25_TUNE_BUDGET_USD` above the approved figure on its own initiative
— a trip is escalated to the user with the diagnosis, per R11.
