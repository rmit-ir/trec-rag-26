## Bottom line

I do **not** think a few-hour iteration on `brief_revise_agent` is likely to beat `aus_agent_v2` overall before tomorrow. `aus_agent_v2` has substantially more architecture, experimentation, and paid selection behind it, and the new 22–8 result is consistent with a real capability gap rather than one remaining prompt defect.

The best attainable iteration is to borrow **one separable idea: the atomic obligation scout**—not the typed terminal answer contract.

Specifically, replace the current small, bundled requirements brief with a larger but bounded inventory of **atomic, expert-completion checks with stable harness-owned IDs**. Keep the existing research loop and final-output format. Also repair the current reviewer’s incomplete-set validation, which presently does not actually guarantee that every requirement was graded.

This could plausibly recover some of the losses caused by short, merely compliant answers. It will not reproduce `aus_agent_v2`’s evidence contract, citation locality, dynamic obligation promotion, or deterministic terminal validation.

---

# 1. Which `aus_agent_v2` mechanism is actually transferable?

## Recommendation: borrow the atomic obligation scout

The most transferable mechanism is:

> Before research, turn the request into a set of small, independently satisfiable answer checks—including expert-domain checks that make the answer complete, not only obligations lexically implied by the prompt.

This is more valuable here than adding a typed `submit_answer` tool.

### Why the typed terminal contract is not cleanly separable

A terminal tool by itself would only change the serialization of the same answer. The benefits described in the README come from the surrounding contract:

- atomic stable obligation IDs;
- searches tagged to obligations;
- commits mapped to obligations;
- extractive claims and source-local quotes;
- exact-term and numeric carry-through checks;
- replay of evidence before submission;
- typed answer items mapped to evidence and satisfied obligations;
- deterministic validation and bounded correction.

Without those components, `submit_answer(items=[...])` is mainly a formatting constraint. It would not make the short neuroscience answer discover model predictions, failure modes, replay, continual learning, or a concrete classification example. It would not make the wellness answer add a distinct crisis path or consent model. It would not make the CS:GO answer add free-to-play history, quantitative evidence, rival comparison, and monetization criticism.

Implementing the full terminal contract safely is not a few-hour change.

### Why “search tied to a requirement ID” is not enough alone

The iteration-1 logs already show highly requirement-shaped searching:

- the geometry run separately searched Ceva, Menelaus, nine-point circle, curriculum, and techniques;
- the EHR run separately searched CDC categories, EHR phenotyping, negation, prevalence, and skills;
- the VLM run separately searched reference standards, non-inferiority, calibration, OOD behavior, and specialist comparisons;
- the scaling run separately searched capacity, feeds, multi-region operation, and observability.

The failure is often not “the agent forgot to issue a query.” It is that the plan contains broad rows, and the final answer stops after satisfying their minimum interpretation. Merely attaching `R3` to the existing search call would improve auditability more than answer quality.

Requirement-tagged evidence becomes powerful only when the harness also blocks closure until every atomic requirement has adequate support. That starts to approach the larger v2 contract.

### Why atomic scouting fits the observed failures

The current brief has at most eight rows, and many rows bundle several distinct checks. Examples:

- VLM R6 bundles subgroups, OOD testing, false negatives, abstention, and human review.
- Scaling R7 bundles monitoring, logs, tracing, deployment, rollback, health checks, load testing, disaster recovery, and SLOs.
- Geometry R3 bundles angle chasing, auxiliary lines, inversion, homothety, and coordinates.
- The social-media evidence row asks for academic studies, journalism, and case studies in every major domain as one row.
- The Plautus history row combines property status, master authority, manumission, mobility, and social hierarchy.

A reviewer can mark such a row FULL after seeing some of it, even though several judge-relevant subchecks remain absent.

The current anti-hunch rule also suppresses useful expert obligations. An implicit requirement must overlap lexically with the narrative. That is safe against invented requirements, but it excludes precisely the domain-completion material that distinguishes many v2 answers:

