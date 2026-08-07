# 2026-08-07 — brief_revise_agent: gpt-5.6-sol deep-dive on the 14 clean losses + improvement plan

Follow-up to `worklogs/2026-08-07-brief-revise-agent-phase5-dev30-and-decision.md`
(Phase 5 decision: `aus_agent` stays the submission, `brief_revise_agent`
missed the preregistered arena bar 9-14 clean wins). This session: handed
gpt-5.6-sol the full raw per-topic data (not a pre-digested summary) and
asked for a deep root-cause analysis of every clean loss plus a concrete
improvement plan. Budget: $30 (user-set, actual spend $0.81).

## Inputs

**Instructions**: `worklogs/assets/2026-08-07-sol-improve-prompt-instructions.md`
(verbatim) — the full task framing: the track spec, both systems' designs
and why they were built that way (the `facet_rag` content-starvation
failure and the `facets_agent` not_decomposed/covered_but_shallow failure
`brief_revise_agent`'s two additions were built against), the measured
Phase 5 results, and two explicit asks (a per-loss-topic root-cause
analysis grounded in the raw data, then a buildable improvement plan). One
constraint stated explicitly and repeated: ClimbMix-only retrieval, no web
search, ever — full freedom otherwise to change tools, prompts, schemas, or
control flow.

**Raw data**: `worklogs/assets/2026-08-07-extract-sol-improve-data.py`
(the exact extraction script, re-runnable) pulled, for all 30 dev topics —
ordered clean-losses-first (14), then ambiguous (7), then clean-wins (9) —
from `data/outputs/{aus_agent,brief_revise_agent}/*.output.json`
(`run_id`s `aus-agent-dev30-luna-e2708ab` /
`brief-revise-dev30-6252022`) and
`evaluation-results/arena/aus_agent-vs-brief_revise_agent-dev30-rubric/judgments.jsonl`:

- the narrative, both systems' full numbered answers with citation indices
  and per-topic word/sentence/uncited counts;
- the arena judge's verdict AND raw output text for both battle orders;
- `brief_revise_agent`'s rendered requirements brief (extracted from
  `trace.input.system_prompt`'s appendix);
- its full search log (engine + query per call) and commit/reject counts
  (fixed two bugs while building this: `commit_context`'s step output is a
  JSON string with a trailing `[context budget: ...]` note appended after
  the object, not a clean dict — needed `json.JSONDecoder().raw_decode`, not
  `json.loads`; and the search-log header was mislabeling the sentence count
  as the search-call count);
- whether the review pass fired, read out of the dev30 run's own stdout log
  (`/tmp/.../bld4o4max.output`) via the `review.hook: usage=...` line this
  session's earlier code-review fix added — including catching the ONE real
  reviewer-JSON-parse-failure case in the wild (topic `605493`, "Markov
  chains") directly in the extracted data.

Total package: ~130K tokens (~520KB raw markdown, not committed — the
extraction script reproduces it exactly from already-existing artifacts).

**Model/cost**: one `gpt-5.6-sol` call, no system prompt (single long user
message), 110,882 input / 12,790 output tokens, **$0.81 of the $30 budget**.
Full raw response: `worklogs/assets/2026-08-07-sol-brief-revise-agent-improvement-analysis.md`.

## What sol found (Part 1: root-cause analysis)

**Scope honesty, stated up front by sol itself**: the arena judge's raw
output was strict-verdict-only (`[[A]]`/`[[B]]`, no reasoning text) on every
battle, so the per-topic diagnoses below are sol's own comparative reading
of the two answers, not the judge's stated reasoning — flagged as an
evidentiary limit rather than glossed over.

Five cross-topic patterns, each named with the specific loss-topic ids that
exhibit it (not asserted in the abstract):

1. **Broad answers were repeatedly compressed below the useful coverage
   level** — 11 of 14 clean losses, `brief_revise_agent` ran 150-325 words
   shorter than `aus_agent` on the same topic while still omitting
   requested content (not padding — sol names the specific omitted
   material per topic: strategic geometry methods, validation metrics,
   legal context, public health, game history, abuse controls, wartime
   decisions, prospective clinical testing).
2. **Retrieved evidence and brief requirements were not reliably translated
   into the answer** — the search logs on Baudelaire, *Mahabharata*, CS:GO,
   social media, EHR, and Markov chains all specifically targeted the exact
   content later found missing from the final answer. This falsifies a
   simple "the brief failed to decompose" story for these losses — the
   brief and searches were often right; the failure was at evidence
   selection / answer planning / revision.
3. **The review pass has no correctness or artifact-validity check** — and
   this is the most concrete, checkable finding: `brief_revise_agent`'s
   geometry answer contains an actually-wrong cyclic-quadrilateral angle
   derivation (sol worked the geometry itself and confirmed the error), and
   its U-Net answer contains non-compiling Python (`def init` instead of
   `__init__`, malformed expressions, truncated sentences) alongside a
   prose/code architecture mismatch (claims "two self-attention blocks" the
   code doesn't contain). The reviewer's four issue types
   (`MISSING_REQUIREMENT`/`SHALLOW`/`UNCITED_CLAIM`/`WEAK_SENTENCE`) have no
   category for "this is factually/mathematically/syntactically wrong,"
   so nothing in the current design could ever catch this class of error.
4. **Checklist specificity sometimes displaced higher-value analysis** — the
   brief's `specific_form` field ("a named mechanism or number, not a
   category label") sometimes rewarded manufactured precision over
   substance: the clinical-VLM topic invented exact unjustified thresholds
   (2% non-inferiority margin, ECE ≤0.05) with no cited rationale; the
   social-media topic spent scarce words on a narrow Australian employment
   case instead of the searched-and-missing public-health domain.
5. **Format/audience fit checked less reliably than raw content presence**
   — CS:GO wanted a feature essay, got a compressed report; the EHR topic's
   novice-audience framing lost to `aus_agent`'s more pedagogically direct
   answer.

**The review pass's actual, narrower truth** (sol's sharpest correction to
this session's own earlier framing): the data supports that review
mechanically fixed citation-presence (26.0%→5.3% uncited, confirmed real)
but does NOT support any causal claim about whether it helped or hurt
individual answers — every clean loss AND every clean win shows the review
firing, there's no saved pre-review draft or issue list to compare against,
and the Markov-chains topic is direct proof the fail-open path is live: a
malformed reviewer response was silently treated as "zero issues" rather
than retried or flagged, exactly the path this session's earlier code
review flagged as intentional/acceptable — sol's read is that it's a real,
consequential gap, not a defensible design choice, because it makes the
whole revision mechanism **unauditable**.

**Correction to this session's own earlier judgment**: the Phase 5 worklog
called the two uncited-rate-regression topics "structurally benign"
(synthesis/derivation sentences, not real citation failures) based on a
quick eyeball read. Sol's closer read disagrees on one of them: on
`6847465956a0f6376a605391` (Southeast Asia market-entry strategy), the 10
uncited sentences in `brief_revise_agent`'s answer are the invented launch
sequencing, risk ratings, and go/no-go gates — central recommendations
under a rubric that explicitly asked for data-driven execution, not
connective wrapper text. The formal-proof topic's uncited sentences (proof
derivation steps) are a more defensible case, but sol notes they're still
central to the request, not disposable, and still score zero under the
track's literal citation-recall rule regardless of whether they're
legitimate original derivation.

## The improvement plan (Part 2), ranked by sol

Full detail in the raw asset; summary of the ranked list and sol's own
recommended build order under time pressure:

1. **(highest priority, build first if only one fits) Replace the free-form
   rewrite with a coverage-gated, non-destructive patch review** — a
   structured per-requirement status matrix (`FULL`/`PARTIAL`/`MISSING`/
   `INCORRECT`) instead of a free issue list, a `KEEP`/`PATCH`/`REWRITE`
   revision mode that preserves sentences marked `KEEP`, saving both
   pre- and post-review drafts, a **fail-closed** parse-failure path (retry
   once with a repair prompt, then accept the original draft and record
   `review_failed=true` — never silently treat unparseable output as "no
   issues"), and a deterministic guard that reverts to the original draft
   if a requirement regresses from `FULL` to `PARTIAL`/`MISSING` after
   revision.
2. **Add a pre-writing evidence-and-coverage checkpoint inside the main
   loop** — a required `coverage_checkpoint` tool call before the model may
   emit the final answer, forcing every explicit requirement to a
   `READY`/`NEEDS_SEARCH`/`NO_EVIDENCE` state (tied to real ClimbMix docids,
   not answer-local citation indices) before generation, since a terminal
   reviewer is too late to cheaply repair broad content that was searched
   but never made it into the draft.
3. **Deterministic artifact validators + new reviewer issue types** — cheap,
   catches the concrete correctness failures found in pattern 3:
   `ast.parse`/`compile` checks on any Python in the answer, new issue types
   (`FACTUAL_ERROR`, `INTERNAL_CONTRADICTION`, `INVALID_CODE`,
   `INCOMPLETE_SENTENCE`, `UNSUPPORTED_PRECISION`, `TIMELINE_OR_ORDER_ERROR`,
   `FORMAT_OR_AUDIENCE_MISMATCH`, `CITATION_MISMATCH`), and an instruction
   for the reviewer to recompute displayed numerical/mathematical results
   (would have caught the geometry error).
4. **Change the stopping rule from "answer seems complete" to "coverage is
   complete"** — cheapest change on the list (prompt-only): a requirement
   only counts as done with a concrete answer + mechanism + evidence +
   requested comparison/example, not just one mention; target 850-1000
   words on broad multi-part narratives unless every requirement is
   demonstrably covered earlier.
5. Prioritized (not just enumerated) requirements brief (`MUST`/`SHOULD`/
   `OPTIONAL`, a `do_not_invent` field to stop the manufactured-precision
   failure mode).
6. Sentence-level citation *entailment* review (does the cited doc actually
   support the claim, not just "a citation exists") — real ClimbMix docids
   and snippets shown to the reviewer, `SUPPORTED`/`PARTIALLY_SUPPORTED`/
   `UNSUPPORTED` verdicts.
7. Logging fix so a future diagnosis doesn't have to reconstruct
   draft-vs-revision causality from stdout logs the way this session did:
   persist the pre-review draft, raw reviewer output, parse/validation
   errors, normalized issues, post-review draft, sentence-level diff, and
   the accept/revert decision, every run.

Sol's own explicit build-order recommendation under the deadline: **1 alone
if only one change fits; add 3 if two fit (cheap, prevents the
catastrophic U-Net/geometry-class failures); add 2 as a third if it
fits.** Explicitly deprioritized: full citation-entailment review (6),
automatic mathematical verification beyond a recompute instruction, and any
second unconstrained free-form rewrite round (the evidence doesn't support
that more free-form rewriting helps — it's what's already failing).

Success criterion sol proposes for the next iteration: re-run the same
preregistered arena rule (≥12 clean challenger wins, ≤8 clean aus_agent
wins) plus two new deterministic gates this analysis motivates directly —
zero accepted reviewer parse failures, zero non-compiling Python in any
answer.

## Not done this session

- No code changes — this was the analysis + plan step only, matching what
  was asked. Implementation is a follow-up.
- Sol's plan was not independently re-verified by a second model/reviewer
  pass this time (unlike the original architecture proposal, which got an
  Opus review before being acted on) — flagged so whoever picks this up
  next knows that gap exists.
