# Strand E1 — Case Studies 1–5: LSTM / Encoder–Decoder Systems in the Real World

**Scope:** Five deployed LSTM / sequence-to-sequence (seq2seq) systems, each covering (a) what & who, (b) architecture with primary citation and the Transformer transition, (c) deployment scale/impact with cited figures, (d) societal/ethical dimensions, (e) sources. Source types are labelled **[primary paper]**, **[official blog/engineering]**, **[reputable journalism]**, **[reference/encyclopedia]**, or **[vendor marketing]**. Company marketing is distinguished from independent evaluation throughout.

---

## Case Study 1 — Google Neural Machine Translation (GNMT, 2016)

**(a) What it is / who built it.** GNMT is Google's production neural machine translation system, introduced in 2016 to replace the company's phrase-based statistical machine translation (PBMT/SMT) engine behind Google Translate. It was developed by a large Google Brain / Google Translate team led by Yonghui Wu, Mike Schuster, Zhifeng Chen, Quoc V. Le, and colleagues (Wu et al. 2016) [1, primary paper].

**(b) Architecture (with primary citation).** GNMT is a deep LSTM encoder–decoder ("seq2seq") with attention. From the abstract of Wu et al. (2016): *"Our model consists of a deep LSTM network with 8 encoder and 8 decoder layers using attention and residual connections."* The attention mechanism connects the bottom layer of the decoder to the top layer of the encoder (for parallelism); rare words are handled by sub-word "wordpiece" units; inference uses low-precision arithmetic and a beam search with length-normalization and a coverage penalty [1, primary paper]. This is *not* a Transformer system — it predates "Attention Is All You Need" (Vaswani et al. 2017). The **Transformer transition** came later: Google's *next* internal NMT generation moved to Transformer/RNMT+ hybrids (the RNMT+ work, Chen et al. 2018, explicitly combines LSTM and Transformer advances) [8, primary paper], and Google Translate's stack progressively shifted to Transformer-based models from ~2017 onward.

The multilingual extension is **Johnson et al. (2017)** [2, primary paper; 3, official blog]. They added a single artificial token at the start of the source sentence to specify the target language, requiring *no change to the base GNMT architecture*, and trained one shared model across many language pairs. This enabled **zero-shot translation** — translating between language pairs never seen paired in training (e.g., Korean⇄Japanese after training only on Korean⇄English and Japanese⇄English) — and produced evidence of a shared "interlingua" representation [2, 3]. Google reported the multilingual system was *"running in production today for all Google Translate users,"* serving 10 of 16 newly launched language pairs at the time [3, official blog].

**(c) Deployment scale / impact (cited figures).**
- **Quality (company evaluation, side-by-side):** GNMT *"reduces translation errors by an average of 60% compared to Google's phrase-based production system"* on isolated simple sentences in a human side-by-side evaluation [1, primary paper]. *Nature*'s news coverage independently reported the same headline figure ("cut error rate by 60%, the company says") — note this is Google's own metric reported by journalism, not an independent benchmark [4, reputable journalism]. On the standard **WMT'14** benchmarks GNMT achieved "competitive results to state-of-the-art," with an 8-model ensemble reaching ~41.16 BLEU on En→Fr (state-of-the-art at the time) [1, primary paper].
- **Scale of Google Translate:** At the time of the GNMT/zero-shot rollout (2016), Google Translate supported 103 languages and translated *"over 140 billion words every day"* [3, official blog]. Google's "Ten years of Google Translate" (2016) cited "more than 500 million" users and "more than 100 billion words a day" [9, official blog]. By 2025–2026 Google stated **>1 billion monthly users** and ~250 languages [10, official blog]. (Earlier, 2013: "a billion translations a day for 200 million users" [CNET, reputable journalism].)

