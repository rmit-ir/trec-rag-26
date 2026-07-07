# ClimbMix Chunking Comparison Plan

This file is the source of truth for the local chunking comparison experiment.
Update the checklist and decision log here after each completed step so the
experiment does not drift across scripts, reports, and discussion notes.

## Goal

Compare chunking strategies locally before embedding or index construction.
The experiment is statistics-only: it measures coverage, truncation, chunk
counts, overlap overhead, and long-document behavior. It does not build dense
embeddings, BM25 indexes, DiskANN indexes, or retrieval services.

## Baseline Input

Use the completed 1% ClimbMix corpus profile as the input source:

- Corpus profile run: `onepct`
- Sample: 66 / 6,543 shards, approximately 1.01% by shard count
- Documents: 660,000
- Seed: `20260703`
- Max docs per shard: 10,000
- Structure rule set: `tightened-primary`
- Raw parquet input: `data/climbmix-profile-sample/raw/`
- Manifest: `data/climbmix-profile-sample/manifests/onepct/sample_manifest.jsonl`
- Corpus stats: `data/climbmix-profile-sample/stats/onepct/corpus_stats.json`
- Corpus report: `tasks/corpus_profile/reports/corpus_profile.md`

## Output Policy

Shareable reports and figures must live inside `tasks/chunking_profile/`, not
under `data/`, because they are useful artifacts for group discussion.

Large or mechanical intermediate files may live under `data/chunking-profile/`
because they are not meant for direct sharing or git commits.

Planned layout:

```text
tasks/chunking_profile/
  EXPERIMENT_PLAN.md
  README.md
  pyproject.toml
  uv.lock
  scripts/
    build_eval_sample.py
    compare_chunkers.py
    render_report.py
    run_chunking_profile.sh
  reports/
    chunking_comparison.md
    teams_post.md
    figures/<run_id>/
    examples/<run_id>/

data/chunking-profile/
  manifests/<run_id>/
  samples/<run_id>/
  stats/<run_id>/
  chunks/<run_id>/        # optional; only if we need persisted chunk text
```

## Experiment Modes

Run the experiment in three stages:

| mode | target docs | purpose |
|---|---:|---|
| `smoke` | 500 | Validate scripts, schema, logging, and report rendering. |
| `sample` | 5,000 | Produce first human-readable comparison and inspect examples. |
| `onepct` | 660,000 | Final local statistics over the current 1% corpus sample. |

Sampling must be deterministic. Use the same seed unless there is a strong
reason to change it:

```text
SEED=20260703
```

## Evaluation Sample Design

For `smoke` and `sample`, build a deterministic stratified subset from the
`onepct` corpus profile input.

Also force the longest documents into the smaller evaluation modes so the
long-document fallback is actually exercised:

| mode | forced longest docs |
|---|---:|
| `smoke` | 20 |
| `sample` | 100 |

Stratify by:

- approximate-token bucket:
  - `<=128`
  - `129-256`
  - `257-512`
  - `513-1024`
  - `1025-2048`
  - `2049-4096`
  - `4097-8192`
  - `>8192`
- primary structure category:
  - `clean_text`
  - `outline_or_markdown_like`
  - `empty_or_tiny`
  - `table_or_record_like`
  - `html_or_markup_like`
  - `strong_code_like`
- long-tail flag:
  - always include or oversample `>8192` approximate-token documents.

Each sampled document must preserve:

- parent doc id
- source shard filename
- row number within shard
- primary structure category
- noise flags
- original character count
- approximate token count

## Chunking Strategies

Compare these strategies in the first experiment:

| strategy | description | role |
|---|---|---|
| `first_512` | Keep only the first 512 approximate tokens. | Cheap baseline; expected to truncate many docs. |
| `first_1024` | Keep only the first 1024 approximate tokens. | Larger prefix baseline. |
| `fixed_512_overlap_64` | Fixed 512-token chunks with 64-token overlap. | Common dense-retrieval baseline. |
| `fixed_1024_overlap_128` | Fixed 1024-token chunks with 128-token overlap. | Fewer, larger chunks. |
| `paragraph_aware_512` | Prefer paragraph boundaries, cap near 512 tokens. | Better text coherence for clean prose. |
| `paragraph_aware_1024` | Prefer paragraph boundaries, cap near 1024 tokens. | Coherent larger chunks. |
| `hybrid_short_whole_long_chunk` | Keep short docs whole; paragraph-aware chunk long docs; cap extreme long-doc fanout at 128 chunks using head/tail anchors plus uniform middle coverage. | Main candidate for production indexing. |

Approximate-token estimates may use the current profile convention
`ceil(char_count / 4)` for the first pass. Exact tokenizer counts can be added
later if the selected embedding model requires tighter budgeting.

## Metrics

Report all metrics overall and grouped by length bucket and structure category.

