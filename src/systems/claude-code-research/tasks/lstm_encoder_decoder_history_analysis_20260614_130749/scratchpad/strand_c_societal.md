# Strand C — Societal Implications of LSTM- and Encoder-Decoder-Based Sequence Models

*Research memo for a graduate "history of technology" seminar paper. Scope: how recurrent/LSTM and encoder–decoder (seq2seq) sequence models made three classes of technology practical (machine translation, speech recognition, predictive/assisted text), and what that meant socially — across globalization, language access, accessibility, and labor. Every claim is cited inline; full citations with source-type labels are in the **Sources** list. Demonstrated effects are distinguished from speculative ones throughout.*

---

## 0. Framing: the technical inflection point (~2014–2017)

The societal effects below trace to a concentrated burst of architectural progress. The encoder–decoder / sequence-to-sequence framework (Sutskever, Vinyals & Le 2014; Cho et al. 2014), the addition of attention (Bahdanau et al. 2015), and LSTM acoustic models for speech all matured into *deployed* products in roughly 2014–2017. The clearest deployment marker is Google's switch of Google Translate from phrase-based statistical MT to Google Neural Machine Translation (GNMT) in **November 2016**, which Google says enabled "great improvements to the quality of translation for over 100 languages" [Source 1, industry]. Microsoft's "human parity" speech-recognition results (2016/2017) were built explicitly on "convolutional and LSTM neural networks" [Source 7, peer-reviewed]. Gmail Smart Reply (2016) and Smart Compose (2018/2019) were built on LSTM/seq2seq language models [Sources 11, 13, peer-reviewed]. This memo treats these deployments as the unit of social analysis.

A caveat for the seminar's "history of technology" framing: the Transformer (2017) and large language models later subsumed many of these systems, so the *durable* social changes (mainstreamed MT, practical dictation, predictive text as a default) outlived the specific LSTM/seq2seq implementations that first delivered them. Where a claim's quantitative evidence post-dates the pure-LSTM era, this is flagged.

---

## 1. Machine translation goes mainstream

### 1.1 Adoption scale and the quality jump (demonstrated)

- Google deployed GNMT in production in **November 2016**; by Google's own account it improved translation quality across **"over 100 languages"** and was its first end-to-end neural production system [Source 1, industry; Source 2, reference/encyclopedic]. Google later reported the multilingual NMT system (Johnson et al. 2017) enabled a *single* model to translate between many language pairs and even perform "zero-shot" translation between pairs never seen together in training [Source 3, peer-reviewed].
- An independent, causal measure of the *quality* jump comes from eBay's in-house neural-era MT ("eMT"). Brynjolfsson, Hui & Liu measured a "Human Acceptability Rate" (HAR) for eMT of **91.4%** versus **84.4%** for the prior Bing system on eBay search/title translation — characterizing the upgrade as a *moderate* quality improvement, not a wholesale jump [Source 4, peer-reviewed (working-paper version)].

### 1.2 Globalization / cross-border commerce (demonstrated, strong)

- The flagship causal result: introducing MT on eBay **increased exports on the platform by 10.9%** (headline figure in the published *Management Science* version) [Source 4a, peer-reviewed]. The NBER/SSRN working paper reports a larger effect for specific corridors — **17.5%–20.9%** for U.S. exports to Spanish-speaking Latin America — and a 10.9% baseline; the **10.9%** is the conservative, most-cited number [Source 4, peer-reviewed working paper]. The authors frame this as "causal evidence that language barriers significantly hinder trade and that AI has already begun to improve economic" outcomes [Source 4, peer-reviewed]. MIT News summarizes the effect as comparable in magnitude to reducing the distance between countries by ~25% or removing a tariff [Source 4b, journalism].
- *Reliability note:* This is a single (if rigorous, peer-reviewed and widely cited) natural experiment on one platform; the 10.9% figure should be treated as platform-specific, not a universal trade elasticity. **Flagged as load-bearing single study.**

### 1.3 Low-resource / "long-tail" languages and language access (mixed: demonstrated capability, contested coverage)

