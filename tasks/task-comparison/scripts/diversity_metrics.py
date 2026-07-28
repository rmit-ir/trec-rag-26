"""Diversity of COMMITTED docs across the 4 search backends, on 30 dev topics.

Embedding-based (jina-v5) metrics — NO LLM calls. Reads the build artifacts in
data/task-comparison/diversity/ (embeddings.npy, docids.json, committed_map.json).

Metrics (all cosine, rows L2-normalized defensively):
  Within-engine, per (topic, engine), then averaged over topics per engine:
    - n_docs
    - mean_pairwise_sim / mean_pairwise_dist (1 - sim)   ← spread / redundancy
    - nn_dup_rate   fraction of docs with >=1 near-twin (cos > DUP) in the set   ← "repeating"
    - vendi         effective # of distinct docs (exp entropy of sim-kernel eigs)
    - vendi_ratio   vendi / n_docs   ← normalized richness in [~1/n, 1]
  Cross-engine, per topic, then averaged:
    - jaccard[e1,e2]        committed docid-set overlap (low = complementary)
    - unique_contrib[e]     frac of e's docs with NO near-dup (cos>DUP) in the
                            union of the OTHER engines' committed docs  ← standout
    - union_vendi           vendi over the union of all engines' committed docs
    - vendi_gain[e]         union_vendi - vendi(e)   (diversity e adds to the whole)

Run:  uv run --no-project --with numpy python \
        tasks/task-comparison/scripts/diversity_metrics.py
Out:  data/task-comparison/diversity/diversity_metrics.{json,md}
"""
from __future__ import annotations

import json
from collections import defaultdict
from itertools import combinations
from pathlib import Path

import numpy as np

DIV = Path("/scratch/fast/kun/projects/trec-rag-26/data/task-comparison/diversity")
DUP = 0.90  # cosine >= DUP  => "near-duplicate"
ENGINES = ["dense", "keyword", "ssr", "lucene"]


def vendi(X: np.ndarray) -> float:
    """Vendi Score (linear/cosine kernel) = exp(Shannon entropy of the
    eigenvalues of the n x n normalized similarity gram K/n). X rows unit-norm.
    Returns effective number of distinct items in [1, n]."""
    n = X.shape[0]
    if n <= 1:
        return float(n)
    K = X @ X.T                      # cosine gram (rows already unit-norm)
    w = np.linalg.eigvalsh(K / n)    # eigenvalues sum to trace(K/n)=1
    w = w[w > 1e-12]
    w = w / w.sum()
    ent = -np.sum(w * np.log(w))
    return float(np.exp(ent))


def pairwise_stats(X: np.ndarray):
    """mean pairwise cosine sim, and near-dup rate (docs with a twin)."""
    n = X.shape[0]
    if n <= 1:
        return float("nan"), 0.0
    S = X @ X.T
    iu = np.triu_indices(n, k=1)
    sims = S[iu]
    mean_sim = float(sims.mean())
    # a doc is a near-dup if any OTHER doc has cos >= DUP
    np.fill_diagonal(S, -1.0)
    dup = (S.max(axis=1) >= DUP)
    return mean_sim, float(dup.mean())


