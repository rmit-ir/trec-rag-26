# Committed-doc diversity across backends (30 dev topics)

_Embeddings: jina-v5; cosine near-dup threshold = 0.9; averaged over 30 topics._

## Within-engine (per-topic mean)

| engine | docs/topic | mean pairwise dist | near-dup rate | Vendi | Vendi/n | unique-contrib | Vendi gain |
|---|--:|--:|--:|--:|--:|--:|--:|
| dense | 13.2 | 0.584 | 0.022 | 6.60 | 0.519 | 0.866 | 6.69 |
| keyword | 10.8 | 0.579 | 0.004 | 5.83 | 0.563 | 0.803 | 7.47 |
| ssr | 12.3 | 0.629 | 0.007 | 6.83 | 0.597 | 0.872 | 6.46 |
| lucene | 14.1 | 0.575 | 0.012 | 6.47 | 0.507 | 0.860 | 6.83 |

- **mean pairwise dist** ↑ = more varied support; **near-dup rate** ↑ = more repetition.
- **Vendi/n** ↑ = committed docs are genuinely distinct (richer support); →1 ideal.
- **unique-contrib** ↑ = more docs no other engine (near-)surfaced (standout/complementary).
- **Vendi gain** ↑ = engine adds more diversity to the pooled union.

Union Vendi (all engines pooled, mean over topics): **13.30**

## Cross-engine committed-docid Jaccard (overlap; low = complementary)

| pair | Jaccard |
|---|--:|
| dense|keyword | 0.030 |
| dense|ssr | 0.023 |
| dense|lucene | 0.023 |
| keyword|ssr | 0.034 |
| keyword|lucene | 0.044 |
| ssr|lucene | 0.032 |