- VLM: multicentre external validation, sample-size planning, prospective silent evaluation, decision-curve analysis.
- Wellness: imminent-crisis path distinct from “three low moods,” consent, counselor unavailability, validated instruments, feasibility-versus-efficacy distinction.
- Neuroscience: ablations, predictions, failure modes, replay and continual learning, uncertainty/abstention.
- Scaling: idempotency, outbox processing, backpressure, hot-key behavior, consistency policy, restore drills.
- Plautus: gendered commodification, `fides`, freedman obligations, peculium, metatheatrical limits.
- CS:GO: free-to-play transition, rivals, player statistics, skin gambling, third-party competitive infrastructure.

Those are not arbitrary embellishments. They are the kinds of checks an expert reader expects from the requested genre.

---

# 2. What iteration 1 appears to have accomplished

## It probably improved broad compliance and citation coverage

There is no same-code ablation in the supplied data, so the causal effect of the review cannot be measured directly. We also do not have the pre-review drafts or parsed grade rows. Therefore, it would be too strong to say the review caused particular improvements.

Nevertheless, the final artifacts show that its intended surface behavior is working:

- Nearly every `brief_revise_agent` answer has zero uncited prose sentences.
- The explicit broad requirements are usually present.
- Requested formulas, categories, workflows, comparisons, and named entities generally survive into the answer.
- The three clean wins are on topics where systematic carry-through matters:
  - a long chronological Baudelaire account;
  - a code-bearing U-Net design with losses, postprocessing, and comparisons;
  - a many-actor political account of the Mahabharata.
- The two ambiguous topics also satisfy awkward format or procedural demands well:
  - separate retirement-investing blog posts;
  - a detailed preschool incident plan.

So iteration 1 appears to have reduced the old failure mode of researching an explicit requested component and then simply omitting it.

## But that is no longer the principal discriminator

`aus_agent_v2` frequently won despite having many uncited sentences:

- geometry: 19 uncited;
- social media: 15;
- scaling: 21;
- VLM: 19;
- wellness: 13.

That does not mean uncited factual claims are desirable in TREC RAG. It means the arena judge was more influenced by substantive completeness, domain judgment, examples, caveats, and explanatory usefulness than by sentence-level citation saturation.

The current agent often produced an answer that was defensibly complete against its brief but materially thinner than v2:

| Topic | brief_revise | v2 | Main missing depth |
|---|---:|---:|---|
| Neuroscience | 510w | 903w | concrete example, replay, predictions, ablations, failure modes, continual learning |
| VLM evaluation | 498w | 990w | multicentre/prospective design, sample size, workflow endpoints, decision analysis |
| Wellness agent | 614w | 1002w | distinct crisis pathway, consent, service availability, validated measures, pilot limitations |
| Markov chains | 728w | 909w | richer foundational distinctions and broader contemporary synthesis |
| CS:GO | 744w | 952w | lifecycle detail, quantitative evidence, rivals, free-to-play, criticism |
| EHR project | 887w | 1020w | clearer caveats about WONDER, prevalence versus mortality, more pedagogical planning |

This is not just “v2 writes longer.” It writes longer because it has more executable checks to close.

## The close-length losses show a second limitation

On geometry, Plautus, social media, and scaling, both answers were near the word cap. V2 still won by selecting more discriminative material:

- **Geometry:** actual worked mini-problems and strategic transitions, rather than a broad catalog of definitions.
- **Plautus:** more interpretive dimensions—gender, `fides`, varieties of enslaved agency, peculium/manumission, and metatheatrical limits.
- **Social media:** methodological caveats, scope, causal uncertainty, distributional weighting, and possible governance changes.
- **Scaling:** operational edge cases such as retry storms, hot keys, outbox semantics, strong/eventual consistency choices, and restore drills.

For these topics, merely forcing 900 words will not help; the agent is already full. It needs more atomic prioritization before writing.

---

# 3. A correctness gap in the current “every requirement” reviewer

The code does not currently enforce its stated all-requirements contract.

`_parse_review` accepts any well-formed object containing list-valued `requirements` and `issues`. In particular:

```json
{"requirements": [], "issues": []}
```

is explicitly treated as a successful parse, even when the brief contains requirements.

A response that grades only R1 and omits R2–R8 is also accepted. There is no check that:

- every `valid_id` appears exactly once;
- no ID is duplicated;
- the returned ID set equals the brief ID set.

