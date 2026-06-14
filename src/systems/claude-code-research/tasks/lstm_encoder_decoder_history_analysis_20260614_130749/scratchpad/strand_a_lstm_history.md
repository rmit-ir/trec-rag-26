# Strand A — The Historical Development of LSTMs and the RNN Lineage

*Research memo for a graduate "history of technology" seminar. Citations are inline; full bibliography with URLs/DOIs at the end. Where a source is a secondary/historical account rather than the original primary contribution, it is explicitly labeled "(secondary/historical account)".*

---

## 0. Overview of the lineage

The LSTM story is a single thread running through ~35 years of neural-network research: (i) early recurrent architectures that gave networks a temporal "memory" (Werbos, Jordan, Elman); (ii) the formal diagnosis that gradient-based training of such networks fails over long time lags (Hochreiter 1991; Bengio, Simard & Frasconi 1994); (iii) the LSTM architecture that engineered around that failure (Hochreiter & Schmidhuber 1997); (iv) a decade of architectural refinements (forget gate, peepholes, bidirectionality, the "vanilla" consolidation); (v) the deep-learning-era applications — CTC, handwriting, large-vocabulary speech, sequence generation, seq2seq — that made LSTMs the dominant sequence model of ~2013–2017; (vi) the simpler GRU competitor; and (vii) the displacement by the Transformer (2017) and a partial architectural resurgence (xLSTM, 2024).

---

## 1. Pre-history: recurrent nets and the long-range dependency problem

