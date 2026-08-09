## 1. $50 design

### Block 0 — reuse existing artifacts, $0 generation

Reuse all five existing Luna runs. Do not regenerate them.

| Cell | Existing `run_id` | Relative to reference |
|---|---|---|
| L0 | `brief-revise-iter1-exp15` | Reference configuration |
| L1 | `brief-revise-iter2-exp15` | Compound v2-brief/v2-grading treatment |
| L2 | `brief-revise-iter3-exp15` | Historical requirement-labelled screener on |
| L3 | `brief-revise-roundB-exp15` | Adjacent pages on |
| L4 | `brief-revise-roundC-exp15` | Word-budget guidance on; use when completed |

L1 should be described as a **compound treatment**, not a clean estimate of `requirements_brief_schema`, because its grading/review behavior also changed.

### Canonical reference configuration

The model comparison must hold every structural setting at the L0 configuration:

```text
requirements_brief=on
requirements_brief_schema=v1
brief_word_budget=off
review_revise_pass=on
adjacent_page_augmentation=off
retrieval_engine_set=semantic,keyword
search_k=10
search_result_filter=off
search_preview_policy=full
stage_search_results=on
judge_relevance_tool=off
commit_release=off
requirement_labelled_retrieval_screener=off
```

For the model experiment, independently configure the three model roles. This requires a small configuration/plumbing change because the current CLI couples them. It does not require changing prompts or research logic.

### Block 1 — four new main-generator cells

Keep the brief analyst and reviewer on Luna and vary only the main research/writer model.

| New `run_id` | Main research/writer | Brief analyst | Reviewer | Topics |
|---|---|---|---|---:|
| `br-model-main-terra-exp15-b1` | `gpt-5.6-terra` | `gpt-5.6-luna` | `gpt-5.6-luna` | 15 |
| `br-model-main-sol-exp15-b1` | `gpt-5.6-sol` | `gpt-5.6-luna` | `gpt-5.6-luna` | 15 |
| `br-model-main-oss120b-exp15-b1` | `openai.gpt-oss-120b-1:0` | `gpt-5.6-luna` | `gpt-5.6-luna` | 15 |
| `br-model-main-qwen80b-exp15-b1` | `qwen.qwen3-next-80b-a3b` | `gpt-5.6-luna` | `gpt-5.6-luna` | 15 |

Use Qwen in a confirmed supported region, `us-east-1` or `us-west-2`.

Together with L0, this creates a controlled five-level experiment for the **main generator model**:

```text
Luna, Terra, Sol, GPT-OSS-120B, Qwen3-Next-80B
```

This requires exactly **4 new 15-topic generation batches**, or 60 new topic runs.

The existing opponent outputs from `aus-agent-v2-exp15-luna` must be reused for every battle.

### Execution controls

1. Freeze the code revision, prompt bytes, retrieval corpus/index revision, topic order, and all non-model parameters.
2. Interleave execution by topic and configuration rather than running all 15 topics for one model and then moving to the next. This reduces calendar-time and service-condition confounding.
3. Record actual input, output, cached, and processed tokens separately by call role.
4. Preserve raw output even if a review call fails open.
5. Use randomized, opaque system aliases during judging. Do not expose model names or run IDs to the judge.
6. Rejudge Block 0 and Block 1 under one common judging protocol. This is cheap and avoids mixing old and new judge conditions.

---

## 2. Cost plan and hard-cap control

The main loop baseline is approximately:

\[
15 \times 106{,}646 \approx 1.60\text{ million processed tokens per batch}.
\]

Allowing 5–15K additional brief/review tokens per topic gives roughly:

\[
1.68\text{–}1.83\text{ million processed tokens per 15-topic batch}.
\]

Processed tokens are not the same thing as billable input/output tokens, so they cannot by themselves establish an exact dollar cost.

### Conservative budget envelope

| Item | Count | Envelope each | Budget |
|---|---:|---:|---:|
| Terra main-generator batch | 1 | $8 | $8 |
| Sol main-generator batch | 1 | $8 | $8 |
| GPT-OSS Bedrock batch | 1 | $12 | $12 |
| Qwen Bedrock batch | 1 | $12 | $12 |
| Rejudge up to 9 cells, 30 ordered battles each | 9 | $0.35 | $3.15 |
| Unallocated safety reserve | — | — | **$6.85** |
| **Total cap** | | | **$50.00** |

