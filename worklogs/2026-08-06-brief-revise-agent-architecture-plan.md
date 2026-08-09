# 2026-08-06 — framework research → `gpt-5.6-sol` proposal → review → `brief_revise_agent` PLAN.md

Branch: `explore/new-agent-framework-system` (not `main`). Planning session
only — **no system code written**. Deliverable: `src/systems/brief_revise_agent/PLAN.md`,
to be implemented by a follow-up session. Deadline context: TREC RAG 2026
submission is 2026-08-08, two days out.

## Why this session happened

Two multi-agent decomposition systems in this repo have now lost to the
simplest one:

- `facet_rag` (planner + concurrent per-facet orchestrator/analyzer/curator,
  isolated context per facet) — lost to `aus_agent` on UMBRELA on all 5
  measured topics; root cause "content starvation" from the curator
  (`worklogs/2026-08-05-facet-rag-honest-rebaseline.md`).
- `facets_agent` (one continuous agent, ~80-line prompt asking it to
  self-decompose) — 20-4-6 clean win groups against `aus_agent` on the
  30-topic dev set, 76.7% pooled preference for `aus_agent`
  (`worklogs/2026-08-06-facets-agent-phase4a-dev30-eval.md`), diagnosed
  `not_decomposed` 47.8% / `covered_but_shallow` 47.4%
  (`worklogs/2026-08-06-facets-agent-loss-factor-analysis.md`).

The question for this session: is there an architecture from the open-source
deep-research world that attacks those failures without repeating them.

## Pipeline, in order

1. **Framework research** (earlier task on this branch): LangChain
   `open_deep_research` (supervisor + parallel isolated researchers, LangGraph),
   GPT Researcher (planner → shared draft → editor/reviewer/reviser/writer/
   publisher), ByteDance DeerFlow (stateful supervisor SuperAgent with
   sandbox/memory/MCP).
2. **Context package written for an external model** — the challenge spec, our
   harness constraints, every existing system and its measured outcome, the
   three frameworks, and the ask. Verbatim copy:
   `worklogs/assets/2026-08-06-sol-context-package.md`.
3. **One API call to `gpt-5.6-sol`** (frontier reasoning model, $0.15) with that
   package. Its full response, unedited:
   `worklogs/assets/2026-08-06-sol-architecture-proposal.md` (548 lines).
   Summary of what it proposed: pick GPT Researcher's reviewer/reviser
   *pattern* but vendor nothing; fork the full `aus_agent` prompt rather than
   write a short one; add a requirements analyst before the run and a
   `pre_final_hook` reviewer after the draft; name it `ledger_revise_agent`.
4. **This review** (Opus, grounded against the real repo, not against `sol`'s
   prose description of it) → `src/systems/brief_revise_agent/PLAN.md`.

## What the review actually did

### The evidence `sol` was missing (and the reason the plan survives)

`sol` justified its entire design against `facets_agent`'s loss diagnosis —
but the design forks `aus_agent`, which by construction does not have
`facets_agent`'s failure modes. So before adopting anything I asked the
question nobody in this repo had asked yet: **where does the winner still lose
points?** The per-criterion scorecard from the dev30 arena already existed, so
this cost nothing but a probe script.

Probe (re-runnable, read-only, no API):
`worklogs/assets/2026-08-06-aus-agent-headroom-probe.py`. Sources:
`evaluation-results/arena/aus_agent-vs-facets_agent-dev30-rubric/criterion-scores/`,
the official `research-rubrics-dev-rubrics.jsonl`, and
`data/outputs/aus_agent/*.output.json` at `run_id=aus-agent-dev30-luna-e2708ab`
(gpt-5.6-luna, 30/30 topics). Full output:

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
  Miscellaneous                    n=   1 mean=2.00 pct<=1=0%

