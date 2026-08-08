# Test119 production runs: verified research-first and Sol default

Date: 2026-08-07

## Objective

Generate two complete TREC RAG 2026 test submissions, preflight their live
execution paths, preserve rich internal traces, and export separate organizer
JSONL files with traces stripped:

1. verified `aus_agent_v2` research-first control (dev30 `0.704159`);
2. original `aus_agent` default method with Sol (dev30 `0.6508`).

Development scores identify the previously measured configurations; they are
not test-set score claims.

## Frozen official input

Path:
`data/official/trec-rag-2026-data/trec-rag-2026/test-data/trec_rag_2026_queries.tsv`

- rows: 119;
- ids: `rag2026-0` through `rag2026-118`;
- SHA-256:
  `72dc2fd358d3eeda973397ccd7a8775545b19a6deaefc67709167eee6a9f8a2c`;
- data checkout revision: `a6255c10119a2984a874f46172d94045168ab1f3`.

The exact preflight input, copied verbatim from row one, was:

> I’m on a hospital nursing DEI council that has to recommend a three-year plan with limited money. Our chief nursing officer wants something that helps recruitment and retention, not just a one-time training. What should we prioritize across nursing school pipeline partnerships, hiring and promotion practices, reporting systems for racism, leadership accountability, and curriculum/continuing education? How should we think about tradeoffs, what outcomes should we measure, and what mistakes would make the plan feel performative to nurses of color?

## Spec freshness

`python scripts/check_vendored_skills.py` compared against official upstream
commit `f281e88f61252662033c681df8b1ed2d0ceda97e`: every vendored official skill
was current. The full log is
`/tmp/trec-rag-vendored-skills-freshness-20260807.log`.

## Exact configurations

The verified control pins Sol, `semantic,keyword`, `k=20`, 500,000 current
context tokens, 40 safety rounds, commit cap 10, prose coverage planning and
the blind atomic scout with at most eight additions. Every experimental
editor, verifier, contract, extra scout, and handoff is explicitly disabled.

The Sol default method pins the original `aus_agent` default prompt, Sol,
`semantic,keyword`, `k=20`, 500,000 current context tokens, 100 safety rounds,
and commit cap 20. It has no isolated v2 planning/scout stage.

The exact preflight, production, resume, monitoring, and export commands are
preserved in:

- `docs/run-verified-research-first-control.md`;
- `docs/run-sol-generator-default-method.md`.

## Live preflight result matrix

Judgment was deterministic structural/trace inspection, not answer-quality
grading. Each row was required to finish, use the pinned method, exercise both
retrieval engines, commit evidence, emit at least one cited answer item, remain
within 1,024 words, and pass `validate_rag_output(submission_output(obj))`.

| configuration | status | engines | calls | committed | references | answer items | words | violations |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| verified research-first | completed | keyword, semantic | search 32; commit 4 | 40 | 31 | 24 | 907 | 0 |
| Sol default method | completed | keyword, semantic | search 14; commit 3; get_documents 1 | 29 | 25 | 32 | 986 | 0 |

Verified-control stage audit: `coverage_plan.enabled=true`,
`plan_critic.enabled=true`; `observable_scout`, `plan_reconcile`,
`coverage_verify`, `audience_verify`, and `finish_review` were all disabled.
The default-method trace contained no v2 plan or critic summaries, as required.

Internal artifacts:

- `data/outputs/aus_agent_v2/20260807T142228368464+1000.i_m_on_a_hospital.output.json`;
- `data/outputs/aus_agent/20260807T142225795820+1000.i_m_on_a_hospital.output.json`.

Raw live logs:

- `/tmp/preflight-sol-aus-v2-research-first-test119-20260807.log`;
- `/tmp/preflight-sol-aus-default-test119-20260807.log`.

## Production execution

