# Plan: `brief_revise_agent` — the winning baseline, plus a pre-flight requirements brief and one grounded revision pass

**Status: planning only, nothing here implemented yet.** Written 2026-08-06 on
branch `explore/new-agent-framework-system`, two days before the 2026-08-08
submission deadline. Inputs, in order: framework research on three open-source
deep-research stacks (LangChain `open_deep_research`, GPT Researcher, ByteDance
DeerFlow); an architecture proposal from `gpt-5.6-sol` grounded in those
(verbatim copy: `worklogs/assets/2026-08-06-sol-architecture-proposal.md`,
$0.15); and this review, which re-derived the evidence against the real repo
and changed four things. Session narrative:
`worklogs/2026-08-06-brief-revise-agent-architecture-plan.md`.

The system is a **fork of `aus_agent`** — the same shared
`agent_harness.run_agent` loop, the same 267-line tuned prompt, the same engine
set and budgets — with exactly two additions:

1. a **requirements brief**: one tool-less LLM call before the run, whose
   output is appended to the system prompt;
2. one **review-and-revise pass** at the end, carried on the harness's
   `pre_final_hook`, which sends the model back once with a list of concrete
   defects in its own draft.

Everything else is deliberately byte-identical to `aus_agent`, because
`aus_agent` is the thing to beat and a fork that changes five variables at once
cannot be read.

---

## 1. The evidence this is built on

Two prior decomposition systems lost to `aus_agent`:

- **`facet_rag`** (planner + concurrent per-facet orchestrator/analyzer/curator,
  isolated context per facet) lost on UMBRELA relevance on all 5 measured
  topics; root cause was the curator over-trimming — "content starvation"
  (`worklogs/2026-08-05-facet-rag-honest-rebaseline.md`).
- **`facets_agent`** (one continuous agent, short prompt asking the model to
  self-decompose) loses 20-4-6 in clean win groups on the 30-topic dev set,
  76.7% pooled battle preference for `aus_agent`
  (`worklogs/2026-08-06-facets-agent-phase4a-dev30-eval.md`). LLM root-cause
  diagnosis: `not_decomposed` 47.8%, `covered_but_shallow` 47.4%
  (`worklogs/2026-08-06-facets-agent-loss-factor-analysis.md`).

**That diagnosis is about a system we are not forking.** `sol`'s proposal
justifies its whole design against those two failure modes; the design forks
`aus_agent`, which by construction does not have them (it is the system that
beat them). Before adopting the design I re-asked the question that actually
matters: *where does `aus_agent` itself still lose points?* The answer is the
load-bearing evidence for everything below, and it was free — the per-criterion
scorecard from the dev30 arena already exists.

Probe (read-only, no API cost, reproduces every number here):
`worklogs/assets/2026-08-06-aus-agent-headroom-probe.py`, over
`evaluation-results/arena/aus_agent-vs-facets_agent-dev30-rubric/criterion-scores/`
and `data/outputs/aus_agent/*.output.json` (`run_id=aus-agent-dev30-luna-e2708ab`,
`gpt-5.6-luna`, 30/30 topics).

```
answers n=30  words mean=872 median=926 min=326 max=1007  (hard cap 1024)
sentences 903, uncited 235 (26.0%)

criteria judged n=755  grades {0: 42.5%, 1: 23.3%, 2: 34.2%, 3: 0.0%}

  Implicit Criteria                n= 315 mean=0.82 pct<=1=71%
  Explicit Criteria                n= 211 mean=1.22 pct<=1=53%
  Synthesis of Information         n= 108 mean=0.87 pct<=1=67%
  Communication Quality            n=  59 mean=0.66 pct<=1=73%
  Instruction Following            n=  43 mean=0.88 pct<=1=65%
  References & Citation Quality    n=  18 mean=0.11 pct<=1=100%
```

Four findings drive the design:

**(a) The winner fails 42.5% of official criteria outright and never scores 3.**
There is no ceiling problem here. On its *own clean-win topics* `aus_agent`
averaged 2.10/3 overall against `facets_agent`'s 1.85 — winning a comparison,
not answering the question well.

