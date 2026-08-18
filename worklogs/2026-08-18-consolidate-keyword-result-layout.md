# 2026-08-18 — consolidate keyword-injection result layout

## Goal

Place all dispersed-uppercase keyword Bing results under `keywords/` and group
both Bing and PromptArmor v4 beneath the actual judge model, `gpt-oss-20b`.

## Canonical layout

```text
evaluation-results/llm-judge-robustness/keywords/gpt-oss-20b/
  bing/
    2021/2021.{judgments,failed}.jsonl, 2021/2021.raw-events/, 2021/2021.log
    2022/2022.{judgments,failed}.jsonl, 2022/2022.raw-events/, 2022/2022.log
    2023/2023.{judgments,failed}.jsonl, 2023/2023.raw-events/, 2023/2023.log
  promptarmor-v4/
    2021/{judgments.jsonl,failed.jsonl,raw-events/,run.log}
  archive/
    bing-pre-uppercase/
      2021.{judgments,failed}.jsonl, 2021.raw-events/, 2021.log
```

The `keywords-uppercase/` tree and the old
`keywords/promptarmor-v4/gpt-oss-20b/` nesting were removed after their contents
were moved. No result artifact was deleted: the conflicting older 2021 Bing run
was moved to the archive.

The Bing artifacts were then grouped into year directories, mirroring the
operator-created `bing/2021/` convention while retaining their year-prefixed
filenames.

## Provenance checks before moving

| Run | Rows | SHA-256 | Legacy `[KEYWORDS:` marker in first row |
|---|---:|---|---|
| canonical pre-move Bing 2021 | 2,385 | `ABB45911C984FEB3100E5CCB506F0719EEDED623B548CB1C546960F481CE63DF` | yes |
| uppercase-tree Bing 2021 | 2,387 | `A7D788DD4F9EE85649966929254C09D5CD44BE91906C3AF51ADEB3E7C5A16B24` | no |
| canonical Bing 2022 | 2,655 | `C641203CDE645C17E814DBB3820718873CF25ED4A8A024BAA579C9A37465F4AE` | no |
| uppercase-tree Bing 2023 | 2,448 | `3563294284770352A73D361E900CCCD406EB70F4A88CAF41E57CBFF2E24E3989` | no |
| PromptArmor v4 2021 | 2,380 | `12929DF0BDCEB86E15A4A15E62631139A728FDB0E11FF40339AE67DE8BFC79AB` | yes |

The PromptArmor v4 2021 run is retained as a pre-uppercase campaign and remains
input-matched to the archived Bing 2021 run in `compare_trec_dl.ipynb`.
