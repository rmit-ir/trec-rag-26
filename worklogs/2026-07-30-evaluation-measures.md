# Submodule refresh + evaluation-measures documentation

## Goal

Two unrelated asks in one session:

1. Update all git submodules.
2. Read arXiv:2504.15205 (*Support Evaluation for the TREC 2024 RAG Track:
   Comparing Human versus LLM Judges*) and document the evaluation measures
   implemented in this repo, on the expectation that TREC RAG 2026 will use the
   same formulas.

## Part 1: Submodules

Both submodules updated with `git submodule update --init --remote --recursive`,
then reattached to `main` (the `--remote` update leaves a detached HEAD, which
would silently drop the branch tracking on the next pull).

| Submodule | Before | After |
|---|---|---|
| `data/official/trec-rag-2026-data` | `be206c5` | `a6255c1` (+4 commits) |
| `evaluation/ragdoll` | `1f06719` | unchanged — already at `origin/main` |

The four new upstream commits are two merged PRs:

- **#1 Simplify TREC RAG data files** — renames the baseline artifacts:
  - `piika_gpt-5.6-sol_medium_agentic_bm25.jsonl` →
    `gpt-5.6-sol_medium_agentic-search_bm25_output-mode-answer.jsonl`
  - `piika_gpt-5.6-sol-retrieval.trec` →
    `gpt-5.6-sol_medium_agentic-search_bm25_output-mode-ranked-list.trec`
- **#2 Document canonical RAG prompts and repair input workflow** — rewrites
  `baselines/rag/README.md` (184 lines changed) and
  `baselines/retrieval/README.md`.

Both are pure renames/docs — no content change to the baseline runs themselves.
Anything in our tree hardcoding the old `piika_*` filenames will break; nothing
under `src/` or `tasks/` referenced them at the time of writing.

## Part 2: Evaluation measures

### Source

Fetched to `tmp/papers/2504.15205.pdf`. The user also had a local copy at
`~/Downloads/2504.15205v1.pdf`; verified byte-identical by SHA-256
(`d60e93a406b54650b9e28980b70ace00cf9126c23a04f0f2de51fb35a2bf88df`), so both
are the same v1, 16 pages.

Note for future sessions: the visual `Read` tool rendered only the first 4 pages
of this PDF. Full text came from a `pypdf` extraction pass, which reported all
16. **Don't trust a page count inferred from the image-render path.**

### Deliverable

`docs/evaluation-measures.md` — covers all five scoring families in
`evaluation/ragdoll/`, each formula traced to its source definition with
line-level implementation pointers (verified individually with `sed -n`, not
guessed):

| Measure | Source | Implementation |
|---|---|---|
| Support weights FS/PS/NS = 1.0/0.5/0.0 | §3.2, §3.4 | `support/metrics.py:12` |
| Weighted precision / recall (first citation) | §3.4 | `support/metrics.py:107,110` |
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

### The core formulas (paper §3.4)

With `C` = sentences having ≥1 citation, `n` = all sentences in the answer, and
`d_i1` = the *first* cited passage of sentence `aᵢ`:

```
Weighted Precision = Σ_{aᵢ ∈ C} s(aᵢ, d_i1) / |C|
Weighted Recall    = Σ_{aᵢ ∈ C} s(aᵢ, d_i1) / n
```

`s(aᵢ,dⱼ)` = 1.0 (Full Support) / 0.5 (Partial Support) / 0.0 (No Support).
Precision penalizes overcitation; recall penalizes undercitation. A sentence
with zero citations is automatically No Support (§3.2) — it lowers recall and
leaves precision untouched.

### Findings worth keeping

- **P and R are identical unless sentences go uncited.** A direct consequence of
  the first-citation-only protocol, stated in §3.4. So any P/R gap in a score
  table is purely a readout of how many sentences carried no citation — not of
  citation *quality*.
- **First-citation-only is a budget decision, not a design preference** (§3.3).
  Judging all `k ≤ 20` cited passages per sentence across 45 runs was
  infeasible, so the organizers took sparse annotation to buy topic diversity.
  The paper explicitly defers multi-citation evaluation to future work.
- **RAGDoll ships the paper's metric plus four extensions the paper does not
  define:** `*_all_judged_citations` (the deferred future work) and `hard_*`
  (FS-only, PS scored 0). Only `*_first_citation` is the official metric. The
  doc marks which is which so an extension never gets reported as an official
  score.
