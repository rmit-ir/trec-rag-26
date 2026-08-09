# 2026-08-09 -- gpt-5.6-sol review of the oss_agent deep-research request

Three-turn working dialogue with `gpt-5.6-sol` (OpenAI backend, used here ONLY
as an advisory/design consultant -- not part of `oss_agent`'s own open-weight
generation pipeline), reviewing the research plan in
`worklogs/assets/2026-08-09-oss-agent-deep-research-prompt.md` before it goes
to Gemini Deep Research. Total cost: **$0.4476** of a $10 cap for this
conversation (real `bedrock-openai-gpt-5-6-sol-useast1` rate card: $5.5/1M
input, $33/1M output -- OpenAI-backend calls, so this is the best available
real-price proxy, not a metered OpenAI-backend bill).

## Turn 1 -- the request itself

Sent `worklogs/assets/2026-08-09-oss-agent-deep-research-prompt.md` in full
as the first user message. Sol's response (in=7088 out=9428, $0.3501):

## 1. Bottleneck-identification plan

I would run three paired diagnostics before making substantial architectural changes. Together they separate:

1. evidence acquisition/curation,
2. implicit-obligation discovery,
3. synthesis from adequate evidence,
4. raw model capability.

For all comparisons, analyze **paired topic-level differences**, not pooled criterion instances as if independent. On the 15-topic development set, I would require either:

- `overall` improvement of **≥0.133**—two topic-grade increments—rather than 0.067;
- or a target-axis improvement of **≥0.15/2**, with no `overall` decline worse than 0.067.

Those are pilot thresholds, not adoption thresholds. Adoption still requires an independent topic set and preferably arena confirmation.

### Diagnostic D1: crossed fixed-evidence replay

**Evidence status:** directly motivated by your data; system-specific diagnostic.

Construct two frozen evidence packages per topic:

- **E-Q:** the exact committed document set, document order, and preferably committed excerpts/context from the qwen run.
- **E-P:** the equivalent package from `brief_revise_agent` or `aus_agent_v2`.

Replay them without search or commit tools. Preserve the same answer instructions, raw request, references mapping, and 1024-word limit. Generate the following 2×2:

| Evidence | Writer |
|---|---|
| E-Q | qwen |
| E-P | qwen |
| E-Q | proprietary reference writer |
| E-P | proprietary reference writer |

The proprietary cells are diagnostic controls, not submission-eligible configurations. If budget or policy precludes fresh proprietary calls, the two qwen cells plus the existing proprietary E-P answer are still informative, but less clean.

Add a **replay-validity control**: compare qwen writing from E-Q with its original live answer. If replay changes Synthesis by more than 0.10 or `overall` by more than 0.133, the replay prompt is not preserving the live task and conclusions should be withheld.

#### Interpretation

- **qwen(E-P) − qwen(E-Q) ≥ +0.15 on Implicit Criteria:** retrieval/curation is materially responsible.
- **qwen(E-P) − qwen(E-Q) ≥ +0.15 on Synthesis:** qwen’s synthesis is evidence-sensitive; its live evidence is too incomplete or noisy.
- **Proprietary − qwen ≥ +0.20 on Synthesis on both evidence pools:** strong evidence of a writer-capability ceiling.
- **qwen(E-P) approaches proprietary(E-P) within 0.10:** acquisition/curation, not prose generation, is the dominant problem.
- **Both evidence origin and writer each move ≥0.15:** mixed bottleneck; pursue retrieval and synthesis in parallel.

**Minimum pilot:** eight stratified topics: four with the largest qwen/proprietary Implicit gap and four with the largest Synthesis gap.  
**Estimated cost:** approximately $12–25 including fresh proprietary controls and judging; substantially less if existing proprietary outputs can be reused.

### Diagnostic D2: obligation-plan transplant

**Evidence status:** directly supported by S14’s +0.123 Implicit-axis signal and the observed supporting-role gap.

Hold fixed:

- qwen as main loop/writer,
- retrieval engines,
- adjacent-page augmentation,
- round cap,
- reviewer,
- temperature/seed policy.

Vary only the pre-flight obligations supplied to it:

1. qwen brief + qwen blind scout;
2. a stronger previously generated proprietary brief/scout package;
3. optionally, an open-weight cross-model package, such as GPT-OSS brief/scout with qwen main.

Do **not** use official rubric criteria as the transplanted plan; that would test criterion leakage rather than realistic obligation discovery. Use blind plans generated from the raw request.

To prevent “more text” from being the treatment, normalize each package to the same deterministic schema and cap:

```json
{
  "obligations": [
    {
      "id": "I3",
      "requirement": "...",
      "implicit": true,
      "priority": "high",
      "suggested_queries": ["..."]
    }
  ]
}
```

Cap at, for example, 12 obligations and 700 tokens.

#### Interpretation

- Strong-plan treatment improves Implicit Criteria by **≥0.15**, with `overall` non-decreasing: obligation discovery/supporting roles are a real bottleneck.
- It improves neither Implicit nor retrieval coverage: the writer is failing to operationalize a sufficient plan.
- It improves evidence coverage but not final grading: synthesis/compression is dropping discovered obligations.
- GPT-OSS plans match proprietary plans: the −0.200 role gap is fixable while remaining open-weight.

**Minimum pilot:** 10 paired topics; use topics with at least eight implicit criteria where possible.  
**Estimated cost:** $5–10 if proprietary plans already exist.

### Diagnostic D3: query transplant and retrieval attribution

**Evidence status:** novel system-specific diagnostic, requiring search-log instrumentation you do not currently have.

For each topic, collect:

- every search query,
- selected engine,
- empty-result indicator,
- rank of documents eventually cited,
- rank of documents cited by the strong proprietary run,
- obligation ID the query was intended to support.

Run two counterfactual retrieval packages:

1. qwen-generated queries executed unchanged;
2. proprietary-run queries executed unchanged against the same engines and corpus.

Then either:

- stage the resulting pools for the same qwen writer, or
- measure retrieval diagnostics before writing: strong-document Recall@20, MRR, empty-result rate, obligation coverage.

A particularly decisive comparison is **query transplant with engine held fixed to `hybrid`**. This distinguishes query formulation from engine selection.

#### Interpretation

- Proprietary queries improve strong-document Recall@20 by **≥10 percentage points** or reduce uncovered obligations by **≥20%**: query writing is a bottleneck.
- Retrieval improves but answer axes do not: synthesis is failing to use better evidence.
- Retrieval metrics are similar but E-P still wins in D1: curation/commit decisions, rather than querying, are responsible.
- Neither query nor evidence origin matters, while writer identity does: raw generation ceiling.

**Minimum pilot:** eight topics, reusing D1 topics.  
**Estimated cost:** $3–6 plus modest logging work.

### Recommended supplementary audit

On five D1 topics, manually classify every failed Implicit or Synthesis criterion into:

1. obligation never discovered;
2. discovered but never searched;
3. evidence found but not committed;
4. committed but omitted;
5. present but too vague;
6. present but poorly organized/connected;
7. lost to word-budget compression.

This is not a substitute for the paired experiments, but it makes their aggregate result actionable.

---

## 2. Architecture and component proposals

### A1. Evidence-grounded synthesis compiler

**Evidence status:** novel system-specific hypothesis; should be funded if D1 implicates writing or mixed causes.

The current reviewer sees a complete draft and asks for a revision. A weaker model may be poor at globally restructuring already-written prose. Move the structured reasoning before prose finalization.

#### Mechanism

Immediately before the first final answer, invoke an open-weight planning call over:

- request;
- normalized obligation list;
- committed document IDs and full evidence;
- current remaining word budget.

Require a compact report blueprint:

```json
{
  "sections": [
    {
      "heading": "...",
      "budget_words": 130,
      "obligations": ["I2", "E4"],
      "claims": [
        {
          "claim": "...",
          "docids": ["D17", "D44"],
          "relation": "comparison|cause|qualification|fact"
        }
      ]
    }
  ],
  "omitted_low_priority": ["I9"]
}
```

Apply deterministic validation:

- every high-priority obligation appears;
- total section budgets ≤950, leaving citation/layout margin;
- every claim has 1–3 docids;
- cited docids are committed.