The Azure envelope is consistent with the deliberately pessimistic `$3/M input + $12/M output` placeholder unless output constitutes an unusually large fraction of processed tokens. The Bedrock envelopes are intentionally higher because their actual rates are unmeasured here.

### Mandatory hard-budget gate

Because GPT-OSS and Qwen pricing is genuinely unknown, no token-only estimate can guarantee the monetary cap. Therefore:

1. Before completing either Bedrock batch, run its first scheduled topic and obtain the provider’s actual billable-token or dollar meter.
2. Include that topic as topic 1 of the final cell; it is not a throwaway regeneration.
3. Project the 15-topic cost using:
   - actual first-topic cost,
   - observed token count,
   - the historical high-tail topic range,
   - at least a 25% contingency.
4. Proceed only if all four cells plus judging remain projected below $47, retaining at least $3 emergency headroom.
5. Enforce a cumulative job-level monetary stop at $47 before judging, then spend at most the reserved judging amount.
6. Do not silently replace a model or omit expensive topics. If provider metering shows that the specified four batches cannot fit, stop before exceeding $50 and report the provider-price constraint.

Expected spending is approximately **$34–43**, including judging. The table above is the authorization envelope, not a claim that the unknown Bedrock rates are known.

---

## 3. How the design weights the LLM question

Of the **four new generation cells**:

- **4/4 answer the main-generator model question**
- **0/4 introduce a new structural treatment**
- **0/4 estimate a model × structure interaction**

This is deliberate.

The current evidence has five Luna structural runs but no non-Luna run at all. Spending the first $50 on more structural variants would deepen an already one-model-only design while leaving the user’s main question unanswered. A complete five-model comparison at one fixed configuration is more informative than a partial model comparison plus one or two disconnected structural cells.

The structural evidence is not discarded:

- L0 vs L3 estimates the adjacent-pages contrast within Luna.
- L0 vs L2 estimates the historical screener contrast within Luna.
- L0 vs L4 estimates word-budget guidance within Luna once L4 completes.
- L0 vs L1 measures the compound v2-brief/v2-grading treatment.

The $50 tier cannot reliably determine whether those structural effects generalize across models. That becomes the first extension block.

Importantly, varying only M1 means the resulting contrast is specifically the **main research/writer model effect**, not the effect of changing the analyst, writer, and reviewer as one coupled stack.

---

## 4. Analysis method

### Unit of analysis

The experimental unit is the generated candidate answer for a particular:

```text
topic × configuration × replicate
```

The two presentation orders are repeated judge observations of that same candidate/opponent pair, not independent generated samples.

Retain the two raw order-specific judgments. Do not use only the existing clean W/L/amb summary as the primary data, because discarding order-discordant battles can introduce selection bias.

### Primary arena model

Encode every order-specific judgment as:

```text
candidate preferred
tie / ambiguous
opponent preferred
```

Fit an ordinal or multinomial mixed-effects model with:

- fixed effect for main generator model;
- fixed indicators for the reusable structural treatments;
- fixed effect for candidate presentation position/order;
- topic random intercept;
- candidate-pair random intercept, nesting the two order observations for the same output pair.

Conceptually:

\[
\text{preference} \sim
\text{main model}
+ \text{adjacent}
+ \text{word budget}
+ \text{historical screener}
+ \text{v2 compound}
+ \text{presentation position}
+ (1|\text{topic})
+ (1|\text{topic:cell:replicate})
\]

If the ordinal proportional-odds assumption is poor, use a multinomial mixed model instead.

Because the structural variants occur only under Luna in this tier, their estimates rely on an additive model. Report them as **within-Luna/exploratory contrasts**, not universal structural main effects.

### Planned model tests

Use this hierarchy:

1. Omnibus likelihood-ratio or Wald test for the five-level main-model factor.
2. Four preplanned contrasts against Luna:
   - Terra − Luna
   - Sol − Luna
   - GPT-OSS − Luna
   - Qwen − Luna
3. Holm correction across those four contrasts.
4. Exploratory pairwise model comparisons only after the omnibus result, clearly labeled exploratory.

Report:

- odds ratios with 95% confidence intervals;
- model-adjusted probability that the candidate beats the opponent;
- probability of tie/ambiguity;
- absolute percentage-point difference from Luna;
- topic-level win/tie/loss counts for interpretability.

