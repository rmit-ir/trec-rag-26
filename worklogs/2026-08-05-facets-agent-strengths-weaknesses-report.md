# 2026-08-05 — facets_agent strengths/weaknesses report: full trajectory + response analysis

**Branch:** `main`. Full analysis of both systems' responses AND trajectories
(not just final answers) over their shared 15 topics
(`run_id=aus-agent-15topic` / `facets-agent-15topic`, the fresh post-fix
batch from `worklogs/2026-08-05-facets-agent-rerun-full-reevaluation.md`),
combining free structural analysis of the trace data with a budgeted
LLM-assisted qualitative pass. Goal: identify what worked, what didn't, and
concrete improvements for facets_agent (prompt / tools / process).

**Cost: $0.23 actual (estimated, pessimistically), against a $20 budget.**
15 `gpt-5.6-luna` calls, 48,030 input + 6,858 output tokens total. See
"Methodology" for the estimate basis.

## Methodology

Two passes, in order:

1. **Free structural analysis** (`worklogs/assets/2026-08-05-trajectory-behavior-analysis.py`,
   no API calls) — parses every trace step (`tool_call`/`generation`) across
   all 30 output artifacts: search-engine distribution, query length/`k` by
   engine, commit/reject/release counts, turn/token/wall-clock stats,
   rejection-reason breakdown, and a search-for-"facet"-in-reasoning check.
2. **Budgeted LLM diagnosis** (`worklogs/assets/2026-08-05-llm-diagnosis.py`,
   `gpt-5.6-luna`, one call per topic, JSON-mode, cached per topic) — for
   each of the 15 topics, fed the request, facets_agent's own search-query
   log, both systems' final answers, and the SPECIFIC rubric criteria an
   independent judge (`gpt-5.6-terra`, from the prior rubric-scorecard
   worklog) already found they differ on. Asked for a structured diagnosis:
   `weakness_category`, concrete `evidence` (not a restatement of the
   rubric), and an `improvement_suggestion`. Reusing the existing
   per-criterion judgments (rather than re-deriving quality from scratch)
   kept each call small and let the model focus on WHY, which the rubric
   scorer's 0/1/2 grades can't say by themselves.

Cost estimate basis: `gpt-5.6-luna` has no committed rate in this repo's
pricing table (Azure-hosted, no public listing) — used a deliberately
pessimistic placeholder ($3/1M input, $12/1M output, well above typical
rates for a model this size) so the reported figure is a safe upper bound,
not an optimistic one. Real cost is almost certainly lower.

## Quantitative behavioral comparison

| metric (mean per topic unless noted) | aus_agent | facets_agent |
|---|---|---|
| searches | 10.5 (min 7, max 17) | **18.6** (min 8, max 39) |
| search engines used | semantic, keyword only | semantic, keyword, hybrid (near-even split: 96/91/92) |
| commit_context calls | 2.7 | 3.6 |
| committed docs | 17.4 | 16.2 |
| rejected docs | 71.1 | **200.3** |
| commit yield (committed / total staged) | ~19.7% | **~7.5%** |
| `get_documents` calls | 0.0 | 0.6 |
| `release` uses | n/a (not offered) | **0** (built this session, never used) |
| model turns | 7.2 | 8.5 |
| wall-clock seconds | 67.3 | 61.7 (lower despite more searches — same-turn calls run in parallel) |
| processed tokens (cost proxy) | 88,228 | **195,047 (2.2x)** |
| failed search calls | 0 | 0 |
| Markdown/narration leakage | ~none | ~none |

**hybrid engine specifically** (facets_agent only): mean query length 19.3
words vs semantic's 11.8 and keyword's 9.7 — confirms the HyDE-style
hypothetical-passage instruction is being followed, not just a longer
keyword string. Mean `k` requested was 15.2, matching the
`DEFAULT_HYBRID_K=15` override and occasionally asking for more (up to 20).

**Rejection reasons**: 2,959 of 3,005 facets_agent rejections (98.5%) are
genuine "not selected for committed context" judgments, not duplicate
tombstones (46, 1.5%) — the high search volume is not literally re-finding
the same documents over and over; it is casting a wide net and discarding
most of it after genuine consideration.

## Design choices confirmed working as intended

- **Facet decomposition genuinely happens.** All 15/15 topics show the
  model's own reasoning text explicitly discussing "facets" (1-6 mentions
  each) before searching — the prompt's step 1 is not being ignored.
- **Engine coverage per facet is balanced and intentional**, not defaulting
  to one engine: semantic/hybrid/keyword usage is within a few percent of
  even (96/92/91) across the whole run.
- **The HyDE-style hybrid instruction works exactly as designed** — see the
  query-length/`k` numbers above. This was a specific, deliberate design
  choice (`worklogs/2026-08-05-facets-agent-new-system.md`) and the
  behavioral data confirms the model complies with it reliably.
