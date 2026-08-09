## Recommendation: use GPT Researcher’s shared-draft review pattern, not its full runtime

I would choose **B, GPT Researcher’s planner → shared research state → reviewer → reviser pattern**, adapted to the existing harness.

I would **not vendor or integrate the whole GPT Researcher framework in two days**. Its crawling, publishing, and orchestration abstractions duplicate code already working in `agent_harness`, `tools.search_tool`, and `ragrun`. Instead, implement its useful architectural distinction:

- One preliminary **requirements analyst**
- One continuous, evidence-rich **research/writer agent**
- One independent **citation/coverage reviewer**
- One revision by the original agent in its unchanged accumulated context

This should be a new system named, for example:

```text
src/systems/ledger_revise_agent/
```

### Why not A: `open_deep_research`

Its supervisor plus isolated parallel researchers is almost exactly the failed `facet_rag` topology. Even if the supervisor received fuller transcripts, it would still introduce:

- context handoffs,
- per-facet evidence boundaries,
- pressure to summarize before synthesis,
- duplicated searches across isolated workers.

That is the measured source of `facet_rag`’s relevance loss. Fixing A sufficiently would mean removing most of its defining architecture.

### Why not C: DeerFlow

DeerFlow adds state management, sandboxing, memory, MCP, and general-purpose subagents that this task does not need. Integration risk is unjustifiable with a two-day deadline.

### Why B fits the observed failures

B’s valuable feature is not “more agents.” It is that the **reviewer and reviser operate on the same draft**, while research evidence remains available to the writer.

That directly permits:

- a separate analyst to catch `facets_agent`’s **`not_decomposed`** omissions;
- a reviewer to flag **`covered_but_shallow`** prose;
- citation precision and recall checks before accepting the report;
- no curator and no compressed subagent handoff, avoiding `facet_rag`’s **content starvation**.

---

# Proposed system: `ledger_revise_agent`

## Core design principle

Start with the winning `aus_agent` behavior and add only two bounded interventions:

1. An external, structured **coverage ledger** before research.
2. A single **pre-final audit/revision cycle**.

Do **not** replace the long tuned `aus_agent` prompt with another short “please decompose carefully” prompt. That experiment already lost.

Do **not** split research into isolated facet workers.

---

## Components

```text
src/systems/ledger_revise_agent/
├── __init__.py
├── run.py
├── prompts.py
├── requirements.py
├── search_policy.py
├── pre_final_audit.py
└── config.py
```

### `requirements.py`: Requirements Analyst

One non-tool LLM call before `run_agent`.

Input:

- original narrative;
- a tightly specified output schema;
- instructions to identify both explicit and implied answer obligations.

Output:

```json
{
  "facets": [
    {
      "id": "F1",
      "requirement": "Compare implementation costs, not only benefits",
      "origin": "implicit",
      "confidence": "high",
      "priority": "required",
      "specificity_target": [
        "cost driver",
        "implementation mechanism",
        "trade-off or constraint"
      ],
      "query_seeds": [
        "..."
      ]
    }
  ],
  "cross_cutting_requirements": [
    "Distinguish mechanisms from category labels"
  ]
}
```

Hard limits:

- At most 6 facets.
- At most 3 high-confidence implicit requirements.
- Every implicit item must explain what language in the narrative implies it.
- Optional/low-confidence facets cannot consume the run unless evidence appears quickly.

This is specifically intended to prevent `facets_agent`’s `not_decomposed` failures. The main agent is no longer solely responsible for noticing an unnamed compliance, cost, comparison, or operational requirement while simultaneously searching and writing.

The ledger is advisory rather than an outline the final answer must blindly follow. This prevents an overactive planner from forcing irrelevant sections.

### `prompts.py`: Research/writer prompt

Fork the **full `aus_agent` prompt**, preserving its successful retrieval and evidence-handling instructions. Add a focused appendix rather than rewriting it.

The appendix should establish the following completion contract:

1. Every required/high-confidence ledger item must receive at least one targeted search.
2. A facet is not “covered” merely because a category is named.
3. Before marking a facet covered, the agent must have evidence for at least one of:
   - a concrete mechanism or process;
   - a named implementation/entity;
   - a numeric threshold, cost, or measured result;
   - a specific trade-off, failure condition, or constraint.
