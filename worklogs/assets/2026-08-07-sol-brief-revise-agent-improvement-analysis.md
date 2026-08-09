## Scope and evidentiary limits

The arena judge supplied no substantive explanation on any clean-loss topic: every verdict was only `[[A]]` or `[[B]]`. Accordingly, the root-cause analysis below derives the cause of each loss from the answer comparison, requirements brief, searches, and review status—not from unreported judge reasoning.

The raw export also omits actual ClimbMix document IDs and full retrieved text; it exposes only answer-local citation indices such as `[0]`. I therefore do not invent ClimbMix IDs or claim that a particular citation entails a sentence. References such as “BR sentence 8” below are pointers to the supplied run artifacts, not source citations.

# Part 1 — Root-cause analysis

## A. The 14 clean losses

### 1. `683a58c9a7e7fe4e7695846f` — Competition geometry

**Judge evidence.** Both orders selected `aus_agent`, with no reasoning beyond `[[A]]` and `[[B]]`.

**Material advantage for `aus_agent`.**

- It covers a wider problem-solving repertoire: spiral similarity, homothety, trigonometric methods, tool selection, and a beginner workflow. BR mostly gives a sequence of named theorems.
- AUS explains strategic recognition: “search for structure before calculating” and choose among “synthetic geometry, coordinates, trigonometry, vectors, and transformations.” That better addresses the requested contrast between classroom and contest reasoning.
- BR’s first worked example is mathematically wrong. It says that in cyclic quadrilateral \(ABCD\), “equal inscribed angles subtending arc AD give \(\angle ADC=\angle ABC=50^\circ\)” (BR sentence 8). Those angles subtend chord \(AC\) from opposite sides and are supplementary, not equal. The subsequent \(10^\circ\) conclusion therefore does not follow.
- BR is only 775 words versus AUS’s 1,001, despite the broad request. Its added Ptolemy, Power-of-a-Point, and Nine-Point-Circle examples did not compensate for the loss of strategic breadth.

**Brief/search diagnosis.** The brief was reasonable and explicitly asked for techniques plus application. The searches covered all the omitted areas, including “angle chasing auxiliary line,” “inversion,” and “mass points.” This is not a retrieval failure; it is an evidence-selection and correctness failure.

**Review diagnosis.** The review fired but missed a central invalid derivation. It also did not flag that the answer became a theorem catalogue rather than a fuller comparison of competitive problem-solving habits.

---

### 2. `683a58c9a7e7fe4e76958488` — Engrams plus predictive coding

**Judge evidence.** Only strict verdict tokens; both favor AUS.

**Material advantage for `aus_agent`.**

Both answers are strong, but AUS integrates the two mechanisms more tightly:

- AUS defines an explicit predictive-coding objective, \(E=\sum_l\pi_l\lVert e_l\rVert^2\), and a local learning rule in which prediction error directly changes synapses.
- BR’s main engram learning rule is ordinary Hebbian coactivity, \(\Delta w_{ij}=\eta\,pre_i\,post_j\) (BR sentence 9). Prediction error drives inference, but is not clearly part of engram learning. Its closing claim that predictive coding is the network’s “online inference-and-learning rule” is therefore less well established.
- AUS states a concrete experimental prediction: correct classification should reactivate a class-specific ensemble while prediction-error activity falls. BR instead spends space on implementation details such as event-driven spikes, a separate readout population, and a “rapid feedforward gist pathway.”
- BR is longer—717 versus 583 words—but the added machinery does not produce a clearer single mechanism. The separate category engram and class readout also make the classifier less conceptually economical.

**Brief/search diagnosis.** The brief correctly required one integrated network and local biological learning. Only four broad searches were made, but the retrieved material was enough for a good answer. The weakness lies in synthesis: BR assembled plausible components without proving that the same local error mechanism trains the engram.

**Review diagnosis.** The reviewer did not test mechanistic coherence: whether each claimed system role is actually implemented by the equations and connections described.

---

### 3. `683a58c9a7e7fe4e7695848b` — EHR NLP and CDC WONDER

**Judge evidence.** No reasoning beyond the two strict verdicts for AUS.

**Material advantage for `aus_agent`.**

- AUS is more pedagogically useful to the confused student. Its example note includes both “rheumatoid arthritis suspected” and “no history of lupus,” immediately motivating uncertainty and negation handling.
- It defines the actual extraction output as a patient-level variable with `unknown` and `conflicting` values, not just a set of detected strings.
- It gives a fuller validation and epidemiology plan: sensitivity, specificity, PPV, NPV, false-positive/false-negative inspection, healthcare-utilization confounding, missingness, site effects, and sensitivity analyses.
- BR gives a clearer preliminary CDC crosswalk and a numerical prevalence example, but it spends scarce space on generic preprocessing and GDPR even though the user’s setting and jurisdiction were not established.
- AUS is 178 words longer and uses that space on workflow and methodological caveats that directly help the user execute the project.

