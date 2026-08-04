# facet_rag — next-session plan

Written 2026-08-04, after the orchestrator/analyzer/curator rebuild and the
first `aus_agent` comparison. Everything below was checked against what is
actually on disk; where a claim could not be verified it says so.

**Read this first:** the headline result of the last session — "facet_rag is
0.1–0.3 UMBRELA behind aus_agent" — is **not a valid measurement**. The two
systems were judged on different passage text for the same docids (§1). Nothing
in §3 should be acted on until §2.1 has re-established the baseline.

---

## 0. Aims — checkable targets for the improved system

Derived from reading both systems' actual final answers on aus_agent's top-5
dev topics, not from generic RAG advice. Current facet_rag numbers are from
`evaluation-results/facet_rag/curator_full/`; aus_agent from
`evaluation-results/aus-agent/` (`run_id == "aus-agent-dev-full"`).

| # | Aim | Current facet_rag | aus_agent (dev-full) | Target |
|---|---|---|---|---|
| A1 | **Use the word budget.** Track cap is 1024 words; nugget-rubric coverage is bounded by how much the answer says. | 314 / 413 / 464 words (31–45% of cap) — and *no facet_rag run ever recorded, across 20 runs in 7 eval dirs, exceeded 767 words* | 922 / 967 / 1007 / 1014 / 1018 (90–99% of cap, deliberately) | ≥ 850 words on every broad narrative; keep short answers short for narrow ones |
| A2 | **Fact density per sentence.** | CS:GO answer: 2 specific figures in 20 sentences ("$2.49 per key", "$400 million in 2018"); **zero dates in a "gaming history and culture" essay** | CS:GO answer: ~15 figures/dates/proper names (1999, 2012, $250,000, $1M, $2M, 2.75M viewers, 1,802,853 players, 26M, Minh "Gooseman" Le, fnatic, iBUYPOWER, KQLY) | ≥ 50% of factual sentences carry a number, date, or proper name |
| A3 | **Synthesis across sources.** A sentence citing 2–3 docids is one the writer actually combined. | 1.00–1.35 citations per cited sentence; CS:GO is exactly **1.00** — one evidence item transcribed per sentence | 1.00–1.43; 10 of 29 CS:GO sentences combine 2–3 sources | mean ≥ 1.3 citations per cited sentence on broad narratives |
| A4 | **Citation support (the actually-scored metric).** | **never measured** — only `ragdoll umbrela judge` has been run | `full_support_rate` 0.347, `partial_or_full` 0.868, no-support 83/781 = 10.6% (`evaluation-results/aus-agent/support-bedrock/judgments.summary.csv`) | `partial_or_full` ≥ 0.87, no-support ≤ 10% |
| A5 | **Keep the recall advantage.** Spec `rag-task.md:129`: an answer object with no citations scores **0 for weighted recall** and is excluded from precision entirely. | 100% of sentences cited on all 3 topics — strictly better than aus_agent here | 79–91% cited; aus_agent's 6 uncited CS:GO transitions each take a 0 on recall | stay ≥ 95% cited **while** hitting A1–A3 |
| A6 | **Argue, don't list.** | CS:GO answer has no opening thesis, no conclusion, no causal connective; facet seams are visible (sentences 0-2 gameplay, 3-5 weapons, 6-8 maps, 9-11 community, 12-14 economy, 15-19 esports) | opens with a thesis, closes with a 3-cited synthesis, uses transitions ("That preserved 'flavor' became central to the game's staying power") | opening thesis + closing synthesis present; no visible facet-block ordering |
| A7 | **Answer the deliverable, not the topic.** | CS:GO: asked for a *history and culture feature essay*; produced a feature-list summary with no history | PRESCHOOL answer opens "Since your gentle, preventative-only approach is not enough for this particular child…" and works the questioner's own five subsystems in SWARM | the first sentence must name the requested artifact and the questioner's stated situation |
| A8 | **Say what the corpus could not support.** | no mechanism; a facet with an unfillable gap silently burns iterations | SWARM sentence 21: "…the committed evidence does not include a single paper proving that exact joint bound, which remains an identified gap" | at most one such sentence, present when a planned facet genuinely failed |

**Where facet_rag is genuinely ahead and must not regress:** A5 (100% citation
coverage), and multi-facet decomposition guarantees every declared aspect gets
its own retrieval budget — aus_agent's single continuous loop can and does drop
a planned coverage area silently.

---

## 1. The measurement is broken — read before trusting any number