- Coverage expanded but remains highly skewed. The OECD notes that at time of writing MT systems existed for "around 100" languages — "only" a tiny fraction of the world's ~7,000 spoken languages [Source 5, report (OECD)]. Google's 2022 work added 24 languages via zero-resource/massively-multilingual methods, and in 2024 announced 110 more, explicitly targeting long-tail languages [Source 6, industry; Source 1, industry].
- "Long-tail" languages remain handicapped by sparse and often low-quality training data, which depresses MT quality precisely where access would matter most [Source 5, report; Source 9, report (CDT — low-resource data is "often… mistranslated or even nonsensical")].

### 1.4 Linguistic hegemony and language preservation (mostly speculative / debated)

- The concern that MT *homogenizes* language and entrenches dominant languages is argued in the scholarly/heritage literature: machine translation "may encourage the homogenisation of language, as speakers of minority languages may rely on translations into dominant" languages [Source 10, peer-reviewed/heritage journal]. This is a **theorized risk**, supported by argument rather than large-scale measured outcomes.
- The "digital language divide" framing — that languages without digital/MT support face "digital language extinction" while major-language speakers gain — is documented in policy and ACL venues [Source 8, report (Internet Policy Review); Source 8b, peer-reviewed (ACL TDLE 2024)].
- Countervailing (also partly speculative): AI/MT is argued to *aid* documentation and revitalization of endangered languages (Dartmouth/Historica), though demonstrated, at-scale revival outcomes are thin [Source 14, journalism/industry]. **Net: linguistic-hegemony claims are real concerns but largely not yet quantitatively demonstrated; flag as speculative.**

---

## 2. Speech recognition / ASR becomes practical

### 2.1 The "human parity" milestone (demonstrated as a benchmark result; contested as a real-world claim)

- Microsoft (Xiong et al.) reported a **5.9% word error rate (WER)** on the NIST 2000 Switchboard test set in October 2016 — matching their measured human transcriber error rate — explicitly crediting "convolutional and LSTM" acoustic models; CallHome WER was 11.3% [Source 7, peer-reviewed (arXiv 1610.05256 / IEEE TASLP 2017); Source 7b, industry (MS blog)]. In August 2017 they improved this to **5.1% WER** [Source 7c, industry].
- **Critical counterpoint (peer-reviewed):** Beaver (2022, *AI Magazine*) argues these "human parity" claims "do not appear to be the case in the real-world," because parity was demonstrated on a clean, narrow benchmark and degrades sharply on accents, dialects, noise, and spontaneous speech [Source 8c, peer-reviewed]. The seminar should treat "human parity 2016/2017" as a **benchmark milestone, not a claim of real-world equivalence.** Independent accuracy figures for consumer ASR sit around **85–95% in quiet conditions with clear speakers** [Source 20, journalism], far below parity in adverse conditions.

### 2.2 Mainstreaming: voice assistants, dictation, transcription (demonstrated scale)

- Voice assistants reached mass scale shortly after practical neural ASR: Juniper Research estimated **3.25 billion voice assistants in use by early 2019**, projected to ~8 billion [Source 16, industry/journalism (Voicebot citing Juniper)]. (Caveat: "in use" counts installed assistants across devices, not unique users.)
- Practical dictation/transcription products (Otter.ai, Rev, Google Docs voice typing, cloud Speech-to-Text APIs) became standard workplace tools in this period — see §4 (accessibility) and §5 (labor) for deployment-specific evidence.

### 2.3 Productivity vs surveillance-adjacent uses (demonstrated tool; risks partly speculative)

- *Productivity (demonstrated):* dictation and meeting transcription are now default features in major platforms; the accessibility evaluations in §4 also show genuine functional gains.
- *Surveillance-adjacent (documented risk, uneven evidence):* cheap, accurate ASR lowers the cost of mass voice monitoring. Regulators have already acted: a data-protection investigation cited "a lack of consent or other legal basis for using AI voice analytics" in customer service [Source 17, journalism/legal blog (Debevoise)]. Voice-assistant privacy reviews document false-wake recording and cloud storage of sensitive audio [Source 18, peer-reviewed survey]. These are demonstrated *capabilities and incidents*; claims of pervasive covert surveillance remain partly speculative.

---

## 3. Predictive text and smart composition

### 3.1 Deployments and adoption (demonstrated, with primary figures)

