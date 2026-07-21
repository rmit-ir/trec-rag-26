#!/usr/bin/env python3
"""Add RAGDoll-compatible reference text to TREC RAG output artifacts.

All input ``*.output.json`` artifacts are combined into one normalized JSONL
file in RAGDoll's answers schema. Each row gets a ``segments`` object mapping
every entry in ``references`` to its full shard text. Sentence citation indices
are preserved unchanged.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from utils.search_dense import DEFAULT_DENSE_URL, auth_headers  # noqa: E402

DEFAULT_PYSERINI_DOC_URL = "http://api.castorini.uwaterloo.ca/v1/climbmix-400b/doc"
DEFAULT_RAGDOLL_OUTPUT = (
    REPO_ROOT / "evaluation" / "ragdoll" / "results" / "aus-agent" / "answers.resolved.jsonl"
)


def load_repo_env() -> None:
    """Load simple KEY=VALUE entries without requiring python-dotenv."""
    env_file = REPO_ROOT / ".env"
    if not env_file.exists():
        return
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip("\"").strip("'")
        os.environ.setdefault(key.strip(), value)


def input_files(items: list[Path]) -> list[Path]:
    files: list[Path] = []
    for item in items:
        if item.is_dir():
            files.extend(sorted(item.glob("*.output.json")))
        elif item.name.endswith(".output.json"):
            files.append(item)
        else:
            raise ValueError(f"not an output artifact: {item}")
    return sorted(dict.fromkeys(path.resolve() for path in files))


def validate_row(row: dict[str, Any], path: Path) -> list[str]:
    references = row.get("references")
    answer = row.get("answer")
    if not isinstance(references, list) or not all(
        isinstance(item, str) and item for item in references
    ):
        raise ValueError(f"{path}: references must be a list of non-empty strings")
    if len(references) != len(set(references)):
        raise ValueError(f"{path}: references contains duplicate docids")
    if not isinstance(answer, list):
        raise ValueError(f"{path}: answer must be a list")
    for sentence_index, sentence in enumerate(answer):
        citations = sentence.get("citations") if isinstance(sentence, dict) else None
        if not isinstance(citations, list) or not all(isinstance(c, int) for c in citations):
            raise ValueError(f"{path}: answer[{sentence_index}].citations must be integer indices")
        for citation in citations:
            if citation < 0 or citation >= len(references):
                raise ValueError(
                    f"{path}: answer[{sentence_index}] citation {citation} is outside references"
                )
    return references


def collect_result_texts(value: Any, texts: dict[str, str]) -> None:
    """Recursively collect search-result ``docid``/``text`` pairs."""
    if isinstance(value, dict):
        results = value.get("results")
        if isinstance(results, list):
            for result in results:
                if not isinstance(result, dict):
                    continue
                docid, text = result.get("docid"), result.get("text")
                if isinstance(docid, str) and isinstance(text, str) and text.strip():
                    texts.setdefault(docid, text)
        for child in value.values():
            collect_result_texts(child, texts)
    elif isinstance(value, list):
        for child in value:
            collect_result_texts(child, texts)
    elif isinstance(value, str) and value.lstrip().startswith(("{", "[")):
        try:
            decoded, _ = json.JSONDecoder().raw_decode(value.lstrip())
        except json.JSONDecodeError:
            return
        collect_result_texts(decoded, texts)


def trajectory_texts(output_path: Path, trajectory_dir: Path | None) -> dict[str, str]:
    directory = trajectory_dir or output_path.parent
    suffix = ".output.json"
    stem = output_path.name[: -len(suffix)] if output_path.name.endswith(suffix) else output_path.stem
    trajectory = directory / f"{stem}.trajectory.json"
    if not trajectory.exists():
        return {}
    payload = json.loads(trajectory.read_text(encoding="utf-8"))
    texts: dict[str, str] = {}
    collect_result_texts(payload, texts)
    return texts


def ragdoll_row(row: dict[str, Any]) -> dict[str, Any]:
    """Normalize one resolved organizer row to RAGDoll's answers schema."""
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    qid = str(
        row.get("qid")
        or row.get("topic_id")
        or row.get("query_id")
        or metadata.get("narrative_id")
        or ""
    )
    if not qid:
        raise ValueError("cannot create RAGDoll row without a qid/narrative_id")
    query = str(
        row.get("query")
        or row.get("topic")
        or metadata.get("narrative")
        or metadata.get("title")
        or ""
    )
    run_id = str(row.get("run_id") or metadata.get("run_id") or metadata.get("team_id") or "")
    answer = row["answer"]
    answer_text = " ".join(str(sentence.get("text", "")) for sentence in answer).strip()
    return {
        "run_id": run_id,
        "qid": qid,
        "topic_id": qid,
        "query": query,
        "topic": query,
        "response_length": len(answer_text.split()),
        "answer_text": answer_text,
        "answer": answer,
        "references": row["references"],
        "segments": row["segments"],
    }


def fetch_batch(base_url: str, docids: list[str], timeout: float) -> dict[str, str]:
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/doc/batch",
        data=json.dumps({"docids": docids}).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "User-Agent": "trec-rag-reference-resolver/1.0",
            **auth_headers(),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"document API returned HTTP {exc.code}: {detail}") from exc
    docs = payload.get("docs")
    if not isinstance(docs, list):
        raise RuntimeError("document API response has no docs list")
    resolved: dict[str, str] = {}
    for doc in docs:
        if not isinstance(doc, dict):
            continue
        docid, text = doc.get("docid"), doc.get("text")
        if isinstance(docid, str) and isinstance(text, str) and text.strip():
            resolved[docid] = text
    return resolved


