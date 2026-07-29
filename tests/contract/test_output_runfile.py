"""Contract: the six-column TREC runfile (`r_output_trec_rag_2026.tsv`).

**There is no runfile writer under `src/`.** `grep -rn "Q0" src/` finds nothing;
the only producers in the repo are two ad-hoc task scripts
(`tasks/custom_index/scripts/eval_umbrela.py:89`,
`tasks/custom_index/scripts/fetch_remote_run.py:140`) that format the line with an
inline f-string. So the Retrieval task's output format has no enforcement in the
codebase, and rather than write one into `src/` (out of scope here) this module
tests a validator — ``contract.runfile.validate_runfile`` — that encodes
`retrieval-task.md`'s field rules and Validation Rules.

The tests come in pairs: a conforming file must be silent, and each specific
non-conformance must produce its own violation. That second half is the part that
gives the validator any value — a validator that returns ``[]`` for everything
would otherwise pass the happy-path test just fine.

The final test connects the validator to real retrieval output (``fake_hits`` /
``run_search_tool`` via ``stub_search_tool``), so the docid-projection rule
("submit ClimbMix document ids", i.e. ``hit["docid"]`` not ``hit["id"]``) is
checked against actual ``SearchHit`` data rather than hand-written ids.
"""
from __future__ import annotations

import json
from typing import Any, Callable

import pytest

from contract.runfile import (CLIMBMIX_DOCID_RE, format_runfile, rows_from_hits,
                              validate_runfile)

from conftest import CLIMBMIX_DOCIDS

pytestmark = pytest.mark.contract

RUN_ID = "rmit-ir-bm25-top100"

# The spec's own example block, transcribed verbatim (bare numeric topic ids and
# all) — the validator must accept the document it is derived from.
SPEC_EXAMPLE = (
    "1 Q0 shard_00459_61697 1 12.4838 my-run\n"
    "1 Q0 shard_01012_88420 2 11.9721 my-run\n"
    "1 Q0 shard_00210_44018 3 10.5542 my-run\n"
    "2 Q0 shard_00044_91812 1 10.8114 my-run\n"
)


def conforming_rows() -> list[tuple[str, str, int, float, str]]:
    """Two topics with different row counts (explicitly allowed by the spec)."""
    return [
        ("rag2026-0", CLIMBMIX_DOCIDS[0], 1, 12.5, RUN_ID),
        ("rag2026-0", CLIMBMIX_DOCIDS[1], 2, 11.5, RUN_ID),
        ("rag2026-0", CLIMBMIX_DOCIDS[2], 3, 10.5, RUN_ID),
        ("rag2026-37", CLIMBMIX_DOCIDS[3], 1, 9.5, RUN_ID),
        ("rag2026-37", CLIMBMIX_DOCIDS[0], 2, 8.5, RUN_ID),
    ]


# ---------------------------------------------------------------------------
# Conforming files
# ---------------------------------------------------------------------------
def test_spec_example_block_is_conforming() -> None:
    """The validator must accept the spec's own example, unmodified.

    This is the anchor for every rejection test below: a validator strict enough
    to reject the document it was written from would fail every real submission
    while all the negative cases still passed.
    """
    assert validate_runfile(SPEC_EXAMPLE) == []


def test_generated_runfile_is_conforming() -> None:
    """Writer and validator agree — the round-trip closes.

    Both live in ``tests/contract/runfile.py``, so they can drift apart and each
    still look right in isolation. This is the only test that pins them together,
    which matters because ``format_runfile`` is what any future ``src/`` runfile
    writer will be checked against.
    """
    assert validate_runfile(format_runfile(conforming_rows())) == []


def test_generated_runfile_has_six_tab_separated_columns() -> None:
    """The writer's own shape, so the fixtures below start from a valid file."""
    text = format_runfile(conforming_rows())

    for line in text.splitlines():
        assert len(line.split("\t")) == 6
        assert line.split("\t")[1] == "Q0"