Append the validated blueprint to the live conversation and ask the main model to write from it. The existing reviewer then checks primarily for omissions and incoherent transitions, not generic quality.

This differs from the previously unsuccessful typed coverage ledger: it does **not** replace free-text commits or continuously constrain retrieval. It is a late, evidence-conditioned **composition plan** with explicit word allocation.

**Targets:** Synthesis primarily; Implicit Criteria secondarily. Likely relevant to both standalone grading and arena preference because organization and completeness are pairwise-visible.

**Cost:** one additional open-weight call/topic; modest latency.

**Pilot:** 15 paired topics.  
**Go:** Synthesis +0.15 and `overall` +0.133, or Synthesis +0.20 with no overall/citation decline.

### A2. Obligation union with deterministic reconciliation

**Evidence status:** partly directly supported by S14; implementation is a novel refinement.

Keep the existing brief and blind scout, but stop merely appending two advisory texts. Mechanically union their outputs before the main loop:

1. both produce normalized obligation records;
2. deterministic lexical/embedding-free deduplication merges near-identical obligations;
3. disagreements are retained as separate checks rather than resolved by another generative call;
4. each obligation receives:
   - explicit/implicit label,
   - priority,
   - one broad query,
   - one exact-term query,
   - target word budget.

The main loop receives a compact checklist, while the original natural-language plans remain available only if space permits.

This targets a likely open-weight-specific failure: qwen may not reliably reconcile two long, partially redundant advisory blocks. The mechanism makes S14’s discovered obligations operational.

**Targets:** Implicit Criteria first; Instruction Following and Synthesis second.

**Cost:** no extra calls if existing brief/scout outputs are structured; otherwise only prompt/schema changes.

**Pilot:** 10 topics using D2.  
**Go:** Implicit +0.15, no `overall` loss greater than 0.067.

### A3. Criterion-partitioned claim union

**Evidence status:** novel implementation intended to realize the oracle criterion-union headroom. Unlike the failed best-of-four, it creates deliberate diversity.

Run three independent open-weight branches with non-overlapping responsibilities:

1. **Explicit/factual branch**
   - hybrid retrieval;
   - named entities, dates, quantities, requested comparisons;
   - outputs evidence-backed claim records.

2. **Implicit/critical-reader branch**
   - obligation scout output;
   - searches for caveats, mechanisms, limitations, counterarguments, contextual implications;
   - uses hybrid plus targeted Boolean retrieval.

3. **Synthesis/relationship branch**
   - searches specifically for evidence connecting facts: causal links, comparisons, chronology, tensions, and consensus/disagreement;
   - instructed not to duplicate standalone facts unless needed for a relationship.

Each branch returns claims, not a full polished report:

```json
{
  "claim": "...",
  "obligation_ids": ["I4"],
  "importance": 3,
  "supporting_docids": ["D8", "D31"],
  "support_excerpt": "...",
  "estimated_words": 45
}
```

A deterministic union stage:

- groups claims by obligation;
- rejects records whose docids were not fetched;
- deduplicates near-identical claims;
- reserves word budgets, for example:
  - 55% required explicit content,
  - 30% implicit/high-value context,
  - 15% synthesis transitions and qualification;
- selects claims under an approximately 900-word content budget using priority and marginal obligation coverage.

A final open-weight editor receives the selected claims **plus their source documents**, not unsupported branch prose. It may compress and connect claims but may not introduce new factual claims. Citation indices remain traceable through docids and are mapped by the existing deterministic mapper.

This creates real diversity through **criterion partition, retrieval policy, and drafting role**, not stochastic reruns.

**Targets:** Implicit Criteria and Synthesis; potentially arena strongly. Citation Quality is a guardrail, not the optimization target.

**Cost:** roughly three branch loops plus one editor; approximately 3–5× current generation cost, still likely under $1/topic with qwen.

**Pilot:** eight D1 topics first.  
**Go:** at least +0.20 on one target axis and +0.133 `overall`, with the other target axis non-decreasing. Then run all 15 and an independent set.

### A4. Two-stage targeted revision instead of generic repeated revision

**Evidence status:** untested external pattern adapted to this system.

Do not simply allow “more revisions.” Give two revisions orthogonal jobs:

1. **Coverage revision:** identify high-priority obligations absent from the draft and propose exact insertion/deletion patches with docids.
2. **Synthesis revision:** improve ordering, comparisons, causal connections, and qualification while preserving factual claims and citations.

Only invoke revision two if deterministic checks show room under 1024 words or identify redundant passages to remove. Feed structured patches back to the same writer.

This is preferable to generic iterative self-critique, which often produces stylistic churn and may explain why more inference does not automatically help.

**Targets:** first pass—Implicit; second pass—Synthesis and arena quality.

**Cost:** up to two extra calls and revision turns/topic.

**Pilot:** 10 topics, preferably after A1.  
**Go:** Synthesis +0.15 or Implicit +0.15 and `overall` +0.133; reject if Citation Quality falls by >0.15.

### A5. Open-weight role specialization

**Evidence status:** directly motivated by the −0.200 role-decoupling observation, although the responsible role is unknown.

Keep qwen as main writer and run a fractional factorial:

1. all support roles qwen;
2. brief/scout GPT-OSS, reviewer qwen;
3. brief/scout qwen, reviewer GPT-OSS;
4. all support roles GPT-OSS.

If another candidate model becomes available, substitute it only after a small role benchmark. Short support calls should not encounter GPT-OSS’s 30-round main-loop failure mode.

**Targets:** Implicit if planning roles matter; Synthesis if reviewer matters.

**Cost:** nearly unchanged dollar cost; some latency.

**Pilot:** eight paired topics × four configurations.  
**Go:** a role swap must improve its expected axis by ≥0.15 and `overall` by ≥0.133 relative to all-qwen. If only the all-GPT-OSS condition works, test the interaction on 15 topics.

---

## 3. Retrieval and reranking proposals

### R1. Targeted Boolean retrieval, not another unrestricted engine set

**Evidence status:** system-specific hypothesis. The proprietary “wider engine” findings do not cover `ssr` or `lucene_bool`, and may not transfer to weaker query writers.

I would not replace hybrid globally. Test a controlled policy:

- Every obligation gets one normal `hybrid` query.
- Obligations containing names, quoted phrases, identifiers, dates, or two required concepts get one additional `lucene_bool` query.
- Use `ssr` only where absence is informative or exact co-occurrence is required.

Examples:

```text
lucene_bool:
+"named entity" +(mechanism OR pathway) -unrelated_term

ssr:
"named entity" AND ("specific phrase" OR (term1 NEAR/8 term2))
```

Add a deterministic query sanitizer:

- quote escaping;
- balanced parentheses;
- remove unsupported operators;
- cap required terms at three;
- if exact search is empty, relax one requirement and record the fallback.

Stage full text from the best unique documents; do not use snippets or positional truncation.

#### Why weaker models might benefit more

A strong model can recover from noisy broad retrieval through semantic inspection and curation. A weaker model may:

- commit near-matches;
- miss that a key entity is absent;
- be distracted by topically relevant but criterion-irrelevant passages.

High-precision results therefore may have greater marginal value for qwen. However, Boolean retrieval can amplify poor query formulation, so it should be tested after or alongside D3.

**Pilot arms:**

1. hybrid only;
2. hybrid + model-authored Boolean;
3. hybrid + obligation-template Boolean.

Run 10 topics with exact-entity or relationship-heavy narratives.

**Go:** strong-document Recall@20 or covered-obligation rate +10 points, followed by Implicit +0.15 or `overall` +0.133. Do not adopt from retrieval metrics alone.

### R2. Query compiler for exact retrieval

**Evidence status:** novel and conditional on D3.

If D3 shows qwen query-writing weakness, have an open-weight pre-flight role produce search intents, but render actual Boolean syntax mechanically.

Input intent:

```json
{
  "required": ["Entity A"],
  "any": ["mechanism", "pathway"],
  "phrases": ["exact phrase"],
  "excluded": ["Entity B"],
  "proximity": [["term1", "term2", 8]]
}
```

A deterministic compiler emits valid Lucene/GCL. This separates semantic planning from brittle syntax and makes empty results interpretable.

