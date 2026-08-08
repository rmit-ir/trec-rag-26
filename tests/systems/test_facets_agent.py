"""End-to-end coverage for ``src/systems/facets_agent`` — a thin configuration
of the shared ``agent_harness.agent.run_agent`` staged-context harness.

``facets_agent.agent.run_agent`` reimplements nothing: it renders this
package's own minimal prompt and calls straight into
``agent_harness.agent.run_agent`` with ``system_name="facets_agent"``, the
three natural-language retrieval engines enabled (``ssr``/``lucene_bool`` are
no longer supported), and a wider default ``k`` for the ``hybrid`` engine. The
loop mechanics themselves (staged/committed evidence, the final-report
contract, citation parsing) are already covered by
``tests/systems/test_aus_agent.py`` against the same shared code — this file
only proves facets_agent's OWN configuration actually reaches the harness:
its artifacts land under its own system name, its tool definition advertises
exactly those three engines, and an omitted ``k`` on a ``hybrid`` call gets
the wider default rather than the plain one.

Provider substitution follows the same pattern as ``test_aus_agent.py``:
``ScriptedProvider`` stands in for the model, patched onto
``agent_harness.agent.make_provider`` (where the shared harness actually
constructs it) rather than on ``facets_agent.agent`` — the wrapper module
never calls ``make_provider`` itself.
"""
from __future__ import annotations

from typing import Any, Callable

import pytest
from conftest import CLIMBMIX_DOCIDS, ScriptedProvider, model_turn, tool_call

from agent_harness import agent as agent_harness_mod

from facets_agent.agent import DEFAULT_ENGINES, DEFAULT_HYBRID_K, SYSTEM_NAME
from facets_agent.agent import run_agent as facets_run_agent

QID = "mock_facets_001"
QUERY = "How effective is congestion pricing at reducing traffic?"
D = CLIMBMIX_DOCIDS


@pytest.fixture
def drive(monkeypatch: pytest.MonkeyPatch,
          stub_search_tool: dict[str, list[dict[str, Any]]]
          ) -> Callable[..., dict[str, Any]]:
    """Run ``facets_agent.agent.run_agent`` against a scripted provider."""
    def _drive(script: list[dict[str, Any]], *, query_id: str = QID,
               query: str = QUERY, **kwargs: Any) -> dict[str, Any]:
        provider = ScriptedProvider(script)
        monkeypatch.setattr(agent_harness_mod, "make_provider",
                            lambda backend, model: provider)
        kwargs.setdefault("safety_max_rounds", 20)
        summary = facets_run_agent(query_id, query, **kwargs)
        return {"summary": summary, "provider": provider,
                "calls": stub_search_tool}
    return _drive


HAPPY_SCRIPT = [
    model_turn(reasoning=["Search hybrid first; it's the safe default."],
               tool_calls=[tool_call(
                   "search", {"query": "congestion pricing revenue plan",
                              "search_engine": "hybrid"}, id="s1")]),
    model_turn(text="One of those is worth keeping.",
               tool_calls=[tool_call("commit_context", {"documents": [
                   {"docid": D[0], "reason": "revenue allocation"}]}, id="c1")]),
    model_turn(text=f"Toll revenue funds the capital plan [{D[0]}]."),
]


def test_run_writes_valid_artifacts_under_its_own_system_name(
        drive: Callable[..., dict[str, Any]]) -> None:
    """facets_agent must never write into aus_agent's output tree.

    Both systems share the harness code, so the one thing that actually
    distinguishes their artifacts on disk is ``system_name`` reaching
    ``ragrun.save_run`` — this is the regression a copy-paste of aus_agent's
    hardcoded ``"aus_agent"`` string would silently reintroduce.
    """
    from ragrun import validate_rag_output

    result = drive(list(HAPPY_SCRIPT))
    summary = result["summary"]
    assert summary["status"] == "completed"
    paths = summary["paths"]
    assert paths["output"].parent.name == SYSTEM_NAME == "facets_agent"
    assert paths["trajectory"].parent.name == "facets_agent"
    output = __import__("json").loads(paths["output"].read_text())
    assert validate_rag_output(output) == []
    assert output["references"]


