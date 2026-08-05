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

> **Update 2026-08-04 (late):** `evaluation-results/facet_rag/` is GONE from
> this clone — it was never committed (`git log --all` has no trace of it), so
> every "Current facet_rag" cell below and the appendix's 20-run table are
> historical and unreproducible. Fresh, verifiable replacements exist: all 5
> topics were re-run (`run_id = facet_rag.opus_plan_5topic`, 2026-08-05, all
> `status=completed`, artifacts in `data/outputs/facet_rag/`, archived at
> `/research/remote/petabyte/users/oleg/trec_rag_26_data/`). Measured shape:
> CSGO 19 sents/365 w/100% cited/14 refs/1.11 c/cs; SCALING 33/460/100%/15/1.18;
> RETIRE 36/734/100%/12/1.14; PRESCHOOL 31/437/**94%**/14/1.03; SWARM
> 20/363/**90%**/15/1.00. Consequences: A1 confirmed (still 35–72% of cap; 734
> is the best ever, still under the old 767 max); A3's ≥1.3 target has now
> never been hit by any surviving run (1.00–1.18); and **A5's "100% cited" no
> longer holds** — PRESCHOOL/SWARM are the first sub-100% facet_rag answers,
> both already violate the ≥95% target, and they are exactly the two
> deliverable-shaped topics A7 predicts are weakest. The answers remain thin —
> the pattern §3 diagnoses is unchanged. These runs are unjudged (no UMBRELA,
> no support) — §2.1/§2.2 now have real inputs.

| # | Aim | Current facet_rag | aus_agent (dev-full) | Target |
|---|---|---|---|---|
| A1 | **Use the word budget.** Track cap is 1024 words; nugget-rubric coverage is bounded by how much the answer says. | 314 / 413 / 464 words (31–45% of cap) — and *no facet_rag run ever recorded, across 20 runs in 7 eval dirs, exceeded 767 words* | 922 / 967 / 1007 / 1014 / 1018 (90–99% of cap, deliberately) | ≥ 850 words on every broad narrative; keep short answers short for narrow ones |
| A2 | **Fact density per sentence.** | CS:GO answer: 2 specific figures in 20 sentences ("$2.49 per key", "$400 million in 2018"); **zero dates in a "gaming history and culture" essay** | CS:GO answer: ~15 figures/dates/proper names (1999, 2012, $250,000, $1M, $2M, 2.75M viewers, 1,802,853 players, 26M, Minh "Gooseman" Le, fnatic, iBUYPOWER, KQLY) | ≥ 50% of factual sentences carry a number, date, or proper name |
| A3 | **Synthesis across sources.** A sentence citing 2–3 docids is one the writer actually combined. | 1.00–1.35 citations per cited sentence; CS:GO is exactly **1.00** — one evidence item transcribed per sentence | 1.00–1.43; 10 of 29 CS:GO sentences combine 2–3 sources | mean ≥ 1.3 citations per cited sentence on broad narratives |
| A4 | **Citation support (the actually-scored metric).** | **never measured** — only `ragdoll umbrela judge` has been run | `full_support_rate` 0.347, `partial_or_full` 0.868, no-support 83/781 = 10.6% (`evaluation-results/aus-agent/support-bedrock/judgments.summary.csv`) | `partial_or_full` ≥ 0.87, no-support ≤ 10% |
| A5 | **Keep the recall advantage.** Spec `rag-task.md:129-131`: an answer object with no citations scores **0 for weighted recall** and is excluded from precision entirely. | 100% of sentences cited on all 3 topics — strictly better than aus_agent here | 79–91% cited; aus_agent's 6 uncited CS:GO transitions each take a 0 on recall | stay ≥ 95% cited **while** hitting A1–A3 |
| A6 | **Argue, don't list.** | CS:GO answer has no opening thesis, no conclusion, no causal connective; facet seams are visible (sentences 0-2 gameplay, 3-5 weapons, 6-8 maps, 9-11 community, 12-14 economy, 15-19 esports) | opens with a thesis, closes with a 3-cited synthesis, uses transitions ("That preserved 'flavor' became central to the game's staying power") | opening thesis + closing synthesis present; no visible facet-block ordering |
| A7 | **Answer the deliverable, not the topic.** | CS:GO: asked for a *history and culture feature essay*; produced a feature-list summary with no history | PRESCHOOL answer opens "Since your gentle, preventative-only approach is not enough for this particular child…" and works the questioner's own five subsystems in SWARM | the first sentence must name the requested artifact and the questioner's stated situation |
| A8 | **Say what the corpus could not support.** | no mechanism; a facet with an unfillable gap silently burns iterations | SWARM sentence 21: "…the committed evidence does not include a single paper proving that exact joint bound, which remains an identified gap" | at most one such sentence, present when a planned facet genuinely failed |

