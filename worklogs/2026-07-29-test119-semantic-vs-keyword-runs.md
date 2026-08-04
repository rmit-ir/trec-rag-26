# 2026-07-29 — Test-set generation: 119 topics × {semantic, keyword}

First aus_agent runs over the **official TREC RAG 2026 test topics**, and the
first test-set runs on the **chunk-native** retrieval/commit path (both dense
and BM25 now return `<docid>_p<page>` chunk ids — see
`worklogs/2026-07-28-chunked-bm25-cutover-viewer-and-page-prefix.md`).

Two single-engine arms so each retrieval method's effect on the test set can be
read in isolation; everything else held constant.

## Configuration (all decisions confirmed with the user before launch)

| Setting | Value | Note |
| --- | --- | --- |
| Topics | `data/official/trec-rag-2026-data/trec-rag-2026/test-data/trec_rag_2026_queries.tsv` | 119 topics, `rag2026-0` … `rag2026-118` |
| Arms | `--search-backends semantic` / `--search-backends keyword` | dense Jina-v5 DiskANN vs hosted BM25 (both chunked) |
| Backend / model | `openai` / `gpt-5.6-luna` | same as every prior comparison run (dev-30 per-engine, prompt A/B) |
| Prompt variant | `default` | `prompts/system/default.md` (the chunk-native/navigation baseline) |
| `--k` | **20** | raised from the dev-30 default of 10 |
| `--max-committed-per-step` | **20** | raised from the dev-30 default of 10 |
| `--context-token-budget` | 500000 (default) | |
| `--safety-max-rounds` | 100 (default) | |
| Run ids | `test-semantic-119`, `test-keyword-119` | |
| Launch | **both arms in parallel** | user's choice; ~half the sequential wall-clock |
| Resumability | `--skip-existing` | re-running the script only fills gaps for the same run-id |

`k`/`max-committed-per-step` = 20 is the **only** intentional deviation from the
dev-30 settings, so test-set numbers are not directly comparable to
`dev-dense-30` / `dev-keyword-30` on per-topic commit counts.

## Pre-launch check

Probed both engines through the real tool path
(`tools.search_tool.run_search_tool`, k=2, "nuclear reactor safety"):

```
semantic OK ['shard_00754_44807_p1', 'shard_05907_13961_p1']
keyword  OK ['shard_04448_8044_p22', 'shard_05366_3197_p19']
```

Both live and returning chunk (`_pN`) ids — confirming the chunked BM25 cutover
is in effect for this run.

## Driver

`tasks/task-comparison/scripts/run_test119_engines.sh` (new; mirrors
`gen_per_engine_dev30.sh` but forks the two arms and `wait`s on both).

```bash
bash tasks/task-comparison/scripts/run_test119_engines.sh 2>&1 | tee /tmp/test119.log
```

Per-arm logs: `tasks/task-comparison/logs/test-{semantic,keyword}-119.log`
(gitignored). Outputs: `data/outputs/aus_agent/<ts>.<qidslug>.{output,trajectory}.json`,
selected by `metadata.run_id`.

## Cost estimate (pre-run, from the dev-30 arms)

Median per-topic duration 45.0 s (dense) / 49.4 s (keyword), median 16 steps.
Per-topic total tokens ranged ~50 k (dense sample) to ~158 k (keyword sample).

- Sequential estimate: ~3.3 h wall-clock.
- **Parallel (chosen): ~1.7 h.**
- Tokens: ~12–19 M per arm, **~25–30 M total** through luna.

Raising `k` 10→20 pushes the token figure up (more staged text per search call),
so treat the above as a floor.

## BUG FOUND MID-RUN — `get_documents` crashed the topic it was called on

At ~25 min (38–39 topics/arm) each arm had **one hard failure**, same cause:

```
File "src/systems/aus_agent/agent.py", line 1235, in run_agent
    tb.add_tool_call(...)
File "src/ragrun/trajectory.py", line 149, in add_tool_call
    returned_docids = [hit["docid"] for hit in returned]
TypeError: string indices must be integers, not 'str'
```

**Cause.** `TrajectoryBuilder.add_tool_call(returned=...)` expects a list of hit
**dicts** and derives strict `returned_docids` via `hit["docid"]`. The `search`
branch honours that (`returned = [{"docid":…, "score":…}, …]`, see
`tools/search.py:176`). The `get_documents` branch added in the chunk-native
work passed a list of unit-id **strings** instead, so `hit["docid"]` indexed a
string and raised. Any topic where the model called `get_documents` died with
`status=failed` (1 sentence, 0 references).

**Why it escaped the earlier test.** In the 10-topic `chunknav-dev10` run
`get_documents` was invoked **0 times**, so the branch never executed on real
data. It only fired at test-set scale — the higher `k=20` and the broader
test topics evidently push the model to read adjacent pages.

Failure rate before the fix: 1 of ~38 topics per arm (~3%).

**Fix** (`agent.py`, get_documents branch) — mirror the search hit shape, and
keep unit ids where unit ids belong (`context.staged`):