- **`-1` is a RAGDoll-only sentinel** for a judge failure
  (`status != "completed"`), and it *removes* the sentence from both numerator
  and denominator. This is materially different from a genuine zero-citation
  sentence, which counts as NS and drags recall down. Confusing the two
  inflates scores.
- **Expected judge bias when comparing an LLM judge to humans** (§4.1): GPT-4o
  skews toward Partial Support, humans toward No Support, so LLM-judged
  weighted P/R runs *higher*. Largest off-diagonal confusion cell from-scratch
  is GPT-4o=PS / human=NS at 15.1%.
- **Cohen's κ (Figure 4) is not implemented in RAGDoll.** The doc records the
  paper's reference values but flags the gap — it would be needed to replicate
  the 537-pair judge-agreement study.

### Paper reference values recorded in the doc

Judge agreement, GPT-4o vs human (§4.1, §4.2):

| Quantity | Manual from scratch | With post-editing |
|---|---|---|
| Perfect agreement | 56% (13.7 + 11.9 + 30.4) | 72.1% (15.9 + 18.7 + 37.5) |
| Weighted precision τ (run-level) | 0.884 | 0.792 |
| Weighted precision τ (per-topic / individual) | 0.596 / 0.470 | 0.629 / 0.611 |
| Weighted recall τ (run / per-topic / individual) | 0.892 / 0.644 / 0.539 | — |

Cohen's κ on the 537-pair disagreement study (Figure 4): independent human vs
GPT-4o 0.29 / 0.27, vs NIST human −0.03 / 0.07; LLAMA-3.1 405B vs GPT-4o
0.60 / 0.46.

## Validation

Rather than assume RAGDoll matches the paper, ran the §3.4 worked example
through the real implementation. Probe script preserved at
`worklogs/assets/2026-07-30-support-metric-paper-probe.py` (re-run and confirmed
reproducing after saving, so the recorded output in its docstring is live, not
transcribed):

```bash
cd evaluation/ragdoll && uv run python ../../worklogs/assets/2026-07-30-support-metric-paper-probe.py
```

| Case | Expected | RAGDoll |
|---|---|---|
| §3.4 example — weighted precision | 0.75 (paper) | 0.75 |
| §3.4 example — weighted recall | 0.5 (paper) | 0.5 |
| §3.4 example — hard P / R | — | 0.5 / 0.3333 |
| All sentences cited → P == R | P == R (§3.4 claim) | 0.75 == 0.75 |
| One unjudged (`-1`) of two sentences | excluded from both denominators | 1.0 / 1.0, `sentences=2` |
| Sentence citing `[FS, NS]` | mean, not first | `all_judged` 0.5 vs `first_citation` 1.0 |

Every case behaved as documented. Existing regression coverage in the
submodule: `tests/test_support.py::test_support_metric_matches_reference_arithmetic`,
`tests/test_metrics.py::test_calculate_scores_matches_reference_semantics`,
`tests/test_prompt_provenance.py::test_support_prompt_template_byte_identical`
(the judge prompt is already byte-pinned to Figure 1).

Note: running the probe created `evaluation/ragdoll/.venv` (72 packages) as a
side effect of `uv run` inside the submodule. That path is gitignored.

## Caveat on the premise

The 2026 official data in `data/official/trec-rag-2026-data` does **not** state
its evaluation measures anywhere — grepping the four READMEs for
`weighted precision|nugget|umbrela|support|ndcg|trec_eval|measure|metric`
returned nothing. So "2026 uses the same formulas as 2024" is an expectation,
not something confirmable from the track spec. `docs/evaluation-measures.md`
says so explicitly rather than asserting equivalence as fact. Worth re-checking
once the 2026 track guidelines publish their measures.

> **Resolved later the same day** — see
> `worklogs/2026-07-30-spec-revendor-validator-relax.md`. The guidelines had
> *already* published them; the wrong place was searched. The vendored
> `skills/trec-rag-2026-track-guidelines/` was still at v0.3.0 while upstream was
> at v0.6.0, which names weighted citation precision/recall and cites the same
> study. The measures section of the data submodule's READMEs was never going to
> carry them. `docs/evaluation-measures.md` §1.8 now records what the spec does
> and does not pin down.

## Files

- `docs/evaluation-measures.md` — new
- `worklogs/assets/2026-07-30-support-metric-paper-probe.py` — new
- `data/official/trec-rag-2026-data` — submodule pointer `be206c5` → `a6255c1`