def test_only_the_three_nl_engines_are_advertised_to_the_model(
        drive: Callable[..., dict[str, Any]]) -> None:
    """The search tool's enum must list exactly semantic/keyword/hybrid by
    default — ssr/lucene_bool are no longer supported and must not appear."""
    result = drive(list(HAPPY_SCRIPT))
    search_tool_def = next(
        t for t in result["provider"].tools if t["name"] == "search")
    assert (search_tool_def["input_schema"]["properties"]["search_engine"]
            ["enum"]) == DEFAULT_ENGINES
    assert set(DEFAULT_ENGINES) == {"semantic", "keyword", "hybrid"}


def test_hybrid_search_defaults_to_a_wider_k_than_other_engines(
        drive: Callable[..., dict[str, Any]]) -> None:
    """An omitted ``k`` on a ``hybrid`` call must widen to DEFAULT_HYBRID_K.

    The prompt already asks the model to request more results from hybrid
    (its HyDE-style query benefits from a wider net), but the model is not
    guaranteed to comply — this is the code-level guarantee that backs it up.
    """
    result = drive(list(HAPPY_SCRIPT))
    hybrid_calls = result["calls"]["hybrid"]
    assert hybrid_calls, "the scripted hybrid search never reached the engine"
    assert hybrid_calls[0]["k"] == DEFAULT_HYBRID_K


def test_get_documents_tool_is_available(
        drive: Callable[..., dict[str, Any]]) -> None:
    """The fetch-full-document tool must be wired in like aus_agent's."""
    result = drive(list(HAPPY_SCRIPT))
    names = {t["name"] for t in result["provider"].tools}
    assert {"search", "get_documents", "commit_context"} <= names


def test_commit_context_tool_advertises_release(
        drive: Callable[..., dict[str, Any]]) -> None:
    """facets_agent's own extended commit_context, not aus_agent's plain one,
    must reach the model -- otherwise the model has no way to learn the
    ``release`` field exists."""
    result = drive(list(HAPPY_SCRIPT))
    commit_tool = next(
        t for t in result["provider"].tools if t["name"] == "commit_context")
    assert "release" in commit_tool["input_schema"]["properties"]


def test_judge_relevance_is_advertised_by_default(
        drive: Callable[..., dict[str, Any]]) -> None:
    """PLAN.md Phase 4b §7.4: facets_agent opts into the global
    agent_harness judge tool by default -- the model must see it to ever
    choose to call it."""
    result = drive(list(HAPPY_SCRIPT))
    names = {t["name"] for t in result["provider"].tools}
    assert "judge_relevance" in names


def test_judge_relevance_can_be_disabled(
        drive: Callable[..., dict[str, Any]]) -> None:
    """``judge_tool=None`` must actually remove it, proving the default is
    overridable (e.g. for an A/B run with/without the tool)."""
    result = drive(list(HAPPY_SCRIPT), judge_tool=None)
    names = {t["name"] for t in result["provider"].tools}
    assert "judge_relevance" not in names


# A better document (D[1]) shows up on a second search and supersedes the
# first-committed one (D[0]): commit D[0], search again, commit D[1] while
# releasing D[0] in the same call, then cite only D[1].
RELEASE_SCRIPT = [
    model_turn(reasoning=["First pass: search hybrid."],
               tool_calls=[tool_call(
                   "search", {"query": "congestion pricing revenue plan",
                              "search_engine": "hybrid"}, id="s1")]),
    model_turn(text="Keep this for now.",
               tool_calls=[tool_call("commit_context", {"documents": [
                   {"docid": D[0], "reason": "first version of the figure"}]},
                   id="c1")]),
    model_turn(reasoning=["Search again for a more precise source."],
               tool_calls=[tool_call(
                   "search", {"query": "congestion pricing revenue precise "
                                       "figure", "search_engine": "semantic"},
                   id="s2")]),
    model_turn(text="This states the figure more precisely; drop the first.",
               tool_calls=[tool_call("commit_context", {
                   "documents": [{"docid": D[1],
                                  "reason": "states the figure precisely"}],
                   "release": [{"id": D[0],
                                "reason": f"{D[1]} states this more precisely"}],
               }, id="c2")]),
    model_turn(text=f"Toll revenue funds the capital plan [{D[1]}]."),
]


