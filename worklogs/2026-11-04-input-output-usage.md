# Separate generation input and output usage

Follow-up to the Sol cost recovery and Astra report update: after requesting a
commit and push, the user requested input/output token usage separately.
Recovered the remaining five runs through DevSpace Sunfyre;
the two Sol runs reuse the validated recovery evidence. No new generation or
paid API calls were made.

## Exact sources and method

Project: `/home/el7/E103037/repos/trec-rag-26`. Read rich output traces under
`data/outputs/{brief_revise_agent,facets_agent,facet_rag,open_weight_agent}`.
Selected exact internal run IDs, then required each successful output's narrative
ID, answer, and references to match its organizer export under
`data/outputs/submissions/<tag>/rag_output_trec_rag_2026.jsonl`.
All five selections have exactly 119 unique matching topics.

| Organizer tag | Internal run ID |
| --- | --- |
| brief-base-t119 | brief-revise-base-test119-20260808 |
| brief-hybrid-t119 | brief-revise-hybrid-test119-20260808 |
| facets-t119 | facets-agent-test119-20260808 |
| facetrag-t119 | facet-rag-test119-20260808 |
| owa-glm5-t119 | open-weight-agent-glm5-test119-20260809 |

Exact read-only probe: [assets/2026-11-04-input-output-usage.py](assets/2026-11-04-input-output-usage.py).
Ran as `uv run --offline --no-project python -c '<probe contents>'` on Sunfyre.
The initial full scan exceeded 30 seconds; a prefix check avoided parsing
unrelated runs and the retry completed. Its stdout exceeded the tool display
limit, so the result was compacted from the tool's saved stdout without rescanning
or changing sources. [Saved results](assets/2026-11-04-input-output-usage.json)
contain all 595 successful topic rows, exact totals, and submission hashes.
The other 238 rows and two failed default attempts remain in
[Sol recovery evidence](assets/2026-11-04-sol-cost-recovery.json).

## Exact totals and rounded means

Input is split into uncached input and cached reads. All seven runs have zero
recorded cache-write tokens. Processed tokens = uncached input + output here;
cached reads are additional input, excluded by the historical processed-token
cost estimate. Rounded means divide each exact total by 119 independently.

| Run | Uncached input total | Cached input total | Output total | Mean uncached input | Mean cached input | Mean output |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| brief-base | 38,027,796 | 46,237,170 | 954,864 | 319,561 | 388,548 | 8,024 |
| brief-hybrid | 34,876,105 | 38,365,184 | 897,749 | 293,077 | 322,397 | 7,544 |
| sol-default, including recorded failed attempts | 21,858,040 | 24,184,074 | 729,400 | 183,681 | 203,228 | 6,129 |
| sol-research-first | 39,333,645 | 43,950,115 | 1,246,976 | 330,535 | 369,329 | 10,479 |
| facets | 16,533,352 | 8,499,068 | 703,496 | 138,936 | 71,421 | 5,912 |
| OWA | 49,394,555 | 0 | 701,979 | 415,080 | 0 | 5,899 |
| facetrag | 48,986,766 | 0 | 5,917,531 | 411,653 | 0 | 49,727 |

## Scope and validation

The five existing processed-token means are reproduced by these totals. Their
costs were originally calculated on successful submitted attempts; unsuccessful
attempts are excluded. The probe found 99 noncompleted brief-base outputs, 75
hybrid, none for facets, one facetrag, and two OWA. Those are not added to the
existing cost figures. Sol-default's retry-inclusive basis is retained and
explicitly labeled; its two failed attempts add 175,037 uncached input, 103,395
cached input, and 4,349 output tokens. This scope difference limits full-run
cost comparisons. Unknown usage from requests returning no usage is excluded.

OpenAI amounts remain the report's hypothetical $5/M processed-token estimates,
not billing totals; Bedrock amounts retain the report's metered costs. This
change separates recorded token categories without repricing any run.

## Validation and report integration

- All 595 new successful-topic rows reconcile to their recorded totals and
  satisfy `processed = uncached input + cache writes + output`.
- All 21 repo input/cache/output means and all 14 report input/output means
  match the exact totals, checked with Decimal arithmetic. Independently
  rounded figures can differ by one token when summed.
- Full offline suite: `UV_CACHE_DIR=/tmp/trec-rag-uv-cache bash scripts/test.sh`
  passed 1,970 tests, with 12 live tests deselected and one existing Starlette
  deprecation warning. `git diff --check` passes.
- Updated the sibling report's submitted-runs table and usage explanation with
  Astra; preserved its separately fetched Overleaf author/project-setting changes
  via a clean rebase. The first push had been rejected because the remote was
  ahead; no remote history was overwritten.
- Report clean two-pass build remains five pages, without undefined references
  or overfull boxes. Both author and parent inspected all five rendered pages.
  The ignored report `main.pdf` contains the updated version.