worst topics by fraction of positive rubric weight lost:
  0.877 6847465956a0f6376a6054be ncrit=20 implicit_mean=0.14 uncited=21% words=874
  0.858 6847465956a0f6376a6054a7 ncrit=28 implicit_mean=0.47 uncited= 0% words=806
  0.829 683a58c9a7e7fe4e76958498 ncrit=31 implicit_mean=0.41 uncited=13% words=882
  0.798 6847465956a0f6376a605440 ncrit=23 implicit_mean=0.22 uncited= 0% words=326
  0.787 6847465956a0f6376a605492 ncrit=21 implicit_mean=0.62 uncited=29% words=500
  0.758 6847465956a0f6376a6053a0 ncrit=21 implicit_mean=0.25 uncited=67% words=926
  0.725 6847465956a0f6376a6053fb ncrit=28 implicit_mean=0.53 uncited=23% words=937
  0.721 6847465956a0f6376a6053c9 ncrit=29 implicit_mean=0.45 uncited=57% words=962
```

How these were judged: the grades are the existing `gpt-5.6-terra` per-criterion
scorecard pass (0–3 per official criterion), not a new judging run. The
"failure shape" reading of the `Implicit Criteria` zeros is **graded by hand**:
I dumped the highest-weight grade-0 implicit criteria and read them. They are
unglamorous — "defines bonds as loans"; "compares traditional and Roth savings
accounts for the 401k and IRA"; "names the major US stock market indexes (S&P
500, Dow Jones, Nasdaq, Russell 2000)"; "highlights policy or regulatory
responses (Section 230 of the CDA, COPPA, the SAFE act)"; "specifies the
geographical regions under consideration and justifies this selection". Every
one is an obligation a careful reader infers from the request in seconds, and
the writing agent — 200K tokens deep in a search loop — does not.

Three conclusions that changed the plan:

- **`not_decomposed` is the baseline's problem, not `facets_agent`'s.** It just
  got named there first. That retargets `sol`'s requirements analyst from
  "fixes the challenger" to "fixes the champion", which is the difference
  between a speculative and an evidence-backed intervention.
- **26.0% of `aus_agent`'s answer sentences carry no citation** (headings are
  already stripped by `_parse_final_prose`, so these are prose). TREC scores
  weighted citation *recall* over all sentences, uncited = 0. This is a free,
  deterministic, un-argued-about improvement target, and it became the
  review pass's primary preregistered metric.
- **The 1024-word cap is already binding** (median 926, 10/30 above 965), so a
  reviewer that only says "add X" produces an over-length report, which
  `_parse_final_prose` rejects. `sol` missed this. The reviewer contract
  changed from additive to substitutive.

### Mechanical audit of `sol`'s control flow against the real harness

Traced `src/agent_harness/agent.py`, `context.py`, `src/systems/aus_agent/*`,
`src/systems/facets_agent/*`. Five mismatches, none fatal:

1. `pre_final_hook` fires **only on a candidate that already passed**
   `_parse_final_prose` (`agent.py:918`, `:1039`). So `sol`'s §4.1 deterministic
   checklist (word cap, >3 citations, unknown docids, malformed objects,
   reference indices) is already enforced upstream and unreachable. Only the
   uncited-sentence scan is new. → keep one check, drop five.
2. `sol` has the reviewer re-fetch cited documents from the ClimbMix endpoint.
   `ContextLedger.call_history` (`context.py:113-117`) keeps every staged call's
   full-text documents for the run's life and the hook receives the live
   `ledger` (`agent.py:756-763`). → read locally, no network.
3. "Up to two final targeted searches" after the review is **not guaranteed**:
   when `budget_hit or safety_hit`, retrieval calls are refused
   (`agent.py:1215-1240`). All 30 dev30 `aus_agent` runs ended `completed`, so
   it is usually available. → revision feedback must be satisfiable with zero
   new searches.
4. `sol`'s "injected user-side context" block would put the brief in the user
   message; the harness builds that from `query` and records `query` as the
   artifact narrative (`TASK_PROMPT`, `agent.py:83-89`). → brief goes on
   `system_prompt` (already a per-call parameter, zero harness change). `sol`'s
   own pseudocode had this right; its prose contradicted it.
5. `sol`'s output-construction section describes `_map_citations` /
   `build_rag_output` / `validate_rag_output` as they already exist. → no work.

Two facts found that make the build cheaper than `sol` assumed:
`facet_rag/llm.py::one_shot` is exactly the tool-less-call helper both new
stages need, and `facets_agent/agent.py` + `review.py` are a worked example of
a fork-as-configuration system with a `pre_final_hook` wired as a
default kwarg.

### Scope cuts (beyond `sol`'s own stretch list, which I accepted wholesale)

- **`search_policy.py` (`facet_id`/`goal` fields on the search tool) — cut.**
  `facets_agent` already ships this exact instrument (a required `requirement`
  field on every search, PLAN §1.1) and it is measured insufficient. It also
  perturbs the tuned search schema, turning a two-variable experiment against
  `aus_agent` into a three-variable one.
- **Retrieval budget re-spec (14 searches, k≤8, 30–45 docs) — cut.** Never
  retune the winner's knobs inside an architecture experiment.
- **Full-text entailment checking of citations — cut for v1.** It targets
  citation precision; the measured hole is recall.
- **`config.py` — cut.** Nothing to configure that isn't a kwarg.

### Name

`ledger_revise_agent` → **`brief_revise_agent`**. `ledger` is a load-bearing
identifier in shared harness code (`ContextLedger`, `ledger.committed_ids`, and
literally `context["ledger"]` inside the hook this system supplies) where it
means the staged/committed *document* ledger. Reusing it for a requirements list
in the one system that reads both would be a daily confusion. "Brief" names the
pre-flight requirements document; "revise" names the post-draft pass.

## Result: the plan

`src/systems/brief_revise_agent/PLAN.md` — a fork of `aus_agent` (same loop,
same 267-line prompt byte-copied, same engines and budgets) plus exactly two
interventions: a capped requirements brief appended to the system prompt, and a
`pre_final_hook` that runs a deterministic uncited-sentence scan plus one
reviewer call and sends the model back once with substitution-shaped fixes.
**Zero shared-code changes** — `system_prompt`, `system_name` and
`pre_final_hook` are all existing `run_agent` parameters.

Validation reuses the existing arena/scorecard scripts, generalized in place
with `--challenger-system` (~10 lines each) rather than copied. Three tiers:
Tier 0 deterministic and free (uncited rate 26.0% → target <15%, word cap,
status, brief size, hook fire rate); **Tier 1 a free within-run paired A/B** —
the pre-revision draft is preserved in `trace.steps` because `_record_turn`
runs before the hook, so draft-vs-revision can be scored on the official
criteria at zero extra generation cost, which is the only measurement here that
isolates one intervention cleanly; Tier 2 the 30-topic arena vs `aus_agent`
(whose answers already exist), read as clean win groups given the judge's
documented position bias.

Preregistered decision rule: submit the new system only if the uncited rate
improves with nothing else regressing, the paired draft-vs-revision favours the
revision, and clean win groups are ≥12 wins with ≤8 losses. Otherwise
`aus_agent` is the submission — which is the default outcome, and the reason
nothing in the plan touches `aus_agent` or any shared layer.

## Not done this session

- No code, no runs, no API spend beyond the single $0.15 `sol` call.
- No independent re-derivation of the `facets_agent` loss diagnosis — taken as
  given from its worklog; this plan's evidence base is the `aus_agent` probe
  above, which is new.
- The `References & Citation Quality` axis (18 criteria, 100% graded ≤1, mean
  0.11) is noted but **not** designed for: reading them, most demand things a
  ClimbMix-only corpus-cited answer structurally cannot do (APA-formatted
  citations, "cites seminal works Hebb 1949 / Marr 1971", per-blog-post citation
  blocks). Worth a separate look at whether any are reachable; not on the
  critical path at n=18.
- No ablation runs planned (brief-only vs review-only). The kwargs exist to
  make one possible later; there is no time for it before 2026-08-08.