def test_release_drops_a_superseded_document_end_to_end(
        drive: Callable[..., dict[str, Any]]) -> None:
    """The whole release path -- tool schema, apply_commit, ContextLedger
    .release_committed, provider.compact_tool_results -- must be reachable
    through facets_agent's configured harness, not just unit-testable in
    isolation. The superseded document must never reach the final answer
    even though it was committed first."""
    result = drive(list(RELEASE_SCRIPT))
    assert result["summary"]["status"] == "completed"
    assert result["summary"]["n_references"] == 1

    from agent_harness.context import RELEASE_PREFIX

    s1_result = next(
        m for m in result["provider"].raw_messages
        if isinstance(m, dict) and m.get("tool_call_id") == "s1")
    assert RELEASE_PREFIX in s1_result["content"]


# --- Phase 2: tool-carried requirement ledger (PLAN.md §4 phase-2 tests) ---

def test_search_def_requires_requirement_and_advertises_the_run_engines(
        drive: Callable[..., dict[str, Any]]) -> None:
    """The advertised search tool must carry a required `requirement` field
    on top of the run's actual engine enum -- the tool-carried plan-review
    half of the coverage-gap fix rides on this schema reaching the model."""
    result = drive(list(HAPPY_SCRIPT))
    search_tool_def = next(
        t for t in result["provider"].tools if t["name"] == "search")
    schema = search_tool_def["input_schema"]
    assert "requirement" in schema["properties"]
    assert "requirement" in schema["required"]
    assert schema["properties"]["search_engine"]["enum"] == DEFAULT_ENGINES


def test_commit_def_carries_the_coverage_ledger_with_three_value_status(
        drive: Callable[..., dict[str, Any]]) -> None:
    """The advertised commit_context tool must carry `coverage` (with a
    covered/open/unavailable status enum) and `ready_to_report` -- this is
    what the model's pre-report self-check is computed from."""
    result = drive(list(HAPPY_SCRIPT))
    commit_tool = next(
        t for t in result["provider"].tools if t["name"] == "commit_context")
    schema = commit_tool["input_schema"]
    assert "coverage" in schema["properties"]
    assert "ready_to_report" in schema["properties"]
    assert "coverage" in schema["required"]
    assert "ready_to_report" in schema["required"]
    status_schema = (schema["properties"]["coverage"]["items"]["properties"]
                      ["status"])
    assert status_schema["enum"] == ["covered", "open", "unavailable"]


# Same shape as HAPPY_SCRIPT, but the search call names a requirement and the
# commit call restates a full coverage ledger -- proves the whole payload
# round-trips through the harness (dispatch, ContextLedger, the saved trace)
# without needing new dispatch branches, since the underlying handlers only
# read the arguments they already understood and pass the rest through inert.
COVERAGE_SCRIPT = [
    model_turn(reasoning=["Search hybrid for the revenue-plan requirement."],
               tool_calls=[tool_call(
                   "search", {"query": "congestion pricing revenue plan",
                              "search_engine": "hybrid",
                              "requirement": "how congestion pricing revenue "
                                             "is used"}, id="s1")]),
    model_turn(text="One of those is worth keeping.",
               tool_calls=[tool_call("commit_context", {
                   "documents": [{"docid": D[0],
                                  "reason": "revenue allocation"}],
                   "coverage": [{"requirement": "how congestion pricing "
                                                 "revenue is used",
                                 "status": "covered", "note": D[0]}],
                   "ready_to_report": True,
               }, id="c1")]),
    model_turn(text=f"Toll revenue funds the capital plan [{D[0]}]."),
]


