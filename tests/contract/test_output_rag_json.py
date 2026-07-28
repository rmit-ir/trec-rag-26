"""Contract: the submitted RAG object (`rag_output_trec_rag_2026.jsonl`).

`rag-task.md` states the output shape once and then restates it twice more as
"Answer Rules" and "Validation Rules". This module walks those rules one at a
time against the real implementation (``ragrun.outputs``), because they are the
rules an organizer's validator will run — a violation here is a rejected
submission, not a quality regression.

Two rules deserve the emphasis they get below:

- **"Do not add extra keys to the ``metadata`` object."** Diagnostics are exactly
  what a research repo accumulates, so the metadata key set is asserted as an
  equality, not a superset — and ``submission_output`` is asserted to strip the
  rich ``trace`` that ``save_run`` deliberately embeds in the internal artifact.
- **The 1024-word budget**, tested at 1024 (valid) and 1025 (violation), since an
  off-by-one there is invisible in every normal run.

The final test pair closes the loop on real code rather than hand-built fixtures:
``ali_deepresearch.answer_format.format_answer(..., llm=None)`` is the
deterministic formatter every offline run uses, and its output must satisfy
``validate_rag_output`` with no post-processing.
"""
from __future__ import annotations

import json
from typing import Any

import pytest

from ali_deepresearch.answer_format import format_answer
from ragrun import build_rag_output, submission_output, validate_rag_output

from conftest import CLIMBMIX_DOCIDS

pytestmark = pytest.mark.contract

METADATA_KEYS = {"team_id", "narrative_id", "narrative", "run_id", "run_desc"}

NARRATIVE = (
    "Can you help me understand whether congestion pricing is a credible and "
    "fair way to fund the MTA?"
)


def make_output(references: list[str] | Any | None = None,
                answer: list[dict[str, Any]] | Any | None = None,
                **overrides: Any) -> dict[str, Any]:
    """A valid RAG output object, built by the REAL ``build_rag_output``.

    Tests mutate the result to construct exactly one violation each, so the
    "valid" baseline is never re-implemented by hand.
    """
    kwargs: dict[str, Any] = {
        "narrative_id": "rag2026-37",
        "narrative": NARRATIVE,
        "run_id": "contract-run",
        "run_desc": "BM25 top-100 ClimbMix retrieval with cited sentences.",
        "references": list(CLIMBMIX_DOCIDS[:2]) if references is None
        else references,
        "answer": [
            {"text": "Toll revenue is dedicated to the capital plan.",
             "citations": [0]},
            {"text": "Peak-period drivers skew higher-income than riders.",
             "citations": [1]},
        ] if answer is None else answer,
    }
    kwargs.update(overrides)
    return build_rag_output(**kwargs)


def to_jsonl(objects: list[dict[str, Any]]) -> str:
    """Serialize outputs the way a submission file is written.

    ``ensure_ascii=False`` matches ``ragrun.save_run``; the point of the helper is
    that it is the *only* newline-inserting step, so ``test_jsonl_*`` below can
    prove one-object-per-line holds for arbitrary answer text.
    """
    return "".join(
        json.dumps(submission_output(obj), ensure_ascii=False) + "\n"
        for obj in objects)


# ---------------------------------------------------------------------------
# build_rag_output: the exact shape
# ---------------------------------------------------------------------------
def test_build_rag_output_top_level_keys() -> None:
    """Exactly ``metadata``, ``references``, ``answer`` — nothing else."""
    obj = make_output()

    assert set(obj) == {"metadata", "references", "answer"}


def test_build_rag_output_metadata_keys_are_exactly_five() -> None:
    """"Do not add extra keys to the ``metadata`` object" — asserted as equality."""
    obj = make_output()

    assert set(obj["metadata"]) == METADATA_KEYS
    assert obj["metadata"]["narrative_id"] == "rag2026-37"
    assert obj["metadata"]["narrative"] == NARRATIVE
    assert obj["metadata"]["team_id"] == "rmit-ir"      # repo default