### 1.1 The two systems were judged on different text (blocking)

`evaluation-results/*/answers.resolved.jsonl` holds the `segments` the UMBRELA
judge actually saw. For **the same docid** `shard_04677_48238` on the CS:GO
topic:

- aus_agent: **3,632 chars** (whole document)
- facet_rag: **2,000 chars** (exactly the cap — same opening text, cut short)

Across the judged sets: aus_agent median passage **3,741–3,971 chars**
(mean 5,358–8,458); facet_rag median **exactly 2,000**, with **35 of 42
segments (83%) pinned at 2,000**. UMBRELA grades passage↔query relevance, so a
passage truncated before its relevant content scores lower. facet_rag was
handicapped by roughly 1.8× less text per judged passage in **every cell of the
comparison table**.

Cause: `scripts/resolve-rag-output-references.py` has two fetch paths —
`--api-base-url` (POST `/doc/batch`, returns a single ~2,000-char *page*; note
the judged passages begin "Page 3 of document: …") and `--doc-url` (Pyserini,
default `DEFAULT_PYSERINI_DOC_URL`, returns the full doc). The two resolves used
different ones. Neither script truncates client-side — the difference is the
endpoint.

**Action:** re-resolve `data/outputs/facet_rag/*.output.json` through the
*same* path aus_agent used (`--doc-url`, i.e. omit `--api-base-url`), re-run
UMBRELA, and only then compare. Do the same for anything new.

### 1.2 The rest of the methodology, in priority order

- **Single trials.** The same CS:GO topic scored 1.429 then 0.875 on
  consecutive trials under identical code. Every delta in the session's table
  is within that noise band. Minimum viable: 3 trials/topic, report the spread.
- **Wrong metric.** UMBRELA scores reference-pool relevance. The track scores
  weighted citation precision/recall (`rag-task.md:128-131`), nugget-rubric
  coverage, and pairwise battles. `ragdoll support judge` has still never been
  run on facet_rag. It is the metric the whole citation-precision fix was for.
- **`data/outputs/facet_rag/` is empty.** Every trajectory from the last
  session is gone; only the derived `evaluation-results/facet_rag/*/
  answers.resolved.jsonl` survive. That is why several questions below say
  "cannot be answered from disk". Keep the run artifacts this time.

---

## 2. Do these before writing any new code

### 2.1 Re-baseline honestly *(blocking everything else)*

```sh
# 1. re-resolve facet_rag through the same endpoint aus_agent used
python scripts/resolve-rag-output-references.py data/outputs/facet_rag/ \
    --ragdoll-output evaluation-results/facet_rag/<tag>/answers.resolved.jsonl
#    (no --api-base-url: falls back to --doc-url / Pyserini full documents)

# 2. UMBRELA, as before
python scripts/ragdoll-answers-to-umbrela.py \
    evaluation-results/facet_rag/<tag>/answers.resolved.jsonl \
    --output evaluation-results/facet_rag/<tag>/umbrela.input.jsonl
cd evaluation/ragdoll && uv run ragdoll umbrela judge \
    --provider amazon-bedrock --model openai.gpt-oss-120b-1:0 \
    --input-file .../umbrela.input.jsonl \
    --output-file .../umbrela-bedrock-120/judgments.jsonl
```

Sanity check before judging: median segment length should now be ~3,500–4,000,
not 2,000.

### 2.2 Run `ragdoll support judge` — highest-value missing measurement

`ragdoll support judge` consumes the **same** `answers.resolved.jsonl` shape
(`references` + `answer[].citations` as int positions + `segments`) — see
`evaluation/ragdoll/src/ragdoll/support/resolve.py:113-124`. No new input
builder needed:

```sh
cd evaluation/ragdoll && uv run ragdoll support judge \
    --provider amazon-bedrock --model openai.gpt-oss-120b-1:0 \
    --input-file  ../../evaluation-results/facet_rag/<tag>/answers.resolved.jsonl \
    --output-file ../../evaluation-results/facet_rag/<tag>/support-bedrock-120/judgments.jsonl \
    --raw-events-dir ../../evaluation-results/facet_rag/<tag>/support-bedrock-120/raw-events
python scripts/ragdoll-support-to-csv.py <...>   # gives the summary.csv shape
```

Compare against `evaluation-results/aus-agent/support-bedrock/
judgments.summary.csv` (`aus-agent-dev-full`: 781 judged citations, 0.347 full,
0.868 partial-or-full, 10.6% no-support). Metric definitions:
`evaluation/ragdoll/src/ragdoll/support/metrics.py:12-27`
(`WEIGHTED_SCORES = {-1:0, 0:0, 1:0.5, 2:1.0}`).