def fetch_one(doc_url: str, docid: str, token: str, timeout: float) -> tuple[str, str]:
    url = f"{doc_url.rstrip('/')}/{urllib.parse.quote(docid, safe='')}"
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": "trec-rag-reference-resolver/1.0",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{docid}: document API returned HTTP {exc.code}: {detail}") from exc
    raw = payload.get("doc") if isinstance(payload, dict) else None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return docid, raw
    if isinstance(raw, dict):
        for key in ("contents", "content", "text", "body", "segment"):
            text = raw.get(key)
            if isinstance(text, str) and text.strip():
                return docid, text
    if isinstance(payload, dict):
        for key in ("contents", "content", "text", "body", "segment"):
            text = payload.get(key)
            if isinstance(text, str) and text.strip():
                return docid, text
    raise RuntimeError(f"{docid}: document API returned no usable text")


def main() -> int:
    load_repo_env()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument(
        "--ragdoll-output",
        type=Path,
        default=DEFAULT_RAGDOLL_OUTPUT,
        help=f"Normalized RAGDoll answers JSONL (default: {DEFAULT_RAGDOLL_OUTPUT}).",
    )
    parser.add_argument(
        "--trajectory-dir",
        type=Path,
        help="Directory containing companion *.trajectory.json files (defaults to each input directory).",
    )
    parser.add_argument(
        "--api-base-url",
        help="Search service base URL providing POST /doc/batch.",
    )
    parser.add_argument(
        "--doc-url",
        default=os.environ.get("PYSERINI_DOC_URL", DEFAULT_PYSERINI_DOC_URL),
        help="Bearer-authenticated document endpoint; docid is appended to this URL.",
    )
    parser.add_argument("--token-env", default="PYSERINI_API_TOKEN")
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--batch-size", type=int, default=512)
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()
    if not 1 <= args.batch_size <= 4096:
        parser.error("--batch-size must be between 1 and 4096")

    try:
        files = input_files(args.inputs)
        if not files:
            parser.error("no *.output.json files found")
        rows: list[tuple[Path, dict[str, Any], list[str]]] = []
        unique_docids: list[str] = []
        seen: set[str] = set()
        for path in files:
            row = json.loads(path.read_text(encoding="utf-8"))
            references = validate_row(row, path)
            rows.append((path, row, references))
            for docid in references:
                if docid not in seen:
                    seen.add(docid)
                    unique_docids.append(docid)

        resolved: dict[str, str] = {}
        for path, _, _ in rows:
            resolved.update(trajectory_texts(path, args.trajectory_dir))
        unresolved = [docid for docid in unique_docids if docid not in resolved]
        print(
            f"resolved {len(unique_docids) - len(unresolved)}/{len(unique_docids)} "
            "from local trajectories",
            flush=True,
        )
        if unresolved and args.api_base_url:
            for start in range(0, len(unresolved), args.batch_size):
                batch = unresolved[start : start + args.batch_size]
                resolved.update(fetch_batch(args.api_base_url, batch, args.timeout))
                print(f"API fallback resolved {min(start + len(batch), len(unresolved))}/{len(unresolved)}")
        elif unresolved and os.environ.get(args.token_env, "").strip():
            token = os.environ.get(args.token_env, "").strip()
            with ThreadPoolExecutor(max_workers=args.workers) as executor:
                futures = {
                    executor.submit(fetch_one, args.doc_url, docid, token, args.timeout): docid
                    for docid in unresolved
                }
                for count, future in enumerate(as_completed(futures), start=1):
                    docid, text = future.result()
                    resolved[docid] = text
                    if count % 50 == 0 or count == len(unresolved):
                        print(f"API fallback resolved {count}/{len(unresolved)}", flush=True)
        missing = [docid for docid in unique_docids if docid not in resolved]
        if missing:
            preview = ", ".join(missing[:10])
            raise RuntimeError(f"{len(missing)} references were not resolved: {preview}")

        ragdoll_by_cell: dict[tuple[str, str], dict[str, Any]] = {}
        superseded = 0
        for path, row, references in rows:
            row["segments"] = {docid: resolved[docid] for docid in references}
            normalized = ragdoll_row(row)
            cell = (normalized["run_id"], normalized["qid"])
            if cell in ragdoll_by_cell:
                superseded += 1
                del ragdoll_by_cell[cell]
            ragdoll_by_cell[cell] = normalized
        ragdoll_rows = list(ragdoll_by_cell.values())
        args.ragdoll_output.parent.mkdir(parents=True, exist_ok=True)
        args.ragdoll_output.write_text(
            "".join(
                json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n"
                for item in ragdoll_rows
            ),
            encoding="utf-8",
        )
        print(
            f"wrote {len(ragdoll_rows)} RAGDoll answer rows with "
            f"{len(unique_docids)} unique references to {args.ragdoll_output}"
        )
        if superseded:
            print(f"deduplicated {superseded} older reruns by (run_id, qid); newest artifacts kept")
        return 0
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