**(d) Societal / ethical dimensions.**
- *Access vs. quality asymmetry.* The 60% error-reduction figure is from "isolated simple sentences" and from Google's own evaluation — independent and downstream studies have repeatedly shown NMT quality varies sharply by language pair and domain, with much weaker performance for low-resource languages, which can entrench digital inequality even as coverage expands.
- *Interlingua / zero-shot.* Johnson et al.'s shared representation is scientifically important but means quality for an unseen pair is inferred, not directly trained — raising reliability concerns for high-stakes uses (legal, medical, asylum) where users may not know a pair is zero-shot.
- *Marketing vs. independent evaluation.* The widely-quoted "60%" and "human-level" framings originate in Google's papers and PR; the academic record (e.g., later critiques of the "bridging the gap to human translation" claim) cautions that sentence-level side-by-side wins do not equal document-level human parity.

**(e) Sources.** [1], [2], [3], [4], [8], [9], [10] (full list below).

---

## Case Study 2 — DeepL

**(a) What it is / who built it.** DeepL Translator is a neural MT service launched **28 August 2017** by DeepL GmbH (Cologne, Germany), the company formerly known as Linguee. Co-founder Gereon Frahling (ex-Google Research) and CTO Jaroslaw "Jarek" Kutylowski built it on top of Linguee's large bilingual corpus [5, reputable journalism; 11, reference]. It positioned itself as a higher-quality challenger to Google/Microsoft/Facebook translation.

