# Strand D — Ethical Dimensions of LSTM / Encoder–Decoder Language and Speech Technologies

**Research memo for a graduate "history of technology" seminar paper.**
Scope: bias from training data; access and the digital divide; misuse (surveillance, disinformation); and evaluation against formal ethical frameworks. The technologies in view are the LSTM/seq2seq era of language and speech systems — neural machine translation (NMT), word embeddings, end-to-end automatic speech recognition (ASR), and the large language models that grew out of this lineage. The ethical critiques below were largely formulated against precisely these systems and remain the canonical references in the literature.

A note on framing: the bias and harms literature distinguishes two kinds of harm throughout, drawn from Barocas, Crawford, and codified for NLP by Blodgett et al. (2020): **allocational harms** (a system withholds resources or opportunities — jobs, credit, accurate transcription — from a group) and **representational harms** (a system represents a group less favorably, demeans it, or reinforces a stereotype). Keep this distinction in mind; it is the connective tissue between the empirical findings (§1–§3) and the normative frameworks (§4).

---

## 1. Bias from Training Data in MT/NLP and ASR

### 1.1 Word-embedding bias — the geometric foundation

**Bolukbasi et al. (2016)** showed that word embeddings — the distributed vector representations that underpin neural language and translation systems — encode "female/male gender stereotypes to a disturbing extent." Crucially, they demonstrated that **gender bias is captured by a *direction* in the embedding space**: the vector arithmetic that famously yields `man − woman ≈ king − queen` also yields the analogy "man is to computer programmer as woman is to homemaker." They distinguished *direct* bias (e.g., *receptionist* sitting closer to *female*) from *indirect* bias, defined metrics for both, and proposed a "hard-debiasing" algorithm that neutralizes gender-neutral words along the gender direction while preserving legitimate associations (*queen*–*female*) [Bolukbasi et al. 2016]. The paper's significance for a history of technology is twofold: (i) it located bias not in a bug but in the *geometry* of the learned representation, and (ii) it established that the same machinery that makes embeddings useful (capturing semantic regularities) is what makes them biased — the bias and the utility are the same phenomenon.

**Caliskan, Bryson, and Narayanan (2017)**, published in *Science*, generalized this from anecdote to systematic measurement. They introduced the **Word-Embedding Association Test (WEAT)**, a statistical analogue of the psychological Implicit Association Test (IAT), and the Word-Embedding Factual Association Test (WEFAT). Applying WEAT to GloVe embeddings trained on a Common Crawl web corpus, they **replicated a spectrum of documented human biases**: morally neutral ones (flowers pleasant, insects unpleasant), and socially consequential ones (European-American names more associated with "pleasant" than African-American names; female names more associated with family, male names with career; female terms more associated with the arts, male terms with mathematics and science). WEFAT further showed embeddings tracked *veridical* statistics — the embedding's gender association for an occupation correlated (r ≈ 0.90 in their data) with the actual percentage of women in that occupation per U.S. labor statistics. Their conclusion is foundational and is quoted across the entire downstream literature: **"language itself contains recoverable and accurate imprints of our historic biases,"** so "mere exposure to everyday language can account for the biases we replicate here." For the historian, this is the empirical demonstration that data bias is not an artifact of a particular model but a property of the human language corpora these models are trained on [Caliskan et al. 2017].

### 1.2 Gender bias in machine translation

**Prates, Avelar, and Lamb (2019)** ran a large case study on **Google Translate**. Starting from a comprehensive list of occupations from the U.S. Bureau of Labor Statistics, they built sentences of the form "He/She is an [occupation]" in twelve **gender-neutral languages** (Hungarian, Finnish, Chinese, Yoruba, and others that do not mark pronominal gender), translated them *into English*, and counted the pronoun the system chose. Google Translate exhibited **"a strong tendency towards male defaults,"** especially in STEM fields, and — critically — produced male pronouns *far more often than even the real-world skew in female labor-force participation would predict*. That is, the system did not merely mirror an unbalanced world; it **amplified** the imbalance beyond the actual statistics. This is the concrete MT manifestation of the embedding bias documented in §1.1 [Prates et al. 2019].

**Stanovsky, Smith, and Zettlemoyer (2019)**, in their ACL 2019 paper, built the **first challenge set and automatic evaluation protocol for gender bias in MT (WinoMT)**. Drawing on coreference datasets (Winogender/WinoBias) that deliberately cast people into **non-stereotypical roles** — e.g., "The doctor asked the nurse to help *her* in the operation," where the doctor is unambiguously female — they tested eight target languages with grammatical gender and used morphological analysis to check whether the translation used the correct gendered inflection. **Four commercial systems (Google, Microsoft, Amazon, SYSTRAN) and two state-of-the-art academic models all showed significant gender bias**, frequently defaulting to the stereotypical gender and even **ignoring explicit feminine cues present in the source sentence**. WinoMT became the standard benchmark for the problem. The finding is a clean example of *representational harm* operationalized as a measurable error rate [Stanovsky et al. 2019].

