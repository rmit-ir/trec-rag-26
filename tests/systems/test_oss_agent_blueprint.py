"""Coverage for ``src/systems/oss_agent/blueprint.py`` -- the alternative
``pre_final_hook`` from the converged sol/Opus design review (see the
module's own docstring for the design rationale). Unit tests exercise
``parse_blueprint``/``render_blueprint_feedback`` directly (same principle
``test_oss_agent.py`` uses for ``review.hook``: most tests get a faster,
more precise assertion out of calling the parser/renderer in isolation);
one end-to-end test proves ``--synthesis-compiler`` actually wires
``blueprint.hook`` in place of ``review.hook``, not the mechanism twice.
"""
from __future__ import annotations

import json
from typing import Any

import pytest
from conftest import CLIMBMIX_DOCIDS, ScriptedProvider, model_turn, tool_call

from agent_harness import agent as agent_harness_mod

from oss_agent import blueprint
from oss_agent.agent import load_base_system_prompt
from oss_agent.agent import run_agent as oss_run_agent
from systems.brief_revise_agent.brief import Requirement

D = CLIMBMIX_DOCIDS
QID = "mock_oss_agent_blueprint_001"
QUERY = "How effective is congestion pricing at reducing traffic?"

REQS = [Requirement(id="R1", requirement="State a quantified traffic effect",
                    origin="implicit", why="", specific_form="a percentage or count")]
SCOUT_ADDITIONS = [{"kind": "evidence", "requirement": "Cite a before/after study",
                    "must_mention": [], "reason": "needs a measured baseline"}]


def test_obligation_list_unifies_brief_and_scout_ids_consistently() -> None:
    """The blueprint's obligation ids must match what the model already
    read in the system-prompt appendix (brief.render_appendix/
    scout.render_scout_appendix's own numbering) -- otherwise a validated
    blueprint could reference an obligation the model was never told
    about under that id."""
    obligations = blueprint.obligation_list(REQS, SCOUT_ADDITIONS)
    ids = [o["id"] for o in obligations]
    assert ids == ["R1", "S1"]


def test_parse_blueprint_drops_docids_and_obligation_ids_not_in_scope() -> None:
    """A hallucinated docid or obligation id must never survive into the
    feedback sent back to the model -- mirrors brief.parse_brief's and
    review._parse_review's own defensive-drop convention."""
    raw = json.dumps({"sections": [
        {"heading": "Baseline", "budget_words": 200,
         "obligations": ["R1", "R9-does-not-exist"],
         "claims": [
             {"claim": "Traffic fell 12%.", "docids": [D[0], "shard_fake_doc"],
              "relation": "fact"},
         ]},
        {"heading": "Context", "budget_words": 150, "obligations": [],
         "claims": []},
    ]})
    sections, omitted, ok = blueprint.parse_blueprint(
        raw, valid_obligation_ids={"R1", "S1"}, committed_ids={D[0], D[1]})
    assert ok is True
    assert sections[0]["obligations"] == ["R1"]
    assert sections[0]["claims"][0]["docids"] == [D[0]]


def test_parse_blueprint_caps_total_section_budget() -> None:
    """Section budgets summing over the cap must be truncated, not
    rejected outright -- a blueprint that is otherwise good should not be
    thrown away for one oversized section."""
    raw = json.dumps({"sections": [
        {"heading": "A", "budget_words": 700, "obligations": [], "claims": []},
        {"heading": "B", "budget_words": 700, "obligations": [], "claims": []},
    ]})
    sections, _, ok = blueprint.parse_blueprint(
        raw, valid_obligation_ids=set(), committed_ids=set())
    assert ok is True
    total = sum(s["budget_words"] for s in sections)
    assert total <= blueprint.MAX_SECTION_BUDGET_TOTAL


def test_parse_blueprint_rejects_fewer_than_two_sections() -> None:
    """A single-section (or zero-section) response is not a structure --
    treated as unparseable so hook() retries once rather than accept a
    degenerate blueprint."""
    raw = json.dumps({"sections": [
        {"heading": "Only one", "budget_words": 500, "obligations": [], "claims": []},
    ]})
    _, _, ok = blueprint.parse_blueprint(raw, valid_obligation_ids=set(),
                                         committed_ids=set())
    assert ok is False