**Brief/search diagnosis.** The brief was excellent, and the 15 searches directly targeted categories, prevalence, NLP, validation, and privacy. The answer failed to carry several searched items—especially clinical-NLP evaluation and observational bias—into comparable detail.

**Review diagnosis.** The reviewer did not detect the gap between “a practical sequence” and a genuinely operational validation protocol. It also did not distinguish a useful realistic EHR example from a merely populated synthetic record.

---

### 4. `684397d188c1deceb49af31d` — Slavery in *Pseudolus*

**Judge evidence.** Only the strict verdict tokens, both for AUS.

**Material advantage for `aus_agent`.**

- AUS supplies more historically specific legal framing: the Lex Aquilia, peculium, manumission, freedman obligations, and the distinction between protecting the owner’s property interest and the slave’s autonomy.
- It offers richer close analysis of the plot: Harpax’s refusal, Pseudolus adapting after that failure, Simia’s role, the circulation of letters/clothing/money, and the ending in which drunken conviviality contains rather than abolishes the hierarchy.
- BR repeatedly relies on one source index—document `[0]` appears in most of its play-specific sentences. Without the document text, its precision cannot be verified, but this concentration is visibly less evidentially diverse than AUS’s use of separate play, legal, and historical materials.
- The brief explicitly required quoting or closely paraphrasing specific speeches. BR includes one quotation-like exchange in sentence 9 but otherwise compresses the primary-source analysis; AUS gives more scene-level evidence even without extensive direct quotation.

**Brief/search diagnosis.** Searches covered both the play and Roman legal status. The answer did not make full use of the legal searches and compressed 16 committed documents into a narrower 706-word argument.

**Review diagnosis.** The review missed the relative thinness of the historical framework and the brief’s own primary-source requirement.

---

### 5. `684397d188c1deceb49af325` — Baudelaire orphans

**Judge evidence.** Both verdicts favor AUS; no explanation.

**Material advantage for `aus_agent`.**

- AUS is more genuinely chronological. It introduces V.F.D. as the children encounter it at the hospital and carnival, then traces the headquarters, Sugar Bowl, submarine, Hotel Denouement, and island.
- BR postpones the explanation of V.F.D.’s origin and schism until sentence 22, after it has already reached the Grim Grotto. It then says the Sugar Bowl “becomes relevant by The Hostile Hospital” in sentence 24, after discussing later books. That violates the explicit chronological requirement.
- AUS includes important causal characters and events BR omits or compresses: Hector’s rescue of the Quagmires, Jacques Snicket’s death, the meaning of “Volunteer Fire Department,” Larry’s warning, the destroyed headquarters, Dewey’s accidental death, Ishmael, and the island’s V.F.D. participants.
- BR says Josephine “abandons and betrays” the children, which is an oversimplified description of her coerced disclosure, and ends with “Olaf is finally dispatched,” avoiding the requested complete outcome.
- Both answers are near the cap, so the issue is not simply running out of words. BR used 958 words but selected and ordered details less effectively.

**Brief/search diagnosis.** The brief correctly emphasized chronology and causal connection. Searches were extensive and specifically included Hector, Jacques, Kit, Dewey, the schism, and the Sugar Bowl. This is a clear searched-but-not-used failure.

**Review diagnosis.** The reviewer failed to perform a timeline-order check or compare the named-character inventory against the final answer.

---

### 6. `684397d188c1deceb49af32d` — Preschool aggression and sharing

**Judge evidence.** No reasoning; both orders choose AUS.

**Material advantage for `aus_agent`.**

Both answers are safe and actionable, but AUS is more behaviorally precise:

- It explicitly prioritizes “safe hands and safe body” over forced sharing and says refusal to share is not itself abnormal at age three or four.
- It identifies possible behavioral functions—obtaining the object, escaping a turn, gaining attention, or managing overload—rather than merely listing triggers.
- It gives stronger safeguards around physical intervention: only the least restrictive assistance allowed by service policy and training, and no unsafe restraint.
- It explicitly warns against forced apologies or forced sharing immediately after an incident.
- BR recommends a formal functional behavior assessment “now” (sentence 26). That may be appropriate given repeated injury, but AUS gives a more graduated team-review threshold tied to worsening behavior and observation results.
- BR’s “No ice cream for hitting or yelling” script is less neutral than AUS’s “ice cream is not available … hitting will not get it,” and could sound punitive rather than function-based.

**Brief/search diagnosis.** Brief and searches were well aligned. The difference is nuance and prioritization, not missing retrieval.

**Review diagnosis.** The reviewer did not compare the scripts for neutrality or check whether consequences were clearly contingent on replacement behavior rather than the end of a tantrum.

---

### 7. `6847465956a0f6376a6053ca` — Modified U-Net

