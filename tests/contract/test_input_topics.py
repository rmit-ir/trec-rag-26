"""Contract: the topics TSV input format (`trec_rag_2026_queries.tsv`).

Both track references (`retrieval-task.md` "Input Format: Topics" and
`rag-task.md` same section) specify exactly two tab-separated fields per line —
topic id, then topic text — and require the id to be "preserved exactly" and the
text "copied exactly" into ``metadata.narrative``. That "exactly" is the whole
reason this module exists: the parser is four lines long, but a stray ``.strip()``
or a re-split on whitespace would silently mangle the narrative of every topic in
the submission, and nothing downstream would notice.

The parser under test is ``facet_rag.run.load_topics`` — the shared shape all
systems use (see also ``claude-code-research/scripts/save_run.py``). Narratives in
the real file are long prose paragraphs (the rag2026-37 example in the spec is one
sentence short of 100 words) full of commas, quotes, colons and question marks, so
the fixtures here are deliberately punctuation-heavy rather than toy strings.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from facet_rag.run import load_topics
from ragrun import build_rag_output

pytestmark = pytest.mark.contract

# The spec's own worked example, verbatim from rag-task.md / retrieval-task.md.
SPEC_QID = "rag2026-37"
SPEC_NARRATIVE = (
    "I work for a New York City council member whose district has a lot of "
    "transit riders but also some small businesses worried about delivery "
    "costs. Can you help me understand whether congestion pricing is a "
    "credible and fair way to fund the MTA? What should we weigh about the "
    "revenue promise, who pays, who benefits, environmental tradeoffs in "
    "places like the Bronx and New Jersey, and whether the MTA and Albany can "
    "be held accountable for actually spending the money on reliable service "
    "instead of repeating past mistakes?"
)


def write_tsv(tmp_path: Path, *lines: str, trailing_newline: bool = True) -> Path:
    """Write a topics TSV verbatim (no reformatting) and return its path."""
    body = "\n".join(lines) + ("\n" if trailing_newline else "")
    path = tmp_path / "trec_rag_2026_queries.tsv"
    path.write_text(body, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# The happy path: exact id, exact narrative
# ---------------------------------------------------------------------------
def test_parses_qid_and_narrative_exactly(tmp_path: Path) -> None:
    """The spec's example line round-trips byte-for-byte through the parser."""
    path = write_tsv(tmp_path, f"{SPEC_QID}\t{SPEC_NARRATIVE}")

    rows = load_topics(path)

    assert rows == [(SPEC_QID, SPEC_NARRATIVE)]
    # Belt and braces: identity of the *characters*, not just equality of a
    # normalized form — a parser that collapsed whitespace would pass `==` on a
    # single-spaced fixture but fail here.
    assert len(rows[0][1]) == len(SPEC_NARRATIVE)


def test_parses_multiple_topics_in_file_order(tmp_path: Path) -> None:
    """File order is preserved, and qids are never sorted or renumbered.

    Batch runners resume by index into this list and the runfile groups topics in
    the order they were processed, so a reordering here would silently misalign a
    partial run's outputs with the topics they answer. The qids are deliberately
    not in lexical or numeric order to catch an incidental ``sorted()``.
    """
    path = write_tsv(
        tmp_path,
        "rag2026-0\tFirst information need.",
        f"{SPEC_QID}\t{SPEC_NARRATIVE}",
        "rag2026-104\tThird information need.",
    )

    rows = load_topics(path)

    assert [qid for qid, _ in rows] == ["rag2026-0", SPEC_QID, "rag2026-104"]


