# Yun Yi custom-text passage injector

Created:

`tasks/llm_judge_robustness/scripts/inject_yun_yi_text.py`

The script reads the gold TREC-DL 2021, 2022, and 2023 CSVs and appends one
normalized text block to every passage. Text can be supplied by editing the
top-level `INJECTION_TEXT` variable, with `--text`, or from a UTF-8
`--text-file`. The latter two override the constant. Embedded newlines and
repeated whitespace are collapsed so each CSV passage remains clean.

Default outputs:

- `data/ragdoll-robustness/injected/yun_yi/trec_dl_2021.csv`
- `data/ragdoll-robustness/injected/yun_yi/trec_dl_2022.csv`
- `data/ragdoll-robustness/injected/yun_yi/trec_dl_2023.csv`

The implementation preserves the exact five-column source schema and writes
each CSV atomically. Existing outputs require explicit `--overwrite`.

Validation used the exact temporary injection text `YUN YI SMOKE TEST`. The
script passed `py_compile` and produced 2,398 rows for 2021, 2,656 for 2022, and
2,460 for 2023. Every passage in all three files ended with the test text (zero
incorrect endings). Temporary smoke-test outputs were removed afterward.

Follow-up: added `--yun-yi` to `build_ragdoll_relevance_inputs.py`. It converts
the flat injected CSV layout into
`data/ragdoll-robustness/derived/ragdoll-inputs/yun_yi/<year>.requests.jsonl`
for subsequent regular UMBRELA and modified armor-prompt evaluation. The mode
is mutually exclusive with `--original` and passed `py_compile`/CLI exposure
checks. No real conversion was run because the user has not yet supplied the
custom injection text, so the three default `yun_yi` CSVs do not yet exist.