This is materially different from the rejected mandatory retrieval screener: it does not filter every result through a requirement gate and does not prevent broad hybrid discovery.

### R3. Open-weight neural reranking

**Evidence status:** externally supported, untested here.

Use an open-weight reranker conservatively because it materially shapes staged evidence. My recommendation is to treat the gray area as requiring open weights even though it only reorders documents.

Candidates include:

- **Qwen3-Reranker-4B or 8B:** approximately 4B/8B dense models, long-context/instruction-aware depending on checkpoint.
- **BAAI bge-reranker-v2-m3:** approximately 568M, multilingual cross-encoder, cheaper and easier to self-host.

Data flow:

1. retrieve top 20–30 unique hits from hybrid and targeted Boolean;
2. score `(request + obligation, candidate passage/document)`;
3. retain:
   - top two per high-priority obligation;
   - at least one hybrid result for diversity;
   - adjacency pages belonging to retained hits;
4. stage full text, not reranker excerpts.

Avoid one global query-document score; obligation-conditioned ranking is important for implicit coverage.

**Targets:** Implicit Criteria through better evidence coverage; Synthesis by reducing noisy context. Citation is monitored only as a guardrail.

**Pilot:** eight topics after D3.  
**Go:** obligation-level Recall@5 +10 points and either target axis +0.15. Reject if the number of unique supported obligations falls.

### R4. Retrieval behavior instrumentation

Before changing engines, log:

- queries/topic and queries/obligation;
- engine distribution;
- empty-result rate;
- duplicate-document rate;
- strong-answer document Recall@k;
- fraction of committed documents later cited;
- obligations with no committed evidence;
- average staged-to-committed and committed-to-cited conversion.

This is nearly free and should accompany every subsequent run. In particular:

- high retrieval recall + low committed-to-cited use implicates synthesis;
- low retrieval recall with good use of found evidence implicates queries/engines;
- many empty Boolean searches implicate query compilation, not corpus absence.

---

## 4. Model-selection and inference-scaling proposals

### 4.1 Other open-weight model candidates

I cannot verify the Bedrock catalog as of 2026-08-09 from here. The first operational step should therefore be an API/catalog discovery against your enabled regions and Bedrock Marketplace. The table distinguishes models I consider plausible from models I can confidently claim are in your account.

| Model | Approximate architecture | Context | Tool/function calling | Deployment confidence |
|---|---|---:|---|---|
| **Meta Llama 4 Maverick** | ~400B total MoE, ~17B active | ~1M | Supported through common hosted tool-call adapters/Bedrock Converse, but validate exact endpoint | **Medium-high for Bedrock family availability**, low for your account/region |
| **Meta Llama 4 Scout** | ~109B total MoE, ~17B active | up to ~10M advertised | Same caveat | Medium-high Bedrock; likely below Maverick in quality |
| **Qwen3-235B-A22B-Instruct-2507** | ~235B MoE, ~22B active | up to ~262K for the newer checkpoint | Native structured/function calling in major serving stacks | Low for native Bedrock; high via specialist hosted providers |
| **DeepSeek-V3/V3.1-class** | ~671B MoE, ~37B active | ~128K | Tool calling supported by several hosted APIs; endpoint behavior varies | Low for native Bedrock; medium-high via Fireworks/Together-style routes |
| **GLM-4.5-class** | ~355B MoE, ~32B active | ~128K | Strong native agent/function-calling orientation | Low for Bedrock; medium through other hosted routes |
| **Kimi K2 Instruct, non-thinking** | ~1T MoE, ~32B active | ~128K | Tool calling | Medium that a related endpoint may be accessible given your K2 Thinking access; exact availability unknown |

“Open-weight” here does not mean OSI-open-source licensing; Meta and several other families have custom licenses. Confirm the project’s licensing interpretation.

#### Most promising model probes

1. **Llama 4 Maverick**, if actually exposed through Bedrock with reliable tool calls.
2. **Qwen3-235B-A22B-Instruct**, through an equally practical managed endpoint if Bedrock lacks it.
3. **GLM-4.5-class**, because agent/tool behavior may matter more than benchmark knowledge here.
4. **Kimi K2 non-thinking**, because it may preserve K2 capability while avoiding the 40–60-round hangs observed with the thinking endpoint.

I would not prioritize DeepSeek-R1-style reasoning models unless the endpoint demonstrates reliable native tools and bounded reasoning. Your Kimi result is a warning that nominal reasoning capability can be offset by agent-loop reliability.

### 4.2 Role-decoupling

Run A5 before assuming qwen is best in every role. The natural comparison indicates supporting roles account for as much as 0.200 overall, which is larger than almost every structural lever in the proprietary sweep.

Also test role outputs directly:

- obligation recall against the blind proprietary plan;
- number of unique valid implicit obligations;
- reviewer patch acceptance rate;
- whether proposed fixes have supporting committed evidence.

A reviewer that identifies flaws but proposes unusable changes is not useful despite looking sophisticated.

### 4.3 Inference scaling

My ranking is:

1. **better base model**, if available;
2. **deliberately diversified claim union**;
3. **evidence-grounded synthesis planning/targeted revision**;
4. more generic rounds or same-configuration samples.

M1’s 0.40–1.07 effect range dominates the observed structural effects. Therefore model replacement has the highest expected value. The failed best-of-four shows that ordinary sampling is not an effective scaling law for this configuration.

I would not fund:

- blanket increases in qwen’s round cap, unless logs show termination due to insufficient retrieval;
- more same-config complete drafts;
- unrestricted repeated self-revision.

I would fund scaling only when it changes the computation performed:

- criterion-partitioned retrieval;
- claim-level union;
- coverage then synthesis revisions;
- cross-model open-weight role specialization.

---

## 5. Prioritized, budget-aware experiment portfolio

Costs below are approximate generation-plus-internal-judging costs. Infrastructure engineering time is not monetized. Hosted large-model bakeoffs may vary substantially.

| Rank | Experiment | Hypothesis | Primary target | Topics | Est. cost | Go/no-go |
|---:|---|---|---|---:|---:|---|
| 1 | **D1: crossed fixed-evidence replay** | Localizes retrieval versus writer ceiling | Implicit, Synthesis | 8 | $12–25 | Evidence or writer contrast ≥0.15 axis; replay control valid |
| 2 | **Alternative open-model bakeoff** | M1 remains the largest available lever | `overall`, both target axes, completion | 8/model, then 15 | $20–60 | ≥0.20 overall over qwen pilot, ≥95% completion; confirm on 15 |
| 3 | **D2/A5: obligation transplant + open role factorial** | Supporting roles cause a material part of −0.200 | Implicit; Synthesis for reviewer | 8–10 | $6–12 | Target axis +0.15 and overall +0.133 |
| 4 | **D3: query transplant and logging** | qwen formulates weaker searches | Retrieval coverage, then Implicit | 8 | $3–6 | Recall@20 +10 points or uncovered obligations −20% |
| 5 | **A1: synthesis compiler** | qwen can write better from an evidence-conditioned composition plan | Synthesis, arena | 15 paired | $7–12 | Synthesis +0.15 and overall +0.133 |
| 6 | **R1: hybrid + targeted Boolean retrieval** | Precise retrieval helps weaker curation more than proprietary models | Implicit | 10, then 15 | $6–10 | Retrieval +10 points and axis +0.15/overall +0.133 |
| 7 | **A3: criterion-partitioned claim union** | Deliberate diversity realizes part of oracle union headroom | Implicit, Synthesis, arena | 8, then 15 | $10–25 | Target axis +0.20 and overall +0.133 |
| 8 | **R3: obligation-conditioned reranker** | Noise reduction improves evidence use | Implicit, Synthesis | 8–10 | $5–12 | Recall@5 +10 points and target axis +0.15 |
| 9 | **A4: two-stage targeted revision** | Orthogonal revisions outperform generic critique | Implicit, Synthesis | 10 | $7–12 | Target axis +0.15 and overall +0.133 |
| 10 | **A2: deterministic obligation reconciliation** | qwen currently fails to operationalize scout output | Implicit | 10 | $3–6 | Implicit +0.15; no >0.067 overall loss |
| 11 | **Blanket extra rounds/same-config ensembles** | More undirected compute helps | Unclear | — | — | **Do not fund absent diagnostic evidence** |

