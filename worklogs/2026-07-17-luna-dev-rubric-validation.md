# 2026-07-17 — luna on 5 dev topics, validated against ResearchRubrics

**System:** `src/systems/aus_agent/`, backend `openai`, model `gpt-5.6-luna`
(Azure endpoint via `.env` `OPENAI_BASE_URL`/`OPENAI_API_KEY`), run-id
`aus-agent-luna-dev`.
**Inputs:** 5 of 30 topics from `research-rubrics-topics-dev.tsv`, chosen for
domain spread; graded by reading each trajectory + answer against that topic's
criteria in `research-rubrics-dev-rubrics.jsonl` (weighted, incl. negative
criteria). Grading is judgment-based, not scripted — percentages are
approximate weighted-attainment estimates.

## Env incident first

All 5 initial runs failed instantly with Azure 401. Cause: the user's shell
profile exports a stale `OPENAI_API_KEY`, and `load_dotenv()` **never
overrides existing env vars**, so runs sent the old key to the Azure endpoint.
Fix: prefix `unset OPENAI_API_KEY;` on launch (better: remove the export from
the shell profile). The failure produced clean `status:"failed"` artifacts.

## Runs

| topic (qid suffix) | domain | search/commit | refs | words | tokens | est. rubric attainment |
|---|---|---|---|---|---|---|
| …958498 investing series | Consumer | 4/1 | 6 | 867 | 76K | ~35% |
| …605367 Taj Mahal + dating | Historical | 8/2 | 10 | 936 | 120K | ~55% |
| …605391 plant-meat SEA | Business | 10/2 | 12 | 972 | 182K | ~62% |
| …6053fb social media | Current Events | 8/2 | 11 | 823 | 113K | ~40% |
| …605493 Markov chains | STEM | 7/2 | 9 | 984 | 103K | ~80–85% |

## Retrieval-process review

- **Queries are consistently question-derived decompositions** (per-country
  for SEA, per-domain for social media, per-sub-question for Taj
  Mahal/dating). Round 2 refines toward entities surfaced in round 1 (Thai
  Union OMG, Burgreens/Green Rebels, BPOM, Egyptian chronology) — the
  loop behaves as designed on these lower-prior topics.
- Commit discipline clean everywhere (1–2 commits, no staged-report lapse,
  23–63 rejected docs per run shows real selection).
- **Investing run under-searched**: 4 queries, 1 commit, then wrote. The
  rubric wanted named specifics (Roth vs traditional, S&P 500/Dow/Nasdaq,
  brokers, tickers) that the corpus could plausibly supply but were never
  queried — the same early-stopping pattern seen on rag2026-72.

## Citation fidelity — excellent

Every spot-checked claim traced to retrieved text: Hancock 226-paper
meta-analysis, Makarin staggered-Facebook-rollout study, OxWell 14,500
survey, 2019 Canada election "no evidence of impact" finding, Thai 38% /
SG 21% flexitarian, US$39.11M Thai market, 30-by-30, mung beans, Makrana
marble, well foundations, chuna plaster, Levant 19-year offset, Markov 1906
/ Eugene Onegin, seven riffle shuffles, and the N-heads formula
(2^{N+1}−2, algebra verified by hand). One benign synonym substitution
("term deposits" for the retrieved "certificates of deposit"). No
fabricated evidence found.

## Rubric-validation findings

1. **Strong on explicit criteria, math, and negative criteria.** Markov hit
   nearly everything (definition, 1906 genesis-as-LLN-dispute, Onegin,
   first-step analysis, correct closed form); no run triggered a
   blanket-claim/out-of-scope/misinformation penalty; social media avoided
   the −5 uncited-mental-health-claims trap because every claim was cited.
2. **A structural rubric family is unattainable in TREC RAG format**:
   tables, section headings, images/diagrams, per-post citation blocks,
   500–2000 words *per post* (TREC caps 1024 total). Roughly 8–15 weighted
   points per topic are format-impossible; dev-rubric scores should be read
   net of these.
3. **The real gap is implicit-criteria specificity.** Rubrics reward named
   entities and framings the question never states: non-Western platforms,
   Section 230/GDPR contrasts, counterfactual baselines, smartphone-era
   linkage (social media); Roth/traditional, index names, brokers, tickers
   (investing); Ebba Koch, siruj mortar, Libby vs Cambridge half-life
   (Taj Mahal); org charts, IP strategy, exit scenarios (plant-meat).
   luna answers the question asked; the rubric imagines the ideal report a
   domain expert would volunteer. This is the discovery-breadth problem in
   a new costume — more searching per topic (or a widening pass before the
   report) is the lever, not answer-writing quality.
4. **Word-limit overshoot wastes a turn.** 3 of 5 runs bounced the first
   report on the 1024-word cap (1366→1136→972; 1177→1128→867; 1138→936).
   Recovery works but each bounce costs a full report-generation turn.
   Possible cheap fix: state the word cap more prominently near the
   report-contract bullet (luna appears to aim at ~1100–1400 first).
5. **Best runs pair breadth of search with per-entity refinement** —
   plant-meat (10 searches: per-country × per-facet) and Taj Mahal (8) beat
   investing (4) on rubric attainment by wide margins. Attainment tracks
   search count more than answer length.