### 1.3 Dialect / accent disparities in ASR

**Koenecke et al. (2020)**, in *PNAS*, measured racial disparity in end-to-end ASR. They tested five state-of-the-art commercial systems (**Amazon, Apple, Google, IBM, Microsoft**) on 19.8 hours of audio from structured interviews with 42 white and 73 Black speakers across five U.S. cities, matched on age and gender. **All five systems exhibited substantial racial disparities, with an average Word Error Rate (WER) of 0.35 for Black speakers versus 0.19 for white speakers** — nearly double. The gap persisted on *identical phrases* spoken by Black and white speakers, isolating the cause to the **acoustic models** (i.e., to under-representation of African American Vernacular English in training audio) rather than to vocabulary or content. They quantified the downstream harm starkly: assuming a transcript with WER > 0.5 is unusable, **23% of audio snippets from Black speakers were rendered unusable, versus 1.6% for white speakers**, and WER rose with dialect density (DDM). This is the paradigmatic *allocational harm* in speech technology: a Black speaker is materially less able to use dictation, captioning, voice assistants, or voice-driven services. The authors recommend training on more diverse data including AAVE [Koenecke et al. 2020]. (Earlier, smaller-scale precursors — Tatman 2017 on YouTube auto-captions — are cited within Koenecke as the seeds of this line.)

### 1.4 The critical / normative turn — Blodgett et al. (2020) and "Stochastic Parrots" (2021)

