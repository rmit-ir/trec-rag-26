"""TREC RAG 2026 output object + run persistence — the ``*.output.json`` half.

``build_rag_output`` produces the organizer-facing fields from the track's
``rag-task.md`` (see skills/trec-rag-2026-track-guidelines/references):

    {
      "metadata": {team_id, narrative_id, narrative, run_id, run_desc},
      "references": ["<climbmix docid>", ...],   # retrieved docids; uncited is OK
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
    """Assemble one TREC RAG 2026 output object (no extra metadata keys).

    Raises ``TypeError`` if ``references`` is a bare string. ``list("shard_0…")``
    silently splats it into single-character "docids", and since v0.6.0 made
    uncited references legal the result *validates clean* — so this is the only
    place a trivial ``references=docid`` typo can still be caught.
    """
    if isinstance(references, str):
        raise TypeError(
            "references must be a list of docid strings, not a single string "
            f"({references!r}) — did you mean [{references!r}]?")
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


def jsonl_row(obj: dict[str, Any]) -> str:
    """Serialize one submission object as a single, unambiguous JSONL line.

    ``ensure_ascii=False`` is deliberate — narratives and answers stay readable
    Unicode rather than ``\\uXXXX`` soup — but it leaves U+2028 LINE SEPARATOR and
    U+2029 PARAGRAPH SEPARATOR literal. Splitting on ``"\\n"`` is unaffected (the
    record is still one physical line by the LF definition), but Python's
    ``str.splitlines()`` breaks on both, so any organizer-side tool reading the
    submission that way would see a truncated record. Escaping just these two
    removes the hazard without touching the readability of everything else.
    """
    return (json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
            .replace(" ", "\\u2028")
            .replace(" ", "\\u2029"))


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
    (empty list = valid). Mirrors rag-task.md.

    Only the explicit structural rules are enforced, per the guidelines'
    directive not to add stylistic validation of our own. Three things the spec
    calls out as *not* rejectable — extra ``metadata`` keys, uncited
    ``references``, and an empty ``citations`` array — are therefore accepted.
    """
    errs: list[str] = []
    meta = obj.get("metadata")
    if not isinstance(meta, dict):
        errs.append("metadata missing or not an object")
        meta = {}
    required = {"team_id", "narrative_id", "narrative", "run_id", "run_desc"}
    missing = required - meta.keys()
    if missing:
        errs.append(f"metadata missing keys: {sorted(missing)}")
    # Extra ``metadata`` keys are explicitly allowed ("may also contain any
    # additional participant-defined fields"), so only the five required keys
    # are checked. Do not reinstate an extra-key check.

    refs = obj.get("references")
    answer = obj.get("answer")
    if not isinstance(refs, list) or not all(isinstance(r, str) for r in refs):
        errs.append("references must be a list of docid strings")
        refs = []
    if not isinstance(answer, list) or not answer:
        errs.append("answer must be a non-empty list")
        answer = []

    total_words = 0
    for i, sent in enumerate(answer):
        if not isinstance(sent, dict) or "text" not in sent or "citations" not in sent:
            errs.append(f"answer[{i}] must have 'text' and 'citations'")
            continue
        # The spec treats `text` as "an opaque, non-empty text string". Without
        # this guard a non-string raised AttributeError out of validate_rag_output
        # and out of save_run, so the run's artifacts were never written at all —
        # a validation *report* must never destroy the thing it is reporting on.
        if not isinstance(sent["text"], str):
            errs.append(f"answer[{i}].text must be a string, "
                        f"got {type(sent['text']).__name__}")
        elif sent["text"] == "":
            errs.append(f"answer[{i}].text must be non-empty")
        else:
            # The spec defines the count normatively as
            # sum(len(item["text"].split()) for item in answer) — do not change it.
            total_words += len(sent["text"].split())
        cits = sent["citations"]
        if not isinstance(cits, list) or len(cits) > 3:
            errs.append(f"answer[{i}].citations must be a list of at most 3 citations")
            continue
        for c in cits:
            # A citation is either a zero-based position into ``references`` or
            # the docid string of a reference entry, written verbatim.
            if isinstance(c, str):
                if c not in refs:
                    errs.append(f"answer[{i}] cites unknown reference docid {c!r}")
            # `type(c) is int`, not isinstance: bool is a subclass of int, so a
            # JSON `true` would otherwise validate as index 1.
            elif type(c) is int and 0 <= c < len(refs):
                continue
            else:
                errs.append(f"answer[{i}] cites invalid reference index {c!r}")
    if total_words > 1024:
        errs.append(f"answer is {total_words} words (max 1024)")
    # Uncited references are explicitly permitted and must not be penalized, so
    # there is no coverage check here. Do not reinstate one.
    return errs


