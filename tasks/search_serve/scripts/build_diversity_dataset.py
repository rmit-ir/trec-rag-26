#!/usr/bin/env python3
"""Build the committed-document dataset (canonical text + jina-v5 embeddings)
for the cross-engine diversity analysis.

Deterministic build job. Mirrors the DENSE index encoding config exactly
(data/built-indexes/climbmix-full/encoding_meta.json):

  model=jinaai/jina-embeddings-v5-text-nano  dim=768  normalize=true
  max_seq_len=512  task=retrieval  prompt_name=document  dtype=bfloat16

Run inside the search_serve env (has jina-v5 + einops + peft + dotenv):

  uv run --project tasks/search_serve python \
      tasks/search_serve/scripts/build_diversity_dataset.py
"""
from __future__ import annotations

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np

sys.path.insert(0, "src")
from utils.fetch_doc import fetch_doc  # noqa: E402

ROOT = Path("/scratch/fast/kun/projects/trec-rag-26")
COMMITTED = Path("/tmp/committed_dev30.json")
POOL = ROOT / "data/task-comparison/rubric-judge/out/pool.json"
OUT_DIR = ROOT / "data/task-comparison/diversity"

MODEL = "jinaai/jina-embeddings-v5-text-nano"
DIM_EXPECTED = 768
MAX_SEQ_LEN = 512
TASK = "retrieval"
PROMPT_NAME = "document"
NORMALIZE = True
ENV_USED = "uv run --project tasks/search_serve"


def load_committed() -> dict:
    return json.loads(COMMITTED.read_text())


def collect_docid_qid(committed: dict) -> dict[str, str]:
    """docid -> qid (each docid appears under exactly one qid)."""
    m: dict[str, str] = {}
    for qid, engmap in committed.items():
        for _eng, docids in engmap.items():
            for d in docids:
                if d in m and m[d] != qid:
                    print(f"[warn] docid {d} under multiple qids: {m[d]} and {qid}",
                          flush=True)
                m[d] = qid
    return m


def build_text_map(docid_qid: dict[str, str]) -> tuple[dict[str, str], int, int, int, list[str]]:
    """Return (docid->text, n_from_pool, n_fetched, n_failed, failed_docids)."""
    pool = json.loads(POOL.read_text())
    text: dict[str, str] = {}
    from_pool = 0
    need_fetch: list[str] = []

    for docid, qid in docid_qid.items():
        pt = pool.get(qid, {}).get(docid, {}).get("text")
        if isinstance(pt, str) and pt:
            text[docid] = pt
            from_pool += 1
        else:
            need_fetch.append(docid)

    print(f"[text] from pool: {from_pool}  to fetch: {len(need_fetch)}", flush=True)

    def _fetch(docid: str) -> tuple[str, str | None]:
        try:
            r = fetch_doc(docid)
            t = r.get("text")
            if isinstance(t, str) and t:
                return docid, t
            return docid, None
        except Exception:
            # retry once
            try:
                r = fetch_doc(docid)
                t = r.get("text")
                if isinstance(t, str) and t:
                    return docid, t
                return docid, None
            except Exception as e:  # noqa: BLE001
                print(f"[fetch-fail] {docid}: {type(e).__name__}: {e}", flush=True)
                return docid, None

    fetched = 0
    failed_docids: list[str] = []
    done = 0
    with ThreadPoolExecutor(max_workers=16) as ex:
        futs = {ex.submit(_fetch, d): d for d in need_fetch}
        for fut in as_completed(futs):
            docid, t = fut.result()
            done += 1
            if t is not None:
                text[docid] = t
                fetched += 1
            else:
                failed_docids.append(docid)
            if done % 200 == 0:
                print(f"[fetch] {done}/{len(need_fetch)} "
                      f"(ok={fetched} fail={len(failed_docids)})", flush=True)

    print(f"[text] fetched: {fetched}  failed: {len(failed_docids)}", flush=True)
    return text, from_pool, fetched, len(failed_docids), sorted(failed_docids)