**(b) The largest pool of lost weight is `Implicit Criteria`: 315 criteria,
71% graded ≤1.** Reading the high-weight zero-graded ones, they are exactly the
`not_decomposed` shape, and they are *not* obscure: "defines bonds as loans";
"compares traditional and Roth savings accounts for the 401k and IRA"; "names
the major US stock market indexes (S&P 500, Dow Jones, Nasdaq, Russell 2000)";
"highlights policy or regulatory responses (Section 230, COPPA, the SAFE act)";
"specifies the geographical regions under consideration and justifies this
selection". These are obligations any competent reader infers from the request
in ten seconds — and the writing agent, 200K tokens into a search loop, does
not. So `not_decomposed` is not a `facets_agent` defect at all; it is the
dominant defect of the *baseline*, and `facets_agent`'s diagnosis was simply
the first place it got named. **This is what the requirements brief is for**,
and it is the reason to keep the intervention even though `aus_agent`'s prompt
already contains a §0 "every requirement the request states" instruction: the
instruction exists and is measurably not enough when it competes with
retrieval for the same attention.

**(c) 26.0% of `aus_agent`'s answer sentences (235 of 903) carry no citation.**
Markdown headings are stripped by `_parse_final_prose` before this count, so
these are all prose sentences. TREC scores weighted citation *recall* over all
sentences — an uncited sentence scores 0 — as a separate axis from precision
(`skills/trec-rag-2026-track-guidelines/references/rag-task.md`). A quarter of
every answer is scoring zero on one of three official axes, and it is
deterministically detectable with no model call. **This is what the review pass
is for**, and it is the cheapest available point of leverage in the whole repo.

**(d) The word cap is already binding on half the topics.** Median answer 926
words against a 1024 hard cap; 10 of 30 topics are above 965. Any reviewer that
says "also cover X" without saying "cut Y" produces an over-length report, which
`_parse_final_prose` *rejects*, costing a correction turn. `sol` did not account
for this. It changes the reviewer's contract from *additive* to *substitutive*
and it is why the revision instruction must carry the live word count. Note the
opposite case exists too: the two worst-scoring topics answered in 326 and 500
words, so on some topics there is a third of the budget sitting unused.

---

## 2. Mechanical constraints verified against the real harness

`sol` wrote its control flow against a prose description of the harness. I
traced it. Five things it assumes are wrong or unnecessary; all are cheap to
fix, none is fatal.

1. **`pre_final_hook` fires only on an ALREADY-VALID candidate**
   (`src/agent_harness/agent.py:918` and `:1039`, both guarded by
   `if candidate is not None:` after `_parse_final_prose`). So `sol`'s §4.1
   deterministic checklist — word count over 1024, more than 3 citations,
   unknown docids, malformed answer objects, invalid reference indices — is
   **already enforced upstream** and cannot reach the hook: over-length is a
   rejection, >3 citations are trimmed, uncommitted docids are dropped,
   headings/fences/emphasis are repaired (`_parse_final_prose`,
   `agent.py:200-315`). The one deterministic check that is *not* redundant is
   the uncited-sentence scan — finding (c) — because an uncited report is only
   refused when *no* sentence anywhere cites anything. Build that one; drop the
   rest.
2. **The hook needs no network.** `sol` has the reviewer re-fetch every cited
   document's full text from the ClimbMix endpoint. Unnecessary:
   `ContextLedger.call_history` keeps every staged call's original full-text
   documents for the life of the run (`src/agent_harness/context.py:113-117`),
   and the hook receives the live `ledger` in its context dict
   (`agent.py:756-763`). Read the text locally: zero latency, zero cost, and no
   new failure mode on a flaky endpoint.
3. **Post-review searches are best-effort, not guaranteed.** When
   `budget_hit or safety_hit`, every `search` call is refused with an error
   envelope (`agent.py:1215-1240`) — so if the hook fires *after* the budget
   trips, the revision has only committed evidence to work with. In practice
   this is the good case: all 30 dev30 `aus_agent` runs ended `status=completed`
   (mean ~8 searches), so the budget is normally intact. The revision
   instruction must still be written to be satisfiable with **zero** new
   searches, treating extra retrieval as optional.