**Judge evidence.** Both strict verdicts favor AUS.

**Material advantage for `aus_agent`.**

This is the clearest technical-quality failure:

- BR’s Python is not runnable. It uses `def init` and `super().init()` instead of `__init__`, contains `c=`, expressions such as `2c`, and malformed losses such as `2(py)` and `(1-p)(1-y)`.
- Sentences 20–21 are textually incomplete: distance targets are “normalizing each instance independently to.” and “requiring D targets in.”
- The prose claims “two compact self-attention blocks” in the bottleneck, but the code’s `self.mid` contains only convolutions and `Block` instances. The architecture described and architecture implemented do not match.
- AUS’s compact lambda-based code is also not production-quality and appears syntactically questionable, but its architecture, four heads, target construction, postprocessing, validation metrics, and center-assisted watershed are substantially more coherent.
- BR omits the center-heatmap head while still relying on distance maxima alone, making separation more vulnerable to noisy peaks.

**Brief/search diagnosis.** The searches were appropriate. This was not a corpus problem; it was a failure to validate generated code and to cross-check prose against code.

**Review diagnosis.** The review fired and missed syntax errors, incomplete sentences, and an architecture/code contradiction. Its issue schema had no explicit `INVALID_CODE` or `INTERNAL_CONTRADICTION` category.

---

### 8. `6847465956a0f6376a6053fb` — Social media’s overall impact

**Judge evidence.** No explanation; AUS selected twice.

**Material advantage for `aus_agent`.**

- AUS covers more socially consequential domains: politics, mental health, relationships, economy/work, information/public health, and activism. BR covers politics, combined mental health/relationships, education, and economics.
- AUS’s public-health section is especially weighty: COVID misinformation, vaccination misinformation, and the mismatch between rapid dissemination and accuracy. BR omits public health entirely.
- AUS uses Cambridge Analytica and cross-national democracy/trust data. BR instead spends several sentences on an Australian employment-law case, which is narrower and less central to society-wide impact.
- BR’s final judgment says political and mental-health harms carry the greatest weight, but its mental-health section calls the evidence mixed. AUS’s overall weighting is more coherent because it identifies information/public health as the clearest net-negative domain.
- BR is 200 words shorter despite a broad multi-domain assignment.

**Brief/search diagnosis.** The brief named public information as a possible major domain, but the search plan drifted into narrow queries such as the Australian Facebook dismissal case. The answer then omitted a major high-stakes domain found in AUS.

**Review diagnosis.** The reviewer did not ask whether the chosen domains adequately represented society or whether the conclusion’s weighting matched the domain-level findings.

---

### 9. `6847465956a0f6376a605404` — CS:GO feature essay

**Judge evidence.** Only strict verdicts; both prefer AUS.

**Material advantage for `aus_agent`.**

- AUS is a feature essay; BR reads like a compressed analytical summary.
- AUS explains historical inheritance from the 1999 Half-Life mod and prior Counter-Strike games. BR largely begins with contemporary player counts and game modes.
- AUS analyzes how maps, economy, utility, callouts, repeated practice, and the relationship between legibility and deep mastery sustain both play and spectatorship.
- It also explains esports as a “social mythology” of teams, rivalries, heroes, and comebacks, and Valve’s selective negotiation with community pressure.
- BR devotes a disproportionate share of its 480 words to skins, cases, paid openings, and Operations, leaving cultural history and game-design mechanics thin.
- The brief required an organized, engaging feature essay. BR is 326 words shorter than AUS and does not exploit the available budget.

**Brief/search diagnosis.** Searches covered history, mechanics, esports, updates, skins, and free-to-play. The output selected monetization and platform facts but omitted much of the cultural mechanism.

**Review diagnosis.** The review failed to flag both register mismatch and underdeveloped breadth.

---

### 10. `6847465956a0f6376a60542a` — Scaling a Twitter-like startup

**Judge evidence.** No explanation beyond both verdicts for AUS.

**Material advantage for `aus_agent`.**

Both designs are strong. AUS is more complete operationally:

- It includes shared-session handling, hot-object cache policy and TTLs, spam/bot/moderation controls, SLOs, incident-oriented alerting, and the measurements needed before converting “1M users/day” into capacity.
- It emphasizes cursor pagination, replica staleness, dead-letter handling, eventual-consistency policy, and why sharding should be delayed.
- BR is stronger on schema migration, dual reads/writes, validation, and rollback, but omits moderation and gives less explicit SLO/capacity planning.
- The user requested recommendations for “anything necessary”; for a global social product, abuse handling and measurable service objectives are material omissions.

**Brief/search diagnosis.** The brief covered operational safeguards but did not explicitly enumerate abuse prevention, SLOs, or workload estimation. Searches focused on infrastructure and feeds, so these omissions partly originate in under-decomposition.