# ---------------------------------------------------------------------------
# Characters that appear in real narratives must survive verbatim
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("narrative", [
    pytest.param(
        "Commas, lots of them, and a trailing clause, too.", id="commas"),
    pytest.param(
        'She said "congestion pricing" and I said \'maybe\'.', id="quotes"),
    pytest.param(
        "Two questions: first, does it work? Second: who pays?", id="colons"),
    pytest.param(
        "A sentence.  Two spaces after the period.   And three here.",
        id="internal-multiple-spaces"),
    pytest.param(
        "I’m on a hospital nursing DEI council — limited money.",
        id="unicode-punctuation"),
    pytest.param(
        "Ranked #1 (2025) at 50% ≥ baseline; see §3 & Fig. 2.",
        id="symbols"),
    pytest.param(SPEC_NARRATIVE, id="spec-example"),
])
def test_narrative_survives_verbatim(tmp_path: Path, narrative: str) -> None:
    """No normalization of the second column: what's in the file is what's used.

    ``metadata.narrative`` is what organizers diff against their own topic file,
    so any normalization here is a submission-level defect.
    """
    path = write_tsv(tmp_path, f"rag2026-7\t{narrative}")

    assert load_topics(path) == [("rag2026-7", narrative)]


def test_topic_id_is_not_normalized(tmp_path: Path) -> None:
    """Ids are opaque strings — no int coercion, no case folding, no prefix
    assumptions (the retrieval-task example even uses bare ``1``/``2``)."""
    path = write_tsv(
        tmp_path,
        "1\tBare numeric id, as in the runfile example.",
        "RAG2026-9\tUppercased id.",
        "6847465956a0f6376a605492\tHex dev-topic id.",
    )

    assert [qid for qid, _ in load_topics(path)] == [
        "1", "RAG2026-9", "6847465956a0f6376a605492"]


# ---------------------------------------------------------------------------
# Lines that are not topics
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("junk", [
    pytest.param("", id="blank-line"),
    pytest.param("   ", id="spaces-only"),
    pytest.param("\t", id="tab-only"),
    pytest.param("  \t  ", id="whitespace-both-columns"),
    pytest.param("rag2026-9", id="qid-with-no-tab"),
    pytest.param("rag2026-9\t", id="qid-with-empty-narrative"),
    pytest.param("rag2026-9\t   ", id="qid-with-whitespace-narrative"),
    pytest.param("\tnarrative but no qid", id="narrative-with-no-qid"),
])
def test_non_topic_lines_are_skipped(tmp_path: Path, junk: str) -> None:
    """A half-line is dropped rather than emitted as a malformed topic.

    ``load_topics`` requires BOTH columns to be non-blank after stripping, so a
    trailing blank line or a truncated row can never become a topic with an
    empty narrative (which would produce an empty ``metadata.narrative``).
    """
    path = write_tsv(tmp_path, junk, f"{SPEC_QID}\t{SPEC_NARRATIVE}", junk)

    assert load_topics(path) == [(SPEC_QID, SPEC_NARRATIVE)]


@pytest.mark.parametrize("trailing_newline", [True, False])
def test_trailing_newline_at_eof_is_optional(tmp_path: Path,
                                             trailing_newline: bool) -> None:
    """Both EOF conventions must yield the same topics.

    Real topic files arrive both ways — a POSIX tool writes the final newline, a
    spreadsheet export or a hand-trimmed subset often does not. A reader that
    assumes one loses the last topic of the file, i.e. exactly one missing row in
    the submission, which is easy to miss in a several-dozen-topic run.
    """
    path = write_tsv(tmp_path, f"{SPEC_QID}\t{SPEC_NARRATIVE}",
                     trailing_newline=trailing_newline)

    assert load_topics(path) == [(SPEC_QID, SPEC_NARRATIVE)]


def test_empty_file_yields_no_topics(tmp_path: Path) -> None:
    """An empty file is an empty list, not an exception.

    A truncated download or a not-yet-published topics file is the common cause.
    Returning ``[]`` lets the runner report "0 topics" and exit cleanly instead of
    dying in the loader, which is the difference between a legible error and a
    traceback that looks like a parser bug.
    """
    path = tmp_path / "empty.tsv"
    path.write_text("", encoding="utf-8")

    assert load_topics(path) == []