def test_build_rag_output_team_id_is_overridable() -> None:
    """``team_id`` must be settable per run, not baked into the builder.

    It is the field the organizers key submissions on, and it differs between a
    real submission and any shared/borrowed run we generate for comparison. A
    hardcoded default that could not be overridden would attribute someone else's
    baseline to us.
    """
    assert make_output(team_id="other-team")["metadata"]["team_id"] == "other-team"


def test_build_rag_output_copies_references_list() -> None:
    """The caller's list is copied, so later mutation of the retrieval state
    cannot retroactively edit an already-built submission object."""
    refs = list(CLIMBMIX_DOCIDS[:2])
    obj = make_output(references=refs)

    refs.append("shard_99999_1")

    assert obj["references"] == list(CLIMBMIX_DOCIDS[:2])


def test_build_rag_output_splats_a_string_reference_current_behaviour() -> None:
    """CURRENT BEHAVIOUR / GAP: passing a bare docid string as ``references``
    silently becomes a list of its characters.

    ``build_rag_output`` does ``list(references)``, so
    ``references="shard_00459_61697"`` yields 17 single-character "docids" instead
    of raising or wrapping. ``validate_rag_output`` then reports them as uncited
    references (not as a type error), which is a confusing diagnosis of a simple
    caller mistake. Pinned rather than fixed; a ``str`` guard in
    ``build_rag_output`` would be the one-line change.
    """
    obj = build_rag_output(
        narrative_id="rag2026-37", narrative=NARRATIVE, run_id="r",
        run_desc="d", references="shard_00459_61697",
        answer=[{"text": "x", "citations": [0]}])

    assert obj["references"] == list("shard_00459_61697")
    assert validate_rag_output(obj) == [
        "references never cited: indices "
        f"{sorted(range(1, len('shard_00459_61697')))}"]


def test_build_rag_output_is_json_serializable() -> None:
    """A round-trip through JSON must be lossless, so the object contains only
    JSON primitives.

    The submission is JSONL, so anything the builder lets through that
    ``json.dumps`` cannot encode (a ``Path``, a ``set``, a numpy scalar from a
    reranker) fails at write time — after the expensive part of the run. Equality
    after the round-trip additionally rules out silent lossy coercions such as a
    tuple becoming a list in a place a later comparison depends on.
    """
    obj = make_output()

    assert json.loads(json.dumps(obj, ensure_ascii=False)) == obj


def test_valid_object_has_no_violations() -> None:
    """The baseline every other case in this module is measured against.

    All the negative tests below assert that a specific mutation of
    ``make_output()`` produces a violation; without this test a validator that
    rejected *everything* would still pass them all. It also pins that the
    builder's own output satisfies the validator — the two live in the same
    module and can drift apart.
    """
    assert validate_rag_output(make_output()) == []


# ---------------------------------------------------------------------------
# validate_rag_output: one case per Validation Rule
# ---------------------------------------------------------------------------
def _drop_metadata_key(key: str) -> dict[str, Any]:
    obj = make_output()
    del obj["metadata"][key]
    return obj


def _add_metadata_key(key: str, value: Any = "diagnostic") -> dict[str, Any]:
    obj = make_output()
    obj["metadata"][key] = value
    return obj


def _long_answer(words: int) -> dict[str, Any]:
    """One-sentence answer of exactly ``words`` words (whitespace-split)."""
    return make_output(references=[CLIMBMIX_DOCIDS[0]],
                       answer=[{"text": " ".join(["revenue"] * words),
                                "citations": [0]}])