For categorical arena outcomes, odds ratios and predicted probabilities are more appropriate than partial eta-squared.

### Continuous or ordinal rubric grades

If rubric grades are also available:

- use a cumulative-link mixed model for ordinal grades;
- use a linear mixed model only when the rubric score is sufficiently granular and residual diagnostics are acceptable;
- include topic as a random intercept and the same fixed effects;
- report standardized mean differences and confidence intervals;
- partial eta-squared may be supplied for the linear-model analysis, but it should be secondary to model-adjusted contrasts.

For multiple rubric dimensions, report each dimension and control false discovery rate with Benjamini–Hochberg. Do not average dimensions unless the aggregate was defined before inspecting results.

### Position bias and order consistency

Use both orders for every candidate/opponent pair.

Report four judge diagnostics:

1. estimated presentation-position coefficient;
2. percentage of pairs with the same substantive winner in both orders;
3. percentage that reverse when order reverses;
4. percentage involving a tie/ambiguous judgment in either order.

Also fit a model × presentation-position interaction as a diagnostic. If it is large, report position-adjusted marginal probabilities and avoid ranking models solely from raw clean wins.

Sensitivity analyses:

- primary: all raw ordered judgments;
- secondary: topic-level score, e.g. candidate preference `+1`, tie `0`, opponent preference `−1`, averaged over both orders;
- tertiary: clean-consistent pairs only, explicitly labeled as a sensitivity analysis rather than the primary result.

Since Terra is also a candidate generator in one cell, a Terra judge could have style-family affinity. Blind aliases address explicit identity leakage but not latent stylistic affinity. Treat this as a limitation; a later judge-replication block should use at least one non-Terra judge.

### Sparse-design limitations

Do not fit arbitrary high-order interactions in the $50 tier. They are not identifiable.

The model × adjacent-pages interaction, for example, cannot be estimated until adjacent pages has been run under the other four main models. The correct output is an explicit “not estimable in this block,” not a regularized interaction coefficient presented as established evidence.

With only 15 topics, emphasize confidence intervals and topic-wise consistency over p-value thresholds.

---

## 5. Ordered extension blocks

Blocks are cumulative. No prior cell is replaced.

Estimated block costs use the same conservative envelopes and should be recalibrated from actual Block 1 billing.

### Block 0 — existing Luna structural cells

- Cost: $0 generation
- Purpose: recover existing within-Luna structural evidence.
- Cells: L0–L4 above.

### Block 1 — $50 tier: isolated main-model sweep

- New cells: 4
- Estimated total including unified judging: $34–43
- Authorization cap: $50
- New question answered: **Does the main research/writer model materially change performance when analyst, reviewer, prompts, retrieval, and opponent are fixed?**

### Block 2 — main model × adjacent-pages interaction

Run the L3 adjacent-pages treatment under the other four main models:

| Run ID | Main | Analyst/reviewer | Structural difference |
|---|---|---|---|
| `br-main-terra-adj-exp15-b2` | Terra | Luna/Luna | adjacent pages on |
| `br-main-sol-adj-exp15-b2` | Sol | Luna/Luna | adjacent pages on |
| `br-main-oss120b-adj-exp15-b2` | GPT-OSS | Luna/Luna | adjacent pages on |
| `br-main-qwen80b-adj-exp15-b2` | Qwen | Luna/Luna | adjacent pages on |

All other settings remain canonical.

- New cells: 4
- Approximate incremental cost: $34–43
- Existing L0/L3 plus Blocks 1/2 form a complete `5 main models × 2 adjacent-page levels` grid.
- New questions:
  - Does adjacent-page augmentation help on average?
  - Does its effect depend on the main model?
  - Are model rankings stable under a retrieval change?

Adjacent pages is chosen first because it is currently available, requires no additional LLM call, and L3 is the best existing Luna result, albeit with weak evidence.

### Block 3 — brief-analyst model sweep

Fix:

```text
main model = Luna
reviewer = Luna
canonical structural configuration
```

Run four cells with analyst equal to Terra, Sol, GPT-OSS, and Qwen.

- New cells: 4
- Approximate incremental cost: $30–41
- New question: **Does the model used only for requirements analysis affect final answer quality?**
- Combined with L0, this supplies all five M2 levels while isolating M2.