```python
returned = [{"docid": str(d["docid"]), "score": d.get("score")}
            for d in documents]
context = {"staged": [str(d["id"]) for d in documents],
           "committed": [], "rejected": []}
```

So strict `returned_docids` are PARENT docids (organizer-facing, consistent with
search) while `context.staged` stays unit/chunk ids (internal).

**Regression test** — `test_get_documents_records_hit_dicts_not_id_strings` in
`test_context.py` pins the contract: builds the get_documents document shape,
calls `add_tool_call`, asserts `returned_docids == parent docids` and
`context.staged == unit ids`. Suite: **48/48 pass**.

### Recovery procedure

1. Killed the batch (driver + two orphaned `run.py` children by pid) so it would
   stop emitting corrupt artifacts.
2. Applied the fix + regression test.
3. Moved the non-completed artifacts aside (scratchpad, **not deleted**):
   `test-semantic-119/rag2026-14` + `test-keyword-119/rag2026-33` (failed) and
   `rag2026-40` / `rag2026-42` (mid-flight when killed) — 4 topics, both
   `.output.json` and `.trajectory.json`.
4. Re-ran the same script. `--skip-existing` preserved the completed work and
   picked up exactly the remainder:
   ```
   --skip-existing: 39 of 119 topics already answered by run-id 'test-semantic-119'; running 80
   --skip-existing: 41 of 119 topics already answered by run-id 'test-keyword-119'; running 78
   ```

Net cost of the bug: ~4 topics re-run; no completed work lost.

## Results

**Both arms 119/119 `completed`, exit 0, zero failures, zero tracebacks.**
119 distinct `narrative_id`s per arm (no duplicate/superseded files on disk).
Restarted portion ran 03:47 → 04:44 (keyword done 04:39, semantic 04:44):
**~56 min wall-clock** for the 80/78 remaining topics — comfortably under the
~1.7 h whole-batch estimate.

| | test-semantic-119 | test-keyword-119 |
| --- | --- | --- |
| topics completed | 119/119 | 119/119 |
| search calls | 1073 | 1070 |
| commit_context steps | 284 | 281 |
| `get_documents` calls | 1 | 4 |
| committed units | 2182 (median 18/topic) | 2040 (median 16/topic) |
| chunk-level commits (`_pN`) | 2182/2182 = **100%** | 2040/2040 = **100%** |
| rejected units | 6098 | 6540 |
| selection ratio (committed / retrieved) | **0.264** | **0.238** |
| topics committing >1 page of one doc | **42/119 (35%)** | **44/119 (37%)** |
| `output.json` refs (parent docids) | median 16, range 3–34 | median 14, range 4–30 |
| answer sentences | median 23 | median 23 |
| wall-clock / topic | median 39.6 s, max 133.9 s | median 36.7 s, max 86.7 s |
| tokens (total / processed) | 14.34 M / 9.09 M | 15.31 M / 10.12 M |
| peak context tokens | median 30,794 | median 34,827 |

Combined ≈ **29.7 M tokens**, in line with the 25–30 M pre-run estimate even
with `k` doubled to 20.

### Observations

- **Semantic is the more selective arm** — it commits a larger share of what it
  retrieves (0.264 vs 0.238) AND more units per topic (median 18 vs 16), i.e.
  its candidate pool is denser in keepable material rather than merely larger.
  Keyword compensates with a wider funnel (6540 rejected vs 6098).
- **The chunk-native path is genuinely exercised, not merely tolerated**:
  ~35–37% of topics commit **more than one page of the same parent document**
  as distinct units. Under the old parent-docid ledger those commits would have
  collapsed into one, losing page-level provenance. Compare the dev-10 run,
  where this was 5/10 — the behaviour holds at scale.
- **Peak context stays ~30–35 k tokens**, an order of magnitude under the 500 k
  budget, so no topic came near budget exhaustion. Nothing here argues for
  raising the budget; if anything the ledger compaction is doing its job.
- **`get_documents`: 5 calls across 238 runs (~2%)** — 1 semantic, 4 keyword.
  Rare but real, and every post-fix call succeeded. This is the same call path
  that crashed pre-fix, so the fix is validated end-to-end on real data, not
  only by unit test. The low rate still suggests the prompt's
  "do not call another tool merely to fetch the same document" line suppresses
  proactive adjacent-page reading; distinguishing "read MORE" from "re-fetch"
  remains an open follow-up.
- `k`/`max-committed` = 20 (vs the dev-30 default of 10) means per-topic commit
  counts here are **not** comparable to `dev-dense-30` / `dev-keyword-30`.

### Artifacts

- Outputs: `data/outputs/aus_agent/*.{output,trajectory}.json`, selected by
  `metadata.run_id` ∈ {`test-semantic-119`, `test-keyword-119`}.
