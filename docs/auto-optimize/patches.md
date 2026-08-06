# Patch ledger

One row per **single-factor** prompt change. A patch is the unit of evidence
here, not a prompt file: prompts are built from patches by
`tasks/task-comparison/scripts/build_prompt_variants.py`, so a patch that banks
a win can be recombined without re-deriving anything.

## Rules

1. **Screen one patch at a time.** Every screening arm is `default.md` + exactly
   ONE patch (`solo-<patch>.md`). A stacked arm cannot tell you which change
   did the work — `evidence-dense` is seven patches, and its published
   uncited-rate result is unattributable to any one of them for exactly this
   reason.
2. **Bank on improvement in ANY aspect**, not just the headline score. The
   rubric gives a per-axis breakdown (explicit, implicit, synthesis,
   communication, instruction, references) plus penalty-avoidance and
   conformance. A patch that lifts Communication Quality while flat overall is
   a real finding and is kept — it may carry its weight in a later combination.
   "Improvement" means the paired per-topic CI excludes zero on that aspect.
3. **Never delete a banked patch.** The prompt file stays in
   `prompts/system/`, the row stays here, and the effect it bought stays
   recorded against the run that measured it.
4. **Combine only banked patches, and re-measure the combination.** Effects do
   not add: two patches can cancel (the `commit_context` de-duplication rule
   silently cancelled `paired-lead` until both were changed together), or
   overlap (`cite-or-cut` and `compression` both shorten). A combination is a
   new hypothesis needing its own arm, never an assumed sum of its parts.
5. **A killed patch stays killed.** Do not re-screen it inside a later
   combination hoping it helps there; that launders noise into a result.

## Status

`banked` — CI excludes zero on at least one aspect, patch retained.
`killed` — CI excludes zero in the WRONG direction on the headline score.
`inconclusive` — no aspect resolved; retained as a file, not eligible to combine.

| patch | status | aspect moved | effect | CI | evidence it targets |
|---|---|---|---|---|---|
| ~~`localization`~~ | **retired** | — | — | — | cause fixed at source: `now_full()` injected `(Australia/Melbourne)` into every request, and prompts were titled `# AUS research agent`. Never screen a rule whose cause you can delete. |
| `stated-form` | inconclusive | 30 topics, sol judge, 3x | mean -0.0134 | [-0.0357, +0.0084] | rag2026-60 asked for a ~10-min-read article, got 38 flat declaratives |
| `decision-item` | inconclusive | 30 topics, sol judge, 3x | mean -0.0067 | [-0.0328, +0.0190] | 3 of 12 hand-read losses: baseline volunteers the decision-relevant fact |
| `reading-a-result` | inconclusive | 30 topics, sol judge, 3x | mean -0.0192 | [-0.0439, +0.0048] | 42-47% of missed figures were in documents we ourselves cited |
| `cite-or-cut` | **killed** | 30 topics, sol judge, 3x | mean -0.0335 | [-0.0555, -0.0099] | 13.5% uncited answer objects vs 0% for both baselines |
| `english-only` | inconclusive | 30 topics, sol judge, 3x | mean +0.0113 | [-0.0102, +0.0338] | non-Latin script mid-sentence in rag2026-10 |
| `no-meta-reference` | inconclusive | 30 topics, sol judge, 3x | mean +0.0043 | [-0.0145, +0.0225] | 3 sentences make the retrieval the subject (rag2026-3/-47/-99) |
| `paired-lead` | inconclusive | 30 topics, sol judge, 3x | mean -0.0073 | [-0.0292, +0.0143] | dense/sparse share 3.6% of retrieved docs; only 4% of rounds paired a lead |
| `decision-lead` | **killed** | 30 topics, sol judge, 3x | mean -0.0232 | [-0.0416, -0.0050] | the answer buries the decisive finding below background |
| `compression` | inconclusive | 30 topics, sol judge, 3x | mean -0.0113 | [-0.0368, +0.0140] | we are 1.16-1.18x baseline length and losing |
| `name-the-source` | inconclusive | 30 topics, sol judge, 3x | mean -0.0016 | [-0.0244, +0.0206] | 24/30 baseline answers named zero sources in prose |

