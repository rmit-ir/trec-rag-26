# 2026-08-07 — brief_revise_agent iteration 2: repo sync, aus_agent_v2 as the new target, sol-guided round 2

Follow-up to `worklogs/2026-08-07-brief-revise-agent-sol-improvement-analysis.md`.
User request this session: sync the repo (aus_agent had "a new version"),
pick a 15-topic experimental dev set, run the new baseline with
`gpt-5.6-luna`, then iterate with gpt-5.6-sol against a $50 sol budget +
$50 generation/eval budget until `brief_revise_agent` beats the new
baseline, or the budget/time runs out.

## 1. Repo sync

`git fetch && git merge origin/main` into `explore/new-agent-framework-system`.
Origin had diverged substantially: a new `aus_agent_v2` system (many commits
— atomic planner, obligation scout, coverage contract, semantic-closure
verification), plus `claude-code-research`/`codex_cli_research` and several
other new systems. `aus_agent` itself barely changed (6 lines, an IANA-
timezone prompt fix applied repo-wide). Merge conflicts were all in
generated/registry files (`docs/architecture.html`, `pyproject.toml` dep
groups, `gen_arch_viz.py`'s `SYSTEM_KIND`/`SYSTEM_BLURB` dicts) — resolved
by keeping both sides' additions and regenerating the HTML fresh. One
pre-existing, unrelated test failure surfaced after the merge
(`test_codex_cli_research.py` needs a local `.codex/config.toml` this box
never generated) — not caused by this work, noted and bypassed with
`SKIP_TEST_CHECK=1` on every commit since, each time after confirming it's
the only failure.

**`aus_agent_v2` is "the new aus_agent" per its own README**: a separate,
much more heavily engineered system (`src/systems/aus_agent_v2/README.md`),
whose default (`run_one`) scored **0.7042** on their own internal 30-topic
scorer vs 0.6508 for the old baseline, built through many paid experiment
rounds — the README states a tracked **$1,096.72** total spend against a
$300 cap. Design: an atomic obligation scout, a coverage-plan/critic stage,
evidence committed with explicit source-quote+scope+exact-term validation
tied to stable requirement ids, a typed `submit_answer` terminal tool
(not free prose), deterministic multi-axis validation, and an optional
post-handoff semantic-closure verifier.

## 2. Generalized the arena script's baseline side too

`tasks/task-comparison/scripts/arena_aus_agent_vs_facets_agent_rubric.py`
already had `--challenger-system`/`--challenger-run-id` (this session,
earlier). Added the symmetric `--baseline-system`/`--baseline-run-id`
(default `aus_agent`, byte-identical for every existing invocation) so
`aus_agent_v2` could be compared without copy-pasting the script again.

## 3. 15-topic experimental dev set

Reused the 14 clean-loss + 1 clean-win topics from the last full-30 run
against the OLD `aus_agent` (continuity with the existing sol analysis of
those exact topics). `data/task-comparison/topics-brief-revise-exp15.tsv`.

## 4. New baseline, generated fresh

```bash
export OPENAI_API_KEY="$(grep '^AZURE_OPENAI_API_KEY=' .env | cut -d= -f2-)"
uv run --group aus-agent-v2 python src/systems/aus_agent_v2/run.py \
  --all --topics data/task-comparison/topics-brief-revise-exp15.tsv \
  --backend openai --model gpt-5.6-luna \
  --run-id aus-agent-v2-exp15-luna --skip-existing
```

15/15 completed, 0 failed. Notably heavier per-topic than `aus_agent`/
`brief_revise_agent` — many more search rounds per topic (its atomic
obligation-scout + coverage-plan stages).

## 5. Iteration 1 (already built earlier this session, sol Priority 1: the
coverage-gated patch review) vs the new baseline

```bash
uv run --group brief-revise-agent python src/systems/brief_revise_agent/run.py \
  --all --topics data/task-comparison/topics-brief-revise-exp15.tsv \
  --backend openai --model gpt-5.6-luna \
  --run-id brief-revise-iter1-exp15 --skip-existing

uv run --group aus-agent python \
  tasks/task-comparison/scripts/arena_aus_agent_vs_facets_agent_rubric.py \
  --baseline-system aus_agent_v2 --baseline-run-id aus-agent-v2-exp15-luna \
  --challenger-system brief_revise_agent --challenger-run-id brief-revise-iter1-exp15 \
  --out-dir evaluation-results/arena/aus_agent_v2-vs-brief_revise_agent-iter1-exp15
```

```
aus_agent_v2 vs brief_revise_agent: 22-8-0 (n=30 battles), aus_agent_v2 pref rate 0.7333
Clean win groups: aus_agent_v2 wins 10, brief_revise_agent wins 3, 2 ambiguous.
```

For comparison: iteration 1's LAST measured result (different opponent —
the OLD `aus_agent`, full 30 topics, before this session's sync): 14 clean
losses / 9 clean wins / 7 ambiguous, 58.3% pooled preference for the old
baseline. **The clean-loss ratio roughly tripled** against the new
opponent (10-3 here vs 14-9 there, on a smaller/harder-selected topic set —
some widening is structurally expected since this 15-topic set is exactly
the old losses, but the direction and size of the gap is a real signal).

## 6. Sol consultation round 2 ($0.49 of the $50 sol budget)

Handed sol: the fresh 15-topic result (both systems' full answers, brief
content, search logs, review-fire status per topic — extraction script
`worklogs/assets/2026-08-07-extract-iter2-data.py`), the current
`brief_revise_agent` code (post-iteration-1), and `aus_agent_v2`'s full
README, with an explicit ask to be honest about whether closing this gap by
tomorrow's deadline is realistic. Full response:
`worklogs/assets/2026-08-07-sol-iter2-vs-aus-agent-v2-plan.md`.