# Each row: (rule label, object with exactly one violation, expected message).
VIOLATION_CASES = [
    pytest.param(
        _drop_metadata_key("run_desc"),
        "metadata missing keys: ['run_desc']",
        id="metadata-missing-key"),
    pytest.param(
        _drop_metadata_key("narrative"),
        "metadata missing keys: ['narrative']",
        id="metadata-missing-narrative"),
    pytest.param(
        _add_metadata_key("prompt_version"),
        "metadata has extra keys (not allowed): ['prompt_version']",
        id="metadata-extra-key"),
    pytest.param(
        _add_metadata_key("generation_type"),
        "metadata has extra keys (not allowed): ['generation_type']",
        id="metadata-extra-diagnostic-key"),
    pytest.param(
        # NB: constructed by hand rather than through ``build_rag_output``,
        # which would coerce the bare string with ``list(...)`` — see
        # ``test_build_rag_output_splats_a_string_reference_current_behaviour``.
        {**make_output(), "references": "shard_00459_61697"},
        "references must be a list of docid strings",
        id="references-not-a-list"),
    pytest.param(
        make_output(references=[{"docid": CLIMBMIX_DOCIDS[0]}],
                    answer=[{"text": "x", "citations": []}]),
        "references must be a list of docid strings",
        id="references-not-strings"),
    pytest.param(
        make_output(references=[], answer=[]),
        "answer must be a non-empty list",
        id="answer-empty"),
    pytest.param(
        make_output(references=[], answer={"text": "x", "citations": []}),
        "answer must be a non-empty list",
        id="answer-not-a-list"),
    pytest.param(
        make_output(references=list(CLIMBMIX_DOCIDS[:4]),
                    answer=[{"text": "Four citations.",
                             "citations": [0, 1, 2, 3]}]),
        "answer[0].citations must be a list of at most 3 indices",
        id="more-than-three-citations"),
    pytest.param(
        make_output(references=[CLIMBMIX_DOCIDS[0]],
                    answer=[{"text": "Cites index 0.", "citations": [0]},
                            {"text": "Cites a missing reference.",
                             "citations": [7]}]),
        "answer[1] cites invalid reference index 7",
        id="citation-index-out-of-range"),
    pytest.param(
        make_output(references=[CLIMBMIX_DOCIDS[0]],
                    answer=[{"text": "Cites index 0.", "citations": [0]},
                            {"text": "Negative index.", "citations": [-1]}]),
        "answer[1] cites invalid reference index -1",
        id="citation-negative"),
    pytest.param(
        make_output(references=[CLIMBMIX_DOCIDS[0]],
                    answer=[{"text": "Cites index 0.", "citations": [0]},
                            {"text": "Stringly typed index.",
                             "citations": ["0"]}]),
        "answer[1] cites invalid reference index '0'",
        id="citation-non-int-string"),
    pytest.param(
        make_output(references=[CLIMBMIX_DOCIDS[0]],
                    answer=[{"text": "Cites index 0.", "citations": [0]},
                            {"text": "Float index.", "citations": [0.0]}]),
        "answer[1] cites invalid reference index 0.0",
        id="citation-non-int-float"),
    pytest.param(
        make_output(references=list(CLIMBMIX_DOCIDS[:3]),
                    answer=[{"text": "Only the first two are cited.",
                             "citations": [0, 1]}]),
        "references never cited: indices [2]",
        id="reference-never-cited"),
    pytest.param(
        make_output(answer=[{"text": "Missing the citations key."}]),
        "answer[0] must have 'text' and 'citations'",
        id="answer-item-missing-citations"),
    pytest.param(
        make_output(answer=[{"citations": [0, 1]}]),
        "answer[0] must have 'text' and 'citations'",
        id="answer-item-missing-text"),
    pytest.param(
        _long_answer(1025),
        "answer is 1025 words (max 1024)",
        id="over-word-budget"),
]


@pytest.mark.parametrize("obj, message", VIOLATION_CASES)
def test_validation_rule_produces_its_violation(obj: dict[str, Any],
                                                message: str) -> None:
    """Each Validation Rule yields its specific, actionable message.

    Asserting the exact string (not just "some violation") is deliberate: the
    violations file is what a human reads when a run is rejected, and a reworded
    or merged message is a real regression in that workflow.
    """
    errs = validate_rag_output(obj)

    assert message in errs, f"expected {message!r} in {errs!r}"


