# 2026-08-18 — consolidate Yun Yi result layout

## Goal

Group every Yun Yi result beneath the judge model while preserving the existing
evaluator and year organization.

## Canonical layout

```text
evaluation-results/llm-judge-robustness/yun_yi/gpt-oss-20b/
  bing/
    2021/{judgments.jsonl,failed.jsonl,raw-events/,run.log}
    2022/{judgments.jsonl,failed.jsonl,raw-events/,run.log}
    2023/{judgments.jsonl,failed.jsonl,raw-events/,run.log}
  promptarmor-v4-corrected/
    2021/{judgments.jsonl,failed.jsonl,raw-events/,run.log}
    2022/{judgments.jsonl,failed.jsonl,raw-events/,run.log}
    2023/{judgments.jsonl,failed.jsonl,raw-events/,run.log}
```

The old `yun_yi/<evaluator>/gpt-oss-20b/` nesting was removed after moving its
contents. The six judgment ledgers retained their original SHA-256 hashes.
The UMBRELA evaluator folder was subsequently renamed from `umbrela-bing/` to
the shorter canonical name `bing/`.

## Judgment-ledger integrity

| Evaluator | Year | SHA-256 |
|---|---:|---|
| UMBRELA Bing | 2021 | `C7E70D149DF3CD94A74A697E26C6B8F32D7793042FC75DA08EFCF8211C62BD7A` |
| UMBRELA Bing | 2022 | `0EDCF3ED244B97B8B214F97CB2201DCB17B9F792CBF5A398DDE72C0442C35EFC` |
| UMBRELA Bing | 2023 | `3F9ACEE9D611F674A0BF1FDD974FB913612AE9DA37DC19C9413BC0E500084B50` |
| PromptArmor v4 corrected | 2021 | `BE03762E941775CC77B8FA2F1E5ECF65664C3376552CB2663BC488FFE3ED9159` |
| PromptArmor v4 corrected | 2022 | `7DE16E0CDE3E15D82AC8CD48D08AD0C24AC71BE6EFFE0D2F04C3F936CE4D4F9F` |
| PromptArmor v4 corrected | 2023 | `265AB1C97E8056C124FFFA1848ABD96AB4A4AD8D922FFD47F85052054D1823E5` |

## Dependent artifact

`worklogs/assets/2026-08-18-build-compare-trec-dl.py` was updated to use the
canonical paths. Its generated `tmp/compare_trec_dl.ipynb` notebook was rebuilt
and executed after the move.