### The first three experiments

I would run, in order:

1. **D1 fixed-evidence replay.**  
   This determines whether retrieval work or synthesis work deserves most of the remaining budget.

2. **Alternative open-model availability check and eight-topic bakeoff.**  
   Run this in parallel with D1 if an endpoint can be enabled quickly. M1 is too dominant to defer model search until after extensive harness work.

3. **D2/A5 combined obligation-plan and support-role factorial.**  
   It directly tests the observed −0.200 supporting-role signal while remaining fully open-weight in the deployable arms.

Together these should consume roughly **$40–80**, leaving enough budget for one substantial follow-up and independent confirmation.

### Proposals that should wait

- **R1/R2/R3 retrieval changes should wait for D1/D3.** If qwen writes poorly even from E-P and transplanted queries do not improve retrieval, they are low-value.
- **A1 and A4 should wait for D1’s writer contrast.** They become high priority if qwen remains weak on fixed strong evidence.
- **A3 criterion union should wait for D1 and D2**, because its branch allocation should reflect whether missing obligations, missing evidence, or prose compression dominates.
- **Generic inference scaling should not be funded** unless logs show a concrete round-cap or search-budget failure.

### Adoption standard

No change should be adopted from one positive 15-topic standalone result. For any pilot that passes:

1. rerun on the full 15-topic development set if the pilot was smaller;
2. confirm on an independent topic set;
3. require completion reliability of at least 95%, preferably 100%;
4. check that Citation Quality does not decline materially despite not being the target;
5. run a blind arena comparison against the current qwen default.

For synthesis-oriented changes, I would require both independent rubric confirmation and arena confirmation, because S6 demonstrates that standalone and pairwise preference can reverse. For retrieval-oriented changes, also retain the current full-text staging and adjacent-page augmentation unless a separately powered ablation overturns their existing evidence.

## Turn 2 -- cost critique and scope questions (my message)

Reviewed. Strong plan overall — the D1/D2/D3 decomposition is exactly the kind of falsifiable diagnostic I asked for, and A3's criterion-partitioned union is a real answer to the failed best-of-4 (deliberate diversity via role/retrieval-policy partition, not resampling). Before I fund anything, three things need resolving. This is a working-budget review with roughly $9.65 left for THIS conversation specifically (separate from the $150-200 project budget the request itself describes) — so be concrete and short, not another full essay.

**1. D1's $12-25 cost estimate looks too high, and I think you're double-paying for evidence we already have.**

Our qwen bake-off's real generation cost was $0.16/topic for a FULL agentic run (search + commit + write + review, ~15-30 rounds). A fixed-evidence replay has none of that — no search/commit tools, one write call from a frozen evidence package. That should cost qwen well under $0.05/topic, not a meaningful driver of D1's cost. The real cost driver in your estimate must be "fresh proprietary controls" — but we don't need fresh proprietary generation at all: `aus_agent_v2` and `brief_revise_agent` both already have complete `output.json`/`trajectory.json` artifacts on disk for these exact 15 topics (`data/outputs/aus_agent_v2/`, `data/outputs/brief_revise_agent/`, run-ids `aus-agent-v2-exp15-luna` and `br-model-main-sol-exp15-b1`), including committed document ids and the full evidence each pulled. E-P is a data-extraction task against files we already have, not a new API call. The only real spend in D1 should be: qwen(E-Q) and qwen(E-P) generation (near-free) plus internal judging (4 cells × 8 topics × ~$0.15/judge-call ≈ $4.80, using our own existing judge protocol). Give me a revised D1 cost with that assumption, and confirm whether replaying already-generated proprietary evidence (not calling a proprietary model fresh) is what you meant, or whether you specifically want a NEW proprietary(E-P)/proprietary(E-Q) generation cell as a diagnostic control that reused artifacts can't substitute for — and if so, why the existing artifacts aren't good enough for that specific comparison.

**2. Confirm the open-weight constraint's scope for anything in D1 that isn't the reused-artifact path.**

The original request said judging is out of scope for the open-weight rule but didn't explicitly rule on ad-hoc diagnostic proprietary calls that never ship. If you do think a fresh proprietary write-from-E-Q/E-P cell is worth its own spend beyond what reused artifacts give you, say so explicitly and I'll decide — but default to the reused-artifact path unless you can name what it specifically can't tell us.

