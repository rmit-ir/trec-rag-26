# chunking-strategy — dataset browser + chunking playground

Web app for deciding the corpus chunking strategy: browse the documents in a
parquet shard, chunk them live with any registered strategy, tweak the dials
(target band, hard max, overlap, tokens-per-word factor), and eyeball how each
chunk reads. Also computes chunk-size distributions over a doc sample.

Token counts are estimated as `words × tokens_per_word` (default 1.3).
Chunk ids follow the production scheme `<docid>#c<k>` (docid derivable via
`chunk_id.rsplit("#c", 1)[0]`, adjacent chunks are `#c<k±1>`).

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
| `band` | paragraph-aware packing into a target token band; a chunk may exceed the band only to keep a paragraph whole, never past the hard max; under-min chunks fold into the previous chunk (with `hard_max >= target_max + target_min` the fold always fits) | `target_min` 200, `target_max` 500, `hard_max` 700 |
| `para_pack` | greedy paragraph packing to a single budget (the chunking-1pct "para" strategy) | `max_tokens` 1024 |
| `fixed` | sliding word window with overlap (the chunking-1pct "fixed" strategy) | `chunk_tokens` 1024, `overlap_tokens` 128 |

All strategies fall back for oversized paragraphs: split at the last single
`\n` inside the budget, else the last sentence end (`.!?。！？`), else a hard
word cut — same hierarchy validated in `docs/chunking-1pct-findings.md`.

## API (what the UI calls)

- `GET /api/info` — corpus + strategy/param specs
- `GET /api/docs?offset&limit` — doc listing with word/token counts
- `GET /api/doc/{i}` — full doc text
- `GET /api/chunks/{i}?strategy=band&target_min=350&...` — chunk the doc live
- `GET /api/stats?sample=200&strategy=...` — chunk-size distribution over the
  first N docs

`chunkers.py` has no web dependencies — the chosen strategy lifts straight
into the production chunking script later.
