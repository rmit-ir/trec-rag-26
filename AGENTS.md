Google Groups mailing list: https://groups.google.com/g/trec-rag-2026-participants
TREC RAG 2026 Official Skills: https://github.com/TREC-RAG/trec-rag-skills.git

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

## Active Tasks

- **Creating local custom index** — working in `tasks/custom_index/`. All
  scripts, logs, and intermediate artifacts for this task live there.
- **Search engine + REST API** — working in `tasks/search_serve/`. Consumes a
  built-index dir (`data/built-indexes/<RUN>/`). Provides `SearchEngine`
  Python library, ad-hoc CLI, FastAPI REST. Designed to extract into a
  standalone repo post-submission.

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

### Multi-GPU benchmark notes

- **Single-worker peak ≈ 28 req/s** at C=1, dropping to ~16 req/s at C=16
  (the encode bottleneck).
- **4-worker gunicorn (1 GPU/worker) peaks at ~71 req/s at C=8** (2.6× the
  single-worker baseline). Per-worker encode at C=8 climbs to ~50 ms
  (each worker handling ~2 in-flight requests).
- **8-worker gunicorn currently *regresses* vs 4-worker** at C=8 because of
  the FastAPI threadpool issue above — fix that before drawing conclusions
  about 8-GPU scaling.

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