**3. Given real uncertainty about which of your §4.1 candidate models (Llama 4, Qwen3-235B, DeepSeek-V3, GLM-4.5, Kimi non-thinking) are actually reachable on Bedrock under our account — versus D1 being nearly free once we use existing artifacts — should the model-catalog check (a boto3 `list_foundation_models` call, zero cost, no LLM spend) happen BEFORE any pilot dollars go to rank-2 in your portfolio, rather than in parallel with D1 as you proposed? I can run that catalog check myself for free right now. Does that change your "run D1 and the model search in parallel" recommendation, or do you still want them parallel for a different reason (e.g. lead time on getting a new model's access approved)?

Answer concisely — a revised cost line for D1, a yes/no on the reused-artifact question, and a yes/no plus one sentence on the catalog-check ordering is enough. Don't re-explain the parts of the plan that don't change.

### Sol's reply (in=10446 out=317, $0.0679, cumulative $0.4180)

### 1. Revised D1 cost

**Revised D1, 8 topics: approximately $5.00–$5.60 total.**

- Four judged cells × 8 topics × ~$0.15: **$4.80**
- 16 qwen replay generations—E-Q and E-P: likely **<$0.80 total**, probably substantially less
- E-Q/E-P extraction: **$0 API cost**

### 2. Reused proprietary artifacts

**Yes—default to reused artifacts.** I do **not** recommend fresh proprietary generation initially.

Existing proprietary outputs provide proprietary(E-P), while qwen replay supplies qwen(E-Q) and qwen(E-P). The only missing clean factorial cell is newly generated proprietary(E-Q). That cell would estimate whether the proprietary writer can rescue qwen’s evidence, but it is unnecessary for the primary question of whether qwen improves when given E-P. Fund it only if qwen(E-P) materially improves and you then need a cleaner evidence×writer interaction estimate.

Any such fresh proprietary call would be an **offline diagnostic, not submission-eligible**; judging remains exempt. Whether diagnostics are permitted is your policy choice, but the deployed generation pipeline must remain fully open-weight.

### 3. Catalog-check ordering

**Yes—run the free Bedrock catalog check before spending any pilot dollars on model search.** D1 can proceed independently; only run them “in parallel” operationally if model-access approval or endpoint wiring has lead time after the catalog results.

## Turn 3 -- real Bedrock catalog, checked myself for free, no LLM call (my message)

Ran the free catalog check myself (`boto3 bedrock.list_foundation_models`, both regions, just now) instead of waiting. Real result, not speculation. Filtered to non-Anthropic, text-output models, ON_DEMAND unless noted:

**us-east-1 and ap-southeast-2 both have**, beyond our current 3: `qwen.qwen3-235b-a22b-2507-v1:0` (ap-southeast-2 only, not listed in us-east-1), `qwen.qwen3-coder-480b-a35b-v1:0`, `qwen.qwen3-vl-235b-a22b`, `qwen.qwen3-32b-v1:0`, `deepseek.v3.2`, `deepseek.v3-v1:0`, `deepseek.r1-v1:0` (INFERENCE_PROFILE), `zai.glm-5`, `zai.glm-4.7`, `zai.glm-4.7-flash`, `moonshotai.kimi-k2.5` (a newer Kimi, distinct from our `kimi-k2-thinking`), `minimax.minimax-m2`/`m2.1`/`m2.5`, `mistral.mistral-large-3-675b-instruct`, `mistral.devstral-2-123b`, `google.gemma-3-27b-it`/`12b`/`4b`, `openai.gpt-oss-20b-1:0` (smaller sibling of our gpt-oss-120b), `openai.gpt-oss-safeguard-120b`.

**us-east-1 only, INFERENCE_PROFILE (needs a cross-region inference profile id, not the bare model id, to invoke — more setup than our current 3, but not blocked)**: `meta.llama4-maverick-17b-instruct-v1:0`, `meta.llama4-scout-17b-instruct-v1:0`.

So: your #1 pick (Llama 4 Maverick) is real and reachable, with the inference-profile caveat. Your #2 pick (Qwen3-235B-A22B) is real in ap-southeast-2 specifically. DeepSeek and GLM — which you were uncertain about and deprioritized — are BOTH directly ON_DEMAND, no inference-profile hassle, same simplicity as our current 3.

None of this required an LLM call or the model-access approval process you flagged as a possible lead-time risk — these are already enabled on the account today. That removes the deployability uncertainty that was the main reason your ranking put "better base model" above a guaranteed-cheap diagnostic like D1.

Given this real list (not the speculative one), and knowing our current ceiling is 1.200/3 on a ~80B model: what's your actual top-2 pick to bake off next, and does DeepSeek-v3.2 or GLM-5 change your view now that they're confirmed trivial to reach (no inference-profile setup, ON_DEMAND, same tool-calling path as our existing 3) versus your earlier "wouldn't prioritize DeepSeek-R1-style reasoning models" caveat — v3.2 is presumably not the R1 reasoning variant, but confirm if that distinction matters to your pick. One paragraph, not a full re-analysis.

### Sol's reply (in=1252 out=688, $0.0296, cumulative $0.4476)

My top two are **`qwen.qwen3-235b-a22b-2507-v1:0`** and **`zai.glm-5`**: Qwen is the lowest-risk scaling test against your current Qwen baseline (~22B versus ~3B active parameters), while GLM-5 is the strongest architecture-diverse, agent/tool-oriented candidate with frictionless ON_DEMAND access. **DeepSeek-v3.2 moves to a close third** and is materially more attractive now; it is a V-series general model, not the separate R1 reasoning endpoint, so my R1 reliability caveat does not automatically apply, although any optional thinking mode should initially be disabled for bounded tool behavior. I would run eight-topic bakeoffs for those top two alongside the ~$5 D1, then test DeepSeek-v3.2 if neither beats qwen by at least **+0.20 overall** with clean completion.


---

# 2026-08-09 (continued) -- Tier-2 build: sol + Opus review, three pilots, final verdict

Continuation of the same sol dialogue above (turns 4-7) plus a parallel
review with Claude Opus 4.8 (standing in for Claude Fable 5, which turned
out to be blocked by an RMIT AWS Organizations Service Control Policy --
confirmed via `boto3`/`aws` CLI, no permission to even read the policy,
not fixable from this account). Total additional review cost: sol
cumulative **$0.7902** (from $0.35 first turn), Opus's real cost unlogged
(a placeholder-rate bug in the throwaway driver script always printed
$0.00 -- cosmetic only, did not affect model behavior or content).

## Turn 4 (sol) -- re-rank Tier-2 given Tier-1 results

**Sent:**

Follow-up, same review. We ran the Tier-1 batch (your D1/D2 plus a model bake-off) for real. Results, then a request.

**Model bake-off, 6 more real Bedrock-catalog-confirmed open-weight models, same 15-topic protocol:**
- `zai.glm-5`: **1.467** (vs. 1.200 old qwen3-next-80b-a3b default) — winner, replicated on an independent 15-topic set at an even larger margin (1.333 vs. 0.867 there, Δ=+0.467). Adopted as the new main-writer default.
- `deepseek.v3.2`: 1.200 (tied old default; first attempt read 0.933 but that was an AWS-token-expiry artifact contaminating 3/15 topics, corrected).
- `qwen.qwen3-235b-a22b-2507` (bigger/newer Qwen): **0.867** — genuinely worse than the small model it should supersede, confirmed on clean data (same token-expiry contamination as deepseek hit 6/15 of its topics, also corrected).
- `moonshotai.kimi-k2.5`: 1.333.
- `us.meta.llama3-3-70b-instruct-v1:0`: excluded before a full run — smoke test showed 0 tool calls across 4 rounds under our harness's Bedrock Converse tool schema, never recovers.

**D1 (fixed-evidence replay) result:** qwen writing from `aus_agent_v2`'s own frozen committed evidence vs. its own live evidence: Synthesis axis +0.154 (clears your own +0.15 threshold — evidence-sensitive), Implicit Criteria axis +0.006 (nowhere close — NOT evidence-sensitive). Reading against your own predeclared framework: retrieval/curation is NOT materially responsible for the Implicit Criteria gap specifically; that gap needs an architecture answer, not a retrieval answer. Separately, even WITH `aus_agent_v2`'s own evidence, qwen's replay score (1.267) still trails `aus_agent_v2`'s own live score (2.267) by a full point — a real writer-capability ceiling independent of evidence quality.

**D2/A5 (role-decoupling) result — this one reverses something:** main=qwen throughout, ONE support role swapped to proprietary `gpt-5.6-luna` (diagnostic only). Scout=luna: 1.000 (-0.200 vs. all-qwen). Brief=luna: 1.067 (-0.133). Swapping in a STRONGER model for a support role made the system WORSE, not better. This directly contradicts the premise your A5/4.2 proposals were built on (that the earlier -0.200 mixed-pipeline gap reflected support-role capability specifically) — that earlier number came from comparing two DIFFERENT systems' architectures with only the main model held constant, not an isolated role swap. This is the first clean single-variable test, and it says the opposite: a support role needs to match the main writer's own "idiom," not just be individually stronger.

**Request:** Given these three findings — especially D1's evidence-not-Implicit-Criteria result and D2's role-decoupling reversal — re-rank your own Tier-2 proposals (A1-A5, R1-R4) from your first-turn plan. Specifically:
1. Does D1 change your priority between A1 (synthesis compiler) and A3 (criterion-partitioned union) as the first architecture bet, given Implicit Criteria specifically needs an architecture fix, not a retrieval one?
2. Does D2 kill A5 (role specialization) entirely, or is there a narrower version worth keeping (e.g. swapping in a STRONGER OPEN-WEIGHT model for one role, not a proprietary one — untested, different comparison than what D2 actually ran)?
3. One concrete recommendation: which ONE Tier-2 item should be built and measured next, given ~$180 of budget remains and the new glm-5 default replaces qwen as the base every Tier-2 experiment should now be run against?

Keep it tight — this is a re-ranking against new evidence, not a new plan from scratch.

**Sol's reply:**

### Re-ranking

1. **A3 — criterion-partitioned claim union**
2. **A1 — evidence-grounded synthesis compiler**
3. **A2 — deterministic obligation reconciliation**
4. **A4 — targeted coverage/synthesis revisions**
5. **R4 — instrumentation** (enable routinely; not really a funded experiment)
6. **R1 — targeted Boolean retrieval**
7. **R2 — exact-query compiler**
8. **R3 — neural reranking**
9. **A5 — cross-model role specialization**

### 1. A1 versus A3

**D1 moves A3 ahead of A1.** A1 remains well motivated for Synthesis, but the unchanged Implicit score under superior evidence says additional/better evidence alone will not recover implicit obligations. A3 can force those obligations into the candidate content through an independent implicit-criteria branch and budgeted union. Its value now comes primarily from **criterion-partitioned drafting and inclusion**, not extra retrieval.

### 2. Status of A5

**Kill A5 as a general “stronger specialist model” proposal.** D2 invalidates its motivating inference. A narrower open-weight swap is logically unruled-out, but there is currently no positive reason to fund it—especially now that GLM-5 is the strongest available model. Use **GLM-5 consistently in every A3 role** to preserve idiom compatibility. Revisit cross-model roles only if a specific GLM role failure is observed.

### 3. Next build

Build **A3 on GLM-5**, initially as an eight-topic paired pilot against the all-GLM default. Preserve deliberate criterion partitions, but emphasize three distinct content roles—explicit facts, implicit obligations/qualifications, and cross-source synthesis—followed by deterministic word-budgeted claim union and a GLM-5 final editor.

**Go threshold:** Implicit Criteria **+0.15** and `overall` **+0.133**, with Synthesis and Citation Quality non-decreasing. If it passes, run all 15 topics, then independent-set and arena confirmation.

## Turn 1 (Opus, fresh conversation, same full context as Gemini's original request plus the Tier-1 addendum)

**Opus's reply** (picked mechanism Y -- the synthesis compiler -- over
sol's mechanism X -- criterion-partitioned union -- specifically because
of D1's capability-ceiling finding):

Tight review. One meta-point first, because it reorders everything.

## The caveat that gates the whole plan

**D1 and the role-decoupling test were both run on qwen. The default is now glm-5, and the model swap bought +0.267 — larger than any structural lever §3 ever found post-model-fix.** So the two diagnostics you're using to prioritize Group A were measured on a model you've retired, and the bottleneck may have moved. Specifically, D1's "writer-capability ceiling" (replay 1.267 vs 2.267) was *qwen's* ceiling; glm-5 at 1.467 already clears qwen's with-good-evidence score. You do not yet know where glm-5's remaining ~0.8-point gap lands per-axis.

**Step 0, near-free, before funding any A-item:** pull the per-axis breakdown for the glm-5 runs you already generated in the bake-off (you reported holistic only). If those runs weren't axis-scored, re-judge the existing transcripts — that's judge cost only, no regeneration, ~$1–2. This tells you whether Implicit Criteria + Synthesis are still the two gaps under glm-5, or whether the stronger model already closed one of them. **Do not build A1/A3 against a bottleneck diagnosed on the old model.** This is the single highest-value thing on the list and it costs almost nothing.

## Q1 — Does D1 change the A1 vs A3 priority?

Yes, but toward **A3**, not A1, and for a reason D1 makes sharp:

D1 gives you two distinct findings: (i) Implicit Criteria is *not* evidence-sensitive (+0.006) → architectural/capability; (ii) even with perfect evidence there's a **flat writer-capability ceiling** (full point of residual gap). Finding (ii) is the one that should drive the build choice: it says fragmenting the synthesis act makes things worse, not better, when the writer is weak. **A1's deterministic claim-union directly violates this** — it replaces coherent prose generation with mechanical stitching of claim fragments, which threatens exactly the two axes you're trying to raise (Synthesis, Communication Quality). The oracle criterion-union number (0.8048) was oracle *and* was measured as content selection, not as prose you'd actually ship; a real deterministic union is not synthesis.

A3 keeps a single coherent writing pass (respecting the capability-ceiling finding) while forcing implicit-obligation enumeration and section structure into a validated blueprint *before* prose. That hits the architectural Implicit gap (obligations become an explicit, checkable field) and the organization side of Synthesis, without asking a weak model to also perform fragment-merging.

So: **A3 > A1 as first build.** A1 is the correct *follow-on* if A3 raises coverage but prose stays flat — that outcome would tell you the front-end needs the parallel-diversity partition A1 provides, and you'd then de-risk A1 by feeding its unioned claims into a *single* synthesis writer rather than deterministic stitching.

## Q2 — Does the role-decoupling reversal kill C1?

**Effectively yes — kill it, don't spend the narrow check.** Two independent reasons now converge:

1. The idiom-match interpretation cuts against C1, not around it. C1 (glm-5 scout under a cheaper main) is *still* a cross-model idiom mismatch. C1 differs from the failed test only in that the mismatched support model is open-weight — but the reversal's lesson was about idiom coherence, not licensing. Nothing in your evidence suggests open-weight-to-open-weight mismatch is exempt.

2. **The economics that motivated C1 collapsed.** Heterogeneous routing pays off only when the strong model is expensive and you use it sparingly. glm-5 is simultaneously your *best* and a *cheap* open-weight model. There is no cheaper-and-adequate main to sit under a glm-5 support role that would beat just running glm-5 in every role. The one role-routing configuration your evidence now supports is **glm-5 homogeneous across all roles** — which is just the new default.

Park C1 at zero priority. If you ever get a *stronger* open-weight model that's meaningfully more expensive than glm-5, revisit it then — not now.

## Q3 — The one item to build next

**Build A3 (evidence-grounded synthesis compiler), against glm-5, after Step 0 confirms the axes.** Rationale, tightly:

- It targets both remaining gap axes with one mechanism: obligations-per-section attacks the architectural Implicit gap; heading/word-budget structure attacks the organizational half of Synthesis (the half D1 showed *is* evidence-and-structure-sensitive, +0.154).
- It respects D1's capability-ceiling finding by *not* fragmenting the write pass — a blueprint is a lower-dimensional artifact than prose, so a weak model is likelier to get structure right than full text, and the final synthesis stays a single coherent turn.
- Cost is trivial: one extra tool-less call (blueprint) validated deterministically before the existing final turn — ~$0.03–0.05/topic, 15 topics ≈ $1. Budget is not your constraint; adoption-discipline is.
- Implementation reuses machinery you have: it's a second pre-flight-style structured call whose output is appended and *validated* (each section must carry ≥1 docid and map to a brief/scout obligation), plus the existing citation mapper. No new component types.

Cheap companion you can ship in the same PR at ~zero marginal cost: **A4** (deterministically union brief+scout into the structured checklist that A3 consumes) — it's plumbing A3 wants anyway, so fold it in rather than run it as a separate experiment.

**Guardrails (non-negotiable per §3's hybrid reversal):**
- Primary metric: Implicit Criteria and Synthesis axis means, *not* holistic overall — recall the scout moved Implicit by +0.123 while holistic stayed flat; judge A3 on the axes it targets.
- Adoption threshold: effect must exceed **~0.13 (2× the 0.067 noise floor)** on at least one target axis, **AND replicate on your second 15-topic set**, **AND** survive an arena check against the current best opponent before graduating. §3's `hybrid` case is the standing reason a single standalone win is not enough.
- Hold ~$100 of the $180 in reserve for opportunistic model swaps. D1's flat capability ceiling is the sobering signal here: it says the biggest confirmed lever remains M1 (glm-5's +0.267, replicated), and §3 says structural toggles land below noise 10/11 times post-model-fix. A3 is worth building, but don't bet the whole budget on architecture beating a better base model.

## Re-ranked Tier-2

| Rank | Item | Targets | New status given evidence | Gate / cost |
|---|---|---|---|---|
| 0 | **Step-0 axis re-check on glm-5** | confirm bottleneck under new default | *free-ish, run first* | judge-only re-score of existing runs, ~$2 |
| 1 | **A3 (+A4 folded in)** | Implicit (obligations), Synthesis (structure) | **build next** | ≥0.13 on a target axis + 2nd-set replication + arena; ~$1 |
| 2 | A5 (coverage/synthesis critic split) | Implicit, Synthesis | fund only if A3 under-delivers on coverage | ~$1–2 |
| 3 | A1 (parallel claim union, single-writer variant) | Implicit (dedicated branch) | follow-on to A3, de-risked (no deterministic stitching) | conditional on A3 result |
| 4 | B1 (query/retrieval instrumentation) | diagnostic | run anytime; near-zero cost, but D1 already demoted retrieval | log analysis only |
| 5 | A2 (delta two-draft union) | Synthesis | subsumed by A5/A1; skip | — |
| — | B2/B3/B4 | retrieval | **hold** — gated on B1 showing a retrieval problem D1 says isn't there | — |
| — | **C1** | role routing | **killed** — idiom-mismatch + glm-5-is-cheap-and-best | do not fund |

Bottom line: Step 0 (free) → A3+A4 (one build) → judge on the target axes with the 0.13/replication/arena gate. Everything else waits on those two results, and C1 is closed.

## Turn 5 (sol) -- resolving the X-vs-Y disagreement

**Sent:**

One more round -- a second independent reviewer (Claude Opus, standing in for Fable which turned out to be blocked by an org-level AWS policy) reviewed the same evidence and picked a DIFFERENT mechanism as the first build than you did. Worth resolving properly, not glossing over.

**First, a check you didn't have**: Opus flagged that D1 and the role-decoupling test were both run on qwen, not the new glm-5 default, and asked whether the diagnosed bottleneck still holds. I pulled glm-5's own per-axis bake-off numbers (already on disk, zero extra cost) against the proprietary baseline:

| Axis | glm-5 | qwen (old) | proprietary baseline | gap (baseline - glm-5) |
|---|---:|---:|---:|---:|
| Communication Quality | 0.633 | 0.633 | 0.733 | 0.100 |
| Explicit Criteria | 1.275 | 1.239 | 1.450 | 0.174 |
| **Implicit Criteria** | 0.765 | 0.694 | 0.988 | **0.224 (still largest)** |
| Instruction Following | 0.812 | 0.875 | 1.000 | 0.188 |
| Synthesis of Information | 0.667 | 0.590 | 0.795 | 0.128 (shrank the most, ~38% smaller than under qwen) |
| References & Citation Quality | 0.556 | 0.667 | 0.222 | -0.334 (still a glm-5/qwen strength) |

Implicit Criteria remains the single largest axis gap under glm-5 (shrank in absolute terms, 0.294->0.224, but stayed relatively largest); Synthesis shrank proportionally more just from the model swap alone. Your target-axis reasoning still holds under the new default.

**Now the actual disagreement.** Restating both proposals by MECHANISM, not label, since our two numbering schemes drifted apart:

- **Mechanism X (your pick, your own "A3")**: 3 parallel branches (explicit-facts / implicit-critical-reader / synthesis-relationships), each returns claims not prose, a deterministic union stage assembles the final report, a final editor pass smooths it.
- **Mechanism Y (Opus's pick, your own "A1")**: one pre-flight call produces a structured section-by-section blueprint (heading, word budget, obligations covered, claims+docids per section) validated deterministically, THEN the model writes the final report as ONE continuous coherent pass from that blueprint -- no fragment-stitching.

Opus's argument for Y over X, verbatim reasoning: "D1['s]... flat writer-capability ceiling... is the one that should drive the build choice: it says fragmenting the synthesis act makes things worse, not better, when the writer is weak. [Mechanism X]'s deterministic claim-union directly violates this -- it replaces coherent prose generation with mechanical stitching of claim fragments, which threatens exactly the two axes you're trying to raise (Synthesis, Communication Quality). The oracle criterion-union number (0.8048) was oracle AND was measured as content selection, not as prose you'd actually ship; a real deterministic union is not synthesis." Opus's proposed sequencing: build Y first; if Y raises obligation coverage but prose/organization stays flat, THEN build X as a follow-on, but even then feed the unioned claims into a single synthesis writer rather than deterministic stitching (a "de-risked" version of X).

Do you agree, disagree, or split the difference? If you still prefer X first, engage directly with the capability-ceiling argument -- why would deterministic stitching NOT compound a weak writer's existing coherence problems? If you're persuaded, say so plainly. One paragraph, not a re-derivation of your whole original case.

**Sol's reply (agrees with Y-first):**

**I agree with Y-first, though not entirely with Opus’s interpretation.** D1 does not show that fragmentation itself worsens synthesis, and my X already used deterministic union only to select/budget claims before a single final editor—not to ship mechanically stitched prose. Nevertheless, glm-5’s smaller Synthesis gap and still-dominant Implicit gap make Y the cleaner, lower-risk first intervention: force implicit obligations and evidence-backed claims into a validated blueprint, then preserve one coherent generation pass. Build Y first; if it improves Implicit by <0.15 or reveals that obligations are planned but still omitted, escalate to X’s partitioned claim generation while retaining the same single-pass synthesis writer.

**Consensus reached: build Y (evidence-grounded synthesis compiler) first.**

## Build: blueprint.py (`--synthesis-compiler`)

Implemented per the converged design. Two real implementation bugs caught
by testing before any pilot spend (`.format()` breaking on the JSON
schema example's literal braces; glm-5 collapsing each section into one
giant paragraph despite an explicit one-sentence-per-line rule, fixed
with a worked example built from the model's own claims -- see
`src/systems/oss_agent/blueprint.py`'s own module docstring and git
history for the full account).

**15-topic pilot result: a clean, decisive NEGATIVE** -- both target axes
moved the WRONG direction (Implicit Criteria -0.130, Synthesis -0.154),
plus a sharp Communication Quality (-0.266) and Citation Quality (-0.445)
collapse. Overall: 0.933 vs. 1.467 baseline (-0.534).

## Turn 6 (sol) and Turn 2 (Opus) -- reacting to the negative result

**Sent to both:**

Built and ran it. A3 (your term) / Mechanism Y (the evidence-grounded synthesis compiler you and Opus converged on) is a clean NEGATIVE result -- both target axes moved the WRONG way, not a null:

| Axis | glm-5 baseline | glm-5 + synthesis compiler | Δ |
|---|---:|---:|---:|
| overall | 1.467 | 0.933 | **-0.534** |
| Implicit Criteria | 0.765 | 0.635 | **-0.130** |
| Synthesis of Information | 0.667 | 0.513 | **-0.154** |
| Communication Quality | 0.633 | 0.367 | -0.266 |
| References & Citation Quality | 0.556 | 0.111 | -0.445 |

No implementation bug found (checked output format directly: normal sentence-level granularity, real per-sentence citations, valid structure). Two implementation issues WERE caught and fixed before this run: (1) the model initially collapsed each section into one giant paragraph despite an explicit "one sentence per line" rule -- fixed with a worked example built from the model's own claims, which did fix the granularity; (2) that fix didn't rescue the underlying result once actually measured.

My working hypothesis for why: the blueprint call is ANOTHER isolated, blind call by the same base model -- unlike the scout (which only appends a FEW extra checklist items on top of the model's own organic writing), this one REPLACES the model's entire approach to organizing the answer, discarding a first draft the model had already invested real synthesis effort into. The architect call has no access to whatever implicit judgment the main loop accumulated across its own search/commit turns; it's planning blind, and its plan turned out worse than what glm-5 would write on its own.

Question: given this real negative result on Mechanism Y, do you now prefer trying Mechanism X (criterion-partitioned union) as originally proposed, or is there a narrower fix to Y worth one more shot (e.g. give the architect call the model's own discarded first draft as additional context instead of writing blind, so it's revising structure rather than replacing judgment)? Or does this result change your view on Group A entirely -- is there reason to believe X would fail the same way, given both mechanisms share the "external call restructures the writer's own output" pattern that just failed here? One paragraph.

**Sol's reply** (proposes a narrower additive patcher, deprioritizes full
mechanism X too):

This negative makes me **deprioritize full Mechanism X as originally scoped**, because its union/editor stage shares the same dangerous property: replacing glm-5’s organically accumulated synthesis with externally imposed organization, potentially worsening coherence and citation provenance again. I would not retry Y merely by adding the draft; that approaches the generic review/revise pass already present. The only Group-A follow-up I would fund is an **additive, draft-aware implicit patcher**: after glm-5 drafts normally, give a same-model call the draft, committed evidence, and obligation list; permit at most 2–3 evidence-backed insertion patches for clearly missing implicit obligations, with exact docids, while forbidding global reordering or rewriting. The main-loop model applies those patches while preserving existing prose and citations. This retains the scout’s successful “small additive correction” pattern and directly tests whether external intervention fails because of wholesale replacement rather than because glm-5 cannot use auxiliary judgments at all; full X should wait unless that constrained patcher is positive.

**Opus's reply** (independently converges on the same "additive-only"
conclusion, names it as effectively sol's own A5 critic/editor pattern):

Don't build X — this result actively predicts it fails, and probably worse. The signature of Y's failure isn't in the two target axes; it's the collapse in Communication (−0.266) and Citation (−0.445), i.e. the blind external skeleton corrupted the *whole* generation, not just coverage. X shares Y's core pattern (an external step supplants the writer's own organic synthesis) but pushes it further: Y at least preserved one coherent writing pass over its imposed plan, whereas X replaces prose generation entirely with deterministic union of claim fragments — exactly the move D1's flat capability-ceiling finding warned against, and exactly the axes (Synthesis, Communication, Citation-provenance-across-merged-content) that just cratered. You'd be running the failed experiment with the fragmentation dial turned up. The real signal across all your evidence is now that the *only* pattern with positive support is **additive-on-top-of-the-model's-own-organic-output** (the scout adds a few checklist items; it never restructures), and everything that *replaces or reorganizes* accumulated judgment loses. So take your own narrower-fix instinct seriously — but note that "give the architect the model's discarded first draft so it revises rather than replaces" is no longer really Y; it's A5 (the coverage/synthesis critic-editor revision pass) operating on the writer's own draft. That's the one Group-A direction consistent with your evidence: keep glm-5's organic report as the primary artifact, then layer a light, targeted revision that flags missing implicit obligations and weak synthesis *without* rewriting structure from scratch. Build that next, not X, and gate it hard on Communication/Citation not regressing — those are your early-warning axes for this whole failure class.

