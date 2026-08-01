Google Groups mailing list: https://groups.google.com/g/trec-rag-2026-participants
TREC RAG 2026 Official Skills: https://github.com/TREC-RAG/trec-rag-skills.git

## Vendored Official Skills (the spec drifts silently — check it)

`skills/trec-rag-2026-track-guidelines/`, `skills/pyserini-rest-api/`, and
`skills/trec-rag-climbmix-corpus-creation/` are **copies** of the official skills
above, not submodules — Claude Code only discovers skills at `skills/<name>/`.
The track-guidelines one is **the canonical spec** for the submission formats
(the official data repo says so). Nothing refreshes any of them: `git submodule
update --remote` does not touch them.

**Before any submission-format work, check freshness:**

```bash
python scripts/check_vendored_skills.py            # report drift (needs network)
python scripts/check_vendored_skills.py --update   # re-vendor in place
```

Never hand-edit these copies — `--update` overwrites them wholesale.
`skills/trec-rag-new-system/` and `skills/bm25-parameter-tuning/` are ours and
are skipped (`LOCAL_ONLY` in that script). CI re-checks weekly
(`.github/workflows/vendored-skills.yml`); it is not in the pytest suite because
it needs network.

A re-vendor can invalidate code, not just docs: the v0.3.0 → v0.6.0 bump relaxed
three validation rules `validate_rag_output` was still enforcing, so it was
rejecting conforming submissions. See
`worklogs/2026-07-30-spec-revendor-validator-relax.md`.

## Environment Rules

- **Each task gets its own `uv` env.** Every directory under `tasks/<task>/`
  owns its own `pyproject.toml` and `.venv/`. Run Python inside a task as
  `uv run --project tasks/<task> …` (or `cd tasks/<task> && uv run …`). Tasks
  often target different servers / stacks, so isolation prevents dep conflicts.
- **Do not reuse or share the project root env from a task.** The repo root
  `pyproject.toml`/`.venv` (if any) is for repo-wide tooling only; task scripts
  must never depend on packages installed there, and must never `uv add` into
  the root env from inside a task.
- For command-line tools (`huggingface-cli`/`hf`, etc.), prefer `uvx <tool> …`
  — `uvx` runs each tool in its own ephemeral env, so it never pollutes either
  the system, the root env, or the task env.
- **One-off Python scripts / probes:** run them in an ephemeral env with
  `uv run --no-project --with <pkg1,pkg2> python - <<'EOF' … EOF` (e.g.
  `uv run --no-project --with boto3 python …`). `--no-project` skips the root
  project entirely, `--with` pulls just the deps needed — nothing is installed
  into any env, so quick experiments never pollute root or task envs.
- **Data artifacts live under `data/`, never under `tasks/`.** `tasks/<task>/`
  holds code, configs, and logs only. Built indexes go under
  `data/built-indexes/<RUN>/`; corpora and large intermediates go elsewhere
  under `data/`. Task scripts should point their output paths at `data/`, not
  at their own task dir — keeps large artifacts out of the code tree and
  consistent across tasks.
- **Reference / external repos live under `tmp/`.** Any upstream source repo we
  consult (e.g. `tmp/Cottontail-claclark`) is cloned under `tmp/` so it can be browsed
  and re-pulled (`git -C tmp/<repo> pull --ff-only`). **Before cloning an
  external repo anywhere else, check whether it already exists under `tmp/` and
  reuse it.** The index of what's there is `tmp/REFERENCE-REPOS.md`; add a row
  when you clone a new one.
- **A task may use a `mamba`/conda env instead of `uv` when it needs a native
  toolchain** (C++/Bazel, etc.) that `uv` can't provide. Create it in-folder as
  a prefix env (`tasks/<task>/env`) so it stays self-contained like `.venv`.
  `tasks/ssr_search/` does this (gcc 13 + bazelisk for building Cottontail).

## Running Long Commands

For anything that may run longer than a few seconds (downloads, uploads, builds,
migrations, dev/test servers, batch jobs), launch it as a **tracked** background
task (`run_in_background`, not a detached `&`) and `tee` the output to a log
file so it is visible in both places.

