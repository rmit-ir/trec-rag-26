# Why did owa-glm5-t119 beat sol-research-first on B1 human preference? (2026-11-13)

Question: B1 is the holistic human-preference batch (17 narratives). `owa-glm5-t119` has
BT 1212.8 vs 1062.7 for `sol-research-first` (non-overlapping 95% CIs), despite lower
rubric coverage. Is the cause surface structure (headings, capitalisation, signposting)?
Analysis only: no new generations or judgments. **Descriptive, 17 topics, no p-values.**

## Inputs

- GLM-5 submission: `data/outputs/submissions/owa-glm5-t119/rag_output_trec_rag_2026.jsonl`
  (local copy; also in `~/Downloads/trec_rag_26_data/outputs/submissions/`).
- Sol submission: copied read-only over ssh from Sunfyre,
  `/scratch/fast/kun/projects/trec-rag-26/data/outputs/submissions/sol-aus-v2-research-first-test119-20260807/rag_output_trec_rag_2026.jsonl`,
  SHA-256 `744c2d0624a1b834b94ad87fbc50548b1957f22a09beb1903230da72fe4986d8`
  (1,114,270 bytes). Not committed; only derived numbers are.
- Topics: `RMIT-ADM+S scores/batch1-topics.txt` (17 ids).
- Per-topic preference: `RMIT-ADM+S scores/rag-sxs-counts-batch1.tsv`. These are W/T/L
  **against the assessed field, not head-to-head**. "Net" = (wins - losses) / (W+T+L);
  margin = net(GLM-5) - net(Sol).
- Per-topic readability: `trec-rag-26-report/worklogs/assets/2026-11-08-batch1-readability.json`
  (`per_topic`, batch 1).
- Probe scripts and full raw output: `assets/2026-11-13-b1-structure-probes/`
  (`all-outputs.txt` has every number below; scripts hardcode the session scratchpad path
  for the Sol file, so point `S` in `struct.py` at a local copy to rerun).

## 1. Markdown structure: none in either run

The answer format is a list of text items. Neither run has `#`, bold, bullets or tables.
B1 means per report: GLM-5 words 805.3, items 14.4, citations 21.7, refs 16.6;
Sol words 951.2, items 24.5, citations 41.9, refs 28.9.

## 2. Heading-like markers

Detectors (in `struct.py`, `cap.py`, `caps2.py`):

| Marker (B1 mean per report) | GLM-5 | Sol |
|---|---|---|
| Short uncited, no-final-period items (title-like) | 2.1 (4/17 topics) | 0 |
| Title Case heading items (<=12 words) | 2.1 | 0 |
| Inline Title Case labels ("Control Protection Mechanisms: ...") | 1.1 (5 topics) | 0 |
| Topics with any Title Case marker | 5/17 | 0/17 |
| ALL CAPS tokens (acronyms, not headings) | 3.1 | 3.4 |
| ALL CAPS headings | 0 | 0 |

GLM-5 title-case topics: rag2026-13 (7 headings + 4 labels), 30, 45, 68, 95. Per-topic
heading counts in B1 order: `[0, 8, 0, 0, 0, 15, 0, 6, 0, 0, 0, 0, 7, 0, 0, 0, 0]`.
ALL CAPS headings exist only outside B1 (GLM-5 rag2026-2, B2: 9 headings; 4/119 topics overall,
Sol 0/119).

## 3. Signposting markers (B1 mean per report)

| Marker | GLM-5 | Sol |
|---|---|---|
| Enumerators (First,/Second,/(a)/1)) | 1.0 (5 topics) | 0.0 (0) |
| Any-case colon lead-in | 2.4 (8 topics) | 1.9 (15) |
| Semicolons | 2.3 | 5.2 |
| Digit phase markers (Month 4, Step 2) | 0.2 | 0.0 (**regex miss**: Sol writes "months one and two") |
| Imperative/rule openers | 0.4 | 0.4 |

Correlation of (GLM-5 - Sol signposting gap) with preference margin: r = -0.44
(wrong sign for "structure wins"; driven by rag2026-13; n = 17).

## 4. Does structure predict where GLM-5 wins? No.

Mean net preference, structured (5 topics: 13, 30, 45, 68, 95) vs plain (12):

| Topics | n | GLM-5 net | Sol net |
|---|---|---|---|
| structured | 5 | 0.415 | 0.112 |
| plain | 12 | 0.487 | 0.165 |
| all | 17 | 0.466 | 0.149 |

GLM-5 leads by ~0.30 on structured and ~0.32 on plain. Full per-topic matrix (GLM-5 W/T/L net |
Sol W/T/L net, `S` = structured):

