# Multilingual distractor translation and injection

Added `tasks/llm_judge_robustness/scripts/translate_distractors.py` to translate
the generated English distractor title and body fields through Amazon
Translate. The script supports the same 11 non-English targets already declared
for query translation, checkpoints after each completed distractor, resumes
existing outputs, retries transient failures, supports bounded paid pilots, and
records per-run and cumulative estimated character costs.

Updated `inject_distractors.py` to accept `--languages` and write injected CSVs
as `<category>/<language>/trec_dl_<year>.csv`. Only the distractor is translated;
the original query and passage remain unchanged. Updated
`build_ragdoll_relevance_inputs.py` to consume this language-aware layout and
write `<category>/<language>/<year>.requests.jsonl`.

Moved all 12 existing injected CSV artifacts (four categories times 2021–2023)
from `<category>/trec_dl_<year>.csv` into
`<category>/english/trec_dl_<year>.csv`. These are moves, not regenerated data.

No paid API request was made. Validation comprised:

```bash
uv run --project tasks/llm_judge_robustness python tasks/llm_judge_robustness/scripts/translate_distractors.py --years 2021 --categories related-topic --languages arabic --dry-run
```

This reported 51 distractors, 102 planned TranslateText calls, and 19,889
planned input characters. An English injection smoke test reproduced the 2021
related-topic artifact at 1,834,239 bytes, appending 51 distractors to 2,291 of
2,398 passage rows. All three scripts passed `py_compile`.
