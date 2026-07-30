# Evaluation Measures

Reference for every scoring formula implemented in this repo's evaluation stack
(`evaluation/ragdoll/`), with each one traced back to its source definition.

The anchor source for **support evaluation** is:

> Thakur, Pradeep, Upadhyay, Campos, Craswell, Lin.
> *Support Evaluation for the TREC 2024 RAG Track: Comparing Human versus LLM Judges.*
> arXiv:2504.15205v1, 21 Apr 2025 (16 pp).
> Local copy: `tmp/papers/2504.15205.pdf`

**This is the 2026 track's own citation, not our inference.** The v0.6.0 track
guidelines name weighted citation precision and recall as the support measures and
point at this study by name for the methodology
(`skills/trec-rag-2026-track-guidelines/references/rag-task.md:126-133`). The spec
links the SIGIR 2025 published version — *Assessing Support for the TREC 2024 RAG
Track: A Large-Scale Comparative Study of LLM and Human Evaluations*,
[10.1145/3726302.3730165](https://dl.acm.org/doi/pdf/10.1145/3726302.3730165) —
of which the arXiv preprint above is the same study by the same authors; section
numbers here are the preprint's.

So the §3.4 definitions are the spec our implementation must match, and RAGDoll
reproduces the paper's worked example exactly (see
[Verification](#verification)). What the spec does *not* restate is the
first-citation-only annotation protocol (§1.5) — see
[What the 2026 spec does and does not pin down](#what-the-2026-spec-does-and-does-not-pin-down).

---

## 1. Support evaluation (arXiv:2504.15205 §3.2–3.4)

### 1.1 Judgment scale

Three-level grade, one judgment per (answer sentence, cited passage) pair
(paper §3.2):

| Label | Meaning (verbatim from §3.2) | Weight `s(aᵢ,dⱼ)` | RAGDoll int |
|---|---|---|---|
| **FS** — Full Support | All of the information in the answer sentence is factually consistent with and supported by the cited passage. | 1.0 | `2` |
| **PS** — Partial Support | Some of the information in the answer sentence is factually consistent with and supported by the cited passage, but other parts of the sentence are not supported. | 0.5 | `1` |
| **NS** — No Support | The cited passage is completely irrelevant and does not support any part of the answer sentence. | 0.0 | `0` |

Edge case (§3.2): **a sentence with zero citations is automatically "no
support"**, since it does not cite any retrieved passage.

RAGDoll mapping — `evaluation/ragdoll/src/ragdoll/support/assignments.py:12`:

```python
SUPPORT_LABEL_SCORES = {"FS": 2, "PS": 1, "NS": 0}
```

and the weights at `evaluation/ragdoll/src/ragdoll/support/metrics.py:12-13`:

```python
WEIGHTED_SCORES = {-1: 0.0, 0: 0.0, 1: 0.5, 2: 1.0}   # NS=0, PS=0.5, FS=1.0
HARD_SCORES     = {-1: 0.0, 0: 0.0, 1: 0.0, 2: 1.0}   # FS only
```

`-1` is a RAGDoll extension, not a paper label: it marks a citation the judge
failed to score (`status != "completed"`). Such sentences are **excluded from
both numerator and denominator** rather than counted as NS — see §1.5.

### 1.2 Notation

An answer `r` is segmented into `n` sentences, `r = {a₁, …, aₙ}`. Each sentence
`aᵢ` carries up to `m` document citations, `aᵢ = {d_i1, …, d_im}` (paper §2;
the TREC 2024 track allowed up to `m = 20`). Support is the judge function

```
f(aᵢ, dⱼ) = s(aᵢ, dⱼ) ∈ {0, 0.5, 1}
```

where `f` may be a human or an LLM judge.

### 1.3 Weighted precision

> "the weighted proportion of citations that support each answer sentence"
> — §3.4. Penalizes **overcitation**.

Let `C = {aᵢ : aᵢ has ≥ 1 citation}` be the cited sentences. Under the
first-citation protocol (§1.5):

```
                    Σ_{aᵢ ∈ C}  s(aᵢ, d_i1)
Weighted Precision = ─────────────────────────
                             |C|
```

Paper's worked example (§3.4) — 3 sentences `{a₁,a₂,a₃}`, corpus `{p₁,p₂}`,
where `p₁` partially supports `a₁`, `p₂` fully supports `a₂`, and `a₃` has zero
citations:

```
Weighted Precision = (s(a₁,p₁) + s(a₂,p₂)) / count({a₁,p₁},{a₂,p₂})
                   = (0.5 + 1) / 2
                   = 0.75
```

Note the denominator counts **citation pairs**, so the uncited `a₃` does not
appear — precision is unchanged by undercitation.

### 1.4 Weighted recall

> "the weighted proportion of answer sentences that are supported by their cited
> passages" — §3.4. Penalizes **undercitation**.

Same weights, but the denominator is **all** sentences in the answer:

```
                 Σ_{aᵢ ∈ C}  s(aᵢ, d_i1)
Weighted Recall = ────────────────────────
                            n
```

Same example:

```
Weighted Recall = (s(a₁,p₁) + s(a₂,p₂)) / count({a₁,a₂,a₃})
                = (0.5 + 1) / 3
                = 0.5
```

**Consequence stated in §3.4:** a sentence with zero citations lowers recall and
leaves precision unchanged. And because only the first citation is judged,
**weighted precision and recall are identical whenever every answer sentence has
at least one citation.** Treat a P/R gap in a score table as a direct readout of
how many sentences went uncited.

### 1.5 Annotation protocol — first citation only

§3.3 documents the budget tradeoff: judging all `k ≤ 20` cited passages per
sentence across 45 runs was infeasible, so the organizers chose **sparse
annotation for topic diversity** — both the human and GPT-4o judges scored
**only the first cited passage of every answer sentence**. Evaluating multiple
citations per sentence is left as future work.

RAGDoll implements the paper's protocol *and* an all-citations variant, so it
emits six columns (`support/metrics.py:14-21`):

| Column | Formula | Paper status |
|---|---|---|
| `weighted_precision_first_citation` | §1.3 above | **the paper's metric** |
| `weighted_recall_first_citation` | §1.4 above | **the paper's metric** |
| `weighted_precision_all_judged_citations` | per-sentence mean over all judged citations, then averaged over cited sentences | RAGDoll extension (paper's "future work") |
| `weighted_recall_all_judged_citations` | same numerator, denominator = all sentences | RAGDoll extension |
| `hard_precision` | first-citation precision with `HARD_SCORES` (FS=1, PS=0) | RAGDoll extension |
| `hard_recall` | first-citation recall with `HARD_SCORES` | RAGDoll extension |

The all-citations numerator per sentence is the **mean** of its judged citation
weights, so a sentence never contributes more than 1.0 regardless of citation
count:

```
                                  Σ_{aᵢ ∈ C}  ( (1/|Jᵢ|) Σ_{dⱼ ∈ Jᵢ} s(aᵢ,dⱼ) )
Weighted Precision (all judged) = ───────────────────────────────────────────────
                                                     |C|
```

where `Jᵢ` is the set of *judged* (score ≠ −1) citations of `aᵢ`. Sentences with
no judged citation are dropped from the denominator entirely.

Run-level and topic-level aggregation is a plain unweighted mean over cells
(a *cell* = one `(topic_id, run_id)` pair); the paper sorts its Tables 5–8 by
mean weighted precision descending.

### 1.6 Judge prompt

The GPT-4o judge prompt (paper Figure 1, §3.2) is reproduced **byte-identically**
in `evaluation/ragdoll/src/ragdoll/support/prompts.py:3-19`, pinned by
`tests/test_prompt_provenance.py::test_support_prompt_template_byte_identical`
against `trec2024-rag/support_evaluation_original_prompt.txt`.

Protocol details that matter for reproducing scores:

- **One passage per prompt.** §3.2 footnote 2: providing multiple cited passages
  at once performed worse with the GPT-4o judge.
- **No explanation.** The judge answers with the bare label; `parse_support_label`
  (`support/prompts.py:30-38`) does a case-insensitive substring match for
  "full support" / "partial support" / "no support", returning `None` (→ `-1`) on
  anything else.

### 1.7 Judge-agreement measures (paper §4.2, §5)

Used to validate an automatic judge against humans, not to score runs:

- **Kendall's τ** on run-level scores. RAGDoll uses **τ-b** (ties-aware, SciPy)
  at `evaluation/ragdoll/src/ragdoll/stats.py:10`. Paper reference values
  (GPT-4o vs human): weighted precision τ = 0.884 run-level / 0.596 per-topic /
  0.470 individual; weighted recall τ = 0.892 / 0.644 / 0.539 (manual from
  scratch); weighted precision τ = 0.792 run-level (with post-editing).
  All run-level τ > 0.79.
- **Perfect-agreement rate** from the 3×3 confusion matrix (Figure 3): 56%
  from-scratch (13.7 + 11.9 + 30.4), rising to 72.1% with post-editing
  (15.9 + 18.7 + 37.5).
- **Cohen's κ** on the 537-pair disagreement study (Figure 4) — *not implemented
  in RAGDoll*. Paper values: independent human vs GPT-4o κ = 0.29 / 0.27 vs
  independent human vs NIST human κ = −0.03 / 0.07; LLAMA-3.1 405B vs GPT-4o
  κ = 0.60 / 0.46.

Directional bias to expect when comparing an LLM judge to humans (§4.1): **GPT-4o
skews toward "partial support", humans toward "no support"**, so LLM-judged
weighted P/R runs higher. The largest single off-diagonal cell from-scratch is
GPT-4o=PS / human=NS at 15.1%.

### 1.8 What the 2026 spec does and does not pin down

The v0.6.0 guidelines (`references/rag-task.md`, "Evaluation") name the measures
and the methodology paper, but restate less than the paper defines. What is
stated, and what we are still inferring from 2024:

| Fact | Stated in the 2026 spec? |
|---|---|
| Support scored as weighted citation precision + recall | **Yes** — named, with the same prose definitions as §3.4 |
| Uncited answer objects omitted from precision, scored 0 for recall | **Yes** — stated twice, and made a validation rule |
| The methodology paper | **Yes** — cited by name (SIGIR '25 version) |
| Nugget scoring "in the style of AutoNuggetizer" | **Yes** — named, formulas not given |
| Pairwise system-vs-system battles with hidden identities and randomized order | **Yes** — named, aggregation method not given |
| FS/PS/NS weights = 1.0 / 0.5 / 0.0 | **No** — "weighted" is never expanded; taken from §3.2 |
| Only the *first* cited passage of each answer object is judged | **No** — inherited from §3.3 |
| Rubric scoring, UMBRELA relevance judging | **Not for the RAG task** — ResearchRubrics rubrics and UMBRELA qrels ship as *development-data diagnostics* (`references/development-data.md`), not as announced test-set measures |

Two consequences worth acting on:

- **The first-citation-only protocol is the load-bearing unstated assumption.**
  If 2026 judges *all* citations of a sentence, then citing three passages when
  one supports the claim starts costing precision — under first-citation-only it
  costs nothing, and the spec's "order the citations from strongest to weakest
  support" rule (`rag-task.md:146`) is exactly what makes a first-citation
  reading safe. That rule existing is weak evidence the protocol carries over,
  but it is not a statement of it. Prefer citing the single strongest passage,
  which is optimal under either protocol.
- **The zero-citation asymmetry is now a *rule*, not just an artifact.** The spec
  states it in the Evaluation section and again as a validation rule, so "an
  empty citations array costs recall only" is guaranteed 2026 behaviour, not an
  inference from the 2024 implementation.

Note the aggregation the paper uses (unweighted mean over `(topic, run)` cells,
§1.5) is also unstated for 2026 — a macro-average over narratives is the safe
assumption, but a leaderboard rank computed locally will not necessarily match
the organizers' to the digit.

---

## 2. Nugget coverage (`nuggetizer`)

`evaluation/ragdoll/src/ragdoll/nuggetizer/metrics.py` — a port of the AutoPi
reproduction harness (`trec2024_compare.py`), the AutoNuggetizer lineage the
paper defers to for nugget evaluation (§2, citing Pradeep et al.).

Per cell, over a nugget list where each nugget has an `importance`
(`vital` | `okay`) and an `assignment` (`support` | `partial_support` |
`not_support` | `failed`):

```
                Σ_{nugget ∈ S}  v(assignment)
coverage(S) = ───────────────────────────────      ∈ [0, 1]
                          |S|
```

with

```
v(support) = 1.0
v(partial_support) = 0.5   in non-strict variants, 0.0 in strict variants
v(anything else) = 0.0
```

Four metrics from the two axes — nugget set × strictness:

| Metric | Nugget set `S` | `partial_support` counts |
|---|---|---|
| `V_strict` / `strict_vital_score` | vital only | no (0.0) |
| `A_strict` / `strict_all_score` | all nuggets | no (0.0) |
| `V` / `vital_score` | vital only | yes (0.5) |
| `A` / `all_score` | all nuggets | yes (0.5) |

Empty set → `0.0`. Run-level score = mean over the run's topics, NaNs skipped.
Kendall τ-b against a reference assignment is reported both run-level and
per-cell (`correlations.csv`).

---

## 3. Rubric scoring (`rubric`)

`evaluation/ragdoll/src/ragdoll/rubric/metrics.py` — ResearchRubrics-style
weighted criteria. Each criterion has a `weight`, a `tier`
(`mandatory` | …), a `type`, and a ternary `verdict`.

```
v(satisfied) = 1.0,  v(partially_satisfied) = 0.5,  v(not_satisfied) = 0.0
binary mode: v ≥ 1.0 → 1.0, else 0.0
```

```
            Σ_c  wᵢ · v(verdictᵢ)
score = ───────────────────────────      normalized to [0, 1]
          Σ_{c : wᵢ > 0}  wᵢ
```

`nan` when no criterion carries positive weight. Both a `ternary_score` and a
`binary_score` (partial collapsed to 0) are emitted per cell, plus
`n_mandatory_fail` — mandatory criteria scoring below 1.0.

Per criterion **type**, a failure rate (paper Eq. 2, simplified):

```
failure_rate(type) = |{c of that type : v(c) < 1.0}| / |{c of that type}|
```

Correlations reported: `ternary_vs_binary` τ-b, plus each score column against a
reference run when one is supplied.

---

## 4. Pairwise comparison (`arena`)

`evaluation/ragdoll/src/ragdoll/arena/metrics.py` — head-to-head judging.

**Preference rate** (ties split evenly):

```
                    wins_A + 0.5 · ties
pref_rate(A vs B) = ─────────────────────
                    wins_A + wins_B + ties
```

`nan` when no valid judgments exist for the pair.

**Leaderboard rating:** Bradley–Terry via the `lmarena/arena-rank` backend
(`scale = 400.0`, `init_rating = 1000.0`, sandwich CIs). Degenerate cases — a
single run, or no usable judgments — return `init_rating` for everyone. Ranking
sorts by descending rating, then `run_id` for determinism.

Only `status == "completed"` judgments with a well-formed 2-element `pair` count
toward any of these.

---

## 5. Relevance judging (`umbrela`)

`evaluation/ragdoll/src/ragdoll/umbrela/prompts.py` — UMBRELA emits a
**0–3 integer relevance grade** per (query, passage), parsed from
`##final score: N` (with fallbacks for `final score: N` and
`relevance category: N`). This is a *qrels generator*, not a run metric: the
graded pool it produces is consumed by `trec_eval`-style measures (nDCG@k etc.)
outside RAGDoll. The paper points to Upadhyay et al. for the relevance-assessment
analysis (§2).

---

## Verification

The paper's §3.4 worked example reproduces exactly against RAGDoll's
implementation:

```bash
cd evaluation/ragdoll && uv run python - <<'EOF'
from ragdoll.support.metrics import support_metric
row = {"topic_id": "t1", "run_id": "r1", "sentences": [
    {"text": "a1", "citations": [{"support": 1}]},   # PS -> 0.5
    {"text": "a2", "citations": [{"support": 2}]},   # FS -> 1.0
    {"text": "a3", "citations": []},                 # zero citations
]}
m = support_metric(row)
print(m.weighted_precision_first_citation, m.weighted_recall_first_citation)
EOF
```

| Quantity | Paper §3.4 | RAGDoll |
|---|---|---|
| Weighted precision | 0.75 | 0.75 |
| Weighted recall | 0.5 | 0.5 |

Additional behaviours confirmed by the same probe:

- All sentences cited → precision == recall (0.75 == 0.75), matching the §3.4
  claim about the first-citation protocol.
- One unjudged citation (`-1`) among two sentences → 1.0 / 1.0, i.e. the
  unjudged sentence leaves *both* denominators rather than scoring 0.
- A sentence citing `[FS, NS]` → `all_judged` precision 0.5 vs `first_citation`
  precision 1.0, confirming the mean-over-citations numerator.

Regression coverage in the submodule:
`tests/test_support.py::test_support_metric_matches_reference_arithmetic`,
`tests/test_metrics.py::test_calculate_scores_matches_reference_semantics`,
`tests/test_prompt_provenance.py::test_support_prompt_template_byte_identical`.

---

## Quick reference: where each formula lives

| Measure | Source definition | Implementation |
|---|---|---|
| Support weights FS/PS/NS = 1.0/0.5/0.0 | arXiv:2504.15205 §3.2, §3.4 | `support/metrics.py:12` |
| Weighted precision (first citation) | §3.4 | `support/metrics.py:107` |
| Weighted recall (first citation) | §3.4 | `support/metrics.py:110` |
| Weighted P/R (all judged citations) | RAGDoll extension | `support/metrics.py:111-112` |
| Hard (FS-only) P/R | RAGDoll extension | `support/metrics.py:121-122` |
| Support judge prompt | §3.2 Figure 1 | `support/prompts.py:3` |
| Kendall τ-b | §4.1 | `stats.py:10` |
| Nugget coverage (4 variants) | AutoNuggetizer / AutoPi harness | `nuggetizer/metrics.py:48` |
| Rubric weighted score | ResearchRubrics | `rubric/metrics.py:30` |
| Rubric category failure rate | ResearchRubrics Eq. 2 | `rubric/metrics.py:87` |
| Pairwise preference rate | — | `arena/metrics.py:48` |
| Bradley–Terry arena rating | `lmarena/arena-rank` | `arena/metrics.py:114` |
| UMBRELA 0–3 relevance grade | UMBRELA | `umbrela/prompts.py:20` |