| metric | what it measures | why it matters |
|---|---|---|
| `chunks_per_doc` | Number of chunks produced per parent document. | Controls index size and parent fanout. |
| `tokens_per_chunk` | Chunk length distribution. | Checks fit with encoder context and retrieval granularity. |
| `coverage_rate` | Fraction of original approximate tokens retained. | Shows how much content survives the strategy. |
| `truncation_rate` | Fraction of documents that lose content. | Exposes prefix-only loss. |
| `overlap_overhead` | Repeated token mass introduced by overlap. | Estimates index bloat from overlap. |
| `parent_doc_fanout_p50/p95/p99` | Chunk count percentiles per document. | Detects long-document blow-up. |
| `empty_chunk_rate` | Empty or tiny chunks produced by a strategy. | Catches chunker bugs and bad boundary logic. |
| `long_doc_behavior` | Metrics restricted to `>8192` token docs. | Confirms extreme documents have a controlled fallback. |

## Report Requirements

The shareable report should be short and slide-friendly:

- one executive summary section
- one strategy comparison table
- one coverage/truncation figure
- one chunks-per-document figure
- one tokens-per-chunk figure
- one long-document behavior table
- a small appendix of before/after examples

The MS Teams summary should be a separate short file:

```text
tasks/chunking_profile/reports/teams_post.md
```

## Decision Criteria

Prefer a strategy that:

- keeps short documents intact when reasonable
- avoids first-window truncation as the main retrieval path
- controls chunk count for very long documents
- keeps parent doc ids so final citations can point back to ClimbMix documents
- does not explode index size through excessive overlap
- produces readable chunks for clean text and acceptable chunks for structured text

The expected first candidate is:

```text
hybrid_short_whole_long_chunk
```

This is not final until it wins the local statistics comparison.

## TODO

Update this checklist after each completed step.

- [x] Freeze local experiment plan and output policy.
- [x] Create task-local `pyproject.toml`, `.gitignore`, and `README.md`.
- [x] Implement `build_eval_sample.py`.
- [x] Implement chunking strategies in `compare_chunkers.py`.
- [x] Implement report rendering in `render_report.py`.
- [x] Implement unattended wrapper `run_chunking_profile.sh`.
- [x] Run `smoke` mode and inspect logs.
- [x] Inspect before/after examples from `smoke`.
- [x] Run `sample` mode and generate first shareable report.
- [ ] Review figures and metrics with group.
- [ ] Adjust strategy definitions if needed.
- [ ] Run `onepct` mode over 660,000 docs.
- [ ] Produce final `tasks/chunking_profile/reports/chunking_comparison.md`.
- [ ] Produce final `tasks/chunking_profile/reports/teams_post.md`.
- [ ] Decide whether to proceed to embedding/index experiments.

## Decision Log

- 2026-07-07: Reports, figures, and shareable examples for this task should be
  written under `tasks/chunking_profile/reports/`. Large intermediate sample,
  stats, and optional chunk dumps may go under `data/chunking-profile/`.
- 2026-07-07: The comparison starts as a local stats-only experiment. EC2,
  embeddings, BM25, dense indexes, and DiskANN are out of scope for this phase.
- 2026-07-07: `smoke` completed with 500 / 500 docs processed and 0 errors.
  The smoke sample intentionally overrepresents rare structure categories and
  long-tail documents, so its metrics validate the pipeline but should not be
  interpreted as natural corpus-level rates.
- 2026-07-07: Updated `build_eval_sample.py` so `smoke` and `sample` force in
  top-longest documents. The first smoke run did not trigger the hybrid
  `max_chunks_per_doc=64` cap, so the sample design needed explicit long-doc
  stress cases before larger runs.
- 2026-07-07: Reran `smoke` after forcing top-longest documents. The hybrid
  cap is now exercised: long-doc max chunks is 64, long-doc p95 chunks is 64,
  and long-doc retained token rate drops to 58.17%. This confirms the fanout
  cap works, but its coverage tradeoff needs review before larger runs.
- 2026-07-07: Updated the hybrid strategy from `max_chunks_per_doc=64` with
  simple head/tail selection to `max_chunks_per_doc=128` with
  `head_tail_anchors_uniform_middle`: keep 8 head chunks, keep 8 tail chunks,
  and fill remaining slots with evenly spaced middle chunks.
- 2026-07-07: Reran `smoke` with the updated hybrid strategy. The hybrid
  long-doc max and p95 chunks are now 128. Long-doc retained token rate improved
  from 58.17% under the 64 head/tail cap to 91.32% under the 128
  head/tail-anchor plus uniform-middle cap. Overall retained token rate is
  92.86%, overall truncation rate is 2.60%, and mean chunks/doc is 8.10.
- 2026-07-07: Fixed smoke example generation before manual inspection. `FORCE=1`
  now clears stale example files, examples show representative first/middle/last
  selected chunks, and saved examples prioritize truncated / long-tail docs.
  Hybrid examples now include capped documents with selected positions such as
  1, 2, 18, 49, 80, 111, 127, and 128.
- 2026-07-07: Ran `sample` mode with 5,000 docs, including 434 long-tail docs
  and the top 100 longest docs. The run processed 5,000 / 5,000 docs with 0
  errors. Hybrid retained 98.49% of overall approximate tokens, truncated 0.26%
  of docs, averaged 4.19 chunks/doc, and retained 97.71% of long-doc tokens
  with long-doc p95 chunks/doc at 102.35 and max chunks/doc capped at 128.
