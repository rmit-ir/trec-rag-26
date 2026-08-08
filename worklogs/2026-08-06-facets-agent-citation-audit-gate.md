# 2026-08-06 — citation_audit_gate: self-identify + re-retrieve, not just narrow/drop

Follow-up to `worklogs/2026-08-06-facets-agent-two-tier-v2-improvements.md`. That
round's citation re-verify prompt clause moved full-support 7.9%→12.5% but left
104/192 citations "no support" — still roughly half of default's 23.6%, and
even the best-performing of the 5 diagnostic topics kept a 35% no-support rate.
User asked to go further: explicitly ask the agent to self-identify the two
failure patterns found in the sample and run ANOTHER RETRIEVAL CYCLE to find
better evidence, not just narrow or drop the citation as a first resort.

## Two concrete failure patterns sampled from the v2 run's "no support" citations

1. **Topic match without claim support** — document is on the right general
   subject but doesn't state the specific fact. E.g. a combinatorics text
   cited for a specific weight-assignment formula it never states; a Google
   LSTM speech-recognition doc cited for a claim about Apple QuickType.
2. **Model judgment presented as sourced fact** — the model's own
   recommendation/synthesis ("verify X before using it", "N participants is
   too small for Y") gets a citation to a document that never made that
   judgment (an IEEE standards doc cited for the model's own advice; a study
   abstract cited for the model's own sample-size adequacy opinion).

Full findings + exact examples: `worklogs/assets/2026-08-06-review-citation-audit-prompt.py`.

## Mechanism: no new harness plumbing needed

`pre_final_hook` already fires once, injects one user-message, and the
model's next turn can make arbitrary new tool calls (search/get_documents/
commit_context) before re-attempting the report — "another retrieval cycle"
was already mechanically possible. Only the instruction text needed writing.

## Review process

Drafted an instruction from the findings above, sent full context (mechanism,
quantitative comparison table, all 4 concrete examples, harness constraints —
fires once, injected as a user message mid tool-calling conversation, not a
system prompt) to `gpt-5.6-sol` for critique. Sol answered directly (no
clarifying questions) and flagged real gaps in the draft:

- Pattern-2 fallback offered "drop the id" too easily — retrieval should be
  the default response for BOTH patterns, not just pattern 1.
- "For every citation" was ambiguous at the sentence level; needs to be
  explicit that each co-cited id on a multi-citation sentence is verified
  separately.
- "search previews are not evidence" needed to be stated explicitly — must
  fetch with `get_documents` and `commit_context` before citing a
  replacement.
- The `{ids_list}` placeholder needed framing as "an audit inventory", not
  the whole task.
- "further search genuinely finds nothing better" was too vague for a
  smaller model — needs concrete sequencing: flag → targeted retrieval pass
  for every flagged claim → fallback editing only after that.

Full request/response: `worklogs/assets/2026-08-06-review-citation-audit-prompt.py`
/ `-sol-citation-audit-review.txt`. Sol's revised instruction was implemented
verbatim as `_CITATION_AUDIT_TEMPLATE` in `src/systems/facets_agent/review.py`.

## Implementation

`src/systems/facets_agent/review.py`:
- `citation_audit_gate(context)` — fires whenever the draft has at least one
  citation (an uncited draft has no citation-support risk to check).
- `two_tier_final_gate(context)` — composes `coverage_gate(context) or
  citation_audit_gate(context)`: coverage gaps first (a missing requirement
  is a bigger defect than an imperfect citation), citation audit only once
  coverage is already clean. Necessary because `pre_final_hook` only fires
  once per run — both checks have to share that single shot.

`src/systems/facets_agent/run.py`: `--two-tier-search` now wires
`pre_final_hook=two_tier_final_gate` instead of leaving the harness default;
non-two-tier runs keep `pre_final_hook=coverage_gate` explicitly (previously
implicit via `facets_agent.agent.run_agent`'s own default) — kept explicit so
both branches of the CLI's behavior are visible at the call site rather than
one being an implicit fallback.

Added unit tests in `tests/systems/test_facets_agent.py`: no-op cases (no
citations, no candidate_sentences), correct dedup of the `{ids_list}`
placeholder, and `two_tier_final_gate`'s priority ordering (coverage over
citation audit, citation audit runs only when coverage is clean, no-op when
both pass). Full suite: 1657 passed, 0 skips.

## Wiring bug: the gate never fired on the first measurement attempt

The first diagnostic run (`facets-agent-diag5-twotier-llm-v3`, since
discarded — not worth keeping as an artifact, its trajectories are
byte-equivalent to what plain `--two-tier-search` without the audit gate
would produce) computed the right `pre_final_hook` local in `run.py`
(`two_tier_final_gate` under `--two-tier-search`, `coverage_gate`
otherwise) but never actually passed `pre_final_hook=pre_final_hook` into
the `run_agent(...)` call — so every run silently fell back to
`facets_agent.agent.run_agent`'s own default (`coverage_gate` alone).
Caught by grepping the v3 trajectories' `raw_messages` for the audit
template's own text (`"audit every sentence"` / `"requirement ledger"`) and
finding zero matches despite committed citations being present in every
run. Fixed in a follow-up commit; re-verified by grepping the corrected
run's (`v4`) trajectories and confirming `citation_audit_gate`'s text
appears in 4/5 topics (the 5th's `coverage_gate` fired instead — correct
priority, since `pre_final_hook` only gets one shot per run and a missing
requirement is checked first).

## Measurement: `facets-agent-diag5-twotier-llm-v4`, same 5-topic set

Same 5 diagnostic topics as every prior round in this series
(`worklogs/2026-08-06-facets-agent-two-tier-snippet-diagnosis.md`,
`-v2-improvements.md`). Full pipeline: `scripts/resolve-rag-output-
references.py` → `ragdoll support judge` (bedrock, `openai.gpt-oss-120b-1:0`,
155 citations judged, 0 judge errors) → `arena_aus_agent_vs_facets_agent_
rubric.py` (`--aus-agent-run-id aus-agent-dev30-20260806` — the default
`aus-agent-15topic` run-id has ZERO overlap with these 5 qids; the actual
aus_agent baseline for this whole diagnostic series has always been
`aus-agent-dev30-20260806`, confirmed by cross-checking the 5 topic ids in
`facets-agent-diag5-twotier-llm-v2`'s own arena judgments) →
`rubric_scorecard_aus_agent_vs_facets_agent.py`, same `--out-dir`. Judge
model `gpt-5.6-terra` throughout, matching every prior round.

### Citation support (RAGDoll, full/partial/no-support)

| variant | full_support | partial_or_full | no_support |
|---|---:|---:|---:|
| default (no two-tier) | 23.6% | 60.2% | 39.8% |
| twotier llm v1 (facet-only snippets) | 7.9% | 43.4% | 56.6% |
| twotier llm v2 (full-question + re-verify prompt clause) | 12.5% | 45.8% | 54.2% |
| **twotier llm v4 (+ citation_audit_gate)** | **11.6%** | **56.1%** | **43.9%** |
| aus_agent (baseline) | 38.7% | — | — |

`full_support` is flat vs v2 (11.6% vs 12.5%, within noise on n=155 vs
n=192 citations) — the audit gate did NOT move the headline metric it was
built for. `no_support` did drop meaningfully (54.2%→43.9%, closing over
half the remaining gap to default's 39.8%), but almost entirely by
converting "no support" into "partial support" (partial_support alone:
v2 undocumented per-label, v4 69/155 = 44.5%) rather than into full
support. Per-topic full-support rates were highly uneven: 25.0% and 23.1%
on the two easiest topics, down to 3.6% on the hardest
(`6847465956a0f6376a6054ad`, the mental-wellness-agent topic).

### Rubric arena vs aus_agent — this is the part that got WORSE

| variant | aus_agent win rate | order_consistency |
|---|---:|---:|
| twotier llm v1 | 60% | — |
| **twotier llm v2** | **50% (a tie)** | **1.0** |
| **twotier llm v4 (+ citation_audit_gate)** | **70%** | **0.8** |

v4 is a clear regression from v2's tie back toward v1's loss. Per-topic
arena preference (both battle orders):

| topic | v2 facets grade | v4 facets grade | v2 arena | v4 arena |
|---|---:|---:|---|---|
| `60543d` | 2 | 2 | facets wins | facets wins (both orders) |
| `5846f` | 2 | **1** | tie (1-1 grade) | aus wins (both orders) |
| `605360` | 3 | 3 | tie (3-3 grade) | split (1 order each) |
| `6054ad` | 3 | **2** | tie (3-3 grade) | aus wins (both orders) |
| `6054be` | 0 | 0 | aus wins | aus wins (both orders) |

Two topics (`5846f`, `6054ad`) regressed on the 0-3 rubric grade between v2
and v4 — v2's own headline claim ("zero regressions vs default across the
5 topics") does not extend to v4. `criterion_scorecard`'s per-axis
breakdown for the 3 topics aus_agent won under v4 shows facets_agent's
**Explicit Criteria** axis scoring particularly low (0.188 average, vs
aus_agent's 0.714 on the same topics) — consistent with a hypothesis that
the audit gate's re-verification/re-retrieval cycle consumes turns and
report-length budget that would otherwise go toward covering more of the
request's explicit requirements, trading breadth for citation caution.
Not confirmed further (no per-sentence diff was done between v2's and v4's
actual report text) — a candidate follow-up, not run this session.

### Verdict

**Net negative vs v2, on this 5-topic sample.** The audit gate achieves
what it was asked to do narrowly (fewer flatly-unsupported citations,
`no_support` down 10 points) but the mechanism — sending the model back for
a full self-audit-and-re-retrieve pass, one-shot, budgeted from the same
turn/token allowance as the rest of the run — appears to cost more in
answer breadth/quality than it recovers in citation precision, net-net
scoring worse on both the rubric grade and the arena judge that are the
metrics actually tied to the user's stated goal ("improve facets_agent to
beat aus_agent"). This is a real, not a noise-level, result: the arena
swing (50%→70% aus-preference) and two independent rubric-grade drops both
point the same direction.

`two_tier_final_gate`/`citation_audit_gate` remain implemented and tested
(`tests/systems/test_facets_agent.py`) but are opt-in only
(`--two-tier-search`, itself not facets_agent's default) — this result
does not touch facets_agent's actual default behavior. Not recommended for
promotion to default given this measurement. Candidates for a next
iteration, not built this session: cap the audit gate to only the
sentences/citations most likely to be pattern-1/pattern-2 failures rather
than auditing every citation in the draft (the full pass may be consuming
disproportionate budget); or give it a dedicated turn/token allowance
separate from the rest of the run's budget so the audit doesn't compete
with initial coverage for the same resource.
