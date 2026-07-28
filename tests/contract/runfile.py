"""TREC runfile conformance validator (`r_output_trec_rag_2026.tsv`).

**Why this lives in `tests/` and not in `src/`.** There is no runfile writer in
`src/` at all — `grep -rn "Q0" src/` returns nothing; the only two writers in the
repo are ad-hoc task scripts (`tasks/custom_index/scripts/eval_umbrela.py` and
`fetch_remote_run.py`) that format the line inline with an f-string. So the
Retrieval task's output format is currently unenforced anywhere in the codebase,
and this module is the only executable statement of it. It is written as a
validator rather than a writer deliberately: a validator can be pointed at
whatever a task script produced, and it does not pre-empt the design of a real
`ragrun` writer.

The rules implemented are exactly `retrieval-task.md` "Output Format: Ranked
Results" + "Validation Rules":

- six whitespace-separated columns: ``topic_id Q0 docid rank score run_id``;
- ``Q0`` is a fixed literal in column 2;
- ranks restart at 1 for each topic and ascend by 1;
- scores are non-increasing within a topic;
- rows of a topic are contiguous and sorted by rank ascending;
- ``docid`` is a ClimbMix document id — ``shard_<digits>_<digits>`` — and
  explicitly not an MS MARCO segment id (``...#<n>``);
- no fixed row cap, and row counts may differ across topics (so neither is
  checked — the absence is the rule).

Like ``ragrun.validate_rag_output``, ``validate_runfile`` returns a list of
human-readable violation strings (empty == conforming) rather than raising, so a
caller can report every problem in one pass.
"""
from __future__ import annotations

import re
from typing import Any

# ClimbMix docid convention: `shard_<5-digit shard>_<row>`. Kept deliberately
# loose on the shard width (the corpus uses 5 digits, but the rule that matters
# is "shard_<digits>_<digits>" with no segment marker).
CLIMBMIX_DOCID_RE = re.compile(r"^shard_\d+_\d+$")

# An MS MARCO V2.1 segment id looks like `msmarco_v2.1_doc_51_1043....#4_2314`.
# The `#` is the tell, and the spec calls these out by name as forbidden.
MSMARCO_SEGMENT_RE = re.compile(r"#")

N_COLUMNS = 6
Q0 = "Q0"


def validate_runfile(text: str) -> list[str]:
    """Return the runfile's conformance violations (``[]`` == conforming).

    ``text`` is the full file content. Lines are split on any whitespace run (the
    spec says "whitespace-separated", and real TREC tooling accepts both tabs and
    spaces), which is why a docid containing a space is reported as a column-count
    error rather than silently splitting a field.
    """
    errs: list[str] = []
    if not text.strip():
        return ["runfile is empty"]

    # Per-topic state, keyed by topic_id: last rank seen, last score seen.
    last_rank: dict[str, int] = {}
    last_score: dict[str, float] = {}
    topic_order: list[str] = []
    current_topic: str | None = None

    for lineno, raw in enumerate(text.split("\n"), start=1):
        if not raw.strip():
            # A trailing newline is normal; an interior blank line is not, but it
            # carries no data either way — skip rather than fail the whole file.
            continue
        fields = raw.split()
        if len(fields) != N_COLUMNS:
            errs.append(f"line {lineno}: expected {N_COLUMNS} whitespace-"
                        f"separated columns, got {len(fields)}")
            continue
        topic_id, q0, docid, rank_s, score_s, run_id = fields

        if q0 != Q0:
            errs.append(f"line {lineno}: column 2 must be the literal {Q0!r}, "
                        f"got {q0!r}")
        if MSMARCO_SEGMENT_RE.search(docid):
            errs.append(f"line {lineno}: docid {docid!r} looks like an MS MARCO "
                        "segment id, not a ClimbMix document id")
        elif not CLIMBMIX_DOCID_RE.match(docid):
            errs.append(f"line {lineno}: docid {docid!r} is not a ClimbMix "
                        "document id (expected shard_<digits>_<digits>)")
        if not run_id:
            errs.append(f"line {lineno}: run_id must be non-empty")

        try:
            rank = int(rank_s)
        except ValueError:
            errs.append(f"line {lineno}: rank {rank_s!r} is not an integer")
            rank = None  # type: ignore[assignment]
        try:
            score = float(score_s)
        except ValueError:
            errs.append(f"line {lineno}: score {score_s!r} is not numeric")
            score = None  # type: ignore[assignment]

        # Topic blocks must be contiguous: a topic reappearing after another
        # topic's rows means the file is not sorted by topic, which breaks the
        # "ranks restart at 1 for each topic" reading.
        if topic_id != current_topic:
            if topic_id in last_rank:
                errs.append(f"line {lineno}: topic {topic_id!r} rows are not "
                            "contiguous (topic reappears after another topic)")
            else:
                topic_order.append(topic_id)
            current_topic = topic_id

        if rank is not None:
            previous = last_rank.get(topic_id)
            if previous is None:
                if rank != 1:
                    errs.append(f"line {lineno}: topic {topic_id!r} starts at "
                                f"rank {rank}, must restart at 1")
            elif rank != previous + 1:
                errs.append(f"line {lineno}: topic {topic_id!r} rank {rank} does "
                            f"not ascend by 1 from {previous}")
            last_rank[topic_id] = rank
        if score is not None:
            previous_score = last_score.get(topic_id)
            if previous_score is not None and score > previous_score:
                errs.append(f"line {lineno}: topic {topic_id!r} score {score} "
                            f"increased over the previous row's {previous_score} "
                            "(scores must be non-increasing within a topic)")
            last_score[topic_id] = score

    return errs


def format_runfile(rows: list[tuple[str, str, int, float, str]]) -> str:
    """Serialize ``(topic_id, docid, rank, score, run_id)`` rows to runfile text.

    A test-only writer: it exists so the conforming fixtures below are produced
    the same way a real writer would produce them, and so the non-conforming cases
    can be built by perturbing a conforming file rather than by hand-typing lines.
    """
    return "".join(
        f"{topic_id}\t{Q0}\t{docid}\t{rank}\t{score:.4f}\t{run_id}\n"
        for topic_id, docid, rank, score, run_id in rows)


def rows_from_hits(topic_id: str, hits: list[dict[str, Any]], run_id: str
                   ) -> list[tuple[str, str, int, float, str]]:
    """Project ``SearchHit`` dicts onto runfile rows.

    Uses ``hit["docid"]`` (never ``hit["id"]``): the retrieval task submits
    ClimbMix *document* ids, so a chunk-level run must be projected to its parents
    — the same rule that keeps RAG ``references`` doc-level.
    """
    return [(topic_id, hit["docid"], i, float(hit["score"]), run_id)
            for i, hit in enumerate(hits, start=1)]