- **No protocol violations**: zero failed search calls, zero commit-cap
  overflow, zero Markdown/narration leakage, engines never leaked outside
  the three offered (no `ssr`/`lucene_bool` calls despite the shared
  `tools.search_tool` layer still knowing about them).
- **Output-format compliance is clean** on both systems — this is not a
  differentiator, it's confirmation that both harnesses' final-report
  contract is being followed correctly.

## The dominant weakness: facet decomposition is too shallow, not search execution

**11 of 15 topics (73%) were diagnosed `search_coverage_gap`** — by a wide
margin the most common finding, and the single most actionable one. The
pattern, consistent across nearly every case: facets_agent's initial
decomposition step identifies a SMALL SET OF BROAD, OBVIOUS facets and then
searches them thoroughly (sometimes redundantly — see next section) — but
specific explicit or implicit sub-requirements in the request are never
turned into a facet at all, so they receive **zero search queries** and
consequently never appear in the final answer. This is a **planning
failure, not a retrieval failure**: the searches that DO happen mostly
succeed at finding relevant material; the problem is entire required
sub-topics never get searched for in the first place.

Concrete examples (topic id suffix in brackets), each independently
diagnosed by the LLM pass with reference to the actual search log:

- **[605476]** Alternate-history essay: 9 searches covered only Barbarossa,
  US-Soviet détente, and British decolonization — never searched for a
  shared US-Soviet enemy or internal British opposition, both explicitly
  required by the prompt. The final answer accordingly asserts an alliance
  and a communist Britain without explaining either mechanism.
- **[60547e]** Robotics research proposal: covered SLAM, task reassignment,
  and disruption-tolerant networking well, but never searched for
  UAV-vs-UGV-exclusive capabilities or concrete hazard sensors — both
  requested — leaving the final answer generic where it needed to be
  specific.
- **[605492]** Dermatology VLM experimental plan: 8 searches covered
  benchmark design and calibration broadly, but never searched for the
  specific secondary objective (predefined morphological features) or
  labeler credentials (board-certified) the request named explicitly.
- **[60535d]** AI-agent regulation framework: searched interpretability
  broadly ("transparency," "monitoring") but never for a single named
  technique (SHAP, LIME, feature attribution) — the rubric explicitly wanted
  a concrete method named.
- **[6054a7]** UBI comparison: 39 searches (the single largest search volume
  in the whole run) repeatedly re-confirmed employment/wellbeing/fiscal-cost
  findings for the same three pilot programs, but never once searched for
  Ontario eligibility criteria, political feasibility, or a baseline UBI
  definition — all requested, none searched for even once.

**Why this explains the arena result despite facets_agent searching 1.8x
more overall**: the extra search volume is being spent RE-CONFIRMING facets
already identified, not DISCOVERING facets that were missed. More search
effort within a too-narrow decomposition cannot fix a decomposition gap —
it just makes the well-covered parts even more thoroughly covered while the
missed parts stay at zero.

## Secondary weakness: research is adequate but the write-up loses requested structure

**3 of 15 topics (20%) were diagnosed `synthesis_organization`** — search
coverage was fine, but the final answer failed to preserve structure or
precision the request explicitly asked for:

- **[9af325]** (Baudelaire orphans overview): searched nearly every book in
  the series but wrote one continuous, unstructured narrative rather than
  book-by-book sections, and blurred specific facts under compression (wrong
  antagonist attributed to a plot event).
- **[9af32d]** (preschool behavior plan): the request wanted an executable
  first-15-minutes protocol; the answer buried immediate action inside a
  longer discussion of data collection and long-term planning instead of
  leading with a crisp, sequenced first step.
- **[605493]** (Markov chains intro): searched chain-taxonomy and historical
  context correctly, but the final answer skipped most of that material,
  wrote equations as plain text instead of the requested LaTeX-style
  notation, and organized around one worked example rather than the
  requested taxonomy.

**One case ([605391], plant-based meat GTM report), 7% of topics**, was
diagnosed `under_specified_or_thin`: facet coverage was fine and the
identified competitors were real, but recommendations stayed thematically
generic (mentions "hotels, cafes, QSRs") rather than concrete
(no named partner candidates like specific retail chains or delivery
platforms) — a narrower version of the coverage-gap problem, localized
within one otherwise-covered facet rather than a whole missing facet.

## An unused capability: `release`

`release_committed` — the harness capability built this session
specifically so a facet's evidence could stay minimal by dropping a
document a better one supersedes (`worklogs/2026-08-05-facets-agent-new-system.md`) —
**was never invoked, not once, across all 15 real topics.** This is not
evidence of a bug (no misuse either) but it is evidence the current prompt
doesn't create situations where the model reaches for it. Two readings,
not mutually exclusive:

1. The model's commit-time adjudication (choosing among a batch of
   currently-staged results) already does most of the "keep only the best"
   work before anything is committed, so by the time a genuinely-better
   LATER document shows up, the model doesn't think to look back — the
   prompt describes `release` but doesn't give a strong trigger cue for
   when a later search should prompt reconsidering an earlier commit.