- Hand-off bundle for external analysis:
  `/tmp/trec-rag26-test119-runs.tar.gz` (29 MB; 113 MB unpacked) — one dir per
  arm, 119 output+trajectory pairs each, plus a self-contained `README.md`
  covering the config, the chunk-id scheme (unit ids internally vs collapsed
  parent docids in `references`, with `trace.output.references_full` retaining
  page-level provenance), and the `"Page N of document:"` text-prefix artifact.
  **NB:** `/tmp` is not durable — re-create from `data/outputs/` if needed later.
- Per-arm logs: `tasks/task-comparison/logs/test-{semantic,keyword}-119.log`
  (gitignored; **truncated on restart**, so their internal counters cover only
  the post-fix pass — the on-disk `output.json` set is the authoritative record).
- Embedding fine-tuning side-car (added 2026-07-30):
  `/tmp/trec-rag26-test119-search-labeled.jsonl` (46 MB; `.gz` 13 MB), built by
  `tasks/task-comparison/scripts/build_finetune_dataset.py`. See
  "Chunk-level labelled search data" below.
- Crash artifacts from the pre-fix pass: session scratchpad
  `…/scratchpad/test119-failed/` (6 files: 2 failed topics with both
  output+trajectory, 2 killed-mid-flight with output only). Session-local — copy
  to `worklogs/assets/` if the failing trajectory is worth keeping as evidence.

## Chunk-level labelled search data (2026-07-30)

Follow-up ask: the bundle's `trajectory.json` looked like it had neither the
result **text** nor the real **chunk ids** — only parent docids. Both were in
fact present, just not where you'd look:

- `result[].returned` / `returned_docids` are **parent docids by design** —
  that is the organizer-facing contract (`ragrun/trajectory.py:149`).
- The chunk ids *and* full text are inside the tool call's `output` **string**
  (the raw search payload: `id`, `docid`, `kind`, `score`, `text`, `truncated`).
- `output.json.trace` keeps the ledger (`context.staged/committed/rejected`) at
  unit granularity but **strips text**.

So nothing needed re-running — only re-projecting. Originals are left
**byte-identical** (verified by `diff -rq` against the shipped tarball);
everything derived goes to one new side-car file.

`tasks/task-comparison/scripts/build_finetune_dataset.py` → one JSONL,
**one row per search call**:

```json
{"run_id", "engine", "query_id", "topic", "call_index",
 "search_query", "k", "n_positive", "n_negative", "n_unjudged",
 "results": [{"id","docid","chunk","rank","score","label","reason",
              "prefix_chars","text","commit_reason"}]}
```

`results` stays in engine rank order; every hit carries its label.

| | value |
| --- | --- |
| rows (search calls) | 2143 (1073 semantic + 1070 keyword) |
| topics | 119 × 2 arms |
| labelled hits | 4857 positive / 12889 negative / 342 unjudged |
| rows with both a positive and a negative | 1998 / 2143 (93%) |
| size | 46 MB (13 MB gz) |
| truncated passages | 0 — every hit carries full chunk text |

### The ledger is not a clean positive/negative split

Taking `rejected` at face value would have poisoned the negatives. Three cases
had to be separated (`classify()`):

- **481 "rejections" are actually positives** — 355 `duplicate/already
  committed; later occurrence compacted` + 126 the within-batch variant. The
  chunk *was* committed; a later search re-staged it and the ledger compacted
  the repeat. A further 75 ids were "not selected" at one step but committed at
  another. Rule applied: **committed anywhere in the topic ⇒ positive**.
- **444 rejections carry no judgement at all** — `staged batch expired after
  invalid commit_context: ValueError: cannot commit documents outside the
  staged context: …`. The model tried to commit an id it had not staged, the
  call failed, and the *entire* staged batch was voided as "rejected". These
  are labelled `unjudged` (342 survive after the committed/duplicate rules) and
  should be **excluded from training**, not used as negatives.
- The remaining `not selected for committed context` (12668) and `not retained`
  (77) are genuine non-selections → negatives, and they are *hard* negatives:
  same top-k pool, frequently out-ranking the positives.

Verified: 0 ids labelled both positive and negative within a topic; 0 empty
texts; rank order monotonic; `id == docid + "_pN"` for every hit.

### Two caveats for the fine-tune

- **`prefix_chars`** — chunks after the first begin with a literal
  `"Page N of document: <title>\n\n"` (chunker `title_chunks=1`, known debt).
  It is layout metadata that leaked into indexed content, so the *embedding
  model saw it at retrieval time*. Rather than shipping a second stripped copy
  of every passage, each hit reports the prefix length; strip with
  `text[prefix_chars:]`. Decide deliberately — training on the stripped text
  creates a train/serve mismatch until the corpus is re-chunked.
- **Scores are engine-native** (inner product vs BM25) and not comparable
  across arms; `label` is comparable, `score` is not.

### Follow-up worth doing

The `cannot commit documents outside the staged context` failure is a **real
agent bug**, not just a data nuisance: 444 staged chunks across the two arms
were thrown away without judgement because one hallucinated id voided the whole
batch. Committing the valid subset and reporting the invalid ids back to the
model would recover those decisions — and would have produced more committed
context in those topics.