This is the check that tells you whether the evidence-block/heuristic-fallback
fixes actually bought precision, or only bought a plausible-looking answer.

### 2.3 Finish the 5-topic comparison

aus_agent's top-5 dev topics by UMBRELA (`aus-agent-dev-full`, restricted to
`research-rubrics-topics-dev.tsv`):

| topic | slug | aus_agent | facet_rag (curator_full) |
|---|---|---|---|
| `6847465956a0f6376a605404` | CS:GO feature essay | 2.083 (n=12) | 1.750 (n=12) |
| `6847465956a0f6376a60542a` | scaling to 1M users | 1.667 (n=21) | 1.400 (n=15) |
| `683a58c9a7e7fe4e76958498` | retirement blog series | 1.583 (n=12) | 1.467 (n=15) |
| `684397d188c1deceb49af32d` | pre-school teacher strategy | 1.467 (n=15) | **not run** |
| `6847465956a0f6376a60547e` | decentralized swarm proposal | 1.294 (n=17) | **not run** |

> Use 1.583/n=12 for the retirement topic, not the 1.500 quoted earlier in the
> session — that number mixed run_ids. All aus_agent figures above are
> `aus-agent-dev-full` only, recomputed from
> `evaluation-results/aus-agent/umbrela-bedrock-120/judgments.jsonl`.