**Review diagnosis.** The reviewer did not expand “operations” into the missing production disciplines or challenge the assumption that daily users alone is enough for sizing.

---

### 11. `6847465956a0f6376a60542d` — Politics of the *Mahabharata*

**Judge evidence.** Strict verdict only, twice for AUS.

**Material advantage for `aus_agent`.**

- AUS covers substantially more wartime consequences of prewar politics: Drona’s pressure to capture Yudhishthira, diversion of Arjuna, Abhimanyu’s death, Jayadratha, deception concerning Ashwatthama, Bhishma and Shikhandi, Karna, and Shalya’s conduct as charioteer.
- It gives concrete coalition lists, the Kauravas’ eleven divisions versus the Pandavas’ seven, Vidura’s resignation, Balarama’s neutrality, and the distinction between numerical alliance and genuine loyalty.
- BR ends after Karna and gives only two detailed wartime decision episodes. It therefore undercovers the explicit requirement to explain how political factors affected decisions during the war.
- BR sentence 16 associates Bhagadatta with Kamboja; Bhagadatta is normally linked to Pragjyotisha, making this at least a suspicious conflation.
- AUS is near the cap at 1,007 words; BR leaves roughly 190 words unused that could have covered the missing commanders and wartime choices.

**Brief/search diagnosis.** Searches specifically targeted Drona, Bhishma, Jayadratha, Abhimanyu, Shalya, and tactics. Much of that evidence was retrieved but omitted.

**Review diagnosis.** The reviewer failed to compare the answer’s actor list and war-decision list against R5 and R6.

---

### 12. `6847465956a0f6376a605492` — VLM replacing skin-lesion specialists

**Judge evidence.** No reasoning; AUS won both orders.

**Material advantage for `aus_agent`.**

- AUS tests replacement in two stages: a frozen benchmark followed, only if successful, by a prospective workflow trial comparing specialist-only, model-only, and model-plus-specialist conditions.
- It includes robustness tests, image-quality abstention, repeated prompt/order perturbations, inter-specialist disagreement, kappa, blinded failure analysis, explanations inconsistent with images, labeling time, unnecessary biopsies, missed malignancies, reliance, and cost.
- BR prematurely fixes a narrow three-class taxonomy and highly specific replacement thresholds: a two-point non-inferiority margin, false-negative rate ≤5%, ECE ≤0.05, and subgroup deficit ≤3%. No rationale is given for those numbers.
- Those exact thresholds create an appearance of rigor but are not tied to clinical severity, expected prevalence, sample size, regulator requirements, or specialist variability.
- BR never tests whether model-only operation is safe in a real workflow after the image-label benchmark.

**Brief/search diagnosis.** The brief correctly requested clinically meaningful metrics and a decision rule, but its “specific form” encouraged exact thresholds without requiring justification. Searches did not explicitly target prospective workflow replacement or clinically justified margins.

**Review diagnosis.** The reviewer failed to distinguish useful pre-specification from unsupported numerical precision.

---

### 13. `6847465956a0f6376a605493` — Markov chains

**Judge evidence.** Both verdicts favor AUS; no textual reason.

**Material advantage for `aus_agent`.**

- AUS gives a broader contemporary review: mixing times, random walks, approximate counting, statistical physics, MCMC, Markov decision processes, reinforcement learning, finance, economics, networks, and public health.
- BR’s review is narrower: MCMC, mixing, linear extensions, and quantum sampling. The quantum item is interesting but displaces broader contemporary applications.
- AUS more explicitly explains limitations of state selection and the Markov assumption, and it connects the heads example to transition-matrix calculations.
- Both derive the consecutive-head expectation correctly, but AUS better fulfills “literature review” breadth.
- BR is 188 words shorter despite the request for both history and contemporary research.

**Brief/search diagnosis.** Searches covered MDPs, applications, MCMC, mixing, and combinatorics. The final answer omitted several searched themes.

**Review diagnosis.** This run records `REVIEWER JSON PARSE FAILED (degraded to zero issues)`. That is direct evidence of a fail-open review path: the system knew review output was invalid but accepted it as if no issues existed.

---

### 14. `6847465956a0f6376a6054ad` — Two-agent mental-wellness MVP

**Judge evidence.** No explanation; both orders select AUS.

**Material advantage for `aus_agent`.**

- AUS opens with the essential scope boundary: supportive wellness tool, not diagnosis or counselor replacement.
- It separates three-low-mood escalation from a single urgent disclosure that must immediately trigger a crisis pathway.
- It specifies the minimum counselor handoff data, allows users to review/edit/delete the summary before sharing, and acknowledges unavoidable backup-deletion delay.
- Its test plan is much stronger: labeled sarcasm/multilingual/transcription-error cases, clinician scoring, adversarial testing, state-machine tests, safety outcomes, adverse-event review, exit interviews, and explicit go/no-go criteria.
- It correctly says 20 users for two weeks can test usability, safety, and engagement, not clinical effectiveness.
- BR says data should be permanently deleted from “scheduled backups.” That is operationally overconfident; a deletion schedule and disclosed backup-retention delay is more realistic.
- BR is 245 words shorter and compresses safety validation disproportionately.