4. **The brief goes in the system prompt, not the user message.** `sol`'s
   pseudocode gets this right (`system_prompt=build_prompt(AUS_PROMPT, ledger)`)
   but its "injected user-side context" block contradicts it. The user message
   is built by the harness from `query` (`TASK_PROMPT`, `agent.py:83-89`), and
   `query` is also what `TrajectoryBuilder` records as the topic narrative —
   appending a brief to it would corrupt the saved artifact. `system_prompt` is
   a per-call parameter, so a per-topic appendix needs **no harness change at
   all**.
5. **Citation-index mapping and `references[]` are already done.** `sol`'s
   "output construction" section (dedupe cited docids in first-citation order,
   map to 0-based indices, validate) describes `_map_citations` +
   `build_rag_output` + `validate_rag_output` as they already exist
   (`agent.py:317-350`, `src/ragrun/`). No work.

Two more facts that shape the build:

6. **A one-shot tool-less LLM call already has a helper.**
   `src/systems/facet_rag/llm.py::one_shot(provider, system, user)` plus
   `strip_fences` — 20 lines, used by `facet_rag`'s planner/curator, and exactly
   what the brief and the reviewer need. Import it rather than writing a third
   copy. (If a later cleanup wants it in `agent_harness`, that is a move, not a
   rewrite. Not doing it now: shared-layer changes cost a full-suite rerun and
   buy nothing this week.)
7. **`facets_agent` is the worked example for a fork of this shape** — a ~50-line
   `agent.py` that is pure configuration over `run_agent`, its own `run.py` CLI,
   its own prompt, its own `pre_final_hook` (`review.coverage_gate`) wired as a
   default kwarg that tests can pass `None` to disable
   (`src/systems/facets_agent/agent.py:123-152`). Copy that skeleton.

---

## 3. The design

```
src/systems/brief_revise_agent/
├── __init__.py
├── agent.py                    # ~60 lines: config over agent_harness.run_agent
├── brief.py                    # requirements analyst: 1 LLM call, strict JSON, fallback
├── review.py                   # pre_final_hook: uncited scan + 1 reviewer call
├── prompts.py                  # BRIEF_PROMPT, REVIEW_PROMPT, APPENDIX template
├── prompts/system/default.md   # byte-copy of aus_agent's + one appended section
├── run.py                      # copy of aus_agent/run.py, renamed defaults
└── README.md
```

### 3.1 `brief.py` — the requirements brief (targets finding (b))

One tool-less call before `run_agent`, on the same provider factory
(`make_provider(backend, model)`), via `facet_rag.llm.one_shot`. Input: the
narrative and a schema. Output, strict JSON:

```json
{"requirements": [
  {"id": "R1",
   "requirement": "Define each instrument named (stocks, bonds, 401k, IRA) at first use",
   "origin": "implicit",
   "why": "the request addresses a beginner audience and names four instruments",
   "specific_form": "a one-line definition per instrument, not a category label"}
]}
```

Rules, all of which exist to stop the planner failure that killed `facet_rag`:

- **Cap at 8 entries**, at most 4 of them `origin: "implicit"`. An analyst that
  invents obligations is worse than none: every entry it adds competes for a
  binding 1024-word budget (finding (d)).
- Every implicit entry must name the wording that implies it (`why`). An entry
  that cannot cite the request is a hunch and gets dropped at parse time.
- `specific_form` is the anti-`covered_but_shallow` field: it states what
  *counts* as covering the requirement, in the shape the rubrics reward (a named
  entity, a mechanism, a number, a comparison) rather than a topic label.
- **Parse defensively, never block a run.** Bad JSON, missing keys, zero
  usable entries → empty brief → the run proceeds exactly as `aus_agent` does
  today. Same policy as `facet_rag.planner.fallback_facets`.

The brief is rendered into a short appendix appended to the forked system prompt
(§3.2), explicitly labelled advisory: *a checklist to search against and to
check the report against, not an outline the answer must follow.* The
narrative, not the brief, remains the authority — a planner that has
misread the request must be overridable by the corpus, which is the failure
`facet_rag`'s rigid plan could not recover from.