@pytest.mark.parametrize("text, why", [
    pytest.param(format_runfile(conforming_rows()).replace("\t", " "),
                 "space-separated is equally valid", id="space-separated"),
    pytest.param(format_runfile(conforming_rows()).replace("\t", "  "),
                 "runs of whitespace collapse", id="multi-space-separated"),
    pytest.param(format_runfile(conforming_rows()).rstrip("\n"),
                 "no trailing newline at EOF", id="no-trailing-newline"),
    pytest.param(format_runfile(conforming_rows()) + "\n",
                 "a trailing blank line carries no data", id="trailing-blank"),
    pytest.param(format_runfile([("1", CLIMBMIX_DOCIDS[0], 1, 12.5, RUN_ID)]),
                 "one topic, one row", id="single-row"),
    pytest.param(format_runfile([("t", CLIMBMIX_DOCIDS[0], 1, 5.0, RUN_ID),
                                 ("t", CLIMBMIX_DOCIDS[1], 2, 5.0, RUN_ID)]),
                 "equal scores are non-increasing", id="tied-scores"),
    pytest.param(format_runfile([("t", CLIMBMIX_DOCIDS[0], 1, 0.5, RUN_ID),
                                 ("t", CLIMBMIX_DOCIDS[1], 2, -0.5, RUN_ID)]),
                 "negative scores are numeric", id="negative-scores"),
    pytest.param(format_runfile([(f"rag2026-{t}", CLIMBMIX_DOCIDS[0], 1, 1.0,
                                  RUN_ID) for t in range(50)]),
                 "no cap on topics", id="many-topics"),
])
def test_conforming_variants(text: str, why: str) -> None:
    """"whitespace-separated" and "rows per topic may vary" are real latitude —
    the validator must not tighten the spec."""
    assert validate_runfile(text) == [], why


def test_row_counts_may_differ_across_topics() -> None:
    """Explicit Validation Rule: "Rows per topic may vary across topics" and
    "There is no fixed maximum number of rows per topic"."""
    rows = ([("a", CLIMBMIX_DOCIDS[0], 1, 3.0, RUN_ID)]
            + [("b", CLIMBMIX_DOCIDS[i % 4], i, 100.0 - i, RUN_ID)
               for i in range(1, 201)])

    assert validate_runfile(format_runfile(rows)) == []


# ---------------------------------------------------------------------------
# Non-conforming: one case per Validation Rule
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text, fragment", [
    # --- six columns ---
    pytest.param("rag2026-0\tQ0\tshard_00459_61697\t1\t12.5000\n",
                 "expected 6 whitespace-separated columns, got 5",
                 id="too-few-columns"),
    pytest.param(
        "rag2026-0\tQ0\tshard_00459_61697\t1\t12.5000\trun\textra\n",
        "expected 6 whitespace-separated columns, got 7",
        id="too-many-columns"),
    pytest.param("rag2026-0 Q0 shard_00459_61697 1 12.5000 my run id\n",
                 "expected 6 whitespace-separated columns, got 8",
                 id="whitespace-inside-run-id"),
    # --- Q0 literal ---
    pytest.param("rag2026-0\tq0\tshard_00459_61697\t1\t12.5000\trun\n",
                 "column 2 must be the literal 'Q0', got 'q0'",
                 id="lowercase-q0"),
    pytest.param("rag2026-0\t0\tshard_00459_61697\t1\t12.5000\trun\n",
                 "column 2 must be the literal 'Q0', got '0'",
                 id="missing-q0-literal"),
    # --- ranks restart at 1 per topic and ascend ---
    pytest.param("rag2026-0\tQ0\tshard_00459_61697\t0\t12.5000\trun\n",
                 "starts at rank 0, must restart at 1",
                 id="rank-starts-at-zero"),
    pytest.param(
        "rag2026-0\tQ0\tshard_00459_61697\t1\t12.5000\trun\n"
        "rag2026-37\tQ0\tshard_01012_88420\t2\t11.5000\trun\n",
        "starts at rank 2, must restart at 1",
        id="rank-does-not-restart-for-new-topic"),
    pytest.param(
        "rag2026-0\tQ0\tshard_00459_61697\t1\t12.5000\trun\n"
        "rag2026-0\tQ0\tshard_01012_88420\t3\t11.5000\trun\n",
        "rank 3 does not ascend by 1 from 1",
        id="rank-skips-a-value"),
    pytest.param(
        "rag2026-0\tQ0\tshard_00459_61697\t1\t12.5000\trun\n"
        "rag2026-0\tQ0\tshard_01012_88420\t1\t11.5000\trun\n",
        "rank 1 does not ascend by 1 from 1",
        id="duplicate-rank"),
    pytest.param(
        "rag2026-0\tQ0\tshard_00459_61697\t2\t12.5000\trun\n"
        "rag2026-0\tQ0\tshard_01012_88420\t1\t11.5000\trun\n",
        "starts at rank 2, must restart at 1",
        id="ranks-descend"),
    pytest.param("rag2026-0\tQ0\tshard_00459_61697\tone\t12.5000\trun\n",
                 "rank 'one' is not an integer", id="non-integer-rank"),
    # --- scores non-increasing within a topic ---
    pytest.param(
        "rag2026-0\tQ0\tshard_00459_61697\t1\t11.0000\trun\n"
        "rag2026-0\tQ0\tshard_01012_88420\t2\t12.0000\trun\n",
        "score 12.0 increased over the previous row's 11.0",
        id="score-increases-within-topic"),
    pytest.param("rag2026-0\tQ0\tshard_00459_61697\t1\tbest\trun\n",
                 "score 'best' is not numeric", id="non-numeric-score"),
    # --- ClimbMix docids ---
    pytest.param(
        "rag2026-0\tQ0\tmsmarco_v2.1_doc_51_104#4_2314\t1\t12.5000\trun\n",
        "looks like an MS MARCO segment id",
        id="msmarco-segment-id"),
    pytest.param("rag2026-0\tQ0\tshard_00459_61697_p3\t1\t12.5000\trun\n",
                 "is not a ClimbMix document id",
                 id="chunk-id-instead-of-docid"),
    pytest.param("rag2026-0\tQ0\t12345\t1\t12.5000\trun\n",
                 "is not a ClimbMix document id", id="bare-numeric-docid"),
    pytest.param("rag2026-0\tQ0\tshard_XX_1\t1\t12.5000\trun\n",
                 "is not a ClimbMix document id", id="non-numeric-shard"),
    # --- topic blocks contiguous ---
    pytest.param(
        "a\tQ0\tshard_00459_61697\t1\t12.5000\trun\n"
        "b\tQ0\tshard_01012_88420\t1\t11.5000\trun\n"
        "a\tQ0\tshard_00210_44018\t2\t10.5000\trun\n",
        "rows are not contiguous",
        id="interleaved-topics"),
])
def test_non_conforming_cases(text: str, fragment: str) -> None:
    """Each rule violation is detected and named.

    Asserting on a message fragment (not just ``errs != []``) is what proves the
    validator caught *this* rule rather than tripping over something incidental in
    the fixture.
    """
    errs = validate_runfile(text)

    assert any(fragment in e for e in errs), \
        f"expected a violation containing {fragment!r}, got {errs!r}"


