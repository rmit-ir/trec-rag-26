`skills/trec-rag-2026-track-guidelines/`, `skills/pyserini-rest-api/`, `skills/trec-rag-climbmix-corpus-creation/` = **copies** of official skills above, not submodules — Claude Code only discover skills at `skills/<name>/`. track-guidelines = **canonical spec** for submission formats (official data repo say so). Nothing refresh them: `git submodule
update --remote` don't touch them.

Google Groups mailing list: https://groups.google.com/g/trec-rag-2026-participants
TREC RAG 2026 Official Skills: https://github.com/TREC-RAG/trec-rag-skills.git

## Vendored Official Skills (the spec drifts silently — check it)

**Before submission-format work, check freshness:**

```bash
python scripts/check_vendored_skills.py            # report drift (needs network)
python scripts/check_vendored_skills.py --update   # re-vendor in place
```

Never hand-edit these copies — `--update` overwrite wholesale. `skills/trec-rag-new-system/`, `skills/bm25-parameter-tuning/` = ours, skipped (`LOCAL_ONLY` in script). CI re-check weekly (`.github/workflows/vendored-skills.yml`); not in pytest suite — need network.

Re-vendor can break code, not just docs: v0.3.0 → v0.6.0 bump relaxed three validation rules `validate_rag_output` still enforced — rejected conforming submissions. See `worklogs/2026-07-30-spec-revendor-validator-relax.md`.

## Environment Rules

