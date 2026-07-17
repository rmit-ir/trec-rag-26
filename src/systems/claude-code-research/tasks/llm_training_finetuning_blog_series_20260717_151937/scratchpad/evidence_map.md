# Evidence map (docid → claims it supports)

## Intro / instruction tuning
- shard_02297_27511 — LMs trained on vast data acquire capabilities; must select desired behavior; RLHF "complex and often unstable"; DPO closed-form optimal policy via reward reparameterization, simple classification loss; DPO matches PPO-RLHF on sentiment/summarization/dialogue up to 6B; dynamic per-example importance weight prevents degeneration.
- shard_03213_29492 — instruction tuning = fine-tune on labeled instruction/output pairs; improves instruction-following in general.

## Post 1: LoRA
- shard_00142_71938 — full FT of GPT-3 175B instances prohibitively expensive; LoRA freezes pretrained model.
- shard_06287_78837 — freezes weights, injects rank-decomposition matrices A (n×r), B (r×n), r≪n; rank 1–4 works; output = W0x + b0 + BAx; low intrinsic rank / over-parameterized hypothesis; memory savings from gradients+optimizer state (Adam moments) only for trainable params; no additional inference latency.
- shard_02128_11561 — W0 frozen no gradient updates; h = W0x + BAx; A Gaussian init, B zero init so ΔW=0 at start; scaling of ΔWx by constant tied to r avoids hyperparameter retuning; batching-across-tasks limitation; on par or better than full FT on RoBERTa/DeBERTa/GPT-2/GPT-3 (WikiSQL, MNLI-m, SAMSum).
- shard_03425_78590 — LoRA "learns less and forgets less" vs full FT; theoretical basis open question.

## Post 2: QLoRA
- shard_06480_60449 — combines high-precision compute with low-precision storage.
- shard_05319_13195 — frozen 4-bit quantized base + trainable adapters; gradients backprop through quantized weights; NF4 / paged optimizers (GPU↔CPU transfers, memory spikes) / double quantization.
- shard_02429_75068 — NF4 information-theoretically optimal for normally distributed weights; DQ quantizes quantization constants; paged optimizers; 1,000+ models tuned; 33B/65B infeasible otherwise; Guanaco 99.3% of ChatGPT on Vicuna, 24h single GPU.
- shard_03832_7813 — double quantization: 8-bit floats, block size 256 for secondary quantization.
- shard_04199_71755 — storage NF4, compute BFloat16; double dequantization via constants c1, c2; NF4 QLoRA matches 16-bit full FT and 16-bit LoRA on benchmarks.
- shard_01738_69542 — hardware must support low-precision types/ops for gains.

## Post 3: RLHF
- shard_05247_62603 — trains reward model from human feedback, used as reward function to optimize policy via RL (PPO); feedback commonly = ranking outputs; "simple to judge but challenging to specify" (backflip, 900 bits); used for ChatGPT and Claude.
- shard_04363_73109 — RLHF stages: pretrain/fine-tune → human feedback (ranking/binary/graded) → reward model assigns scalar → PPO policy optimization; instability sources: complex reward signals, policy updates, variance in feedback; DPO overview ("secretly a reward model"); reparameterization removes baselines/normalization; no reward model training; "Is DPO always better" framing.
- shard_00131_66741 — Bradley-Terry p* = σ(r*(x,y_w) − r*(x,y_l)); substitution kills partition function; DPO higher reward than PPO at every KL (IMDb).
- shard_04253_66031 — r = rθ − λ·r_KL; KL penalty prevents drift + gibberish that fools reward model; PPO on-policy trust-region.
- shard_05083_46242 — reward model trained on ranked comparisons (helpful/harmless/honest criteria).
- shard_06503_49501 — RLAIF: preference data from AI labeler; constitution as ranking criteria; Pareto improvement over RLHF (helpfulness/harmlessness).

## Post 4: DPO
- shard_00100_16648 — Gibbs inequality: D_KL(πθ ‖ (1/Z)πref·e^{r/β}) minimized at 0 iff identical; Z intractable; reparameterize reward in terms of policy; Z cancels; NLL loss = supervised learning; avoids reward model, RL, sampling.
- shard_03753_15732 — r(x,y) = β·log πr(y|x)/πref(y|x) + β·log Z(x); substitute into BT, Z cancels; pipeline: sample y1,y2 ~ πref, label to D = {x, y_w, y_l}, minimize L_DPO given β.
- shard_00229_23100 — reward model NLL binary classification; π(y|x) policy notation; DPO reparameterizes BT to optimize LLM directly.
- shard_04137_30983 — successors: length-normalized reward (no reference model), target reward margin in BT objective.

## Selected but not fetched fully (snippets from logged searches)
shard_00299_52645 (LoRA cost motivation), shard_03435_60662 (NF4 detail).
