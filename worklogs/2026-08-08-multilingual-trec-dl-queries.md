# Multilingual TREC-DL query pipeline

Created a resumable Amazon Translate pipeline in
`tasks/llm_judge_robustness/scripts/translate_queries.py`. It extracts unique
`qid`/`query` pairs from the cleaned TREC-DL 2021–2023 gold CSVs and writes
language/year JSONL checkpoints under
`data/ragdoll-robustness/derived/query-translations/`.

Requested languages: English, Arabic, Chinese, Russian, Hebrew, Hindi,
Vietnamese, Thai, Tagalog, Swahili, Gaeilge (the request's “gailge”), and
Amharic (replacing the initially requested, unsupported Aramaic). All targets
are supported by Amazon Translate; the pipeline uses Simplified Chinese (`zh`)
and Amharic (`am`).

The pipeline copies English locally and calls Amazon Translate's synchronous
`TranslateText` API once per non-English query with explicit `en` source and
target codes. It validates the returned text and language codes, checkpoints
atomically after every successful request, records service provenance, and
resumes completed translation IDs. `--max-requests` supports a bounded pilot.

The extraction preflight found one source inconsistency: 2021 qid `1107704`
occurs with both “what was the main-all benefit of a single european currency?”
(24 passage rows) and “what was the main benefit of a single european
currency?” (17 rows). Neither input was discarded or silently selected. Both
retain qid `1107704` and receive a deterministic hash-suffixed
`translation_id`; all other qids use their qid directly.

An earlier bounded Bedrock pilot wrote the 54-row 2021 English checkpoint, then
failed before a successful paid translation with `UnrecognizedClientException`.
The transport was subsequently replaced at user request by Amazon Translate;
the final script makes no Bedrock or generative-model call.

Added per-run cost accounting using AWS's published Standard Text Translation
rate of USD 15 per million input characters, including whitespace. Each run is
appended to `_runs.jsonl`; `_cost-total.json` is atomically recomputed from the
ledger. Counts include successful paid `TranslateText` requests only. The total
is explicitly an estimate before free tier, credits, taxes, or negotiated
pricing; AWS CloudWatch `CharacterCount` is the billing-authoritative metric.

## Distractor generator

Adapted the four newly supplied Appendix C reconstruction prompts (related
topic, hypothetical, negation, and modal statement) from question/correct-answer
inputs to query/gold-evidence inputs. Relevance-2+ passages are passed only as
answer-bearing facts the generator must avoid. The generator writes resumable
category/language/year JSONL under `data/ragdoll-robustness/derived/distractors/`.
At user direction it uses the repository's Azure OpenAI-compatible endpoint and
the `gpt-5.6-terra` deployment, not Bedrock. Prompt, model, qid, translation ID,
source query, and language provenance are retained per row.

Token usage is persisted on every generated row. At normal completion (and at
a bounded `--max-requests` stop), the script reconstructs a cumulative
`distractors/usage.csv` across all category/language/year checkpoints. Optional
input/output per-million-token CLI rates populate per-row estimated costs;
without deployment-specific rates the token columns remain authoritative and
cost columns are intentionally blank.

The full-run evidence policy was finalized as `relevance >= 2`. Twenty-one
query variants do not meet it and are skipped rather than receiving grade-1,
grade-0, or fabricated evidence. The generator writes them idempotently to
`distractors/skipped-no-grade2-evidence.csv` with their maximum available grade
and removes any ineligible rows left by an earlier checkpoint.

Added `scripts/inject_distractors.py` to produce one injected judged-CSV set per
distractor category under `data/ragdoll-robustness/injected/distractors/`.
After clarification, injection means suffixing the generated title/text onto
every existing passage for that exact qid/query variant—not adding a synthetic
row. Row count, pid, query, relevance, and column order remain unchanged.
Strict mode requires all grade-2+-eligible query variants, while explicit
`--allow-partial` supports pilot inspection. Outputs are atomic and overwrite
protected.

The real conversion preflight found three exact repeated qid/pid rows in 2021
and one in 2022. The converter collapses exact duplicates so RAGDOLL judges each
candidate once, but still rejects a reused pid carrying conflicting passage
text because that result could not be joined unambiguously.

Added the clearly named `scripts/build_ragdoll_relevance_inputs.py` converter.
It groups each injected CSV by exact qid/query pair into RAGDOLL UMBRELA
`query` plus `candidates[].doc.segment` requests, retains pids as docids, and
hash-disambiguates the reused 2021 qid. The 12 atomic outputs live under
`data/ragdoll-robustness/derived/ragdoll-inputs/distractors/` and are overwrite
protected.