Additionally, a PARTIAL or MISSING row only becomes actionable when `fix` is nonempty:

```python
gaps = [g for g in grades if g["status"] != "FULL" and g["fix"]]
```

Thus a valid row like:

```json
{"id":"R4","status":"MISSING","missing_specific":"X","fix":""}
```

can disappear from feedback.

The parser is fail-closed only for malformed top-level JSON shape, not for incomplete coverage grading.

This should be fixed in iteration 2 regardless of the larger experiment. It is a small correctness fix, not the main competitive idea.

---

# 4. Proposed iteration 2

## Name: atomic expert-completion brief

Replace the present bundled brief with an atomic inventory generated in the existing one-shot call. Do not add another paid stage.

### Output shape

For example:

```json
{
  "requirements": [
    {
      "kind": "REQUEST",
      "requirement": "Compare the model directly with human specialists",
      "answer_form": "Report model and individual-specialist performance on the same locked test cases",
      "search_query": "skin lesion AI blinded dermatologist head to head evaluation"
    },
    {
      "kind": "EXPERT_COMPLETION",
      "requirement": "Specify a prospective external validation stage",
      "answer_form": "Name a geographically or institutionally external cohort and a prospective silent-validation phase",
      "why_needed": "A retrospective benchmark cannot establish specialist substitution",
      "search_query": "prospective external validation medical AI diagnostic study"
    }
  ]
}
```

The harness, not the model, should assign IDs in accepted order:

```text
A01, A02, ... A14
```

That eliminates duplicate, missing, or invented model IDs.

### Limits

Use:

- 8–14 total atomic rows;
- at most 6 `EXPERT_COMPLETION` rows;
- no more than one independently gradable proposition per row;
- at most 2 format/style rows;
- every expert row must contain:
  - a concrete reason it is necessary;
  - a concrete answer form;
  - a targeted search query;
- no generic rows such as “be comprehensive,” “discuss limitations,” or “use evidence.”

A narrow request may return fewer rows.

### Atomicity examples

Reject or split:

> “Address subgroup testing, OOD behavior, false negatives, abstention, and human safeguards.”

Into:

- compare performance across prespecified demographic subgroups;
- test a geographically or institutionally external dataset;
- analyze clinically consequential false negatives;
- define an uncertainty/abstention rule;
- define which cases require human review.

Likewise, split “operational readiness” into SLOs, observability, deployment rollback, load testing, and disaster recovery only when each is genuinely material.

### Prompt instruction that matters most

The scout should be told:

> Do not merely paraphrase the request. Add the smallest set of domain-expert checks whose omission would make an otherwise compliant answer feel shallow, unsafe, methodologically incomplete, or historically ungrounded.

That is the main change from iteration 1.

## Preserve request authority

To control overreach:

- `REQUEST` rows come directly from the narrative.
- `EXPERT_COMPLETION` rows may add standard domain expectations but may not alter the user’s requested conclusion, audience, or format.
- Expert rows should be omitted if they would consume space without changing the answer’s usefulness.
- The report may explicitly mark an expert check unresolved when ClimbMix lacks support.

This is safer than the current lexical anti-hunch gate while still bounded.

## Review exact atomic closure

Change `_parse_review` so a review is valid only if:

```python
returned_ids == valid_ids
and len(grades) == len(valid_ids)
and len({g["id"] for g in grades}) == len(grades)
```

Any missing, duplicate, or unknown ID triggers the existing repair retry.

Also synthesize a fallback fix when a non-FULL row has no `fix`, rather than silently dropping it:

```text
Add the missing specific named by the reviewer, using committed evidence if available;
cut the least relevant non-required sentence to make room.
```

The reviewer should grade `EXPERT_COMPLETION` rows exactly like requested rows, but the feedback should identify their kind so the writer can prioritize explicit user obligations first.

## Loosen the patch rule slightly

“Never touch a sentence supporting a FULL requirement” is too rigid once there are 10–14 atomic rows and a 1,024-word cap. Several losses are already at approximately 1,000 words.

Replace it with:

> Do not delete or weaken any fact that is the sole support for a FULL row. You may compress, merge, or relocate FULL-supporting prose if the same fact and citation remain.

That preserves coverage while permitting a better allocation of the fixed word budget. The current literal no-touch rule can prevent useful restructuring.