```bash
some-command 2>&1 | tee /tmp/<task>.log   # launch as a tracked background task
# then tell the user: tail -f /tmp/<task>.log
```

Do not pipe an in-flight command through `tail`/`head` — piped output is
buffered until the producer exits, so the user sees nothing while progress is
being made.

When launching a tracked background task, print the **full command** verbatim
in the chat response (a fenced block) right after kicking it off, so the user
can post-check exactly what is running. Don't paraphrase or omit env vars.

Proactively clean up: kill background tasks and throwaway resources once
they're no longer needed. Exception: something handed to the user for testing
(e.g. a dev server) stays running until they say they're done.

## Worklogs

Take a worklog (`worklogs/YYYY-MM-DD-<topic>.md`) for every substantive work
session, and commit it with the work it describes.

**Experiment worklogs must be self-contained down to the raw inputs.** Unlike
code worklogs — where the diff and git history preserve the details — an
experiment's intermediate artifacts (ad-hoc probe scripts, sub-agent
transcripts, scratchpad sweep logs, judgment passes) are session-local and
vanish when the session ends. So the worklog itself must capture:

- the **exact inputs**: every query/prompt string tested, verbatim — not a
  paraphrase like "compact keyword variants";
- the **full result matrix**, not just aggregates or highlights;
- how outcomes were judged (metric, or graded-by-reading and on what);
- run-ids / artifact paths for anything that *does* persist under
  `data/outputs/`.

When a raw sweep log or probe script exists, copy it into
`worklogs/assets/<date>-<name>.<ext>` and reference it — that file is the
only surviving evidence behind the worklog's judgment calls.

## Notebooks

Exploratory Jupyter notebooks live in `tmp/` and are the one deliberate
exception to "each task gets its own env" — **all notebooks are always run
with the root `notebook` dependency group** (`uv run --group notebook …`),
never a `tasks/<task>/` env. The group lives in the repo-root
`pyproject.toml` (`pandas`, `pyarrow`, `matplotlib`, `ipykernel`, `jupyter`,
`nbconvert`); notebook deps are added there (`uv add --group notebook <pkg>`),
nowhere else.

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

Neither of these can be committed, so **every fresh checkout must run both**:

```bash
# 1. git hooks (hooks are never cloned)
bash scripts/git-hooks/install.sh                 # sets core.hooksPath=scripts/git-hooks

# 2. Claude Code hooks (.claude/ is gitignored)
mkdir -p .claude
cp scripts/hooks/claude-settings.example.json .claude/settings.json
```

Both exist to keep `docs/architecture.html` — the interactive RAG-systems
architecture diagram, generated from `src/systems/` — from going stale:

- **pre-commit** (`scripts/git-hooks/pre-commit`) rejects a commit whose staged
  tree has a stale diagram. It only fires when the commit touches
  `src/systems/`, `gen_arch_viz.py`, or the diagram itself. Bypass with
  `git commit --no-verify` or `SKIP_ARCH_VIZ_CHECK=1`. The same hook runs the
  offline test suite when a commit touches `src/`, `tests/`, or
  `pyproject.toml` (bypass with `SKIP_TEST_CHECK=1`).
- **Claude Code hooks** (`scripts/hooks/arch_viz_refresh.sh`) regenerate it
  in-session on edits under `src/systems/`, and self-heal on `Stop`. If you
  already have a `.claude/settings.json`, merge the template's `hooks` block in
  rather than overwriting it.

CI (`.github/workflows/architecture-diagram.yml`) re-checks freshness on PRs and
`main`, so a clone that skips step 1 or 2 is still caught — just later.
Regenerate manually any time with
`python skills/trec-rag-new-system/scripts/gen_arch_viz.py --open`; see the
`trec-rag-new-system` skill for the full story.

## Testing (`tests/`)

All tests live under `tests/` and are collected by pytest — nothing under
`src/` is a test file. The suite is **hermetic by default**: no credentials, no
network.

**Use `scripts/test.sh`** — it passes the dep groups for you and fails on a
skip (both are easy to get wrong by hand; see below). Two modes:

```bash
bash scripts/test.sh                    # EVERYTHING (947 cases, ~16s) — before every commit
bash scripts/test.sh contract           # just one area
```

