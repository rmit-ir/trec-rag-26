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

## Not yet measured

This entry covers the review + implementation only. Next: a new diagnostic
run on the same 5-topic set (`/tmp/topics_diag5.tsv`) with
`--two-tier-search --two-tier-preview-mode llm`, resolve, RAGDoll support
judge, rubric arena vs aus_agent and vs the prior `facets-agent-diag5-twotier-
llm-v2` run, to see whether the audit gate moves full-support past v2's
12.5% toward default's 23.6% / aus_agent's 38.7%.