## Do not add a typed terminal tool this iteration

Keep the required `ragrun`/`ali_deepresearch.answer_format` path unchanged. A terminal tool migration creates unnecessary integration risk without the evidence contract that makes it valuable.

## Do not build dynamic obligation promotion yet

The v2 ability to promote post-retrieval facts into new obligations is valuable, but it requires commit metadata and closure-state changes. Defer it unless the atomic scout pilot shows clear gains and more time becomes available.

---

# 5. Expected effect by topic

The best candidates for improvement are the underfilled design/report topics:

1. **Neuroscience model**
   - atomic rows for architecture, engram formation/reactivation, predictive inference, local learning, readout, worked example, replay, ablations, predictions, and failure modes.

2. **VLM specialist substitution**
   - atomic rows for task definition, reference standard, same-case head-to-head comparison, external split, prospective stage, primary endpoint, non-inferiority rule, sample size, calibration, subgroup/OOD analysis, abstention, and substitution decision.

3. **Wellness agent**
   - atomic rows for two-agent contract, confusion handling, three-low escalation, separate imminent-crisis path, counselor availability, consent, encryption, deletion propagation, pilot endpoints, and feasibility limitations.

4. **CS:GO**
   - atomic rows for core mechanics, lifecycle, esports, community creation, skins economy, free-to-play, quantitative endurance evidence, rivals, and criticisms.

5. **Markov chains**
   - atomic rows for genesis, foundational notation, statistical role, combinatorial role, mixing, MCMC, contemporary contrasting directions, and full consecutive-heads derivation.

It may also improve Plautus and scaling by forcing selection of additional analytical dimensions, but those answers are already at the cap, so gains depend on successful compression.

### Realistic forecast

I would expect:

- a meaningful quality improvement on some short answers;
- perhaps conversion of **one to three of the ten clean-loss topics** into ambiguous or winning outcomes;
- no credible expectation of reversing the full 22–8 battle result;
- continued losses where v2’s richer evidence handling or superior material selection is decisive.

That is worthwhile gap-closing, not a plausible path to outright parity.

---

# 6. How to spend the remaining budget

## Do not rerun all 15 topics

Use the already-generated v2 answers as fixed opponents. Generate only the iteration-2 fork.

### First: zero-cost artifact analysis

Before any provider calls, extract for every existing topic:

- pre-review draft, if retained in trajectory;
- reviewer raw JSON;
- parsed requirement grades;
- revision feedback;
- final revised answer;
- which sentences changed.

This establishes whether iteration 1 actually inserted missing content or mostly caused citation/wording patches. It also reveals how often the incomplete-grade parser defect occurred.

### Paid pilot: four likely-gain topics plus one regression topic

Generate iteration 2 on:

- neuroscience;
- VLM substitution;
- wellness agent;
- CS:GO;
- U-Net as a regression guard.

If budget permits a sixth, use Plautus or scaling to test whether the richer atomic inventory helps when the answer is already near the word cap.

### Judge against cached answers

For each generated answer:

1. Compare iteration 2 against cached iteration 1.
2. Compare iteration 2 against cached `aus_agent_v2`.
3. Use both battle orientations.
4. Ask for a short criterion-level rationale in addition to the preference if the judging harness supports it.

Predeclare a promotion rule such as:

- iteration 2 must beat iteration 1 on at least three of five topics;
- it must not lose the U-Net regression topic in both orientations;
- it must improve at least two v2 comparisons from clean loss to split or win;
- no malformed or missing final artifacts.

If it fails, stop. Do not spend the remaining money layering on a terminal schema.

## Submission strategy

If `aus_agent_v2` itself is eligible for the final submission, the rational submission choice remains its verified default unless a separately tested candidate clearly beats it. The current evidence does not support betting the submission on this fork.

For `brief_revise_agent`, the rational goal is now:

> demonstrate whether atomic expert-completion planning closes a measurable portion of the gap at low implementation cost.

That is the highest-value experiment available within the remaining time and budget. Trying to reproduce v2’s complete typed evidence contract by tomorrow would be high-risk, under-tested, and very unlikely to outperform the architecture that already had over $1,000 of experimentation behind it.