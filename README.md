# trec-rag-26 — RMIT-ADM+S @ TREC RAG 2026

[![TREC RAG 2026](https://img.shields.io/badge/TREC%20RAG-2026-0A66C2)](https://trec-rag.github.io/)
[![Corpus: ClimbMix](https://img.shields.io/badge/corpus-ClimbMix-6E4AFF)](https://trec-rag.github.io/)
[![Spec v0.6.0](https://img.shields.io/badge/track%20spec-v0.6.0-informational)](skills/trec-rag-2026-track-guidelines/)
[![Python 3.13](https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white)](.python-version)
[![uv](https://img.shields.io/badge/deps-uv-DE5FE9?logo=astral&logoColor=white)](https://docs.astral.sh/uv/)
[![Tests](https://img.shields.io/badge/tests-947%20hermetic-brightgreen?logo=pytest&logoColor=white)](tests/)
[![CI](https://img.shields.io/badge/CI-3%20workflows-2088FF?logo=githubactions&logoColor=white)](.github/workflows/)
[![Systems](https://img.shields.io/badge/RAG%20systems-5-8A2BE2)](src/systems/)
[![Retrieval](https://img.shields.io/badge/retrieval-dense%20%7C%20BM25%20%7C%20SSR%20%7C%20Pyserini-005571)](#retrieval)
[![Architecture](https://img.shields.io/badge/architecture-interactive%20diagram-F9A03C)](docs/architecture.html)

Retrieval and RAG systems built by the **RMIT-ADM+S** team for the
[TREC RAG 2026](https://trec-rag.github.io/) shared task, over the **ClimbMix**
corpus.

The repo holds everything end to end: the retrieval infrastructure we index and
serve ourselves, the answer-generating RAG systems that run on top of it, and
the evaluation harness we score them with.

## Layout

| Path | What's in it |
| --- | --- |
| `src/systems/` | The RAG systems — one package per system, each with its own README |
| `src/utils/`, `src/tools/` | Shared retrieval clients (dense, sparse/BM25, SSR, Pyserini) and the agent-facing `search` tools |
| `src/ragrun/` | Run artifacts: the strict submission output plus the rich trajectory trace |
| `src/mcp/` | ClimbMix MCP server, used by the hosted-agent baselines |
| `tasks/` | Infrastructure tasks — index building, search serving, chunking, load testing, output viewer |
| `evaluation/` | [RAGDoll](https://github.com/castorini/RAGDoll) (submodule) — LLM-judged relevance, support, and nugget/rubric scoring |
| `tests/` | Hermetic pytest suite (no creds, no network) over the shared layers and every system |
| `skills/` | Agent skills: track guidelines, corpus creation, Pyserini API, new-system scaffolding |
| `docs/architecture.html` | Interactive architecture diagram, generated from `src/systems/` |
| `worklogs/` | Dated log of every substantive work session |

Data artifacts (corpora, built indexes, run outputs) live under `data/` and are
never committed.

## Systems

| System | Approach |
| --- | --- |
| [`aus_agent`](src/systems/aus_agent/) | Agentic RAG with a staged/committed context ledger and pluggable LLM backends (Bedrock, OpenAI) |
| [`facet_rag`](src/systems/facet_rag/) | Plan-then-execute: decompose the narrative into facets, one search per facet, then synthesize |
| [`ali_deepresearch`](src/systems/ali_deepresearch/) | Port of Alibaba Tongyi DeepResearch's multi-turn ReAct agent onto ClimbMix tools |
| [`o3_deep_research`](src/systems/o3_deep_research/) | OpenAI `o3-deep-research` baseline, grounded through the ClimbMix MCP server |
| [`claude-code-research`](src/systems/claude-code-research/) | Claude Code driven as a research agent over the corpus CLI |

Every system emits the same two artifacts under `data/outputs/<system>/`: a
spec-conformant `*.output.json` for submission and a `*.trajectory.json` trace
for debugging and evaluation. All citations are ClimbMix docids.

## Retrieval

Three engines are indexed and served in-house over ClimbMix, alongside the
official hosted baseline:

- **Dense** — Jina-v5-nano embeddings in a DiskANN index (`tasks/custom_index/`,
  served by `tasks/search_serve/`)
- **Sparse** — Lucene/Anserini BM25 (`tasks/bm25_index/`), plus a Boolean/phrase
  searcher for ad-hoc work
- **SSR** — Cottontail annotative index with Shortest-Substring Ranking over GCL
  Boolean queries (`tasks/ssr_search/`)
- **Pyserini REST** — the official TREC RAG hosted BM25 baseline

## Getting started

```bash
git clone --recurse-submodules https://github.com/rmit-ir/trec-rag-26.git
cd trec-rag-26
uv sync                                  # repo-root tooling + shared src/ layers
cp .env.example .env                     # fill in search + model credentials

# per-clone setup (neither hook set can be cloned)
bash scripts/git-hooks/install.sh
mkdir -p .claude && cp scripts/hooks/claude-settings.example.json .claude/settings.json

# run a system — each has its own dep group
uv run --group facet-rag python src/systems/facet_rag/run.py --qid <topic-id>

# tests (~16s, hermetic)
bash scripts/test.sh
```

Each `tasks/<task>/` directory owns its own environment — run inside one with
`uv run --project tasks/<task> …`, never the root env.

## Conventions

`AGENTS.md` / `CLAUDE.md` are the working agreement for this repo: environment
isolation, where artifacts go, worklog requirements, the testing contract, and
hard-won stack quirks worth not rediscovering. Read them before making changes.