**Brief/search diagnosis.** Searches covered uncertainty, escalation, privacy, deletion, and pilot evaluation. The final answer omitted much of the safety-testing depth.

**Review diagnosis.** The reviewer did not treat safety evaluation, non-diagnostic scope, and deletion semantics as mandatory rather than optional refinements.

---

## B. Cross-topic dominant failure patterns

### Pattern 1: Broad answers were repeatedly compressed below the useful coverage level

This is the most frequent regression.

Affected clean losses include:

- Competition geometry: 775 versus 1,001 words.
- EHR project: 796 versus 974.
- *Pseudolus*: 706 versus 874.
- Preschool behavior: 796 versus 965.
- Social media: 737 versus 937.
- CS:GO: 480 versus 806.
- Scaling: 820 versus 926.
- *Mahabharata*: 832 versus 1,007.
- Skin-lesion VLM: 385 versus 500.
- Markov chains: 695 versus 883.
- Wellness agent: 640 versus 885.

The omitted material was usually substantive, not padding: strategic geometry methods, validation metrics, legal context, public health, game history, abuse controls, wartime decisions, prospective clinical testing, contemporary applications, and safety testing.

This is not evidence that “longer is always better.” The engram answer was longer and still lost. The repeated issue is **stopping before broad requirements have been covered with enough mechanism and evidence**.

### Pattern 2: Retrieved evidence and brief requirements were not reliably translated into the answer

The search logs often went directly after the missing content:

- The Baudelaire searches named Hector, Jacques, Dewey, Kit, the V.F.D. schism, and the Sugar Bowl, but the final chronology remained incomplete and out of order.
- The *Mahabharata* searches targeted Drona, Bhishma, Shalya, Abhimanyu, Jayadratha, and wartime strategy, but several were omitted or compressed.
- The CS:GO searches included history, maps, competitive gameplay, updates, and esports, but the answer overfocused on cosmetics.
- The social-media searches covered public information and mental health, but the final answer omitted public health and spent space on a narrow employment case.
- The EHR searches included precision/recall, case definitions, and prevalence limitations, but the answer did not develop validation as fully as AUS.
- The Markov searches covered MDPs and broad applications, which did not survive into the final literature review.

This falsifies a simple “the brief failed to decompose” explanation for many losses. The requirements and searches frequently existed; the failure occurred at evidence selection, answer planning, or revision.

### Pattern 3: The review had no effective correctness or artifact-validity check

Affected topics include:

- Competition geometry: invalid cyclic-quadrilateral derivation.
- U-Net: non-compiling code, incomplete text, and prose/code architecture mismatch.
- Engram/predictive coding: the claimed integrated learning mechanism is not implemented by the stated Hebbian rule.
- Skin-lesion VLM: unsupported exact clinical thresholds.
- Baudelaire: chronology disorder and questionable character/event characterization.
- *Mahabharata*: suspicious alliance/geography conflation.

The existing reviewer types—`MISSING_REQUIREMENT`, `SHALLOW`, `UNCITED_CLAIM`, and `WEAK_SENTENCE`—do not force checks for `FACTUAL_ERROR`, `INVALID_CODE`, `INTERNAL_CONTRADICTION`, `UNSUPPORTED_PRECISION`, or `TIMELINE_ERROR`.

### Pattern 4: Literal checklist specificity sometimes displaced higher-value analysis

Examples:

- Geometry adds a succession of named theorems and numerical examples, including the incorrect one, while dropping broader strategic comparison.
- The VLM plan invents precise replacement thresholds without clinical justification.
- Social media uses a specific Australian Facebook employment case but omits the larger public-health domain.
- CS:GO gives concrete marketplace and Operation facts but little historical-cultural analysis.
- The engram answer adds implementation machinery and a separate readout without making the central learning integration clearer.

The brief’s `specific_form` field rewards “a named mechanism or number,” but it does not distinguish **decision-relevant specificity** from merely concrete detail.

### Pattern 5: Format and audience fit were checked less effectively than content presence

Most visible in:

- CS:GO, where AUS is a feature essay and BR is a compact report.
- EHR, where AUS more directly teaches a confused novice what the project means.
- *Pseudolus*, where AUS better sustains literary-historical argument rather than satisfying elements serially.
- Baudelaire, where the required chronological narrative became a partly reordered inventory.

## C. What the review pass actually did—and did not prove

The citation result is real: uncited sentences fell from 26.0% to 5.3%. But the data do **not** support a causal claim that review improved or harmed any individual answer:

- Every clean loss says the review fired.
- The clean wins also generally say it fired.
- No pre-review draft, reviewer issue list, sentence diff, or accepted/rejected patch is supplied.
- Markov chains demonstrates a parse failure that silently became zero issues.

The best-supported refinement of the original story is:

> The review pass successfully optimized a mechanically visible property—whether sentence objects had citations—but did not reliably protect global coverage or semantic validity.

The two main things it could not fix in its current form were:

1. **Global editorial selection and coverage preservation:** deciding which searched evidence and requested dimensions must survive the 1,024-word budget.
2. **Correctness and internal consistency:** checking mathematics, code, chronology, mechanistic claims, and unjustified numbers.

There is also a third issue the original diagnosis did not anticipate: **the revision mechanism itself is unauditable and fail-open**. Without the original draft and reviewer issues, the current artifacts cannot show whether review repaired, deleted, or introduced content. The Markov JSON failure proves that at least one malformed review was treated as “nothing to fix.”

### The two topics whose uncited rate worsened

The raw sentence counts identify them:

- Southeast Asia strategy (`6847465956a0f6376a605391`): AUS had 2 uncited sentences; BR had 10. BR’s uncited material includes most of its invented launch targets, sequencing, risk ratings, and go/no-go gates. These are not benign wrappers; they are central recommendations under a rubric that explicitly requested data-driven execution.
- Alignment proof (`6847465956a0f6376a605440`): AUS had 0 uncited sentences; BR had 7. The uncited material consists largely of formal definitions and proof steps. Those may be original derivations rather than externally sourced factual claims, but under the track’s stated citation-recall rule they still score zero when uncited. They are also central to the requested proof, not disposable transitions.

Thus the prior “structurally benign synthesis sentences” characterization is only partly defensible for the proof topic and is not defensible for the Southeast Asia topic.

# Part 2 — Improvement plan

## Priority 1 — Replace free-form rewrite with a coverage-gated, non-destructive patch review

**Expected impact:** Very high  
**Implementation cost:** Low to medium  
**Build first if there is time for only one change.**

### Finding targeted

The dominant losses are searched-but-omitted content and post-review compression: Baudelaire, *Mahabharata*, CS:GO, social media, EHR, Markov chains, wellness, and geometry.

### What to build

1. Extend the reviewer schema from a maximum of six generic issues to a requirement matrix:

```json
{
  "requirements": [
    {
      "requirement_id": "R5",
      "status": "FULL|PARTIAL|MISSING|INCORRECT",
      "draft_sentence_ids": [12, 13],
      "missing_specifics": ["Drona command decision", "Bhishma removal"],
      "supporting_document_ids": ["actual_climbmix_id"],
      "recommended_action": "ADD|REPLACE|KEEP"
    }
  ],
  "global_issues": [],
  "revision_mode": "KEEP|PATCH|REWRITE"
}
```

2. Change the revision instruction from “revise the report” to:
   - preserve all sentences marked `KEEP`;
   - make the smallest patch that resolves `PARTIAL`, `MISSING`, or `INCORRECT`;
   - every addition over the word cap must name the sentence being cut;
   - do not remove a requirement’s only concrete example or mechanism.

3. Keep both candidate answers:
   - `draft_pre_review.json`
   - `draft_post_review.json`

4. If the reviewer output fails schema parsing, **do not degrade to zero issues**. Retry once with a repair prompt; if repair fails, accept the original draft and record `review_failed=true`.

5. Add a final deterministic guard:
   - no requirement may move from `FULL` before revision to `PARTIAL/MISSING` after revision;
   - if it does, revert to the original draft.

### How to know it worked

- Re-run the 14 clean-loss topics.
- Primary metric: clean wins/losses against AUS in both orders.
- Cheap diagnostics:
  - fraction of requirements rated `FULL`;
  - number of requirements regressing after review;
  - average pre/post word change;
  - percentage of revisions accepted versus reverted;
  - reviewer parse-failure rate.
- Keep uncited-sentence rate at or below the current 5.3%.

---

## Priority 2 — Add a pre-writing evidence-and-coverage checkpoint inside the main conversation

**Expected impact:** Very high  
**Implementation cost:** Medium  
**Build second if two changes are possible.**

### Finding targeted

The brief and searches frequently contained the right material, but the final answer omitted it. A terminal reviewer is too late to repair broad selection cheaply.

### What to build

Add a required `coverage_checkpoint` tool call before the model may emit the final answer:

```json
{
  "requirements": [
    {
      "requirement_id": "R4",
      "planned_answer_role": "section or argument",
      "specific_claims": [
        {
          "claim": "Jacques Snicket is captured and killed after trying to help",
          "document_ids": ["actual_climbmix_id"],
          "evidence_snippets": ["retrieved snippet"]
        }
      ],
      "coverage_status": "READY|NEEDS_SEARCH|NO_EVIDENCE"
    }
  ],
  "word_budget": {
    "reserved_by_requirement": {"R1": 120, "R2": 180},
    "planned_total": 930
  }
}
```