@pytest.mark.parametrize("obj, message", VIOLATION_CASES)
def test_valid_object_never_reports_that_violation(obj: dict[str, Any],
                                                   message: str) -> None:
    """The mirror half of the table: a conforming object is silent about the rule."""
    assert message not in validate_rag_output(make_output())


def test_missing_metadata_object_is_reported() -> None:
    """``metadata`` absent entirely: reported as missing, then as missing keys —
    validation does not stop at the first error, so one bad run surfaces
    everything wrong with it in a single pass."""
    obj = make_output()
    del obj["metadata"]

    errs = validate_rag_output(obj)

    assert "metadata missing or not an object" in errs
    assert f"metadata missing keys: {sorted(METADATA_KEYS)}" in errs


@pytest.mark.parametrize("words, expect_violation", [
    pytest.param(1023, False, id="1023-words-ok"),
    pytest.param(1024, False, id="1024-words-exactly-at-the-limit"),
    pytest.param(1025, True, id="1025-words-over"),
])
def test_word_budget_boundary(words: int, expect_violation: bool) -> None:
    """"Every RAG answer must be no more than 1024 words" is INCLUSIVE of 1024.

    Both spec statements ("at or below 1024 words per topic" in Answer Rules, "no
    more than 1024 words" in Validation Rules) make 1024 legal, so the comparison
    must be ``> 1024`` and not ``>= 1024``. The boundary is tested at 1023/1024/1025
    because an off-by-one here is invisible in every normal run — real answers land
    far under the cap — and only surfaces on the one verbose topic in a submission,
    where it either wrongly rejects a valid answer or lets an over-length one
    through to an organizer-side rejection.
    """
    errs = validate_rag_output(_long_answer(words))

    assert bool(errs) is expect_violation
    if expect_violation:
        assert errs == [f"answer is {words} words (max 1024)"]


def test_word_budget_counts_across_all_sentences() -> None:
    """The budget is per topic ("full response"), not per sentence."""
    refs = [CLIMBMIX_DOCIDS[0]]
    sentences = [{"text": " ".join(["word"] * 513), "citations": [0]}
                 for _ in range(2)]

    errs = validate_rag_output(make_output(references=refs, answer=sentences))

    assert errs == ["answer is 1026 words (max 1024)"]


@pytest.mark.parametrize("citations", [
    pytest.param([], id="zero-citations"),
    pytest.param([0], id="one-citation"),
    pytest.param([0, 1], id="two-citations"),
    pytest.param([0, 1, 2], id="three-citations-is-the-max"),
])
def test_up_to_three_citations_is_allowed(citations: list[int]) -> None:
    """"no more than three reference positions" — three is legal.

    Note an uncited sentence is legal too; only an uncited *reference* is not.
    """
    refs = list(CLIMBMIX_DOCIDS[:3])
    answer = [{"text": "Sentence under test.", "citations": citations},
              {"text": "Mops up any reference the first sentence skipped.",
               "citations": [c for c in (0, 1, 2) if c not in citations][:3]}]

    assert validate_rag_output(make_output(references=refs,
                                           answer=answer)) == []


def test_duplicate_docid_in_references_is_not_flagged_current_behaviour() -> None:
    """CURRENT BEHAVIOUR / GAP: the same docid twice in ``references`` passes.

    The spec's ``references`` is an "ordered list of retrieved ClimbMix document
    IDs cited by the answer"; it never forbids duplicates explicitly, and
    ``validate_rag_output`` only checks positional coverage. So a formatter bug
    that emitted a docid twice would ship. ``format_answer`` dedupes upstream
    (``dict.fromkeys``), which is why this has never bitten us.
    """
    obj = make_output(references=[CLIMBMIX_DOCIDS[0], CLIMBMIX_DOCIDS[0]],
                     answer=[{"text": "Both positions cited.",
                              "citations": [0, 1]}])

    assert validate_rag_output(obj) == []