### 1.1 Backpropagation Through Time (Werbos, 1990)
**Citation:** Werbos, P. J. (1990). "Backpropagation through time: what it does and how to do it." *Proceedings of the IEEE*, 78(10), 1550–1560.
**Contribution:** Werbos formalized and popularized BPTT — the procedure of "unrolling" a recurrent network across time steps into an equivalent deep feedforward graph (with shared weights), then applying ordinary backpropagation to compute exact gradients of a loss with respect to all weights. (The underlying reverse-mode differentiation traces to Linnainmaa 1970 and Werbos's own earlier work; Werbos 1990 is the canonical RNN-training reference.)
**Why it mattered:** BPTT is the training algorithm whose failure mode the entire LSTM line was built to fix; it remains the standard method for training recurrent nets, and "unrolling" is the conceptual frame in which vanishing/exploding gradients are analyzed (Werbos, 1990).

### 1.2 Jordan networks (1986) and Elman / Simple Recurrent Networks (1990)
**Citation:** Elman, J. L. (1990). "Finding Structure in Time." *Cognitive Science*, 14(2), 179–211. (Builds explicitly on Jordan, M. I., 1986, "Serial order: A parallel distributed processing approach," UCSD ICS Report 8604.)
**Contribution:** Elman introduced the Simple Recurrent Network (SRN): a feedforward net augmented with a "context layer" that copies the hidden layer's activations from the previous time step and feeds them back as additional input, giving the network a dynamic, learned memory of recent inputs. Trained on temporally structured tasks (sequence prediction, simple language), the SRN discovered structure such as word boundaries and lexical-category clusters without being told they existed. Jordan's earlier variant fed back the *output* layer rather than the hidden layer (Elman, 1990; Jordan, 1986).
**Why it mattered:** Elman and Jordan established the practical RNN template — recurrence as feedback of state — and demonstrated that recurrent nets could learn temporal/linguistic structure, motivating the question of *how far back* such memory could reach.

### 1.3 Hochreiter's 1991 diploma thesis — the vanishing gradient problem (first analysis)
**Citation:** Hochreiter, S. (1991). *Untersuchungen zu dynamischen neuronalen Netzen* ["Investigations on dynamic neural networks"]. Diploma (master's) thesis, Institut für Informatik, Technische Universität München; supervised by Jürgen Schmidhuber.
**Contribution:** Hochreiter gave the first explicit analysis of what is now called the **vanishing (and exploding) gradient problem**: when error signals are backpropagated through time, they are repeatedly multiplied by weight/derivative factors, so the gradient either shrinks toward zero exponentially (vanishes) or blows up exponentially (explodes) as the time lag grows. The consequence is that standard gradient descent cannot learn dependencies spanning more than ~5–10 time steps. This analysis is the technical foundation later summarized in the 1997 LSTM paper (Hochreiter, 1991).
**Why it mattered:** It diagnosed precisely *why* the Elman/BPTT approach failed on long-range tasks, defining the problem statement LSTM was designed to solve. The thesis is in German and unpublished as a journal article; in English-language work it is almost always cited via the 1997 LSTM paper's review of it or via Hochreiter et al. (2001). *(I could not access the thesis full text directly to verify page-level claims — see "Verification notes" below.)*

### 1.4 Bengio, Simard & Frasconi (1994) — independent rigorous proof
**Citation:** Bengio, Y., Simard, P., & Frasconi, P. (1994). "Learning long-term dependencies with gradient descent is difficult." *IEEE Transactions on Neural Networks*, 5(2), 157–166.
**Contribution:** Independently of Hochreiter, this paper proved formally that gradient-based learning of long-term dependencies in RNNs is fundamentally hard: they showed a dilemma whereby for a recurrent system to *robustly store* information (latch a state against noise) the relevant Jacobian eigenvalues must have magnitude < 1, which is exactly the condition that makes gradients vanish exponentially over time. Thus robust long-term storage and efficient gradient-based learning are in tension. They also experimented with alternatives (simulated annealing, time-weighted pseudo-Newton) (Bengio, Simard & Frasconi, 1994).
**Why it mattered:** This is the peer-reviewed, theorem-backed statement of the long-term-dependency problem in the mainstream literature, and (together with Hochreiter 1991) the canonical "why RNNs fail" citation that motivated LSTM and, later, gradient clipping.

### 1.5 Later consolidation: Hochreiter et al. (2001)
**Citation (secondary/historical analysis):** Hochreiter, S., Bengio, Y., Frasconi, P., & Schmidhuber, J. (2001). "Gradient flow in recurrent nets: the difficulty of learning long-term dependencies." In S. C. Kremer & J. F. Kolen (Eds.), *A Field Guide to Dynamical Recurrent Neural Networks*. IEEE Press.
**Contribution:** A unifying book chapter (by the principals of both 1991 and 1994 analyses) that consolidates the vanishing/exploding-gradient analysis and surveys remedies. Useful as the English-language reference for Hochreiter's thesis results. Labeled here as a later analytical/review consolidation, not the original diagnosis.

---

## 2. The original LSTM (Hochreiter & Schmidhuber, 1997)

**Citation:** Hochreiter, S., & Schmidhuber, J. (1997). "Long Short-Term Memory." *Neural Computation*, 9(8), 1735–1780. DOI: 10.1162/neco.1997.9.8.1735. (A precursor appeared as Hochreiter & Schmidhuber, "LSTM can solve hard long time lag problems," *NIPS 9*, 1997.)
**Core technical contribution:** LSTM solves the vanishing-gradient problem by enforcing **constant error flow** through specially constructed memory cells. The central mechanism is the **Constant Error Carousel (CEC)**: each memory cell has a self-connected linear unit with a fixed weight of 1.0, so its activation (the cell state) is preserved unchanged across time steps and, crucially, error backpropagated through it neither vanishes nor explodes. Access to the CEC is regulated by multiplicative **gate units**: an **input gate** that protects the stored contents from irrelevant inputs, and an **output gate** that protects other units from the currently irrelevant memory contents. The original 1997 cell did *not* have a forget gate (so the CEC weight was a hard 1.0). They trained with a truncated, gradient-based algorithm and showed LSTM could bridge minimal time lags in excess of 1000 steps — far beyond what SRNs/BPTT, RTRL, Elman nets, or Neural Sequence Chunkers could manage (Hochreiter & Schmidhuber, 1997).
**Why it mattered historically:** This is the foundational architecture of the entire modern recurrent-sequence-modeling era. By engineering the gradient to be well-behaved over long lags rather than relying on a better optimizer, it made long-range sequence learning practical for the first time and introduced the gating idea that recurs in GRUs, highway/residual networks, and even gated attention.

---

## 3. Key architectural refinements (1999–2017)

### 3.1 The forget gate (Gers, Schmidhuber & Cummins, 2000)
**Citation:** Gers, F. A., Schmidhuber, J., & Cummins, F. (2000). "Learning to Forget: Continual Prediction with LSTM." *Neural Computation*, 12(10), 2451–2471. (First presented at ICANN 1999.)
**Contribution:** The original LSTM's cell state could only grow/accumulate; on long, continuous (non-reset) input streams the cell state could saturate and the network had no mechanism to release stored information. Gers et al. added a **forget gate** (originally "keep gate") that learns to multiplicatively reset or decay the CEC's self-recurrence, letting the cell flush its own state when it becomes irrelevant. The cell-state update became $c_t = f_t \odot c_{t-1} + i_t \odot \tilde{c}_t$ (Gers, Schmidhuber & Cummins, 2000).
**Why it mattered:** The forget gate is now considered an essential part of LSTM; it enabled stable learning on continuous/streaming sequences and is, per later ablations (Greff et al. 2017), one of the two most important components of the cell. Almost every "LSTM" used after ~2000 is really the forget-gate variant.

### 3.2 Peephole connections (Gers & Schmidhuber, 2000; Gers, Schraudolph & Schmidhuber, 2002)
**Citations:**
- Gers, F. A., & Schmidhuber, J. (2000). "Recurrent nets that time and count." *Proceedings of the IEEE-INNS-ENNS International Joint Conference on Neural Networks (IJCNN 2000)*, vol. 3, 189–194.
- Gers, F. A., Schraudolph, N. N., & Schmidhuber, J. (2002). "Learning Precise Timing with LSTM Recurrent Networks." *Journal of Machine Learning Research*, 3, 115–143.
**Contribution:** Added **peephole connections** — direct weighted links from the internal cell state (CEC) to the multiplicative input, forget, and output gates — so the gates can "see" the cell's current contents even when the output gate is closed. This let LSTM learn tasks requiring **precise timing and counting** of intervals between events, which the gate-blind version could not do (Gers, Schraudolph & Schmidhuber, 2002).
**Why it mattered:** Peephole LSTM became a standard variant (e.g., in influential Google speech models), extending LSTM to fine-grained temporal/rhythmic tasks. Notably, Greff et al. (2017) later found peepholes *not* critical for most tasks — a nice example of an early refinement that the field eventually pruned.

### 3.3 Bidirectional LSTM (Graves & Schmidhuber, 2005)
**Citation:** Graves, A., & Schmidhuber, J. (2005). "Framewise phoneme classification with bidirectional LSTM and other neural network architectures." *Neural Networks*, 18(5–6), 602–610. (Companion: Graves, Fernández & Schmidhuber, "Bidirectional LSTM Networks for Improved Phoneme Classification and Recognition," ICANN 2005.)
**Contribution:** Combined LSTM with the bidirectional-RNN idea (Schuster & Paliwal, 1997): run one LSTM forward over the sequence and a second LSTM backward, concatenating both hidden states so each output has access to **both past and future context**. They also introduced a full-gradient (untruncated) version of the LSTM learning algorithm. On the TIMIT phoneme-classification benchmark BLSTM outperformed unidirectional LSTM, standard RNNs, and HMM baselines (Graves & Schmidhuber, 2005).
**Why it mattered:** BLSTM became the default for offline sequence-labeling tasks (speech, handwriting, NLP tagging) where the whole input is available, and was a building block of the CTC handwriting/speech systems and later of ELMo-style contextual embeddings.

### 3.4 The "vanilla LSTM" consolidation (Greff et al., 2017)
**Citation:** Greff, K., Srivastava, R. K., Koutník, J., Steunebrink, B. R., & Schmidhuber, J. (2017). "LSTM: A Search Space Odyssey." *IEEE Transactions on Neural Networks and Learning Systems*, 28(10), 2222–2232. (arXiv:1503.04069, 2015.)
**Contribution:** The first large-scale, systematic ablation of LSTM. The authors define the **"vanilla LSTM"** — the now-standard cell with input/forget/output gates, block input, a single CEC cell, output activation, and peephole connections — and evaluate eight variants across ~5400 experiments on speech, handwriting, and polyphonic-music tasks. Key findings: (a) no variant reliably beats the standard cell; (b) the **forget gate** and the **output activation function** are the most critical components; (c) coupling input and forget gates (CIFG, the GRU-like simplification) and removing peepholes simplify the model without significant loss (Greff et al., 2017).
**Why it mattered:** It canonized "the" LSTM that practitioners actually use, settling years of architectural variation, and provided empirical justification for the simplifications (drop peepholes, couple gates) that frameworks adopted as defaults. Labeled partly secondary in spirit (a survey/ablation) but it is itself a primary peer-reviewed empirical contribution.

---

## 4. Deep-learning-era breakthroughs that made LSTM dominant

### 4.1 Connectionist Temporal Classification (Graves et al., 2006)
**Citation:** Graves, A., Fernández, S., Gomez, F., & Schmidhuber, J. (2006). "Connectionist Temporal Classification: Labelling Unsegmented Sequence Data with Recurrent Neural Networks." *Proceedings of the 23rd International Conference on Machine Learning (ICML 2006)*, 369–376.
**Contribution:** CTC is an output layer + loss function that lets a recurrent net (typically BLSTM) be trained directly on **unsegmented** sequences — mapping an input frame sequence to a shorter label sequence without requiring a pre-aligned, frame-by-frame target. It introduces a "blank" symbol and sums over all possible alignments via a forward–backward dynamic program, making the whole pipeline end-to-end differentiable (Graves et al., 2006).
**Why it mattered:** CTC removed the need for HMM-style forced alignment, enabling end-to-end LSTM speech and handwriting recognition. It is the conceptual basis of "end-to-end" sequence recognition and is still used in modern ASR.

### 4.2 Handwriting recognition (Graves et al., 2009)
**Citation:** Graves, A., Liwicki, M., Fernández, S., Bertolami, R., Bunke, H., & Schmidhuber, J. (2009). "A Novel Connectionist System for Unconstrained Handwriting Recognition." *IEEE Transactions on Pattern Analysis and Machine Intelligence (TPAMI)*, 31(5), 855–868.
**Contribution:** A multidimensional BLSTM + CTC system that recognized unconstrained online and offline handwriting end-to-end, winning multiple ICDAR handwriting competitions and beating HMM-based state of the art (Graves et al., 2009).
**Why it mattered:** This was one of the first high-profile, competition-winning demonstrations that LSTM-based systems beat the dominant HMM paradigm on a real-world task — an early proof point for deep recurrent nets.

### 4.3 Sequence generation (Graves, 2013)
**Citation:** Graves, A. (2013). "Generating Sequences With Recurrent Neural Networks." arXiv:1308.0850.
**Contribution:** Showed that deep LSTM networks trained as autoregressive next-step predictors can **generate** complex sequences with long-range structure — character-level text (including Wikipedia) and, strikingly, realistic online handwriting, the latter via a mixture-density output and a differentiable attention-like window mechanism for conditional ("write this text in handwriting") generation (Graves, 2013).
**Why it mattered:** A landmark demonstration of generative sequence modeling with LSTMs; it popularized character-level RNN language models, mixture density network outputs for RNNs, and an early soft-attention mechanism, directly influencing later neural-attention work.

### 4.4 Large-vocabulary / large-scale speech recognition (Sak, Senior & Beaufays, 2014)
**Citation:** Sak, H., Senior, A., & Beaufays, F. (2014). "Long Short-Term Memory Recurrent Neural Network Architectures for Large Scale Acoustic Modeling." *Proc. INTERSPEECH 2014*, 338–342. (Closely related arXiv:1402.1128, "Long Short-Term Memory Based Recurrent Neural Network Architectures for Large Vocabulary Speech Recognition.")
**Contribution:** Introduced the **LSTMP** architecture — an LSTM with a separate linear **recurrent projection layer** that shrinks the recurrent dimensionality, giving more modeling power per parameter — and reported the first distributed training of LSTM RNN acoustic models via asynchronous SGD across a large machine cluster. These LSTM/LSTMP acoustic models outperformed deep feedforward networks (DNNs) for large-vocabulary speech recognition (Sak, Senior & Beaufays, 2014).
**Why it mattered:** This put LSTMs into production-scale speech recognition at Google and helped trigger broad industry adoption (Google, Microsoft, IBM, Apple, Amazon) of LSTM acoustic/language models in the mid-2010s — the period when LSTM became the de facto industrial sequence model.

### 4.5 Regularization / making big LSTMs trainable (Pascanu et al. 2013; Zaremba et al. 2014)
**Citations:**
- Pascanu, R., Mikolov, T., & Bengio, Y. (2013). "On the difficulty of training recurrent neural networks." *ICML 2013*, PMLR 28, 1310–1318 (arXiv:1211.5063, 2012). *Contribution:* revisited vanishing/exploding gradients, characterized the error-surface "cliffs," and proposed **gradient-norm clipping** for exploding gradients plus a regularizer for vanishing gradients — the now-standard practical fixes for training RNNs.
- Zaremba, W., Sutskever, I., & Vinyals, O. (2014). "Recurrent Neural Network Regularization." arXiv:1409.2329. *Contribution:* showed how to apply **dropout correctly to LSTMs** — only on the non-recurrent (feedforward) connections, leaving the recurrent CEC path untouched — substantially reducing overfitting and setting new state-of-the-art on Penn Treebank language modeling, speech, and translation.
**Why they mattered:** Together these made large, deep LSTM language models trainable and reliable at scale, a precondition for the LSTM-dominant period of ~2014–2017.

### 4.6 Sequence-to-sequence learning (Sutskever, Vinyals & Le, 2014)
**Citation:** Sutskever, I., Vinyals, O., & Le, Q. V. (2014). "Sequence to Sequence Learning with Neural Networks." *Advances in Neural Information Processing Systems 27 (NeurIPS 2014)* (arXiv:1409.3215).
**Contribution:** A deep multi-layer LSTM **encoder** reads the source sentence into a fixed-length vector; a second LSTM **decoder** generates the target sentence from that vector — a general, end-to-end mapping from one variable-length sequence to another. They achieved strong English→French machine-translation results and found that reversing the source word order dramatically improved performance (Sutskever, Vinyals & Le, 2014).
**Why it mattered:** Seq2seq made LSTM the backbone of neural machine translation and, more broadly, of all encoder–decoder sequence transduction (summarization, dialogue, speech). Its fixed-vector bottleneck directly motivated the attention mechanism (Bahdanau et al. 2015), which in turn led to the Transformer.

---

## 5. The simpler competitor: GRU (Cho et al., 2014)

**Citation:** Cho, K., van Merriënboer, B., Gulcehre, C., Bahdanau, D., Bougares, F., Schwenk, H., & Bengio, Y. (2014). "Learning Phrase Representations using RNN Encoder–Decoder for Statistical Machine Translation." *Proc. EMNLP 2014*, 1724–1734 (arXiv:1406.1078).
**Contribution:** Introduced the **RNN Encoder–Decoder** framework for MT and, within it, the **Gated Recurrent Unit (GRU)** — a simplified gated cell with only two gates (a **reset gate** and an **update gate**) and **no separate memory cell / output gate**; the update gate interpolates between the previous hidden state and a candidate state. GRU has fewer parameters than LSTM while retaining gated control of information flow (Cho et al., 2014).
**Why it mattered:** GRU became the principal lightweight alternative to LSTM; empirical studies (Chung et al. 2014; Greff et al. 2017) found it competitive with LSTM on many tasks at lower cost, and it remains widely used. The same paper's encoder–decoder framing also seeded the attention/NMT line.

---

## 6. Decline (Transformers) and partial resurgence (xLSTM)

### 6.1 The Transformer (Vaswani et al., 2017)
**Citation:** Vaswani, A., Shazeer, N., Parmar, N., Uszkoreit, J., Jones, L., Gomez, A. N., Kaiser, Ł., & Polosukhin, I. (2017). "Attention Is All You Need." *Advances in Neural Information Processing Systems 30 (NeurIPS 2017)* (arXiv:1706.03762).
**Contribution:** Dispensed with recurrence entirely, replacing it with **self-attention**. Because attention processes all positions in parallel (rather than stepping through time), Transformers train far faster on modern hardware and model long-range dependencies directly via attention weights, avoiding the sequential bottleneck and residual gradient difficulties of RNNs (Vaswani et al., 2017).
**Why it mattered (for this story):** The Transformer's parallelism and scaling behavior made it strictly preferable to LSTM for large-scale language modeling, and by ~2018–2020 it had displaced LSTM as the dominant sequence architecture (BERT, GPT). This marks the end of the LSTM-dominant era.

### 6.2 Partial resurgence: xLSTM (Beck et al., 2024)
**Citation:** Beck, M., Pöppel, K., Spanring, M., Auer, A., Prudnikova, O., Kopp, M., Klambauer, G., Brandstetter, J., & Hochreiter, S. (2024). "xLSTM: Extended Long Short-Term Memory." *NeurIPS 2024* (arXiv:2405.04517).
**Contribution:** Revisits LSTM with two upgrades aimed at closing the gap with Transformers: **exponential gating** (with normalization/stabilization) and modified memory structures — **sLSTM** (scalar memory, new memory-mixing) and **mLSTM** (a fully parallelizable matrix memory with a covariance update rule), stacked into residual xLSTM blocks. The authors report performance competitive with state-of-the-art Transformers and state-space models (e.g., Mamba) at scale, with linear-in-sequence-length compute and constant memory for inference (Beck et al., 2024).
**Why it mattered:** Led by Sepp Hochreiter (co-inventor of the original LSTM), xLSTM is the most prominent attempt to make the recurrent/gated lineage competitive again in the Transformer era — a notable bookend to the 1997 paper.

---

## 7. Compact timeline

| Year | Milestone | Key authors |
|---|---|---|
| 1986 | Jordan network (output-feedback RNN) | Jordan |
| 1990 | Backpropagation Through Time, formalized | Werbos |
| 1990 | Simple Recurrent Network (SRN) | Elman |
| 1991 | First vanishing-gradient analysis (diploma thesis) | Hochreiter (sup. Schmidhuber) |
| 1994 | Formal proof: long-term deps. hard with gradient descent | Bengio, Simard & Frasconi |
| 1997 | **LSTM** — CEC, input/output gates | Hochreiter & Schmidhuber |
| 2000 | **Forget gate** | Gers, Schmidhuber & Cummins |
| 2000/2002 | **Peephole connections** | Gers, Schmidhuber, (Schraudolph) |
| 2005 | **Bidirectional LSTM** | Graves & Schmidhuber |
| 2006 | **CTC** loss for unsegmented labeling | Graves, Fernández, Gomez & Schmidhuber |
| 2009 | Handwriting recognition (BLSTM+CTC, TPAMI) | Graves et al. |
| 2013 | Gradient clipping for RNNs (ICML) | Pascanu, Mikolov & Bengio |
| 2013 | Sequence generation with LSTM | Graves |
| 2014 | **GRU** / RNN Encoder–Decoder | Cho et al. |
| 2014 | Seq2seq learning | Sutskever, Vinyals & Le |
| 2014 | LSTM dropout regularization | Zaremba, Sutskever & Vinyals |
| 2014 | Large-scale LSTM acoustic models (LSTMP) | Sak, Senior & Beaufays |
| 2015/2017 | "Vanilla LSTM" ablation / consolidation | Greff et al. |
| 2017 | **Transformer** (displacement) | Vaswani et al. |
| 2024 | **xLSTM** (resurgence) | Beck et al. (Hochreiter) |

*(Secondary/historical syntheses for context: Schmidhuber 2015; Hochreiter et al. 2001 — see Sources.)*

---

## Verification notes (claims not fully verified against primary full text)

- **Hochreiter (1991) thesis:** verified existence, title, institution (TU München), supervisor (Schmidhuber), and 1991 date via multiple secondary sources (Google Scholar, Schmidhuber's own pages, NeurIPS references). I did **not** read the German full text, so specific in-thesis page/equation claims rest on the 1997 LSTM paper's review of it and standard secondary accounts.
- **Jordan (1986):** cited via Elman (1990) and standard references; I did not retrieve the original 1986 ICS technical report.
- **Gers, Schmidhuber & Cummins (2000) "keep gate" terminology** and the **2000 IJCNN "Recurrent nets that time and count"** peephole-precursor are verified via JMLR 2002, IDSIA, and NASA ADS listings; exact page numbers for the IJCNN 2000 paper (vol. 3) should be double-checked against the proceedings.
- **Sak, Senior & Beaufays (2014):** there are two closely related 2014 works — the INTERSPEECH paper (LSTMP, distributed ASGD) and arXiv:1402.1128 (large-vocabulary). Both are by the same authors in 2014; the memo cites the INTERSPEECH one as the primary "large scale acoustic modeling" reference and notes the arXiv companion. Page numbers (338–342) are from the ISCA archive listing.
- All arXiv IDs, journal volumes/issues/pages, and venues for items in §2–§6 were cross-checked against publisher/arXiv listings during research and are believed accurate.

---

## Sources

1. Werbos, P. J. (1990). Backpropagation through time: what it does and how to do it. *Proceedings of the IEEE*, 78(10), 1550–1560. https://ieeexplore.ieee.org/document/58337 (PDF: https://www.werbos.com/Neural/BTT.pdf)
2. Jordan, M. I. (1986). Serial order: A parallel distributed processing approach. ICS Report 8604, UCSD. (cited via Elman 1990)
3. Elman, J. L. (1990). Finding Structure in Time. *Cognitive Science*, 14(2), 179–211. DOI: 10.1207/s15516709cog1402_1. https://onlinelibrary.wiley.com/doi/abs/10.1207/s15516709cog1402_1 (PDF: https://jontalle.web.engr.illinois.edu/Public/Elman-FindingStructureinTime.90.pdf)
4. Hochreiter, S. (1991). *Untersuchungen zu dynamischen neuronalen Netzen.* Diploma thesis, Institut für Informatik, Technische Universität München. https://www.researchgate.net/publication/243781690_Untersuchungen_zu_dynamischen_neuronalen_Netzen
5. Bengio, Y., Simard, P., & Frasconi, P. (1994). Learning long-term dependencies with gradient descent is difficult. *IEEE Transactions on Neural Networks*, 5(2), 157–166. DOI: 10.1109/72.279181.
6. Hochreiter, S., Bengio, Y., Frasconi, P., & Schmidhuber, J. (2001). Gradient flow in recurrent nets: the difficulty of learning long-term dependencies. In Kremer & Kolen (Eds.), *A Field Guide to Dynamical Recurrent Neural Networks.* IEEE Press. *(secondary/historical analysis)*
7. Hochreiter, S., & Schmidhuber, J. (1997). Long Short-Term Memory. *Neural Computation*, 9(8), 1735–1780. DOI: 10.1162/neco.1997.9.8.1735. https://dl.acm.org/doi/10.1162/neco.1997.9.8.1735 (PDF: https://www.bioinf.jku.at/publications/older/2604.pdf)
8. Gers, F. A., Schmidhuber, J., & Cummins, F. (2000). Learning to Forget: Continual Prediction with LSTM. *Neural Computation*, 12(10), 2451–2471. DOI: 10.1162/089976600300015015.
9. Gers, F. A., & Schmidhuber, J. (2000). Recurrent nets that time and count. *Proc. IJCNN 2000*, vol. 3, 189–194. https://ui.adsabs.harvard.edu/abs/2000ijcn....3...32G/abstract (PDF: https://sferics.idsia.ch/pub/juergen/TimeCount-IJCNN2000.pdf)
10. Gers, F. A., Schraudolph, N. N., & Schmidhuber, J. (2002). Learning Precise Timing with LSTM Recurrent Networks. *Journal of Machine Learning Research*, 3, 115–143. https://www.jmlr.org/papers/volume3/gers02a/gers02a.pdf
11. Graves, A., & Schmidhuber, J. (2005). Framewise phoneme classification with bidirectional LSTM and other neural network architectures. *Neural Networks*, 18(5–6), 602–610. DOI: 10.1016/j.neunet.2005.06.042. (PDF: https://www.cs.toronto.edu/~graves/ijcnn_2005.pdf)
12. Graves, A., Fernández, S., Gomez, F., & Schmidhuber, J. (2006). Connectionist Temporal Classification: Labelling Unsegmented Sequence Data with Recurrent Neural Networks. *Proc. ICML 2006*, 369–376. DOI: 10.1145/1143844.1143891. (PDF: https://www.cs.toronto.edu/~graves/icml_2006.pdf)
13. Graves, A., Liwicki, M., Fernández, S., Bertolami, R., Bunke, H., & Schmidhuber, J. (2009). A Novel Connectionist System for Unconstrained Handwriting Recognition. *IEEE TPAMI*, 31(5), 855–868. DOI: 10.1109/TPAMI.2008.137.
14. Pascanu, R., Mikolov, T., & Bengio, Y. (2013). On the difficulty of training recurrent neural networks. *ICML 2013*, PMLR 28, 1310–1318. arXiv:1211.5063. https://arxiv.org/abs/1211.5063
15. Graves, A. (2013). Generating Sequences With Recurrent Neural Networks. arXiv:1308.0850. https://arxiv.org/abs/1308.0850
16. Cho, K., van Merriënboer, B., Gulcehre, C., Bahdanau, D., Bougares, F., Schwenk, H., & Bengio, Y. (2014). Learning Phrase Representations using RNN Encoder–Decoder for Statistical Machine Translation. *Proc. EMNLP 2014*, 1724–1734. arXiv:1406.1078. https://aclanthology.org/D14-1179 / https://arxiv.org/abs/1406.1078
17. Sutskever, I., Vinyals, O., & Le, Q. V. (2014). Sequence to Sequence Learning with Neural Networks. *NeurIPS 27*. arXiv:1409.3215. https://arxiv.org/abs/1409.3215
18. Zaremba, W., Sutskever, I., & Vinyals, O. (2014). Recurrent Neural Network Regularization. arXiv:1409.2329. https://arxiv.org/abs/1409.2329
19. Sak, H., Senior, A., & Beaufays, F. (2014). Long Short-Term Memory Recurrent Neural Network Architectures for Large Scale Acoustic Modeling. *Proc. INTERSPEECH 2014*, 338–342. https://www.isca-archive.org/interspeech_2014/sak14_interspeech.html (companion: arXiv:1402.1128, https://arxiv.org/abs/1402.1128)
20. Greff, K., Srivastava, R. K., Koutník, J., Steunebrink, B. R., & Schmidhuber, J. (2017). LSTM: A Search Space Odyssey. *IEEE TNNLS*, 28(10), 2222–2232. DOI: 10.1109/TNNLS.2016.2582924. arXiv:1503.04069. https://arxiv.org/abs/1503.04069
21. Schmidhuber, J. (2015). Deep Learning in Neural Networks: An Overview. *Neural Networks*, 61, 85–117. DOI: 10.1016/j.neunet.2014.09.003. arXiv:1404.7828. *(secondary/historical survey)* https://arxiv.org/abs/1404.7828
22. Vaswani, A., Shazeer, N., Parmar, N., Uszkoreit, J., Jones, L., Gomez, A. N., Kaiser, Ł., & Polosukhin, I. (2017). Attention Is All You Need. *NeurIPS 30*. arXiv:1706.03762. https://arxiv.org/abs/1706.03762
23. Beck, M., Pöppel, K., Spanring, M., Auer, A., Prudnikova, O., Kopp, M., Klambauer, G., Brandstetter, J., & Hochreiter, S. (2024). xLSTM: Extended Long Short-Term Memory. *NeurIPS 2024.* arXiv:2405.04517. https://arxiv.org/abs/2405.04517
24. Schuster, M., & Paliwal, K. K. (1997). Bidirectional Recurrent Neural Networks. *IEEE Transactions on Signal Processing*, 45(11), 2673–2681. *(primary source for the bidirectional idea adapted by Graves & Schmidhuber 2005)*