def _umask() -> int:
    """Read the process umask without disturbing it (no portable getter)."""
    current = os.umask(0o022)
    os.umask(current)
    return current


def atomic_write_text(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` so a concurrent reader sees old-or-new, never
    a truncated file.

    A run now rewrites its ``output.json`` repeatedly while it is still going
    (see ``save_run``'s ``write_trajectory``/``validate`` partial mode), and the
    outputs viewer polls those files. ``Path.write_text`` truncates in place,
    so a poller landing mid-write reads half a JSON document. Writing to a temp
    file in the *same directory* (so ``os.replace`` stays within one filesystem
    and is therefore atomic) and renaming over the target removes that window
    entirely; the temp file is removed on any failure, so no ``.tmp`` debris is
    left behind.
    """
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        # mkstemp creates 0600 and os.replace keeps the temp file's mode, which
        # would quietly make every artifact owner-only — Path.write_text left
        # them at the umask default (0644), and other accounts (a viewer server
        # running as its own user) need to read them.
        os.chmod(tmp_name, 0o666 & ~_umask())
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def run_artifact_paths(system_name: str, query: str,
                       timestamp: str) -> dict[str, Path]:
    """The artifact paths a run writes, derived only from its timestamp+query.

    Callers allocate the timestamp once at the start of a run so every
    incremental write targets the same files.
    """
    slug = query_slug(query)
    out_dir = data_dir() / "outputs" / system_name
    return {
        "trajectory": out_dir / f"{timestamp}.{slug}.trajectory.json",
        "output": out_dir / f"{timestamp}.{slug}.output.json",
        "violations": out_dir / f"{timestamp}.{slug}.output.violations.json",
    }


def save_run(system_name: str, query: str, *, trajectory: dict[str, Any],
             output: dict[str, Any], timestamp: str | None = None,
             validate: bool = True,
             write_trajectory: bool = True) -> dict[str, Path]:
    """Persist the run artifacts; returns their paths.

    Writes ``data/outputs/<system_name>/<ts>.<slug>.trajectory.json`` and
    ``...output.json``. With ``validate=True`` (default) the output object is
    checked against the track rules and violations are stored alongside as
    ``...output.violations.json`` (the run is still saved — visibility over
    hard failure).

    Both files are written atomically (temp file + ``os.replace``) because the
    outputs viewer polls ``output.json`` while a run is still in flight.

    ``timestamp`` pins the filenames; pass the run's own stamp to make repeated
    incremental saves land on the same files. ``write_trajectory=False`` and
    ``validate=False`` are the partial-write mode: the viewer only reads
    ``output.json``, and validating an unfinished answer would only produce a
    misleading violations file.
    """
    ts = timestamp or run_timestamp()
    paths = run_artifact_paths(system_name, query, ts)
    paths["output"].parent.mkdir(parents=True, exist_ok=True)

    trace = getattr(trajectory, "trace", None)
    if trace is not None:
        output["trace"] = trace

    written: dict[str, Path] = {"output": paths["output"]}
    if write_trajectory:
        atomic_write_text(
            paths["trajectory"],
            json.dumps(dict(trajectory), ensure_ascii=False, indent=2))
        written["trajectory"] = paths["trajectory"]
    atomic_write_text(
        paths["output"], json.dumps(output, ensure_ascii=False, indent=2))

    if validate:
        errs = validate_rag_output(output)
        if errs:
            atomic_write_text(
                paths["violations"],
                json.dumps(errs, ensure_ascii=False, indent=2))
            written["violations"] = paths["violations"]
    return written