**Second consensus: build an additive-only mechanism** (correction
layered on the model's own organic draft, never replacing/restructuring
it) -- the only pattern either reviewer now trusts, given both prior
mechanisms shared the "external step replaces the writer's own
judgment" failure signature.

## Build: `review_scout_obligations`

Widened `review.hook`'s own requirement list to also grade the blind
scout's additions (S1, S2, ...), reusing the mechanism completely
unmodified -- no new module, minimal implementation risk.

**15-topic pilot result: mixed, net negative.** Synthesis improved
(+0.205, clears the +0.13 gate) but Implicit Criteria -- the axis this
mechanism specifically targeted -- moved the WRONG way (-0.165), and
Citation Quality collapsed again (-0.334, the same recurring casualty as
the first attempt). Overall: 1.267 vs. 1.467 baseline (-0.200).

## Turn 7 (sol) and Turn 3 (Opus) -- final synthesis

**Sent to both:**

Built and ran your additive proposal (widen review.hook's own grading to include the scout's obligations, same FULL/PARTIAL/MISSING mechanism, nothing new). Real result, mixed but still net negative:

| Axis | glm-5 baseline | + review_scout_obligations | Δ |
|---|---:|---:|---:|
| overall | 1.467 | 1.267 | **-0.200** |
| Implicit Criteria | 0.765 | 0.600 | **-0.165 (target axis, wrong direction)** |
| Synthesis of Information | 0.667 | 0.872 | **+0.205 (target axis, clears the +0.13 gate)** |
| Communication Quality | 0.633 | 0.467 | -0.166 |
| References & Citation Quality | 0.556 | 0.222 | **-0.334** |
| Instruction Following | 0.812 | 0.562 | -0.250 |
| Explicit Criteria | 1.275 | 1.165 | -0.110 |

