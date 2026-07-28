"""Build the committed-doc dataset: canonical text + jina-v5 doc embeddings.

Text source per (qid, docid): rubric-judge pool.json if present (same-qid),
else Pyserini fetch_doc (stdlib urllib; token from env). Embeddings: jina-v5
DOCUMENT encoding (task=retrieval, prompt_name=document, normalized, seq<=512)
— mirrors tasks/custom_index/scripts/encode_documents.py defaults.

Run in the custom_index env (has jina-v5 + einops + peft):
  PYTHONPATH=src uv run --project tasks/custom_index python \
    tasks/task-comparison/scripts/build_diversity_dataset.py

Artifacts -> data/task-comparison/diversity/{doc_text.jsonl, embeddings.npy,
docids.json, committed_map.json, build_report.json}
"""
from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path("/scratch/fast/kun/projects/trec-rag-26")
sys.path.insert(0, str(ROOT / "src"))
DIV = ROOT / "data/task-comparison/diversity"
POOL = ROOT / "data/task-comparison/rubric-judge/out/pool.json"
COMMITTED = Path("/tmp/committed_dev30.json")
MODEL = "jinaai/jina-embeddings-v5-text-nano"


def main():
    from utils.fetch_doc import fetch_doc

    DIV.mkdir(parents=True, exist_ok=True)
    committed = json.loads(COMMITTED.read_text())
    pool = json.loads(POOL.read_text())

    # (qid, docid) pairs; each docid unique to one qid here
    pairs = []
    for qid, engmap in committed.items():
        docs = set()
        for dl in engmap.values():
            docs.update(dl)
        for d in docs:
            pairs.append((qid, d))
    print(f"committed pairs: {len(pairs)}", flush=True)

    text: dict[str, str] = {}
    qid_of: dict[str, str] = {}
    to_fetch = []
    for qid, d in pairs:
        qid_of[d] = qid
        t = (pool.get(qid, {}).get(d) or {}).get("text")
        if t:
            text[d] = t
        else:
            to_fetch.append(d)
    print(f"from pool: {len(text)} | to fetch: {len(to_fetch)}", flush=True)

    failed = []

    def grab(docid):
        for _ in range(2):
            try:
                r = fetch_doc(docid)
                if r.get("text"):
                    return docid, r["text"]
            except Exception:
                continue
        return docid, None

    done = 0
    with ThreadPoolExecutor(max_workers=16) as ex:
        for docid, t in ex.map(grab, to_fetch):
            done += 1
            if t:
                text[docid] = t
            else:
                failed.append(docid)
            if done % 200 == 0:
                print(f"  fetched {done}/{len(to_fetch)} (failed {len(failed)})", flush=True)
    print(f"fetch done: {len(text)} have text, {len(failed)} failed", flush=True)

    # stable docid order = all docs WITH text
    docids = [d for _, d in pairs if d in text]
    docids = list(dict.fromkeys(docids))  # dedup, preserve order
    texts = [text[d] for d in docids]

    # write text before the heavy embed step (checkpoint)
    with open(DIV / "doc_text.jsonl", "w") as f:
        for d in docids:
            f.write(json.dumps({"docid": d, "qid": qid_of[d], "text": text[d]}) + "\n")
    (DIV / "docids.json").write_text(json.dumps(docids))
    (DIV / "committed_map.json").write_text(json.dumps(committed))

    # ---- embed (jina-v5 document mode) ----
    import numpy as np
    from sentence_transformers import SentenceTransformer

    print(f"loading {MODEL} ...", flush=True)
    model = SentenceTransformer(MODEL, device="cpu", trust_remote_code=True)
    model.max_seq_length = 512
    print("encoding", len(texts), "docs ...", flush=True)
    emb = model.encode(
        texts, batch_size=32, convert_to_numpy=True, show_progress_bar=True,
        normalize_embeddings=True, task="retrieval", prompt_name="document",
    ).astype(np.float32)
    np.save(DIV / "embeddings.npy", emb)

    report = {
        "n_pairs": len(pairs), "n_docids": len(docids),
        "n_from_pool": len(pairs) - len(to_fetch), "n_fetched": len(to_fetch) - len(failed),
        "n_failed": len(failed), "failed_docids": failed,
        "embed_model": MODEL, "dim": int(emb.shape[1]), "normalized": True,
        "task": "retrieval", "prompt_name": "document", "max_seq_len": 512,
    }
    (DIV / "build_report.json").write_text(json.dumps(report, indent=2))
    print("BUILD OK:", json.dumps({k: report[k] for k in
          ("n_docids", "n_from_pool", "n_fetched", "n_failed", "dim")}))


if __name__ == "__main__":
    main()