@pytest.mark.parametrize("text, fragment", [
    # Each row is the *conforming* counterpart of one non-conforming case above,
    # chosen to sit as close to the rule's boundary as the spec allows.
    pytest.param("rag2026-0 Q0 shard_00459_61697 1 12.5 my-run\n",
                 "expected 6", id="exactly-six-columns"),
    pytest.param("rag2026-0\tQ0\tshard_00459_61697\t1\t12.5000\trun\n",
                 "must be the literal", id="literal-Q0"),
    pytest.param("a\tQ0\tshard_00459_61697\t1\t2.0000\trun\n"
                 "b\tQ0\tshard_01012_88420\t1\t9.0000\trun\n",
                 "must restart at 1",
                 id="second-topic-restarts-at-1-with-a-higher-score"),
    pytest.param("a\tQ0\tshard_00459_61697\t1\t5.0000\trun\n"
                 "a\tQ0\tshard_01012_88420\t2\t5.0000\trun\n",
                 "increased over", id="equal-scores-are-non-increasing"),
    pytest.param("a\tQ0\tshard_00459_61697\t1\t5.0000\trun\n",
                 "MS MARCO", id="climbmix-docid-has-no-hash"),
    pytest.param("a\tQ0\tshard_00459_61697\t1\t5.0000\trun\n"
                 "a\tQ0\tshard_01012_88420\t2\t4.0000\trun\n"
                 "b\tQ0\tshard_00210_44018\t1\t3.0000\trun\n",
                 "not contiguous", id="topic-blocks-are-contiguous"),
])
def test_conforming_counterpart_reports_no_rule_violation(text: str,
                                                          fragment: str) -> None:
    """The mirror half: no false positives at each rule's boundary.

    Score monotonicity is per topic, so a *higher* first score on a later topic is
    legal — that pairing (``second-topic-restarts-at-1-with-a-higher-score``) is
    the one a naive global-monotonicity check would get wrong.
    """
    errs = validate_runfile(text)

    assert errs == []
    assert not any(fragment in e for e in errs)


def test_empty_file_is_reported() -> None:
    """An empty or whitespace-only runfile is a violation, not vacuous success.

    This is the failure mode a `[]`-means-valid validator cannot catch: a run that
    crashed before writing any row, or wrote to the wrong path, produces a file
    that satisfies every per-row rule because there are no rows. Submitting it
    scores zero on every topic, and nothing upstream would have complained.
    """
    assert validate_runfile("") == ["runfile is empty"]
    assert validate_runfile("\n\n  \n") == ["runfile is empty"]


def test_multiple_violations_are_all_reported() -> None:
    """Like ``validate_rag_output``, validation does not stop at the first error."""
    text = ("rag2026-0\tq0\t12345\t2\t12.5000\trun\n"
            "rag2026-0\tQ0\tshard_01012_88420\t3\t99.0000\trun\n")

    errs = validate_runfile(text)

    assert len(errs) >= 4
    assert any("literal 'Q0'" in e for e in errs)
    assert any("not a ClimbMix document id" in e for e in errs)
    assert any("must restart at 1" in e for e in errs)
    assert any("increased over" in e for e in errs)


