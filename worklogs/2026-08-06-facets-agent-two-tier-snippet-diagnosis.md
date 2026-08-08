# 2026-08-06 — two-tier retrieval: snippet-truncation fix tested, gap unexplained by it

Follow-up to `worklogs/2026-08-06-facets-agent-phase4cd-ab-and-two-tier.md`'s
Phase 4d prototype. That prototype's first live run (15-topic sample) hit
its intended mechanical target (peak context tokens down 33-35%, `get_documents`
genuinely adopted: 52 calls vs default's 7) but citation full-support rate
collapsed from 22.7% to 4.5%.

## Diagnostic topic selection

Per-topic rubric grades pulled from the already-run scorecards (no new
judge spend for selection itself) for both signals requested:

- **Two-tier's worst 3** (lowest overall grade, ties broken by biggest
  regression vs default): `6847465956a0f6376a6054be` (0/0/0 — a hard
  topic no system handles well, not diagnostic of the fix specifically),
  `6847465956a0f6376a60543d` (default=2 → twotier=1, a real regression),
  `683a58c9a7e7fe4e7695846f` (default already dropped aus's 2→1).
- **aus_agent's best 3**: `6847465956a0f6376a605360` (3),
  `6847465956a0f6376a6054ad` (3), `683a58c9a7e7fe4e7695846f` (2, the
  overlap with the list above).

Only 1 of 6 selections overlapped, so the diagnostic set was the union of
5 distinct topics, not 3.

## Checked piika's actual snippet code

`nourj98/piika`, `src/pi-search/searcher/adapters/pyserini_rest/adapter.ts::truncateSnippet`:
whitespace-collapsed (`text.replace(/\s+/g, " ")`), naive first-500-chars
slice, `...` appended, no word-boundary care (piika's own version CAN cut
mid-word). My original prototype used raw ClimbMix chunk text (original
newlines intact) truncated at 400 chars with no word awareness — worse on
both counts than piika's own default.

## Fix: `_truncate_snippet` (`agent_harness/agent.py`)

Collapses all whitespace first (so budget isn't wasted on newlines), then
backs up to the last space before the character limit rather than cutting
mid-word (hard-cuts only a single very long token with no space at all).
Default preview bumped 400 → 500 to match piika. Tests:
`tests/agent_harness_context/test_two_tier_search.py` (+4 unit cases for
the truncation function itself).

## Re-tested on the 5-topic diagnostic set (same-topic, apples-to-apples)

| | full_support | partial_or_full | rubric grade movement |
|---|---:|---:|---|
| default | 23.6% (38/161) | 60.2% | — |
| twotier, pre-fix | 9.2% (14/152) | 40.1% | — |
| twotier, fixed | 8.3% (12/144) | 38.2% | 1/5 topics recovered fully (`60543d`: 1→2, matching default) |

**Honest result: the truncation fix did NOT close the citation-support
gap.** 8.3% vs 9.2% is flat, within noise — a real but minor contributor.
The rubric-grade recovery on `60543d` is a genuine, if small (n=5), win.
The bulk of the original 22.7%→4.5% collapse is caused by something else.

**Most likely remaining causes, not yet isolated**: the model committing
or citing based on a preview impression even after calling `get_documents`
(a discipline gap in `TWO_TIER_SEARCH_ADDENDUM`, not a text-formatting
gap), or citations drifting from what the fetched full text actually says
by the time the model writes several turns later. Neither investigated
this session — deferred in favor of the user's next direction (LLM-generated,
query-relevant snippets instead of any positional truncation, naive or
word-aware) rather than debugging the truncation-based approach further.

## Next: LLM-generated snippets (this session, follow-on)

Replacing positional truncation (however careful) with a cheap secondary
model (`openai.gpt-oss-120b-1:0`, same convention as `judge_relevance`)
extracting the query-relevant span per document, capped at 500 chars. See
the next commit/worklog entry for the implementation — recorded separately
since it's new code, not a fix to the existing truncation path.
