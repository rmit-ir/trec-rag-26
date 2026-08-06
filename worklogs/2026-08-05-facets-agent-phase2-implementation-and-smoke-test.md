# 2026-08-05 — facets_agent Phase 2: tool-carried requirement ledger + 4-topic smoke test

**Branch:** `main`. Executes Phase 2 of `src/systems/facets_agent/PLAN.md` (the
`requirement`/`coverage`/`ready_to_report` schema fields and the harness
`search_tool_def` parameter) and re-runs the plan's own 4-topic cheap gate —
the same four worst-case topics Phase 1 used — to see whether the structured
ledger moves behavior further than Phase 1's wording-only change did. Code
committed alongside this worklog.

## What changed

**Harness (`src/systems/aus_agent/agent.py`).** Added a `search_tool_def:
dict | None = None` parameter to `run_agent`, mirroring the existing
`commit_context_tool` override. `tool_definitions` now reads
`search_tool_def or build_search_tool_def(engines)` — with the parameter
absent (aus_agent's own calls), this is byte-identical to before.

**`src/systems/facets_agent/tools.py` (rewritten).** Two additions, both
described in the module's own docstring:

- `build_search_tool_def(engines)` — wraps `aus_agent.tools.search`'s own
  builder, adds a **required** `requirement` property (the request
  requirement a query serves, in the request's own words — never a candidate
  answer), and appends the named-candidate/category engine-assignment
  sentence to the `query` property's description, but only when `keyword` is
  among the enabled engines.
- `COMMIT_CONTEXT_TOOL` extended with **required** `coverage` (an array of
  `{requirement, status, note}`, `status` an enum of
  `covered`/`open`/`unavailable`) and **required** `ready_to_report`
  (boolean, true only when no `coverage` entry is `open`).

Both new fields are schema-required as a **model-compliance forcing
function, not a failure mode**: OpenAI tools aren't sent in strict mode, and
the underlying handlers (`apply_commit`, `execute_full_text_search`) read
only the arguments they already understood, silently ignoring the rest —
identical to how `release` already worked. A call omitting either field still
completes; non-compliance would only be visible in the saved trace.

A `SEARCH_TOOL_DEF` module constant (`build_search_tool_def` called with the
three default engines) was added purely for `gen_arch_viz.py`, which
resolves tool refs via `ast.literal_eval` on a module-level assignment and
cannot call a function — the same pattern `aus_agent.tools.search.
SEARCH_TOOL_DEF` already uses. Caught by actually running the diagram
generator rather than assuming the ref would resolve.

**`src/systems/facets_agent/agent.py`.** Passes `search_tool_def=
build_search_tool_def(engines)` through to the harness; `ARCH_STAGES`
updated to point at the new `SEARCH_TOOL_DEF` ref and describe both new
fields in `tools_note`.

**`src/systems/facets_agent/prompts.py`.** Per `PLAN.md` §3's prompt-budget
plan, step 2's named-candidate engine-assignment sentence ("`keyword` is the
engine for a named candidate...") moved out of the prompt into
`build_search_tool_def`'s own `query` description — the same schema-vs-prompt
split step 3's release mechanics already used. Step 2 and the Tools section
instead name the two new required fields. Net effect: prompt body went from
92 lines (Phase 1) to 89 lines even after adding a description of the new
`coverage`/`ready_to_report` fields, versus the plan's ~79-line phase-2
target — still an overshoot, tracked as such, not chased further given how
small the remaining gap is.

**Tests.** `tests/systems/test_facets_agent.py` gained 5 cases per `PLAN.md`
§4's phase-2 list: (a) the advertised search def carries a required
`requirement` plus the run's engine enum, (b) the commit def carries
`coverage`/`ready_to_report` with the three-value status enum, (c) an
end-to-end scripted run where a `commit_context` call carries a `coverage`
payload completes and the payload is legible in the saved trace's
`trace.steps` (not `trajectory.json`, which only carries `raw_messages` —
caught by actually reading the saved artifact rather than assuming the
schema), (d) a call *omitting* `coverage` still completes, (e) the
named-candidate query hint only appears when `keyword` is enabled. Full
suite: 1594/1594 passing (was 1589; +5 new). `docs/architecture.html`
regenerated twice — once for the `SEARCH_TOOL_DEF` ref fix, once more after
the prompt-text edit (prompt bodies are inlined into the diagram, so any
prompt change alone marks it stale).

## Smoke test: the same 4 topics, run_id=facets-agent-phase2-smoke

```bash
export OPENAI_API_KEY="$AZURE_OPENAI_API_KEY"
uv run --group facets-agent python src/systems/facets_agent/run.py \
  --qid <qid> --run-id facets-agent-phase2-smoke
```

All 4 completed, 0 protocol violations, 0 `report_repairs`. Full logs:
`worklogs/assets/2026-08-05-phase2-smoke-run.log` (topics 1–2),
`worklogs/assets/2026-08-05-phase2-smoke-run-605391.log` (topic 4).
Comparison script: `worklogs/assets/2026-08-05-phase2-compare.py`.

**Schema compliance was 100% across all 4 topics**: every `search` call
carried a non-empty `requirement`; every `commit_context` call carried both
`coverage` and `ready_to_report`. The forcing-function design worked as
intended — the model complied on its own the first time, with no examples in
the prompt showing the field being used.

| topic | searches v1→p1→p2 | refs v1→p1→p2 |
|---|---|---|
| 6054a7 (UBI) | 39→23→**18** | 11→19→**8** |
| 605476 (alt-history) | 9→14→**12** | 6→9→**13** |
| 9af325 (Baudelaire) | 13→13→**8** | 18→21→**14** |
| 605391 (plant-based meat GTM) | 17→24→**12** | 16→22→**19** |

Search counts dropped further in 3 of 4 topics versus Phase 1 (continued
efficiency gain — the ledger seems to be cutting redundant re-search, not
just Phase 1's wording). But **references dropped too, in 3 of 4 topics**
(6054a7, 9af325, 605391) — a genuinely mixed signal that needed reading the
actual final answers, not just the counts, to interpret.

**6054a7 — the named gaps are still not closed, and now we know why.** The
final coverage ledger for this topic has only **4 entries**, all coarse
(`"Compare the effectiveness and potential long-term consequences of
Universal Basic Income..."`, `"utilizing data from peer-reviewed economic
studies"`, `"policy analysis and commentary from experts published
post-2015"`, `"published post-2015"`) — none of them break out "Ontario
eligibility criteria" or "political feasibility/public opinion" as their own
line. Reading the actual answer text confirms it: 15 dense, specific,
well-cited sentences (Ontario's 50% benefit-withdrawal rate, economist Kevin
Milligan's $15B/year warning, Stockton's 28%→40% employment jump, Finland's
7.3-vs-6.8 life-satisfaction gap) but genuinely nothing on who was eligible
for the Ontario pilot or the political/public-opinion angle the original
diagnosis named. **The mechanism is now legible**: the coverage ledger only
enforces "don't stop while an entry is open" — it does not itself force finer
requirement granularity than step 1's own decomposition already produced,
and for this topic step 1 stayed coarse (arguably reasonably: the request
text itself is coarse, and "eligibility criteria" and "political
feasibility" are things the *original diagnosis* inferred as implied
sub-facets, not phrases in the request). This is a real, specific limit of
Phase 2 as designed, not a bug — a structured ledger only checks off what got
enumerated, it can't manufacture granularity the model's own reading skipped.
Refs dropping 19→8 alongside this reads as the model closing out its (too
coarse) ledger early with what it judged sufficient support, rather than
under-searching — 18 searches still ran, just against 4 broad buckets instead
of finding new specific ones.

**605476 — a genuine further improvement, and the "shared enemy" gap is now
explicitly targeted.** The ledger decomposed cleanly into the request's own
5 numbered assumptions plus the connective and length requirements (7 clean
entries, each `covered`). One of the hybrid queries now reads *"By 1980, a
durable U.S.-Soviet alliance emerges from wartime cooperation, détente, arms
control, **and shared opposition to China**"* — explicitly naming the
"shared enemy" mechanism the original diagnosis flagged as missing and Phase
1 didn't close. Refs rose again (9→13). This topic's request happens to be
phrased as an explicit numbered list, which likely explains why step 1's
enumeration stayed granular here where it didn't for 6054a7 — a testable
hypothesis for why the ledger helps unevenly.

**9af325 — confirms Phase 1's correction to the original diagnosis, this
time from the ledger itself.** One of the 7 covered requirements reads
*"Cover the material as a coherent account of the Baudelaire orphans' case,
rather than as individual book summaries."* The request itself asks the
model NOT to structure the answer book-by-book — the original diagnosis's
"missing book-by-book structure" complaint was never a real gap, and now the
model's own requirement enumeration says so explicitly rather than this
being an inference from reading the answer by hand (as Phase 1's worklog had
to do). Searches and refs both dropped (13→8, 21→14), consistent with less
redundant search on a topic that was never as broken as described.

**605391 — clean 9-way decomposition tracking the report's own listed
sections almost 1:1**, and `GrabFood` is named again in a query (though not
`Indomaret` this time — the model's candidate recall varies run to run, as
expected of an LLM's own knowledge retrieval). Refs dropped slightly (22→19)
alongside a large search-count drop (24→12); given the ledger shows all 9
sections `covered` with no `open` entries left, this reads as the same
"efficient closure" pattern as 6054a7, just on a topic whose ledger was
granular enough not to lose anything specific in the process.

## Reading the result

The tool-carried ledger reaches the model reliably (100% schema compliance)
and produces a second, real improvement on top of Phase 1's wording change —
605476's explicit "shared opposition to China" query is a clean example, and
9af325's ledger entry confirms Phase 1's own correction to the original
diagnosis rather than just repeating it. But the smoke test also surfaces a
limit the plan's own reasoning anticipated in the abstract (§4: "a licence to
name candidates does nothing for a requirement the model never enumerated")
and this session can now show concretely: **the ledger's usefulness is
capped by step 1's own enumeration granularity**, which varies by how
explicitly the request itself is structured (numbered assumptions in 605476
vs. a single flowing sentence in 6054a7). 6054a7's specific named gaps
(Ontario eligibility, political feasibility) remain open after both phases —
not because the model didn't search, but because nothing in its own
reasoning ever named them as separate things to check.

Net read: ship Phase 2 (it strictly added compliance-verified structure with
no regressions in status/violations, and it closed a real gap Phase 1
didn't), but the 6054a7 pattern is evidence for `PLAN.md`'s Phase 3 decision
point being worth taking rather than skipping — specifically, whether a
sharper step-1 instruction (or a small worked example of decomposing a
single-sentence multi-part request into several separate ledger entries)
would help requests that don't hand the model an explicit list to key off of.
That is a prompt-wording question, answerable without another schema change,
and is the natural next increment.

## Not done this session

- The full 15-topic re-run and `PLAN.md` §5's Tier 1 (deterministic trace
  metrics, now fully measurable with `requirement`/`coverage` populated) and
  Tier 2 (rubric-recall) validation.
- Tier 1 metric #9 (the `unavailable`-candidate leak check) specifically —
  none of the 4 smoke topics produced an `unavailable` entry at all (every
  ledger entry across all 4 topics came back `covered`), so there is nothing
  yet to check that leak logic against. Worth watching on the 15-topic run:
  an agent that never uses `unavailable` either has an easy corpus or isn't
  exercising the safeguard the plan's row 7 relies on.
- The Phase 3 decision point above (sharper step-1 enumeration guidance for
  single-sentence multi-part requests) — flagged here as the concrete next
  step, not started.