Selective mode takes anything pytest does — a directory, a file, a
`file::test_name`, a `-k` expression — plus the shorthands `contract`, `shared`,
`systems`, `dummy-api`, `aus-agent`, and `live`:

```bash
bash scripts/test.sh tests/shared/test_fusion.py
bash scripts/test.sh tests/systems/test_facet_rag.py::test_run_one_plans_both_facets
bash scripts/test.sh -k "rrf or fuse"
bash scripts/test.sh live               # ONLY the live tests — needs creds, hits real services
```

**Run the full suite after ANY change under `src/utils/`, `src/tools/`,
`src/ragrun/` or `src/systems/`**, and before committing. Those layers are shared
by all five systems, so a subset can't clear a change to them — and the whole
suite is ~16s, cheaper than reasoning about which tests your edit reached.
A selective run prints this reminder on success.

The equivalent by hand, if you need pytest flags the script doesn't pass through:

```bash
DEP_GROUPS="--group dev --group o3-deep-research --group aus-agent"
uv run $DEP_GROUPS pytest                        # whole offline suite
uv run $DEP_GROUPS pytest -m 'live or not live'  # offline + live together
```

**Pass all three dep groups.** `tests/shared/test_mcp_server.py` `importorskip`s
`mcp.server.fastmcp` and `tests/systems/test_aus_agent.py` `importorskip`s
`boto3`, so with `--group dev` alone those tests *skip* and the run is green
having proven nothing about the code they cover. The suite is otherwise skip-free
by design, so **`scripts/test.sh` and CI both fail on any skip** — if you add an
`importorskip`, add its group to `scripts/test.sh`,
`.github/workflows/tests.yml`, and `scripts/git-hooks/pre-commit`.

(Don't name that variable `GROUPS` — it's a bash built-in holding your numeric
group ids, and assigning to it is silently ignored.)

Layout: `tests/contract/` (input/output format conformance against the track
spec), `tests/shared/` (`utils`/`tools`/`mcp` layers), `tests/systems/`
(per-system end-to-end), `tests/aus_agent_context/` (the `ContextLedger` suite),
`tests/dummy_api/` (the real clients over loopback HTTP, see below).

`tests/conftest.py` holds the shared fixtures and *enforces* hermeticism rather
than trusting it — read it before writing tests:

- **`no_network`** (autouse) fails any unmarked test that reaches
  `urllib.request.urlopen`/`socket.create_connection`, naming the URL.
- **`isolated_data_dir`** (autouse) repoints `RAGRUN_DATA_DIR` at a tmp dir so
  `save_run` never writes into the real `data/outputs/`.
- **`no_ambient_creds`** (autouse) strips `SEARCH_API_KEY`/`OPENAI_API_KEY`/AWS
  vars for offline tests — otherwise a "hermetic" test can pass locally only
  because it silently authenticated.
- **`stub_search_tool`** — dummy retrieval backends returning
  spec-shaped payloads; patches `tools.search_tool._DISPATCH`, so the real
  serialization/truncation/error-envelope code stays under test while transport
  is faked. Returns a `calls` dict for asserting engine routing.
- **`scripted_provider`** — dummy LLM implementing the full
  `providers.base.Provider` contract; script it with a list of `ModelTurn`s or a
  `responder(pending_text, turn_index)` callable.
- **`fake_hits` / `fake_search_response`** — canonical ClimbMix payloads in the
  exact shapes `references/{rag,retrieval}-task.md` document.

**Every external API is dummied in the offline suite** — search endpoints via
`stub_search_tool`, model backends via `scripted_provider` — each returning a
response in the documented format, so a pipeline runs end-to-end with zero
network. Mark a test `@pytest.mark.live` to hit the real services instead; each
system keeps at least one so the real path stays exercisable.

`tests/dummy_api/` goes one layer deeper: a local `HTTPServer` speaking each
backend's documented wire format, with the **real** clients pointed at it via
their env vars and nothing patched. That covers what `stub_search_tool` cannot —
URL construction, auth headers, the `User-Agent` the proxy requires, HTTP verb,
request-body shape, and response→`SearchHit` mapping. Those tests are marked
`local_socket` (loopback only, no creds, runs in CI); `tests/dummy_api/conftest.py`
narrows `no_network` rather than disabling it, so a hardcoded hosted URL still
fails.

