# aus_agent_v2 lean executable-contract pipeline

Date: 2026-08-06

## Outcome

This offline session created a distinct runnable `run_lean_contract_one`
candidate for GPT-5.6 Sol. It does not change the verified 0.7042 `run_one`
control. The candidate keeps the isolated plan, independent obligation scout,
same-context search/commit loop, executable evidence ledger, bounded annotation
correction, and typed terminal submission, but removes a model-facing
contradiction left by layering that contract onto the legacy prompt.

The previous contract candidate loaded a 2,541-word prompt that independently
asked the research model to make another internal plan and ultimately "emit no
tool calls and write the final report." A later dynamic addendum then required
`submit_answer` instead. The research context therefore received two planners
and two incompatible terminal contracts. The new research prompt is 417 words;
with its terminal addendum it is 492 words and has one terminal route. The
contract commit-tool description is 74 words rather than the inherited 220,
while detailed source adjudication remains in the tool-field schema where it is
used.

No provider, retrieval, search, OpenAI, Bedrock, judge, or grader call was made.
Cumulative paid spend remains **$1,096.72**, the standing **$300** cap remains
exceeded, and the best verified complete 30-topic score remains **0.7042**.
This candidate has no score until an explicitly reauthorized all-30 generation
and three-pass grade is complete.

## Baseline answer-form constraint

The earlier complete frozen-author audit remains the answer-form evidence:

| Baseline | Topics | Heading topics | Table topics | Bullet topics | Numbered-list topics |
|---|---:|---:|---:|---:|---:|
| `base-agentic-bm25` | 119 | 0 | 1 | 0 | 0 |
| `base-singlepass` | 119 | 2 | 1 | 0 | 0 |

The table case explicitly requested a table and cited every structured object.
This candidate therefore does not enable broad Markdown. The terminal schema
continues to allow only request-gated repeated labels and raw Python; ordinary
answers remain independently citable prose items.

## Exact new system prompt

The exact `contract-lean.md` source, before replacing the document-count
placeholder with `10`, is:

~~~text
# Research agent

You are a research agent producing the strongest answer the ClimbMix corpus can
support. Prior knowledge may help choose searches and interpret results, but it
is not evidence and must not support factual claims.

## Goal

Answer the actual request completely, at its requested level and in its
requested form. The task message includes a coverage plan and an executable
contract made in isolated contexts. Treat them as the checklist for research
and completion, not as evidence and not as content to repeat to the reader.

Success means every answer-required contract row is either:

- closed by a clear answer item using committed evidence mapped to that row; or
- honestly unresolved after a tagged search failed to produce usable support.

Preserve breadth while making each selected point complete: include its
material value, name, date, population, jurisdiction, or scope when the
evidence provides one. Integrate related evidence into a useful explanation,
comparison, design, argument, or deliverable rather than listing sources.

## Research

Use only the available search and commit tools. Search directly for open
contract rows, and run independent searches in parallel when useful. Start
from the request and its ordinary paraphrases; later searches may use names,
terms, mechanisms, and gaps surfaced by retrieved text. If an important gap
persists, one targeted candidate probe from prior knowledge is allowed, but a
candidate belongs in the answer only if the corpus then supports it.

Search results already contain page text and may include adjacent pages.
Inspect them before deciding. On the immediately following turn, resolve the
staged batch with one commit_context call. Keep at most
__MAX_COMMITTED_DOCS__ exact result ids whose text makes a distinct
contribution; unselected pages are discarded. Map a selected page only to
contract rows it directly supports, using short exact source-backed anchors.
Follow correction feedback precisely if an annotation is rejected.

Only committed evidence may support the terminal answer. Cite the smallest set
of mapped pages that directly supports each factual item. Do not guess, broaden
a result beyond its measured scope, convert missing evidence into a factual
negative, or hide a material conflict between sources.

## Stop

After each commit, decide which required rows remain open and use the smallest
useful next search batch. Stop researching when every required row is supported
or has a real failed attempt, or when further search is unlikely to improve the
answer. The context ceiling is a limit, not a target. Once research is closed,
complete the executable terminal contract rather than starting another search.
~~~

The exact rendered legacy prompt, rendered lean prompt, terminal addendum,
sample dynamic contract protocol, inherited commit description, and lean
commit and terminal-submit descriptions are copied verbatim into:

`worklogs/assets/2026-08-06-aus-agent-v2-lean-prompt-audit.json`