### Block 4 — reviewer model sweep

Fix:

```text
main model = Luna
brief analyst = Luna
canonical structural configuration
```

Run four cells with reviewer equal to Terra, Sol, GPT-OSS, and Qwen.

- New cells: 4
- Approximate incremental cost: $30–41
- New question: **Does reviewer model choice affect the final revised answer independently of the generator?**
- Combined with L0, this supplies all five M3 levels while isolating M3.

Blocks 1, 3, and 4 are one-factor role sweeps, not a `5³` role cross. They identify which role is worth crossing later.

### Block 5 — replication of the five baseline main-model cells

Generate one additional independent replicate for each of the five Block 1 baseline configurations, including a new Luna baseline replicate.

- New cells/batches: 5
- Approximate incremental cost: $42–52; split into two sub-blocks if necessary.
- New questions:
  - How much variation is due to generation stochasticity?
  - Are model rankings reproducible?
  - Are observed differences larger than run-to-run variation?

Use distinct replicate IDs and preserve the same topic blocking.

### Block 6 — word-budget interaction

Once L4 is complete, run word-budget guidance under Terra, Sol, GPT-OSS, and Qwen while retaining Luna analyst/reviewer for the isolated M1 comparison.

- New cells: 4
- Approximate incremental cost: $34–43
- Produces a complete `5 main models × 2 word-budget levels` grid.
- New question: Does explicit answer-length allocation help all models or only particular generators?

### Later role interactions

Only after Blocks 1, 3, and 4 identify promising role models should mixed-role cells be added. For example, if Sol is the best writer and Terra the best reviewer, add:

```text
main=Sol, analyst=Luna, reviewer=Terra
```

and its matched controls. Do not begin with the full `5³` role cross.

---

## 6. Factors excluded from the $50 tier

The $50 tier introduces no new structural variants. The following remain fixed or are used only through existing artifacts.

| Factor | Decision and reason |
|---|---|
| `requirements_brief` | Fixed on. Turning it off also changes the information available to review, making interpretation less clean. |
| `requirements_brief_schema` | Fixed v1. Existing v2 cell regressed and is confounded with v2 grading. |
| `brief_word_budget` | No new generation; reuse L4 when complete. Cross it later only if the initial result warrants it. |
| `review_revise_pass` | Fixed on. Important, but a review-off study requires a matched model grid and competes directly with the requested model sweep. |
| `adjacent_page_augmentation` | Fixed off in Block 1; existing L3 is reused. It becomes the first interaction extension. |
| `retrieval_engine_set` | Fixed `semantic,keyword`. Four levels would consume the budget and introduce installation/support differences. |
| `search_k` | Fixed 10. Lower priority than model choice and entangled with retrieval volume/cost. |
| `search_result_filter` | Fixed off. Not currently wired into `brief_revise_agent`, and exact variants lack supplied positive evidence. |
| `search_preview_policy` | Fixed full staging. Prior sibling-system result was inconclusive, and generated previews may add another model-dependent call. |
| `stage_search_results` | Fixed on. Turning it off is a large protocol change with no supplied live quality evidence. |
| `judge_relevance_tool` | Fixed off. Adds tool-schema and side-conversation behavior; no brief-revise quality result. |
| `commit_release` | Fixed off. It was never invoked in 15 real sibling runs, so it is unlikely to be informative at this budget. |
| Historical requirement-labelled screener | Fixed off for new runs. Reuse L2 only; it was worse and would require restoring reverted code. |
| Analyst model M2 | Fixed Luna in Block 1 so M1 is isolated; tested in Block 3. |
| Reviewer model M3 | Fixed Luna in Block 1 so M1 is isolated; tested in Block 4. |

## Final specification

The $50 experiment is therefore:

- reuse five existing Luna artifacts;
- add exactly four 15-topic batches;
- vary only the main generator across Terra, Sol, GPT-OSS, and Qwen;
- keep the brief analyst and reviewer on Luna;
- use the iter1 structural configuration;
- reuse the existing AUS opponent;
- judge every pair in both orders under one blinded protocol;
- analyze raw ordered preferences with topic blocking and explicit position adjustment;
- reserve structural interactions and role-model sweeps for ordered extension blocks.

This maximizes direct information about model choice while leaving a clean path to a `5 × 2` model-by-structure design, isolated analyst/reviewer sweeps, and later replication.