The pattern across BOTH of today's Tier-2 attempts, not just this one: Citation Quality is the recurring casualty (-0.445 for synthesis_compiler, -0.334 here) every time I add ANY extra post-hoc intervention on top of glm-5's organic first draft -- regardless of whether the intervention restructures everything (synthesis_compiler) or just widens what one existing, previously-safe mechanism grades (this one). Everything else drops too except Synthesis, which improved here specifically -- but Implicit Criteria, the axis this whole idea targeted, moved the WRONG way, which is hard to explain if the mechanism is doing what it's supposed to (grading scout obligations should only ever ADD coverage, never remove it).

My working read: any additional forced revision turn on glm-5 -- even a narrowly-scoped, additive-only PATCH -- seems to systematically degrade citation discipline across the WHOLE answer, not just the sentences being patched, even though review.hook's own feedback explicitly says "do not touch a FULL-graded sentence." Two independent interventions, two independent citation collapses, is now a real pattern, not noise.

Given this: do you now recommend shipping the PLAIN baseline (no synthesis_compiler, no review_scout_obligations, unmodified review.hook grading brief requirements only, exactly as it stood before today's Tier-2 work) as the final default, and treating "any post-hoc revision intervention hurts this model+harness combination" as a real, evidence-backed conclusion for this whole Group-A direction? Or is there one narrower diagnostic worth the last bit of budget before closing this out -- e.g. checking whether the plain BASELINE's own existing review pass (brief-only, always-on) is ALSO quietly costing citation quality relative to no review pass at all, which would mean the problem isn't specific to today's two additions but to the review-and-revise pattern itself? Keep it to one paragraph and a clear yes/no on shipping the plain baseline.

**Sol's reply:**

**Yes—ship the plain glm-5 baseline unless one final ablation beats it.** Treat the evidence-backed conclusion narrowly as “additional post-hoc revision pressure degrades this model+harness combination,” not yet “all revision is harmful,” because the always-on brief-only review has never been isolated. The one worthwhile final diagnostic is therefore **plain baseline versus no review/revision pass at all** on the same 15 topics. Adopt no-review only if Citation Quality improves by ≥0.15 while `overall` is non-inferior within 0.067—or if `overall` improves by ≥0.133 without a major target-axis loss; otherwise retain the exact pre-Tier-2 baseline and close Group A.

**Opus's reply** (catches the same gap independently: the "baseline" in
every comparison so far already includes the always-on review pass,
never itself ablated):

