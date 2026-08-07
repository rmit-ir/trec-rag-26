# brief_revise_agent — aus_agent fork + requirements brief + review pass (TREC RAG 2026)

A **fork of `aus_agent`** — the same shared `agent_harness.agent.run_agent`
staged-context loop, the same 267-line tuned system prompt, the same engine
set (`semantic,keyword`) and budgets (500K context, 500K stopping policy,
`max_committed_per_step`) — with exactly two additions, both explained in
full in `PLAN.md` (read it before touching this system again):

1. a **requirements brief** (`brief.py`): one tool-less LLM call before the
   run, producing a short checklist of what the answer must do — obligations
   the request states outright, and ones a careful reader would infer — that
   is rendered into an advisory appendix appended to the loaded system
   prompt;
2. one **review-and-revise pass** (`review.py`), wired as the shared
   harness's `pre_final_hook`: a deterministic uncited-sentence scan plus one
   grounded reviewer call, sending the model back at most once with concrete,
   substitutive fixes before the report is accepted.

Nothing else changes. `PLAN.md` §1 is the evidence this is built on: on its
own measured dev30 headroom, `aus_agent` fails 42.5% of official criteria
outright, its largest single loss is `Implicit Criteria` (315 judged, 71%
graded ≤1 — obligations a careful reader infers in ten seconds that the
writing agent, 200K tokens into a search loop, does not), and 26.0% of its
answer sentences carry no citation at all. The brief targets the first
finding; the review pass's deterministic scan targets the second — the one
check `_parse_final_prose` does not already enforce upstream (it only
refuses a report when *every* sentence is uncited, not when *some* are).

## Design

Both additions are deliberately narrow, per `PLAN.md` §2's mechanical trace
through the real harness:

- **The brief never blocks a run.** `brief.get_requirements` parses the
  analyst's JSON defensively (mirroring
  `facet_rag.planner`'s fallback policy exactly): bad JSON, missing keys, or
  zero usable entries → an empty list → an empty appendix → the system prompt
  is then exactly `aus_agent`'s own (plus the static Appendix B below). Caps
  at 8 entries total, at most 4 `origin: "implicit"`, and every implicit
  entry's `why` must be traceable to the request's own wording — an entry
  that cannot cite the request is a hunch and is dropped at parse time
  (`brief._why_quotes_narrative`).
- **The review pass needs no network.** The evidence inventory it gives the
  reviewer is read locally from `context["ledger"].call_history` — every
  staged call's original full-text documents are already held in memory for
  the life of the run, so there is no re-fetch, no extra latency, and no new
  failure mode on a flaky endpoint.
- **The review pass never fails a run.** Its entire body — the deterministic
  scan and the reviewer call together — is wrapped in one blanket exception
  guard: any failure (a raising provider, unparseable JSON, a malformed
  ledger) is logged and degrades to accepting the draft unchanged. A review
  failure must degrade to plain `aus_agent` behaviour, never to a failed
  topic.
- **Feedback is a substitution, not an addition.** `aus_agent`'s dev30 median
  answer is already 926/1024 words, so a reviewer that says "also cover X"
  without saying "cut Y" would produce an over-length report that
  `_parse_final_prose` rejects outright, costing a full correction turn. Every
  issue the reviewer raises carries a `fix` naming the substitution, and the
  feedback message always states the live word-budget arithmetic.
- **Not built** (deliberately, see `PLAN.md` §5(e)): full-text entailment
  checking of every citation. That is the expensive half of a fuller
  reviewer and it targets citation *precision*; the measured hole is citation
  *recall* — 26% of sentences cite nothing at all — which the deterministic
  scan already catches for free.

## Layout

- `prompts/system/default.md` — a byte-copy of
  `aus_agent/prompts/system/default.md` (the tuned 267-line baseline,
  including its `__MAX_COMMITTED_DOCS__` placeholder) plus one *static*
  additive section ("Review pass", ~10 lines): tells the model up front that
  its first report is a draft, checked against the brief and its own
  citations, with exactly one revision. Nothing in the original 267 lines is
  edited or deleted.
- `prompts.py` — `BRIEF_PROMPT` (the requirements analyst), `REVIEW_PROMPT`
  (the reviewer), and the per-topic `APPENDIX_TEMPLATE`/`ENTRY_TEMPLATE`
  ("Appendix A" — the brief itself, rendered and appended to the loaded
  system prompt at call time, since unlike the static review-pass section it
  varies per topic).
- `brief.py` — the requirements analyst: prompt building, defensive JSON
  parsing (caps, the implicit `why`-must-quote-the-request rule,
  fallback-to-empty-brief), and appendix rendering.
- `review.py` — the `pre_final_hook`: the deterministic uncited-sentence
  scan, the evidence inventory read from `ledger.call_history`, the reviewer
  prompt/parse, feedback rendering, and the blanket exception guard.
- `agent.py` — ~60 lines of configuration over `agent_harness.agent.run_agent`
  (modelled on `facets_agent/agent.py`): loads this package's own system
  prompt, runs the brief step on its own provider, appends the appendix,
  builds the review hook as a closure over the parsed brief and a second
  provider (both from the same `backend`/`model` factory the run itself
  uses), and delegates to the shared harness with `system_name` set to this
  package's own.
- `run.py` — a copy of `aus_agent/run.py`: same topics file, same CLI shape,
  `RUN_BRIEF_REVISE_AGENT_*` env-var prefixes and its own `--run-id`/output
  directory.

## CLI

```sh
# one dev topic by qid
uv run --group brief-revise-agent python src/systems/brief_revise_agent/run.py \
  --qid 6847465956a0f6376a605492

# ad-hoc query, explicit model
uv run --group brief-revise-agent python src/systems/brief_revise_agent/run.py \
  --query "..." --model au.anthropic.claude-sonnet-5

# every topic in the dev TSV
uv run --group brief-revise-agent python src/systems/brief_revise_agent/run.py --all
```

Config: same as `aus_agent` — root `.env` supplies `AWS_ACCESS_KEY_ID` /
`AWS_SECRET_ACCESS_KEY` / `AWS_SESSION_TOKEN` for the default `bedrock`
backend, or pass `--backend openai` with `OPENAI_API_KEY` set.

Disabling the review pass (e.g. to isolate the brief's own effect) is a
`run_agent(..., pre_final_hook=None)` call, not a CLI flag — there is no
`--no-review` switch; add one if a real experiment needs it.

## Tests

```sh
uv run --group dev --group aus-agent pytest tests/systems/test_brief_revise_agent.py
```

Offline only, driven by `tests/conftest.py`'s `ScriptedProvider` and
`stub_search_tool` — the loop mechanics themselves (staged/committed
evidence, citation parsing, budget/backstop behavior) are already covered by
`tests/systems/test_aus_agent.py` against the same shared code and are not
re-tested here. This file proves brief_revise_agent's own two additions: the
brief's defensive JSON parsing and cap enforcement; the review hook's
deterministic uncited-sentence scan, its blanket exception guard (a reviewer
call that raises or returns garbage still accepts the draft), and its
`None`-disables-the-whole-pass override; and that a non-empty brief actually
lands in the recorded system prompt (`trace.input.system_prompt`).