**Where facet_rag is genuinely ahead and must not regress:** A5 (100% citation
coverage — but see the §0 update: the fresh PRESCHOOL/SWARM runs are already at
94%/90%, so this lead has started to erode on deliverable-shaped topics), and
multi-facet decomposition guarantees every declared aspect gets its own
retrieval budget — aus_agent's single continuous loop can and does drop a
planned coverage area silently.

---

## 1. The measurement is broken — read before trusting any number

### 1.1 The two systems were judged on different text (blocking)

`evaluation-results/*/answers.resolved.jsonl` holds the `segments` the UMBRELA
judge actually saw. For **the same docid** `shard_04677_48238` on the CS:GO
topic:

- aus_agent: **3,632 chars** (whole document)
- facet_rag: **2,000 chars** (exactly the cap — same opening text, cut short)

Across the judged sets: aus_agent median passage **3,338–3,971 chars**
per topic (mean 5,358–8,458; see the appendix — the range quoted here
originally omitted the two low-median topics); facet_rag median **exactly
2,000**, with **35 of 42 segments (83%) pinned at 2,000**. UMBRELA grades
passage↔query relevance, so a passage truncated before its relevant content
scores lower. facet_rag was
handicapped by roughly 1.8× less text per judged passage in **every cell of the
comparison table**.

Cause: `scripts/resolve-rag-output-references.py` has two fetch paths —
`--api-base-url` (POST `/doc/batch`, returns a single ~2,000-char *page*; note
the judged passages begin "Page 3 of document: …") and `--doc-url` (Pyserini,
default `DEFAULT_PYSERINI_DOC_URL`, returns the full doc). The two resolves used
different ones. Neither script truncates client-side — the difference is the
endpoint.

> **Correction (2026-08-04, verified against the script + recovered traces):**
> the endpoint story above is incomplete. The resolver's PRIMARY path is
> neither endpoint — it resolves from **local `*.trajectory.json` files first**
> (`resolve-rag-output-references.py:268-276`) and only falls back to an API
> for docids the trajectories don't carry. aus_agent's judged segments
> byte-match its trajectory-staged texts exactly (verified 77/77 references
> across all 5 dev-full topics) — aus_agent looked "full-doc" because its
> search tool stages up to 4,096 tokens ≈ 20,480 chars per result
> (`aus_agent/tools/search.py:10-11`), not because of `--doc-url`. facet_rag's
> trajectories stage `--max-chars`-truncated search text, so **re-resolving
> with trajectories present reproduces the confound**: the fresh
> `facet_rag.opus_plan_5topic` trajectories resolve all 70/70 references at
> median exactly 2,000 chars, 56/70 pinned at the cap. (The Pyserini full doc
> for `shard_04677_48238` is exactly 3,632 chars — confirming aus_agent's
> staged text was the whole document.)

**Action:** re-resolve `data/outputs/facet_rag/*.output.json` through the
full-document path (`--doc-url`, i.e. omit `--api-base-url`), **and bypass the
trajectory-first path** — point `--trajectory-dir` at an empty directory,
otherwise every docid resolves from the 2,000-char trajectory text and the
`--doc-url` fallback never fires. Needs `PYSERINI_API_TOKEN` (present in
`.env`). Re-run UMBRELA, and only then compare. Do the same for anything new.

### 1.2 The rest of the methodology, in priority order

- **Single trials.** The same CS:GO topic scored 1.429 then 0.875 on
  consecutive trials under identical code. Every delta in the session's table
  is within that noise band. Minimum viable: 3 trials/topic, report the spread.