def main():
    emb = np.load(DIV / "embeddings.npy").astype(np.float32)
    docids = json.loads((DIV / "docids.json").read_text())
    committed = json.loads((DIV / "committed_map.json").read_text())
    assert emb.shape[0] == len(docids), (emb.shape, len(docids))
    # L2-normalize defensively
    norms = np.linalg.norm(emb, axis=1, keepdims=True)
    emb = emb / np.clip(norms, 1e-12, None)
    row = {d: i for i, d in enumerate(docids)}

    def rows_for(dids):
        idx = [row[d] for d in dids if d in row]
        return emb[idx] if idx else np.zeros((0, emb.shape[1]), np.float32)

    within = defaultdict(list)          # engine -> list of per-topic metric dicts
    cross_jac = defaultdict(list)       # (e1,e2) -> [jaccard...]
    uniq_contrib = defaultdict(list)    # engine -> [frac...]
    vendi_gain = defaultdict(list)      # engine -> [gain...]
    union_vendis = []

    for qid, engmap in committed.items():
        Xby = {e: rows_for(engmap.get(e, [])) for e in ENGINES}
        setby = {e: set(engmap.get(e, [])) for e in ENGINES}

        # within-engine
        for e in ENGINES:
            X = Xby[e]
            n = X.shape[0]
            if n == 0:
                continue
            ms, dup = pairwise_stats(X)
            v = vendi(X)
            within[e].append(dict(n=n, mean_sim=ms, mean_dist=(1 - ms) if ms == ms else float("nan"),
                                  nn_dup_rate=dup, vendi=v, vendi_ratio=v / n))

        # cross: docid jaccard
        for e1, e2 in combinations(ENGINES, 2):
            a, b = setby[e1], setby[e2]
            if a or b:
                cross_jac[(e1, e2)].append(len(a & b) / len(a | b))

        # cross: embedding unique-contribution + union vendi/gain
        all_rows = np.vstack([Xby[e] for e in ENGINES if Xby[e].shape[0]])
        uv = vendi(all_rows)
        union_vendis.append(uv)
        for e in ENGINES:
            X = Xby[e]
            if X.shape[0] == 0:
                continue
            others = np.vstack([Xby[o] for o in ENGINES if o != e and Xby[o].shape[0]]) \
                if any(Xby[o].shape[0] for o in ENGINES if o != e) else np.zeros((0, emb.shape[1]), np.float32)
            if others.shape[0]:
                sim = X @ others.T                    # n_e x n_others
                is_unique = (sim.max(axis=1) < DUP)   # no near-dup among others
            else:
                is_unique = np.ones(X.shape[0], bool)
            uniq_contrib[e].append(float(is_unique.mean()))
            vendi_gain[e].append(uv - vendi(X))

    def avg(xs):
        xs = [x for x in xs if x == x]
        return sum(xs) / len(xs) if xs else float("nan")

    # aggregate within-engine
    agg = {}
    for e in ENGINES:
        rows = within[e]
        agg[e] = {k: avg([r[k] for r in rows]) for k in
                  ("n", "mean_sim", "mean_dist", "nn_dup_rate", "vendi", "vendi_ratio")}
        agg[e]["n_topics"] = len(rows)
        agg[e]["unique_contrib"] = avg(uniq_contrib[e])
        agg[e]["vendi_gain"] = avg(vendi_gain[e])

    out = {
        "params": {"dup_threshold": DUP, "engines": ENGINES, "n_topics": len(committed)},
        "within_engine": agg,
        "cross_engine_jaccard": {f"{a}|{b}": avg(v) for (a, b), v in cross_jac.items()},
        "union_vendi_mean": avg(union_vendis),
    }
    (DIV / "diversity_metrics.json").write_text(json.dumps(out, indent=2))

    # markdown
    L = []
    L.append("# Committed-doc diversity across backends (30 dev topics)\n")
    L.append(f"_Embeddings: jina-v5; cosine near-dup threshold = {DUP}; averaged over "
             f"{len(committed)} topics._\n")
    L.append("## Within-engine (per-topic mean)\n")
    L.append("| engine | docs/topic | mean pairwise dist | near-dup rate | Vendi | Vendi/n | unique-contrib | Vendi gain |")
    L.append("|---|--:|--:|--:|--:|--:|--:|--:|")
    for e in ENGINES:
        a = agg[e]
        L.append(f"| {e} | {a['n']:.1f} | {a['mean_dist']:.3f} | {a['nn_dup_rate']:.3f} "
                 f"| {a['vendi']:.2f} | {a['vendi_ratio']:.3f} | {a['unique_contrib']:.3f} | {a['vendi_gain']:.2f} |")
    L.append("\n- **mean pairwise dist** ↑ = more varied support; **near-dup rate** ↑ = more repetition.")
    L.append("- **Vendi/n** ↑ = committed docs are genuinely distinct (richer support); →1 ideal.")
    L.append("- **unique-contrib** ↑ = more docs no other engine (near-)surfaced (standout/complementary).")
    L.append("- **Vendi gain** ↑ = engine adds more diversity to the pooled union.\n")
    L.append(f"Union Vendi (all engines pooled, mean over topics): **{out['union_vendi_mean']:.2f}**\n")
    L.append("## Cross-engine committed-docid Jaccard (overlap; low = complementary)\n")
    L.append("| pair | Jaccard |")
    L.append("|---|--:|")
    for k, v in out["cross_engine_jaccard"].items():
        L.append(f"| {k} | {v:.3f} |")
    (DIV / "diversity_metrics.md").write_text("\n".join(L) + "\n")

    print("wrote", DIV / "diversity_metrics.json", "and .md")
    print("\nwithin-engine summary:")
    for e in ENGINES:
        a = agg[e]
        print(f"  {e:8} docs/t={a['n']:.1f} dist={a['mean_dist']:.3f} "
              f"dup={a['nn_dup_rate']:.3f} vendi/n={a['vendi_ratio']:.3f} "
              f"uniq={a['unique_contrib']:.3f}")


if __name__ == "__main__":
    main()