def test_non_string_answer_text_raises_current_behaviour() -> None:
    """CURRENT BEHAVIOUR / GAP: a non-string ``answer[].text`` crashes the
    validator instead of being reported as a violation.

    ``total_words += len(sent["text"].split())`` runs before any type check, so
    ``{"text": 123, "citations": [0]}`` raises ``AttributeError`` out of
    ``validate_rag_output`` — and therefore out of ``save_run``, losing the run's
    artifacts. Only reachable from a hand-written or LLM-parsed output object
    (``format_answer`` always ``str()``s the text), but it is a real hole.
    """
    obj = make_output(references=[CLIMBMIX_DOCIDS[0]],
                      answer=[{"text": 123, "citations": [0]}])

    with pytest.raises(AttributeError):
        validate_rag_output(obj)


def test_bool_citation_index_is_accepted_current_behaviour() -> None:
    """CURRENT BEHAVIOUR: ``True`` passes as citation index 1.

    ``isinstance(True, int)`` is ``True`` in Python, so a JSON ``true`` in a
    citations array validates as index 1. Harmless in practice (JSON produced by
    our own formatters never contains booleans there) and the fix would be
    ``type(c) is not int``; pinned so the quirk is documented rather than
    rediscovered.
    """
    obj = make_output(references=list(CLIMBMIX_DOCIDS[:2]),
                      answer=[{"text": "Cites 0 and a boolean.",
                               "citations": [0, True]}])

    assert validate_rag_output(obj) == []


# ---------------------------------------------------------------------------
# submission_output: the organizer-facing projection
# ---------------------------------------------------------------------------
def test_submission_output_strips_trace() -> None:
    """``save_run`` embeds the rich trace in the internal artifact; the submission
    must not carry it (nor any other non-spec top-level key)."""
    obj = make_output()
    obj["trace"] = {"schema_version": "trec-rag-trace/2", "steps": [{"id": "x"}]}
    obj["debug_engine_stats"] = {"semantic": 3}

    projected = submission_output(obj)

    assert set(projected) == {"metadata", "references", "answer"}
    assert "trace" not in json.dumps(projected)
    assert "debug_engine_stats" not in json.dumps(projected)


def test_submission_output_strips_extra_answer_item_keys() -> None:
    """Per-sentence diagnostics (support scores, source spans) are dropped too."""
    obj = make_output(answer=[{"text": "Grounded sentence.", "citations": [0],
                               "support_score": 0.91, "source_span": [10, 40]}],
                      references=[CLIMBMIX_DOCIDS[0]])

    projected = submission_output(obj)

    assert projected["answer"] == [{"text": "Grounded sentence.",
                                    "citations": [0]}]


def test_submission_output_is_a_deep_enough_copy() -> None:
    """Mutating the projection must not write back into the saved run object."""
    obj = make_output()
    projected = submission_output(obj)

    projected["metadata"]["run_id"] = "mutated"
    projected["references"].append("shard_99999_1")
    projected["answer"][0]["citations"].append(2)

    assert obj["metadata"]["run_id"] == "contract-run"
    assert obj["references"] == list(CLIMBMIX_DOCIDS[:2])
    assert obj["answer"][0]["citations"] == [0]


def test_submission_output_is_stable_across_calls() -> None:
    """Byte-stable: two projections of the same object serialize identically
    (dict order is construction order, and construction order is fixed)."""
    obj = make_output()

    first = json.dumps(submission_output(obj), ensure_ascii=False)
    second = json.dumps(submission_output(obj), ensure_ascii=False)

    assert first == second
    assert first.startswith('{"metadata": {"team_id": ')