### 3.2 The prompt fork

`prompts/system/default.md` starts as a **byte-copy** of
`src/systems/aus_agent/prompts/system/default.md` (267 lines, including its
`__MAX_COMMITTED_DOCS__` placeholder, loaded by the same
`load_system_prompt`-style helper). Two edits, both additive:

- **Appendix A — the brief** (rendered per topic, ~15 lines): the requirement
  list, plus three sentences of contract: every entry gets at least one targeted
  search; an entry is covered only when the answer states the specific form, not
  the category; amend an entry the corpus contradicts, but never silently drop
  one.
- **Appendix B — the review contract** (~6 lines): tell the model up front that
  its first report is a draft that will be checked against the brief and against
  its own citations, and that it will get exactly one revision. A model that
  knows a review is coming writes a draft that is easier to revise; a model
  surprised by the feedback rewrites from scratch and loses material.

Nothing in the base 267 lines is edited or deleted — including the round-one
anti-seeding rule, which stays as `aus_agent` has it. `facets_agent` already
runs the experiment of relaxing that rule; running it again inside a different
change would confound both.

### 3.3 `review.py` — the `pre_final_hook` (targets findings (b), (c), (d))

Signature is fixed by the harness: `hook(context: dict) -> str | None`, fired at
most once, `None` accepts the draft, a string is injected as a user message and
the loop continues. Sequence inside:

1. **Deterministic scan (no LLM).** From `context["candidate_sentences"]`:
   the indices and text of every sentence with an empty `citations` list, and
   the total word count via the same `split()` rule the harness uses. This is
   finding (c), and it alone justifies the hook.
2. **One reviewer call** (`one_shot`, same provider factory, may be a cheaper
   model). Input:
   - the narrative and the brief;
   - the draft, one numbered sentence per line, with its citations;
   - the deterministic uncited-sentence list;
   - an **inventory of committed evidence** — for each committed id, a short
     snippet pulled from `ledger.call_history`, so the reviewer can say "R4 is
     supported by `shard_x_y`, which you committed and never used" rather than
     "do more research";
   - the live word count against the 1024 cap.

   Output: strict JSON, at most 6 issues, each one of
   `MISSING_REQUIREMENT` / `SHALLOW` / `UNCITED_CLAIM` / `WEAK_SENTENCE`, each
   naming the sentence number or requirement id, and each carrying a
   `fix` that is a *substitution* — what to cut to pay for what to add.
3. **Feedback or accept.** No issues and no uncited sentences → return `None`
   (byte-identical to no hook). Otherwise return a feedback string: the issue
   list, the word budget arithmetic ("your draft is 947 words; the cap is 1024"),
   and the standing instructions that the revision must (i) keep every claim it
   already supports, (ii) prefer attaching an existing committed docid to an
   uncited sentence over deleting the sentence, (iii) use extra searches only if
   a required item is genuinely unsupported — they may be refused if the budget
   is spent (§2.3).
4. **Never break a run.** The whole hook body is wrapped: any exception, timeout
   or unparseable reviewer response → log and return `None`. A review failure
   must degrade to `aus_agent` behaviour, not to a failed topic, and this is not
   negotiable on a two-day timeline.

Not built (deliberate, see §5): sentence-level entailment checking against full
document text. That is the expensive half of `sol`'s reviewer (every cited
document, in full, in one call) and it targets citation *precision*, which is
not where the measured hole is.

### 3.4 What does NOT change

Search tool schema; commit tool schema; engine set (`semantic,keyword`);
`k`; `context_token_budget` (500K); `safety_max_rounds`; `max_committed_per_step`;
commit policy; the report contract; `_parse_final_prose`; `_map_citations`;
`ragrun`. **Zero shared-code changes** — `pre_final_hook`, `system_prompt` and
`system_name` are all existing parameters. That is the single most important
property of this plan: the system is one `git diff` of `aus_agent` plus two
files, and it can be compared to `aus_agent` as a two-variable experiment.

---

## 4. Adopted vs rejected from `sol`'s proposal