That file also records SHA-256, word, character, and byte counts for every
string. It is generated by the committed reproducible script
`worklogs/assets/2026-08-06-aus-agent-v2-lean-prompt-audit.py`; raw output is in
the adjacent `.log`.

Exact command:

~~~bash
PYTHONPATH=src/systems:src uv run --group aus-agent-v2 python worklogs/assets/2026-08-06-aus-agent-v2-lean-prompt-audit.py --output worklogs/assets/2026-08-06-aus-agent-v2-lean-prompt-audit.json
~~~

Complete static result matrix:

| Check | Legacy default | Lean contract |
|---|---:|---:|
| system-prompt words | 2,541 | 417 |
| rendered system characters | 15,920 | 2,691 |
| separate internal-plan section | yes | no |
| free-prose terminal instruction | yes | no |
| sentence-per-line output instruction | yes | no |
| combined terminal names `submit_answer` | no | yes |
| combined prompt says Australia / AUS agent | no | no |

The lean system plus the plain-prose terminal addendum is 492 words and 3,189
characters. The lean prompt alone is 16.4% of the legacy prompt by words. No
model judgment was used: every result is an exact string check.

## Model-specific decision

The current official OpenAI GPT-5.6 guidance was consulted because this is a
Sol prompt/tool intervention:

https://developers.openai.com/api/docs/guides/latest-model

It recommends lean instructions stated once, task-relevant tools with concise
precise descriptions, and preserving explicit structured/tool contracts. The
implementation follows that split: the system prompt owns research outcomes,
the dynamic contract owns stable rows, and field schemas own detailed
adjudication. The existing provider already uses the Responses API with
`store=False`, requests encrypted reasoning content, and replays model output
items verbatim across tool turns, so no separate provider rewrite was needed.

## Runnable path and control isolation

- `pipeline.run_lean_contract_one` selects `contract-lean`, coverage contract,
  observable scout, k=20, and 40 rounds.
- `pipeline.run_one` is byte-for-byte unchanged from the 0.7042 control.
- The full dev runner now defaults to run id
  `sol-aus-v2-lean-contract-dev30`, prints `prompt=contract-lean`, and passes
  `--prompt-variant contract-lean` to every independent topic worker.
- The runner still requires exactly 30 topic rows and still fails closed before
  provider setup unless explicit paid authorization, a new absolute total
  ceiling, and a positive in-flight reserve are supplied.
- The architecture model shows both the verified default and lean candidate;
  the lean path is not promoted.

Fail-closed preflight command:

~~~bash
env RUN_PAID_EXPERIMENT=NO tasks/task-comparison/scripts/run_aus_agent_v2_parallel.sh
~~~

Result: 30 topics, 30 pending, concurrency six, model
`openai.gpt-5.6-sol`, prompt `contract-lean`, then exit 3 before any paid call.
The complete output is
`worklogs/assets/2026-08-06-aus-agent-v2-lean-runner-preflight.log`.

## Verification

Focused command:

~~~bash
bash scripts/test.sh tests/aus_agent_v2/test_contract_prompt.py tests/aus_agent_v2/test_coverage_contract.py tests/systems/test_aus_agent_v2.py
~~~

Result: **54 passed**, one live test deselected. This includes an actual
scripted-provider run proving the final provider system starts with
`# Research agent`, omits the legacy sentence-per-line rule, and preserves
request-authorized runnable Python. It also pins the full-30 runner to the lean
candidate. Raw log:
`worklogs/assets/2026-08-06-aus-agent-v2-lean-contract-focused-tests.log`.

Architecture command and result are recorded in
`worklogs/assets/2026-08-06-aus-agent-v2-lean-contract-architecture.log`.

~~~bash
python skills/trec-rag-new-system/scripts/gen_arch_viz.py --open --system aus_agent_v2
~~~

Result: regenerated six systems, 18 shared edges, and five engines, then opened
the deep-linked `aus_agent_v2` view.

Full-suite command and final result are recorded in
`worklogs/assets/2026-08-06-aus-agent-v2-lean-contract-full-tests.log`.

~~~bash
bash scripts/test.sh
~~~

Result: **1,704 passed, eight live tests deselected, zero skips or failures**
in 16.60 seconds. The sole warning is the existing Starlette/httpx test-client
deprecation warning.

## Acceptance gate

Success remains a comparable complete 30-topic rubric mean of at least 0.8.
The only decision-grade next step is all 30 topics through this exact candidate
followed by the same three-pass Sol rubric grade. It remains prohibited until
the operator establishes a new absolute total ceiling above the already
recorded $1,096.72 plus an in-flight reserve.