**(b) Architecture (what is publicly known — with caveats).** DeepL is *deliberately secretive* about its architecture, so primary technical detail is thin and must be sourced carefully:
- **At launch (2017):** Contemporary reporting (TechCrunch, based on email from CEO Frahling) states DeepL moved from the **recurrent neural networks (RNNs)** it had used previously to **convolutional neural networks (CNNs)** with **attention mechanisms**, citing then-recent research showing CNNs were "the way to go" for long, complex sentences [5, reputable journalism]. (This places DeepL in the encoder–decoder + attention lineage but with a CNN encoder rather than an LSTM — a meaningful nuance for the seminar's "encoder–decoder" theme.) The TOP500 report adds that DeepL trained on a 5.1-petaflop supercomputer in Iceland and claimed BLEU advantages, e.g. 31.1 vs. Google's 28.4 on a shared En→De test set [6, reputable journalism].
- **Today:** DeepL's own materials say it uses *"custom neural network architectures,"* containing *"parts of"* the Transformer (including attention) but with a *"notable[y] different ... topology,"* running *"billion-parameter"* models [7, vendor blog]. Wikipedia states the algorithm "uses the transformer architecture" [11, reference]. Since ~2024 DeepL has shipped an LLM-based "next-gen" model [7, vendor blog]. **Caveat / flag:** there is **no DeepL primary/peer-reviewed architecture paper**; all architecture claims are vendor statements or journalism relaying vendor statements.

**(c) Deployment scale / impact (cited figures).**
- **Quality claims — distinguish source.** DeepL's launch claim that professional translators preferred it ~**3-to-1** over Google/Microsoft/Facebook in blind tests is a **company-run blind test** reported by *TOP500* and *DW* [6, reputable journalism; 12, reputable journalism]. *DW* (2018) describes the blind test of 100 sentences scored by professional translators [12]. TechCrunch's reviewers *independently* judged DeepL's output "generally superior" on French/German samples — independent but anecdotal, not a controlled benchmark [5].
- **Market / usage (largely vendor figures).** A 2024 Forrester study (commissioned, reported via DeepL PR) and DeepL's own releases claim DeepL was the **most-used MT provider among language service companies in 2024 (82% adoption vs. Google 46%)** [13, vendor PR/PRNewswire]; revenues of **US$185.2M (2024), up 31% from US$141.3M (2023)** [14, third-party stats aggregator]; **>200,000 business customers / unicorn valuation >$2B** [DeepL About + business profiles, vendor/secondary].
- **EU / professional context.** DeepL is European-headquartered, GDPR-positioned, and strongest on European language pairs; broad surveys report ~70%+ of independent European language professionals use MT to some extent [redokun/sonix, secondary]. This is the competitive context: DeepL markets quality + EU data-residency/security to the professional-translation and enterprise market that Google/Microsoft also chase.

**(d) Societal / ethical dimensions.**
- *Opacity.* The lack of a published architecture or evaluation methodology makes DeepL's superiority claims hard to verify independently; most "DeepL beats Google" figures trace back to DeepL-run or DeepL-commissioned tests.
- *Labor displacement.* DeepL's value proposition (Forrester: "reducing translation time by 90%") directly implicates the professional-translation workforce in the EU — productivity tool vs. job displacement is the core ethical tension.
- *Concentration & data.* Built on Linguee's web-scraped bilingual corpus (>1 billion translations), raising provenance/copyright questions common to MT training data.

**(e) Sources.** [5], [6], [7], [11], [12], [13], [14].

---

## Case Study 3 — Apple Siri / On-Device Speech Recognition

**(a) What it is / who built it.** Siri is Apple's voice assistant (acquired 2010, shipped 2011). Apple's Siri Speech and Machine Learning teams progressively rebuilt Siri's speech stack with deep learning from ~2014 onward, publishing details through the **Apple Machine Learning Journal / Research** site from 2017 [15, 16, official engineering].

**(b) Architecture (with citation — and an important flag).**
- **"Hey Siri" voice trigger (on-device):** The always-on wake-word detector uses a **Deep Neural Network (DNN)** acoustic model (5 hidden layers of 32/128/192 units) feeding a temporal-integration (HMM-style dynamic-programming) stage — *not* an LSTM. Apple's primary write-up: *"Hey Siri: An On-device DNN-powered Voice Trigger"* (Siri Team, 2017) [15, official engineering]. This is the clearest Apple-authored primary source on the on-device, privacy-relevant component.
- **Main / large-vocabulary ASR (recurrent / LSTM):** Apple's *main* speech recognizer historically ran in the cloud (Apple says the "main automatic speech recognition ... [is] in the Cloud") [15]. Apple did move its acoustic models from HMM-GMM to **deep and recurrent (LSTM) networks**. The most defensible citation that Apple's acoustic model is **recurrent/LSTM** is the IEEE Signal Processing Magazine survey *"Speech Processing for Digital Home Assistants"* (Haeb-Umbach et al., 2019), which documents that the Siri team "replaced [HMMs] with deep and recurrent" networks and built on-device deep-learning systems [secondary survey]. Apple's *"Optimizing Siri on HomePod in Far-Field Settings"* (2018) describes a deep-learning signal-processing front end (DNN-based mask estimation, beamforming) feeding the recognizer, but does not itself name the acoustic model as LSTM [17, official engineering]. Apple's *Geo-LM* article (2018) reports a **hybrid CNN-HMM** acoustic model in its experiments [18, official engineering].
- **⚠ FLAG (per task instructions):** I could **not** find a single *Apple-authored primary paper that explicitly states "Siri's acoustic model is an LSTM."* The LSTM/seq2seq attribution for Siri's main ASR rests on (i) Apple's general statements that it uses deep+recurrent networks and (ii) the third-party IEEE survey. Treat the "LSTM acoustic model" claim for Siri as **well-supported but indirect**, unlike GNMT/Smart Compose where the primary paper names the architecture. The strongest *primary* Apple architecture document is the DNN voice-trigger paper [15].
- **On-device transition & Transformers:** Apple shipped **on-device dictation/ASR with iOS 13 (2019)** — "Accurate dictation using the Siri speech recognition engine," processed on device using the Neural Engine, framed as a privacy improvement [19, official support]. Apple's stack later moved to Transformer/Conformer and RNN-T models (e.g., Apple's "Conformer-Based Speech Recognition on Extreme Edge," and 2024+ Apple Intelligence on-device models) — the Transformer transition mirrors the industry's ~2018–2021 shift.