| `sol` proposed | Verdict | Why |
|---|---|---|
| B (GPT Researcher reviewer/reviser pattern) over A/C, without vendoring the framework | **Adopt** | Correct, and for a better reason than given: it targets `aus_agent`'s own measured deficits (§1), not `facets_agent`'s |
| Fork the full `aus_agent` prompt, append rather than rewrite | **Adopt** | `facets_agent` already ran the short-prompt experiment and lost |
| Requirements analyst as one tool-less JSON call with a hard facet cap + fallback | **Adopt** (cap 8/4 not 6/3, and add `specific_form`) | §1(b); `specific_form` is what makes an entry checkable against the shallow-coverage failure |
| `pre_final_hook` reviewer + one revision in the same conversation | **Adopt** | The conversation still holds all committed evidence; the reviewer diagnoses, the evidence-rich agent revises — this is the anti-starvation property |
| Reviewer's deterministic checks (word cap, ≤3 citations, bad docids, malformed objects) | **Reject** | Already enforced before the hook can fire (§2.1). Keep only the uncited-sentence scan, which is not |
| Reviewer fetches full text of every cited doc from ClimbMix | **Reject** | `ledger.call_history` already holds it locally (§2.2); and full-text entailment checking is the expensive half aimed at the wrong axis (§5) |
| `search_policy.py`: `facet_id`/`goal` bookkeeping fields on the search tool | **Reject** | `facets_agent` already ships exactly this (`requirement` on every search, PLAN §1.1) and it is measured insufficient. It also perturbs the tuned search schema, turning a two-variable experiment into a three-variable one |
| Retrieval budget re-spec (14 searches, k≤8, 30–45 docs, 30–34 rounds) | **Reject** | Never retune the winning baseline's knobs inside an architecture experiment. Dev30 `aus_agent` runs ~8 searches and finishes `completed` on 30/30 |
| Ledger injected as user-side context | **Fix** | Corrupts the recorded narrative; use the `system_prompt` parameter (§2.4) |
| Reviewer issues are additive ("add cost analysis") | **Fix** | Median draft is 926/1024 words — issues must be substitutions with the word budget attached (§1(d)) |
| Explicit output-construction steps (dedupe refs, map indices, validate) | **Drop** | Already implemented (§2.5) |
| Stretch list (entailment scoring, adaptive budgets, parallel analysts, multiple review rounds, LangGraph/GPT-Researcher as a dependency, learned reranking, cross-topic memory) | **Agree, all cut** | Nothing on that list is buildable and measurable in two days |
| Name `ledger_revise_agent` | **Rename** | `ledger` is a load-bearing identifier in shared code — `ContextLedger`, `context["ledger"]`, `ledger.committed_ids` — and means the staged/committed *document* ledger, not a requirements list. `brief_revise_agent` names the two actual interventions with no collision |
| Keep `aus_agent` as the fallback submission | **Adopt, emphatically** | §7 makes this the default outcome unless the new system clears a preregistered bar |

---

## 5. Alternatives considered and rejected

**(a) LangChain `open_deep_research` (supervisor + parallel isolated
researchers).** This is `facet_rag`'s topology with better engineering. The
measured failure of `facet_rag` was not implementation quality, it was that
isolated per-facet contexts arrive at synthesis pre-compressed. Fixing that
means removing the isolation, i.e. removing the framework. Rejected.

**(b) ByteDance DeerFlow.** Checkpointing, sandboxing, memory, MCP, general
subagents — none of it addresses a cited-QA task, all of it costs integration
days we do not have. Rejected.

**(c) A third decomposition architecture of any kind.** Two have lost. The one
lesson both losses share is that *the writer must be the searcher, holding all
the evidence*. This plan's two interventions are the only two that do not put a
context boundary between evidence and prose: the brief runs *before* any
evidence exists, and the reviewer *cannot delete evidence* — it emits text, and
the same conversation revises.

**(d) A separate "publisher"/formatting model.** Another chance to detach a
citation from its sentence, for no measured gain. Rejected (`sol` agrees).