4. Broad first-pass evidence should trigger a lexical follow-up using terminology found in the documents.
5. Commit all plausibly useful documents. Reject only clearly irrelevant or substantially duplicate material.
6. Do not produce per-facet summaries that replace the underlying documents.
7. Every factual final sentence must have 1–3 citations that jointly support the entire sentence.

The injected user-side context should contain:

```text
ORIGINAL NARRATIVE
...

COVERAGE LEDGER
F1 [required, implicit/high]: ...
Specificity target: ...
Suggested query seeds: ...

The ledger is a search and audit checklist, not a mandatory answer outline.
Amend it if corpus evidence reveals a better interpretation, but do not
silently omit required items.
```

### `search_policy.py`: Tagged search wrapper

Reuse the existing ClimbMix search implementation, but expose an overridden tool schema with two bookkeeping fields:

```json
{
  "engine": "semantic | keyword | ssr | lucene_bool",
  "query": "...",
  "k": 6,
  "facet_id": "F1",
  "goal": "coverage | depth | verification"
}
```

`facet_id` and `goal` are recorded in the trajectory and stripped before calling the existing search endpoint if necessary. No retrieval backend changes are required.

This creates a machine-readable coverage ledger without isolating any context.

---

# Control flow

## Phase 1: requirement expansion

```python
ledger = analyze_requirements(narrative)
```

- One LLM call.
- No search tools.
- Strict JSON parsing.
- If parsing fails, fall back to a ledger containing the narrative’s explicit deliverables only. A planner failure must not block a run.

This call should use the same provider infrastructure already configured in the repo, not introduce another SDK.

## Phase 2: one continuous research run

```python
result = run_agent(
    narrative=narrative,
    system_prompt=build_prompt(AUS_PROMPT, ledger),
    tools=tagged_climbmix_tools,
    pre_final_hook=make_audit_hook(narrative, ledger),
    ...
)
```

The entire research and writing process remains in **one provider conversation**, exactly as in `aus_agent`.

There are no parallel researchers and no per-facet contexts.

### Recommended retrieval schedule

The model retains discretion, but the prompt and ledger impose these bounds.

#### A. Coverage sweep: approximately 4–6 searches

For each required or high-confidence facet:

- one `semantic` query;
- `k=6` or `k=8`;
- query at the facet level, including important narrative terms.

Also allow one broad semantic query over the complete narrative if the facets are highly interdependent.

The purpose is corpus reconnaissance, not final evidence selection.

#### B. Depth follow-ups: approximately 4–6 searches

For the most important facets, follow terminology surfaced in the first pass with:

- `keyword` for exact products, standards, methods, organizations, or technical phrases;
- `ssr` for relationships, mechanisms, comparisons, and proximity-sensitive claims;
- `lucene_bool` only when exact Boolean constraints are clearly useful.

Examples of the intended transition:

```text
Broad result: "Caching reduces repeated computation."
Depth query:   Redis TTL eviction cache invalidation implementation
```

or:

```text
Broad result: "The regime creates compliance costs."
Depth query:   <regime name> reporting audit staffing compliance cost
```

A facet should normally receive a second search when its evidence only supports a category label.

#### C. Gap/verification searches: 0–2 searches

Used when:

- a required ledger item still lacks evidence;
- two documents conflict;
- the candidate answer contains a specific claim for which the supporting document is ambiguous.

### Hard limits

Suggested initial configuration:

- **14 total search calls**
- `k <= 8`
- approximately **30–45 committed documents**, subject to the model context limit
- enough harness rounds for each search/commit pair plus finalization, likely **30–34 rounds**

The exact token cap should match the known-good `aus_agent` configuration. Do not lower it merely to make the new system cheaper; retaining a large evidence pool is one of the baseline’s measured advantages.

### Commit policy

This is deliberately anti-curation:

- Commit a document if it might support a required answer claim, useful comparison, concrete mechanism, or constraint.
- Reject clear noise and near duplicates.
- Do not impose a small per-facet quota.
- Do not convert committed documents into curator summaries.
- Do not delete a document because it has not yet been cited.

This is the primary protection against `facet_rag`’s content starvation.

---

## Phase 3: candidate final report

The main agent writes a candidate report using the existing harness’s cited-prose format.

Writing constraints:

