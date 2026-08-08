# 2026-08-06 — two-tier retrieval v2: full-question snippets + citation re-verify

Follow-up to `worklogs/2026-08-06-facets-agent-two-tier-snippet-diagnosis.md`.
Deep tool-use analysis of the 5-topic diagnostic set (free, no judge spend —
trace/token/tool-count comparison) found the actual mechanism behind the
citation-support collapse, then two targeted fixes closed part of the gap.

## Deep analysis: what actually changed under two-tier

Tool-use and token stats, default vs two-tier (both variants), same 5
topics:

| metric | default | trunc-fix | llm (v1) |
|---|---:|---:|---:|
| `get_documents` calls/topic | 1.4 | 3.4 | 3.0 |
| rejected docs/topic | 174.0 | 5.0 | 3.0 |
| peak context tokens | 79,865 | 57,396 (-28%) | 58,576 (-27%) |
| **processed tokens (cumulative)** | **242,490** | **80,145 (-67%)** | **99,078 (-59%)** |
| `cited_pct` (formal citation rate) | 86.9% | **65.9%** | 86.5% |

Two findings: (1) the real efficiency win is *processed* tokens, not peak
context — down 59-67%, from eliminating default's massive rejected-doc
churn (174/topic, each turn re-processing a growing conversation). (2) LLM
snippets recovered something plain truncation broke: `cited_pct` crashed to
65.9% under word-aware truncation (e.g. 41.5% and 15.9% on two individual
topics) but climbed back to 86.5% under LLM snippets, nearly matching
default.

**The key disconnect**: `cited_pct` (formal rate) came back to near-default
under LLM snippets, but citation *support* (from the prior session turn)
stayed flat at ~8% vs default's 23.6%. The model was citing just as often —
just citing things that didn't hold up as precisely.

**Mechanism, grounded in the numbers**: default full-text-reads *every*
staged batch (170 docs/topic) before choosing what to commit. Two-tier only
ever `get_documents`'s ~14-16 of a similarly-sized ~150-160 previewed pool
— so the *decision* of which handful deserve a full read, and often the
specific claim wording, was still anchored to the preview impression more
often than in default's fully-informed comparison.

## Two fixes, per user direction

1. **`generate_snippets(query, requirement, documents)`** — now takes the
   FULL original research request alongside the current search's narrower
   `requirement`, not just the facet. facets_agent's `run.py` binds the
   per-topic `query` via `functools.partial` each loop iteration (the
   harness's `search_preview_generator` hook contract is unchanged —
   `(requirement, documents)` — so this is transparent to
   `agent_harness/agent.py`).
2. **Citation re-verification** — `TWO_TIER_SEARCH_ADDENDUM` gained an
   explicit step: before writing each cited sentence, re-read the committed
   `get_documents` text behind that id and confirm it states the SPECIFIC
   claim, not just the right topic; narrow the sentence or drop the
   citation if it doesn't.

Also answered a clarifying question: document ranking (still the
underlying engine's own score, unaffected) and accept/reject (still
`commit_context`, same mechanism, now gated only by `get_documents`
staging) are both unchanged by two-tier mode. No additional relevance
filtering is active — Phase 4c's `search_result_filter`
(`minimize_filter`/`rank_filter`) has never been combined with two-tier in
any run so far; a real next lever, not built.

## Result: re-run on the same 5-topic diagnostic set

| variant | full_support | partial_or_full | arena vs aus_agent |
|---|---:|---:|---|
| default | 23.6% | 60.2% | — |
| twotier, pre-fix | 9.2% | 40.1% | — |
| twotier, truncation-fixed | 8.3% | 38.2% | — |
| twotier, llm-snippet v1 (facet-only) | 7.9% | 43.4% | 60% aus-pref |
| **twotier, llm-snippet v2 (full-question + re-verify)** | **12.5%** | **45.8%** | **50% — a tie** |

`full_support` up 7.9%→12.5% (+58% relative). Per-topic rubric grades: v2
has **zero regressions vs default** across the 5 topics, and now matches or
exceeds default on 3/5 (two of those exactly matching aus_agent's own
grade) — v2 both kept v1's gains AND fixed v1's one regression
(`60543d`: v1 dropped it 2→1, v2 recovered to 2).

## Where this leaves things

Real, measurable progress from both fixes combined, but citation support
(12.5%) is still roughly half of default's (23.6%) — the underlying
mechanism (fewer full-text reads before committing) is only partially
compensated for, not eliminated. Candidates for a next increment, not
built this session: layering `rank_filter` (Phase 4c, never dropped
anything) on top of two-tier previews to also reorder them by relevance;
raising the `get_documents` batch size/frequency the prompt encourages; or
accepting that two-tier trades some support quality for the large
efficiency win (59-67% fewer processed tokens) and deciding whether that
trade is worth it before shipping it as facets_agent's default (still not
the default — every run this session used explicit opt-in flags).