**Sol's bottom line, stated plainly and not softened:** *"I do not think a
few-hour iteration on brief_revise_agent is likely to beat aus_agent_v2
overall before tomorrow... the new 22-8 result is consistent with a real
capability gap rather than one remaining prompt defect."* Realistic
forecast: converting 1-3 of the 10 clean-loss topics, not reversing the
battle result. Explicit recommendation on the actual submission: *"the
rational submission choice remains [aus_agent_v2's] verified default unless
a separately tested candidate clearly beats it — the current evidence does
not support betting the submission on this fork."*

**Which `aus_agent_v2` mechanism is actually transferable, and which
isn't:** sol recommends the atomic obligation scout (a bounded inventory of
small, independently-gradable checks, including expert-domain checks the
request never states) as the one separable idea. Explicitly rejects
porting the typed `submit_answer` terminal contract this iteration — its
value comes from the whole surrounding machinery (stable obligation ids,
searches/commits tagged to them, extractive source-quote validation,
terminal evidence replay, bounded correction), not from the tool
serialization alone; building the full contract safely is "not a few-hour
change."

**A real correctness bug in iteration 1's reviewer, found by close reading
of the code (not just the data):** `_parse_review` accepted any
well-formed `{"requirements": [...], "issues": [...]}` shape as a
successful parse even when the requirements array graded only a SUBSET of
the brief's ids, or omitted ids entirely — the "grade every requirement"
contract was stated in the prompt but never enforced in code. Separately, a
PARTIAL/MISSING grade with an empty `fix` string was silently dropped from
the rendered feedback (`gaps = [... and g["fix"]]`), so a real gap the
reviewer identified could vanish without a trace.

**Sol's diagnosis of what iteration 1 actually achieved:** no same-code
ablation exists to prove causation, but the surface behavior matches intent
— nearly every answer now has zero uncited sentences, and the 3 clean wins
+ 2 ambiguous topics are exactly the ones where systematic requirement
carry-through matters most (long chronological narrative, code-bearing
design, many-actor political account). But citation-sentence coverage
stopped being the decisive factor against this opponent: `aus_agent_v2`
frequently won with MORE uncited sentences (19 on geometry, 21 on scaling)
because the judge weighted substantive completeness and domain judgment
over citation saturation. The real gap on most losses is length-driven by
EXECUTABLE CHECKS, not padding — sol's word-count table shows
`brief_revise_agent` running 200-500 words shorter than `aus_agent_v2` on
6 of the topics, and traces it to specific missing content per topic (a
concrete worked example, replay/continual-learning discussion, a distinct
crisis pathway, prospective-validation design detail — content an expert
reader would expect but the request's own wording never names, which the
OLD lexical anti-hunch gate structurally excluded from the brief).

## 7. Iteration 2, built (`8a1feec`)

Per sol's spec, two changes:

1. **`brief.py`/`prompts.py` — the brief becomes an "atomic
   expert-completion" checklist.** Caps raised (14 total / 6
   `EXPERT_COMPLETION`, was 8/4 "implicit"); explicit atomicity instruction
   ("Address subgroup testing, false negatives, and human review" must
   become three entries, not one) with worked split-apart examples from the
   actual loss topics; the OLD lexical anti-hunch gate (`why` had to
   word-overlap the narrative) is **dropped** — sol's read is that it was
   suppressing exactly the domain-completion material that distinguishes
   `aus_agent_v2`'s stronger answers — replaced by a cheaper check: an
   `EXPERT_COMPLETION` entry needs a stated concrete reason (`why_needed`),
   not narrative overlap. Ids are now **harness-assigned** (`A01`, `A02`,
   ... in accepted order), never read from the model's own JSON — this is
   what makes the reviewer-side fix (next) enforceable at all: there's no
   model-chosen id space left to omit from, duplicate, or invent into.
2. **`review.py` — the correctness fix.** `_parse_review` now enforces
   exact atomic closure: the returned requirement ids must equal the
   brief's id set exactly, no duplicates, no omissions, else `parsed_ok`
   is `False` and the existing fail-closed retry fires (same mechanism
   iteration 1 already has for malformed JSON). A non-FULL grade with an
   empty `fix` now gets a synthesized fallback fix instead of silently
   dropping from feedback. The "never touch FULL content" patch rule is
   loosened per sol's finding that several losses were already near the
   1024-word cap: FULL-supporting content may now be compressed, merged, or
   relocated (not deleted or weakened) to free room, rather than being
   completely frozen.

Tests: added 4 new cases (harness-assigned sequential ids, an
`EXPERT_COMPLETION` entry dropped only for a missing `why_needed` — not for
failing a lexical check that no longer exists — the entry-cap enforcement
at the new limits, and the core new behavior: a reviewer response that
skips a requirement id triggers the same fail-closed retry as unparseable
JSON). `bash scripts/test.sh`: 1916/1917 passed (the one pre-existing,
unrelated `codex_cli_research` gap).

## 8. Pilot, per sol's own budget-conscious execution plan

Sol's explicit recommendation: *"Do not rerun all 15 topics ... generate
only the iteration-2 fork"* on 5 topics (4 likely-gain + 1 regression
guard), judge against the cached iteration-1 and cached `aus_agent_v2`
answers, predeclare a promotion rule, and stop spending if it fails.
5-topic set (`data/task-comparison/topics-brief-revise-pilot5.tsv`):
neuroscience/engram (`683a58c9a7e7fe4e76958488`), U-Net as the regression
guard (`6847465956a0f6376a6053ca`), CS:GO (`6847465956a0f6376a605404`),
VLM specialist substitution (`6847465956a0f6376a605492`), wellness agent
(`6847465956a0f6376a6054ad`).

[continued in the next worklog entry once the pilot run and judging complete]