def load_model():
    import torch
    from sentence_transformers import SentenceTransformer

    print(f"[model] loading {MODEL} (cpu, bfloat16)…", flush=True)
    t0 = time.time()
    model = SentenceTransformer(
        MODEL, device="cpu", trust_remote_code=True,
        model_kwargs={"dtype": torch.bfloat16},
    )
    model.max_seq_length = MAX_SEQ_LEN
    print(f"[model] loaded in {time.time()-t0:.1f}s", flush=True)

    probe = model.encode(
        "probe", convert_to_numpy=True, normalize_embeddings=NORMALIZE,
        show_progress_bar=False, task=TASK, prompt_name=PROMPT_NAME,
    )
    dim = int(probe.shape[-1])
    print(f"[model] probed dim={dim}", flush=True)
    return model, dim


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    committed = load_committed()
    docid_qid = collect_docid_qid(committed)
    print(f"[load] {len(committed)} topics, {len(docid_qid)} unique docids", flush=True)

    text_map, n_from_pool, n_fetched, n_failed, failed_docids = build_text_map(docid_qid)

    # Deterministic row order: sorted docids that HAVE text.
    docids = sorted(d for d in docid_qid if d in text_map)
    print(f"[order] {len(docids)} docids with text (row order = sorted)", flush=True)

    model, dim = load_model()
    if dim != DIM_EXPECTED:
        print(f"[warn] probed dim {dim} != expected {DIM_EXPECTED}", flush=True)

    texts = [text_map[d] for d in docids]
    print(f"[encode] encoding {len(texts)} docs…", flush=True)
    t0 = time.time()
    embs = model.encode(
        texts, convert_to_numpy=True, normalize_embeddings=NORMALIZE,
        show_progress_bar=True, batch_size=32,
        task=TASK, prompt_name=PROMPT_NAME,
    ).astype(np.float32)
    print(f"[encode] done in {time.time()-t0:.1f}s  shape={embs.shape}", flush=True)

    # --- verify ---
    assert embs.shape[0] == len(docids), (embs.shape, len(docids))
    assert embs.shape[1] == dim, (embs.shape, dim)
    n_nan = int(np.isnan(embs).sum())
    row_norms = np.linalg.norm(embs, axis=1)
    n_zero_rows = int((row_norms == 0).sum())
    assert n_nan == 0, f"{n_nan} NaNs in embeddings"
    assert n_zero_rows == 0, f"{n_zero_rows} zero rows"
    if NORMALIZE:
        assert np.allclose(row_norms, 1.0, atol=1e-2), \
            f"norms not unit: min={row_norms.min()} max={row_norms.max()}"
    print(f"[verify] OK  nan={n_nan} zero_rows={n_zero_rows} "
          f"norm[min={row_norms.min():.4f} max={row_norms.max():.4f}]", flush=True)

    # --- persist ---
    doc_text_path = OUT_DIR / "doc_text.jsonl"
    with doc_text_path.open("w") as f:
        for d in docids:
            f.write(json.dumps(
                {"docid": d, "qid": docid_qid[d], "text": text_map[d]},
                ensure_ascii=False) + "\n")

    emb_path = OUT_DIR / "embeddings.npy"
    np.save(emb_path, embs)

    docids_path = OUT_DIR / "docids.json"
    docids_path.write_text(json.dumps(docids))

    committed_path = OUT_DIR / "committed_map.json"
    committed_path.write_text(json.dumps(committed))

    report = {
        "n_docids": len(docid_qid),
        "n_with_text": len(docids),
        "n_from_pool": n_from_pool,
        "n_fetched": n_fetched,
        "n_failed": n_failed,
        "failed_docids": failed_docids,
        "embed_model": MODEL,
        "dim": dim,
        "normalized": NORMALIZE,
        "max_seq_len": MAX_SEQ_LEN,
        "task": TASK,
        "prompt_name": PROMPT_NAME,
        "dtype": "bfloat16",
        "env_used": ENV_USED,
        "row_order": "sorted docids (docids.json)",
    }
    report_path = OUT_DIR / "build_report.json"
    report_path.write_text(json.dumps(report, indent=2))

    print("[done] artifacts:", flush=True)
    for p in (doc_text_path, emb_path, docids_path, committed_path, report_path):
        print("  ", p, flush=True)
    print("[report]", json.dumps({k: v for k, v in report.items()
                                  if k != "failed_docids"}), flush=True)


if __name__ == "__main__":
    main()