**Yes — ship the plain baseline as the default now**, but run exactly the diagnostic you named before closing the book, because it's cheap, decisive, and could turn a defensive ship into a strict improvement. Here's the confound that makes it worth the last dollars: the "plain baseline" is *not* the no-revision floor — it already carries the always-on S4 review/revise pass. So "any post-hoc revision hurts glm-5" is a hypothesis your two experiments are *consistent with* but have not actually tested, because both added revision *on top of* an existing revision pass you've never ablated on this model. The clean test is subtractive: run baseline-minus-review-pass (no S4 at all) on the 15-topic set and read Citation Quality first. If citation quality *rises* when you remove the always-on review, then the real conclusion isn't "today's two additions failed" — it's "the review-and-revise pattern itself is miscalibrated for the glm-5+Bedrock combination," today's two failures are just the tail of a longer curve, and you have a lever that is simultaneously cheaper (one fewer call per topic) *and* higher-scoring — the exact profile of the S6 win. If citation quality is flat or drops, then the current baseline's review pass is earning its keep, "revision hurts glm-5 *at the margin*" is the right framing, and you ship the plain baseline with genuine evidence-backed confidence rather than assumption. Either way you learn something adoptable, at ~$2–3. One hard caveat, given S6: if the subtractive result looks like a win, it is a standalone-only win until you replicate on the second topic set *and* run the arena check — that's the one pattern this project has already watched reverse.

**Both converge on one final diagnostic**: baseline minus the review pass
entirely (`--no-review`), to separate "today's two additions hurt
citation quality" from "the review-and-revise pattern itself is
miscalibrated for glm-5."

## Final diagnostic: `--no-review`

**15-topic pilot result: definitive.** Citation Quality does not rise
with no review at all -- it COLLAPSES to **0.000** (vs. 0.556 baseline),
the worst citation result of any variant tested this session. Implicit
Criteria and Explicit Criteria and Communication Quality are all
unchanged (review's brief-only grading apparently never touches them
either way); Instruction Following improves (+0.188); Synthesis and
overall both drop (-0.103, -0.200).

**This resolves the ambiguity completely, in the direction Opus's own
predeclared criteria named as "ship with confidence": the always-on
review pass is PROTECTING citation quality, not costing it.** Neither of
today's two additive Tier-2 attempts failed because "any revision hurts
glm-5" -- they failed for some other, still-unexplained reason specific
to widening what the pass does, while the pass's own existing narrow
scope (brief requirements only) is doing real, measurable, necessary
work.

## Final verdict

**Ship the plain baseline** (glm-5, `hybrid` engine, adjacent-page
augmentation on, blind scout on, unmodified `review.hook` grading brief
requirements only -- exactly the configuration this repo already had
before today's Tier-2 build). Standalone overall: **1.467/3**, unchanged
from before this exploration. `synthesis_compiler` and
`review_scout_obligations` are kept in the codebase, off by default, as
two real, decisive, well-documented negative results -- not deleted, per
this project's own convention of keeping validated negative findings
available rather than erasing the evidence they represent.

Total cost this Tier-2 round: sol consultation ~$0.79 (cumulative across
all 7 turns), Opus consultation cost not reliably logged (a driver-script
placeholder-rate bug, cosmetic only) but of the same order of magnitude
as sol's given comparable prompt/response sizes; three 15-topic
generation+judging pilots at the same per-pilot cost as every other cell
in this project (~$15-20 each, generation + 15 judge calls) --
approximately $50-60 for the full three-pilot Tier-2 round, well inside
the $40 consultation budget plus the $300 total project cap.
