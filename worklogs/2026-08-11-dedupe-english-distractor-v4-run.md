# Deduplicate English distractor PromptArmor v4 run

Date: 2026-08-11

## Scope

Clean the most recent 2021 English related-topic distractor evaluation under:

`evaluation-results/llm-judge-robustness/distractors/promptarmor-v4/gpt-oss-20b/related-topic/english/2021/`

## Audit before cleanup

- `judgments.jsonl`: 2,381 rows, 2,381 unique task IDs, no internal duplicates.
- `failed.jsonl`: 736 rows, 731 unique task IDs, five excess duplicate rows.
- 717 failed task IDs also appeared in the successful ledger after a later retry.
- Only 14 task IDs remained failure-only.
- The union of successful and failed task IDs contained all 2,395 expected candidates.

## Cleanup rule

The successful ledger was left unchanged. For the failure ledger:

1. Remove every failure row whose task ID has a successful judgment.
2. For any remaining repeated task ID, retain its latest physical row.
3. Write UTF-8 JSONL without a byte-order mark.

The original failure ledger was preserved as:

`evaluation-results/llm-judge-robustness/distractors/promptarmor-v4/gpt-oss-20b/related-topic/english/2021/failed.before-dedupe-20260811-160404.jsonl`

## Verified result

- Successful judgments: 2,381
- Cleaned failure rows: 14
- Unique cleaned failures: 14
- Successful plus failure-only tasks: 2,395

No successful judgment rows were modified.
