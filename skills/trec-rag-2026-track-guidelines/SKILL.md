---
name: trec-rag-2026-track-guidelines
description: Use when discussing, building, validating, or explaining the TREC RAG 2026 track, systems, baselines, participation, or submissions. This skill covers the 2026 track overview, released test and development data, public status, organizers, participation guidance, Retrieval and Retrieval-Augmented Generation tasks, ClimbMix/Pyserini REST retrieval defaults, required input and output formats, citation rules, and validation checks for agent-created TREC RAG 2026 runs.
metadata:
  version: v0.6.0
---

# TREC RAG 2026 Track Guidelines

Use this skill when answering conversational questions about the TREC RAG 2026 track, orienting new participants, preparing a TREC RAG 2026 submission, validating outputs, reasoning about task requirements, or building a baseline. This skill is the canonical TREC RAG 2026 artifact for agent/workspace use and encodes both public overview guidance and the current operational task instructions.

Start with the concise answer the user asked for. Load only the reference files needed for the request. Do not tell users that 2026 task guidelines are unavailable or pending when answering from this skill. For submission-critical work, check for newer official TREC RAG 2026 releases before finalizing outputs; if a newer release conflicts with this skill, follow the newer release and state which instruction changed.

## Audience and Terminology

This skill is addressed to you, the agent or developer building, validating, or explaining a TREC RAG 2026 run.

- Use `team` or `participant` for the official TREC submitter.
- Use `system` for the retrieval or RAG pipeline being built or evaluated.
- Use `user` only when referring to the person giving instructions outside the track specification.
- Use `narrative` for one complete long-form information need supplied for evaluation.
- Use `narrative ID` for the first field of the test-data TSV and `narrative` for its second field.
- Use `query` for text actually issued to a retrieval system. A query may be the original narrative or a rewritten or decomposed form of it.
- Use `prompt` only for model instructions or when preserving terminology from an external dataset such as ResearchRubrics.
- Use `topic_id` only when referring to the literal first field required by the standard TREC Retrieval run-file format. Its value is the narrative ID.

## Core Defaults

- Available 2026 tasks: Retrieval (`R`) and Retrieval-Augmented Generation (`RAG`).
- Removed task: the 2025 Augmented Generation-only task (`AG`) is not a 2026 output.
- The 2026 task guidelines are out in this `trec-rag-2026-track-guidelines` skill for agent/workspace use.
- Official test narratives: 119 narratives in `trec-rag-2026/test-data/trec_rag_2026_queries.tsv`, with IDs `rag2026-0` through `rag2026-118`.
- Submission deadline: August 8th, per the TREC RAG website source checked July 17, 2026.
- Submission upload procedures and portal-specific requirements are still not specified in the public TREC RAG materials; verify them before submission-critical work.
- Primary retrieval corpus/index: ClimbMix.
- Pyserini REST index name: `climbmix-400b`.
- Narrative input filename: `trec_rag_2026_queries.tsv`.
- Retrieval output filename: `r_output_trec_rag_2026.tsv`.
- RAG output filename: `rag_output_trec_rag_2026.jsonl`.
- RAG response length: up to 1,024 words per narrative; in Python parlance, count across `answer[].text` as `sum(len(item["text"].split()) for item in answer)`.
- RAG citation count: zero to three references per answer object; an empty `citations` array is valid.
- RAG citations may use either zero-based positions into `references` or ClimbMix document IDs directly.
- RAG metadata may include participant-defined fields, and `references` may include documents that are not cited in the answer.
- RAG evaluation: organizer-run, anonymized system-by-system battles, individualized nugget rubric scoring in the style of AutoNuggetizer, and weighted citation precision and recall.
- Retrieval depth: choose `k` independently for each narrative and submit all and only the documents predicted to be relevant and useful for answer generation. Do not pad outputs to a fixed cutoff; `k` may vary across narratives and has no fixed maximum.

## Track Overview And Participation

Use [references/trec-rag-overview.md](references/trec-rag-overview.md) for conversational overview questions, current public status, track goals, organizers, participation guidance, source links, and timeline.

- Answer only with 2026 information from the current TREC RAG public materials unless the user explicitly provides newer source material.
- Treat the August 8th submission deadline as public but still verify upload procedures and portal-specific requirements before submission-critical work.
- If the user needs operationally current participation instructions, browse `https://trec-rag.github.io/` before answering because registration, timelines, and guidelines can change.
- If the user asks about TREC RAG 2025 or TREC RAG 2024, do not summarize those years from this skill. Refer them to:
  - 2025: https://trec-rag.github.io/trec25/
  - 2024: https://trec-rag.github.io/trec24/
- If the user asks about task-level differences between 2025 and 2026, use this skill for the 2026 side and refer to the 2025 page for prior-year details.

## What to Read

- For track overview, public status, organizers, participation guidance, source links, and timeline, read [references/trec-rag-overview.md](references/trec-rag-overview.md).
- For official 2026 test-narrative release details, file location, schema, narrative count, handling rules, and the distinction between test and development data, read [references/test-data.md](references/test-data.md).
- For Retrieval (`R`) task requirements, output format, and validation rules, read [references/retrieval-task.md](references/retrieval-task.md).
- For Retrieval-Augmented Generation (`RAG`) task requirements, output format, citation rules, and validation rules, read [references/rag-task.md](references/rag-task.md).
- For released development narratives and prompts, nuggets, rubrics, projected qrels, smoke tests, retrieval tuning, prompt iteration, or practice evaluation, read [references/development-data.md](references/development-data.md).
- For Pyserini REST API access, authentication, endpoint docs, command examples, response parsing, health checks, query behavior, or error handling, use the `pyserini-rest-api` skill.

Read only the reference files needed for the requested task. For API mechanics, route to `pyserini-rest-api` and load only the API references needed for the implementation detail.

## Validation Checklist

Before considering a run complete, verify:

- The run targets only the requested 2026 task: `R`, `RAG`, or both.
- No `AG`-only output is produced.
- Every input narrative has output unless a subset was explicitly requested.
- Official full runs cover all 119 released test narratives and preserve every `rag2026-*` identifier exactly.
- Retrieval output follows [references/retrieval-task.md](references/retrieval-task.md).
- RAG output follows [references/rag-task.md](references/rag-task.md).
- Apply only the explicit structural rules in `rag-task.md`; do not introduce additional stylistic validation requirements.
- No secrets, API tokens, `.env.local` contents, or authorization headers appear in outputs.

## When Requirements Are Unclear

Treat this skill and its referenced files as the authoritative task instructions for agent-created TREC RAG 2026 runs. If a newer official TREC RAG skill release supersedes this one, follow the newer skill and state which instruction changed. If submission logistics such as deadlines, upload procedures, or portal-specific requirements are not yet specified, state the assumption and proceed with the applicable defaults in this skill.