| Topic | GLM-5 | Sol | |
|---|---|---|---|
| 11 | 3/5/1 0.22 | 0/8/3 -0.27 | |
| 13 | 2/0/8 -0.60 | 3/0/9 -0.50 | S |
| 16 | 10/2/1 0.69 | 2/1/7 -0.50 | |
| 17 | 7/3/0 0.70 | 3/1/3 0.00 | |
| 29 | 8/3/2 0.46 | 7/0/5 0.17 | |
| 30 | 7/0/2 0.56 | 6/0/7 -0.08 | S |
| 41 | 15/5/0 0.75 | 8/0/2 0.60 | |
| 45 | 11/0/2 0.69 | 9/0/2 0.64 | S |
| 50 | 7/0/5 0.17 | 5/0/3 0.25 | |
| 57 | 5/0/2 0.43 | 5/1/2 0.38 | |
| 59 | 6/0/2 0.50 | 3/0/8 -0.45 | |
| 61 | 7/1/1 0.67 | 3/5/0 0.38 | |
| 68 | 13/0/1 0.86 | 6/2/6 0.00 | S |
| 71 | 5/0/2 0.43 | 10/4/0 0.71 | |
| 79 | 8/0/2 0.60 | 8/0/3 0.45 | |
| 95 | 5/1/1 0.57 | 11/2/3 0.50 | S |
| 97 | 4/3/2 0.22 | 4/6/1 0.27 | |

GLM-5 has the higher net on 13/17 topics. Sol has the higher net on 13 (-0.50 vs -0.60), 50, 71
and 97. (An earlier in-session list said 95; its net is GLM-5 0.57 vs Sol 0.50, so GLM-5 is
ahead there.) rag2026-13 is GLM-5's worst topic (net -0.60) and has the most
headings, so headings did not rescue it. (rag2026-13: GLM-5 23 items/769 words/18 refs, Sol
28/966/20; GLM-5 commits to "stay CEO, hire a COO now"; Sol covers stay/hire/succession
paths, decision rights, CEO charter, scorecards, metrics and failure modes.)

## 5. Does readability or length predict the margin? No.

Per-topic (GLM-5 - Sol) gap vs margin, n = 17 (Pearson / Spearman):
words -0.26/-0.20; references -0.22/-0.04; words per sentence 0.04/0.12; Flesch reading
ease -0.13/-0.26; FK grade 0.11/0.26; ARI 0.08/0.22; Coleman-Liau 0.12/0.19; Gunning fog
0.25/0.39; difficult words -0.32/-0.26; sentences -0.08/-0.08. GLM-5 is easier on 16/17
(Flesch), shorter-sentenced on 17/17, shorter on 15/17, so there is almost no variation to
explain within the batch. Overall-batch readability remains a plausible background factor
(see 2026-11-08-batch1-readability.md) but cannot be shown from per-topic data.

## 6. Read-through of 7 divergent topics (one reader, one pass)

Biggest GLM-5 margins:

- **16 (NLP for ADE surveillance), +1.19.** GLM-5: 7 long items, answers expectations,
  source comparison and workflow, ends on precision/recall and queue capacity. Sol: 20 items,
  opens with ADE/ADR/medication-error definitions, then n2c2/MADE/CADEC/ADE-SCAI figures, pilot
  protocol.
- **59 (city fleet supply risk), +0.95.** GLM-5: 6 items, names semiconductors, ICE vs EV,
  validates the mechanics' warning, gives a phased strategy. Sol: 26 items, opens with a scope
  and date caveat and six glossary items (ICEV, BEV, duty cycle, lead time, allocation, SLA).
- **68 (school safety), +0.86.** GLM-5: 18 items with "Priority 1/2/3 / Lower Priority"
  headings and a firm ranking. Sol: 29 items, full layered framework and a hypothetical
  $150,000 split, but no single ranked list up front.

Topics where Sol is ahead or tied (95 is included because Sol reads stronger despite GLM-5's
small net lead, +0.07):

- **71 (plea bargaining).** GLM-5 gives 8 items, one per concern; the ask also needs safeguards
  and data reporting. Sol covers detention/conviction studies, voluntariness law, trial-penalty
  selection bias, two hypothetical pathways and a dashboard design.
- **95 (youth safety budget).** GLM-5 compares six interventions but ends "I could not find
  detailed experimental outcome data..." Sol gives a percentage budget split, launch timeline
  and a 6/12-month reallocation rule.
- **50 (Malayan Emergency panel).** GLM-5 5 items vs Sol 17 with specific figures (572,917
  people moved) and the 1968-89 insurgency.
- **97 (Boric).** Near tie; Sol adds macro, fiscal and water-code detail.

## Interpretation (hypothesis, not a finding)

1. GLM-5 tends to win when it gives a short, committed, ranked answer in its first items
   while Sol front-loads definitions and caveats.
2. GLM-5 tends to lose when the prompt asks for concrete deliverables (budget split, data
   reporting, specific museum content) and GLM-5's 5-9 items are too thin.
3. Sol looks more thorough on every divergent topic, so the preference result may reflect
   assessors favouring directness over thoroughness where the runs diverge. Assessor reasons
   are not in the data.

Untested follow-up: classify whether Sol's first three items are definitions/scope/caveats
for all 17 topics and correlate with the margin.

## Caveats

- n = 17; one reader; preference counts are against the field, not head-to-head.
- Detectors are regex heuristics (e.g. Sol's spelled-out months missed).
- The assessor interface (whether items render as paragraphs) is unknown.
- B2 is out of scope here; rag2026-2 (B2) was inspected only to see ALL CAPS headings.