def test_a_commit_call_carrying_coverage_completes_and_is_saved_in_the_trace(
        drive: Callable[..., dict[str, Any]]) -> None:
    """An end-to-end run where commit_context carries a coverage payload must
    complete normally, and the payload must be legible in the saved trace --
    that raw-argument record is what PLAN.md §5's Tier 1 metrics read."""
    result = drive(list(COVERAGE_SCRIPT))
    assert result["summary"]["status"] == "completed"
    import json
    output = json.loads(result["summary"]["paths"]["output"].read_text())
    steps = output["trace"]["steps"]
    commit_step = next(
        s for s in steps
        if s.get("type") == "tool_call" and s.get("tool_name") == "commit_context")
    assert commit_step["arguments"]["ready_to_report"] is True
    assert commit_step["arguments"]["coverage"][0]["status"] == "covered"
    search_step = next(
        s for s in steps
        if s.get("type") == "tool_call" and s.get("tool_name") == "search")
    assert search_step["arguments"]["requirement"] == \
        "how congestion pricing revenue is used"


def test_a_commit_call_omitting_coverage_still_completes(
        drive: Callable[..., dict[str, Any]]) -> None:
    """The schema marks `coverage`/`ready_to_report` required as a
    model-compliance forcing function, never a failure mode: the underlying
    handler must still accept and complete a call that omits them, exactly
    like HAPPY_SCRIPT (no coverage payload at all) already proves for the
    plain case -- this test pins that a partially-compliant call (present
    `release`, absent `coverage`) is equally tolerated."""
    script = [
        model_turn(reasoning=["Search hybrid."],
                   tool_calls=[tool_call(
                       "search", {"query": "congestion pricing revenue plan",
                                  "search_engine": "hybrid"}, id="s1")]),
        model_turn(text="Keep this.",
                   tool_calls=[tool_call("commit_context", {"documents": [
                       {"docid": D[0], "reason": "revenue allocation"}]},
                       id="c1")]),
        model_turn(text=f"Toll revenue funds the capital plan [{D[0]}]."),
    ]
    result = drive(script)
    assert result["summary"]["status"] == "completed"
    assert result["summary"]["n_references"] == 1


def test_named_candidate_query_hint_only_appears_when_keyword_is_enabled(
        drive: Callable[..., dict[str, Any]]) -> None:
    """The named-candidate/category engine-assignment sentence only makes
    sense when `keyword` is actually offered -- it must not appear in the
    `query` description for a run that disables `keyword`, mirroring how the
    shared base builder already conditions its own multi-engine sentence."""
    with_keyword = drive(list(HAPPY_SCRIPT), engines=["semantic", "keyword", "hybrid"])
    without_keyword = drive(list(HAPPY_SCRIPT), query_id="mock_facets_002",
                             engines=["semantic", "hybrid"])
    with_desc = next(t for t in with_keyword["provider"].tools
                      if t["name"] == "search")["input_schema"]["properties"]["query"]["description"]
    without_desc = next(t for t in without_keyword["provider"].tools
                         if t["name"] == "search")["input_schema"]["properties"]["query"]["description"]
    assert "named candidate" in with_desc
    assert "named candidate" not in without_desc


# ---------------------------------------------------------------------------
# Phase 4 §7.1 — review.coverage_gate, the default pre_final_hook
# ---------------------------------------------------------------------------
from facets_agent.review import coverage_gate  # noqa: E402


def test_coverage_gate_is_a_noop_when_nothing_was_ever_committed() -> None:
    """No commit_context call yet (e.g. an uncited-report edge case) must not
    crash — ``last_commit_arguments`` is ``None``, not a missing key."""
    assert coverage_gate({"last_commit_arguments": None}) is None


def test_coverage_gate_is_a_noop_when_commit_call_carried_no_coverage() -> None:
    """A commit call that omits ``coverage`` entirely (e.g. a scripted test,
    or a model turn that malformed the field) is accepted, not crashed —
    the schema is a forcing function, never a failure mode, same principle
    as ``tools.py``'s own docstring states for every field it adds."""
    assert coverage_gate({"last_commit_arguments": {"documents": []}}) is None


