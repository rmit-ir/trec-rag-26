# 2026-08-07 — brief_revise_agent rounds B/C/D: conclusion

Follow-up to `worklogs/2026-08-07-brief-revise-agent-sol-iteration2-vs-aus-agent-v2.md`
(sol's round-4 verdict: revert to iteration 1, then investigate aus_agent_v2's
actual code for fresh ideas). This worklog closes out the resulting B/C/D
thread before the session's focus moved to the factorial LLM-comparison
analysis.

## Full result table, all vs `aus_agent_v2` (`aus-agent-v2-exp15-luna`), full
15-topic set, both battle orders, `gpt-5.6-terra` judge

| Round | Mechanism | Clean wins | Clean losses | Ambiguous | Pooled aus_agent_v2 pref |
|---|---|---:|---:|---:|---:|
| Iteration 1 (baseline) | brief + review, sol Priority 1 | 3 | 10 | 2 | 73.3% |
| Iteration 2 | atomic expert-completion brief | 1 | 11 | 3 | 83.3% (regressed) |
| Iteration 3 | mandatory search-`requirement` + retrieval screener | 2 | 13 | 0 | 86.7% (regressed) |
| **Round B** | **adjacent-page auto-retrieval (zero LLM calls)** | **3** | **9** | **3** | **70.0% (best)** |
| Round C | section-level word budget in the brief | 0 | 13 | 2 | 93.3% (worst) |

## Round D decision

Asked sol (quick check-in, $0.003) whether round D (combining B+C) was
still worth testing given round C's severe regression. Verbatim answer:

> "No-go on round D. Round C's severe regression makes a B+C combination
> unjustified absent a specific reason to expect a strong positive
> interaction; testing it would add risk with little supporting evidence.
> Round B should remain the final recommended configuration."

**Round B (adjacent-page auto-retrieval) is the final recommended
`brief_revise_agent` configuration** from this thread. It is the current
default (`search_result_augment=adjacent_pages.augment`, on by default;
`--disable-adjacent-pages` to turn off). Round C's word-budget code remains
in `brief.py`/`prompts.py` (fails open to no-budget guidance when the
model's numbers don't validate) but is measured harmful when the model
actually complies with it -- worth a follow-up look at WHY before ever
reviving it, not assumed safe just because it fails open.

## Why word budgets likely hurt (not measured directly this session, a
hypothesis for anyone picking this up)

Unlike round B (pure retrieval, no model-facing instruction change), round
C changes what the model is TOLD to do -- allocate words per requirement
before writing. Plausible failure modes worth checking against the actual
answers before trying again: the model may treat the budget as a hard cap
rather than a target (per-requirement under-writing to "stay in budget"
even when more depth was available and warranted), or the upfront
allocation may be wrong for a requirement whose true depth need only
becomes clear once evidence is in hand (research findings changing what
matters, after the budget was already committed to).

## What's next

Session focus moved to a separate, larger analysis: a factor taxonomy
(luna+terra) and a sol-designed $50 factorial experiment isolating whether
the main generator LLM matters more than these structural choices --
tracked separately (`worklogs/2026-08-07-brief-revise-agent-llm-factorial-*`,
in progress at the time of this worklog).