**Blodgett, Barocas, Daumé III, and Wallach (2020)**, "Language (Technology) is Power: A Critical Survey of 'Bias' in NLP" (ACL 2020), surveyed **146 papers** analyzing "bias" in NLP and found their **motivations "often vague, inconsistent, and lacking in normative reasoning,"** and their quantitative techniques "poorly matched" to those motivations and disconnected from relevant work outside NLP. Their core contribution for this memo is conceptual: analyzing "bias" is *inherently a normative act*, so researchers must state **what behaviors are harmful, in what way, to whom, and why**. They organize harms into **allocational** (unfair allocation of resources/opportunities — jobs, credit) and **representational** (stereotyping, denigration, under- or mis-representation, questioning of one group's identity), and they argue work should center the **lived experiences of affected communities** and "the power relations between technologists and such communities." This paper is the bridge to §4: it insists that empirical bias measurement is incomplete without an explicit ethical framework [Blodgett et al. 2020].

**Bender, Gebru, McMillan-Major, and Shmitchell (2021)**, "On the Dangers of Stochastic Parrots: Can Language Models Be Too Big? 🦜" (FAccT 2021, pp. 610–623), is the synthesizing critique of the scale-and-data regime that the LSTM/seq2seq era ushered in. It raises four interlocking concerns:
1. **Environmental and financial cost.** Training ever-larger models consumes large amounts of energy and compute, with carbon costs borne disproportionately by marginalized communities who least benefit from the technology. The paper recommends *weighing environmental and financial costs first*.
2. **Unfathomable, uncurated training data.** Web-scraped corpora are too large to document or audit; they over-represent hegemonic, English-language, younger, and wealthier viewpoints, and encode the biases of §1.1–§1.3. The "documentation debt" makes harms hard to diagnose or fix.
3. **A "stochastic parrot."** A language model is characterized as "a system for haphazardly stitching together sequences of linguistic forms … according to probabilistic information about how they combine, but without any reference to meaning." Coherence is in the eye of the human reader, not the model.
4. **Misdirected research effort and downstream harms**, including the potential for fluent synthetic text to fuel disinformation and to encode stereotypes at scale.

Their recommendations — invest in *dataset curation and documentation*, weigh costs before scaling, and center affected communities — are the data-ethics counterpart to Blodgett et al.'s conceptual program [Bender et al. 2021]. (The paper is historically notable as the proximate cause of Timnit Gebru's and Margaret Mitchell's departures from Google, making it a landmark in the institutional politics of AI ethics.)

---

## 2. Access and the Digital Divide

**Joshi, Santy, Budhiraja, Bali, and Choudhury (2020)**, "The State and Fate of Linguistic Diversity and Inclusion in the NLP World" (ACL 2020), quantified the language-coverage inequity. Of the **7,000+ languages spoken worldwide, only a tiny fraction are served by modern language technology.** They introduced a **taxonomy of six classes (0–5)** based on the availability of labeled and unlabeled data, ranging from "**The Left-Behinds**" (Class 0 — the vast majority of languages, with essentially no resources and little hope of progress under current paradigms) up to the "**Winners**" (Class 5 — English, and a handful of others such as Spanish, German, Japanese, French, Mandarin, which dominate NLP research and benchmarks). Their quantitative analysis of resources and of representation at NLP conferences over time shows the gap *widening*, and directly **challenges the "language-agnostic" self-image of modern models** — systems are only as universal as their data, and their data is overwhelmingly English-centric. The slogan of the paper — "so that no language is left behind" — names the access problem precisely [Joshi et al. 2020].

The structural argument that ties §2 to the rest of the memo:
- **Compute and capital concentration.** The scale regime critiqued by Bender et al. (2021) means that the ability to *build* state-of-the-art seq2seq/LLM systems is concentrated in a few well-resourced, mostly U.S.- and China-based actors. Who builds determines who benefits, and whose languages and dialects are represented (§1.3 ASR disparities are the same problem at the sub-language, dialect level).
- **English-centrism and the Global South.** Low-resource languages — predominantly languages of Africa, South and Southeast Asia, and Indigenous communities — are systematically under-served, reproducing existing global inequalities. The very framing of these as "low-resource" or "long-tail" has itself been critiqued as reproducing colonial logics that position these languages as inherently deficient rather than under-invested-in (a critique developed in the more recent literature building on Joshi et al.).
- **Allocational at civilizational scale.** When essential services (search, translation, government, health, education) are mediated by language technology that works well only for "Winner" languages, the digital divide becomes an allocational harm at the level of entire linguistic communities.

---

## 3. Misuse Risks

### 3.1 Surveillance — speech and translation technology as instruments of state monitoring

The same end-to-end ASR and NMT advances that power consumer assistants make **mass monitoring of voice communication** tractable for the first time. Voice, historically "ephemeral and unsearchable," becomes "scanned, catalogued and archived."

**(a) NSA / signals intelligence.** Reporting by *The Intercept* (Froomkin 2015), based on the Snowden archive, documented the NSA's long-standing and expanding use of **automated speech-to-text** to make spoken communications searchable — internally described in agency documents as building "Google for voice," whereby keyword search becomes possible over intercepted calls. The reporting notes the technology was openly funded for decades via DARPA programs (e.g., RATS — Robust Automatic Transcription of Speech) and IARPA's **Babel** program, whose explicit goal was speech recognition "rapidly applied to *any* human language … to provide effective search capability for analysts to efficiently process massive amounts of real-world recorded speech." Whistleblower Thomas Drake and Senator Ron Wyden are quoted on the civil-liberties stakes; the article emphasizes that *cheap, automated* transcription removes the resource constraint that historically limited mass surveillance [Froomkin / The Intercept 2015]. Voiceprint/speaker-recognition (a related biometric) was used by the NSA to confirm identities of high-value targets (per the Snowden documents, as later reported by Hvistendahl/WIRED 2020).

**(b) Uyghur and minority-language technology in China.** Multiple investigations document speech/translation technology embedded in the surveillance apparatus targeting Turkic Muslims in Xinjiang:
- **Human Rights Watch (2019)**, "China's Algorithms of Repression," *reverse-engineered the Integrated Joint Operations Platform (IJOP)* mobile app used by Xinjiang police, exposing the data-collection architecture of mass surveillance applied to ~13 million Turkic Muslims [HRW 2019].
- **WIRED reporting on iFlytek (Hvistendahl 2020)** details how China's dominant voice-computing firm (≈70% of the Chinese voice market, 700M+ users) developed speech recognition, transcription, dialect/translation tools — including a "**Dialect Protection Plan**" soliciting recordings of Uyghur and Tibetan — alongside government and public-security contracts. iFlytek built voice-pattern (voiceprint) databases; in 2016 police in **Kashgar** contracted an iFlytek subsidiary for **25 voiceprint terminals** to collect speech samples for biometric dossiers (alongside photos, fingerprints, DNA). Human Rights Watch's Maya Wang characterizes the dual benign/surveillance use as "precisely what makes them very problematic," because consumer data improves the surveillance models and vice versa. iFlytek was placed on the U.S. Commerce Department's **Entity List** in October 2019 [Hvistendahl / WIRED 2020; HRW reporting cited therein]. The Australian Strategic Policy Institute (ASPI 2019) independently mapped iFlytek and peer firms within China's surveillance-tech ecosystem.

The historical point: surveillance is not a property of the model but of the *deployment*. The very capabilities that make ASR/NMT a public good (accessibility, translation across the language barrier) are dual-use, and the §1.3 dialect-disparity problem inverts here — *being legible* to the system becomes the harm rather than being illegible.

### 3.2 Disinformation — lowering the cost of multilingual influence operations

Neural MT and neural text generation **lower the marginal cost** of producing fluent, multilingual, synthetic content, changing the economics of influence operations.

**Buchanan, Lohn, Musser, and Sedova (2021)**, "Truth, Lies, and Automation: How Language Models Could Change Disinformation" (Georgetown CSET), evaluated **GPT-3** across disinformation-relevant tasks (narrative reiteration, elaboration, manipulation, seeding, wedging, persuasion). Their central finding: such systems are well-suited to **scaling and partially automating the *content-generation* stage** of influence operations — producing varied, on-message, fluent text far faster than human trolls — though human–machine teaming (a human curating and steering the model) is more effective than full automation, and detection/attribution remain the system's weaknesses. They warn this could let operators **scale up and diversify** campaigns, including across languages, lowering the labor cost that has historically bounded such operations [Buchanan et al. 2021]. Neural MT compounds this: a single source narrative can be machine-translated into many target languages cheaply, removing the native-speaker bottleneck for cross-border influence operations. (Bender et al. 2021 anticipated this risk as a downstream harm of fluent-but-meaningless synthetic text; subsequent work, e.g., Goldstein et al. 2023 on generative-model influence operations, develops it further.)

---

## 4. Formal Ethical Frameworks

Below, each framework's relevant principles are summarized and mapped to the seq2seq/ASR harms in §1–§3. The recurring principle clusters are **transparency/explainability, accountability, fairness/non-discrimination, privacy, and human oversight** — and every framework below addresses all or most of them.

### 4.1 IEEE — *Ethically Aligned Design* and the IEEE 7000-series

**IEEE Ethically Aligned Design (EAD)** is the IEEE Global Initiative on Ethics of Autonomous and Intelligent Systems' foundational document. Its governing maxim: "Standards of **transparency, competence, accountability, and evidence of effectiveness** should govern the development of autonomous and intelligent systems." It prioritizes human well-being, requires transparency in decision-making, and the prevention of algorithmic bias. EAD seeded a family of concrete standards [IEEE EAD; IEEE 2018 overview]:

- **IEEE 7000-2021 — *Model Process for Addressing Ethical Concerns During System Design.*** A normative process standard (the first of its kind) built around **Value-Based Engineering (VbE)**: it gives engineers a "systematic, transparent, and traceable" method to **elicit stakeholder values and translate them into system requirements** early in the life cycle, broadening risk analysis beyond physical harm to "value harms." Application to seq2seq/ASR: VbE would require a translation or ASR team to surface and document values (e.g., fairness across dialects, gender-neutral handling) as *requirements* before training, rather than auditing for bias post hoc [IEEE 7000-2021; IEEE SA press release 2021].
- **IEEE 7001-2021 — Transparency of Autonomous Systems.** Sets measurable, stakeholder-specific transparency requirements (users, developers, regulators, investigators). Maps to the "documentation debt" critique of Bender et al. (2021) and to Blodgett et al.'s demand that systems' behavior and harms be made legible.
- **IEEE 7002 — Data Privacy Process.** A standard for data privacy/management with privacy impact assessment. Directly relevant to the surveillance harms of §3.1 and to the consent problems in voice-data collection.
- **IEEE P7003 — Algorithmic Bias Considerations.** Provides developers a framework to identify and mitigate "unjustified" or unintended bias in algorithmic systems — the standards counterpart to the WEAT/WinoMT/Koenecke empirical literature, intended as a "roadmap for fair AI development" [IEEE P7003; Koene et al. 2018].

### 4.2 EU — *Ethics Guidelines for Trustworthy AI* (High-Level Expert Group, 8 April 2019)

Trustworthy AI must be **(1) lawful, (2) ethical, and (3) robust**, resting on four foundational principles (respect for human autonomy, prevention of harm, fairness, explicability) and operationalized as **seven key requirements** [EC/HLEG 2019]:
1. **Human agency and oversight** — human-in-the-loop / on-the-loop / in-command.
2. **Technical robustness and safety** — accuracy, reliability, reproducibility, fallback.
3. **Privacy and data governance** — data quality/integrity, legitimate access.
4. **Transparency** — traceability, explainability, and disclosure that one is interacting with AI, including its capabilities and limitations.
5. **Diversity, non-discrimination and fairness** — avoid unfair bias, ensure accessibility for all.
6. **Societal and environmental well-being** — sustainability and environmental impact.
7. **Accountability** — auditability and accessible redress.

Mapping: Requirement 5 directly indicts the §1 bias findings (MT gender bias, ASR dialect disparity); Requirement 6 names the environmental critique of Bender et al.; Requirement 3 governs §3.1 surveillance; Requirement 4 (transparency) governs synthetic-content disclosure in §3.2. The Guidelines were later operationalized as the **Assessment List for Trustworthy AI (ALTAI, 2020)** [EC/HLEG 2019].

### 4.3 OECD — *Recommendation of the Council on Artificial Intelligence* (adopted May 2019; updated 2024)

The first **intergovernmental standard** on AI (47 adherents). Five **values-based principles** [OECD 2019]:
1. **Inclusive growth, sustainable development and well-being.**
2. **Human rights and democratic values, including fairness and privacy.**
3. **Transparency and explainability.**
4. **Robustness, security and safety.**
5. **Accountability.**

Plus five recommendations to policymakers (R&D investment; inclusive AI-enabling ecosystem; interoperable governance; building human capacity / labor-market transition; international cooperation). Principle 1 directly engages the digital-divide concerns of §2 ("inclusive growth"); Principle 2 names *fairness and privacy* — covering §1 bias and §3.1 surveillance respectively [OECD 2019].

### 4.4 UNESCO — *Recommendation on the Ethics of Artificial Intelligence* (adopted November 2021)

The first **global standard-setting instrument** on AI ethics, adopted by all UNESCO member states (193/194). **Four core values:** (1) human rights and human dignity; (2) living in peaceful, just, interconnected societies; (3) ensuring diversity and inclusiveness; (4) environment and ecosystem flourishing. **Ten core principles** [UNESCO 2021]:
1. Proportionality and Do No Harm; 2. Safety and Security; 3. Right to Privacy and Data Protection; 4. Multi-stakeholder and Adaptive Governance & Collaboration; 5. Responsibility and Accountability (auditability/traceability); 6. Transparency and Explainability; 7. Human Oversight and Determination ("AI systems do not displace ultimate human responsibility"); 8. Sustainability; 9. Awareness & Literacy; 10. Fairness and Non-Discrimination.

UNESCO is distinctive in (i) anchoring everything in *human rights*, (ii) its explicit **gender** policy-action area and the *Women4Ethical AI* platform (responsive to §1.1–§1.2 gender bias), and (iii) eleven concrete **Policy Action Areas** plus a mandated **Ethical Impact Assessment** tool, moving beyond principles to implementation. Value 3 (diversity/inclusiveness) and Principle 10 map to §2's linguistic-diversity problem; Principle 3 to §3.1 surveillance [UNESCO 2021].

### 4.5 ACM — *Code of Ethics and Professional Conduct* (2018)

A professional code binding on computing practitioners. Its **General Ethical Principles (§1)** include: 1.1 contribute to society and human well-being, *acknowledging that all people are stakeholders*; **1.2 avoid harm**; 1.3 be honest and trustworthy; **1.4 be fair and take action not to discriminate**; 1.6 respect privacy; 1.7 honor confidentiality. Section 2 (Professional Responsibilities) includes 2.5, requiring **comprehensive and thorough evaluations of computer systems and their impacts, including analysis of possible risks**. Section 3 addresses leadership responsibilities. Principle 1.4's explicit anti-discrimination duty and 1.2's harm-avoidance duty place the bias findings of §1 within an individual practitioner's professional obligations; 2.5 mandates exactly the kind of impact/bias auditing that WinoMT and Koenecke et al. perform [ACM 2018]. *(Note: the ACM page was bot-blocked during retrieval; principle numbering/content above reflects the published 2018 Code, which should be verified against acm.org/code-of-ethics or the PDF at the source for the final paper.)*

### 4.6 NIST — *AI Risk Management Framework (AI RMF 1.0)* (January 2023)

A voluntary, sector-agnostic U.S. framework (NIST AI 100-1). It defines **seven characteristics of *trustworthy AI*** — valid and reliable; safe; secure and resilient; accountable and transparent; explainable and interpretable; privacy-enhanced; and **fair, with harmful bias managed** — and organizes risk management into **four core functions** [NIST 2023]:
- **GOVERN** — cultivate a risk-aware culture and policies (applies across all stages).
- **MAP** — establish context and identify risks (e.g., who is affected, including dialect/language groups).
- **MEASURE** — analyze, assess, benchmark, and monitor risks (the home of WEAT/WinoMT/WER-disparity metrics).
- **MANAGE** — prioritize and act on risks, allocating resources to treatment and response.

NIST also published a companion **Generative AI Profile (NIST AI 600-1, 2024)** addressing risks specific to systems like the seq2seq-descended LLMs, including disinformation/CBRN/synthetic content — directly relevant to §3.2. The "fair — with harmful bias managed" characteristic is the framework's hook for §1; "privacy-enhanced" for §3.1 [NIST 2023].

### 4.7 Synthesis — applying the frameworks to seq2seq/ASR

| Harm (this memo) | Empirical anchor | Principle(s) violated / engaged |
|---|---|---|
| Gender bias in MT | Stanovsky 2019; Prates 2019; Bolukbasi 2016; Caliskan 2017 | EU R5 *non-discrimination*; OECD P2 *fairness*; UNESCO P10; ACM 1.4; NIST *fair/bias-managed*; IEEE P7003 |
| Dialect/accent ASR disparity | Koenecke 2020 | EU R5; OECD P2; UNESCO P10; ACM 1.4/1.2; NIST MEASURE/*fair* |
| Scale, data, environment | Bender 2021; Blodgett 2020 | EU R6 *societal/environmental well-being* & R4 *transparency*; UNESCO P8 *sustainability*; IEEE 7001 *transparency* |
| Language coverage / digital divide | Joshi 2020 | EU R5 *accessibility*; OECD P1 *inclusive growth*; UNESCO Value 3 *diversity & inclusiveness* |
| Surveillance | The Intercept 2015; HRW 2019; WIRED/iFlytek 2020; ASPI 2019 | EU R3 *privacy & data governance*; OECD P2 *privacy*, *human rights*; UNESCO P3 *privacy*, P7 *human oversight*; IEEE 7002; NIST *privacy-enhanced*; ACM 1.6 |
| Disinformation | Buchanan et al. 2021 (CSET); Bender 2021 | EU R1 *human agency*; UNESCO P1 *do no harm*, P6 *transparency*; NIST GenAI Profile; ACM 1.2/1.3 |

The frameworks converge: bias is a **fairness/non-discrimination** problem; surveillance a **privacy + human-oversight** problem; disinformation a **transparency + harm-avoidance** problem; the digital divide an **inclusive-growth/diversity** problem. The empirical literature (§1–§3) supplies the *measurement*; the frameworks (§4) supply the *normative standard* against which the measurements are judged — exactly the gap Blodgett et al. (2020) said the field must close.

---

## Sources

*Source-type key: [Primary–peer-reviewed] = peer-reviewed paper; [Primary–framework] = official framework/standard document; [Primary–reporting] = original investigative journalism / NGO investigation; [Secondary] = summary/secondary source.*

1. Bolukbasi, T., Chang, K.-W., Zou, J. Y., Saligrama, V., & Kalai, A. T. (2016). **Man is to Computer Programmer as Woman is to Homemaker? Debiasing Word Embeddings.** *Advances in Neural Information Processing Systems (NeurIPS) 29*, 4349–4357. arXiv:1607.06520. — https://arxiv.org/abs/1607.06520 — **[Primary–peer-reviewed]**

2. Caliskan, A., Bryson, J. J., & Narayanan, A. (2017). **Semantics derived automatically from language corpora contain human-like biases.** *Science*, 356(6334), 183–186. DOI: 10.1126/science.aal4230. Preprint arXiv:1608.07187. — https://www.science.org/doi/10.1126/science.aal4230 — **[Primary–peer-reviewed]**

3. Prates, M. O. R., Avelar, P. H. C., & Lamb, L. C. (2019/2020). **Assessing Gender Bias in Machine Translation — A Case Study with Google Translate.** *Neural Computing and Applications*, 32, 6363–6381. DOI: 10.1007/s00521-019-04144-6. Preprint arXiv:1809.02208. — https://arxiv.org/abs/1809.02208 — **[Primary–peer-reviewed]**

4. Stanovsky, G., Smith, N. A., & Zettlemoyer, L. (2019). **Evaluating Gender Bias in Machine Translation.** *Proceedings of the 57th Annual Meeting of the ACL*, 1679–1684. ACL Anthology P19-1164. DOI: 10.18653/v1/P19-1164. arXiv:1906.00591. — https://aclanthology.org/P19-1164/ — **[Primary–peer-reviewed]**

5. Koenecke, A., Nam, A., Lake, E., Nudell, J., Quartey, M., Mengesha, Z., Toups, C., Rickford, J. R., Jurafsky, D., & Goel, S. (2020). **Racial disparities in automated speech recognition.** *Proceedings of the National Academy of Sciences (PNAS)*, 117(14), 7684–7689. DOI: 10.1073/pnas.1915768117. — https://www.pnas.org/doi/10.1073/pnas.1915768117 (abstract: https://pubmed.ncbi.nlm.nih.gov/32205437/) — **[Primary–peer-reviewed]**

6. Blodgett, S. L., Barocas, S., Daumé III, H., & Wallach, H. (2020). **Language (Technology) is Power: A Critical Survey of "Bias" in NLP.** *Proceedings of the 58th Annual Meeting of the ACL*, 5454–5476. arXiv:2005.14050. — https://aclanthology.org/2020.acl-main.485/ (preprint: https://arxiv.org/abs/2005.14050) — **[Primary–peer-reviewed]**

7. Bender, E. M., Gebru, T., McMillan-Major, A., & Shmitchell, S. (2021). **On the Dangers of Stochastic Parrots: Can Language Models Be Too Big? 🦜** *Proceedings of the 2021 ACM Conference on Fairness, Accountability, and Transparency (FAccT '21)*, 610–623. DOI: 10.1145/3442188.3445922. — https://dl.acm.org/doi/10.1145/3442188.3445922 (open PDF: https://dl.acm.org/doi/pdf/10.1145/3442188.3445922) — **[Primary–peer-reviewed]**

8. Joshi, P., Santy, S., Budhiraja, A., Bali, K., & Choudhury, M. (2020). **The State and Fate of Linguistic Diversity and Inclusion in the NLP World.** *Proceedings of the 58th Annual Meeting of the ACL*, 6282–6293. arXiv:2004.09095. — https://aclanthology.org/2020.acl-main.560/ (preprint: https://arxiv.org/abs/2004.09095) — **[Primary–peer-reviewed]**

9. Froomkin, D. (2015). **Speech Recognition is NSA's Best-Kept Open Secret.** *The Intercept*, 11 May 2015. — https://theintercept.com/2015/05/11/speech-recognition-nsa-best-kept-secret/ — **[Primary–reporting]**

10. Human Rights Watch (2019). **China's Algorithms of Repression: Reverse Engineering a Xinjiang Police Mass Surveillance App.** 1 May 2019. — https://www.hrw.org/report/2019/05/01/chinas-algorithms-repression/reverse-engineering-xinjiang-police-mass — **[Primary–reporting / NGO investigation]**

11. Hvistendahl, M. (2020). **How a Chinese AI Giant Made Chatting—and Surveillance—Easy** (iFlytek). *WIRED*, June 2020. — https://www.wired.com/story/iflytek-china-ai-giant-voice-chatting-surveillance/ — **[Primary–reporting]**

12. Australian Strategic Policy Institute (ASPI) — Hoffman, S., et al. (2019). **Mapping More of China's Tech Giants: AI and Surveillance.** ASPI ICPC, 28 Nov 2019. — https://www.aspi.org.au/report/mapping-more-chinas-tech-giants — **[Secondary / think-tank investigation]**

13. Buchanan, B., Lohn, A., Musser, M., & Sedova, K. (2021). **Truth, Lies, and Automation: How Language Models Could Change Disinformation.** Center for Security and Emerging Technology (CSET), Georgetown University, May 2021. DOI: 10.51593/2021CA003. — https://cset.georgetown.edu/publication/truth-lies-and-automation/ — **[Primary–framework/think-tank report]**

14. IEEE Global Initiative on Ethics of Autonomous and Intelligent Systems (2019). **Ethically Aligned Design: A Vision for Prioritizing Human Well-being with Autonomous and Intelligent Systems**, First Edition. IEEE. — https://standards.ieee.org/industry-connections/ec/autonomous-systems/ — **[Primary–framework]**

15. IEEE Standards Association (2021). **IEEE 7000-2021 — IEEE Standard Model Process for Addressing Ethical Concerns During System Design** (Value-Based Engineering). DOI: 10.1109/IEEESTD.2021.9536679. Press release: https://standards.ieee.org/news/ieee-7000/ ; standard: https://standards.ieee.org/ieee/7000/6781/ — **[Primary–framework/standard]**

16. IEEE Standards Association. **IEEE 7001-2021 (Transparency of Autonomous Systems); IEEE 7002-2022 (Data Privacy Process); IEEE P7003 (Algorithmic Bias Considerations).** — Overview: https://standards.ieee.org/initiatives/autonomous-intelligence-systems/standards/ ; P7003 description in Koene, A. et al. (2018), "IEEE P7003 Standard for Algorithmic Bias Considerations," *Proc. Intl. Workshop on Software Fairness*. — **[Primary–framework/standard]**

17. European Commission, High-Level Expert Group on AI (2019). **Ethics Guidelines for Trustworthy AI** (8 April 2019); and **Assessment List for Trustworthy AI (ALTAI)** (2020). — https://digital-strategy.ec.europa.eu/en/library/ethics-guidelines-trustworthy-ai — **[Primary–framework]**

18. OECD (2019, updated 2024). **Recommendation of the Council on Artificial Intelligence** (OECD/LEGAL/0449); OECD AI Principles. — https://oecd.ai/en/ai-principles (legal instrument: https://legalinstruments.oecd.org/en/instruments/OECD-LEGAL-0449) — **[Primary–framework]**

19. UNESCO (2021). **Recommendation on the Ethics of Artificial Intelligence** (adopted 23 November 2021). UNESCO doc. SHS/BIO/REC-AIETHICS/2021. — https://www.unesco.org/en/artificial-intelligence/recommendation-ethics (full text: https://unesdoc.unesco.org/ark:/48223/pf0000381137) — **[Primary–framework]**

20. ACM (2018). **ACM Code of Ethics and Professional Conduct.** Association for Computing Machinery, adopted 22 June 2018. — https://www.acm.org/code-of-ethics — **[Primary–framework]** *(content retrieved from canonical published version; site was bot-blocked at fetch — verify §1.x/§2.5 numbering at source for final paper).*

21. NIST (2023). **Artificial Intelligence Risk Management Framework (AI RMF 1.0)**, NIST AI 100-1 (January 2023); and **Generative AI Profile**, NIST AI 600-1 (2024). DOI: 10.6028/NIST.AI.100-1. — https://www.nist.gov/itl/ai-risk-management-framework (PDF: https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.100-1.pdf) — **[Primary–framework]**

### Supporting / corroborating (not load-bearing)
22. Tatman, R. (2017). **Gender and Dialect Bias in YouTube's Automatic Captions.** *Proc. First ACL Workshop on Ethics in NLP*, 53–59. — https://aclanthology.org/W17-1606/ — **[Primary–peer-reviewed]** (cited as precursor within Koenecke et al. 2020).
23. Goldstein, J. A., et al. (incl. OpenAI/Stanford/Georgetown) (2023). **Generative Language Models and Automated Influence Operations: Emerging Threats and Potential Mitigations.** arXiv:2301.04246. — https://arxiv.org/abs/2301.04246 — **[Primary–report]** (extends Buchanan et al. 2021).

---

### Verification notes / caveats for the seminar paper
- **Stanovsky et al. arXiv ID:** the correct identifier is **arXiv:1906.00591** (ACL 2019, P19-1164). Search results occasionally surface unrelated IDs; verified directly against the arXiv abstract page and ACL Anthology.
- **Prates et al. year:** circulated as a 2018 preprint (arXiv:1809.02208); the peer-reviewed version appeared in *Neural Computing and Applications* in **2019/2020** — cite the journal version where possible. Authors confirmed: Marcelo O. R. Prates, Pedro H. C. Avelar, Luís C. Lamb.
- **Koenecke WER figures (0.35 Black vs 0.19 white; 23% vs 1.6% unusable)** verified directly against the PNAS abstract and figure captions.
- **Caliskan quotes** ("language itself contains recoverable and accurate imprints of our historic biases") verified against the arXiv v4 abstract; the *Science* version is paywalled but the open-access author PDF (faculty.washington.edu/aylin) corroborates WEAT/WEFAT.
- **Framework principle wording** (EU 7 requirements, OECD 5 principles, UNESCO 4 values + 10 principles, NIST 4 functions + 7 characteristics, IEEE 7000 VbE) quoted/paraphrased from the official EC, OECD, UNESCO, NIST, and IEEE-SA pages retrieved directly.
- **Could NOT verify at source:** (i) the **ACM Code of Ethics** page returned a bot-challenge — the principle numbering (1.2, 1.4, 1.6, 2.5) is from the canonical 2018 Code and is widely reproduced, but should be confirmed against acm.org for the final paper. (ii) **Bender et al. "Stochastic Parrots" exact page range (610–623)** and the specific "stochastic parrot" definition quote were taken from the open PDF (s10251.pcdn.co) and secondary recaps; the ACM DL landing page was Cloudflare-blocked — verify the verbatim quote against the open FAccT PDF. (iii) The **iFlytek Kashgar "25 voiceprint terminals (2016)"** and **NSA "Google for voice"** details come from single investigative sources (WIRED, The Intercept); they are well-corroborated by HRW/ASPI but are journalism, not peer-reviewed — flag as reporting in the paper.