Both 119-topic runs were launched with concurrency six after the preflights
passed. After 13 minutes, GNU `xargs`' supported `SIGUSR1` control raised each
existing scheduler to ten workers. This did not restart a process, rebuild the
fixed TODO list, or change any topic's model/method arguments; it only admitted
four more independent topic processes per run. The runbooks record ten as the
reproducible from-start setting. No `429` or sustained gateway pressure followed
the increase. Commands use the `/tmp` uv cache because the sandbox cannot write
the shared uv cache. Completion matrices, export hashes, and final validation
follow below.

Raw evidence preserved from the live session:

- `worklogs/assets/2026-08-07-preflight-sol-aus-v2-research-first-test119.log`;
- `worklogs/assets/2026-08-07-preflight-sol-aus-default-test119.log`;
- `worklogs/assets/2026-08-07-sol-aus-v2-research-first-test119.log`;
- `worklogs/assets/2026-08-07-sol-aus-default-test119.log`.

These logs contain every model-generated retrieval query and the full live
result/progress matrix. Rich per-topic inputs, trace steps, decisions, and
outputs persist under the run ids in `data/outputs/`.

## Production result matrix

| configuration | completed topics | failed attempts | searches | commits | references/topic | words/topic |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| verified research-first | 119 unique | 0 | 3,732 | 507 | 10–40; mean 27.67 | 731–1,024; mean 936.55 |
| Sol default method | 119 unique | 2 superseded | 2,849 | 473 | 7–51; mean 27.87 | 497–1,022; mean 882.50 |

The verified runner's final internal recount printed `verified 119 completed
topics`. Every verified trace had the expected plan/scout control path and no
experimental editor/contract flags.

The default initial queue produced 117 completions. `rag2026-55` failed after
32 commits and `rag2026-112` after 19 commits; both gateway responses were
`400 validation_error` with message `Internal server error`. The identical
resume command found `todo=2/119`, started fresh conversations for only those
IDs, and both completed. The two failed output/trajectory attempts remain
preserved beside the 119 successful attempts.

## Organizer exports

The repository's exporter was extended with exact `--run-id` filtering and a
`--topics` completeness/order gate. It validates every selected organizer row,
checks exact narrative text, rejects unexpected/missing/duplicate completed
topics, and writes only `metadata`, `references`, and `answer`. When an exact
run id is supplied, a preserved `failed` attempt may be ignored only if the
official-topic completeness gate can still find its completed replacement;
running or unknown statuses remain fatal.

| run id | rows | trace rows | violations | bytes | SHA-256 |
| --- | ---: | ---: | ---: | ---: | --- |
| `sol-aus-v2-research-first-test119-20260807` | 119 | 0 | 0 | 1,114,270 | `744c2d0624a1b834b94ad87fbc50548b1957f22a09beb1903230da72fe4986d8` |
| `sol-aus-default-test119-20260807` | 119 | 0 | 0 | 1,049,984 | `d6fcf2c14bb48dfc3f7476032ecf79c6d2704664434266efabe383dcace10fc5` |

Paths:

- `data/outputs/submissions/sol-aus-v2-research-first-test119-20260807/rag_output_trec_rag_2026.jsonl`;
- `data/outputs/submissions/sol-aus-default-test119-20260807/rag_output_trec_rag_2026.jsonl`.

Both exports have 119 unique IDs in official TSV order, exact narrative text,
the exact production run id on every row, and no top-level field other than
`metadata`, `references`, and `answer`.

## Verification

- focused exporter suite: `2 passed`;
- shell syntax for both parallel runners: passed;
- architecture regenerated/launched at `#aus_agent_v2` and `#aus_agent`;
- architecture freshness: `8 systems`, up to date;
- full hermetic suite with loopback permission: `1904 passed, 10 deselected,
  1 warning` in 26.32 seconds;
- full-suite log:
  `worklogs/assets/2026-08-07-test119-production-full-tests.log`.

The two earlier sandboxed full-suite attempts were stopped after every
loopback dummy-API test failed/hung because the sandbox denied local sockets.
The same suite passed immediately with loopback permission; its fixtures still
removed ambient credentials and prohibited hosted network access.
