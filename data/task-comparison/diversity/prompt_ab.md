# Prompt A/B — default vs firsthand (10 dev topics)

_Same 10 topics, backends (semantic,keyword), model. Cross-arm committed-docid Jaccard = **0.109** (how much the two prompts commit the SAME docs)._

| metric | default | firsthand | Δ (first−def) |
|---|--:|--:|--:|
| committed docs/topic | 14.5 | 14.1 | -0.4 |
| **primary-source rate** | 0.171 | 0.161 | -0.010 |
| mean source_type (0-2) | 0.424 | 0.373 | -0.051 |
| mean UMBRELA | 1.835 | 1.746 | -0.089 |
| low-rel rate (≤1) | 0.173 | 0.206 | +0.033 |
| committed rubric cov(≥1) | 0.797 | 0.704 | -0.093 |
| **answer** cov(≥1) | 0.765 | 0.777 | +0.012 |
| answer cov(full) | 0.557 | 0.537 | -0.020 |
| **answer overall** (0-3) | 2.000 | 2.200 | +0.200 |

- **primary-source rate** ↑ under firsthand = the variant did shift committed docs toward first-hand/original sources (its intent).
- Watch **answer overall / cov** for whether that shift helped, hurt, or was neutral to the final answer.
- Low **cross-arm Jaccard** = the prompt materially changed which docs get committed (not just reordered).