- One factual proposition or tightly related claim cluster per sentence.
- Every factual sentence receives 1–3 citations.
- Headings may be uncited.
- Do not place multiple independently sourced claims in one long sentence.
- Prefer concrete mechanisms and constraints over category-only language.
- Stay safely below 1,024 words, preferably around 750–950 words to leave revision room.

---

## Phase 4: `pre_final_audit.py`

Use the newly shipped `pre_final_hook`.

The hook performs two layers of checking.

### 4.1 Deterministic checks

Parse the candidate and identify:

- factual-looking answer objects with no citations;
- more than 3 citations;
- invalid or unknown docids;
- invalid reference indices;
- word count over 1,024;
- malformed answer objects;
- citations to documents that were never retrieved or fetched.

These checks do not require an LLM.

### 4.2 Independent reviewer call

Make one reviewer LLM call with:

- original narrative;
- coverage ledger;
- candidate answer;
- full text of every cited document, fetched by docid from the ClimbMix endpoint;
- a compact inventory of other committed documents.

The reviewer does not write a replacement answer. It returns structured issues:

```json
{
  "status": "REVISE",
  "issues": [
    {
      "type": "MISSING_REQUIREMENT",
      "facet_id": "F3",
      "sentence": null,
      "detail": "The narrative implies implementation cost analysis, but the answer covers only benefits.",
      "recommended_action": "Search committed evidence or run one targeted cost query."
    },
    {
      "type": "SHALLOW",
      "facet_id": "F2",
      "sentence": 7,
      "detail": "The sentence says 'use caching' although committed evidence identifies Redis TTL and eviction behavior.",
      "recommended_action": "Replace the category label with the evidenced mechanism."
    },
    {
      "type": "BAD_CITATION",
      "sentence": 11,
      "citation": "docid...",
      "detail": "The document supports latency reduction but not the stated 40% figure."
    }
  ]
}
```

Allowed issue types:

- `MISSING_REQUIREMENT`
- `SHALLOW`
- `UNCITED_FACT`
- `BAD_CITATION`
- `PARTIAL_CITATION`
- `OVERBROAD_SENTENCE`
- `CONTRADICTION`
- `WORD_LIMIT`
- `FORMAT`

The citation reviewer must evaluate whether the cited document supports the **whole sentence**, not merely whether it is topically related. That maps directly to weighted citation precision.

Coverage checks map to citation recall and nugget scoring: an uncited or omitted required claim must be flagged, rather than “solved” by simply removing citations.

### 4.3 Revision

If both deterministic and reviewer checks pass, accept the candidate.

Otherwise, the hook sends the issue list back to the **same research agent conversation**. The agent still has:

- all prior searches;
- all committed full documents;
- the original narrative;
- the ledger;
- its own draft.

It may make up to two final targeted searches if a required item is genuinely unsupported, then writes one revised final answer.

The reviewer must not prune documents or rewrite the draft itself. It diagnoses; the evidence-rich main agent revises. This preserves the advantage of the continuous context.

Because the hook only permits one return, the revised final report should receive a final deterministic validation, but not another open-ended review loop.

---

# Stopping conditions

The main agent should finalize when either the evidence conditions are met or the hard budget is reached.

## Evidence-based stopping

Finalize when:

1. Every explicit required facet has at least one usable supporting document.
2. Every high-confidence implicit facet has either:
   - usable evidence, or
   - a recorded determination that it is not actually demanded by the narrative.
3. Every major answer section contains at least one concrete mechanism, named entity, quantitative fact, or specific constraint where the corpus supports one.
4. The last two depth/verification searches produced no new usable evidence, or only duplicates.
5. Every planned factual sentence can be mapped to 1–3 supporting documents.

## Hard stopping

Finalize when any of these is reached:

- 14 search calls;
- harness token budget;
- round cap;
- committed evidence is near the model’s safe context limit.

At the hard stop, omit unsupported optional claims. For a required claim, prefer a narrowly worded, accurately supported statement over an expansive sentence with a topical but incorrect citation.

---

# Output construction

Continue using the existing pipeline:

```python
trajectory = TrajectoryBuilder(...)
rag_output = build_rag_output(...)
validate_rag_output(rag_output)
save_run(...)
```

Recommended behavior:

1. Parse the final report into `answer[]`.
2. Collect cited ClimbMix docids.
3. Deduplicate them in first-citation order into `references[]`.
4. Convert sentence citations to 0-based reference indices, unless the existing system consistently uses direct docids.
5. Run `validate_rag_output`.
6. Verify the aggregate word count using the challenge’s exact `split()` rule.

No extra Publisher LLM is needed. A final formatting model would add another opportunity to alter claims or detach citations from their sentences.

---

# How this addresses the measured failures

## `facet_rag`: content starvation

The proposed system has:

- no isolated researchers;
- no concurrent facet contexts;
- no curator;
- no per-facet evidence quota;
- no summary-only handoff;
- no synthesis agent that sees only subagent prose.

The final writer is the same agent that searched and committed the documents. The reviewer cannot remove evidence. Even if the reviewer sees a compact evidence inventory, its context is not the synthesis context; the revising agent still has the full accumulated conversation.

## `facets_agent`: `not_decomposed`

The facet list is no longer generated opportunistically inside a busy search loop.

A separate requirements call is explicitly tasked with finding:

- implicit comparisons;
- cost and implementation implications;
- compliance or governance requirements;
- constraints and failure modes;
- actor-specific consequences;
- time horizon or geographic distinctions.

Search calls are tagged to ledger entries, so the pre-final hook can detect that a required facet was never searched rather than trusting the model’s self-assessment.

## `facets_agent`: `covered_but_shallow`

A facet does not count as covered merely because one broad search ran.

The system requires:

- a specificity target;
- a lexical or proximity follow-up when first-pass evidence is generic;
- at least one concrete mechanism/entity/number/constraint where available;
- a reviewer issue specifically for category-only statements.

Thus “use caching” is not considered complete if the committed evidence supports “Redis with TTL expiration and eviction behavior.”

---

# Harness decision

## Reuse `agent_harness.run_agent`

Yes. The research core should reuse `run_agent`.

A new facet-style orchestration layer would discard the strongest measured property in the repository: one continuously accumulating conversation with a large evidence pool.

The only wrapper logic needed outside `run_agent` is:

```text
requirements analyst
        ↓
run_agent with aus-derived prompt and tagged tools
        ↓
pre_final_hook reviewer
        ↓
same run_agent conversation revises once
        ↓
ragrun validation/output
```

Technically this is a thin orchestration shell, but it is not a multi-researcher pipeline. All corpus research and synthesis remain inside the existing harness.

---

# Two-day implementation scope

## Required for a submittable v1

1. Fork the `aus_agent` system rather than starting from `facets_agent`.
2. Implement one strict-JSON requirements call.
3. Inject the ledger into the full `aus_agent` prompt.
4. Add `facet_id` and `goal` bookkeeping to the search wrapper if this is straightforward.
5. Implement the `pre_final_hook`.
6. Fetch full text for cited docids during citation review.
7. Add deterministic citation/word-count/output checks.
8. Run a small comparison against `aus_agent` on the known 30-topic set or at least the previously diagnosed failure topics.

## Stretch goals

These should be dropped if they threaten end-to-end reliability:

- automatic passage extraction from all committed documents for the reviewer;
- sentence-level entailment scoring with a separate specialized model;
- adaptive search-budget allocation by facet;
- parallel requirement analysts;
- multiple reviewer/reviser iterations;
- importing GPT Researcher or LangGraph as a dependency;
- learned query generation or reranking;
- cross-topic memory.

## Main risks

1. **Planner over-expansion:** it may invent implicit requirements. Limit implicit facets and require confidence/rationale.
2. **Prompt regression:** additions may disrupt the highly tuned `aus_agent` prompt. Append a short contract; do not rewrite the base.
3. **Reviewer false positives:** the reviewer may demand unsupported additions. Its output is advisory, and required new searches remain capped.
4. **Latency/cost:** this adds two fixed LLM calls plus potentially two searches. Keep only one review iteration.
5. **No second semantic review:** the revised final is accepted after deterministic validation. This is a limitation of the one-return hook and deadline.

Given the baseline’s dominance, I would keep `aus_agent` intact as the fallback submission. The new system should be promoted only if it improves the diagnosed omission/shallow topics without materially reducing relevance on the rest. The safest bet is not a third decomposition architecture; it is **the winning continuous agent plus an independent requirement ledger and one grounded review/revision pass**.