## Screened

| arm | mean | vs control | CI | below 0.65 | severe penalties |
|---|--:|--:|---|--:|--:|
| `default` (control) | 0.5350 | — | — | 24 | 16 |
| `solo-name-the-source` | 0.5523 | +0.0173 | [-0.0082, +0.0415] | 21 | 13 |
| `solo-reading-a-result` | 0.5473 | +0.0123 | [-0.0132, +0.0372] | 22 | 16 |
| `solo-stated-form` | 0.5485 | +0.0135 | [-0.0065, +0.0343] | 22 | 16 |
| `solo-cite-or-cut` | 0.5422 | +0.0072 | [-0.0150, +0.0308] | 22 | 18 |
| `solo-finish-the-claim` | 0.5476 | +0.0126 | [-0.0119, +0.0373] | 21 | **11** |

**Judge noise floor 0.072 per topic.** At n=30 with 3 gradings averaged, the
smallest resolvable mean effect is about 0.03. All three arms land at ~0.015 —
below resolution. That is not evidence they do nothing; it is the instrument
saying it cannot tell. Their consistent sign (3/3 positive on the headline,
3/3 negative on Communication Quality) is the only signal available at this
size, and it is what motivates testing them combined: three independent
~0.015 effects sum to ~0.045, which IS above the floor.

| `facts` (tool) | inconclusive | none resolves | mean -0.0073 | [-0.0367, +0.0226] | 876 facts extracted across 19 topics; answers unchanged in length, figure density, or example rate |
| `source_grade` (tool) | inconclusive | severe penalties 11->9 | mean -0.0017 | [-0.0239, +0.0212] | LLM classifies source kind at commit; premise undercut by corr(source quality, score) = -0.085 / -0.182 |
| `evidence_rank` (tool) | inconclusive | Synthesis +0.075 | mean +0.0025 | [-0.0284, +0.0326] | within-batch ordering after the absolute score proved miscalibrated on chunks |
| `effort=medium/high/xhigh` | inconclusive | none | -0.0115 / -0.0160 / -0.0028 | all straddle 0 | reasoning tokens move only +12% in-loop vs +70% in isolation |
| `known-candidates` | inconclusive | Implicit went DOWN -0.011 | mean +0.0105 | [-0.0160, +0.0370] | 20/20 high-weight Implicit misses name an entity the question never mentions, and default.md forbids searching for them |

| `coverage-audit` (harness) | inconclusive | Implicit +0.011, Communication -0.056 | mean +0.0168 | [-0.0149, +0.0499] | interrupt fires once when the agent stops; mechanism verified (14 searches, 21 refs vs 14) |
| `wordcap-probe` | inconclusive | — | mean -0.0110 | [-0.0374, +0.0145] | 2,000-word allowance produced 898 words vs 894; cap was never binding |
| `sol-tools` (all three) | inconclusive | severe penalties 6->11 | mean -0.0213 | [-0.0467, +0.0041] | orthogonal tool changes do not stack |
| `sol-finish-the-claim` | inconclusive | — | mean -0.0139 | [-0.0334, +0.0041] | top luna arm did not confirm on the shipping generator |

## Combination queue

Filled once ≥2 patches bank. Each combination is one row in `results.tsv` like
any other arm, and must beat **its own best constituent**, not just the control
— a stack that only matches its best part is worse than that part alone,
because it is more prompt for the same score.

Pre-existing stacks (`evidence-dense`, `evidence-paired`, `decision-first`,
`compressed`) are **combination candidates, not screening arms**. They were
built before this rule and none of their components has been screened alone.

| `finish-the-claim` | inconclusive | 30 topics, sol judge, 3x | mean +0.0237 | [-0.0030, +0.0515] | 25.2% of reward criteria score *partial*; converting that pool is worth ~0.08-0.10 and costs no words |