def test_violations_name_the_line_number() -> None:
    """Line numbers are 1-based and point at the offending row, so a 100k-line
    runfile can actually be debugged."""
    text = ("rag2026-0\tQ0\tshard_00459_61697\t1\t12.5000\trun\n"
            "rag2026-0\tQ0\tshard_01012_88420\t2\t11.5000\trun\n"
            "rag2026-0\tQ0\tnot-a-docid\t3\t10.5000\trun\n")

    errs = validate_runfile(text)

    assert len(errs) == 1
    assert errs[0].startswith("line 3:")


@pytest.mark.parametrize("docid, ok", [
    pytest.param("shard_00459_61697", True, id="canonical"),
    pytest.param("shard_0_0", True, id="short-shard-and-row"),
    pytest.param("shard_00459_61697_p1", False, id="chunk-id"),
    pytest.param("shard_00459", False, id="missing-row"),
    pytest.param("SHARD_00459_61697", False, id="uppercased"),
    pytest.param("shard_00459_61697 ", False, id="trailing-space"),
])
def test_climbmix_docid_pattern(docid: str, ok: bool) -> None:
    """The docid regex, exercised at its boundaries.

    A docid that does not match cannot be resolved against the corpus, so the row
    is unjudgeable — it scores as if it were never retrieved. The parameters cover
    the three ways we can produce one: a chunk id that was never projected to its
    parent (``_p1`` — the most likely bug, see
    ``test_chunk_level_hits_must_be_projected_to_parent_docids``), a truncated id
    missing the row component, and whitespace/case damage from a hand-edited or
    spreadsheet-round-tripped file. ``shard_0_0`` pins that the numeric parts are
    not zero-padded to a fixed width.
    """
    assert bool(CLIMBMIX_DOCID_RE.match(docid)) is ok


# ---------------------------------------------------------------------------
# Against real retrieval output
# ---------------------------------------------------------------------------
def test_runfile_from_real_search_hits_is_conforming(
        fake_hits: Callable[..., list[dict[str, Any]]]) -> None:
    """A runfile built from ``SearchHit`` dicts conforms as-is.

    ``fake_hits`` uses the real ``make_hit``, so the docids, ranks and descending
    scores here are the shapes a backend actually produces.
    """
    hits = fake_hits(4)
    rows = rows_from_hits("rag2026-37", hits, RUN_ID)

    assert validate_runfile(format_runfile(rows)) == []
    assert [r[2] for r in rows] == [1, 2, 3, 4]


def test_chunk_level_hits_must_be_projected_to_parent_docids(
        fake_hits: Callable[..., list[dict[str, Any]]]) -> None:
    """A chunk-level run submits parent ClimbMix docids, not chunk ids.

    ``rows_from_hits`` reads ``hit["docid"]``; the failing half of this test shows
    what happens if a writer reaches for ``hit["id"]`` instead — every row is
    rejected as a non-ClimbMix id. That mistake is exactly the one the spec's "keep
    final references tied to ClimbMix document IDs" rule exists to prevent, and it
    is unenforced today because no ``src/`` writer exists.
    """
    hits = fake_hits(2, ids=("shard_00000_3908_p1", "shard_00000_3908_p2"))

    ok = format_runfile(rows_from_hits("rag2026-37", hits, RUN_ID))
    wrong = format_runfile([("rag2026-37", h["id"], i, h["score"], RUN_ID)
                            for i, h in enumerate(hits, start=1)])

    assert validate_runfile(ok) == []
    assert all("shard_00000_3908" in line and "_p" not in line
               for line in ok.splitlines())
    assert len(validate_runfile(wrong)) == 2


def test_runfile_from_run_search_tool_results_is_conforming(
        stub_search_tool: dict[str, list[dict[str, Any]]]) -> None:
    """End to end through the agent-facing tool envelope: the ``docid`` field of
    each result is directly runfile-ready."""
    from tools.search_tool import run_search_tool

    payload = json.loads(run_search_tool("congestion pricing", k=4,
                                         search_engine="keyword"))
    rows = [("rag2026-37", r["docid"], r["rank"], r["score"], RUN_ID)
            for r in payload["results"]]

    assert validate_runfile(format_runfile(rows)) == []


def test_two_topics_from_the_same_engine_share_a_run_id(
        fake_hits: Callable[..., list[dict[str, Any]]]) -> None:
    """``run_id`` is "a stable identifier for the submitted run" — one value for
    the whole file, not per topic."""
    rows = (rows_from_hits("rag2026-0", fake_hits(3), RUN_ID)
            + rows_from_hits("rag2026-37", fake_hits(2), RUN_ID))
    text = format_runfile(rows)

    assert validate_runfile(text) == []
    assert {line.split("\t")[5] for line in text.splitlines()} == {RUN_ID}
