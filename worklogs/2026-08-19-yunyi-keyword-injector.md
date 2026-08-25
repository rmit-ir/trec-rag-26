# 2026-08-19 - Yun Yi keyword injector

## Change

Added `tasks/llm_judge_robustness/scripts/yunyi_keyword_injector.py` for a
combined robustness condition. It reuses the keyword injector's deterministic
random word-boundary placement, uppercases and disperses every generated key
phrase, and appends the normalized Yun Yi instruction block after the passage.

The default output is
`data/ragdoll-robustness/injected/yunyi_keyword_injector/trec_dl_<year>.csv`.
The CLI accepts the existing input, keyword, year, overwrite, text, and text-file
controls. Rows without keyword data still receive the Yun Yi block and are
reported as missing keyword entries.

## Verification

Focused tests cover ordering, deterministic placement, and rejection of empty
Yun Yi text:

```text
uv run --group dev --group o3-deep-research --group aus-agent pytest tests/llm_judge_robustness/test_yunyi_keyword_injector.py tests/llm_judge_robustness/test_inject_keywords.py
6 passed
```

The new module was also rechecked through the repository's Bash wrapper:

```text
bash scripts/test.sh tests/llm_judge_robustness/test_yunyi_keyword_injector.py
3 passed
```

Static analysis:

```text
uv run --group dev ruff check tasks/llm_judge_robustness/scripts/yunyi_keyword_injector.py tests/llm_judge_robustness/test_yunyi_keyword_injector.py
All checks passed!
```

## 2021 artifact

Generated the combined 2021 condition with:

```text
uv run --project tasks/llm_judge_robustness python tasks/llm_judge_robustness/scripts/yunyi_keyword_injector.py --years 2021
```

The run injected keywords into all 2,398 passages, appended Yun Yi to every
passage, and reported zero missing keyword entries. Validation against the gold
CSV found 2,398 output rows, zero identity-field mismatches, zero unchanged
passages, and zero passages missing the final Yun Yi sentence.

Artifact:
`data/ragdoll-robustness/injected/yunyi_keyword_injector/trec_dl_2021.csv`
(2,707,890 bytes). Run log: `tmp/yunyi-keyword-injector-2021.log`.