Control flow:

1. Research normally.
2. Call `coverage_checkpoint`.
3. If any explicit requirement is `NEEDS_SEARCH`, return to ClimbMix search.
4. If `NO_EVIDENCE`, require the answer to state the limitation instead of guessing.
5. Only permit final generation once every explicit requirement is `READY` or explicitly unavailable.

The ledger must use actual retrieved ClimbMix IDs, not answer-local indices.

### How to know it worked

- Compute “searched-but-unused requirement rate”: requirements with committed evidence but no linked final sentence.
- Target a reduction of at least 50% on the 14 losses.
- Track final-answer word use on broad narratives; under-length answers should fall unless the narrative asks for concision.
- Arena re-run should particularly improve Baudelaire, *Mahabharata*, CS:GO, social media, and Markov chains.

---

## Priority 3 — Add deterministic artifact validators and new reviewer issue types

**Expected impact:** High on technical and formal topics  
**Implementation cost:** Low

### Finding targeted

The U-Net answer contained obvious invalid Python and a prose/code mismatch; the geometry answer contained an invalid derivation. The current review vocabulary does not demand these checks.

### What to build

Add reviewer issue types:

- `FACTUAL_ERROR`
- `INTERNAL_CONTRADICTION`
- `INVALID_CODE`
- `INCOMPLETE_SENTENCE`
- `UNSUPPORTED_PRECISION`
- `TIMELINE_OR_ORDER_ERROR`
- `FORMAT_OR_AUDIENCE_MISMATCH`
- `CITATION_MISMATCH`

Add a local, non-retrieval `validate_artifacts` tool:

```json
{
  "language": "python",
  "code": "...",
  "checks": ["parse", "compile", "undefined_placeholders"]
}
```

For Python:

- normalize fenced code;
- run `ast.parse`;
- run `compile`;
- return line-numbered errors;
- optionally import in a restricted local sandbox when dependencies permit.

Also add deterministic checks for:

- unmatched or unfinished equations;
- sentences ending in “to.”, “in.”, or similar truncated fragments;
- prose claims of modules absent from code, using a reviewer comparison;
- exact numerical decision thresholds with no cited source or explicit rationale.

For mathematical examples, instruct the reviewer to recompute every displayed numerical result and verify the theorem’s conditions. This would have caught the cyclic-quadrilateral error.

### How to know it worked

- `compile_success_rate` for answers containing Python.
- Count of incomplete code/text fragments.
- Count of reviewer-detected prose/code mismatches.
- Manual spot-check on the geometry and U-Net topics.
- No increase in arena losses on nontechnical topics.

---

## Priority 4 — Change the stopping rule from “answer seems complete” to “coverage is complete”

**Expected impact:** Medium to high  
**Implementation cost:** Very low

### Finding targeted

Eleven clean losses were materially shorter than AUS, often by 150–325 words, while still omitting requested dimensions.

### What to build

Add to the existing main system prompt without replacing its tuned content:

- For broad, multi-part narratives, target 850–1,000 words unless all requirements are demonstrably covered earlier.
- Do not stop solely because every requirement was mentioned once.
- A requirement counts as complete only if it has:
  1. a concrete answer,
  2. an explanation or mechanism,
  3. evidence where externally verifiable,
  4. the requested comparison, implication, or example.
- Before finalizing, report internally:
  - unused word budget;
  - missing requirement mechanisms;
  - sections with only one sentence;
  - whether a major counterexample or limitation is absent.

This is not a generic instruction to “be longer.” Concise prompts, such as the skin-lesion technical report, can remain short if their experimental design is complete.

### How to know it worked

- Median unused word budget on broad narratives.
- Number of `PARTIAL` requirements per answer.
- Arena result on the eleven under-length clean losses.
- Ensure no increase in 1,024-word truncation failures.

---

## Priority 5 — Make the requirements brief prioritize, not just enumerate

**Expected impact:** Medium  
**Implementation cost:** Low

### Finding targeted

The current `specific_form` field sometimes encourages low-value concreteness: arbitrary clinical thresholds, narrow legal cases, or theorem catalogues.

### What to build

Extend each brief item with:

```json
{
  "priority": "MUST|SHOULD|OPTIONAL",
  "answer_function": "CORE_ARGUMENT|EVIDENCE|EXAMPLE|FORMAT|SAFETY",
  "minimum_depth": "MENTION|EXPLAIN|COMPARE|DERIVE",
  "risk_if_wrong": "LOW|MEDIUM|HIGH",
  "do_not_invent": ["thresholds", "exact categories", "clinical margins"]
}
```

Prompt changes:

- Limit implicit requirements to those that materially affect rubric success.
- Require the brief writer to identify the three highest-value dimensions.
- For numbers, named entities, or taxonomies, state whether exactness requires retrieval verification.
- Do not suggest example numbers merely to satisfy specificity.

Examples:

- Skin-lesion VLM: “prespecify a clinically justified non-inferiority margin” rather than inventing 2%.
- Social media: prioritize a representative set of high-impact domains over a narrow employment-law case.
- Geometry: prioritize valid worked technique demonstrations over maximizing theorem count.

### How to know it worked

- Rate of exact numerical claims lacking an evidence link or rationale.
- Reviewer count of `UNSUPPORTED_PRECISION`.
- Requirement coverage weighted by `MUST/SHOULD/OPTIONAL`, not raw item count.
- Arena performance on VLM, social media, geometry, and CS:GO.

---

## Priority 6 — Add sentence-level citation entailment review, not merely citation presence

**Expected impact:** Medium for official citation precision; lower for arena content  
**Implementation cost:** Medium

### Finding targeted

The existing deterministic scan solved citation presence but cannot tell whether the attached document supports the sentence. The Pseudolus answer’s heavy dependence on one citation index and the ungrounded execution targets in the Southeast Asia answer illustrate the risk.

### What to build

Show the reviewer, for every draft sentence:

- actual ClimbMix document ID;
- retrieved supporting snippet;
- sentence claim;
- whether the citation is intended as direct support, background, or example.

Require one of:

- `SUPPORTED`
- `PARTIALLY_SUPPORTED`
- `UNSUPPORTED`
- `CITATION_NOT_NEEDED_BUT_TRACK_RULE_REQUIRES_ONE`

Only permit replacement citations from documents actually retrieved in that run. If support is missing, the main agent must either:

1. search ClimbMix;
2. weaken the sentence;
3. remove the claim.

For formally derived sentences, such as the alignment proof, cite retrieved sources for the underlying theorem or formal concept where appropriate, while keeping the derivation explicitly identified as the answer’s own inference.

### How to know it worked

- Existing weighted citation-precision evaluator, if available.
- Otherwise, reviewer-supported sentence rate plus the deterministic uncited rate.
- Specifically recheck Southeast Asia and alignment: neither should regress on uncited sentences.

---

## Priority 7 — Log enough information to diagnose revision causally

**Expected impact:** Diagnostic, not immediate answer quality  
**Implementation cost:** Very low

### Finding targeted

The present artifacts show only final answers and that review “fired.” They do not show what the review changed, making causal analysis impossible.

### What to build

Persist:

- raw requirements-brief JSON;
- every search call with requirement IDs that motivated it;
- committed and rejected ClimbMix document IDs;
- evidence snippets used for commitment;
- pre-review draft;
- deterministic uncited list;
- raw reviewer output;
- parse/validation errors;
- normalized reviewer issues;
- post-review draft;
- sentence-level diff;
- added/removed citations;
- final acceptance or reversion decision;
- word counts before and after;
- per-requirement status before and after.

Do not treat malformed reviewer output as zero issues.

### How to know it worked

This is binary: a future topic report should make it possible to answer:

- Which issue caused each changed sentence?
- Which cited document supported the change?
- Did revision improve or regress each requirement?
- Was the reviewer parsed successfully?
- Was the original or revised candidate submitted?

---

## Recommended build order under the time constraint

### If there is time for only one change

Implement **Priority 1: coverage-gated, patch-only review with original-draft preservation and fail-closed parsing**. It directly addresses the most common loss pattern and prevents review from silently degrading a stronger draft.

### If there is time for two changes

Add **Priority 3: deterministic artifact validation**. It is cheap and would prevent catastrophic losses like the U-Net answer while also catching truncated text and unsupported exactness.

### If a third change fits

Add **Priority 2: the in-loop evidence-and-coverage checkpoint**. It is the strongest structural remedy for searched-but-unused evidence, but it requires somewhat more control-flow and schema work.

### Cut first if time is short

1. Defer full sentence-level citation entailment review; citation presence is already much improved.
2. Defer sophisticated automatic mathematical verification beyond recomputation prompts.
3. Do not add multiple generic revision rounds. The evidence does not show that another unconstrained rewrite would help; it may worsen compression and adds no protection against the observed failures.

## Success criterion for the next iteration

Use the preregistered arena rule already in the repo rather than replacing it:

- re-run the 30-topic arena in both orders;
- require at least 12 clean challenger wins and at most 8 clean AUS wins;
- keep uncited-sentence rate at or below 5.3%;
- additionally require zero accepted reviewer parse failures and zero non-compiling Python answers.

The central design shift should be from **“generate, find up to six issues, rewrite once”** to **“prove coverage before writing, validate high-risk artifacts, patch without regression, and retain the better candidate.”**