def test_submission_output_still_validates() -> None:
    """Stripping the rich fields must not strip anything the spec requires.

    ``submission_output`` is the strict projection: it drops our internal
    ``trace`` and rebuilds each sentence from ``text``/``citations`` only. That
    projection is the last transform before the file leaves the repo, so if it
    dropped a required key the local validation on the full object would still
    pass and the *submitted* object would be malformed. A ``trace`` is attached
    here specifically so the test fails if the projection ever passes it through.
    """
    obj = make_output()
    obj["trace"] = {"steps": []}

    assert validate_rag_output(submission_output(obj)) == []


# ---------------------------------------------------------------------------
# JSONL file shape
# ---------------------------------------------------------------------------
def test_jsonl_is_one_object_per_line() -> None:
    """"must be valid JSONL, with one complete object per line", and "every input
    topic must have exactly one RAG object"."""
    topics = [("rag2026-0", "First need."), ("rag2026-1", "Second need."),
              ("rag2026-37", NARRATIVE)]
    objects = [make_output(narrative_id=qid, narrative=text)
               for qid, text in topics]

    text = to_jsonl(objects)
    lines = text.splitlines()

    assert text.endswith("\n")
    assert len(lines) == len(topics)
    parsed = [json.loads(line) for line in lines]          # independently loadable
    assert [p["metadata"]["narrative_id"] for p in parsed] == \
        [qid for qid, _ in topics]
    assert all(validate_rag_output(p) == [] for p in parsed)


@pytest.mark.parametrize("raw_text", [
    pytest.param("Line one.\nLine two.", id="newline"),
    pytest.param("Column one\tcolumn two.", id="tab"),
    pytest.param("Carriage\r\nreturn.", id="crlf"),
    pytest.param("Vertical\x0btab and form\x0cfeed.", id="vt-ff"),
])
def test_jsonl_line_integrity_with_control_chars_in_answer_text(
        raw_text: str) -> None:
    """A raw newline inside ``answer[].text`` must not split a JSONL record.

    ``json.dumps`` escapes ASCII control characters, so this holds structurally —
    the test pins it because the failure mode (a half-object line) makes the whole
    submission unparseable, and a hand-rolled writer that formatted with f-strings
    would hit it immediately.
    """
    obj = make_output(references=[CLIMBMIX_DOCIDS[0]],
                      answer=[{"text": raw_text, "citations": [0]}])

    text = to_jsonl([obj, make_output()])
    lines = text.split("\n")[:-1]                       # JSONL: split on \n only

    assert len(lines) == 2
    assert "\n" not in lines[0]
    assert json.loads(lines[0])["answer"][0]["text"] == raw_text


@pytest.mark.parametrize("separator", [" ", " "])
def test_unicode_line_separators_stay_literal_current_behaviour(
        separator: str) -> None:
    """CURRENT BEHAVIOUR / hazard: U+2028/U+2029 are NOT escaped by
    ``ensure_ascii=False``, so they survive into the JSONL line verbatim.

    JSONL readers that split on ``"\\n"`` (including ``json.loads`` per line, and
    every reader we use) are unaffected — the record is still one physical line by
    the LF definition. But Python's ``str.splitlines()`` *does* break on these
    code points, so any tooling that reads the submission with ``splitlines()`` or
    ``for line in file`` on a text stream in some locales would see a truncated
    record. ``ensure_ascii=True`` would escape them; ``save_run`` uses
    ``ensure_ascii=False`` for readable Unicode narratives, so the risk is
    accepted and pinned here.
    """
    obj = make_output(references=[CLIMBMIX_DOCIDS[0]],
                      answer=[{"text": f"Paragraph{separator}separator.",
                               "citations": [0]}])

    line = to_jsonl([obj]).rstrip("\n")

    assert separator in line                       # literal, not  -escaped
    assert len(line.split("\n")) == 1              # still one JSONL record
    assert len(line.splitlines()) == 2             # ...but splitlines disagrees
    assert json.loads(line)["answer"][0]["text"] == \
        f"Paragraph{separator}separator."


