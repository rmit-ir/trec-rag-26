# Batch-1 readability and human preference (2026-11-08)

The user requested deterministic readability scores using an established Python library,
a report table retaining the matched-topic length/reference comparison, and a Discussion.
No new generations or judgments were made.

## Inputs and verification

- NIST Batch-1 topics: 17 IDs from `rag-sxs-counts-batch1.tsv`; Batch 2: 25 IDs from its matching file.
- GLM-5 submission: `data/outputs/submissions/owa-glm5-t119/rag_output_trec_rag_2026.jsonl` on Sunfyre.
- Sol submission: `/scratch/fast/kun/projects/trec-rag-26/data/outputs/submissions/sol-aus-v2-research-first-test119-20260807/rag_output_trec_rag_2026.jsonl` on Sunfyre.
- Exact source SHA-256 digests, topic IDs, normalized-text hashes and all 84 per-report
  length/reference rows (including 34 Batch-1 readability rows) are preserved in
  [the full audit](assets/2026-11-08-batch1-readability.json).
- The GLM-5 source digest matches the local submitted JSONL. The Sol digest matches the
  separately preserved `../trec-rag-26/worklogs/assets/2026-11-04-sol-cost-recovery.json`.
  Topic TSV hashes also match the local official-score copies.
- Source submissions each contain exactly 119 unique topics. Matched-topic sets and
  pair alignment are asserted. Batch-1 readability is computed for both runs on all 17 topics.
- No raw submission assets were copied from Sunfyre; only computed results and source hashes were returned.

## Method and reproducibility

[Analysis script](../scripts/analyze_batch1_readability.py) was executed through DevSpace
Sunfyre as an inline copy, read-only against the original submissions.
Equivalent command from this report checkout on a machine with the source data available:

```bash
uv run --no-project --with textstat==0.7.12 --with nltk==3.10.4 --with pyphen==0.18.1 \
  python scripts/analyze_batch1_readability.py \
  --glm-submission /home/el7/E103037/repos/trec-rag-26/data/outputs/submissions/owa-glm5-t119/rag_output_trec_rag_2026.jsonl \
  --sol-submission /scratch/fast/kun/projects/trec-rag-26/data/outputs/submissions/sol-aus-v2-research-first-test119-20260807/rag_output_trec_rag_2026.jsonl \
  --output-dir /tmp/batch1-readability
```

Versions: Python 3.13.14, textstat 0.7.12, nltk 3.10.4, pyphen 0.18.1.
CMU pronunciation dictionary SHA-256: `cad209c39eb87677d64e93d97f8eed10b7e6f9bdd42de8e7ca8efc8e17d62e8a`.
English (en_US); textstat uses CMU pronunciations with Pyphen fallback for syllable estimates.

Inputs to readability are the submitted `answer[].text` fields, joined with spaces,
with Markdown emphasis/code markers removed and whitespace collapsed. Citation indices,
document IDs and the bibliography/reference list are excluded. Library sentence detection
is used consistently for both systems. Length counts retain the original report convention:
whitespace-separated words in the answer fields. Reference counts are unique reference-list entries.
Reported scores are arithmetic means across individual reports, not scores on concatenated corpora.

Flesch Reading Ease is higher for easier surface text; Flesch-Kincaid, ARI and
Coleman-Liau are lower for easier surface text. Negative reading-ease values are valid.
SMOG was initially omitted because its usual 30-sentence requirement is not met by every
report. At the user's request it is now computed for completeness, with a per-report
eligibility flag (14/17 GLM-5 and 5/17 Sol reports meet 30 sentences). Spache targets
children's text and McAlpine EFLAW targets foreign-language learners; both are retained
only as supplementary audit results. Non-English-specific formulas are not applied
to these English reports. Library API defaults are used; consensus is requested numerically.
The formulas are correlated and are not independent tests of comprehension, naturalness,
factuality or causal influence on human preference. No readability p-values are claimed.

## Initial four-metric aggregate results (unchanged)

| Measure | GLM-5 Batch 1 | Sol Batch 1 |
| --- | ---: | ---: |
| Words | 805.2941 | 951.1765 |
| Unique references | 16.5882 | 28.9412 |
| Library words/sentence | 21.8401 | 34.8706 |
| Flesch reading ease | 21.0445 | -1.9413 |
| Flesch-Kincaid grade | 15.7497 | 22.1929 |
| Automated Readability Index | 18.3443 | 26.7549 |
| Coleman-Liau index | 17.2815 | 19.8890 |

GLM-5 is shorter on 15/17 Batch-1 topics. Reading ease and Coleman-Liau favour it on
16/17; Flesch-Kincaid and ARI favour it on 17/17.
Batch-2 context only: mean words 754.48 vs. 945.32; mean references 16.12 vs. 28.92;
GLM-5 shorter on 23/25 topics.

## Interpretation and report changes

Added Section Discussion and the generated comparison table. The Batch-1 published
BT ratings (1212.8 vs. 1062.7) have non-overlapping organizer 95% intervals, supporting
a significantly higher rating under the published judgment-level uncertainty model;
no exact pairwise p-value is invented. These are fitted ratings against the assessed
field, not a direct head-to-head win count.

The discussion distinguishes demonstrated surface differences from the hypothesis that
lower reading burden contributed to holistic preference. Batch-2 length and preference
reversal, different topics/protocols, possible judge sensitivity, pipeline differences
and the documented review failure limit causal claims. Updated earlier prose that
implicitly attributed the reversal to concision without evidence; the abstract and RQ1
answer now reference the descriptive readability evidence.

## Expanded audit and reporting choice

The user subsequently requested all common measures but one score in the paper.
The audit now contains Flesch Reading Ease, Flesch-Kincaid Grade Level, ARI,
Coleman-Liau, Gunning Fog, SMOG, Dale-Chall (both library versions), Linsear Write,
Spache, McAlpine EFLAW, LIX, RIX and the numeric textstat consensus: 14 outputs
for each of the 34 Batch-1 reports. Syllable count, difficult-word count and
estimated reading time are also retained per report. Interpretation limits are
recorded in the JSON, including short-text SMOG and population-specific indices.

All original scores reproduce exactly. Every formula's mean points toward lower
estimated difficulty for GLM-5, but these are correlated descriptive measures.
Flesch-Kincaid Grade Level was selected for concise reporting after the initial
analysis, at the user's request; this was not a preregistered metric choice.
Table 5, the discussion, abstract and conclusion now name only that readability
score (15.7 vs. 22.2; GLM-5 lower on all 17 matched topics). Length and reference
counts remain. The full metric results are preserved in the JSON audit.

Final reporting refinement: Table 5 now contains Batch 1 only, and the library's
words-per-sentence statistic is no longer reported. Original submission length
and reference counts remain. To verify the short Batch-2 trend statement, the
same script also computed Flesch-Kincaid for all 25 matched Batch-2 reports:
means 15.6876 vs. 23.4184, GLM-5 lower on 25/25. Together with shorter mean reports
and fewer references, this supports the brief trend note despite the reversed
human preference. Batch-2 numbers stay in the audit rather than the paper.

## Validation

- Two independent executions of the same analysis produced identical aggregate results.
- Script self-checks cover text cleanup, library response, unique topic counts and paired alignment.
- Source digest checks passed against the local GLM submission, preserved Sol recovery record,
  and both official topic TSVs.
- Two-pass pdflatex build passed with resolved references and no overfull boxes; report is eight pages.
- Visually inspected the discussion/table, conclusion and final references on pages 6--8.
