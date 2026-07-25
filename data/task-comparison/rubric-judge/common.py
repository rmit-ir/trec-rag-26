"""Shared plumbing for the rubric-grounded LLM-as-judge pipeline.

Paths, the engine list, creds/model loading (luna = ``gpt-5.6-luna`` on the
aus_agent OpenAI-compatible Azure endpoint), a JSON-mode luna call helper, and
the two ground-truth loaders (topics TSV + rubrics JSONL). Every stage script
imports from here so there is one source of truth for the model id, the info
axes, and the on-disk layout.

Run stages as (from repo root):
    PYTHONPATH=src uv run --group aus-agent python \
        data/outputs/engine-comparison/rubric-judge/<stage>.py [--qids <qid> ...]
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path("/scratch/fast/kun/projects/trec-rag-26")
SRC = ROOT / "src"
HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
JUDGE_DIR = OUT / "judgments"

TOPICS_TSV = (ROOT / "data/official/trec-rag-2026-data/trec-rag-2026"
              "/development-data/topics/research-rubrics-topics-dev.tsv")
RUBRICS_JSONL = (ROOT / "data/official/trec-rag-2026-data/trec-rag-2026"
                 "/development-data/researchrubrics-dev-rubrics"
                 "/research-rubrics-dev-rubrics.jsonl")

# The four retrieval backends, in a stable order (matches ENGINE_INFO order).
ENGINES = ["semantic", "keyword", "ssr", "lucene_bool"]

# Axes that count as "information requirements" (drop everything else, and drop
# any weight<=0 penalty criterion). Per the task spec.
INFO_AXES = {"Explicit Criteria", "Implicit Criteria", "Synthesis of Information"}

# ---------------------------------------------------------------------------
# sys.path munge so `tools.*` / `utils.*` resolve to src/ (mirrors run.py). Put
# SRC first so the local `tools` shim (if any) does not shadow src/tools.
# ---------------------------------------------------------------------------
_src = str(SRC)
sys.path[:] = [p for p in sys.path if p != _src]
sys.path.insert(0, _src)

# dotenv: find_dotenv() breaks under `python - <<EOF` (no __file__); pass path.
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:  # pragma: no cover
    pass

# aus_agent's default when no OPENAI_MODEL_ID / RUN_AUS_AGENT_MODEL is set
# (see src/systems/aus_agent/providers/openai.py DEFAULT_MODEL_ID).
LUNA_MODEL = (os.environ.get("OPENAI_MODEL_ID")
              or os.environ.get("RUN_AUS_AGENT_MODEL")
              or "gpt-5.6-luna")


def luna_client():
    """An OpenAI client pointed at the aus_agent Azure endpoint (creds from
    the repo-root .env: OPENAI_BASE_URL / OPENAI_API_KEY)."""
    from openai import OpenAI
    return OpenAI(
        base_url=os.environ["OPENAI_BASE_URL"],
        api_key=os.environ["OPENAI_API_KEY"],
        timeout=180.0,
        max_retries=4,
    )


def luna_json(client, system: str, user: str, *, model: str = LUNA_MODEL) -> dict:
    """One luna call in strict-JSON mode; returns the parsed object.

    Uses chat.completions with response_format=json_object — validated working
    against gpt-5.6-luna on this endpoint.
    """
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        response_format={"type": "json_object"},
    )
    return json.loads(resp.choices[0].message.content)


# ---------------------------------------------------------------------------
# Ground-truth loaders
# ---------------------------------------------------------------------------
def load_topics() -> dict[str, str]:
    """qid -> narrative, preserving file order via the returned dict."""
    topics: dict[str, str] = {}
    for line in TOPICS_TSV.read_text().splitlines():
        line = line.rstrip("\n")
        if not line.strip():
            continue
        qid, _, narrative = line.partition("\t")
        topics[qid.strip()] = narrative.strip()
    return topics


def load_rubrics() -> dict[str, dict]:
    """qid -> full rubric row (domain/labels + rubrics list)."""
    rows: dict[str, dict] = {}
    for line in RUBRICS_JSONL.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        d = json.loads(line)
        rows[d["qid"]] = d
    return rows


def first_qid() -> str:
    """The first topic in file order (the validation topic)."""
    return next(iter(load_topics()))


def filter_qids(all_qids, wanted):
    """Order-preserving intersection; ``wanted`` None/empty -> all."""
    if not wanted:
        return list(all_qids)
    ws = set(wanted)
    return [q for q in all_qids if q in ws]


def load_json(path: Path):
    with open(path) as f:
        return json.load(f)


def dump_json(obj, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