**(e) Full-text entailment checking of every cited sentence.** The tempting
version of the reviewer. Rejected for v1 on cost/benefit: it needs every cited
document in the review call (20–40 docs × ~2.5K tokens), and it targets citation
*precision*, whereas the measured hole is recall — 26% of sentences cite nothing
at all (§1c). Fix the sentences with zero citations before auditing the ones
that have three. Revisit only if precision is measured bad.

**(f) Building this as a `facets_agent` phase instead of a new system.**
Rejected: `facets_agent` carries the short-prompt bet and the prior-knowledge
divergence, both of which are confounds against `aus_agent`, and it is the
system that is losing. The whole point is to start from the winner.

**(g) Making the reviewer able to fire more than once.** The harness fires the
hook at most once by design (`pre_final_hook_fired`, `agent.py:750-763`) — a
structural guarantee against loops. Working around it (e.g. a hook that returns
feedback and tracks its own counter) is possible but would need a harness change
and doubles the worst-case cost. One round, and the revised report still passes
`_parse_final_prose`. Rejected for v1; `sol` reaches the same conclusion.

---

## 6. Build sequence (sized for two days, ~1 day of coding)

**Phase 0 — fork (≈45 min).** Package skeleton per §3, `prompts/system/default.md`
as a byte-copy, `agent.py` modelled on `facets_agent/agent.py` (config only,
`system_name="brief_revise_agent"`, `pre_final_hook=review.hook` as a
default kwarg), `run.py` copied from `aus_agent/run.py` with `RUN_BRIEF_REVISE_AGENT_*`
env prefixes, `ARCH_STAGES`, `README.md`. Reuses the `aus-agent` dep group — no
new dependencies. Regenerate `docs/architecture.html`. Gate: one live topic runs
end-to-end with the brief and the hook stubbed out and produces an artifact
identical in shape to `aus_agent`'s.

**Phase 1 — `brief.py` (≈2 h).** Prompt, strict-JSON parse, caps, fallback,
appendix rendering. Gate: run 2 topics live, read the briefs by hand against
the official rubrics for those topics — do the implicit entries look like the
rubric's implicit criteria? If the analyst is producing generic filler, stop and
fix the prompt before building anything on top of it.

**Phase 2 — `review.py` (≈3 h).** Deterministic uncited scan, evidence
inventory from `ledger.call_history`, reviewer prompt + parse, feedback
rendering, blanket exception guard. Gate: 2 live topics, read the full
trajectory — did the model actually act on the issues, and is the revised draft
still in-budget and still cited?

**Phase 3 — tests (≈1 h).** Offline, using `tests/conftest.py`'s
`scripted_provider` and `stub_search_tool`, mirroring
`tests/systems/test_facets_agent.py`:
(i) the hook returns `None` for a clean draft, so behaviour is identical to no
hook; (ii) it returns feedback naming the uncited sentence indices when the
draft has uncited sentences; (iii) a reviewer call that raises, or returns
garbage, still accepts the draft (the no-break-a-run invariant); (iv) the brief
parser survives bad JSON and yields an empty brief; (v) a run with a non-empty
brief puts it in the system prompt recorded at `trace.input.system_prompt`;
(vi) `pre_final_hook=None` disables the whole pass. Then
`bash scripts/test.sh` — full suite, since a new system under `src/systems/`
is in the arch-viz check's path.

**Phase 4 — pilot (≈1 h wall, ~$1).** Four topics, chosen as the ones where
`aus_agent` loses the most positive rubric weight, one per failure shape
(numbers from the §1 probe):
`6847465956a0f6376a6054be` (0.877 weight lost, implicit mean 0.14 — pure
missing-requirements), `6847465956a0f6376a605440` (0.798, answered in only 326
words — the under-length case where the brief has free budget to spend),
`6847465956a0f6376a6053a0` (0.758, **67% uncited sentences at 926 words** — the
citation-recall case *and* the binding-word-budget case together),
`6847465956a0f6376a6054a7` (0.858, 28 criteria, and a `facets_agent` clean win —
a topic where the baseline is beatable). Gate before spending on the full run:
uncited-sentence rate must fall on `6053a0`, and no topic may come back
over-length, `failed`, or with fewer citations than `aus_agent`'s answer for the
same topic.

