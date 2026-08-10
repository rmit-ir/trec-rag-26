# 2026-08-10 — brief-base-t119 vs Sol research-first test119

## Objective

Compare `brief-base-t119` with
`sol-aus-v2-research-first-test119-20260807` using the same native RAGDoll
arena method as the 2026-08-07 organizer-baseline comparison: Luna judge,
medium thinking, seed 13, citation-free organizer answer text, and one
deterministically randomized orientation per shared topic.

## Exact inputs

| run_id | source | rows | SHA-256 |
|---|---|---:|---|
| `brief-base-t119` | `/research/remote/petabyte/users/oleg/trec_rag_26_data/outputs/submissions/brief-base-t119/rag_output_trec_rag_2026.jsonl` | 119 | `291765f4665301330afdf013b30a78c7a36942345c0a1d7c15415d4196d1ddc3` |
| `sol-aus-v2-research-first-test119-20260807` | `data/outputs/submissions/sol-aus-v2-research-first-test119-20260807/rag_output_trec_rag_2026.jsonl` | 119 | `744c2d0624a1b834b94ad87fbc50548b1957f22a09beb1903230da72fe4986d8` |

Both runs contain all and only the 119 official qids. Every narrative is
byte-equivalent to the corresponding value in
`data/official/trec-rag-2026-data/trec-rag-2026/test-data/trec_rag_2026_queries.tsv`,
and both produce zero `validate_rag_output` violations.

The exact structural audit is
`worklogs/assets/2026-08-10-brief-base-vs-research-first-structural.py`.

## Structural comparison

| measure | brief-base | research-first |
|---|---:|---:|
| narratives | 119 | 119 |
| mean words | 830.18 | 936.55 |
| min / max words | 554 / 1007 | 731 / 1024 |
| mean answer objects | 21.77 | 24.44 |
| mean references | 25.82 | 27.67 |
| mean citations per object | 2.034 | 1.660 |
| uncited objects | 37 | 410 |
| uncited-object rate | 0.014280 | 0.140990 |

Mean per-topic reference-set Jaccard is `0.090760`, so the systems use
substantially different evidence.

## Adoption and dry-run checks

- The local RAGDoll pin is
  `1f0671908ab6dc581a61648463e3566ba413b480`; official GitHub `main` returned
  the same commit on 2026-08-10.
- Current official Pi `@earendil-works/pi-coding-agent@0.84.1` was installed in
  `/tmp/brief-base-ragdoll-pi-0.84.1` for this session.
- Native `ragdoll arena compare-all --dry-run` loaded the organizer files and
  reported exactly 119 tasks, proving 119 shared qids and no query mismatch.
- No prior native RAGDoll judgments for this exact pair were found under
  `data/outputs/ragdoll-arena/`.

## Blocked preflight

The required native `ragdoll doctor --probe` stopped before arena execution:

```text
OpenAI API error (401): invalid_api_key — Signature expired
```

The credential signature was dated 2026-08-07 and was expired by the
2026-08-10 probe. The probe produced no assistant text, and **zero arena
judgments were purchased or materialized**. Exact redaction-safe log:
`worklogs/assets/2026-08-10-brief-base-vs-research-first-ragdoll-doctor.log`.

After `OPENAI_API_KEY` is refreshed, rerun the doctor probe, then execute from
`evaluation/ragdoll`:

```bash
set -o pipefail
set -a
source ../../.env
set +a
UV_CACHE_DIR=/tmp/brief-base-compare-uv-cache PI_OFFLINE=1 uv run --no-sync ragdoll arena compare-all --answers /research/remote/petabyte/users/oleg/trec_rag_26_data/outputs/submissions/brief-base-t119/rag_output_trec_rag_2026.jsonl --answers ../../data/outputs/submissions/sol-aus-v2-research-first-test119-20260807/rag_output_trec_rag_2026.jsonl --output-dir ../../data/outputs/ragdoll-arena/brief-base-t119-vs-sol-aus-v2-research-first-test119-20260810 --agent-binary /tmp/brief-base-ragdoll-pi-0.84.1/node_modules/.bin/pi --agent-state-dir /tmp/brief-base-ragdoll-pi-agent --model mantle/openai.gpt-5.6-luna --thinking medium --seed 13 --max-concurrency 8 --timeout-seconds 300 --overwrite 2>&1 | tee /tmp/brief-base-vs-research-first-ragdoll-full.log
```