**Every test needs a docstring, and it must say something the test name does
not** — why the behaviour matters, or what breaks if it regresses. A prose
restatement of the name is worse than nothing. Module docstrings carry the
layer-level "what this file defends and why it's fragile" so per-test ones stay
short. Tests that pin a known `src/` defect are named `*_current_behaviour` and
say so in the docstring, so a fix announces itself by failing.

Enforced by `.github/workflows/tests.yml` on every PR/push and by the
`pre-commit` hook. See the `trec-rag-new-system` skill for the full story.

## RAG Systems (`src/systems/`)

Adding, running, or reviewing a RAG system is covered by the
**`trec-rag-new-system`** skill (package layout, shared `ragrun`/`tools`/`utils`
layers, the strict-vs-rich artifact split, the scaffolder, and the architecture
visualization that must be regenerated + launched whenever a system is developed
or run). Browse the current architecture at `docs/architecture.html`.

## Active Tasks

- **BM25 index (Lucene/Anserini)** — built in `tasks/bm25_index/`. This is a
  *build* task, not a search server: it produced the on-disk Lucene index at
  `data/built-indexes/climbmix-bm25/` (single segment, positions present, ~1.5 TB;
  `.fdt` stored text = 1 TB). Usable for ad-hoc experiments via
  `tasks/bm25_index/boolsearch/BoolSearch.java` (+ `bs.sh`) — a read-only
  full-Lucene-syntax searcher (Boolean `+must`/`-not`, `"phrase"`, `"phrase"~N`
  proximity) over the same mmap'd index. NB: the *hosted* index-server
  (`:8085` / `index-climbmix-bm25.dsync.net`) is **OR-only** — its
  `BagOfWordsQueryGenerator` strips all Boolean operators, so use `BoolSearch`
  for true Boolean/phrase/proximity on Lucene.
- **SSR / Cottontail search (fork stack)** — working in `tasks/ssr_search/`.
  Implements the *Boolean Queries Are All You Need?* (arXiv 2607.11362) approach:
  Cottontail annotative index + Shortest-Substring Ranking (SSR), driven by a
  GCL Boolean query language (`(^ a b)` AND, `(+ a b)` OR, `"phrase"`, `>>`/`<<`
  containment). **This is NOT our Lucene index** — it's a separate C++/Bazel
  engine, our fork `tmp/Cottontail` (remote `rmit-ir/Cottontail`; upstream paper
  repo `tmp/Cottontail-claclark` is a READ reference only, we no longer build it).
  A mamba env (`tasks/ssr_search/env`, gcc 13 + bazelisk) builds the fork's
  `cottontail-jsonl-{index,query,server}` apps; ClimbMix shards index into 26
  stemmed SimpleWarren group-burrows. Served as a fleet of 26 single-burrow
  `cottontail-jsonl-server`s (loopback :7000..:7025, `launch_fork_servers.sh`,
  each memory-bounded by `--cache-budget-mb`) behind `fork_shim.py` (a stdlib
  HTTP fan-out on :8099 via `MultiShardSearchEngine`), reverse-tunneled to
  `index-climbmix-ssr.dsync.net`.
- **Creating local custom index** — working in `tasks/custom_index/`. All
  scripts, logs, and intermediate artifacts for this task live there.
- **Search engine + REST API** — working in `tasks/search_serve/`. Consumes a
  built-index dir (`data/built-indexes/<RUN>/`). Provides `SearchEngine`
  Python library, ad-hoc CLI, FastAPI REST. Designed to extract into a
  standalone repo post-submission.
- **Chunking strategy** — working in `tasks/chunking-strategy/`. Web app
  (FastAPI + vanilla-JS UI) to browse a parquet shard and tune chunking
  strategies live (target band / hard max / overlap dials, words×1.3 token
  estimates, chunk-size distributions). `scripts/chunkers.py` holds the
  strategies and doubles as the pipeline chunking CLI (corpus jsonl in,
  chunk jsonl out). Chunk ids are `<docid>_p<page>` (page from 1, e.g.
  `shard_00000_3908_p1`) so the parent docid is derivable downstream
  (`rsplit("_p", 1)[0]` — unambiguous, rows are pure digits).