def test_coverage_gate_is_a_noop_when_every_entry_is_covered_or_unavailable() -> None:
    assert coverage_gate({"last_commit_arguments": {"coverage": [
        {"requirement": "A", "status": "covered", "note": "id_1"},
        {"requirement": "B", "status": "unavailable", "note": "searched, nothing"},
    ]}}) is None


def test_coverage_gate_names_every_open_requirement() -> None:
    feedback = coverage_gate({"last_commit_arguments": {"coverage": [
        {"requirement": "A", "status": "covered", "note": "id_1"},
        {"requirement": "B", "status": "open", "note": "next query: X"},
        {"requirement": "C", "status": "open", "note": ""},
    ]}})
    assert feedback is not None
    assert "B" in feedback and "next query: X" in feedback
    assert "C" in feedback
    assert "2 entries" in feedback  # only the two `open` ones, not `A`


COVERAGE_GATE_SCRIPT = [
    model_turn(reasoning=["Search hybrid first."],
               tool_calls=[tool_call(
                   "search", {"query": "congestion pricing revenue plan",
                              "search_engine": "hybrid"}, id="s1")]),
    # ready_to_report=True but one requirement is still `open` — the gate
    # must catch this inconsistency even though the model itself claimed
    # it was done.
    model_turn(text="Ready to report.",
               tool_calls=[tool_call("commit_context", {
                   "documents": [{"docid": CLIMBMIX_DOCIDS[0],
                                  "reason": "covers requirement A"}],
                   "coverage": [
                       {"requirement": "A", "status": "covered",
                        "note": CLIMBMIX_DOCIDS[0]},
                       {"requirement": "B", "status": "open",
                        "note": "not yet searched"},
                   ],
                   "ready_to_report": True,
               }, id="c1")]),
    model_turn(text=f"First finding. [{CLIMBMIX_DOCIDS[0]}]"),
    model_turn(text=f"Revised, complete finding. [{CLIMBMIX_DOCIDS[0]}]"),
]


def test_coverage_gate_is_wired_in_by_default_and_blocks_a_premature_report(
        drive: Callable[..., dict[str, Any]]) -> None:
    """End-to-end: ``facets_run_agent`` needs no extra argument for this —
    ``pre_final_hook`` defaults to ``coverage_gate`` — and the harness's own
    ``pre_final_hook`` mechanism (tested generically in
    ``tests/agent_harness_context/test_pre_final_hook.py``) is what actually
    sends the model back. Proves the wiring, not the mechanism twice."""
    result = drive(list(COVERAGE_GATE_SCRIPT))
    assert result["summary"]["status"] == "completed"
    assert result["provider"].user_messages[-1].startswith(
        "Before this report is accepted")
    assert "B" in result["provider"].user_messages[-1]
    output = __import__("json").loads(result["summary"]["paths"]["output"].read_text())
    assert output["answer"][0]["text"] == "Revised, complete finding."


def test_coverage_gate_can_be_disabled_via_pre_final_hook_none(
        drive: Callable[..., dict[str, Any]]) -> None:
    """``pre_final_hook=None`` must accept the SAME script's first report
    attempt as-is, proving the default is genuinely overridable."""
    result = drive(list(COVERAGE_GATE_SCRIPT[:3]), pre_final_hook=None)
    assert result["summary"]["status"] == "completed"
    output = __import__("json").loads(result["summary"]["paths"]["output"].read_text())
    assert output["answer"][0]["text"] == "First finding."


# ---------------------------------------------------------------------------
# Phase 4e -- review.citation_audit_gate / two_tier_final_gate
# ---------------------------------------------------------------------------
from facets_agent.review import (  # noqa: E402
    citation_audit_gate,
    two_tier_final_gate,
)


