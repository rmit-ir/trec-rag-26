"""TREC RAG 2026 output object + run persistence — the ``*.output.json`` half.

``build_rag_output`` produces the organizer-facing fields from the track's
``rag-task.md`` (see skills/trec-rag-2026-track-guidelines/references):

    {
      "metadata": {team_id, narrative_id, narrative, run_id, run_desc},
      "references": ["<climbmix docid>", ...],   # only docids cited by answer
      "answer": [{"text": "<sentence>", "citations": [0, 1]}, ...]
    }

``save_run`` embeds the rich execution trace at top-level ``output.trace`` for
internal analysis. Use ``submission_output`` to strip it when creating the
official JSONL.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Australia/Melbourne")

TEAM_ID = "rmit-ir"  # default; override per run if needed

# Repo root = parents[2] of src/ragrun/outputs.py (src-layout, installed
# editable, so __file__ stays inside the checkout).
_REPO_ROOT = Path(__file__).resolve().parents[2]


def data_dir() -> Path:
    """Root data dir (override with RAGRUN_DATA_DIR)."""
    return Path(os.environ.get("RAGRUN_DATA_DIR", _REPO_ROOT / "data"))


def run_timestamp(now: datetime | None = None) -> str:
    """Filesystem-safe compact ISO 8601 stamp in Melbourne local time with
    offset, e.g. ``20260716T163259123456+1000`` (``+1100`` during AEDT).

    Note: the ``+`` must be percent-encoded (``%2B``) when the id appears in a
    URL path segment.
    """
    now = now or datetime.now(TZ)
    return now.strftime("%Y%m%dT%H%M%S%f%z")


def query_slug(query: str, n_words: int = 5) -> str:
    """First ``n_words`` of the query, sanitised: ``write_a_blog_post_contrasting``."""
    words = re.findall(r"[A-Za-z0-9]+", query.lower())[:n_words]
    return "_".join(words) or "query"


def build_rag_output(*, narrative_id: str, narrative: str, run_id: str,
                     run_desc: str, references: list[str],
                     answer: list[dict[str, Any]],
                     team_id: str = TEAM_ID) -> dict[str, Any]:
    """Assemble one TREC RAG 2026 output object (no extra metadata keys)."""
    return {
        "metadata": {
            "team_id": team_id,
            "narrative_id": narrative_id,
            "narrative": narrative,
            "run_id": run_id,
            "run_desc": run_desc,
        },
        "references": list(references),
        "answer": answer,
    }


def submission_output(obj: dict[str, Any]) -> dict[str, Any]:
    """Return the exact organizer-facing projection, excluding ``trace``."""
    return {
        "metadata": dict(obj["metadata"]),
        "references": list(obj["references"]),
        "answer": [
            {"text": sentence["text"],
             "citations": list(sentence["citations"])}
            for sentence in obj["answer"]
        ],
    }


def validate_rag_output(obj: dict[str, Any]) -> list[str]:
    """Return a list of violations of the track's answer/validation rules
    (empty list = valid). Mirrors rag-task.md."""
    errs: list[str] = []
    meta = obj.get("metadata")
    if not isinstance(meta, dict):
        errs.append("metadata missing or not an object")
        meta = {}
    required = {"team_id", "narrative_id", "narrative", "run_id", "run_desc"}
    missing = required - meta.keys()
    if missing:
        errs.append(f"metadata missing keys: {sorted(missing)}")
    extra = meta.keys() - required
    if extra:
        errs.append(f"metadata has extra keys (not allowed): {sorted(extra)}")

    refs = obj.get("references")
    answer = obj.get("answer")
    if not isinstance(refs, list) or not all(isinstance(r, str) for r in refs):
        errs.append("references must be a list of docid strings")
        refs = []
    if not isinstance(answer, list) or not answer:
        errs.append("answer must be a non-empty list")
        answer = []

    cited: set[int] = set()
    total_words = 0
    for i, sent in enumerate(answer):
        if not isinstance(sent, dict) or "text" not in sent or "citations" not in sent:
            errs.append(f"answer[{i}] must have 'text' and 'citations'")
            continue
        total_words += len(sent["text"].split())
        cits = sent["citations"]
        if not isinstance(cits, list) or len(cits) > 3:
            errs.append(f"answer[{i}].citations must be a list of at most 3 indices")
            continue
        for c in cits:
            if not isinstance(c, int) or not (0 <= c < len(refs)):
                errs.append(f"answer[{i}] cites invalid reference index {c!r}")
            else:
                cited.add(c)
    if total_words > 1024:
        errs.append(f"answer is {total_words} words (max 1024)")
    uncited = set(range(len(refs))) - cited
    if uncited:
        errs.append(f"references never cited: indices {sorted(uncited)}")
    return errs


def save_run(system_name: str, query: str, *, trajectory: dict[str, Any],
             output: dict[str, Any], timestamp: str | None = None,
             validate: bool = True) -> dict[str, Path]:
    """Persist the two run artifacts; returns their paths.

    Writes ``data/outputs/<system_name>/<ts>.<slug>.trajectory.json`` and
    ``...output.json``. With ``validate=True`` (default) the output object is
    checked against the track rules and violations are stored alongside as
    ``...output.violations.json`` (the run is still saved — visibility over
    hard failure).
    """
    ts = timestamp or run_timestamp()
    slug = query_slug(query)
    out_dir = data_dir() / "outputs" / system_name
    out_dir.mkdir(parents=True, exist_ok=True)

    paths = {
        "trajectory": out_dir / f"{ts}.{slug}.trajectory.json",
        "output": out_dir / f"{ts}.{slug}.output.json",
    }
    trace = getattr(trajectory, "trace", None)
    if trace is not None:
        output["trace"] = trace

    paths["trajectory"].write_text(
        json.dumps(dict(trajectory), ensure_ascii=False, indent=2))
    paths["output"].write_text(
        json.dumps(output, ensure_ascii=False, indent=2))

    if validate:
        errs = validate_rag_output(output)
        if errs:
            vpath = out_dir / f"{ts}.{slug}.output.violations.json"
            vpath.write_text(json.dumps(errs, ensure_ascii=False, indent=2))
            paths["violations"] = vpath
    return paths