- **BM25 `k1`/`b` tuning** — working in `tasks/bm25_tune/`. Tunes BM25 on the
  chunked ClimbMix index (read-only, under `BM25_TUNE_INDEX_DIR`) against
  aus_agent's 1063 keyword queries with a `gpt-oss-20b` Bedrock judge (pooled
  0–3 qrels, cached under `data/bm25-tune/judgments/`). JDK 21 conda env
  in-folder; **`export JAVA_HOME="$PWD/tasks/bm25_tune/env/lib/jvm"`** — the
  test suite needs it too. The plan is `tasks/bm25_tune/PLAN.md`; **WP0/WP6
  judge calibration is a mandatory gate before any sweep spend**, and the
  budget cap is a required operator input (`BM25_TUNE_BUDGET_USD`, currently
  $50) with no default in code. The harness is **corpus-agnostic**: seven
  `BM25_TUNE_*` vars carry the ClimbMix values as defaults (so an unset
  environment reproduces the published run), `make-queries` takes any
  JSONL/TSV/CSV/one-per-line query file, and `calibrate --from-pool` runs the
  mandatory gate on a corpus with no labeled log. Running it on **another index**
  is the **`bm25-parameter-tuning`** skill (`skills/bm25-parameter-tuning/` —
  ours, not vendored, so `check_vendored_skills.py` skips it).

## Stack quirks (lessons learned — keep these out of future debugging time)

### Gunicorn

- **`-c <config>` is resolved against the original cwd, not against `--chdir`.**
  Always pass an absolute path to `-c` when also using `--chdir`. Symptom:
  `Error: 'gunicorn_conf.py' doesn't exist`.
- **Per-worker GPU pinning needs a `pre_fork` hook with a master-side counter.**
  Bare `gunicorn -w 8` does not pin anything — all workers share the
  default device. See `tasks/search_serve/scripts/gunicorn_conf.py` for the
  `itertools.count()` + `os.environ["CUDA_VISIBLE_DEVICES"] = str(rank % N)`
  pattern. Must NOT initialize CUDA in the master (no `--preload` with
  torch.cuda touches) or worker fork breaks the inherited CUDA context.
- **Engine load takes minutes** (model + 64 GB PQ mmap + warm-up). Set
  `--timeout 600` or workers get killed mid-load.

### DiskANN (diskannpy)

- **One libaio io_context per search thread, ~1024 events each.** Stay under
  `/proc/sys/fs/aio-max-nr` (kernel default 65,536): `workers × num_threads ×
  1024 < cap`. Exceeding it throws `io_setup() failed with EAGAIN ->
  std::system_error: Operation not permitted` from C++ and kills the process.
  Conservative production default for serve: `DISKANN_THREADS=4` per worker.
- **Default `num_threads=0` means "use all CPUs"** — on a 256-thread box that
  reserves 256 × 1024 = 262K aio events, 4× over a default cap. Always pass
  an explicit small number for search-side threads.

### Multi-GPU servers

- **Each worker process needs its own SentenceTransformer model copy** (no
  sharing across processes); page-cache shares the index files for free.
  ~600 MB per worker on GPU.
- **Encode serializes per process under concurrency.** Single-worker uvicorn
  cannot use Python concurrency to scale encode — it queues on the GIL and
  the GPU/CPU pipeline. To scale, run N workers (gunicorn) and pin GPUs.

### FastAPI threadpool gotcha (CRITICAL — read before adding endpoints)

- **A FastAPI handler declared with `def` (sync) runs in a 40-thread anyio
  threadpool, not the asyncio event loop.** Within ONE worker, this means
  up to 40 concurrent requests fan into 40 threads that share all per-engine
  state — GIL contention on Python work, race conditions on any non-thread-
  safe C extension.