def test_citation_audit_gate_is_a_noop_on_an_uncited_draft() -> None:
    """An uncited draft carries no citation-support risk this gate exists
    for -- it must not fire just because a report was produced."""
    assert citation_audit_gate({"candidate_sentences": [
        {"text": "Uncited transition sentence.", "citations": []},
    ]}) is None


def test_citation_audit_gate_is_a_noop_when_there_are_no_sentences_yet() -> None:
    assert citation_audit_gate({"candidate_sentences": None}) is None
    assert citation_audit_gate({}) is None


def test_citation_audit_gate_lists_every_cited_id_once() -> None:
    feedback = citation_audit_gate({"candidate_sentences": [
        {"text": "Claim one.", "citations": [CLIMBMIX_DOCIDS[0]]},
        {"text": "Claim two.", "citations": [CLIMBMIX_DOCIDS[0], CLIMBMIX_DOCIDS[1]]},
    ]})
    assert feedback is not None
    assert feedback.count(CLIMBMIX_DOCIDS[0]) == 1
    assert CLIMBMIX_DOCIDS[1] in feedback
    assert "get_documents" in feedback and "commit_context" in feedback


def test_two_tier_final_gate_prefers_coverage_over_citation_audit() -> None:
    """A missing requirement is a bigger defect than an imperfect citation
    -- when both would fire, only coverage_gate's feedback goes out, since
    ``pre_final_hook`` only gets one shot per run."""
    context = {
        "last_commit_arguments": {"coverage": [
            {"requirement": "A", "status": "open", "note": ""},
        ]},
        "candidate_sentences": [
            {"text": "Claim.", "citations": [CLIMBMIX_DOCIDS[0]]},
        ],
    }
    feedback = two_tier_final_gate(context)
    assert feedback is not None
    assert feedback.startswith("Before this report is accepted: your own "
                                "requirement ledger")


def test_two_tier_final_gate_runs_citation_audit_when_coverage_is_clean() -> None:
    context = {
        "last_commit_arguments": {"coverage": [
            {"requirement": "A", "status": "covered", "note": ""},
        ]},
        "candidate_sentences": [
            {"text": "Claim.", "citations": [CLIMBMIX_DOCIDS[0]]},
        ],
    }
    feedback = two_tier_final_gate(context)
    assert feedback is not None
    assert feedback.startswith("Before submitting the report")
    assert CLIMBMIX_DOCIDS[0] in feedback


def test_two_tier_final_gate_is_a_noop_when_both_checks_pass() -> None:
    context = {
        "last_commit_arguments": {"coverage": [
            {"requirement": "A", "status": "covered", "note": ""},
        ]},
        "candidate_sentences": [
            {"text": "Uncited transition.", "citations": []},
        ],
    }
    assert two_tier_final_gate(context) is None


# ---------------------------------------------------------------------------
# Phase 4d §7.5 -- piika-inspired two-tier retrieval (opt-in, not the default)
# ---------------------------------------------------------------------------
def test_two_tier_search_is_off_by_default(
        drive: Callable[..., dict[str, Any]]) -> None:
    from facets_agent.prompts import TWO_TIER_SEARCH_ADDENDUM

    result = drive(list(HAPPY_SCRIPT))
    assert TWO_TIER_SEARCH_ADDENDUM not in result["provider"].system_prompt


def test_two_tier_search_appends_the_addendum_when_enabled(
        drive: Callable[..., dict[str, Any]]) -> None:
    from facets_agent.prompts import TWO_TIER_SEARCH_ADDENDUM

    result = drive(list(HAPPY_SCRIPT), search_preview_chars=300,
                    stage_search_results=False, pre_final_hook=None,
                    judge_tool=None)
    assert TWO_TIER_SEARCH_ADDENDUM in result["provider"].system_prompt


@pytest.mark.live
def test_run_agent_live() -> None:
    """Same path against the real ClimbMix + OpenAI endpoints (needs creds)."""
    summary = facets_run_agent(
        "live_smoke", QUERY, safety_max_rounds=20, k=5)
    assert summary["status"] in ("completed", "budget_exhausted")
    assert summary["n_references"] > 0