def test_jsonl_keeps_unicode_unescaped_but_parseable() -> None:
    """``ensure_ascii=False`` (what ``save_run`` uses) still round-trips."""
    obj = make_output(narrative="I’m weighing tradeoffs — café owners.")

    line = to_jsonl([obj]).splitlines()[0]

    assert "’" in line                                     # not ’-escaped
    assert json.loads(line)["metadata"]["narrative"] == \
        "I’m weighing tradeoffs — café owners."


# ---------------------------------------------------------------------------
# The real formatter: format_answer(llm=None) -> a valid submission object
# ---------------------------------------------------------------------------
FORMATTER_DRAFTS = [
    pytest.param(
        "## Findings\n\n**Congestion pricing** dedicates toll revenue to the "
        "MTA capital plan. Early data showed traffic below the pre-toll "
        "baseline. Air-quality monitoring was written into the environmental "
        "assessment.",
        list(CLIMBMIX_DOCIDS),
        id="markdown-draft-4-docids"),
    pytest.param(
        "One single sentence answer.",
        list(CLIMBMIX_DOCIDS[:1]),
        id="one-sentence-one-docid"),
    pytest.param(
        "Alpha. Beta. Gamma. Delta. Epsilon.",
        list(CLIMBMIX_DOCIDS),
        id="more-sentences-than-docids"),
    pytest.param(
        "- bullet one\n- bullet two\n\n```code fence dropped```\n",
        list(CLIMBMIX_DOCIDS[:2]),
        id="bullets-and-code-fence"),
    pytest.param(
        "",
        list(CLIMBMIX_DOCIDS[:2]),
        id="empty-draft-falls-back-to-placeholder"),
]


@pytest.mark.parametrize("draft, docids", FORMATTER_DRAFTS)
def test_format_answer_heuristic_output_validates(draft: str,
                                                 docids: list[str]) -> None:
    """The deterministic (``llm=None``) formatter's output passes every rule.

    This is the assertion that matters most operationally: it exercises the path a
    real offline run takes, so "every reference cited at least once" and "citations
    are valid zero-indexed positions" are proven for produced output, not for a
    fixture written to satisfy them.
    """
    references, answer = format_answer(draft, docids, llm=None)
    obj = build_rag_output(
        narrative_id="rag2026-37", narrative=NARRATIVE, run_id="contract-run",
        run_desc="deterministic formatter", references=references, answer=answer)

    assert validate_rag_output(obj) == []
    assert answer, "formatter must emit at least one sentence"

    cited = {c for sentence in answer for c in sentence["citations"]}
    assert cited == set(range(len(references))), "every reference must be cited"
    assert all(isinstance(c, int) and 0 <= c < len(references)
               for c in cited)
    assert all(len(sentence["citations"]) <= 3 for sentence in answer)
    assert all(ref in docids for ref in references)         # doc-level, allow-listed


def test_format_answer_never_cites_outside_the_allow_list() -> None:
    """"Do not cite documents that are missing from ``references``" — and
    ``references`` may only contain docids retrieval actually returned."""
    allowed = list(CLIMBMIX_DOCIDS[:2])

    references, answer = format_answer(
        "First claim. Second claim.", allowed, llm=None)

    assert set(references) <= set(allowed)


def test_format_answer_output_is_jsonl_ready() -> None:
    """End to end: formatter -> build -> submission projection -> one JSONL line."""
    references, answer = format_answer(
        "First claim here. Second claim here.", list(CLIMBMIX_DOCIDS[:3]),
        llm=None)
    obj = build_rag_output(
        narrative_id="rag2026-37", narrative=NARRATIVE, run_id="contract-run",
        run_desc="deterministic formatter", references=references, answer=answer)

    line = to_jsonl([obj]).rstrip("\n")

    assert "\n" not in line
    assert set(json.loads(line)) == {"metadata", "references", "answer"}