**(c) Deployment scale / impact (cited figures).** Apple does not publish Siri ASR accuracy benchmarks the way Google does. Public scale figures: Apple has repeatedly cited Siri usage in the **hundreds of billions of requests per month / >500 million devices** range in keynotes (Apple marketing). The **iOS 13 on-device** change is the load-bearing deployment fact: on-device dictation removed the network round-trip and, per Apple, keeps audio on-device for the keyboard dictation path [19, official support]. HomePod far-field WER improvements reported by Apple: ~40%/90%/74%/61% relative WER reduction across reverberation/playback/noise/competing-talker conditions (Apple's own measurements) [17, official engineering].

**(d) Societal / ethical dimensions.**
- *Privacy framing.* Apple's central differentiator is **on-device processing** (voice trigger on device; iOS 13 on-device dictation) and "data is not associated with your Apple Account" [Apple legal — Siri/Dictation privacy]. This is both a genuine architectural choice and a marketing position.
- *The grading scandal.* In 2019, reporting (The Guardian) revealed Apple contractors listened to Siri recordings (including accidental activations) for grading; Apple apologized, made human grading **opt-in**, and stopped retaining audio by default. This is the key independent ethical episode for this case (contrast Apple's privacy marketing with the documented practice).
- *Accessibility.* On-device dictation and Siri provide significant accessibility value (hands-free, motor/visual impairments), a positive societal dimension.

**(e) Sources.** [15], [16], [17], [18], [19] + IEEE survey (Haeb-Umbach et al. 2019) + Apple legal/privacy + Guardian 2019 (cited inline).

---

## Case Study 4 — Gmail Smart Reply & Smart Compose

**(a) What it is / who built it.** Two Google features that suggest text in Gmail: **Smart Reply** (short canned-reply suggestions, launched in Inbox by Gmail, 2015–2016; Kannan et al. 2016) and **Smart Compose** (real-time inline sentence-completion as you type, 2018; Chen et al. 2019). Both from Google Research / Gmail teams [20, primary paper; 21, primary paper; 22, official blog].

**(b) Architecture (with primary citations).**
- **Smart Reply (Kannan et al. 2016):** an **end-to-end sequence-to-sequence (LSTM) model** — the input email is encoded word-by-word with an **LSTM**, and candidate replies are decoded with an LSTM, with a response set + scoring for diversity/safety [20, primary paper]. Google's later blog confirms: *"the initial release of Smart Reply encoded input emails word-by-word with a long-short-term-memory (LSTM) recurrent neural network, and then decoded potential replies"* [22, official blog]. The 2017 "Efficient Smart Reply" update moved to a more efficient hierarchical / feed-forward matching model for serving efficiency [22, official blog; 23, primary paper].
- **Smart Compose (Chen et al. 2019, KDD):** *"At the core of Smart Compose is a large-scale neural language model."* The paper studied **both LSTM (RNN) and Transformer** language models and seq2seq variants [21, primary paper]. Crucially for the LSTM-history theme, **they chose an LSTM (LSTM-2-1024) for production**: although Transformer models had *better quality* (lower perplexity, e.g. an 84M-param Transformer beat an 80M-param LSTM by ~0.18 log-perplexity), the Transformer's **decoding latency was much worse** (self-attention must re-attend to all previous steps, so per-step cost grows with sequence length) — unacceptable for real-time keystroke-latency suggestions [21, primary paper]. This is a clean, citable example of LSTM being retained in production *because of* latency even after Transformers won on quality.

**(c) Deployment scale / impact (cited figures).**
- **Smart Reply adoption:** Kannan et al. (2016) state Smart Reply *"is responsible for assisting with 10% of all mobile responses"* in Inbox by Gmail [20, primary paper]. Google's 2017 blog updated this to *"about 12% of replies in Inbox on mobile"* [22, official blog].
- **Smart Compose context:** Chen et al. (2019) frame the scale of the problem: email had *"an estimated 3.8 billion users sending 281 billion e-mails daily"* [21, primary paper] (industry figure, not a Smart Compose usage stat). Smart Compose rolled out to consumer Gmail (2018) and Workspace, in English first, later Spanish/French/Italian/Portuguese [21; Google support].

**(d) Societal / ethical dimensions (well-documented in the primary papers).**
- *Response homogenization.* By suggesting a small set of "safe," common replies, Smart Reply/Compose can nudge users toward uniform, blander language — a documented concern that machine suggestion shapes (and flattens) human expression.
- *Gender / occupation bias.* Chen et al. (2019) **explicitly report** gender-occupation bias: typing "I am meeting an investor next week" yielded the suggestion "Did you want to meet *him*," while "a nurse" yielded "meet *her*." Their mitigation was blunt: *"we removed any suggestions with a gender pronoun,"* and they continue exploring algorithmic debiasing [21, primary paper]. This bias-filtering-by-deletion is itself an ethically interesting design choice (suppressing a capability to avoid harm).
- *Privacy.* Both papers stress training on email "without anyone on the project being able to look at the underlying data," and filtering offensive/PII content from suggestions [21, primary paper].

**(e) Sources.** [20], [21], [22], [23].

---

## Case Study 5 — Microsoft / Skype Translator + Microsoft Translator

**(a) What it is / who built it.** **Skype Translator** is a near-real-time speech-to-speech translation feature (preview Dec 2014; broadly available 2015), built jointly by Skype and Microsoft Research, on top of **Microsoft Translator** (Microsoft's MT service / API). Lineage traces to Microsoft Research's "Translating Telephone" work (Frank Seide, Kit Thambiratnam) [24, official blog; 25, reference]. Microsoft Translator powers Skype Translator, the Translator apps, Office add-ins, Bing, and the Azure (Cognitive Services / AI Foundry) Translator API.

**(b) Architecture (with citations + the seq2seq/LSTM transition).** Skype Translator is a **speech-to-speech pipeline**: ASR → MT → TTS (text-to-speech synthesis), with a "TrueText"/speech-correction stage to clean disfluent spoken input [26, primary/conference paper — ACL TC 2015]. Originally it combined **DNN-based speech recognition** with Microsoft Translator's **statistical machine translation (SMT)** [25, reference]. The neural transition is well-dated by Microsoft's own blogs:
- **Nov 2016:** *"Microsoft Translator is now powering all speech translation through state-of-the-art neural networks,"* replacing SMT for speech languages; the neural models are described as better capturing full-sentence context [27, official blog].
- **Nov 2017:** Microsoft announced *"Speech translation is now powered end to end with LSTM technology,"* explicitly: *"Speech recognition is moving to advanced LSTM neural network architecture,"* and *"Microsoft Translator's NMT uses LSTM technology — speech translation is therefore now using LSTM technology from end to end"* [28, official blog]. They reported LSTM speech recognition improved **word error rate by up to 29%** depending on language [28, official blog]. This is a direct, citable statement that the deployed system was **LSTM encoder–decoder end-to-end** (ASR LSTM + NMT LSTM).
- **Transformer transition:** Microsoft Translator later moved to Transformer-based and Mixture-of-Experts models — e.g., the 2022 **Z-code Mixture-of-Experts** production models (5-billion-parameter models, "80× larger than" the prior production models) [29, official research blog].

**(c) Deployment scale / impact (cited figures).**
- **Speech languages at neural switch (2016):** the 11 languages then NMT-powered (incl. Japanese/Korean text) represented *"more than 80% of the translations performed daily by Microsoft Translator"* [27, official blog].
- **Overall reach:** By Oct 2021 Microsoft Translator/Azure supported **>100 languages and dialects**, which Microsoft stated were "natively spoken by 5.66 billion people" (~72% of the world) [30, official news; InfoQ relaying it, reputable journalism]. Today Azure Translator advertises 100–135 languages [Azure docs, vendor].
- **Skype Translator availability:** integrated into Skype for Windows desktop (Oct 2015); the underlying speech-translation capability was opened as the Microsoft Translator **Speech API** for third-party developers (Mar 2016) [25, reference; 27, official blog].

**(d) Societal / ethical dimensions.**
- *Accessibility (a defining, positive case).* Microsoft built **Presentation Translator** (a Microsoft Garage project) and **Microsoft Translator for Education** to provide **live captions** for students/audience members who are **deaf or hard of hearing**, non-native speakers, or dyslexic [31, vendor/education; 32, official blog — accessibility/DHH tags]. EdScoop and education case studies document classroom and parent-teacher communication use [edscoop, reputable journalism]. This is the strongest accessibility-impact story among the five cases.
- *Real-time error risk.* Independent coverage (MIT Technology Review, "Something Lost in Skype Translation," 2015) cautioned that real-time speech translation makes visible, consequential errors mid-conversation — accuracy varies with accent, noise, and disfluency, and errors can mislead in cross-lingual conversations where neither party can check the other's language [MIT Tech Review, reputable journalism].
- *Privacy / cloud processing.* Unlike Apple's on-device framing, Skype/Microsoft Translator is cloud-based; conversational audio is sent to Microsoft servers, raising the usual cloud-voice privacy considerations (mitigated later by on-premises NMT offerings [28]).

**(e) Sources.** [24], [25], [26], [27], [28], [29], [30], [31], [32].

---

## Cross-case note: marketing vs. independent evaluation

| Case | Headline quality claim | Source character |
|---|---|---|
| GNMT | "60% error reduction" | Google's own side-by-side eval (relayed by Nature) — **company metric** |
| DeepL | "preferred 3-to-1," BLEU 31.1 vs 28.4 | DeepL-run blind test / DeepL-reported BLEU — **vendor**; TechCrunch hands-on is independent but anecdotal |
| Siri | privacy / on-device | Apple engineering + marketing; 2019 grading scandal is the **independent** counterweight |
| Smart Reply/Compose | 10–12% of mobile replies; bias self-reported | Google **primary papers** (unusually candid on bias) |
| MS/Skype | "up to 29% WER reduction" | Microsoft **own blog**; accessibility impact corroborated by education journalism |

**Architecture-citation confidence:** Strong & primary for **GNMT** [1,2], **Smart Reply/Compose** [20,21], and **Microsoft end-to-end LSTM** [28]. **DeepL** has *no* primary architecture paper (vendor + journalism only). **Apple/Siri**'s "LSTM acoustic model" is **flagged**: supported indirectly (Apple's DNN voice-trigger paper [15] + general deep/recurrent statements + IEEE survey), not by an Apple paper naming the main ASR as LSTM.

---

## Sources

1. Wu, Y., Schuster, M., Chen, Z., Le, Q.V., Norouzi, M., et al. (2016). *Google's Neural Machine Translation System: Bridging the Gap between Human and Machine Translation.* arXiv:1609.08144. **[primary paper]** — https://arxiv.org/abs/1609.08144
2. Johnson, M., Schuster, M., Le, Q.V., Krikun, M., Wu, Y., et al. (2017). *Google's Multilingual Neural Machine Translation System: Enabling Zero-Shot Translation.* TACL, Vol. 5. **[primary paper]** — https://aclanthology.org/Q17-1024 / https://arxiv.org/abs/1611.04558
3. Google Research Blog (2016). *Zero-Shot Translation with Google's Multilingual Neural Machine Translation System.* **[official blog]** — https://research.google/blog/zero-shot-translation-with-googles-multilingual-neural-machine-translation-system
4. Castelvecchi, D. (2016). *Deep learning boosts Google Translate tool.* Nature News. **[reputable journalism]** — https://www.nature.com/articles/nature.2016.20696
5. Coldewey, D. (2017). *DeepL schools other online translators with clever machine learning.* TechCrunch, 29 Aug 2017. **[reputable journalism]** — https://techcrunch.com/2017/08/29/deepl-schools-other-online-translators-with-clever-machine-learning
6. Feldman, M. (2017). *Startup Launches Language Translator That Taps into Five-Petaflop Supercomputer.* TOP500.org, 31 Aug 2017. **[reputable journalism]** — https://www.top500.org/news/startup-launches-language-translator-that-taps-into-five-petaflop-supercomputer
7. DeepL (2021, updated). *How does DeepL work?* DeepL Blog. **[vendor blog]** — https://www.deepl.com/en/blog/how-does-deepl-work
8. Chen, M.X., Firat, O., Bapna, A., Johnson, M., Macherey, W., et al. (2018). *The Best of Both Worlds: Combining Recent Advances in Neural Machine Translation* (RNMT+). ACL 2018. **[primary paper]** — https://aclanthology.org/P18-1008.pdf
9. Turovsky, B. (2016). *Ten years of Google Translate.* Google Blog. **[official blog]** — https://blog.google/products-and-platforms/products/translate/ten-years-of-google-translate
10. Google (2025/2026). *Google Translate turns 20 / 20 fun facts* (>1 billion monthly users, ~250 languages). Google Blog. **[official blog]** — https://blog.google/products-and-platforms/products/translate/fun-facts-google-translate-20-years
11. *DeepL Translator.* Wikipedia. **[reference/encyclopedia]** — https://en.wikipedia.org/wiki/DeepL_Translator
12. Deutsche Welle (2018). *DeepL: Cologne-based startup outperforms Google Translate.* DW, 5 Dec 2018 (describes the 100-sentence professional-translator blind test). **[reputable journalism]** — https://www.dw.com/en/deepl-cologne-based-startup-outperforms-google-translate/a-46581948
13. DeepL / PRNewswire (2024). *DeepL is 2024's Most-Used Machine Translation Provider Worldwide Among Language Service Companies* (82% vs Google 46%; Forrester 345% ROI). **[vendor PR]** — https://www.prnewswire.com/news-releases/deepl-is-2024s-most-used-machine-translation-provider-worldwide-among-language-service-companies-302270449.html
14. ElectroIQ (2025). *DeepL Statistics and Facts* (revenue US$185.2M 2024 / US$141.3M 2023). **[third-party stats aggregator]** — https://electroiq.com/stats/deepl-statistics
15. Siri Team, Apple (2017). *Hey Siri: An On-device DNN-powered Voice Trigger for Apple's Personal Assistant.* Apple Machine Learning Research. **[official engineering]** — https://machinelearning.apple.com/research/hey-siri
16. Apple Machine Learning Research — *Research Highlights / Siri voices & speech.* **[official engineering]** — https://machinelearning.apple.com/highlights
17. Siri / Audio Software Eng. Teams, Apple (2018). *Optimizing Siri on HomePod in Far-Field Settings.* Apple Machine Learning Research. **[official engineering]** — https://machinelearning.apple.com/research/optimizing-siri-on-homepod-in-far-field-settings
18. Apple (2018). *Finding Local Destinations with Siri's Regionally Specific Language Models for Speech Recognition* (uses hybrid CNN-HMM acoustic model). Apple ML Research. **[official engineering]** — https://machinelearning.apple.com/research/regionally-specific-language-models
19. Apple Support. *About iOS 13 Updates* — on-device dictation via the Siri speech recognition engine. **[official support]** — https://support.apple.com/en-us/118392
20. Kannan, A., Kurach, K., Ravi, S., et al. (2016). *Smart Reply: Automated Response Suggestion for Email.* KDD 2016 / arXiv:1606.04870 (seq2seq LSTM; "10% of all mobile responses"). **[primary paper]** — https://arxiv.org/abs/1606.04870 / https://research.google.com/pubs/archive/45189.pdf
21. Chen, M.X., Lee, B.N., Bansal, G., Cao, Y., Zhang, S., et al. (2019). *Gmail Smart Compose: Real-Time Assisted Writing.* KDD 2019 / arXiv:1906.00080 (LSTM vs Transformer; LSTM chosen for latency; gender-pronoun bias filtering). **[primary paper]** — https://arxiv.org/pdf/1906.00080
22. Google Research Blog (2017). *Efficient Smart Reply, now for Gmail* (confirms original LSTM seq2seq; "~12% of replies in Inbox on mobile"). **[official blog]** — https://research.google/blog/efficient-smart-reply-now-for-gmail
23. Henderson, M., Al-Rfou, R., Strope, B., et al. (2017). *Efficient Natural Language Response Suggestion for Smart Reply.* Google Research. **[primary paper]** — https://research.google.com/pubs/archive/1846e8a466c079eae7e90727e27caf5f98f10e0c.pdf
24. Microsoft Research (2014). *Enabling Cross-Lingual Conversations in Real Time* / *Skype Translator: Breaking down language barriers.* **[official blog]** — https://www.microsoft.com/en-us/research/blog/enabling-cross-lingual-conversations-real-time
25. *Skype Translator.* Wikipedia (DNN speech recognition + Microsoft Translator SMT; Speech API opened Mar 2016). **[reference/encyclopedia]** — https://en.wikipedia.org/wiki/Skype_Translator
26. Microsoft (2015). *Skype Translator: Breaking Down Language and Hearing Barriers* (S2S pipeline incl. speech correction). ACL Translating & the Computer (TC) 2015. **[primary/conference paper]** — https://aclanthology.org/2015.tc-1.9.pdf
27. Microsoft Translator Blog (15 Nov 2016). *Microsoft Translator launching Neural Network based translations for all its speech languages* (all speech translation switched to neural; 11 languages = >80% of daily translations). **[official blog]** — https://www.microsoft.com/en-us/translator/blog/2016/11/15/microsoft-translator-launching-neural-network-based-translations-for-all-its-speech-languages
28. Microsoft Translator Blog (15 Nov 2017). *Microsoft Translator accelerates use of Neural Networks across its offerings* ("end to end with LSTM technology"; up to 29% WER improvement; on-premises NMT). **[official blog]** — https://www.microsoft.com/en-us/translator/blog/2017/11/15/microsoft-translator-accelerates-use-of-neural-networks-across-its-offerings
29. Microsoft Research Blog (2022). *Microsoft Translator enhanced with Z-code Mixture of Experts models* (5B-parameter MoE production models, "80× larger"). **[official research blog]** — https://www.microsoft.com/en-us/research/blog/microsoft-translator-enhanced-with-z-code-mixture-of-experts-models
30. Microsoft (2021). *Azure AI empowers organizations to serve users in more than 100 languages* (>100 languages; 5.66 billion native speakers). **[official news]** — https://news.microsoft.com/source/features/ai/microsoft-translator-100-language-milestone
31. Microsoft. *Microsoft Translator for Education* / *Presentation Translator* (live captions for deaf/hard-of-hearing, non-native, dyslexic students). **[vendor/education]** — https://www.microsoft.com/en-us/translator/education ; https://www.microsoft.com/en-us/garage/wall-of-fame/presentation-translator
32. Microsoft Translator Blog — *accessibility / DHH tag* (Presentation Translator accessibility for deaf or hard of hearing). **[official blog]** — https://www.microsoft.com/en-us/translator/blog/tag/dhh

**Additional sources cited inline (not numbered):** *Nature* news (case 1); CNET (2013, Google Translate scale); IEEE Signal Processing Magazine — Haeb-Umbach et al. (2019), *Speech Processing for Digital Home Assistants* (Siri deep/recurrent ASR, secondary survey); Apple Legal — *Siri, Dictation & Privacy*; The Guardian (2019, Siri grading/contractor-listening reporting); MIT Technology Review (2015, *Something Lost in Skype Translation*); EdScoop (2018, Microsoft Translator in schools); Redokun / Sonix translation-industry statistics (secondary, EU MT-usage context).
