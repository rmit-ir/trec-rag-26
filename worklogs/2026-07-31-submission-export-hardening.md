# Submission exporter hardening

Date: 2026-07-31

Branch: `feat/submission-hardening`

## Scope and ownership boundary

Harden `scripts/export-rag-submission.py` so one export is checked as a complete
TREC RAG 2026 RAG-task submission, rather than as 119 unrelated schema-valid
objects. This session did not change RAGDoll evaluation, BM25 tuning, or their
tests and configuration.

No commit was created; the changes are intentionally left in the working tree
for review.

## Canonical requirements checked

The vendored `trec-rag-2026-track-guidelines` skill v0.6.0 was used as the
submission-format specification. Before changing the exporter, vendored skill
freshness was checked with:

```bash
python3 scripts/check_vendored_skills.py
```

All three official vendored skills were current: Pyserini REST API v0.3.0,
track guidelines v0.6.0, and ClimbMix corpus creation v0.1.0.

The official data submodule was initialized for an end-to-end smoke check:

- repository revision: `a6255c10119a2984a874f46172d94045168ab1f3`
- test TSV SHA-256:
  `72dc2fd358d3eeda973397ccd7a8775545b19a6deaefc67709167eee6a9f8a2c`
- test TSV: `trec-rag-2026/test-data/trec_rag_2026_queries.tsv`
- expected coverage: 119 narratives, `rag2026-0` through `rag2026-118`

## Previous gaps

The old exporter validated each artifact separately and removed internal trace
data, but it could still emit a submission with missing or unknown narratives,
incorrect official narrative text, mixed run metadata, or non-official row
ordering. It also wrote directly to the destination and could replace a prior
submission before every artifact had been checked.

The shared RAG validator checked the type of `answer[].text` but not the
specification's explicit non-empty-string requirement, so an empty answer item
could reach the exporter without a violation.

## Changes

- Added an explicit official topics TSV input, defaulting to the pinned official
  data submodule path.
- Require explicit expected `team_id` and `run_id` at the CLI boundary.
- Validate the topics TSV shape, unique IDs, exact 119-ID coverage, and official
  order; report its raw SHA-256 for provenance.
- Require exactly one successful internal artifact per official narrative.
- Match `metadata.narrative` byte-for-text against the corresponding TSV field.
- Reject mixed `team_id`, `run_id`, or `run_desc` values across artifacts.
- Preserve allowed participant-defined metadata, uncited references, empty
  citation arrays, and direct docid citations.
- Validate every artifact before writing, serialize in official topic order,
  strip internal trace data, prevent input/output path collisions, and replace
  the output atomically.
- Enforce the official non-empty `answer[].text` rule without adding stylistic
  checks; literal whitespace and Markdown remain structurally valid.
- Added exporter-level and shared-validator contract coverage.

## Verification

Static checks:

```bash
git diff --check
python3 -m py_compile scripts/export-rag-submission.py tests/contract/test_export_rag_submission.py
```

Both completed successfully.

Targeted exporter and RAG-output contract tests:

```bash
bash scripts/test.sh tests/contract/test_export_rag_submission.py tests/contract/test_output_rag_json.py
```

Result: 96 passed. Log: `/tmp/trec-rag-exporter-tests.log`.

All contract tests:

```bash
bash scripts/test.sh contract
```

Result: 251 passed. Log: `/tmp/trec-rag-contract-tests.log`.

Full hermetic offline suite, required because `src/ragrun/outputs.py` changed:

```bash
bash scripts/test.sh
```

Result: 959 passed, 6 live tests deselected, 1 existing Starlette deprecation
warning. Log: `/tmp/trec-rag-full-tests.log`.

A CLI smoke run generated 119 completed temporary artifacts directly from the
official TSV, exported them with the default organizer-facing projection, then
independently parsed the JSONL and checked its 119 IDs, official order, and
top-level keys. Result: 119 ordered rows and the same official TSV checksum.
Log: `/tmp/trec-rag-export-official-smoke.log`. Temporary artifacts were
removed after validation.

## Not verified

- No real system output exists in this checkout to export as a candidate run.
- No submission was uploaded to an organizer portal, and no organizer-hosted
  validator was invoked.
- Live service tests were not run; they are unrelated to file-format export and
  require credentials/network services.