The two missing runs **were attempted this session and failed**: every AWS
credential path is expired (`.env` `AWS_SESSION_TOKEN` → `ExpiredTokenException`
from `bedrock:Converse`; `~/.aws/sso/cache` tokens date from Apr 2025;
`aws sts get-caller-identity` fails on every profile with "Token has expired and
refresh failed"). A human must `aws sso login` / re-vend `.env` keys first.
Then:

```sh
uv run --group facet-rag python src/systems/facet_rag/run.py --qid 684397d188c1deceb49af32d \
    --run-id facet_rag.opus_plan_5topic --run-desc "facet_rag vs aus_agent: extending to aus_agent's top-5 topics"
uv run --group facet-rag python src/systems/facet_rag/run.py --qid 6847465956a0f6376a60547e \
    --run-id facet_rag.opus_plan_5topic --run-desc "facet_rag vs aus_agent: extending to aus_agent's top-5 topics"
```
then §2.1 + §2.2 over the results. These two topics are the interesting ones:
both are *deliverable-shaped* requests (a strategy report for a named situation;
a research-proposal scoping with the questioner's own five subsystems), which is
exactly where A7 predicts facet_rag is weakest.

### 2.4 Cheap instrumentation to add while re-running

None of these need an architecture change and all are currently unanswerable
because the trajectories were deleted:

- searches issued per run, and how many returned a docid already seen — the
  three mandatory engines (`loop.py:65`) fire the *same* sub-question at
  semantic/keyword/hybrid every iteration; measure the overlap.
- `ssr`/`lucene_bool` selection rate (`loop.py:66`). The one run ever checked
  used them 0/39 times. If a second run confirms 0%, delete the optional-Boolean
  half of `ORCHESTRATOR_QUERY_PROMPT` (`prompts.py:64-73`) — it is prompt budget
  buying nothing.
- draft word count → fact-check word count → final word count, per run. §3.1
  hinges on knowing which stage sheds the words.
- tokens/cost per run with and without the curator (`--top-n 0`-style bypass, or
  just one run each). The curator's third LLM call per productive iteration was
  accepted on faith and has never been priced.

---

## 3. Improvements, grounded in the aus_agent traces

Everything here comes from `tmp/aus-agent-traces/` (15 runs, 5 topics) and
`src/systems/aus_agent/prompts/system/default.md`, cross-read against
`src/systems/facet_rag/prompts.py`.

### 3.1 The answer is starved of content — the top problem *(→ A1, A2)*

Three multiplicative causes, all in facet_rag's own code:

1. **Hard evidence cap of 15 items.** `curator.DEFAULT_TOP_N = 3`
   (`curator.py:40`) × 5 facets = 15 references. All three `curator_full` runs
   produced exactly 15/12/15 refs — the count is mechanical, not chosen.
2. **Each item is only 2,000 chars.** `run.py:120` `--max-chars` default 2000.
   aus_agent stages **4,096 tokens ≈ 20,480 chars** per result
   (`aus_agent/tools/search.py:10-11`) and its judged segments average
   5,358–8,458 chars. facet_rag's synthesis therefore sees only each document's
   opening — which is boilerplate and intro prose ("You Are Here\nDecoding the
   Success of CS:GO's Game Design\nIntroduction:…"). **That is the direct cause
   of A2:** generic intros produce generic claims ("Valve monitors competitive
   data and community feedback", "A vibrant modding community creates custom
   maps") because the numbers live deeper in the document.
3. **The formatter compresses.** `ali_deepresearch/prompts.py:85`
   FORMAT_ANSWER_PROMPT says *"Rewrite the draft as a list of short factual
   sentences"* with no length floor, and `answer_format._trim_to_words` enforces
   a ceiling but never a floor.

Note the curator made this **worse**, not better: CS:GO went 438–767 words
pre-curator (`compare3v2`/`compare3v3`) → **314** post-curator. Precision was
bought with content volume. That trade was never measured; §2.2 is what decides
whether it was worth it.

Suggested order: raise `--max-chars` toward aus_agent's depth first (biggest
effect, one-line change, no architecture risk), re-measure, then revisit
`DEFAULT_TOP_N`, then the formatter prompt.

### 3.2 Commit-reason style — the analyzer/curator notes are the wrong shape *(→ A2, A3)*

This is the sharpest, most copyable difference. aus_agent's `commit_context`
reasons, verbatim from `aus-agent-dev-full`:

> `shard_03740_23115` — "Detailed 401k vs Roth IRA comparison: contribution
> limits ($22,500/$6,500 2023), RMD age 73, employer match, investment options,
> early withdrawal penalties"
>
> `shard_00385_39818` — "Concrete example of first Major (DreamHack Winter 2013,
> fnatic champions, $250k pool) and total of 20 Majors across CS:GO/CS2 history"
>
> `shard_05895_78239` — "Real Twitter capacity numbers (150M users, 300K read
> RPS, 5K writes/sec, up to 800 tweets/timeline) and explicit design guidance to
> adopt eventual consistency with SLOs like 99.5% timelines loading within
> 500ms"

Three properties facet_rag's notes lack:

- **They enumerate the specific facts.** A note is effectively a pre-written
  list of the claims the report can make from that document — the writer never
  has to re-read for them. facet_rag's `ANALYZER_PROMPT` (`prompts.py:90-91`)
  asks only for "what it supports and why", which returns a topic label.
- **They name the document's role**, not just its topic: "Counter-argument /
  practical caution against premature microservices adoption for startups…";
  "important caveat/counter-evidence for replica-only scaling"; "core structural
  framework for the report"; "relevant if search-by-keyword feature is added".
- **Counter-evidence is deliberately sought and labelled.** aus_agent's system
  prompt (`default.md:116-117`) says "Actively search for counter-evidence,
  contradictions, limitations, and missing perspectives" — and the traces show
  it landing (the gambling lawsuit, the match-fixing history, the anti-microservices
  caution). facet_rag's prompts never mention counter-evidence; its CS:GO answer
  contains none.

The concrete change: rewrite the `note` field's instruction in `ANALYZER_PROMPT`
to demand the specific facts (numbers/dates/names) the passage contributes, and
the role it plays. This costs nothing extra — same call, same schema — and the
note is what the synthesis prompt reads (`pipeline._render_evidence_block`
renders `note:` above the text).

Also worth copying: the commit tool's own schema wording,
`aus_agent/tools/commit_context.py:42-49`, which asks for "the distinct
evidence, claim, perspective, date, name, counter-evidence, or coverage area
this result **uniquely** contributes".

### 3.3 Search shape — 5× the calls for 1/3 the answer *(→ A2)*

Measured across all 15 traces:

| run | searches | commit calls | docs kept | retrieved | keep rate |
|---|---|---|---|---|---|
| dev-full / CS:GO | 8 | 2 | 12 | 80 | 15% |
| dev-full / retirement | 8 | 2 | 12 | 80 | 15% |
| dev-full / scaling | 14 | 4 | 21 | 139 | 15% |
| luna-dev4 / CS:GO | 7 | 2 | 11 | 37 | 30% |
| sat-go / retirement | 3 | 1 | 6 | 24 | 25% |

facet_rag, by contrast, issued **39 search calls** in the one run ever counted
(5 facets × 3 mandatory engines × ~2.6 iterations).

Two structural reasons aus_agent gets more out of fewer calls:

- **Its 8 searches are 8 different sub-questions.** facet_rag's 3 searches per
  iteration are *one* sub-question rephrased for three engines
  (`ORCHESTRATOR_QUERY_PROMPT`, `prompts.py:58-62`), against the same corpus —
  heavily overlapping result sets. Notably `aus-agent-dev-full` omitted
  `search_engine` entirely (single-engine run) and still produced the best score
  in the whole comparison (CS:GO 2.083). **Query diversity beat engine
  diversity.** Consider making the per-iteration plan "N distinct sub-questions,
  engine of your choice" instead of "one question × 3 mandatory engines".
- **Round 2 queries are traceable to round 1 documents.** `default.md:76-80`:
  "each new content-bearing query term must be traceable to a document retrieved
  in an earlier round". The traces show it working — round 1 was
  `"CS:GO long-term success factors esports history"`; round 2 was
  `"CS:GO cheating scandal VAC ban match fixing iBUYPOWER"`, and *iBUYPOWER is
  nowhere in the topic* — it came out of round 1's documents. facet_rag's gap
  feedback (`loop.py:224-228`) passes a gap string and a list of tried queries,
  but never the retrieved content, so follow-ups cannot specialise this way.
- **Effort scales with the question.** Scaling (broad) got 14 searches / 4
  rounds; retirement (narrower) got 8 / 2. facet_rag's budget is fixed at
  `facets × mandatory engines × iterations` regardless.

### 3.4 The two stages aus_agent doesn't have *(→ A6, A7)*

aus_agent's system prompt ends: *"There is no separate finalizer, formatter, or
compression phase"* (`default.md:260`). The model writes one sentence per line
with `[id]` markers, directly. facet_rag runs **draft → fact-check → LLM
reformat**, and the reformat is a lossy re-write by a model that never saw the
evidence text — only the draft and an allow-list of docids
(`FORMAT_ANSWER_PROMPT`). That stage is where structure (thesis, transitions,
conclusion) and length both die.

Worth evaluating: have the fact-check stage emit the final one-sentence-per-line
`[docid]` form directly, and reduce `format_answer` to a *parser* rather than a
rewriter. `answer_format._heuristic` stays as the safety net.

### 3.5 A spec detail the prompts currently get backwards *(→ A5)*

`rag-task.md:131`: "An answer object with no citations is omitted from
citation-precision scoring and receives a support score of 0 for weighted
recall."

So for a sentence making a **factual claim** that nothing supports, leaving it
uncited is pure loss — 0 recall, and no precision benefit, because uncited
objects aren't scored on precision at all. The precision-preserving move is to
**delete the sentence**. `FACT_CHECK_PROMPT` (`prompts.py:167`) gets this right
("remove or soften sentences left with no supporting citation"); the formatter
that runs *after* it gets it wrong — `ali_deepresearch/prompts.py:88`: "Zero
citations is valid and correct for a sentence nothing in the allowed list
actually supports". The last stage wins.

Fix is one prompt edit, but **`ali_deepresearch/prompts.py` is shared** — check
`ali_deepresearch` before editing, and run the full suite
(`bash scripts/test.sh`), not just `tests/systems/test_facet_rag.py`.

Nuance to preserve: aus_agent's uncited sentences are almost all pure
transitions asserting nothing about the world (CS:GO 0, 4, 10, 15, 18, 24).
Those are the correct case for an empty citation array — the rule should be
"assert nothing, or cite", not "always cite".

---

## 4. Carried-over items, re-triaged

| item | status now |
|---|---|
| 1.1 heuristic fallback as root cause | **done** — was the root cause, fixed |
| 1.2 make the fallback loud | **done** — `answer_format.py:172-178` |
| 1.3 support-judging instead of UMBRELA | **open, now top priority** → §2.2 |
| 1.4 comparison conflated pool size with quality | **worse than thought** → §1.1; the pool-size half was addressed by the curator, but the comparison is confounded by segment length |
| 1.5 / 2.3 uncited-sentence tradeoff | **open, and mis-specified** → §3.5; measure with §2.2 before tuning |
| 1.6 are ssr/lucene_bool worth keeping | **open** → §2.4; still 0/39 in the only run checked |
| 2.1 format stage discards half the word budget | **open and confirmed worse** → §3.1; 314–464 words vs a 1024 cap, and the curator made it worse |
| 2.2 analyzer rubber-stamps ~76% | **partially addressed** — curator caps the pool at 15, but its precision has never been checked; aus_agent's keep rate is 10–30% |
| 2.4 no stop condition for an unfillable gap | **open** → also A8; the curator's `covered` gate doesn't detect a repeated gap. Cheapest fix: keep the last 2 gap strings and stop the facet if they are near-identical |
| 2.5 planner invents non-researchable facets | **open, unverified** — no trajectories survive to check. Re-check after §2.3; the CS:GO facets read as topical, not format-derived, so this may be less common than feared |
| 2.6 fact-check only sees 2,000-char chunks | **open, and now the leading suspect for A2** → §3.1 |
| 2.7 `parse_analysis` treats unparsable JSON as `satisfied=True` | **open, low** (`loop.py:126-131`) — the curator gates the real stop decision now, but this silently drops a whole round's keeps. One-line fix when convenient |

Not tracked here: the architecture-diagram feature requests (GitHub #20) —
separate issue, deliberately deferred.

---

## 5. Decisions that need a human, not a guess

1. **Precision or recall?** A5 says facet_rag's 100%-cited answers are
   recall-optimal; A1–A3 say the content is too thin. The two pull opposite
   ways on the curator's `DEFAULT_TOP_N` and on `--max-chars`. Which does the
   submission optimise for? Pairwise battles and nugget coverage both reward
   content volume; citation precision rewards restraint.
2. **Does facet decomposition survive?** If the fix for A1/A6 is "write more,
   argue more, one continuous evidence pool", that is aus_agent's architecture.
   Is facet_rag meant to stay a genuinely different system (the case for it:
   guaranteed per-aspect retrieval budget, which aus_agent lacks), or converge?
3. **Full-scale validation cost.** Nothing has been run beyond 3 hand-picked
   topics. The 30-topic dev set and the 119-topic test set have never been run
   under this architecture. Someone needs to authorise the Bedrock spend for a
   full dev sweep before submission.
4. **Rubric/nugget scoring stays blocked.** The vendored `evaluation/ragdoll`
   lacks the `--rubric-style research` flag a prior collaborator's run used;
   reproducing it needs the full `nuggetizer create → assign` pipeline and more
   LLM cost. Out of scope last session — confirm it stays out.
5. **Credentials.** §2.3 is blocked until AWS SSO is refreshed. Nobody but the
   account owner can do this.

---

## Appendix — raw numbers behind §0

Answer shape, `aus-agent-dev-full` vs `facet_rag.curator_full`:

```
topic       system      sents  words  cited%  tot_cits  refs  cits/cited_sent
RETIRE      aus_agent      29   1007    100%        37    12       1.28
PRESCHOOL   aus_agent      26   1018     88%        27    15       1.17
CSGO        aus_agent      29    922     79%        33    12       1.43
SCALING     aus_agent      22   1014     91%        25    21       1.25
SWARM       aus_agent      23    967     83%        19    17       1.00
RETIRE      facet_rag      31    464    100%        42    15       1.35
CSGO        facet_rag      20    314    100%        20    12       1.00
SCALING     facet_rag      23    413    100%        31    15       1.35
```

Every facet_rag answer ever produced (7 eval dirs, 20 runs) — none exceeds 767
words:

```
compare3     958498  27 sents  637 w  81 refs      curator_diag 605404  15  324  12
compare3     605404  25 sents  394 w  48 refs      curator_full 958498  31  464  15
compare3     60542a  46 sents  599 w  87 refs      curator_full 605404  20  314  12
compare3v2   958498  26 sents  498 w  25 refs      curator_full 60542a  23  413  15
compare3v2   605404  39 sents  767 w 117 refs      diag2        605404  25  411  28
compare3v2   60542a  35 sents  628 w  31 refs      pilot        95846f  14  345  30
compare3v3   958498  33 sents  573 w  23 refs      pilot        958488  19  357  57
compare3v3   605404  19 sents  438 w  24 refs      pilot        95848b  16  294  48
compare3v3   60542a  40 sents  561 w  40 refs      pilot        958498  31  505  29
                                                   pilot        9af31d  27  518  20
```

Judged-passage lengths (the §1.1 confound):

```
aus-agent-dev-full   RETIRE     median 3741  mean 5737
                     PRESCHOOL  median 3971  mean 6006
                     CSGO       median 3494  mean 5358
                     SCALING    median 3903  mean 6303
                     SWARM      median 3338  mean 8458
facet_rag curator_full  all 3 topics  median 2000  (35/42 segments at the cap)
```
