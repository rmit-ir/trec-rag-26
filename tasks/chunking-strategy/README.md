# chunking-strategy — dataset browser + chunking playground

Web app for deciding the corpus chunking strategy: browse the documents in a
parquet shard, chunk them live with any registered strategy, tweak the dials
(target band, hard max, overlap, tokens-per-word factor), and eyeball how each
chunk reads. Also computes chunk-size distributions over a doc sample.

Token counts are estimated as `words × tokens_per_word` (default 1.3).
Chunk ids follow the production scheme `<docid>_p<page>` with page starting
at 1 (e.g. `shard_00000_3908_p1`). Parent docid derives via
`chunk_id.rsplit("_p", 1)[0]` (unambiguous — rows are pure digits, so `_p`
never occurs inside a docid), adjacent pages are `_p<page±1>`.

## Run

```bash
uv run --project tasks/chunking-strategy python \
  tasks/chunking-strategy/scripts/app.py \
  --parquet data/climbmix-400b-shuffle/shard_00000.parquet \
  --port 8377
```

Then open `http://<host>:8377/`. The whole shard (~86K docs) is loaded into
memory at startup (~300 MB).

## Strategies (`scripts/chunkers.py`)

| name | idea | dials |
|---|---|---|
| `band` | paragraph-aware packing into a target token band; a chunk may exceed the band only to keep a paragraph whole, never past the hard max; under-min chunks fold into the previous chunk (with `hard_max >= target_max + target_min` the fold always fits) | `target_min` 200, `target_max` 500, `hard_max` 700, `split_over_target` off |
| `para_pack` | greedy paragraph packing to a single budget (the chunking-1pct "para" strategy) | `max_tokens` 1024 |
| `fixed` | sliding word window with overlap (the chunking-1pct "fixed" strategy) | `chunk_tokens` 1024, `overlap_tokens` 128 |

All strategies fall back for oversized paragraphs: split at the last single
`\n` inside the budget, else the last sentence end (`.!?。！？`), else a hard
word cut — same hierarchy validated in `docs/chunking-1pct-findings.md`.

Cross-strategy options:

- `split_over_target` (band): by default a paragraph in the target_max..hard_max
  gray zone is kept whole ("over target" badge); with this on it is split at
  sentences so chunks hug the band.
- `title_chunks` (any strategy, "+title in chunks" in the UI): prepend
  `Page N of document: <doc title>` to every chunk after the first, so later
  chunks carry the doc topic and their position into the embedding (jina v5
  mean-pools, so the marker's position in the chunk doesn't matter). Title =
  first
  non-empty line; if over 30 words it's cut at the last sentence end inside
  the budget, else the last comma, else hard at 30 words. Applied after
  packing — a titled chunk can exceed the hard cap by the title length.

## Chunking step for the index pipeline (standalone CLI)

`chunkers.py` is pure stdlib — no web deps — and doubles as the pipeline
chunking step. Corpus jsonl in, chunk jsonl out, same `{"id", "contents"}`
format `encode_documents.py` consumes; ids become `<docid>_p<page>`:

```bash
python tasks/chunking-strategy/scripts/chunkers.py \
  --strategy band --param target_max=500 --param title_chunks=1 \
  --in work/<run>/corpus/shard_00000.jsonl \
  --out work/<run>/chunked/shard_00000.jsonl
```

(`--in - --out -` for stdin/stdout; stats go to stderr.)

## API (what the UI calls)

- `GET /api/info` — corpus + strategy/param specs
- `GET /api/docs?offset&limit` — doc listing with word/token counts
- `GET /api/doc/{i}` — full doc text
- `GET /api/chunks/{i}?strategy=band&target_min=350&...` — chunk the doc live
- `GET /api/stats?sample=200&strategy=...` — chunk-size distribution over the
  first N docs

`chunkers.py` has no web dependencies — the chosen strategy lifts straight
into the production chunking script later.