2. Given the coverage-gap finding above, the model may simply not be
   searching enough DISTINCT ground to encounter "I found something better
   for a fact I already committed" scenarios organically — it is too busy
   re-confirming the facets it already has.

Recommend monitoring rather than removing: it is unexercised, not harmful,
and reading 1 is testable cheaply (see recommendations).

## Recommendations for facets_agent, in priority order

1. **[HIGH] Strengthen facet decomposition to enumerate requirements, not
   just identify themes.** The single highest-leverage fix: before or within
   step 1 of the prompt, add an explicit instruction to extract EVERY
   explicit and implicit requirement stated in the request (not just group
   them into "a small set of facets") and confirm every one maps to at
   least one facet. This borrows the discipline of aus_agent's much longer
   prompt's "every requirement the request states" checklist step, in
   compressed form — the goal is coverage rigor, not aus_agent's length.
2. **[HIGH] Add a pre-finalization coverage self-check.** Several
   independent diagnoses converged on this suggestion unprompted: before
   writing the report, verify each requirement identified in
   recommendation 1 has committed evidence backing it; if any doesn't, run
   one targeted search for that specific gap before finalizing. This is a
   cheap, bounded addition (one more check, not an open-ended loop) that
   directly targets the 73%-of-topics failure mode.
3. **[MEDIUM] Reduce redundant re-confirmation within an already-identified
   facet.** The 6054a7 case (39 searches, still missing 3 requested
   sub-points) shows search effort can be reallocated, not just added:
   guidance like "don't re-search a fact you've already retrieved; move to
   the next requirement, or stop this facet" would free up the budget
   recommendation 2 needs without increasing total search volume — directly
   addressing the 2.2x token-cost gap versus aus_agent at the same time.
4. **[MEDIUM] Tie the final answer's structure to what the request
   explicitly asks for.** Where a request names a structure (per-book
   sections, an immediate action plan, a specific notation), the prompt
   should say the final answer must literally deliver that shape, not just
   cover the content. Targets the 20%-of-topics `synthesis_organization`
   failures directly.
5. **[LOW] Nudge toward named specifics when the request implies needing
   them.** The `under_specified_or_thin` case suggests adding one line to
   the query-writing guidance: when a facet calls for concrete
   recommendations (partners, products, tools), write at least one query
   aimed at surfacing named entities, not just the thematic category.
6. **[LOW / INVESTIGATE, don't change yet] `release`'s zero usage.** Cheap
   test: construct one adversarial topic where a clearly-better source only
   surfaces after a fact has already been committed, and check whether the
   model reaches for `release` given the current prompt wording. If it
   doesn't, that isolates whether the issue is prompt-trigger wording (fix)
   or that the scenario itself is rare in practice (leave as-is).

None of these are implemented in this session — this is the diagnosis and
recommendation deliverable the user asked for; happy to implement any of
them next if wanted.

## For balance: aus_agent's side

The user asked for analysis of both systems, not just facets_agent's
weaknesses. aus_agent's structural profile from this same data:

- **Wins on requirement coverage** (see the rubric-scorecard worklogs) most
  plausibly BECAUSE its ~270-line prompt spends real space forcing
  requirement-by-requirement enumeration before searching (§0 of
  `aus_agent/prompts/system/default.md`) — exactly the discipline
  facets_agent's shorter prompt lacks. This is strong indirect evidence for
  recommendation 1 above: it is not that aus_agent's MODEL is smarter, it's
  that its PROMPT enforces the behavior facets_agent leaves implicit.
- **Costs less** (88K vs 195K processed tokens/topic) for a comparably
  thorough answer — its narrower two-engine default and higher per-search
  commit yield (19.7% vs 7.5%) suggest it wastes less retrieval effort, not
  that it retrieves less usefully.
- **Structural weaknesses of its own, by design, not bugs**: no `hybrid`
  engine in its default engine set (misses the dense+sparse fusion
  facets_agent gets "for free"), no `release`-style mechanism at all (an
  architectural gap facets_agent's harness now fixes, even if facets_agent
  itself under-uses it), and a much larger prompt surface that is
  correspondingly more expensive to maintain and iterate on than
  facets_agent's ~65-line one.

## Artifacts

- `worklogs/assets/2026-08-05-trajectory-behavior-analysis.py` (free
  structural analysis script) +
  `worklogs/assets/2026-08-05-trajectory-behavior-analysis.log` (its full
  output).
- `worklogs/assets/2026-08-05-llm-diagnosis.py` (budgeted per-topic
  diagnosis script) + `worklogs/assets/2026-08-05-llm-diagnosis.log` (full
  run log with running cost estimate) +
  `worklogs/assets/2026-08-05-llm-diagnosis-results.json` (all 15 raw
  diagnoses, the source for every example quoted above).
