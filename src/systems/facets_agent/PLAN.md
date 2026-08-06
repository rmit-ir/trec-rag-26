# Plan: closing facets_agent's coverage gap with a tool-carried requirement ledger — and a deliberate, guarded licence to search from what the model already knows

**Status: planning only, nothing here implemented yet.** Produced 2026-08-05
by two chained Opus planning passes, grounded in
`worklogs/2026-08-05-facets-agent-strengths-weaknesses-report.md` (the
trajectory/response analysis this plan responds to) and the shared harness
code as it exists on `main` at that date. The first pass designed the
tool-carried requirement ledger; the second pass integrated an explicit,
guarded licence to let the model's own parametric knowledge drive query
formation (never the final answer) after user follow-up. Read the
strengths/weaknesses worklog first if you haven't — this plan assumes its
findings (73% of topics show a search-coverage gap; the extra search volume
facets_agent spends over aus_agent re-confirms facets already found rather
than discovering ones that were missed; `release_committed` was never
invoked in 15 real runs) without re-deriving them.

## 0. Mechanical constraints I verified first (these drive the whole design)

Before designing anything I traced the shared harness loop (`src/systems/aus_agent/agent.py`, lines ~780–1300) and the provider layer. Six facts constrain every option:

1. **A model turn with zero tool calls IS the final report.** `if not calls:` → `_parse_final_prose(...)`. Any "review turn" that emits plain text and no tool call will be parsed as a final answer, fail validation, and cost a turn plus an injected correction message (`agent.py:~1000`). A natural-language review pass cannot be its own turn.
2. **A tool name the loop doesn't know crashes the run.** Dispatch is by name into three buckets (`commit_context` / `search` / `get_documents`); `result_by_id` is then indexed for *every* call (`provider.add_tool_results([result_by_id[call["id"]] for call in calls])`). An unhandled name raises `KeyError`, caught by the outer `except`, and the run is saved as `status="failed"`. **A new tool = a real harness change**, not a config change.
3. **Unknown tool *arguments* are silently ignored and recorded verbatim.** `execute_full_text_search` reads only `query`/`search_engine`/`k`/`budget_tokens_per_result`; `apply_commit` reads only `documents`/`release`. Extra properties cost nothing, cannot fail a call, and land in `output.json` (`trace.steps[].arguments` — re-confirmed against a real artifact: a `search` step records `{"query": ..., "k": 15, "search_engine": "hybrid", "budget_tokens_per_result": 2500}`). **Extending a tool schema is free, safe, and self-instrumenting.**
4. **`commit_context` is already override-able; `search` is not.** `run_agent` takes `commit_context_tool=` but builds `build_search_tool_def(engines)` internally (`agent.py:~779`). Touching the search schema needs one new parameter, mirroring exactly how `commit_context_tool` was added.
5. **Tools are not sent in OpenAI strict mode** (`providers/openai.py:115` passes `parameters` with no `strict`), so adding a `required` property carries no schema-validation risk — only model-compliance risk, and compliance today is perfect (0 failed calls, 0 protocol violations).
6. **The citation contract is enforced *per citation*, not *per sentence* — and this is the hole the new prior-knowledge licence has to be designed around.** In `_parse_final_prose` (`agent.py:~230–335`): a docid that was never committed is silently **dropped** from the sentence (recorded as a repair, never bounced back); more than three citations are trimmed; the report is **rejected only if *no* sentence anywhere carries a citation** (or it is empty / over-length). So a sentence with zero citations is legal, and an invented docid degrades to a zero-citation sentence rather than to an error. Measured on the existing 15-topic run: **29 of 354 answer sentences (8.2%) carry no citation at all**, with `report_repairs` empty (0 invented docids) — and the uncited sentences are concentrated in exactly the counterfactual topic the diagnosis flagged (`605476`: 12 of 21 sentences uncited). The harness therefore *cannot* stop parametric knowledge from entering the answer; it can only stop it from being falsely attributed. Any design that widens the model's licence to use prior knowledge must aim its safeguard at the uncited-sentence channel, and must measure it.

Also relevant: in the real artifacts the model fires **4–6 parallel searches on turn 1** with a ~4-sentence reasoning summary as its entire "decomposition". The plan exists only inside lossy reasoning summaries — it is never serialized, never re-read, never auditable. That is the root of the 73% failure mode: *an unwritten plan cannot be checked, by the model or by us.*

And one fact about the failure's *content*, which the second half of this plan turns on: the LLM diagnosis of the coverage gap does not just say "a requirement was missed" — it names the specific missing things, and they are overwhelmingly **named entities a strong model knows from pretraining**. Straight from `worklogs/assets/2026-08-05-llm-diagnosis-results.json`: "no targeted query for … Indian-derived features such as **chhatris**" (605367); "no targeted queries for **Hidden Path Entertainment**, Counter-Strike 1.6/Source, LAN culture" (605404); "no targeted searches for concrete partners such as **Indomaret, GrabFood**" (605391); "no targeted queries for animalism/**Olson**, **Locke**" (60547f); "never for a single named technique (**SHAP, LIME**, feature attribution)" (60535d). The diagnosing model produced those names from its own weights, unprompted, from the same request text. The searching model almost certainly had them too. Nothing in facets_agent's prompt told it that using them was allowed, let alone expected — the one line on the subject ("Prior knowledge may shape how you search and read, but it must never support a factual claim", `prompts.py:34`) reads as a restriction, not a licence.

---

## 1. Centerpiece: the requirement ledger, carried on tool calls — plus a licence to seed queries from what the model knows

**The design in one line:** make the plan a *written artifact carried in tool arguments* — a `requirement` label on every `search`, and a full `coverage` ledger on every `commit_context` — so the self-review is a per-call and per-turn forcing function rather than a separate step that the harness's turn protocol cannot host; and separately, make the model's own knowledge an explicitly permitted, actively encouraged source of **query terms**, while the ledger and the citation contract keep it out of the **answer**.

The two halves attack the same 73% failure from opposite ends. The ledger fixes *which requirements get searched at all*. The prior-knowledge licence fixes *whether the queries for a requirement are specific enough to hit anything* — the 605391/605404/60535d class, where the requirement was arguably in scope but every query for it stayed at the thematic level. They are complementary, independently revertable, and independently measurable (§5).

This answers the user's "before or after searching?" question with **both, at no extra turns**: the search-side field is the *before* check (per query), the commit-side ledger is the *after* check (per batch), and because `commit_context` is by protocol always within one or two turns of the report, the last ledger *is* the pre-finalization coverage check the report asked for (recommendation 2).

### 1.1 Instrument A — `requirement` on `search` (the plan-review, per query)