- **Wrong metric.** UMBRELA scores reference-pool relevance. The track scores
  weighted citation precision/recall (`rag-task.md:128-131`), nugget-rubric
  coverage, and pairwise battles. `ragdoll support judge` has still never been
  run on facet_rag. It is the metric the whole citation-precision fix was for.
- **The last session's artifacts are gone — all of them.** `data/outputs/`
  did not survive (untracked + Git-LFS'd, see `.gitattributes:1`), and the
  derived `evaluation-results/facet_rag/*/answers.resolved.jsonl` this plan
  originally called "the only survivors" turned out never to have been
  committed either — the whole `evaluation-results/facet_rag/` tree is absent
  from this clone and from git history. That is why several questions below
  say "cannot be answered from disk", and why §1.1's 35-of-42/median-2000
  numbers are no longer re-checkable. Mitigations now in place: the 5-topic
  re-run (see §0 update) exists in `data/outputs/facet_rag/`, and run data is
  archived off-repo at `/research/remote/petabyte/users/oleg/trec_rag_26_data/`
  — but archive-on-completion does not cover mid-run crashes; §6.3's
  partial-save is still needed. Keep the run artifacts this time.

---

## 2. Do these before writing any new code

### 2.1 Re-baseline honestly *(blocking everything else)*

The inputs now exist: `data/outputs/facet_rag/` holds the 5-topic
`facet_rag.opus_plan_5topic` run (see §0 update). Use `opus_plan_5topic` as
`<tag>`.

```sh
# 1. resolve through full documents — MUST defeat the trajectory-first path
#    (see §1.1 correction: with the *.trajectory.json files adjacent, every
#    docid resolves from 2,000-char truncated search text and the confound
#    comes right back)
mkdir -p /tmp/no-trajectories
python scripts/resolve-rag-output-references.py data/outputs/facet_rag/ \
    --trajectory-dir /tmp/no-trajectories \
    --ragdoll-output evaluation-results/facet_rag/<tag>/answers.resolved.jsonl
#    (no --api-base-url: falls back to --doc-url / Pyserini full documents;
#     needs PYSERINI_API_TOKEN, present in .env)

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
not 2,000 (the trajectory-resolved texts measure median exactly 2,000, 56/70
pinned at the cap — same confound as last session, now verified on fresh runs).

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

**Done 2026-08-05:** 149 citations judged, aggregate
`full_support_rate=0.443, partial_or_full_rate=0.826, no_support=12.1%`
(`evaluation-results/facet_rag/opus_plan_5topic/support-bedrock-120/judgments.summary.csv`)
— **beats** aus_agent-dev-full on full support (0.347) but is **below**
target on partial-or-full (0.868 aus_agent / ≥0.87 target) and no-support
(10.6% aus_agent / ≤10% target). Per-topic partial-or-full: CSGO 0.857,
SCALING 0.744 (worst — the broadest-facet topic, 39 citations judged),
RETIRE 0.829, PRESCHOOL 0.867, SWARM 0.889. Verdict on the §3.1 curator
tradeoff: the curator's evidence-block precision work did buy something real
(better full-support than aus_agent's uncurated pool), but the answer is
still too thin (§3.1 A1) and citation completeness lags on the broadest
topic. See `worklogs/2026-08-05-facet-rag-honest-rebaseline.md` for the raw
judgment breakdown.

### 2.3 Finish the 5-topic comparison

**Done 2026-08-05.** §2.1/§2.2 executed against `facet_rag.opus_plan_5topic`
(archive recovered from `~/Downloads/trec_rag_26_data/facet_rag-runs/` — the
in-repo `data/outputs/facet_rag/` and the off-repo `/research/remote/...`
mount from the prior session were both empty/unreachable on this machine).
Resolved through `--doc-url` with `--trajectory-dir /tmp/no-trajectories`:
0/70 references resolved from local trajectories, 70/70 via the API
fallback, median segment length 3,987.5 chars (0 pinned at 2,000) — confound
confirmed gone. Full writeup: `worklogs/2026-08-05-facet-rag-honest-rebaseline.md`.

aus_agent's top-5 dev topics by UMBRELA (`aus-agent-dev-full`, restricted to
`research-rubrics-topics-dev.tsv`):

| topic | slug | aus_agent | facet_rag (curator_full, confounded) | facet_rag (opus_plan_5topic, honest) |
|---|---|---|---|---|
| `6847465956a0f6376a605404` | CS:GO feature essay | 2.083 (n=12) | 1.750 (n=12) | 1.643 (n=14) |
| `6847465956a0f6376a60542a` | scaling to 1M users | 1.667 (n=21) | 1.400 (n=15) | 1.067 (n=15) |
| `683a58c9a7e7fe4e76958498` | retirement blog series | 1.583 (n=12) | 1.467 (n=15) | 1.417 (n=12) |
| `684397d188c1deceb49af32d` | pre-school teacher strategy | 1.467 (n=15) | unjudged | 0.857 (n=14) |
| `6847465956a0f6376a60547e` | decentralized swarm proposal | 1.294 (n=17) | unjudged | 1.200 (n=15) |

facet_rag trails aus_agent on UMBRELA on all 5 topics even with the confound
removed — the gap shrinks on RETIRE/SWARM (both within ~0.1) but stays wide on
SCALING (-0.6) and PRESCHOOL (-0.61, the largest gap of any topic — the
deliverable-shaped weakness §0/A7 predicted). §2.2's `ragdoll support judge`
(the metric that actually scores the submission) tells a different story: see
below — facet_rag's `full_support_rate` beats aus_agent's aggregate.

> Use 1.583/n=12 for the retirement topic, not the 1.500 quoted earlier in the
> session — that number mixed run_ids. All aus_agent figures above are
> `aus-agent-dev-full` only, recomputed from
> `evaluation-results/aus-agent/umbrela-bedrock-120/judgments.jsonl`
> (re-verified 2026-08-04: all five means and ns reproduce exactly). The
> facet_rag column is from the lost `evaluation-results/facet_rag/` judgments
> and is historical — and confounded per §1.1 regardless.

~~The two missing runs **were attempted this session and failed**: every AWS
credential path is expired.~~ **Resolved 2026-08-04:** credentials were
refreshed (`sts get-caller-identity` returns a valid assumed-role ARN; `.env`
re-vended with working `SEARCH_API_KEY` + backend URLs), and **all 5 topics
have since been run** — not just the 2 missing ones —
as `run_id = facet_rag.opus_plan_5topic` (see §0 update for the measured
shape). What remains is §2.1 + §2.2 over those results: they are entirely
unjudged. The two previously-missing topics are the interesting ones:
both are *deliverable-shaped* requests (a strategy report for a named situation;
a research-proposal scoping with the questioner's own five subsystems), which is
exactly where A7 predicts facet_rag is weakest.

### 2.4 Cheap instrumentation to add while re-running

None of these need an architecture change. The 5-topic re-run's trajectories
(now on disk) already answer the first two:

- searches issued per run — measured on `opus_plan_5topic`: 22/15/27/25/46
  (CSGO/SCALING/RETIRE/PRESCHOOL/SWARM); the three mandatory engines
  (`loop.py:65`) fire the *same* sub-question at semantic/keyword/hybrid every
  iteration. Still to measure: how many calls returned a docid already seen
  (the overlap).
- `ssr`/`lucene_bool` selection rate (`loop.py:66`). Measured on
  `opus_plan_5topic`: **3 lucene_bool / 135 total calls (2.2%), ssr 0** —
  confirming the earlier 0/39 reading. The orchestrator does occasionally pick
  lucene_bool (1 call each in CSGO/PRESCHOOL/SWARM), so before deleting the
  optional-Boolean half of `ORCHESTRATOR_QUERY_PROMPT` (`prompts.py:64-73`),
  check whether those 3 calls contributed any kept evidence; if not, it is
  prompt budget buying nothing.
- draft word count → fact-check word count → final word count, per run. §3.1
  hinges on knowing which stage sheds the words.
- tokens/cost per run with and without the curator (`--top-n 0`-style bypass, or
  just one run each). The curator's third LLM call per productive iteration was
  accepted on faith and has never been priced.

---

## 3. Improvements, grounded in the aus_agent traces

Two distinct sources, not one: aus_agent *trajectories* come from
`tmp/aus-agent-traces/` — recovered from pre-LFS git blobs (see its README);
originally 15 runs over only **3** topics (retirement 10, CS:GO 3, scaling 2),
extended 2026-08-04 to **20 runs / 5 topics** by recovering PRESCHOOL (3 runs)
and SWARM (2 runs) the same way. aus_agent *answer text* (what A6/A7/A8 quote
for PRESCHOOL/SWARM) comes from
`evaluation-results/aus-agent/answers.resolved.jsonl` (`aus-agent-dev-full`),
which always had all 5 topics. Cross-read against
`src/systems/aus_agent/prompts/system/default.md` and
`src/systems/facet_rag/prompts.py`.

### 3.1 The answer is starved of content — the top problem *(→ A1, A2)*

Three multiplicative causes, all in facet_rag's own code:

1. **Hard evidence cap of ~15 items.** `curator.DEFAULT_TOP_N = 3`
   (`curator.py:40`) × 5 facets = 15 references. All three `curator_full` runs
   produced exactly 15/12/15 refs. The fresh `opus_plan_5topic` runs give
   12/14/14/15/15 over 4–5 planned facets — so the count is bounded by
   `facets × top_n` and driven by it (RETIRE planned 4 facets → 12 refs), but
   not strictly pinned to it (CSGO: 5 facets, 14 refs). The cap, not a content
   judgment, still sets the ceiling.
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

> **Verified 2026-08-05 — the "biggest effect" prediction did not land.**
> `--max-chars` default raised 2000→20000 (`run.py`, commit `50f8f5d`), same 5
> topics re-run as `facet_rag.maxchars20k_5topic`, resolved/judged the same
> way as the `opus_plan_5topic` baseline (worklog:
> `worklogs/2026-08-05-facet-rag-maxchars-verification.md`). Single trial —
> read as a direction check, not a settled result (§1.2's noise-band warning
> applies here too).
>
> | topic | words (2k→20k) | cited% (2k→20k) | UMBRELA mean (2k→20k) | support partial_or_full (2k→20k) |
> |---|---|---|---|---|
> | CSGO | 365→317 | 100%→94% | 1.643→1.636 | 0.857→0.941 |
> | SCALING | 460→591 | 100%→94% | 1.067→1.133 | 0.744→0.689 |
> | RETIRE | 734→437 | 100%→100% | 1.417→1.500 | 0.829→0.919 |
> | PRESCHOOL | 437→613 | 94%→100% | 0.857→0.800 | 0.867→0.826 |
> | SWARM | 363→346 | 90%→100% | 1.200→0.800 | 0.889→0.875 |
>
> Mean words 471.8→460.8 (flat, not up); UMBRELA moved in both directions
> per-topic (SWARM dropped 0.40); support `partial_or_full` also mixed.
> **Root-cause read:** giving the analyzer more text per passage didn't
> translate into a longer or better-judged answer because the two other
> multiplicative causes in this section are untouched — the
> `facets × DEFAULT_TOP_N` reference cap (still 11-15 refs, barely moved from
> 12-15) and the formatter's no-length-floor compression are still binding.
> `--max-chars` alone was not sufficient; **`DEFAULT_TOP_N` and the formatter
> prompt are not optional follow-ups, they're required** — revise the
> "suggested order" above accordingly before spending more judge budget on
> `--max-chars` alone.

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

Measured from the trajectories (each row re-verified against
`tool_call_counts` and the run's `references` count; the manifest's "tool
calls" column is search+commit summed — don't confuse the two):

| run | searches | commit calls | docs kept | retrieved | keep rate |
|---|---|---|---|---|---|
| dev-full / CS:GO | 8 | 2 | 12 | 80 | 15% |
| dev-full / retirement | 8 | 2 | 12 | 80 | 15% |
| dev-full / scaling | 14 | 4 | 21 | 139 | 15% |
| dev-full / preschool | 6 | 3 | 15 | 60 | 25% |
| dev-full / swarm | 13 | 3 | 17 | 130 | 13% |
| luna-dev4 / CS:GO | 7 | 2 | 11 | 37 | 30% |
| sat-go / retirement | 3 | 1 | 6 | 24 | 25% |

(The preschool/swarm rows are from the traces recovered 2026-08-04. swarm
dev-full is the one run where `tool_call_counts_all` ≠ `tool_call_counts` —
one extra `commit_context` attempt, 4 vs 3.)

facet_rag, by contrast, issued **39 search calls** in the one old run ever
counted (5 facets × 3 mandatory engines × ~2.6 iterations), and the fresh
`opus_plan_5topic` runs issued 15–46 (SWARM: 46 searches for a 363-word
answer — vs aus_agent's 13 searches for 967 words on the same topic).

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
  rounds; swarm (broad) 13 / 3; retirement (narrower) 8 / 2; preschool 6 / 3.
  facet_rag's budget is fixed at `facets × mandatory engines × iterations`
  regardless.

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
| 1.6 are ssr/lucene_bool worth keeping | **open** → §2.4; now measured at 3/135 (2.2%, all lucene_bool, ssr 0) on the fresh 5-topic run |
| 2.1 format stage discards half the word budget | **open and confirmed worse** → §3.1; 314–464 words vs a 1024 cap, and the curator made it worse |
| 2.2 analyzer rubber-stamps ~76% | **partially addressed** — curator caps the pool at 15, but its precision has never been checked; aus_agent's keep rate is 10–30% |
| 2.4 no stop condition for an unfillable gap | **open** → also A8; the curator's `covered` gate doesn't detect a repeated gap. Cheapest fix: keep the last 2 gap strings and stop the facet if they are near-identical |
| 2.5 planner invents non-researchable facets | **open, now checkable** — the `opus_plan_5topic` trajectories survive; their facet names read as topical, not format-derived (e.g. CSGO: game design / esports / monetization / community / platform), so this may be less common than feared |
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
3. **Full-scale validation cost.** Nothing has been run beyond 5 hand-picked
   topics. The 30-topic dev set and the 119-topic test set have never been run
   under this architecture. Someone needs to authorise the Bedrock spend for a
   full dev sweep before submission.
4. **Rubric/nugget scoring stays blocked.** The vendored `evaluation/ragdoll`
   lacks the `--rubric-style research` flag a prior collaborator's run used;
   reproducing it needs the full `nuggetizer create → assign` pipeline and more
   LLM cost. Out of scope last session — confirm it stays out.
5. ~~**Credentials.** §2.3 is blocked until AWS SSO is refreshed.~~ **Resolved
   2026-08-04** — SSO refreshed, `.env` re-vended, all search backends live;
   §2.3's runs completed under the working credentials. Session tokens still
   expire, so re-check `sts get-caller-identity` at session start.

---

## 6. Shared infrastructure to build — benefits every system, not just facet_rag

Requested explicitly: three components that live in the shared layers
(`src/ragrun/`, `src/utils/`), not inside `src/systems/facet_rag/`, so
`aus_agent`, `ali_deepresearch`, `o3_deep_research`, and `claude-code-research`
get them too. Each already has a partial, non-shared precedent somewhere in
this repo — reuse/generalize those, don't start from a blank file (see each
item's "prior art").

### 6.1 Cost tracking and analysis

**Why it matters here specifically:** every number in §0/§3 came from token
counts (`ragrun.TrajectoryBuilder`'s `stats.tokens` block, via
`facet_rag.loop.usage_token_stats`), never dollars. The curator's "one more LLM
call per productive iteration" (§3.1, §4 item 2.2) was accepted on faith
because nobody could say what it cost. `tasks/bm25_tune/` needed a hard
$50 ceiling and had to build this from scratch *inside a task directory*
because nothing shared existed to reuse.

**Prior art:** `tasks/bm25_tune/bm25tune/pricing.py` — already does the hard
parts correctly and is worth reading before designing anything new: frozen,
committed rate tables (`prices/bedrock-gpt-oss-20b-aps2-2026-07-30.json`, a
verbatim AWS Pricing API extract — no rate is ever hand-typed), `Rates` /
`load_rates` (raises `UnknownRate` on an unmapped `(model, region, tier)`
rather than guessing), `call_cost(usage, rates) -> cost block`, and a
`CostMeter` for cumulative spend. It is deliberately task-scoped and
budget-ceiling-flavored (it also has a `BudgetGuard` that can hard-stop a run),
which facet_rag/ragrun-level cost tracking does not need — pull out the rate
table + `call_cost` shape, leave the budget-ceiling/single-writer-thread
machinery behind unless a future task actually needs a hard cap again.

**What to build:** a shared `pricing` module (`src/ragrun/pricing.py` or
`src/utils/pricing.py` — pick based on whether it should be importable without
pulling in ragrun's artifact-writing dependencies) that:
- takes a normalized usage dict (the shape `usage_token_stats` already
  produces: `input`, `input_uncached`, `output`, `cache_read`, `cache_write`)
  plus `(model_id, region)` and returns a cost-in-USD breakdown, using the same
  frozen-rate-file pattern as bm25_tune (one JSON per model/region combo
  actually used, committed under a `prices/` dir at the shared-layer level).
- plugs into `ragrun.TrajectoryBuilder` so a `cost` block appears next to the
  existing `tokens` block in every step's `stats` — one wiring point, and every
  system that already reports usage through `TrajectoryBuilder` gets $ figures
  for free, no per-system code.
- has a rollup: total run cost, and cost broken down by whichever dimension
  each system's steps already carry (facet_rag: `input`/role via each step's
  turn+facet; aus_agent: per round). Don't invent a new grouping key — reuse
  `trace_steps`' existing `turn`/`parent_id` structure.
- **facet_rag needs the orchestrator-vs-analyzer-vs-curator split specifically**
  once this exists, to actually answer §4 item 2.2/§3.1's open question ("was
  the curator's extra call worth it") with a number instead of a guess.

### 6.2 Timing — wall-clock duration, per run and per stage

**Prior art, and the gap:** `ragrun.TrajectoryBuilder._trace_step` already
computes `duration_ms` for every individual step from its `t_start`/`t_end`
(`src/ragrun/trajectory.py`) — the raw data exists. What's missing is
*aggregation*: nothing rolls per-step durations up into "this run took N
seconds total" or "the curator stage averages N ms across a run" without
hand-writing it per system. `aus_agent/agent.py` does this today with its own
local `perf_counter()`/`_elapsed_ms()` plumbing (`agent.py:27,147,422-423,578`)
— correct, but bespoke, and no other system has it. facet_rag does get a
run-level `trace.duration_ms` for free (`run_one` passes
`started_at`/`ended_at` to `tb.finalize` — the fresh CSGO run shows 92.6 s),
but almost no per-stage timing: only 4 of the CSGO run's 47 steps carry
`stats.duration_ms`, because the loop's replayed events never set
`t_start`/`t_end` (`pipeline._replay_events`). That per-stage gap is why
§1.2's "single trials, huge variance between runs" was never quantified with
real stage-level numbers this session.

**What to build:** a rollup that reads `trace_steps` (already has
`t_start`/`t_end`/`turn`/`type`/`stats.duration_ms` on everything) and produces,
into `trajectory.trace["summary"]` alongside the existing `tokens` block:
total run wall-clock (first step's `t_start` to last step's `t_end`), and a
breakdown by `type`/`kind` (so "how much of this run's wall-clock was
retrieval vs. LLM calls vs. formatting" is answerable without re-deriving it
by hand each time, the way this plan's §3.3 table had to be built by manually
reading 15 trajectory files). Same wiring point as §6.1 — both are pure
post-processing over data `TrajectoryBuilder` already has, not a new
instrumentation burden on any system.

### 6.3 Trajectory recording, aus_agent-parity — plus why facet_rag needs a design decision aus_agent didn't

**The immediate motivation:** §1.2 of this plan states that every artifact
from the last session is gone (originally phrased as "`data/outputs/facet_rag/`
is empty"; it turned out even the derived eval results were lost) — that's not
a cleanup accident, it's because facet_rag has **no partial/incremental save**.
The off-repo archive at `/research/remote/petabyte/users/oleg/trec_rag_26_data/`
now protects *completed* runs, but a mid-run crash still loses everything, so
this section stands.
`aus_agent.agent.save_partial()` (`agent.py:636-663`) rewrites `output.json`
with `trace.status == "running"` every 2 seconds during a run
(`PARTIAL_SAVE_MIN_INTERVAL_S`), so a crashed or killed aus_agent run still
leaves an inspectable, mid-run artifact. facet_rag's `pipeline.run_one` writes
*nothing* until the very end — kill it, lose a background-task timeout, hit
`ExpiredTokenException` mid-run (as §2.3 did this session), and the entire
run's evidence, searches, and partial answer are gone. This is independently
worth fixing regardless of the cost/timing work above.

**The harder, facet_rag-specific gap `aus_agent` doesn't have to solve:**
aus_agent's `raw_messages` capture is simple because aus_agent is *one*
provider, one continuous conversation — `provider.raw_messages` at the end of
the run is the whole story (`agent.py:611-612`). facet_rag constructs *dozens*
of provider instances per run (one orchestrator per plan/facet/draft/format
call, one analyzer per facet/fact-check call, one curator per facet — see
`pipeline.py`'s repeated `make_orchestrator()`/`make_analyzer()` calls and
`loop.py`'s per-facet `make_analyzer()` call for the curator role), each with
its own short-lived `raw_messages`. `tb.finalize()` is currently called with no
`raw_messages` argument at all (`pipeline.py`, the `tb.finalize(status=status,
started_at=..., ended_at=...)` call) — there is no equivalent of aus_agent's
"one provider's full history" to pass.

**What needs deciding before implementing, not guessing:** what "trajectory
recording" means for a many-short-conversations architecture. Options, roughly
cheapest to richest: (a) don't capture raw provider messages at all, rely on
the existing `LoopEvent`/rich-trace summaries (current state, minus the crash
gap) — cheapest, loses the actual prompt/response text for post-hoc debugging;
(b) capture each instance's `raw_messages` keyed by role + facet + call-site
into a list under `trajectory.trace` (richer, but the trace size grows with
facet count × iterations, unlike aus_agent's single history); (c) capture only
on failure/incomplete runs (the crash-recovery case that actually motivated
this) and skip it for `status == "completed"` runs, keeping the common case
cheap. Whoever picks this up should decide (b) vs (c) — both are reasonable,
they trade off differently between "debuggability of a normal run" and "trace
file size" — rather than defaulting to the biggest option without checking the
cost.

The **partial-save half is not blocked on that decision** and should ship
first: adapt `aus_agent.agent.save_partial`'s pattern (`save_run(..., 
trajectory=build_trajectory("running"), output=build_output([], []), 
timestamp=run_ts, validate=False, write_trajectory=False)`, called every
`PARTIAL_SAVE_MIN_INTERVAL_S`) into `pipeline.run_one`, ideally as a shared
helper in `ragrun` (it's already provider-agnostic — it only needs a
`TrajectoryBuilder` in progress and a timestamp) rather than copy-pasted a
second time.

---

## Appendix — raw numbers behind §0

The aus_agent rows below were re-verified 2026-08-04 against
`evaluation-results/aus-agent/answers.resolved.jsonl` and reproduce exactly.
The facet_rag rows (`curator_full` and the 20-run table) are **historical** —
their source files (`evaluation-results/facet_rag/`) are gone from disk and
from git history, so treat them as recorded observations, not re-checkable
data. The fresh, on-disk replacement is `facet_rag.opus_plan_5topic`:

```
topic       system      sents  words  cited%  tot_cits  refs  cits/cited_sent
CSGO        facet_rag*     19    365    100%        21    14       1.11
SCALING     facet_rag*     33    460    100%        39    15       1.18
RETIRE      facet_rag*     36    734    100%        41    12       1.14
PRESCHOOL   facet_rag*     31    437     94%        30    14       1.03
SWARM       facet_rag*     20    363     90%        18    15       1.00
    (* = opus_plan_5topic, 2026-08-05, data/outputs/facet_rag/ — unjudged)
```

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

Every facet_rag answer produced before the loss (7 eval dirs, 20 runs) — none
exceeds 767 words (historical; the 5 fresh runs above still fit the pattern,
max 734):

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
    (historical — the resolved files are gone; the same confound reproduces on
     the fresh runs: opus_plan_5topic trajectory texts resolve at median
     exactly 2000, 56/70 pinned at the cap. See the §1.1 correction.)
```
