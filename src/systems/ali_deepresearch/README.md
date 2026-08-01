# ali_deepresearch — Alibaba Tongyi DeepResearch, ClimbMix port

A faithful, minimal port of the [Alibaba-NLP/DeepResearch](https://github.com/Alibaba-NLP/DeepResearch)
multi-turn **ReAct** agent (`inference/react_agent.py`) into this repo, with its
native **web** tools replaced by our **ClimbMix corpus** tools. The agent
retrieves *only* from ClimbMix and every citation is a ClimbMix docid (e.g.
`shard_00459_61697`). No web / browsing at agent runtime.

The reference trajectory `data/sample-files/run_InfoSeekQA_1000_*.json` was itself
produced by `Tongyi-DeepResearch-30B-A3B` over a local `search`/`get_document`
corpus, so both the ported system prompt and the emitted artifacts mirror it.

## Design

```
run.py ──> OpenAIChatLLM ─┐
                          ├─> ReactAgent.run(query)           # ported ReAct loop
prompts.SYSTEM_PROMPT ────┘        │
                                   ├─ <think>…</think>            → reasoning step
                                   ├─ <tool_call>{json}</tool_call>→ tools.dispatch
                                   │      search / get_document       (ClimbMix)
                                   ├─ <tool_response>…</tool_response> (fed back)
                                   └─ <answer>…</answer>          → final text
                                            │
              answer_format.format_answer ──┘  → references[] + sentence citations
                                            │
              ragrun.save_run ──────────────┘  → data/outputs/ali_deepresearch/<ts>.<slug>.{trajectory,output}.json
```

- **`react_agent.py`** — the ported loop. Same token protocol, same stop
  sequence `["\n<tool_response>", "<tool_response>"]`, same max-round budgeting
  and "context length reached → force a final answer" fallback. The LLM
  transport is injected (`ChatLLM` protocol) so the identical loop runs against a
  real endpoint or the in-process mock.
- **`prompts.py`** — the DeepResearch system prompt with web tools swapped for
  `search` + `get_document`, plus the answer-formatting prompt.
- **`tools.py`** — `ClimbMixTools` (stateful, cross-step de-duplication like the
  reference retriever) wired to `utils.search.search` for dense+sparse RRF, the
  shared `tools.search_tool.run_search_backend` result envelope, and
  `utils.fetch_doc.fetch_doc`. `search` accepts a single query string or a list
  (upstream's batched form).
- **`answer_format.py`** — free-text `<answer>` → strict TREC RAG sentences with
  docid→reference-index citations. LLM stage when an endpoint is available, a
  deterministic offline heuristic otherwise. Both outputs pass
  `ragrun.validate_rag_output`.
- **`run.py`** — CLI (`--query | --qid | --all`), endpoint config, artifact
  assembly.
Tests live in `tests/systems/test_ali_deepresearch.py` (see `## Tests` below).

## Upstream mapping — kept vs. replaced

| Upstream (`inference/`) | Here | What changed & why |
|---|---|---|
| ReAct loop `MultiTurnReactAgent._run` | `react_agent.ReactAgent.run` | **Kept.** Same `<think>/<tool_call>/<tool_response>/<answer>` protocol, stop tokens, `<tool_response>` truncation, round budget, force-answer-on-limit. |
| `call_server` (OpenAI client + retries) | `run.OpenAIChatLLM` | **Kept**, generalized behind the `ChatLLM` protocol so the loop is transport-agnostic and mockable. Sampling defaults `temperature 0.85 / top_p 0.95 / presence_penalty 1.1`. |
| `SYSTEM_PROMPT` (web tools) | `prompts.SYSTEM_PROMPT` | **Replaced tools.** `search`/`visit`/`google_scholar`/`PythonInterpreter`/`parse_file` → `search` + `get_document` only. Docid rule relaxed from "numeric only" to "exact DocID string" for ClimbMix ids. |
| `tool_search.Search` (Serper web search) | `tools.ClimbMixTools.search` | **Replaced.** Hybrid dense+sparse RRF over ClimbMix via `utils.search.search`, while `run_search_backend` preserves the shared agent-tool envelope. Keeps the batched-`query` array form and the `"A search for '…' found N results"` formatting; adds the sample's cross-step de-dup + "Already-seen" section. |
| `tool_visit.Visit` (fetch + summarize URLs) | `tools.ClimbMixTools.get_document` | **Replaced.** No URLs; retrieve full ClimbMix doc text by docid via `fetch_doc`. `Document <docid>:\n<text>` format matches the sample. |
| `tool_scholar` / `tool_python` / `tool_file` | — | **Dropped.** Web/eval-only; out of scope for corpus-grounded RAG. |
| `count_tokens` via HF `AutoTokenizer` | `_approx_tokens` (chars/4) | **Replaced.** We ship only the `openai` client, not `transformers`; a char heuristic guards the context window. |
| `EXTRACTOR_PROMPT` (web summarizer) | `prompts.FORMAT_ANSWER_PROMPT` | **Repurposed** into the answer→sentence/citation formatter the track requires. |
| free-text `prediction` | `answer_format.format_answer` | **Added.** Upstream stops at prose; the track needs `references[]` + per-sentence citations, so we add an LLM (or offline heuristic) formatting stage. |

## Running against a real endpoint

Set the endpoint in the repo `.env` (auto-loaded), then run with the dep group:

```bash
# .env
ALI_DR_BASE_URL=http://127.0.0.1:8000/v1          # vLLM serving the model
ALI_DR_API_KEY=EMPTY                               # any string for local vLLM
ALI_DR_MODEL=Alibaba-NLP/Tongyi-DeepResearch-30B-A3B
```

vLLM example (endpoint is provisioned separately — this repo deploys nothing):

```bash
vllm serve Alibaba-NLP/Tongyi-DeepResearch-30B-A3B --port 8000 --served-model-name Alibaba-NLP/Tongyi-DeepResearch-30B-A3B
```

OpenRouter instead:

```bash
ALI_DR_BASE_URL=https://openrouter.ai/api/v1
ALI_DR_API_KEY=sk-or-...
ALI_DR_MODEL=alibaba/tongyi-deepresearch-30b-a3b
```

Then:

```bash
# one dev topic by id
uv run --group ali-deepresearch python src/systems/ali_deepresearch/run.py \
    --qid 683a58c9a7e7fe4e7695846f

# an ad-hoc narrative
uv run --group ali-deepresearch python src/systems/ali_deepresearch/run.py \
    --query "How effective are influenza vaccines?" --k 10 --max-rounds 20

# every development topic
uv run --group ali-deepresearch python src/systems/ali_deepresearch/run.py --all
```

Artifacts land in `data/outputs/ali_deepresearch/<ts>.<slug>.{trajectory,output}.json`
(a `.output.violations.json` appears only if the answer breaks a track rule).
Pass `--no-format-llm` to use the offline heuristic formatter instead of an
extra LLM call.

## Tests

```bash
bash scripts/test.sh tests/systems/test_ali_deepresearch.py
```

Fully offline — no credentials, no network. A `ScriptedProvider` drives
`think → search → think → get_document → answer` through the real loop, with
the dense and sparse clients below the real RRF layer stubbed by the
`stub_search_tool` fixture. The suite asserts both retrieval legs ran, both
JSONs were written with no violations, the per-tool call counts, a non-empty
`retrieved_docids`, correctly interleaved reasoning/tool-call items, and that
every reference is cited. The `answer_format` heuristic and LLM paths are
covered separately.

One `@pytest.mark.live` test keeps the real-endpoint path exercisable; it is
deselected by default and needs `SEARCH_API_KEY` / `PYSERINI_API_TOKEN`:

```bash
bash scripts/test.sh live tests/systems/test_ali_deepresearch.py
```