# ---------------------------------------------------------------------------
# Documented edge behaviour (current behaviour, not necessarily desirable)
# ---------------------------------------------------------------------------
def test_extra_tab_in_narrative_keeps_the_remainder(tmp_path: Path) -> None:
    """A literal tab inside the narrative is NOT a column separator.

    ``str.partition("\\t")`` splits on the FIRST tab only, so everything after it
    — tabs included — stays in the narrative. That is the behaviour we want (a
    TSV with three fields is malformed input; keeping the remainder is lossless
    rather than truncating the topic text), but it is worth pinning: a switch to
    ``line.split("\\t")`` + indexing would silently drop half of such a topic.
    """
    path = write_tsv(tmp_path, "rag2026-9\tpart one\tpart two\tpart three")

    (qid, narrative), = load_topics(path)

    assert qid == "rag2026-9"
    assert narrative == "part one\tpart two\tpart three"


def test_narrative_padding_is_stripped_current_behaviour(tmp_path: Path) -> None:
    """CURRENT BEHAVIOUR (reported, not asserted as desirable): surrounding
    whitespace in either column is stripped.

    The spec says the topic text is "copied exactly". ``load_topics`` calls
    ``.strip()`` on both columns, so a narrative written as ``"  text  "`` in the
    TSV is emitted as ``"text"`` — a deviation from a literal reading of "exactly".
    In practice this is desirable (it eats the ``\\r`` of a CRLF file and any
    accidental padding) and the official file has no padded fields, so we pin the
    stripping instead of calling it a bug.
    """
    path = write_tsv(tmp_path, "  rag2026-9  \t   padded narrative text   ")

    assert load_topics(path) == [("rag2026-9", "padded narrative text")]


def test_crlf_line_endings_do_not_leak_into_the_narrative(tmp_path: Path) -> None:
    """A Windows-authored topics file must not append ``\\r`` to every narrative."""
    path = tmp_path / "crlf.tsv"
    path.write_bytes(f"{SPEC_QID}\t{SPEC_NARRATIVE}\r\n".encode("utf-8"))

    assert load_topics(path) == [(SPEC_QID, SPEC_NARRATIVE)]


# ---------------------------------------------------------------------------
# Round trip: TSV -> load_topics -> build_rag_output
# ---------------------------------------------------------------------------
def test_round_trip_into_rag_output_metadata(tmp_path: Path) -> None:
    """The narrative that lands in the submitted JSONL is the file's bytes.

    This is the assertion that actually protects the submission: the two hops
    (parse, then build the output object) are the only places the topic text is
    handled before serialization, so if both are identity-preserving the
    organizer-side diff of ``metadata.narrative`` cannot fail.
    """
    path = write_tsv(tmp_path, f"{SPEC_QID}\t{SPEC_NARRATIVE}")
    (qid, narrative), = load_topics(path)

    obj = build_rag_output(
        narrative_id=qid, narrative=narrative,
        run_id="contract-run", run_desc="topics TSV round-trip check",
        references=["shard_00459_61697"],
        answer=[{"text": "Grounded sentence.", "citations": [0]}])

    assert obj["metadata"]["narrative_id"] == SPEC_QID
    assert obj["metadata"]["narrative"] == SPEC_NARRATIVE


def test_round_trip_survives_json_serialization(tmp_path: Path) -> None:
    """Unicode in the narrative must survive ``ensure_ascii=False`` JSONL too."""
    import json

    narrative = "I’m weighing tradeoffs — café owners vs. riders."
    path = write_tsv(tmp_path, f"rag2026-3\t{narrative}")
    (qid, loaded), = load_topics(path)

    obj = build_rag_output(
        narrative_id=qid, narrative=loaded, run_id="r", run_desc="d",
        references=["shard_00459_61697"],
        answer=[{"text": "Grounded sentence.", "citations": [0]}])
    reloaded = json.loads(json.dumps(obj, ensure_ascii=False))

    assert reloaded["metadata"]["narrative"] == narrative