- We've already been bitten by this: when sweeping the 8-worker gunicorn
  setup at concurrency=8+ we saw (a) `zstandard.backend_c.ZstdError:
  Data corruption detected` (Zstd decompressors are not thread-safe) and
  (b) encode latency exploding from 25 ms to 400+ ms even though each
  worker only had ~1 in-flight request on average (the threadpool stayed
  hot from earlier bursts).
- **Two-part fix when you add an endpoint:**
  1. Make every shared C-extension object thread-safe — either by using
     `threading.local()` per backend or by recreating cheap objects
     per call. `docstore.FlatShardDocStore._decode` already does this for
     the Zstd decoder.
  2. For latency-critical endpoints, declare `async def` and dispatch the
     blocking work via `asyncio.to_thread(...)` — this serializes the
     blocking call per worker (which is what we want for GPU encode and
     DiskANN search anyway, since both already release the GIL internally),
     while letting unrelated requests progress on the loop.

### Multi-GPU benchmark notes (current, post async-refactor)

- **Single-worker peak ≈ 28 req/s** at C=1.
- **4-worker gunicorn (sync def, 1 GPU/worker)** peaked at ~71 req/s at C=8.
- **8-worker gunicorn with async `def` + asyncio.Semaphore(1) per worker
  peaks at 102 req/s at C=32** — 1.7× the previous best, zero errors, and
  encode_p50 stays flat at 24.4 ms across every concurrency level
  (proves per-worker single-stream encode is doing its job).
- C=64 starts to regress (50 r/s) because the kernel listen queue starts
  dropping; for higher real-world load, scale horizontally instead.

### Jina v5 (`jinaai/jina-embeddings-v5-text-nano`)

- **Uses custom `EuroBERT` architecture via `trust_remote_code=True`.** Pull
  in `einops` + `peft` to satisfy the custom code path. The model has
  adapters for `task=retrieval`/`classification`/`clustering`/etc. — the
  ` -retrieval` variant in HF is the pre-merged retrieval-only adapter.
- **ONNX export is NOT viable as of 2026-06-30.** Failure cascade:
  1. `optimum-cli export onnx` rejects EuroBERT (no native `OnnxConfig`).
  2. Legacy `torch.onnx.export(...)` errors with `ScalarType ComplexDouble
     is an unexpected tensor scalar type` (rotary positional embeddings
     use complex tensors).
  3. `torch.onnx.export(..., dynamo=True)` fails at `torch.export.export`
     with a dynamic-shape constraint violation on the `seq` dim.
  Writing a custom `OnnxConfig` + complex-RoPE decomposition is multi-day
  work. **Don't go down this path again without a strong reason.** PyTorch
  CPU + AMX BF16 is competitive (~28 ms p50 single-query encode) and is
  the recommended CPU-only path until upstream gains EuroBERT ONNX support.
- **`get_sentence_embedding_dimension()` returns `None`** on this model —
  probe via a tiny `model.encode("x")` to get the real dim (768).

### CPU inference on Intel Sapphire/Emerald Rapids

- **bf16 + AMX is competitive with single-stream GPU** for small (~140 M)
  embedding models. We measured 28 ms p50 vs 24 ms on L40S at C=1 — within
  noise. GPU only wins decisively for batched inference (large N).
- **Set per-worker `OMP_NUM_THREADS` ≈ physical_cores / n_workers** —
  default oversubscription hurts on multi-worker setups. For an 8-worker
  serve on a 56-core box, `OMP_NUM_THREADS=7` is the sensible per-worker
  share.

### RAGDOLL Evaluation
- **RAGDoll runs TREC-style evaluation for RAG systems** using Pi-backed LLM
  judges. It supports query–passage relevance judging, citation support
  assessment, nugget/rubric scoring, and pairwise system comparison.

- **Inputs and outputs are JSONL-based**, which makes runs easy to reproduce,
  debug, and compare against human qrels. For relevance judging, each query is
  paired with candidate passages and RAGDoll produces automatic relevance labels.
  
## Notes
- Use `uv` for Python dependency management.
- Run commands from the repository root.
- RAGDoll evaluation inputs should use JSONL format.
- For UMBRELA relevance judging, input rows should contain:
  - `qid`
  - `query`
  - `candidates`
  - each candidate should contain `docid` and `doc.segment`
