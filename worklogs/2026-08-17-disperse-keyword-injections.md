# 2026-08-17 — disperse keyword injections through passages

## Problem

`tasks/llm_judge_robustness/scripts/inject_keywords.py` previously rendered all
generated phrases as one synthetic block at one sentence boundary, for example:

```text
[KEYWORDS: adults, age, begin losing bone mass, bone mass loss onset]
```

That does not model keyword stuffing distributed through passage text.

## Change

The injector now inserts every keyword or multiword key phrase as an independent
raw string at a randomly selected word boundary. Placements are:

- distinct internal boundaries whenever the passage has enough words;
- deterministic from `qid + pid`, making rebuilds reproducible;
- different across passages for the same query;
- wrapper-free: no `[KEYWORDS: ...]` marker or comma-joined keyword block.
- uppercased at insertion time, including every word in multiword key phrases.

Short passages still receive every keyword. If there are more phrases than
internal boundaries, deterministic boundary reuse is allowed rather than
dropping phrases.

## Verification

Focused tests:

```text
bash scripts/test.sh tests/llm_judge_robustness/test_inject_keywords.py
3 passed
```

Static analysis:

```text
uv run --group dev ruff check tasks/llm_judge_robustness/scripts/inject_keywords.py tests/llm_judge_robustness/test_inject_keywords.py
All checks passed!
```

Regenerated 2022 artifacts:

- `data/ragdoll-robustness/injected/keywords/trec_dl_2022.csv`: 2,656 source rows,
  all injected, zero missing keyword entries.
- `data/ragdoll-robustness/derived/ragdoll-inputs/keywords/2022.requests.jsonl`:
  76 queries and 2,655 deduplicated candidates.
- Both regenerated artifacts contain zero occurrences of the legacy
  `[KEYWORDS:` marker.
- The artifacts were regenerated again after uppercase insertion was added;
  inspection confirms phrases such as `ROOT YUCCA PLANT`,
  `ROOTING YUCCA CUTTINGS`, and `YUCCA PROPAGATION` are dispersed in uppercase.

