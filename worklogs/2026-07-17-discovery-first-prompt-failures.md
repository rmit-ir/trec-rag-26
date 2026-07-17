# 2026-07-17 — Discovery-first prompting: four failures, concluded model-level

**System:** `src/systems/aus_agent/` (Bedrock `au.anthropic.claude-sonnet-5`)
**Probe topic:** `rag2026-72` — "Write a series of technical blog posts on some
of the advancements in LLM training and fine-tuning in 2023-2025…"
**Conclusion:** on subjects inside the model's expertise, no system-prompt
wording we tried makes Sonnet 5 *discover* the answer space from the corpus
before diving into candidates it already knows. The behaviour is model-level
(prior confidence overrides instruction), not a prompt-wording problem.

---

## The target behaviour

The topic names a **field and a period** ("advancements … in 2023-2025") but
not the specific techniques. The desired first move is a field-level survey
search ("LLM training fine-tuning advances 2023 2025"-shaped) so the *corpus*
nominates the candidate list, followed by per-candidate dives. Instead the
model always jumps straight to techniques recalled from memory.

Not a corpus limitation: probed directly, survey-style queries against
ClimbMix return usable field-level documents (e.g. `shard_02466_36730`
"Timeline of large language models", plus an "Era of Large Language Models: A
Comprehensive Survey" doc). Discovery-first would have been rewarded.

## Four prompt strategies, four identical outcomes

Every run's turn 1 issued essentially the same four recall searches — LoRA,
QLoRA, DPO, GRPO(/Mixtral) — never a field-level query. Runs are in
`data/outputs/aus_agent/` under the run-ids below.

| # | Strategy | Where it lived | Run | Turn-1 searches |
|---|----------|----------------|-----|-----------------|
| 1 | "discover the things before investigating them" rule | Research workflow item | `aus-agent-math-check` | recall (4) |
| 2 | Same rule, moved into the plan the model must produce: classify each coverage area as request-named vs memory-supplied ("discovery area") | Internal success plan item 4 | `aus-agent-discovery-check` (first attempt died on expired AWS token after turn 1 — turn 1 already recall) | recall (2, run truncated) |
| 3 | Same, full run after token refresh | Internal success plan item 4 | `aus-agent-discovery-check` | recall (4) |
| 4 | Reframed away from memory-distrust to corpus-unknowability: "You do not know what this corpus holds on any subject until it answers, no matter how well you know the subject itself" — first searches in the request's own terms | Research workflow item 1 | `aus-agent-recon-check` | recall (4) |

Strategy 4 was designed to dodge the suspected failure mode of 1–3: a rule
premised on "your memory may be incomplete" loses to a model that trusts its
memory, whereas "you cannot know what is in this external corpus" is a fact no
prior can overrule. It made no difference — turn 1 was byte-for-byte the same
four searches.

## Why we stopped

- Four distinct framings, two distinct prompt locations (workflow list vs the
  success plan the model actually produces), zero behaviour change.
- The answers themselves were *good* every time (the recalled candidates are
  the canonical 2023-2025 advances; final runs: ~970 words, 6 refs, real
  derivations inline, e.g. DPO's closed-form reward and LoRA's ΔW = BA with a
  worked parameter count). The failure is only latent: on a field the model
  knows poorly it could silently scope the answer to a stale or wrong
  candidate list. Ironically, on such fields it is also more likely to search
  broadly of its own accord.
- Each probe run costs ~$1 and the marginal prompt idea was getting weaker.

The corpus-recon rule (strategy 4) is **kept** in the prompt: it is principled,
costs nothing on topics like this one (the searches were fine anyway), and may
still help on obscure subjects where there is no strong prior to fight (e.g.
the "Network Physicalization" test topic). We just don't expect it to change
behaviour on canon subjects.

Escalations deliberately not taken:

- **Python-side enforcement** — rejected: "was that a discovery search?" is a
  semantic judgment; a validator can't make it without another LLM call, and a
  wrong heuristic would nag runs that don't need it. Harness enforces
  protocol (commits, citations, word counts); search strategy stays in the
  prompt.
- **Per-topic task-prompt injection** — possible next step if this ever
  matters: a line in the per-query user message (where the timestamp already
  goes, so cache-neutral) is closer to the model's attention than the system
  prompt. Untested; parked.

## Attempt 5: mechanical query-term provenance (`aus-agent-qterm-check`)

Strongest formulation, different in kind from attitude instructions — a
checkable constraint on the query strings themselves (user-designed):
round-one queries built only from the question's own wording; every later
content-bearing query term traceable to a document retrieved earlier; an
escape valve (probe memory candidates one query each) when question-term
queries genuinely fail. Shipped together with a workflow restructure into a
3-step loop (Search → Commit → Decide) plus notes, and a full prompt audit
that removed contradicting lines ("prior knowledge may help you choose
searches", "narrower entities", creativity's claim to the answer's "shape").

Graded by reading the trajectory (a term-overlap metric was written, then
dropped — a stopword heuristic is a worse judge than reading a dozen runs):

- Rule 1 violated: turn 1 searched LoRA and QLoRA, neither in the question.
- Rule 2 mostly violated: PPO traceably appeared in turn-1 results before
  being searched, but DPO, RLHF, GRPO, DeepSeek, and chain-of-thought each
  first occur in the results of their own search — memory-seeded, staggered
  across turns rather than eliminated.

Five strategies, five failures: Sonnet 5 does not comply with query-provenance
instructions on subjects it knows well, whatever their form or placement.

The run was still Sonnet's best overall — 14 refs (vs 6 in every earlier
Sonnet run), 24 sentences / 948 words, 4 equation sentences, interleaved
commit+search each turn, clean protocol. The loop restructure appears to have
improved commit discipline and breadth even though grounding was ignored;
these changes are kept.

## Model A/B: Opus 4.8, same prompt, same topic (`aus-agent-opus-check`)

Since prompt wording was exhausted, swapped only the model
(`--model au.anthropic.claude-opus-4-8`; harness needed zero other changes).
Result — still no pure survey query, but the failure that matters is largely
gone:

- **Turn 1** queries are field-phrased with an anchor ("large language model
  fine-tuning techniques parameter efficient LoRA", "reinforcement learning
  from human feedback RLHF alignment training") rather than Sonnet's bare
  technique names.
- **Turn 2 is the real difference**: after committing 6 docs it launched a
  second wave into *new* territory — mixture-of-experts, FlashAttention,
  RoPE/long-context extension, instruction tuning + CoT. Sonnet 5 never once
  expanded beyond its initial four recalled techniques in four runs.
- Coverage: 11 refs / 12 committed docs / 30 sentences / 969 words vs
  Sonnet's 6 refs / 6 docs; answer spans LoRA, QLoRA, DPO+RLHF derivation,
  MoE, FlashAttention (S = QK^T memory argument), and RoPE frequency
  reinterpolation, each with inline maths (6 equation sentences).
- Protocol clean: committed on both turns, no staged-report lapse, no
  duplicated searches.
- Cost: 275K processed tokens at Opus pricing (~2-3× the Sonnet run).

Refined conclusion: the risk behind discovery-first — silently scoping the
answer to the initially recalled candidate list — is a Sonnet 5 behaviour,
mostly absent in Opus 4.8, which broadens iteratively even without a survey
query. Confirms "model-level"; model choice, not prompt wording, is the lever
for topics where breadth matters.

## Incidental finding from run `aus-agent-recon-check` (worth fixing)

On turn 2 the model wrote the entire final report **directly from the staged,
uncommitted batch** — no `commit_context` at all. Protocol handled it as
designed (batch expired, report bounced with feedback), and the model
recovered by re-running the same four searches verbatim, committing 6 docs,
and rewriting: same final answer at ~2× the tokens (228K processed vs 116K on
the equivalent `aus-agent-discovery-check` run). The contract states only
committed evidence may be cited, but nothing warns at the decisive moment that
a report-writing turn (which by definition issues no tool calls) lets any
staged batch lapse. Fix queued: one line in the final response contract —
commit first, report on a later turn.

## Also confirmed today

- `20260717T133001…design_a_framework_for_regulating` failed with
  `ValidationException: content field … is empty` — that run *predates* (by 5
  minutes) the contentless-Converse-reply retry fix (`70b4426`,
  `EMPTY_RESPONSE_RETRIES = 3` in `providers/bedrock.py`); its history shows
  the classic empty assistant message at index 3. Not a live bug.
- `ExpiredTokenException` mid-run produces a clean `status: "failed"` artifact
  and the topic re-runs fine after refreshing `.env` tokens.