New **required** string property on facets_agent's own search tool definition:

```
requirement (string, required)
  "The requirement from the request that this query serves, quoted or
   paraphrased in the request's own words — not a description of the query.
   Name the requirement, not your hunch about the answer: if you are
   searching for a specific name you expect to be relevant, that name goes
   in `query`; the requirement is still the thing in the request the name
   would serve.
   Asking the same requirement on semantic, keyword and hybrid is expected:
   that is one requirement approached from three angles. If this requirement
   already has committed evidence, do not restate it — say instead what is
   specifically still missing from it that this query goes after. If you
   cannot name either, the call is a re-search: spend it on a requirement
   that has no evidence yet."
```

What it does:

- **Coverage (the 73% failure).** The model cannot fire a search without binding it to a requirement *stated in the request*. That is the aus_agent §0 discipline ("every requirement the request states") compressed into a per-call serialization bottleneck, and applied on turn 1 — before any budget is spent — which is exactly where the report says the failure happens. Crucially, the request text is the anchor, not the model's own facet names; the 6054a7 failure was that "Ontario eligibility criteria" was never *named*, and a field that demands the request's own words makes naming it the path of least resistance.
- **Redundancy (recommendation 3).** The "already covered → name the gap" clause is the Pi-search `reason` idea, sharpened. A generic `reason` would mostly restate the query in prose (my read: it would help redundancy a little and coverage almost not at all, because nothing in it points back at the *request*). Binding the reason to a requirement label is what makes it a coverage instrument as well as a redundancy brake.
- **Measurement, for free.** Every search in every trajectory now carries a join key. `searches per distinct requirement` becomes a deterministic trace metric with hundreds of data points per 15-topic batch — see §5, where this replaces the noisy arena as the primary decision metric.

**Interaction with the prior-knowledge licence — explicitly orthogonal, and the second paragraph of the field description is what keeps it that way.** The two fields answer different questions:

| | answers | anchored to | may contain a name the request never used? |
|---|---|---|---|
| `requirement` | **why** this call exists / what it is for | the **request's own wording** | **No.** A candidate name in this field is a hunch dressed as a requirement. |
| `query` | **how** you are asking the corpus for it | whatever will actually retrieve | **Yes — encouraged.** This is where parametric knowledge belongs. |

So knowing the answer changes the *query terms*, never the *requirement label*. Three concrete reasons this separation is load-bearing rather than pedantic:

1. **It protects the join key.** `searches per distinct requirement` (§5 Tier 1 #2) only works if requirement strings are stable across a topic's searches. If the label absorbed the candidate, one requirement searched three ways ("Indomaret", "GrabFood", "Indonesian modern-trade partners") would count as three requirements and the metric would report *improved* decomposition for what is actually one requirement approached three ways — the exact self-flattering artifact the plan exists to avoid.
2. **It prevents requirement laundering.** A ledger entry is a claim about *what the request demands*. If the model may write `requirement: "Hidden Path Entertainment's role in CS:GO development"` for a request that only asked about the game's development history, then it can later mark that entry `covered` and consider a demand satisfied that the request never made — while the real, broader requirement quietly stays unenumerated.
3. **It makes the candidate falsifiable.** With the requirement stated in the request's words, a search that found nothing about the candidate leaves the requirement legitimately `open` and the model must try another angle. If the candidate *were* the requirement, "nothing found" would push a *request* requirement to `unavailable` on the strength of one guess being wrong.

The one place they touch is the "already covered → name what's missing" clause, which reads naturally with candidates: *"has the market-entry-partners requirement, but nothing committed names an actual distributor — going after named Indonesian modern-trade chains."* That is the intended shape, and it is exactly the sentence that would have produced the Indomaret query.

Does *not* break what works: the multi-engine-per-facet behaviour (96/91/92 split) is explicitly blessed in the field description; nothing touches the HyDE hybrid instruction or `k`.

### 1.2 Instrument B — `coverage` + `ready_to_report` on `commit_context` (the coverage self-check, per batch)

facets_agent already owns its `commit_context` schema (`tools.py`), so this is **zero harness change**. Two additions:

```
coverage (array, required)
  "Your full requirement ledger, restated every time. One entry per
   requirement the request states, explicit or implied — a named comparison,
   a stated audience or scope, a demanded structure, a concrete deliverable.
   Restate the whole list, not just what changed: this is the list your
   report will be checked against."
  items: {
    requirement (string) — the requirement in the request's own words, worded
      identically to the `requirement` you use on searches for it.
    status (enum: covered | open | unavailable)
      covered — committed evidence supports it now. Note that evidence
        CONTRADICTING what you expected still makes it covered: the answer
        states what the corpus says, not what you assumed.
      open — nothing committed yet, and the corpus has not been asked properly.
      unavailable — searched on more than one engine and the corpus does not
        have it; say so in the answer rather than pretending it is covered.
        This includes the case where you searched for a specific name, work,
        technique or event you were confident about and the corpus does not
        carry it: that requirement is `unavailable`, not `covered`, and the
        thing you expected does not enter the report.
    note (string) — for covered: the committed ids that carry it. For open:
      the next query you will run for it. For unavailable: the specific terms
      and names you searched, spelled out — this is the record of what the
      corpus was actually asked.
  }

ready_to_report (boolean, required)
  "True only when no entry is `open`. While any entry is open you have
   searches left to run, however much you have already found for the rest."
```

**Why the enum stays at three values (the question worth answering explicitly).** The obvious extension is to split expectation-relative outcomes: `confirmed` / `contradicted` / `nothing-either-way`. I considered it and reject two of the three:

- **`confirmed` vs `contradicted` — rejected.** Both mean *committed evidence exists and the answer will state what it says*. The downstream behaviour is identical, so the split adds an enum branch with no consequent, and worse, it re-centres the ledger on the model's *beliefs* rather than on the *request's demands* — which is precisely the drift §1.1 spends three paragraphs preventing. The genuine need behind that split is real but belongs elsewhere: it is a *reading* discipline ("write what the document says, not what you expected"), so it goes in the step-5 self-check (§1.3) and in a one-clause note under `covered`, not in the enum.
- **`nothing-either-way` — accepted, but it is already `unavailable`.** This is the case that matters most under the new licence and it needed sharpening, not a new value. The failure to prevent is: model writes a query from a confident belief → corpus returns nothing usable → belief nonetheless appears in the report, uncited, because the model "knows" it. Under the sharpened definition that requirement is `unavailable`, and `unavailable` has a stated consequence for the answer. The `note` requirement ("the specific terms and names you searched, spelled out") is what turns this from an exhortation into something checkable: it puts the candidate name in the trace, so §5's leak check is a string match between `unavailable` notes and the final answer text. That one wording change buys a deterministic, zero-cost integrity metric.

Where this sits in the loop, concretely (turn-by-turn, honouring the staged/commit protocol exactly):

| turn | model emits | ledger role |
|---|---|---|
| 1 | 3–6 `search` calls, each with `requirement` | plan is written down, per query, before budget is spent |
| 2 | `commit_context(documents, coverage, ready_to_report)` + next `search` calls | **first full enumeration**; every open item is a search target for this same turn |
| 3..N | same shape | ledger is restated and revised each round — this is aus_agent's "Decide" step, made explicit and auditable |
| N | last `commit_context` — `ready_to_report: true` | **this is the pre-finalization coverage check**; by protocol it is ≤2 turns before the report |
| N+1 | no tool calls → report | writes against a ledger it just restated in its own history |

Nothing about the one-batch-per-turn protocol changes, no turn is added, no tool is added. The check rides on a call the model already has to make.

Honest cost accounting: a ~15-entry ledger is ~350–450 output tokens, restated ~3.6 times per topic and re-read on subsequent turns — roughly **+8–12K processed tokens/topic against a 195K baseline (~5%)**. The change is designed to *pay for itself* by cutting searches (18.6 → target ≤14); if searches don't fall, the ledger is a net cost and §5's gate says so.

Safety property worth stating explicitly: because `apply_commit` ignores unknown arguments (§0.3), a call that omits or malforms `coverage` **cannot fail the run**. The schema is a forcing function, never a failure mode. Non-compliance shows up as a missing field in the trace, which is exactly what §5 measures.

### 1.3 The prompt edits that bind the instruments (net +17 lines in phase 1, +14 steady-state)

Mechanics live in tool descriptions; *judgment* lives in the prompt. Concretely, in `src/systems/facets_agent/prompts.py`:

**Opening paragraph — replace the prior-knowledge line** (`+3 lines`). This is the deliberate divergence from aus_agent (justified below). Today (`prompts.py:34–35`): *"Prior knowledge may shape how you search and read, but it must never support a factual claim in your answer."* Proposed:

> Prior knowledge is your best source of QUERIES and never a source of CLAIMS. If you already know names, works, people, events, techniques, or products that a requirement probably involves, search for them by name — do not wait for the corpus to volunteer them, and do not confine your queries to the request's own vocabulary. What you know decides what you look for; only what you commit decides what you may assert. When the corpus turns out not to hold something you were confident about, that is a finding about the corpus, not a licence to assert it anyway.

Four sentences, and each does one job: permission, encouragement (the imperative "search for them by name" — a mere permission would be read as a hedge), the separating principle stated as a pair, and the disconfirmation case, which is the whole safeguard in one line. The reason the last sentence has to be *here*, in the same breath as the permission, rather than in a distant "be careful" paragraph: the failure mode isn't the model reading the constraint and ignoring it — it's the model never connecting the constraint to this specific permission at report-writing time, hundreds of thousands of tokens later.

**Step 1 — replace** (`+5 lines`). Today: "Decompose the request into a small set of independent facets…". Proposed:

> 1. Before searching, list every requirement the request states — each explicit instruction and each one it implies (a named comparison, a stated audience or scope, a demanded structure, a concrete deliverable). Take them one at a time, in the request's own words. Then group them into facets: distinct sub-questions that each need their own evidence, where every requirement on your list belongs to a facet. A requirement no facet covers gets no searches and will be missing from your answer. A narrow question may be one requirement and one facet; a multi-part request usually has many of both. Work the facets as separate research tasks: search, curate, and judge coverage one facet at a time.

The load-bearing sentence is the third-last one — it names the actual failure mode as a consequence, which is the shortest form of the aus_agent §0 discipline that still bites. Note the deliberate restraint: step 1 stays in the request's own words even under the new licence. Enumeration is a request-reading task; candidate generation is a query-writing task, and it happens one step later.

**Step 2 — append the named-candidates clause** (`+3 lines`; this supersedes and subsumes the original plan's recommendation-5 clause, and is where the parametric licence becomes an operation):

> When a requirement asks for concrete specifics — named partners, products, tools, techniques, works, people, events — write one query naming your own best candidates and one query for the category around them, so the corpus can both test the candidates you brought and offer ones you did not think of. `keyword` is the engine for a named candidate; `semantic` or `hybrid` for the category. A candidate you supplied is a hypothesis to test, not a finding: the query is where it belongs, the report is not.

Three things are deliberate here.

*The paired query is the confirmation-bias control, not a nicety.* A named query alone can only tell you whether the corpus mentions your candidate; run beside a category query it also tells you what else the corpus offers for the same requirement, so the candidate competes rather than anchors. facets_agent already searches every facet on multiple engines (the 96/91/92 split), so this costs nothing new — it *specialises* a behaviour the system already exhibits.

*The engine assignment is not decoration.* The shared tool description sells `keyword` as "hosted BM25, bag-of-words OR … rare proper names, IDs, and verbatim strings" (`src/tools/search_tool.py:56–60`). A query set containing no names the request didn't supply structurally underuses one of three engines — the model is paying for a proper-noun retriever and feeding it thematic phrases. This clause is what gives the keyword engine something to do.

*"the query is where it belongs, the report is not"* restates the separating principle at the point of temptation, which is where prompt sentences actually work.

**Step 3 — trim** (`−3 lines`). The release mechanic is currently explained at length in the prompt *and* verbatim again in `tools.py`'s schema. Cut the prompt to the judgment ("keep the better one and release the one it replaces") and let the tool description carry the mechanics. This partly pays for the additions and is the same principle as §1.2.

**Step 4 — rewrite for a checkable stop condition** (`+2 lines`). Today's "until genuinely covered, or further search stops helping" is unfalsifiable — this is where the Pi-search "explicit stop condition" idea genuinely transfers:

> 4. A facet is done when every requirement in it is `covered` or `unavailable` in your ledger. Do not search again for a requirement that already has its evidence — spend that call on one that has none. Write the report only when no requirement is still `open`.

**Step 5 — extend the existing self-check** (`+4 lines`): keep the citation check, prepend the coverage check, append the expectation check:

> Before you write the report, read your own ledger back: every requirement, and the committed ids that support it. If one is still `open` and the corpus has not properly been asked, run one more targeted search for exactly that, then finish. Where a query came from something you already knew, check that the committed document says what you are attributing to it — not what you expected it to say — and that anything you expected but never found is either absent from the report or named as something the corpus does not cover.

**Final-report paragraph — two appends** (`+4 lines`).

Structure-is-a-requirement (recommendation 4, `+2`):

> When the request names a shape — a section per item, an ordered plan to act on, a notation, a stated audience — the report must literally take that shape, not merely cover the content it asked about; the shape is a requirement like any other and belongs in your ledger.

Citation discipline aimed at the uncited-sentence channel (`+2`, the safeguard's last line of defence, motivated by §0.6):

> Every sentence that states a fact, a name, a number, an event, or a mechanism ends with its committed ids. The only sentences without ids are the ones that organise or connect what the cited sentences already established — a heading, a transition, a conclusion drawn from cited material. A sentence with no ids may never introduce something new.

That last clause is calibrated, not blanket. A blanket "no uncited sentences" would break the legitimate 8.2%: headings ("Post 1: Start With the Goal"), and the synthesis and directive sentences that the repo's own aus_agent prompt explicitly protects ("Being evidence-grounded constrains what you may assert, not how well you may write"). The rule as written keeps structural and connective sentences legal while closing the one channel that matters — *new content* arriving without support. It also gives §5 a metric with a real baseline (8.2%, and the specific outlier at 605476: 12/21) rather than an aspiration.

**Why this is a named divergence from aus_agent, not an oversight.** aus_agent's `prompts/system/default.md:72–80` is unambiguous and deliberate: *"Round one's queries come from the question: build them only from the question's own wording … Do not seed a query with candidate answers — specific names, techniques, causes, examples — that the question itself does not mention: you do not know what this corpus holds until it answers, no matter how well you know the subject … prior knowledge may rephrase, disambiguate, and supply synonyms — it may never introduce a candidate the corpus has not yet surfaced."* facets_agent will now say close to the opposite. That has to be a decision with reasons, written into the module docstring so nobody "fixes" it later:

1. **The two systems fail in opposite directions, and aus_agent's rule is a precision instrument aimed at facets_agent's *non*-problem.** The rule protects against false positives: asserting specifics the corpus never supported. facets_agent's measured failure is false negatives — 11/15 topics where entire requirements got zero queries, and where the diagnosis names concrete entities (§0) the corpus plausibly holds. On the one axis aus_agent's rule protects, facets_agent's current numbers are clean: 0 protocol violations, 0 invented-docid repairs across 354 sentences. Importing a precision constraint into a system whose deficit is recall is the wrong trade, and it is the trade that a "make facets_agent more like aus_agent" instinct would silently make. The systems exist as separate systems precisely to occupy different points here.
2. **The stated rationale — "you do not know what this corpus holds" — argues for *asking*, not for *not asking*.** A named query is the cheapest possible probe of what the corpus holds, and this harness makes probes cheap on purpose (the shared search description: *"extra queries are cheap — cover an important facet with more than one query"*). Under aus_agent's rule the only way to discover that ClimbMix has a page on Hidden Path Entertainment is for a thematic query to happen to surface it; under this rule you ask, and the corpus answers in one call. What "not knowing what the corpus holds" genuinely forbids is *assuming the answer*, and that is forbidden here too, in three places (opening paragraph, step 2's "hypothesis to test", step 5's expectation check).
3. **The risk aus_agent's rule mitigates by prose, this harness mitigates by machine — partially, and I am specific about the part it doesn't.** Hallucination laundering requires attributing a claim to a document. `_parse_final_prose` strips any docid not in `committed_ids` (§0.6), so a fabricated attribution cannot survive; it degrades to an uncited sentence. That is a *mechanical* guarantee that aus_agent's prompt rule restates in prose. The residual risk is real and I name it rather than wave at it: the uncited-sentence channel, which the harness permits by design. So the safeguard is aimed there — prompt-side by the final-report clause above and step 5, ledger-side by the sharpened `unavailable` semantics, and measurement-side by three preregistered metrics (§5 Tier 1 #8, #9 and Tier 2's leak check), one of which already has a v1 baseline (8.2%) so a regression is visible on the first A/B rather than after it ships.
4. **The condition under which the relaxation is valid, stated as a testable invariant:** *a candidate may enter `query`; it may never enter `requirement`, `coverage[].requirement`, or an answer sentence unless a committed document carries it.* Every mechanism in this plan enforces one clause of that sentence, and §5 measures all three clauses. If measurement shows the invariant breaking — parametric-seeded queries up *and* uncited-sentence rate up *and* leaked `unavailable` candidates > 0 — the relaxation is wrong for this model and reverts as one prompt paragraph, with aus_agent's rule available as the fallback wording.
5. **A useful by-product for the repo's actual research question.** The two systems are compared head-to-head constantly here. After this change they differ on a *named, single-sentence axis* rather than only on "long prompt vs short prompt", which makes the comparison say something transferable about whether corpus-first querying is the right default.

**Prompt budget.** 62 → ~82 lines in phase 1, returning to **~79** in phase 2 when step 2's mechanics sentence ("`keyword` is the engine for a named candidate; `semantic` or `hybrid` for the category") migrates into the search tool's `query` description — which facets_agent will own anyway once §3's `search_tool_def` lands, and which is the same prompt/schema split principle as §1.2 and the step-3 trim. I keep the original's explicit hard cap of **80 lines**, written into the module docstring, with the phase-1 overshoot flagged in the worklog as temporary and time-boxed to one phase: past 80, a change must either cut something or move into a tool description. facets_agent's selling point is a short prompt against aus_agent's 267 — 79 keeps a 3.4x ratio and keeps the claim honest. The reason this doesn't drift into aus_agent-by-instalments is the split: the *discipline* (~17 prompt lines) is separated from the *bookkeeping* (~25 lines of schema in `tools.py`), and schema text is per-tool, local, mechanically enforced, and not what "minimal prompt" was ever measuring.

### 1.4 Alternatives considered and rejected

**(a) A dedicated `review_plan` / `coverage_check` tool, called before finalizing.** The cleanest-sounding option, rejected on three independent grounds. (i) It is a *real harness change* — new dispatch branch, new result envelope, `tool_definitions` list plumbing — in 1,349 lines of shared, heavily-tested state machine that aus_agent also depends on (§0.2). (ii) It burns a whole model turn at near-peak context: at ~195K processed tokens over ~8.5 turns, a dedicated review turn costs on the order of 20–30K processed tokens, directly fighting recommendation 3. (iii) The killer: **a review turn issued while a batch is staged silently expires that batch.** A turn without exactly one `commit_context` is treated as reject-all (`agent.py:~845`). The model would have to know whether a batch is open before deciding whether it may review — a protocol invariant it cannot track reliably, and getting it wrong throws away a full search round. Carrying the review on `commit_context` makes that hazard structurally impossible.

**(b) A natural-language self-review turn ("write your plan as plain text, then continue").** Rejected outright by §0.1: a text-only turn is parsed as the final report, gets rejected by `_parse_final_prose`, and consumes a turn plus a correction message. Worse, telling this model to narrate its process risks the one thing the report confirms is clean today — zero Markdown/narration leakage into the final answer. Not worth trading a confirmed strength for an unverifiable one.

**(c) A one-shot `plan` array on the first search call only.** Cheaper than the ledger, but rejected: the first turn fires 4–6 parallel searches, so which call carries the plan is arbitrary; the plan is then never revised as retrieval teaches what the corpus actually holds (aus_agent's "Decide" step exists precisely for that); and it provides no pre-finalization checkpoint, so it solves half of recommendation 1 and none of recommendation 2.

**(d) A generic Pi-style `reason` on every call, instead of `requirement`.** Rejected as *insufficient*, not wrong. A free-form reason mostly restates the query; it would trim some redundancy and would not close the coverage gap, because nothing in it forces a return to the request's own text. The `requirement` field is the same forcing function pointed at the actual failure mode, and it doubles as a join key for measurement. (The Pi "under 100 words / be specific" framing is worth keeping in the field description's tone.)

**(e) A `SUBMIT_NOW`-style steer.** Not needed: the harness already implements exactly this. When the budget or round cap is hit it sets `finishing`, refuses further searches with an explicit "write the final report now" envelope, and `apply_commit` injects the same instruction. Adding a prompt analogue would duplicate live harness behaviour. Worth noting in the worklog, not building.

**(f) [new] A `candidate_source: request | corpus | prior_knowledge` enum on `search`, to label query provenance declaratively.** Tempting — it would make §5's parametric-seeded-query metric exact instead of inferred. Rejected on cost/benefit: it is a second required field on the same call as `requirement`, doubling the per-search compliance surface at the moment the plan is already spending its compliance budget on the field that matters; self-reported provenance is exactly the kind of label a model rationalises after the fact; and the metric is recoverable from the trace without it, since `trajectory.json`'s `raw_messages` carry both every query and every returned passage in order, so "term appears in neither the request nor any earlier result" is computable post hoc (I prototyped it read-only — §5 Tier 1 #7, 28.0% baseline). Free measurement beats a declared label that costs compliance.

**(g) [new] Requiring the parametric candidate to be searched *only after* a thematic query for the same requirement has come back empty.** This is the conservative middle path between aus_agent's rule and this plan, and it is the one I most seriously considered. Rejected: it costs a full round-trip per candidate at the point in the run where budget is scarcest, it re-introduces exactly the "wait for the corpus to volunteer it" latency that produced the misses, and the model would have to track per-requirement query history across turns to apply it — the same unreliable protocol bookkeeping that sank option (a). The paired named+category query in step 2 gets the same anti-anchoring benefit *within one turn* and at no sequencing cost.

---

## 2. The remaining findings, prioritized

| # | Finding (evidence) | Change | Scope | Prompt-minimality risk |
|---|---|---|---|---|
| 1 | coverage gap, 11/15 topics | `requirement` on `search` + `coverage` ledger on `commit_context` + step-1/4/5 rewrite. **Row 7 attacks the same finding from the query-specificity side**; they are separately measurable and separately revertable | `tools.py` (both schemas), `prompts.py`, `agent.py` (pass the new def), **1 harness param** | +11 prompt lines; bookkeeping lives in schemas — acceptable |
| 2 | pre-final check (report rec 2) | falls out of #1: the last `commit_context` ledger + step 5 | same edits | +3 lines |
| 3 | redundant re-search, 39-search topic | `requirement`'s "name the gap" clause + step 4's checkable stop condition | `tools.py`, `prompts.py` | +2 lines |
| 4 | `synthesis_organization`, 3/15 | structure-is-a-requirement clause; structure enters the ledger | `prompts.py` only | +2 lines |
| 5 | `under_specified_or_thin`, 1/15 (605391: no named partners) — **re-scoped**: this is not a one-topic wording nudge but the visible tip of row 7. The original "aim a query at surfacing names" clause is now step 2's named-candidates clause, which additionally says *where the names come from* (the model's own knowledge) — the missing half, since telling a model to "surface names" while its only stated licence is "prior knowledge must never support a claim" reads as an instruction to hope the corpus offers them | superseded by row 7's step-2 clause | `prompts.py` (phase 1), later the `query` description | +0 beyond row 7 |
| 6 | `release` used 0 times | **do not change the prompt yet** — instrument instead | measurement only | none |
| **7** | **[new] Missed requirements are disproportionately named entities the model knows but never searched — chhatris (605367), Hidden Path (605404), Indomaret/GrabFood (605391), Olson/Locke (60547f), SHAP/LIME (60535d), all named by the diagnosis LLM from the same request text.** Current prompt's only statement on prior knowledge (`prompts.py:34`) reads as a prohibition | Rewrite the opening prior-knowledge line into an active licence + step 2's paired named-candidate/category clause + engine assignment (`keyword` for names). **Named divergence from aus_agent's round-one rule**, justified in the module docstring | `prompts.py` (phase 1); step 2's mechanics sentence migrates to the `query` description in phase 2 | +6 prompt lines; net +3 after the phase-2 migration |
| **8** | **[new] Safeguard for #7: the harness cannot stop parametric assertion, only false attribution.** Uncommitted docids are stripped, not rejected; a report is refused only if *no* sentence cites anything (`agent.py:~230–335`). v1 already runs 8.2% uncited sentences (29/354), 12/21 on 605476 | Sharpened `unavailable` semantics + its "name the terms you searched" note contract (§1.2) + step-5 expectation check + final-report "a sentence with no ids may never introduce something new". Measured by Tier 1 #8/#9 and the Tier 2 leak check | `tools.py` (enum/note text), `prompts.py` | +4 prompt lines; all four are the cost of shipping #7 responsibly |

On **#6**, I'd push back slightly on the report's own recommendation. Building an adversarial topic is real work for a question that change #1 answers for free: the `requirement` field's "if it already has committed evidence, say what is still missing" clause *is* the missing trigger cue — it makes the model compare a new result against what it already holds for that requirement on every single call, which is precisely the "found something better" moment reading 1 says never arrives. Change #7 pushes in the same direction for a second reason: a named-candidate query is the most likely way to retrieve a *sharper* document on a point that already has a vague one, which is the textbook release trigger. So: ship #1 and #7, read `release` counts off the same A/B trace analysis (already computed by the existing behaviour-analysis script), and only build the adversarial topic if release is still 0. If it moves off 0, reading 1 was right and no further work is needed; if it stays 0 while distinct-requirement coverage goes *up*, reading 2 is falsified too and the honest conclusion is that the scenario is rare — leave it as-is and say so.

---

## 3. Harness changes required (explicitly, per the extensibility note)

**Required, one parameter — `search_tool_def` on `aus_agent.agent.run_agent`.** Confirmed current code builds it internally at `agent.py:~779`; there is no override. The change mirrors `commit_context_tool` line for line:

- signature: `search_tool_def: dict[str, Any] | None = None`
- body: `tool_definitions = [search_tool_def or build_search_tool_def(engines), GET_DOCUMENTS_TOOL, commit_context_tool or COMMIT_CONTEXT_TOOL]`
- docstring: one paragraph in the same style as the existing `commit_context_tool` paragraph, including the caveat below.
- **Caveat to document:** unlike `commit_context_tool`, the search def is *engine-dependent* — the `search_engine` enum and the query guidance are derived from `engines` (`src/tools/search_tool.py:169–205`), and `engines` is separately used in `execute_full_text_search`'s error path. A caller passing a def built for a different engine set would desync the two. So facets_agent's `tools.py` must expose a **function** `build_search_tool_def(engines)` (wrapping `aus_agent.tools.search.build_search_tool_def(engines)`, adding the `requirement` property, and — in phase 2 — appending the named-candidate sentence to the `query` description), called from `facets_agent.agent.run_agent` where `engines` is already resolved at line 126 — not a module-level constant like `COMMIT_CONTEXT_TOOL`. Add one test asserting the enum in the advertised def matches the run's engines. Note the phase-2 migration has an engine dependency of its own: the "keyword for a named candidate" sentence is only true when `keyword` is in `engines`, so the wrapper must condition that clause on the enabled set exactly as the shared builder conditions its own multi-engine sentence.
- aus_agent behaviour must be byte-identical when the param is absent; the existing 293-case systems suite is the proof, same bar as the `release` work. This matters doubly now: aus_agent's round-one anti-seeding rule stays exactly as it is, and the divergence must be visible only to facets_agent's model.

**Not required (deferred, spec'd only) — a pre-final coverage gate.** If measurement shows the model setting `ready_to_report: true` while entries are still `open` (the inconsistency §1.2's boolean exists to detect), add a hook to the `if not calls:` branch: on the *first* final-report attempt, if the last-seen `coverage` payload has open entries, inject a user message naming them and `continue` — reusing the exact pattern already there for rejected reports (`provider.add_user_message(feedback)`). Fire at most once per run so it cannot loop. Shape it as a generic `pre_final_hook: Callable[[dict], str | None] | None = None` so it stays system-agnostic in shared code. **Do not build this in phase 1** — it is the most invasive change on the list, and phases 1–2 may make it unnecessary. If it is ever built, the same hook is the natural home for the second gate the safeguard would want (an `unavailable` candidate name appearing in the drafted report text), but that is speculative until Tier 1 #9 shows a nonzero leak rate.

Everything else is `prompts.py` + `tools.py` + a 3-line change in `facets_agent/agent.py` (line 126–134's `_run_agent` call gains `search_tool_def=build_search_tool_def(engines)`). `run.py` needs nothing.

---

## 4. Sequencing

- **Phase 0 — measurement baseline (free, no API).** Generalize the report's trajectory script into a reusable `requirement-coverage` analyzer keyed on the new fields, and run it on the *existing* `facets-agent-15topic` batch so v1 numbers are computed by the same code path as v2's (v1 simply has zero labelled searches; the searches-per-topic, processed-tokens, commit-yield and release baselines all come out of the same run). The prior-knowledge metrics are computable on v1 *today* and I have already prototyped both read-only, so phase 0 is largely done: parametric-seeded query rate **28.0% (78/279)**, uncited-sentence rate **8.2% (29/354)**, invented-docid repairs **0**. Do this first — it defines what "helped" means before anything changes.
- **Phase 1 — prompt-only changes (#4, #5→#7, #7, #8's prompt half, and the step-1/4/5 wording).** No schema, no harness. Cheap to run and revert, and it isolates how much of the coverage gain is pure wording versus the ledger. **The prior-knowledge change is fully evaluable in this phase**: its primary metric (parametric-seeded query rate) and both of its safeguard metrics (uncited-sentence rate, invented-docid repairs) read off artifacts that already exist in v1 form and need no new fields. Only the leak check (Tier 1 #9) waits for phase 2's ledger. That makes phase 1 unusually informative for its cost, and it is the reason not to bundle the two changes.
- **Phase 2 — the two schema changes + the `search_tool_def` harness param + the step-2 mechanics migration into the `query` description.** Tests: extend `tests/systems/test_facets_agent.py` with (a) the advertised search def carries required `requirement` and the run's engine enum, (b) the commit def carries `coverage`/`ready_to_report` with the three-value status enum, (c) an end-to-end scripted run where a `commit_context` call carries a `coverage` payload completes normally and the payload appears in the saved trace, (d) a call *omitting* `coverage` still completes — the "schema is a forcing function, never a failure mode" invariant, (e) the `query` description mentions named candidates only when `keyword` is in the enabled engines. Plus `bash scripts/test.sh systems` unchanged for aus_agent.
- **Phase 3 — decision point.** Only if the phase-2 A/B shows `ready_to_report: true` with open entries, open entries at report time, or a nonzero `unavailable`-candidate leak rate, build the deferred harness gate.

Phase 1 and 2 A/B separately because they answer different questions; if phase 1 alone closes the gap, phase 2's ~5% token overhead is not worth paying and the plan should say so. A specific outcome to be ready for: phase 1 lifts named-entity coverage (rows 5/7) while leaving the whole-requirement misses (row 1) untouched, since a licence to name candidates does nothing for a requirement the model never enumerated. That would be the *expected* split, and it is the case for shipping both.

---

## 5. Validation plan

The arena is the wrong primary metric here and the repo's own worklogs prove it: at n=15 the re-run moved 19-11 → 21-9 with *no code change on aus_agent's side*, clean-win groups went 7/3/5 → 7/1/7, and the judge shows a systematic 66.7% "prefer Assistant B" position bias with `order_consistency` at 0.533. Preregister the metrics in this order:

**Tier 1 — deterministic, zero-cost, hundreds of data points (the decision metric).** From `data/outputs/facets_agent/*.output.json` trace steps and `*.trajectory.json` raw messages:

1. **distinct requirements declared per topic** (v1 baseline: unmeasurable → this is the new instrument; the falsifiable form is #2).
2. **searches per distinct requirement** — target: mean total searches **down** from 18.6 while distinct requirements labelled goes **up**. The 6054a7 signature (39 searches / ~3 requirements) is the specific thing that must not reproduce.
3. **open requirements at report time** — entries still `open` in the last `commit_context`. Target: ~0.
4. **`ready_to_report` vs. ledger consistency** — the trigger for phase 3.
5. **processed tokens** — target: down from 195K toward aus_agent's 88K; a rise means the ledger isn't paying for itself.
6. **commit yield** (7.5% baseline), **release count** (0 baseline), **failed calls / protocol violations** (0 baseline — must stay 0; this is the regression guard on the "keep searching multi-engine" behaviour).

*New, for the prior-knowledge change (rows 7 and 8) — all three prototyped read-only against v1, so the baselines below are measured, not estimated:*

7. **Parametric-seeded query rate — the primary metric for row 7.** For each `search`, extract capitalized/acronym content terms from `query` and keep those appearing in **neither** the request text **nor** any result text returned earlier in the same trajectory. `trajectory.json:raw_messages` interleaves `function_call` and `function_call_output` in order and the outputs carry full passage text, so the "already surfaced by the corpus" exclusion is exact rather than approximate — which is what separates this metric from a naive proper-noun count, and what makes it a direct measurement of the aus_agent rule facets_agent is now relaxing (a corpus-derived name is legal under *both* systems' rules; only a genuinely novel one is the divergence). **v1 baseline: 78 of 279 searches, 28.0%**, per-topic range 0% (605492, 0/8) to 65% (605404, 11/17), with the misses' signature visible in the tail: 605367 4/16, 60535d 3/24, 60547f 2/20 — the three topics whose diagnosis names entities that were never queried are among the four lowest rates in the run. Denoising before the A/B: drop sentence-initial capitals and a small stoplist of generic capitalised tokens (the crude pass admits "How", "Because", "Asia", "Cold War"), and report *distinct novel terms per topic* alongside the query share, since one Indomaret query matters more than three restatements of "UAV". Target: **up, materially — 28% → 45%+, and nonzero on every topic**; a topic that still runs 0/8 has not adopted the licence at all.
   **The joint prediction is what makes this falsifiable, and it is a prediction, not a target:** #7 up *and* (#2 searches-per-requirement down / rubric recall up) means the licence bought specificity. #7 up with #2 and Tier 2 flat means it bought only vocabulary noise — 6054a7 already ran 10 parametric-seeded queries out of 39 and still missed three requirements, which is the exact shape of "named queries without a ledger to point them at the right requirement". That single data point is the strongest available reason to A/B phases 1 and 2 separately.
8. **Uncited-sentence rate — the safeguard's primary regression guard.** Share of `answer[]` entries with an empty `citations` list. **v1 baseline: 8.2% (29/354)**, concentrated in 605476 (12/21), 958498 (7/43), 60547e (6/22). Preregistered gate: **must not exceed 8.2% materially**, and 605476 specifically must not get worse. Paired with **invented-docid repairs** — the count of `report_repairs` entries matching "dropped uncommitted docids" (**v1 baseline: 0 across all 15 topics**), which is the sharpest laundering signal in the whole plan and costs nothing: it fires exactly when the model tries to attach a parametric claim to a document it never committed. Any nonzero value here is a stop-ship for row 7.
9. **`unavailable`-candidate leak rate — the specific check for "searched from a belief, corpus had nothing, claim appeared anyway".** Phase 2 only, and it is the reason §1.2 requires `unavailable` notes to spell out the terms searched. From the last `commit_context`: for every `unavailable` entry, extract the named terms from its `note`, then string/alias-match them (case-insensitive, plus simple morphological variants) against the final answer text. A hit in a **cited** sentence is a *candidate* leak worth reading by hand — the model may have found supporting evidence after all and mis-staged the ledger. A hit in an **uncited** sentence is a **confirmed leak**: the model searched for its belief, recorded that the corpus lacks it, and asserted it anyway. Roughly 30 lines in the same analyzer, zero API cost. **Target: 0 confirmed leaks.** Report the inverse too — `unavailable` entries whose terms are correctly *absent* from the report, or present only in an explicit "the corpus does not cover X" sentence — because that is the behaviour the plan is trying to buy, and it deserves to be counted rather than assumed.

**Tier 2 — planning recall against the rubrics (~$0.30, the causal metric).** This is the measurement the report couldn't make. For each topic, the ~31 official criteria in `research-rubrics-dev-rubrics.jsonl` are a ground-truth requirement list. One `gpt-5.6-luna` JSON-mode call per topic — same shape and cost class as `worklogs/assets/2026-08-05-llm-diagnosis.py`, which came in at $0.23 for all 15 — asking three questions in one response:

1. **Requirement recall:** which rubric criteria have no matching entry in this run's declared requirement ledger? This isolates the *planning* failure from answer quality and moves on a 15-topic sample far more decisively than a pairwise arena can.
2. **Recall decomposition (new, isolates row 7 from row 1):** for each criterion recovered in v2 but missing in v1, classify it as **named-specific** (it demands a particular entity, work, technique or figure) or **thematic** (it demands a topic be addressed). The plan's hypothesis is that the ledger recovers thematic criteria and the prior-knowledge licence recovers named-specific ones. If v2's gains are entirely thematic, row 7 did nothing useful and its six prompt lines should come back out; if they are entirely named-specific, phase 2's ledger overhead is the thing under question.
3. **The laundering check Tier 1 #9 cannot do alone (new):** given the ledger's `unavailable` entries and the full answer text, does the report assert anything about those requirements, and is each such assertion attached to a cited committed document that actually supports it? Tier 1 #9 catches verbatim reappearance of a named term; this catches the paraphrased form — the model that searched "Hidden Path Entertainment", found nothing, marked the requirement `unavailable`, and then wrote "the studio that originally co-developed the game" with no citation. Ask for a verdict per `unavailable` entry (`absent` / `named-as-gap` / `asserted-uncited` / `asserted-cited`) plus the offending sentence, so any nonzero result is one grep away from being read by hand rather than argued about. **Run this on both arms** — v1 has no ledger, so the v1 arm runs the degenerate version (does the answer assert named specifics that no committed document supports?), which is worth having anyway as the pre-change laundering baseline the 8.2% uncited rate only hints at.

**Tier 3 — quality confirmation (not refutation).** Re-run the 15 topics as `--run-id facets-agent-v2-15topic` (resumable via `--skip-existing`), then:
- `arena_aus_agent_vs_facets_agent_rubric.py --facets-agent-run-id facets-agent-v2-15topic` — **zero code change**, the flag already exists. Read *clean win/loss groups* (topics winning both orientations), not the pooled 30-battle count, given the documented position bias.
- A **self-arena v1 vs v2** needs only a thin variant script: `load_answers_from_outputs(system_dir, run_id)` is already generic, so both sides point at `data/outputs/facets_agent` with two run_ids; only `LABELS`, `RUN_IDS` and `OUT_DIR` change. Both orders are already judged and pooled.
- `rubric_scorecard_aus_agent_vs_facets_agent.py` for per-criterion movement, watching the Explicit/Implicit Criteria and Instruction Following axes, and trusting `criterion_tally` over the per-topic average on sparse axes (per the script's own documented lesson). For row 7 specifically, the criteria to watch are the ones the v1 diagnosis named: 605391's partner criteria, 605404's developer/history criteria, 60535d's named-technique criterion, 605367's Indian-features criterion, 60547f's Olson/Locke criteria. Five named criteria across five topics is a small enough set to inspect individually, and their movement is a far more direct read on row 7 than any aggregate.
- **Cache hygiene, load-bearing:** the arena/scorecard caches key on `task_id`, not answer text. New answers under a new run_id are fine, but re-judging the *same* run_id after a change silently returns stale verdicts — the exact trap documented in the re-run worklog.

**Cheap gate before spending any of it:** run phases 1 and 2 on **four topics only** — `6054a7` (39 searches, 3 requirements missed), `605476` (2 explicit mechanisms never searched, *and* the run's worst uncited-sentence rate at 12/21, so it is the safeguard's canary as well as the coverage gate's), `9af325` (structure loss), and `605391` (the named-partners case whose diagnosis literally names Indomaret and GrabFood — the cleanest single test of row 7 in the batch). Check Tier 1 metrics #2, #7, #8. Four of the report's own worst cases, one per failure mode; if searches-per-requirement doesn't move on 6054a7, or the parametric-seeded rate doesn't move on 605391, or the uncited rate rises on 605476, the change doesn't work as designed and the 15-topic run isn't worth the tokens.

**Stated up front in the worklog:** at n=15 the arena cannot *refute* a Tier-1/Tier-2 improvement, only fail to confirm it. Decide on Tier 1 + Tier 2; report Tier 3 with its noise characteristics attached.

---

## 6. Risks

- **Compliance risk on `requirement`:** a required field the model half-fills ("general background"). Detectable directly — label entropy and label-to-request-text overlap are Tier-1 metrics. Mitigation is the field description demanding the request's own words; fallback is to move the enumeration entirely to the commit ledger and make `requirement` optional.
- **Over-decomposition:** the model enumerates 30 trivial requirements and searches each once, shallowly. Guarded by step 1's "group into facets" (facets stay the unit of work; requirements are the checklist) and detectable as distinct-requirements-up *with* commit-yield-down.
- **[new] Confirmation bias — the risk aus_agent's rule exists to prevent.** The model seeds a query with a belief, retrieves a passage that mentions the entity without supporting the specific claim, commits it, and cites it. This is the one failure the harness genuinely cannot catch (the docid *is* committed, so nothing is stripped). Mitigations are layered and all prompt-level: step 2's paired category query so the candidate competes rather than anchors; step 5's "the document says what you are attributing to it, not what you expected"; and the existing, already-working "actively look for evidence that complicates or qualifies a facet". Detection is Tier 2's laundering check, and honestly, only Tier 2 — this is the residual risk that a deterministic metric cannot reach, and the worklog should say so rather than imply the leak check covers it.
- **[new] Budget burned on entities the corpus lacks.** ClimbMix is not the web; a confident model can spend a round confirming that four remembered names are all absent. Signature: total searches up, commit yield down, `unavailable` count up. Partially self-limiting (step 4 forbids re-searching a `covered` requirement, and `unavailable` is a terminal state per requirement), and partially intended — an `unavailable` verdict reached by asking is strictly better information than the same requirement sitting `open` because nobody asked. But if searches rise while yield falls, the paired-query rule is the first thing to weaken (name-only queries, no category twin).
- **[new] The licence reads as a licence to assert.** The most likely way this change goes wrong is not confirmation bias but plain drift: 200K tokens after the opening paragraph, "prior knowledge is your best source of queries" is remembered and "never a source of claims" is not. This is why the constraint is repeated at three distances — opening paragraph, step 2's "the report is not", step 5's pre-report check — and why the final-report paragraph got the "a sentence with no ids may never introduce something new" clause rather than trusting the opening line to carry that far. Detection is Tier 1 #8, which has a real baseline and needs no new instrumentation.
- **Prompt creep:** mitigated by the written 80-line cap, the step-3 trim, the phase-2 migration of step 2's mechanics into the `query` description, and the schema-vs-prompt split. The phase-1 overshoot to ~82 lines is deliberate and time-boxed to one phase; if phase 2 is cancelled on its own merits, the migration still happens.
- **Rollback:** all five artifacts (the ledger prompt text, the prior-knowledge prompt text, two schemas, one harness param) are independently revertable; the prior-knowledge licence in particular is one paragraph plus one step-2 clause and can be reverted — or replaced with aus_agent's stricter wording — without touching the ledger. The harness param defaults to today's exact behaviour, so aus_agent is untouched either way, and aus_agent's own round-one anti-seeding rule stays exactly as written.

---

### Critical Files for Implementation
- `/home/el7/E103037/repos/trec-rag-26/src/systems/facets_agent/prompts.py`
- `/home/el7/E103037/repos/trec-rag-26/src/systems/facets_agent/tools.py`
- `/home/el7/E103037/repos/trec-rag-26/src/systems/aus_agent/agent.py`
- `/home/el7/E103037/repos/trec-rag-26/src/systems/facets_agent/agent.py`
- `/home/el7/E103037/repos/trec-rag-26/tests/systems/test_facets_agent.py`

Supporting (validation): `/home/el7/E103037/repos/trec-rag-26/worklogs/assets/2026-08-05-trajectory-behavior-analysis.py`, `/home/el7/E103037/repos/trec-rag-26/worklogs/assets/2026-08-05-llm-diagnosis-results.json` (the named-entity evidence for row 7), `/home/el7/E103037/repos/trec-rag-26/tasks/task-comparison/scripts/arena_aus_agent_vs_facets_agent_rubric.py`, `/home/el7/E103037/repos/trec-rag-26/tasks/task-comparison/scripts/rubric_scorecard_aus_agent_vs_facets_agent.py`.

Reference for the divergence being declared: `/home/el7/E103037/repos/trec-rag-26/src/systems/aus_agent/prompts/system/default.md:72–80` (aus_agent's round-one anti-seeding rule — to be left untouched and cited in facets_agent's module docstring as the rule it deliberately departs from).