def test_render_blueprint_feedback_names_headings_claims_and_omissions() -> None:
    sections = [{"heading": "Baseline effect", "budget_words": 200,
                "obligations": ["R1"],
                "claims": [{"claim": "Traffic fell 12%.", "docids": [D[0]],
                           "relation": "fact"}]}]
    text = blueprint.render_blueprint_feedback(
        sections, omitted=["R1"],
        obligations=[{"id": "R1", "requirement": "State a quantified effect"}])
    assert "Baseline effect" in text
    assert "Traffic fell 12%." in text
    assert D[0] in text
    assert "State a quantified effect" in text  # omitted obligation named, not silently dropped


def test_blueprint_hook_fails_open_when_both_attempts_are_unparseable() -> None:
    """Same fail-open contract as review.hook: a blueprint failure must
    degrade to accepting the model's own original draft, never fail a
    topic."""
    provider = ScriptedProvider([
        model_turn(text="not json"), model_turn(text="still not json"),
    ])
    context = {"query": QUERY, "ledger": type("L", (), {
        "committed_ids": [D[0]], "call_history": {}, "committed_call_id": {}})()}
    result = blueprint.hook(context, requirements=REQS,
                            scout_additions=SCOUT_ADDITIONS, provider=provider)
    assert result is None


def test_synthesis_compiler_wires_blueprint_hook_not_review_hook(
        monkeypatch: pytest.MonkeyPatch,
        stub_search_tool: dict[str, list[dict[str, Any]]]) -> None:
    """End-to-end proof that ``--synthesis-compiler``/``synthesis_compiler=
    True`` actually replaces ``review.hook`` with ``blueprint.hook`` as the
    harness's ``pre_final_hook`` -- the one wiring test, not the mechanism
    twice (unit tests above already cover the mechanism itself). Asserts on
    the recorded user-message history (persists across the shared
    provider's several ``start()`` resets, unlike the system prompt) for a
    marker string unique to ``render_blueprint_feedback`` -- ``review.hook``
    never emits "discarded"."""
    draft = f"Congestion pricing cuts peak traffic. [{D[0]}]"
    blueprint_json = json.dumps({"sections": [
        {"heading": "Effect", "budget_words": 200, "obligations": [],
         "claims": [{"claim": "Traffic fell.", "docids": [D[0]], "relation": "fact"}]},
        {"heading": "Context", "budget_words": 150, "obligations": [], "claims": []},
    ]})
    revised = f"Congestion pricing directly cuts peak traffic. [{D[0]}]"
    script = [
        model_turn(text=json.dumps({"requirements": []})),  # brief
        model_turn(text=json.dumps({"verdict": "pass", "additions": []})),  # scout
        model_turn(reasoning=["Search once."], tool_calls=[tool_call(
            "search", {"query": "congestion pricing", "search_engine": "hybrid"},
            id="s1")]),
        model_turn(text="Keep this.", tool_calls=[tool_call(
            "commit_context", {"documents": [
                {"docid": D[0], "reason": "core evidence"}]}, id="c1")]),
        model_turn(text=draft),
        model_turn(text=blueprint_json),  # blueprint architect call, NOT a review call
        model_turn(text=revised),  # revision turn, following the blueprint
    ]
    provider = ScriptedProvider(script)
    monkeypatch.setattr(agent_harness_mod, "make_provider",
                        lambda backend, model, region=None, max_tokens=None: provider)

    summary = oss_run_agent(
        QID, QUERY, k=2, safety_max_rounds=20,
        system_prompt=load_base_system_prompt(40), synthesis_compiler=True)
    output = json.loads(summary["paths"]["output"].read_text())

    assert output["trace"]["status"] == "completed"
    assert any("discarded" in msg for msg in provider.user_messages)
    assert output["answer"][-1]["citations"]