- **Each task get own `uv` env.** Every dir under `tasks/<task>/` owns own `pyproject.toml`, `.venv/`. Run Python inside task as `uv run --project tasks/<task> …` (or `cd tasks/<task> && uv run …`). Tasks often target different servers/stacks — isolation prevent dep conflicts.
- **Never reuse/share project root env from task.** Repo root `pyproject.toml`/`.venv` (if any) = repo-wide tooling only; task scripts must never depend on packages installed there, never `uv add` into root env from inside task.
- For command-line tools (`huggingface-cli`/`hf`, etc.), prefer `uvx <tool> …` — `uvx` run each tool in own ephemeral env, never pollute system, root env, or task env.
- **One-off Python scripts/probes:** run in ephemeral env with `uv run --no-project --with <pkg1,pkg2> python - <<'EOF' … EOF` (e.g. `uv run --no-project --with boto3 python …`). `--no-project` skip root project entirely, `--with` pull only deps needed — nothing install into any env, quick experiments never pollute root or task envs.
- **Data artifacts live under `data/`, never under `tasks/`.** `tasks/<task>/` holds code, configs, logs only. Built indexes go under `data/built-indexes/<RUN>/`; corpora, large intermediates go elsewhere under `data/`. Task scripts should point output paths at `data/`, not own task dir — keeps large artifacts out of code tree, consistent across tasks.
- **`data/outputs/`, `evaluation-results/` meant as symlinks into synced-across-machines data dir, not real dirs** — `data/*` gitignored (formerly Git-LFS'd), `evaluation-results/` now gitignored too — fresh clone or different machine start with neither. **Synced dir location + internal layout differ by machine currently**, not yet reconciled:
  - On machines synced via Downloads: `~/Downloads/trec_rag_26_data/` with `outputs/`/`evaluation-results/` subfolders matching repo structure 1:1 — symlink direct: `ln -s ~/Downloads/trec_rag_26_data/outputs data/outputs` and `ln -s ~/Downloads/trec_rag_26_data/evaluation-results evaluation-results`.
  - On this Linux box: `/research/remote/petabyte/users/oleg/trec_rag_26_data/`, laid out differently (`facet_rag-runs/`, `aus-agent-traces/`, `evaluation-results/` per-artifact-type, not `outputs/` mirror of `data/outputs/<system>/`) — **not yet symlinked**, straight symlink would silently misplace `data/outputs/<system>/` writes. Treat as manual copy-in/copy-out source for now (check first before re-running something expensive — data may already exist there from another session) until two layouts unified.
  Whichever applies: never `mkdir` real dir at `data/outputs` or `evaluation-results` once symlinked — silently forks local data out of synced copy.
- **Reference/external repos live under `tmp/`.** Any upstream source repo consulted (e.g. `tmp/Cottontail-claclark`) cloned under `tmp/`, browsable, re-pullable (`git -C tmp/<repo> pull --ff-only`). **Before cloning external repo elsewhere, check if already under `tmp/`, reuse it.** Index of what's there: `tmp/REFERENCE-REPOS.md`; add row when cloning new one.
- **Task may use `mamba`/conda env instead of `uv` when it needs native toolchain** (C++/Bazel etc.) `uv` can't provide. Create in-folder as prefix env (`tasks/<task>/env`) — stays self-contained like `.venv`. `tasks/ssr_search/` does this (gcc 13 + bazelisk for building Cottontail).

## Running Long Commands

Anything running longer than few seconds (downloads, uploads, builds, migrations, dev/test servers, batch jobs): launch as **tracked** background task (`run_in_background`, not detached `&`), `tee` output to log file — visible both places.

```bash
some-command 2>&1 | tee /tmp/<task>.log   # launch as a tracked background task
# then tell the user: tail -f /tmp/<task>.log
```

Never pipe in-flight command through `tail`/`head` — piped output buffer until producer exits, user see nothing while progress happen.

When launching tracked background task, print **full command** verbatim in chat response (fenced block) right after kickoff — user can post-check exact what running. Don't paraphrase or omit env vars.

Clean up proactively: kill background tasks, throwaway resources once no longer needed. Exception: something handed to user for testing (e.g. dev server) stays running until they say done.

## Worklogs

Take worklog (`worklogs/YYYY-MM-DD-<topic>.md`) for every substantive work session, commit it with work it describes.

**Experiment worklogs must be self-contained down to raw inputs.** Unlike code worklogs — where diff, git history preserve details — experiment's intermediate artifacts (ad-hoc probe scripts, sub-agent transcripts, scratchpad sweep logs, judgment passes) session-local, vanish when session end. Worklog itself must capture:

- the **exact inputs**: every query/prompt string tested, verbatim — not a
  paraphrase like "compact keyword variants";
- **full result matrix**, not just aggregates/highlights;
- how outcomes judged (metric, or graded-by-reading and on what);
- run-ids/artifact paths for anything that *does* persist under
  `data/outputs/`.

When raw sweep log or probe script exists, copy into `worklogs/assets/<date>-<name>.<ext>`, reference it — that file only surviving evidence behind worklog's judgment calls.

## Notebooks

Exploratory Jupyter notebooks live in `tmp/`, one deliberate exception to "each task gets own env" — **all notebooks always run with root `notebook` dependency group** (`uv run --group notebook …`), never `tasks/<task>/` env. Group lives in repo-root `pyproject.toml` (`pandas`, `pyarrow`, `matplotlib`, `ipykernel`, `jupyter`, `nbconvert`); notebook deps added there (`uv add --group notebook <pkg>`), nowhere else.

```bash
# Install dependencies and run notebook in VS Code
uv sync --group notebook

# OR Execute headlessly (runs all cells, writes outputs back in place)
uv run --group notebook jupyter nbconvert --to notebook --execute --inplace tmp/<name>.ipynb

# OR Open interactively in Jupyter Lab
uv run --group notebook jupyter lab tmp/<name>.ipynb

# OR Register a kernel for VS Code / any Jupyter frontend
uv run --group notebook python -m ipykernel install --user \
  --name trec-rag-notebook --display-name "trec-rag (notebook)"
```

## Per-Clone Setup (two manual steps — nothing else is automatic)

Neither can be committed — **every fresh checkout must run both**:

```bash
# 1. git hooks (hooks are never cloned)
bash scripts/git-hooks/install.sh                 # sets core.hooksPath=scripts/git-hooks

# 2. Claude Code hooks (.claude/ is gitignored)
mkdir -p .claude
cp scripts/hooks/claude-settings.example.json .claude/settings.json
```

Both exist to keep `docs/architecture.html` — interactive RAG-systems architecture diagram, generated from `src/systems/` — from going stale:

- **pre-commit** (`scripts/git-hooks/pre-commit`) rejects commit whose staged tree has stale diagram. Only fires when commit touches `src/systems/`, `gen_arch_viz.py`, or diagram itself. Bypass with `git commit --no-verify` or `SKIP_ARCH_VIZ_CHECK=1`. Same hook runs offline test suite when commit touches `src/`, `tests/`, or `pyproject.toml` (bypass with `SKIP_TEST_CHECK=1`).
- **Claude Code hooks** (`scripts/hooks/arch_viz_refresh.sh`) regenerate it in-session on edits under `src/systems/`, self-heal on `Stop`. If already have `.claude/settings.json`, merge template's `hooks` block in rather than overwrite it.

CI (`.github/workflows/architecture-diagram.yml`) re-checks freshness on PRs, `main` — clone that skips step 1 or 2 still caught, just later. Regenerate manually any time with `python skills/trec-rag-new-system/scripts/gen_arch_viz.py --open`; see `trec-rag-new-system` skill for full story.

## Testing (`tests/`)

All tests live under `tests/`, collected by pytest — nothing under `src/` is test file. Suite **hermetic by default**: no credentials, no network.

**Use `scripts/test.sh`** — passes dep groups for you, fails on skip (both easy to get wrong by hand; see below). Two modes:

```bash
bash scripts/test.sh                    # EVERYTHING (947 cases, ~16s) — before every commit
bash scripts/test.sh contract           # just one area
```

Selective mode takes anything pytest does — directory, file, `file::test_name`, `-k` expression — plus shorthands `contract`, `shared`, `systems`, `dummy-api`, `aus-agent`, `live`:

```bash
bash scripts/test.sh tests/shared/test_fusion.py
bash scripts/test.sh tests/systems/test_facet_rag.py::test_run_one_plans_both_facets
bash scripts/test.sh -k "rrf or fuse"
bash scripts/test.sh live               # ONLY the live tests — needs creds, hits real services
```

**Run full suite after ANY change under `src/utils/`, `src/tools/`, `src/ragrun/`, `src/systems/`**, before committing. Those layers shared by all five systems — subset can't clear change to them — whole suite ~16s, cheaper than reasoning which tests edit reached. Selective run prints this reminder on success.

Equivalent by hand, if need pytest flags script don't pass through:

```bash
DEP_GROUPS="--group dev --group o3-deep-research --group aus-agent"
uv run $DEP_GROUPS pytest                        # whole offline suite
uv run $DEP_GROUPS pytest -m 'live or not live'  # offline + live together
```

**Pass all three dep groups.** `tests/shared/test_mcp_server.py` `importorskip`s `mcp.server.fastmcp`, `tests/systems/test_aus_agent.py` `importorskip`s `boto3` — with `--group dev` alone those tests *skip*, run green having proven nothing about code they cover. Suite otherwise skip-free by design — **`scripts/test.sh` and CI both fail on any skip** — if add `importorskip`, add its group to `scripts/test.sh`, `.github/workflows/tests.yml`, `scripts/git-hooks/pre-commit`.

(Never name that variable `GROUPS` — bash built-in holding numeric group ids, assigning to it silently ignored.)

Layout: `tests/contract/` (input/output format conformance vs track spec), `tests/shared/` (`utils`/`tools`/`mcp` layers), `tests/systems/` (per-system end-to-end), `tests/aus_agent_context/` (`ContextLedger` suite), `tests/dummy_api/` (real clients over loopback HTTP, see below).

`tests/conftest.py` holds shared fixtures, *enforces* hermeticism rather than trust it — read before writing tests:

- **`no_network`** (autouse) fails any unmarked test reaching `urllib.request.urlopen`/`socket.create_connection`, naming URL.
- **`isolated_data_dir`** (autouse) repoints `RAGRUN_DATA_DIR` at tmp dir — `save_run` never writes into real `data/outputs/`.
- **`no_ambient_creds`** (autouse) strips `SEARCH_API_KEY`/`OPENAI_API_KEY`/AWS vars for offline tests — otherwise "hermetic" test could pass locally only because silently authenticated.
- **`stub_search_tool`** — dummy retrieval backends returning spec-shaped payloads; patches `tools.search_tool._DISPATCH` — real serialization/truncation/error-envelope code stays under test while transport faked. Returns `calls` dict for asserting engine routing.
- **`scripted_provider`** — dummy LLM implementing full `providers.base.Provider` contract; script with list of `ModelTurn`s or `responder(pending_text, turn_index)` callable.
- **`fake_hits` / `fake_search_response`** — canonical ClimbMix payloads in exact shapes `references/{rag,retrieval}-task.md` document.

**Every external API dummied in offline suite** — search endpoints via `stub_search_tool`, model backends via `scripted_provider` — each returning response in documented format, pipeline runs end-to-end zero network. Mark test `@pytest.mark.live` to hit real services instead; each system keeps at least one so real path stays exercisable.

`tests/dummy_api/` goes one layer deeper: local `HTTPServer` speaking each backend's documented wire format, **real** clients pointed at it via env vars, nothing patched. Covers what `stub_search_tool` cannot — URL construction, auth headers, `User-Agent` proxy requires, HTTP verb, request-body shape, response→`SearchHit` mapping. Those tests marked `local_socket` (loopback only, no creds, runs in CI); `tests/dummy_api/conftest.py` narrows `no_network` rather than disabling it — hardcoded hosted URL still fails.

**Every test needs docstring, must say something test name does not** — why behaviour matters, or what breaks if it regresses. Prose restatement of name worse than nothing. Module docstrings carry layer-level "what this file defends and why it's fragile" — per-test ones stay short. Tests pinning known `src/` defect named `*_current_behaviour`, say so in docstring — fix announces itself by failing.

Enforced by `.github/workflows/tests.yml` on every PR/push, `pre-commit` hook. See `trec-rag-new-system` skill for full story.

## RAG Systems (`src/systems/`)

Adding, running, or reviewing RAG system covered by **`trec-rag-new-system`** skill (package layout, shared `ragrun`/`tools`/`utils` layers, strict-vs-rich artifact split, scaffolder, architecture visualization that must be regenerated + launched whenever system developed or run). Browse current architecture at `docs/architecture.html`.

## Active Tasks

- **BM25 index (Lucene/Anserini)** — built in `tasks/bm25_index/`. *Build* task, not search server: produced on-disk Lucene index at `data/built-indexes/climbmix-bm25/` (single segment, positions present, ~1.5 TB; `.fdt` stored text = 1 TB). Usable for ad-hoc experiments via `tasks/bm25_index/boolsearch/BoolSearch.java` (+ `bs.sh`) — read-only full-Lucene-syntax searcher (Boolean `+must`/`-not`, `"phrase"`, `"phrase"~N` proximity) over same mmap'd index. NB: *hosted* index-server (`:8085` / `index-climbmix-bm25.dsync.net`) **OR-only** — its `BagOfWordsQueryGenerator` strips all Boolean operators — use `BoolSearch` for true Boolean/phrase/proximity on Lucene.
- **SSR / Cottontail search (fork stack)** — working in `tasks/ssr_search/`. Implements *Boolean Queries Are All You Need?* (arXiv 2607.11362) approach: Cottontail annotative index + Shortest-Substring Ranking (SSR), driven by GCL Boolean query language (`(^ a b)` AND, `(+ a b)` OR, `"phrase"`, `>>`/`<<` containment). **NOT our Lucene index** — separate C++/Bazel engine, our fork `tmp/Cottontail` (remote `rmit-ir/Cottontail`; upstream paper repo `tmp/Cottontail-claclark` READ reference only, no longer build it). Mamba env (`tasks/ssr_search/env`, gcc 13 + bazelisk) builds fork's `cottontail-jsonl-{index,query,server}` apps; ClimbMix shards index into 26 stemmed SimpleWarren group-burrows. Served as fleet of 26 single-burrow `cottontail-jsonl-server`s (loopback :7000..:7025, `launch_fork_servers.sh`, each memory-bounded by `--cache-budget-mb`) behind `fork_shim.py` (stdlib HTTP fan-out on :8099 via `MultiShardSearchEngine`), reverse-tunneled to `index-climbmix-ssr.dsync.net`.
- **Creating local custom index** — working in `tasks/custom_index/`. All scripts, logs, intermediate artifacts for task live there.
- **Search engine + REST API** — working in `tasks/search_serve/`. Consumes built-index dir (`data/built-indexes/<RUN>/`). Provides `SearchEngine` Python library, ad-hoc CLI, FastAPI REST. Designed to extract into standalone repo post-submission.
- **Chunking strategy** — working in `tasks/chunking-strategy/`. Web app (FastAPI + vanilla-JS UI) to browse parquet shard, tune chunking strategies live (target band/hard max/overlap dials, words×1.3 token estimates, chunk-size distributions). `scripts/chunkers.py` holds strategies, doubles as pipeline chunking CLI (corpus jsonl in, chunk jsonl out). Chunk ids `<docid>_p<page>` (page from 1, e.g. `shard_00000_3908_p1`) — parent docid derivable downstream (`rsplit("_p", 1)[0]` — unambiguous, rows pure digits).
- **BM25 `k1`/`b` tuning** — working in `tasks/bm25_tune/`. Tunes BM25 on chunked ClimbMix index (read-only, under `BM25_TUNE_INDEX_DIR`) against aus_agent's 1063 keyword queries with `gpt-oss-20b` Bedrock judge (pooled 0–3 qrels, cached under `data/bm25-tune/judgments/`). JDK 21 conda env in-folder; **`export JAVA_HOME="$PWD/tasks/bm25_tune/env/lib/jvm"`** — test suite needs it too. Plan: `tasks/bm25_tune/PLAN.md`; **WP0/WP6 judge calibration mandatory gate before any sweep spend**, budget cap required operator input (`BM25_TUNE_BUDGET_USD`, currently $50) with no default in code. Harness **corpus-agnostic**: seven `BM25_TUNE_*` vars carry ClimbMix values as defaults (unset environment reproduces published run), `make-queries` takes any JSONL/TSV/CSV/one-per-line query file, `calibrate --from-pool` runs mandatory gate on corpus with no labeled log. Running on **another index** = **`bm25-parameter-tuning`** skill (`skills/bm25-parameter-tuning/` — ours, not vendored, `check_vendored_skills.py` skips it).

## Outputs Viewer (`tasks/outputs_viewer/`)

Next.js app for browsing runs in `data/outputs/`. Launch with production build, as tracked background task (see *Running Long Commands*):

```bash
cd tasks/outputs_viewer && pnpm build && pnpm start   # http://localhost:3618
```

Keep server up until user says done. Run from `tasks/outputs_viewer/`: `src/lib/server/env.ts` derives repo root as `cwd/../..` to find `data/outputs/`, root `.env`.

## Stack quirks (lessons learned — keep these out of future debugging time)

### Gunicorn

- **`-c <config>` resolved against original cwd, not against `--chdir`.** Always pass absolute path to `-c` when also using `--chdir`. Symptom: `Error: 'gunicorn_conf.py' doesn't exist`.
- **Per-worker GPU pinning needs `pre_fork` hook with master-side counter.** Bare `gunicorn -w 8` pins nothing — all workers share default device. See `tasks/search_serve/scripts/gunicorn_conf.py` for `itertools.count()` + `os.environ["CUDA_VISIBLE_DEVICES"] = str(rank % N)` pattern. Must NOT initialize CUDA in master (no `--preload` with torch.cuda touches) or worker fork breaks inherited CUDA context.
- **Engine load takes minutes** (model + 64 GB PQ mmap + warm-up). Set `--timeout 600` or workers killed mid-load.

### DiskANN (diskannpy)

- **One libaio io_context per search thread, ~1024 events each.** Stay under `/proc/sys/fs/aio-max-nr` (kernel default 65,536): `workers × num_threads ×
  1024 < cap`. Exceeding throws `io_setup() failed with EAGAIN ->
  std::system_error: Operation not permitted` from C++, kills process. Conservative production default for serve: `DISKANN_THREADS=4` per worker.
- **Default `num_threads=0` means "use all CPUs"** — on 256-thread box reserves 256 × 1024 = 262K aio events, 4× over default cap. Always pass explicit small number for search-side threads.

### Multi-GPU servers

- **Each worker process needs own SentenceTransformer model copy** (no sharing across processes); page-cache shares index files for free. ~600 MB per worker on GPU.
- **Encode serializes per process under concurrency.** Single-worker uvicorn can't use Python concurrency to scale encode — queues on GIL, GPU/CPU pipeline. To scale, run N workers (gunicorn), pin GPUs.

### FastAPI threadpool gotcha (CRITICAL — read before adding endpoints)

- **FastAPI handler declared with `def` (sync) runs in 40-thread anyio threadpool, not asyncio event loop.** Within ONE worker: up to 40 concurrent requests fan into 40 threads sharing all per-engine state — GIL contention on Python work, race conditions on any non-thread-safe C extension.
- Already bitten by this: sweeping 8-worker gunicorn setup at concurrency=8+ saw (a) `zstandard.backend_c.ZstdError:
  Data corruption detected` (Zstd decompressors not thread-safe), (b) encode latency exploding from 25 ms to 400+ ms even though each worker only ~1 in-flight request on average (threadpool stayed hot from earlier bursts).
- **Two-part fix when adding endpoint:**
  1. Make every shared C-extension object thread-safe — either `threading.local()` per backend or recreate cheap objects per call. `docstore.FlatShardDocStore._decode` already does this for Zstd decoder.
  2. For latency-critical endpoints, declare `async def`, dispatch blocking work via `asyncio.to_thread(...)` — serializes blocking call per worker (what we want for GPU encode, DiskANN search anyway, both already release GIL internally), while letting unrelated requests progress on loop.

### Multi-GPU benchmark notes (current, post async-refactor)

- **Single-worker peak ≈ 28 req/s** at C=1.
- **4-worker gunicorn (sync def, 1 GPU/worker)** peaked ~71 req/s at C=8.
- **8-worker gunicorn with async `def` + asyncio.Semaphore(1) per worker peaks 102 req/s at C=32** — 1.7× previous best, zero errors, encode_p50 stays flat 24.4 ms across every concurrency level (proves per-worker single-stream encode doing its job).
- C=64 starts regress (50 r/s) — kernel listen queue starts dropping; for higher real-world load, scale horizontally instead.

### Jina v5 (`jinaai/jina-embeddings-v5-text-nano`)

- **Uses custom `EuroBERT` architecture via `trust_remote_code=True`.** Pull in `einops` + `peft` to satisfy custom code path. Model has adapters for `task=retrieval`/`classification`/`clustering`/etc. — ` -retrieval` variant in HF is pre-merged retrieval-only adapter.
- **ONNX export NOT viable as of 2026-06-30.** Failure cascade:
  1. `optimum-cli export onnx` rejects EuroBERT (no native `OnnxConfig`).
  2. Legacy `torch.onnx.export(...)` errors with `ScalarType ComplexDouble
     is an unexpected tensor scalar type` (rotary positional embeddings
     use complex tensors).
  3. `torch.onnx.export(..., dynamo=True)` fails at `torch.export.export`
     with a dynamic-shape constraint violation on the `seq` dim.
  Writing custom `OnnxConfig` + complex-RoPE decomposition = multi-day work. **Don't go down this path again without strong reason.** PyTorch CPU + AMX BF16 competitive (~28 ms p50 single-query encode), recommended CPU-only path until upstream gains EuroBERT ONNX support.
- **`get_sentence_embedding_dimension()` returns `None`** on this model — probe via tiny `model.encode("x")` to get real dim (768).

### CPU inference on Intel Sapphire/Emerald Rapids

- **bf16 + AMX competitive with single-stream GPU** for small (~140 M) embedding models. Measured 28 ms p50 vs 24 ms on L40S at C=1 — within noise. GPU only wins decisively for batched inference (large N).
- **Set per-worker `OMP_NUM_THREADS` ≈ physical_cores / n_workers** — default oversubscription hurts on multi-worker setups. For 8-worker serve on 56-core box, `OMP_NUM_THREADS=7` sensible per-worker share.

### RAGDOLL Evaluation
- **RAGDoll runs TREC-style evaluation for RAG systems** using Pi-backed LLM judges. Supports query–passage relevance judging, citation support assessment, nugget/rubric scoring, pairwise system comparison.

- **Inputs, outputs JSONL-based** — runs easy to reproduce, debug, compare against human qrels. For relevance judging, each query paired with candidate passages, RAGDoll produces automatic relevance labels.

## Notes
- Use `uv` for Python dependency management.
- Run commands from repository root.
- RAGDoll evaluation inputs should use JSONL format.
- For UMBRELA relevance judging, input rows should contain:
  - `qid`
  - `query`
  - `candidates`
  - each candidate should contain `docid` and `doc.segment`