**Phase 5 — dev30 run + evaluation (≈3 h wall).** All 30 dev topics,
`--run-id brief-revise-dev30-<sha>`, `--skip-existing` so an interrupted batch
resumes. Then §7. **Deadline discipline:** Phase 5 must start by the morning of
2026-08-07. If Phase 2 is not passing its gate by then, ship `aus_agent` and
keep this branch unmerged — that is a successful outcome of a two-day
experiment, not a failure.

---

## 7. Validation plan

Reuse the existing tooling. `tasks/task-comparison/scripts/arena_aus_agent_vs_facets_agent_rubric.py`
and `rubric_scorecard_aus_agent_vs_facets_agent.py` already do exactly the
required job — both battle orders, pooled + clean-win groups, official
ResearchRubrics criteria, `gpt-5.6-terra` as a judge that generated neither
side's answers, `load_answers_from_outputs(system_dir, run_id)` already generic.
They hardcode `LABELS = ["aus_agent", "facets_agent"]` and the two `--*-run-id`
flags. **Generalize in place** (add `--challenger-system` / `--challenger-run-id`
defaulting to `facets_agent` and today's run id, ~10 lines each) rather than
copying 250-line scripts — old invocations keep working, and the prior worklogs'
commands stay reproducible. `aus_agent`'s side needs no new generation: the
`aus-agent-dev30-luna-e2708ab` answers already exist.

**Tier 0 — deterministic, free, computed from the run's own artifacts.**
Preregistered against the §1 baselines:

| metric | `aus_agent` baseline | target |
|---|---|---|
| uncited-sentence rate | **26.0%** (235/903) | **< 15%**, and no topic worse than its own baseline |
| words per answer | mean 872 / median 926 | ≤ 1024 on every topic; no `_parse_final_prose` over-length rejection |
| run status | 30/30 `completed` | 30/30 `completed`, 0 `failed` |
| brief entries per topic | n/a | 3–8, with ≥1 implicit; 0 means the analyst silently failed |
| hook outcome | n/a | fired on ≥ 2/3 of topics; if it accepts almost every draft the reviewer is toothless, if it fires 30/30 it is nitpicking |
| searches / processed tokens | ~8 searches, ~88K processed | not materially up; a doubling means the appendix changed the search behaviour, which is a confound |

If the uncited-sentence rate does not move, the review pass has failed at the
one thing it is deterministically able to fix, and no amount of arena noise
should rescue it.

**Tier 1 — the free within-run A/B of the revision pass (~$0.30).** The
pre-revision draft is *preserved in the trajectory*: the no-tool-call turn is
recorded by `_record_turn` before the hook runs, so `trace.steps` holds both the
draft and the final answer for every topic where the hook fired. Score both with
`rubric_scorecard_*` (extracting the draft into an answer-shaped record) and get
a **paired** before/after on the official criteria at zero extra generation
cost. This is the only measurement in the plan that isolates one intervention
cleanly, and it is the one to trust: if the revised answer does not beat its own
draft on `Implicit Criteria` coverage or on uncited sentences, the reviewer is
noise regardless of what the arena says.

**Tier 2 — arena vs `aus_agent` (30 topics × 2 orders, ~$1–2).** Read **clean
win/loss groups**, not the pooled count: the judge shows documented position
bias (order consistency 0.8 on the last dev30 run, 0.533 on an earlier 15-topic
one). Plus the per-criterion scorecard, watching `Implicit Criteria` (315
criteria, `aus_agent` 71% ≤1) as the primary axis — that is where the design
says the gain must come from, and a win that shows up anywhere else is luck.
Cache hygiene: judgments key on `task_id`, so re-judging a *reused* run id
returns stale verdicts — always use a fresh `--run-id` (the trap documented in
`worklogs/2026-08-05-facets-agent-rerun-full-reevaluation.md`).

**Decision rule, preregistered.** Submit `brief_revise_agent` only if all three
hold: (i) Tier 0's uncited-sentence rate improves and nothing else regresses;
(ii) Tier 1's paired comparison favours the revised answer; (iii) Tier 2 clean
win groups are at least **12-x-y with x ≤ 8** — i.e. it wins clean on more
topics than it loses clean on. Anything less and `aus_agent` is the submission.
At n=30 the arena can confirm a Tier-0/Tier-1 improvement but cannot refute one;
report it with its noise characteristics attached, as the previous worklogs do.

---

## 8. Risks

- **The brief invents obligations.** The `facet_rag` planner failure in a new
  costume, and now it competes for a binding word budget (§1d). Mitigations:
  8/4 caps, the `why`-must-quote-the-request rule, "advisory not an outline"
  framing. Detection: Tier 0 brief size + Tier 2 `Explicit Criteria` going *down*
  while `Implicit` goes up — that trade means the brief pulled the answer off
  the actual question.
- **The revision loses more than it gains.** One round, near the context limit,
  with a word cap forcing substitutions: the model may cut a well-supported
  paragraph to make room for a thin new one. This is the single biggest risk in
  the plan and it is exactly what Tier 1's paired draft-vs-revision measurement
  is for. If it fires, the fix is a one-line change to the feedback (issues
  become strictly optional suggestions) or shipping the brief alone.
- **The appendix disturbs the tuned prompt.** 267 lines tuned over weeks, plus
  ~21 new ones at the end. Mitigation: append only, never edit; Tier 0 watches
  search count and token spend for behavioural drift.
- **Reviewer false positives** demanding what the corpus cannot support. The
  feedback says extra searches are optional and unsupported items should be
  narrowed rather than asserted; the `_parse_final_prose` docid check still
  strips any invented citation.
- **Cost/latency.** +2 model calls per topic and one extra revision turn at
  near-peak context. Rough estimate on dev30's ~88K processed tokens/topic:
  +25–35%. Acceptable for 30 topics; noted so the full-test-set run is budgeted
  with eyes open.
- **Deadline.** The mitigation is §6's hard checkpoint: `aus_agent` is the
  submission unless this clears §7's bar by 2026-08-07 evening. Nothing in this
  plan touches `aus_agent`, `agent_harness`, or any shared layer, so the
  fallback is always available and always green.

---

### Critical files for implementation

- `/home/el7/E103037/repos/trec-rag-26/src/systems/aus_agent/agent.py` (the config layer to copy)
- `/home/el7/E103037/repos/trec-rag-26/src/systems/aus_agent/run.py` (the CLI to copy)
- `/home/el7/E103037/repos/trec-rag-26/src/systems/aus_agent/prompts/system/default.md` (byte-copy source)
- `/home/el7/E103037/repos/trec-rag-26/src/systems/facets_agent/agent.py` (worked example: fork-as-configuration + hook wiring)
- `/home/el7/E103037/repos/trec-rag-26/src/systems/facets_agent/review.py` (worked example: a `pre_final_hook`)
- `/home/el7/E103037/repos/trec-rag-26/src/systems/facet_rag/llm.py` (`one_shot`, `strip_fences`)
- `/home/el7/E103037/repos/trec-rag-26/src/systems/facet_rag/planner.py` (defensive JSON-plan parsing to mirror)
- `/home/el7/E103037/repos/trec-rag-26/src/agent_harness/agent.py` (`run_agent` params, `pre_final_hook` at `:750`/`:918`/`:1039`, `_parse_final_prose` at `:200`)
- `/home/el7/E103037/repos/trec-rag-26/src/agent_harness/context.py` (`ContextLedger.call_history` — the reviewer's evidence source)
- `/home/el7/E103037/repos/trec-rag-26/tests/systems/test_facets_agent.py` + `/home/el7/E103037/repos/trec-rag-26/tests/agent_harness_context/test_pre_final_hook.py` (test patterns)
- `/home/el7/E103037/repos/trec-rag-26/tasks/task-comparison/scripts/arena_aus_agent_vs_facets_agent_rubric.py` + `.../rubric_scorecard_aus_agent_vs_facets_agent.py` (generalize with `--challenger-system`)
- `/home/el7/E103037/repos/trec-rag-26/worklogs/assets/2026-08-06-aus-agent-headroom-probe.py` (the §1 evidence, re-runnable)