- **Smartphone keyboards:** SwiftKey shipped the "world's first" neural-network smartphone keyboard (Alpha Oct 2015; full release Sept 2016), re-architecting next-word prediction around neural language models [Source 21, journalism (TechCrunch / TheNextWeb)]. Google's gesture-typing work likewise applied an LSTM variant to keyboard decoding [Source 22, industry/peer-reviewed (Google Research)].
- **Gmail Smart Reply (Kannan et al. 2016):** the seq2seq system was "responsible for assisting with 10% of all mobile responses" in Inbox by Gmail at launch; Google later reported usage rose to ~12% of replies on mobile [Source 11, peer-reviewed (arXiv 1606.04870 / KDD 2016); Source 12, industry (Google blog)].
- **Gmail Smart Compose (Chen et al. 2019):** the production seq2seq/LSTM system "saves users over **one billion characters of typing** each week" [Source 13, peer-reviewed (arXiv 1906.00080 / KDD 2019)].

### 3.2 Implications for communication and writing behavior (mix of demonstrated + emerging)

- *Demonstrated:* these systems measurably change *what* people type — by construction, a billion characters/week of Smart Compose text is model-suggested rather than freely composed [Source 13, peer-reviewed].
- *Emerging / partly speculative:* HCI scholarship raises the "AI answering on our behalf" concern and estimates that ~10% of the ~300 billion daily emails include AI-generated smart replies [Source 11b, peer-reviewed (EUSSET) — note this is an *extrapolation* combining Kannan's 10% figure with email-volume estimates, **flag as derived, not directly measured**].
- *Language homogenization:* the worry that suggestion systems nudge writing toward a model's "average" register is plausible and partly supported by the AAC findings in §4 (users report the model imposing a voice not their own), but population-scale evidence of homogenized human writing from Smart Reply/Compose specifically is **not yet established — flag as speculative.**

---

## 4. Accessibility

### 4.1 Real-time captioning for Deaf / hard-of-hearing (demonstrated deployment + evaluation)

- **Google Live Transcribe** launched Feb 2019 as a free Android app using Google's neural ASR; it originated as a prototype for a deaf Google engineer (built with Gallaudet University researchers incl. Christian Vogler) and surpassed **one billion downloads** by 2023 [Source 23, industry (Google blog); Source 23b, report (Gallaudet)].
- **Evaluation literature (demonstrated, with caveats):** A classroom study found ASR captioning accuracy **greater than 90%** for a real-time conversation among 3 students using Ava and Microsoft Translator [Source 24, peer-reviewed/applied (EDAUD)]. RIT/Kafle & Huenerfauth developed captioning-specific evaluation metrics showing that *word-error rate alone understates usability harm*, because some errors are far more disruptive to comprehension than others [Source 25, peer-reviewed (ASSETS 2017)]. Deaf-community sources caution that automatic captions remain less accurate than human CART stenographers [Source 26, NGO (HLAA)].

### 4.2 Translation for migrants / refugees (demonstrated deployment; evaluation thin)

- Humanitarian platforms (Translators without Borders; **Tarjimly**, a 501(c)(3) founded 2017) use a mix of human volunteers and MT to provide real-time language access to refugees and aid workers, with corporate partners (e.g., Boeing) [Source 27, NGO/industry]. TWB has explicitly worked to bring "marginalized languages to the level of commercial languages" by seeding MT data [Source 27b, NGO]. *Demonstrated as deployment; rigorous outcome evaluations remain scarce — flag as under-evaluated.*

### 4.3 AAC and predictive communication aids (demonstrated, nuanced — strongest accessibility evidence)

- Neural word/sentence prediction shortens the path from intent to utterance for people who type to speak. A Google CHI 2023 study ("*The less I type, the better*") had **12 AAC users** test live language-model suggestions across scenarios; it found genuine speed/effort benefits **but also harms** — suggestions could impose wording that was "not their own voice," shift authorship, and impede authentic self-expression [Source 28, peer-reviewed (CHI 2023)]. Classic AAC work (Trnka et al.) established that word prediction can raise communication rate versus letter-by-letter entry, but with cognitive-overhead trade-offs [Source 29, peer-reviewed]. **This is the best-evidenced accessibility strand — demonstrated benefits and demonstrated trade-offs.**

---

## 5. Labor and jobs

### 5.1 Translation/interpreting profession (demonstrated: no large-scale displacement *yet*; rates pressure real)

- **Headline (authoritative report):** OECD's *Not Lost in Translation* (2023) finds that despite MT advances, **"no large-scale substitution effect occurred"** in the language-professional labor market; employment of interpreters and translators was projected to **grow ~20% (2021–2031), about 15 percentage points above the average** for all occupations (per US BLS) [Source 30, report (OECD, peer-reviewed-adjacent working paper)]. The OECD frames MT as so far a **complement** that shifts the skill mix (toward post-editing/AI skills) rather than a replacement [Source 30, report].
- **Counter-evidence on conditions and pay (journalism + labor surveys):** the *rates* picture is darker than headline employment. Machine-translation post-editing (MTPE) is typically priced well below human translation; practitioners and surveys report MTPE rates roughly **~50% lower** than full human-translation rates [Source 31, journalism/industry (Nimdzi; practitioner accounts)]. Long-form journalism documents translators reporting collapsing rates and exits from the field [Source 32, journalism (Brian Merchant, *Blood in the Machine*, 2025)] — **note: this is post-LLM (2023+) and conflates LSTM-era MT with newer generative AI; attribute cautiously.** Academic work documents "automation anxiety" in translator communities well before LLMs (Vieira 2018) [Source 33, peer-reviewed].
- **Reconciliation:** demonstrated effect = *task and pay restructuring* (rise of post-editing, downward rate pressure) rather than *net job destruction*, at least through ~2023. The strongest single source (OECD) is a report, not a peer-reviewed journal article; corroborated directionally by BLS projections and the VoxEU/CEPR analysis of MT's labor effects [Source 30; Source 34, peer-reviewed/economics (CEPR VoxEU)].

### 5.2 Transcription and captioning work (demonstrated: ASR-driven wage compression)

- Practical ASR turned much transcription into lower-paid *post-editing of machine output*. The clearest documented event: in November 2019 **Rev.com cut contractor base pay to $0.30 per minute of audio**, sparking public outrage — widely read as ASR commoditizing the work [Source 35, journalism (Business Insider 2019); Source 35b, journalism (BoingBoing)]. Current Rev AI-transcription pricing ($0.25/audio-min) underscores how ASR reset the price floor [Source 36, industry (Rev pricing)]. *Demonstrated effect on this segment; magnitude beyond Rev is anecdotal — flag as segment-specific.*

### 5.3 Call centers / localization (mixed: real automation, contested net effect)

- Neural ASR + TTS enabled IVR/voice automation in contact centers (e.g., Webex Contact Center neural TTS) [Source 37, industry]. Commentary at the time of the Rev cuts flagged telephone customer service as "next field for wage cuts" [Source 35b, journalism] — **a prediction, partly borne out but still partly speculative.** Localization/content work has shifted toward MTPE workflows (per §5.1). Net employment effects in call centers in the pure-LSTM era are **not well quantified — flag as under-evidenced.**

---

## 6. Demonstrated vs speculative — quick ledger

| Claim | Status | Key source |
|---|---|---|
| GNMT deployed 2016, >100 languages | Demonstrated | 1, 2 |
| MT ↑ eBay exports 10.9% (causal) | Demonstrated (single study) | 4, 4a |
| Microsoft ASR 5.9%→5.1% WER "human parity" | Demonstrated *as benchmark* | 7, 7c |
| ASR "human parity" in the real world | **Refuted/overstated** | 8c |
| Smart Compose saves >1B chars typed/week | Demonstrated | 13 |
| Smart Reply = 10–12% of mobile replies | Demonstrated | 11, 12 |
| Live Transcribe >1B downloads | Demonstrated | 23, 23b |
| ASR captioning >90% in quiet classroom | Demonstrated (small study) | 24 |
| AAC prediction: benefits + voice/authorship harms | Demonstrated | 28 |
| No large-scale translator displacement (to ~2023) | Demonstrated (report) | 30 |
| MTPE rates ~50% below human rates | Demonstrated (survey/practitioner) | 31 |
| Rev transcription pay cut to $0.30/min | Demonstrated (one firm) | 35 |
| MT causes linguistic homogenization/hegemony | **Speculative/theorized** | 10, 8 |
| Smart Reply/Compose homogenize human writing | **Speculative** | (no scale evidence) |
| Pervasive covert ASR surveillance | **Speculative** (capability real; incidents documented) | 17, 18 |
| Call-center net job loss from ASR | **Under-evidenced** | 35b, 37 |

---

## Weak / single-sourced claims (explicit flags)
1. **eBay +10.9% trade effect** — rigorous and peer-reviewed, but a *single* platform natural experiment; do not generalize to a universal elasticity. (Note: working-paper 17.5% vs published 10.9% — cite 10.9% as the headline.)
2. **Linguistic hegemony / homogenization** — argued, not measured at scale; speculative.
3. **Smart Reply 10% × 300B emails = "10% of all email"** — a *derived* extrapolation (Source 11b), not a direct measurement.
4. **Translator rate collapse (Merchant 2025)** — vivid but post-LLM and journalistic; conflates LSTM-era MT with generative AI. Use only as qualitative testimony.
5. **MTPE "~50% lower" rate** — from industry surveys/practitioner consensus, not a single authoritative dataset; directionally robust, precise figure soft.
6. **Live Transcribe accuracy 85–95%** — from secondary/journalistic roundup (Source 20), not a controlled study; the 90%+ classroom figure (Source 24) is better-grounded but small-N.
7. **Voice-assistant "3.25 billion in use"** — counts installed assistants/devices, not unique users; industry estimate.
8. **Microsoft "human parity"** — true only on the clean Switchboard/NIST-2000 benchmark; Beaver 2022 (Source 8c) shows it does not hold in the real world. Always qualify.

---

## Sources

1. Google Research, "Recent Advances in Google Translate." research.google blog. https://research.google/blog/recent-advances-in-google-translate — **industry**
2. "Google Neural Machine Translation," Wikipedia. https://en.wikipedia.org/wiki/Google_Neural_Machine_Translation — **reference/encyclopedic (tertiary)**
3. Johnson, M. et al. (2017), "Google's Multilingual Neural Machine Translation System: Enabling Zero-Shot Translation," *TACL*. https://aclanthology.org/Q17-1024.pdf — **peer-reviewed**
4. Brynjolfsson, E., Hui, X., & Liu, M. (2018), "Does Machine Translation Affect International Trade? Evidence from a Large Digital Platform," NBER WP 24917. https://www.nber.org/system/files/working_papers/w24917/w24917.pdf — **peer-reviewed (working paper)**
4a. Brynjolfsson, Hui & Liu (2019), *Management Science* 65(12):5449–5460 (+10.9% exports). https://doi.org/10.1287/mnsc.2019.3388 — **peer-reviewed (journal)**
4b. "When machine learning packs an economic punch," MIT News, Dec 2019. https://news.mit.edu/2019/machine-learning-sales-ebay-translation-1220 — **journalism**
5. OECD (2023), "Not Lost in Translation: The Implications of Machine Translation Technologies for Language Professionals and for Broader Society," OECD Social/Employment WP (DELSA/ELSA/WD/SEM(2023)8). https://www.oecd.org/content/dam/oecd/en/publications/reports/2023/03/not-lost-in-translation_86fb25f9/e1d1d170-en.pdf — **report (OECD)**
6. Google Research, "Unlocking Zero-Resource Machine Translation to Support New Languages in Google Translate," May 2022. https://research.google/blog/unlocking-zero-resource-machine-translation-to-support-new-languages-in-google-translate — **industry**
7. Xiong, W., Droppo, J., Huang, X., Seide, F., Seltzer, M., Stolcke, A., Yu, D., Zweig, G. (2016/2017), "Achieving Human Parity in Conversational Speech Recognition," arXiv:1610.05256; IEEE/ACM TASLP 2017. https://arxiv.org/abs/1610.05256 — **peer-reviewed**
7b. Microsoft, "Historic Achievement: Microsoft researchers reach human parity in conversational speech recognition," Oct 2016. https://blogs.microsoft.com/ai/historic-achievement-microsoft-researchers-reach-human-parity-conversational-speech-recognition — **industry**
7c. Microsoft, "Microsoft researchers achieve new conversational speech recognition milestone" (5.1% WER), Aug 2017. https://www.microsoft.com/en-us/research/blog/microsoft-researchers-achieve-new-conversational-speech-recognition-milestone — **industry**
8. "Digitally-disadvantaged languages," *Internet Policy Review* (glossary), Apr 2022. https://policyreview.info/glossary/digitally-disadvantaged-languages — **report/academic glossary**
8b. "Surveying the Technology Support of Languages," ACL TDLE 2024. https://aclanthology.org/2024.tdle-1.1.pdf — **peer-reviewed**
8c. Beaver, I. (2022), "Is AI at Human Parity Yet? A Case Study on Speech Recognition," *AI Magazine* 43(4):386–389, DOI 10.1002/aaai.12071. https://ojs.aaai.org/aimagazine/index.php/aimagazine/article/view/22011 — **peer-reviewed**
9. Center for Democracy & Technology (2023), "Large Language Models in Non-English Content Analysis." https://cdt.org/wp-content/uploads/2023/05/non-en-content-analysis-primer-051223-1203.pdf — **report (NGO)**
10. "The Hegemony of English Language in the Digital Era / Safeguarding Linguistic Diversity as Intangible Cultural Heritage," *inTRAlinea*. https://www.intralinea.org/current/article/the_hegemony_of_english_language_in_the_digital_era — **peer-reviewed (translation-studies journal)**
11. Kannan, A. et al. (2016), "Smart Reply: Automated Response Suggestion for Email," arXiv:1606.04870 / KDD 2016 (assists 10% of mobile responses). https://arxiv.org/abs/1606.04870 — **peer-reviewed**
11b. "Do we really want AI answering on our behalf? A study of smart reply," EUSSET. https://dl.eusset.eu/server/api/core/bitstreams/366714bb-18c3-4a51-bf05-0c75286f0146/content — **peer-reviewed (derived extrapolation)**
12. Google Research, "Efficient Smart Reply, now for Gmail" (~12% of replies on mobile), May 2017. https://research.google/blog/efficient-smart-reply-now-for-gmail — **industry**
13. Chen, M.X. et al. (2019), "Gmail Smart Compose: Real-Time Assisted Writing," arXiv:1906.00080 / KDD 2019 (saves >1B characters/week). https://arxiv.org/abs/1906.00080 — **peer-reviewed**
14. "Language Preservation's Efforts Get an AI Boost," Dartmouth News, Apr 2025 / Historica blog. https://home.dartmouth.edu/news/2025/04/language-preservations-efforts-get-ai-boost — **journalism/institutional**
16. "Juniper Estimates 3.25 Billion Voice Assistants Are in Use Today," Voicebot.ai (citing Juniper Research), Feb 2019. https://voicebot.ai/2019/02/14/juniper-estimates-3-25-billion-voice-assistants-are-in-use-today-google-has-about-30-of-them — **industry/journalism**
17. "Legal Risks of Using AI Voice Analytics for Customer Service," Debevoise Data Blog, Jan 2023. https://www.debevoisedatablog.com/2023/01/10/legal-risks-of-using-ai-voice-analytics-for-customer-service — **journalism/legal**
18. "Security and privacy problems in voice assistant applications: A survey," *Computers & Security* (Elsevier), 2023. https://www.sciencedirect.com/science/article/pii/S0167404823003589 — **peer-reviewed**
20. "Best Live Transcribe Apps…" (85–95% accuracy in quiet conditions), BOSS AI Blog, 2026. https://bossai.tech/blog/live-transcribe-app — **journalism (secondary roundup)**
21. "Swiftkey Releases Predictive Keyboard Built On A Neural Network," TechCrunch, Oct 2015; "SwiftKey improves its keyboard predictions with neural networks," TheNextWeb, Sept 2016. https://techcrunch.com/2015/10/08/swiftkey-releases-predictive-keyboard-built-on-a-neural-network — **journalism**
22. Google Research, "Long Short Term Memory Neural Network for Keyboard Gesture Decoding" (Alsharif et al.). https://research.google.com/pubs/archive/43461.pdf — **peer-reviewed/industry**
23. Google, "Making audio more accessible with two new apps" (Live Transcribe launch), Feb 2019. https://blog.google/company-news/outreach-and-initiatives/accessibility/making-audio-more-accessible-two-new-apps — **industry**
23b. "Google Live Transcribe reaches over one billion downloads," Gallaudet University. https://gallaudet.edu/information-technology/b-s-in-information-technology/google-live-transcribe-reaches-over-one-billion-downloads — **report (university/NGO)**
24. "Accuracy of Speech-to-Text Captioning for Students Who are Deaf or Hard of Hearing" (Ava, Microsoft Translator; >90% in quiet conversation), *Journal of Educational, Pediatric & (Re)Habilitative Audiology*. https://www.edaud.org/assets/docs/1-article-21.pdf — **peer-reviewed (applied)**
25. Kafle, S. & Huenerfauth, M. (2017), "Evaluating the Usability of Automatically Generated Captions for People who are Deaf or Hard of Hearing," ASSETS 2017. https://dl.acm.org/doi/10.1145/3132525.3132542 — **peer-reviewed**
26. Hearing Loss Association of America, "Captioning" (CART vs automatic). https://www.hearingloss.org/find-help/captioning — **NGO**
27. Tarjimly (nonprofit, founded 2017). https://www.tarjimly.org/ ; "Boeing Partners with Translation App Tarjimly," Nov 2022. https://boeing.mediaroom.com/2022-11-03-Boeing-Partners-with-Translation-App-Tarjimly-to-Help-Break-Language-Barriers — **NGO/industry**
27b. Translators without Borders, humanitarian-response blog (elevating marginalized languages via MT data). https://translatorswithoutborders.org/blog/tag/humanitarian-response — **NGO**
28. Valencia, S. et al. (2023), "'The Less I Type, the Better': How AI Language Models can Enhance or Impede Communication for AAC Users," CHI 2023 (12 AAC users), DOI 10.1145/3544548.3581560. https://dl.acm.org/doi/fullHtml/10.1145/3544548.3581560 — **peer-reviewed**
29. Trnka, K. et al. (2008), "Word Prediction and Communication Rate in AAC." https://www.eecis.udel.edu/~mccoy/publications/2008/trnka08at.pdf — **peer-reviewed**
30. OECD (2023), *Not Lost in Translation* (see Source 5) — "no large-scale substitution effect"; +~20% projected employment 2021–2031, 15 pp above average. — **report (OECD)**
31. "Machine Translation Post-editing: How Much Is the Fish?" Nimdzi (MTPE pricing/rates). https://www.nimdzi.com/machine-translation-post-editing-how-much-is-the-fish-nimdzi-finger-food — **journalism/industry**
32. Merchant, B. (2025), "AI Killed My Job: Translators," *Blood in the Machine*. https://www.bloodinthemachine.com/p/ai-killed-my-job-translators — **journalism**
33. Vieira, L.N. (2018/2020), "Automation anxiety and translators," *Translation Studies*. https://www.tandfonline.com/doi/full/10.1080/14781700.2018.1543613 — **peer-reviewed**
34. "Lost in translation: AI's impact on translators and foreign-language skills," CEPR/VoxEU, Mar 2025. https://cepr.org/voxeu/columns/lost-translation-ais-impact-translators-and-foreign-language-skills — **peer-reviewed-adjacent (economics column)**
35. "Rev Transcription Contractors Reveal Work Conditions…" (base pay cut to $0.30/min, Nov 2019), Business Insider. https://www.businessinsider.com/rev-transcription-contractors-reveal-work-conditions-challenges-pay-2019-11 — **journalism**
35b. "Transcription service rev.com cuts… effective hourly wage," BoingBoing forum, Nov 2019. https://bbs.boingboing.net/t/transcription-service-rev-com-cuts-professional-transcriptionists-effective-hourly-wage-from-6-35-to-4-50/155131 — **journalism**
36. Rev.com Pricing (AI transcription $0.25/audio-min). https://support.rev.com/hc/en-us/articles/18893487380365-Pricing — **industry**
37. Cisco, "Text-to-Speech (TTS) in Webex Contact Center" (neural TTS in call centers). https://help.webex.com/en-us/article/ntkjqhw/Text-to-Speech-(TTS)-in-Webex-Contact-Center — **industry**

---

*Memo prepared 2026-06-14. Coverage: 5 strands, ~30 distinct sources across peer-reviewed / industry / report / journalism. Strongest evidence: eBay trade study (1.2), Smart Compose/Reply figures (3.1), Live Transcribe + AAC evaluations (4), OECD labor report (5.1), Rev pay cut (5.2). Weakest/speculative: linguistic hegemony (1.4), writing homogenization (3.2), pervasive surveillance (2.3), call-center net effects (5.3) — all flagged above.*
