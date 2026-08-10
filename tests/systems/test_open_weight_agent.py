"""End-to-end + unit coverage for ``src/systems/open_weight_agent`` -- an
open-weight-only fork of ``brief_revise_agent`` (see
``tests/systems/test_brief_revise_agent.py`` for the brief/review mechanics
inherited unmodified, not re-tested here) plus one addition: a blind
obligation-scout stage (``scout.py``, ported from ``aus_agent_v2.plan_critic``)
merged into the same requirements-brief appendix.

The one behavior unique to this system that ``test_brief_revise_agent.py``
has no equivalent for is the model allowlist (``agent.ALLOWED_MODELS``):
every role must independently clear ``_check_model`` BEFORE any provider is
constructed, so a disallowed model (any OpenAI ``gpt-5.6-*`` id, any
proprietary Bedrock id) fails fast with no API call made, in any role.
"""
from __future__ import annotations

import json
from typing import Any, Callable

import pytest
from conftest import CLIMBMIX_DOCIDS, ScriptedProvider, model_turn, tool_call

from agent_harness import agent as agent_harness_mod

from open_weight_agent import agent as open_weight_agent_mod
from open_weight_agent.agent import (
    ALLOWED_MODELS,
    DEFAULT_ENGINES,
    DEFAULT_MODEL,
    SYSTEM_NAME,
    load_base_system_prompt,
    run_agent as oss_run_agent,
)
from open_weight_agent.scout import render_scout_appendix

QID = "mock_open_weight_agent_001"
QUERY = "How effective is congestion pricing at reducing traffic?"
D = CLIMBMIX_DOCIDS

# A brief turn yielding zero requirements -- same fail-open convention as
# brief_revise_agent's own tests (an empty/failed brief degrades cleanly).
BRIEF_TURN_EMPTY = model_turn(text=json.dumps({"requirements": []}))
SCOUT_TURN_EMPTY = model_turn(text=json.dumps({"verdict": "pass", "additions": []}))
SCOUT_TURN_ONE_ADDITION = model_turn(text=json.dumps({
    "verdict": "add", "additions": [
        {"kind": "evidence", "requirement": "Cite a before/after volume study",
         "must_mention": ["peak-hour"], "reason": "claims need a measured baseline",
         "search_leads": ["congestion pricing before after traffic volume"]},
    ]}))


@pytest.fixture
def drive(monkeypatch: pytest.MonkeyPatch,
          stub_search_tool: dict[str, list[dict[str, Any]]]
          ) -> Callable[..., dict[str, Any]]:
    """Run ``open_weight_agent.agent.run_agent`` against one scripted provider
    shared by every internal call this system makes (brief, scout, main
    loop, and -- when the review pass is active -- the reviewer), the same
    single-queue pattern ``test_brief_revise_agent.py``'s own ``drive``
    fixture uses: a script here reads top to bottom as [brief turn, scout
    turn, ...main loop turns..., (reviewer turn), (revision turn)].
    """
    def _drive(script: list[dict[str, Any]], *, query_id: str = QID,
               query: str = QUERY, **kwargs: Any) -> dict[str, Any]:
        provider = ScriptedProvider(script)
        monkeypatch.setattr(agent_harness_mod, "make_provider",
                            lambda backend, model, region=None,
                                  max_tokens=None: provider)
        kwargs.setdefault("k", 2)
        kwargs.setdefault("safety_max_rounds", 20)
        kwargs.setdefault("system_prompt",
                          load_base_system_prompt(kwargs.get(
                              "max_committed_per_step", 40)))
        summary = oss_run_agent(query_id, query, **kwargs)
        output = json.loads(summary["paths"]["output"].read_text())
        return {"summary": summary, "provider": provider, "output": output,
                "trace": output["trace"], "calls": stub_search_tool}
    return _drive


# ---------------------------------------------------------------------------
# Model allowlist -- this system's entire premise
# ---------------------------------------------------------------------------

def test_allowed_models_has_no_openai_or_anthropic_id() -> None:
    """Regression guard for the constraint itself: nothing in
    ``ALLOWED_MODELS`` may be an OpenAI ``gpt-5.6-*`` id or a proprietary
    Bedrock id (``anthropic.*``/``au.anthropic.*``) -- if either ever
    sneaks in, this system's core premise (open-weight, end to end) is
    silently broken."""
    for model in ALLOWED_MODELS:
        assert not model.startswith("gpt-5")
        assert "anthropic" not in model


def test_run_agent_rejects_a_disallowed_main_model_before_any_provider_call(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The allowlist check must run BEFORE ``make_provider`` is ever
    called, in any of the four roles -- otherwise a disallowed model could
    still cost one real API call (the brief's) before failing."""
    calls: list[Any] = []
    monkeypatch.setattr(agent_harness_mod, "make_provider",
                        lambda *a, **k: calls.append(a) or ScriptedProvider([]))
    with pytest.raises(ValueError, match="open-weight-only"):
        oss_run_agent(QID, QUERY, model="gpt-5.6-luna",
                      system_prompt=load_base_system_prompt(40))
    assert calls == []


def test_run_agent_rejects_a_disallowed_role_model_even_when_main_is_allowed(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Each of brief/review/scout must independently clear the allowlist --
    a disallowed model in a secondary role must not slip through just
    because the main writer model is fine."""
    monkeypatch.setattr(agent_harness_mod, "make_provider",
                        lambda *a, **k: ScriptedProvider([]))
    with pytest.raises(ValueError, match="open-weight-only"):
        oss_run_agent(QID, QUERY, model=DEFAULT_MODEL,
                      brief_model="au.anthropic.claude-sonnet-5",
                      system_prompt=load_base_system_prompt(40))


def test_brief_backend_openai_bypasses_the_allowlist_for_that_role_only(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The diagnostic role-decoupling escape hatch (worklogs/assets/
    2026-08-09-open-weight-agent-sol-plan-review.md): passing brief_backend="openai"
    must let brief_model be a proprietary id WITHOUT touching the main
    writer's own allowlist enforcement -- proving the bypass is scoped to
    exactly the one role it was given for, not a global relaxation."""
    calls: list[tuple[str, str | None]] = []

    def fake_make_provider(backend: str, model: str | None,
                           region: str | None = None,
                           max_tokens: int | None = None) -> Any:
        calls.append((backend, model))
        return ScriptedProvider([BRIEF_TURN_EMPTY, SCOUT_TURN_EMPTY])

    monkeypatch.setattr(agent_harness_mod, "make_provider", fake_make_provider)
    monkeypatch.setattr(open_weight_agent_mod, "_run_agent",
                        lambda *a, **k: {"status": "completed", "paths": {}})

    open_weight_agent_mod.run_agent(
        QID, QUERY, model=DEFAULT_MODEL,
        brief_model="gpt-5.6-luna", brief_backend="openai",
        system_prompt=load_base_system_prompt(40))

    assert ("openai", "gpt-5.6-luna") in calls
    # The main writer's own model is still checked via _check_model(model)
    # with the hardcoded backend="bedrock" default -- a disallowed main
    # model must still raise even with an unrelated support role relaxed.
    with pytest.raises(ValueError, match="open-weight-only"):
        open_weight_agent_mod.run_agent(
            QID, QUERY, model="gpt-5.6-luna",
            brief_model="gpt-5.6-luna", brief_backend="openai",
            system_prompt=load_base_system_prompt(40))


def test_default_engines_is_hybrid_only() -> None:
    """S6 (factor-analysis report §4.6): hybrid alone was the one
    confirmed cheap-AND-better retrieval-engine lever found against the
    semantic,keyword default -- open_weight_agent adopts it as the default rather
    than brief_revise_agent's own semantic,keyword pair."""
    assert DEFAULT_ENGINES == ["hybrid"]


# ---------------------------------------------------------------------------
# scout.py -- direct unit coverage
# ---------------------------------------------------------------------------

def test_render_scout_appendix_is_empty_when_there_are_no_additions() -> None:
    """Fail-open contract, same as ``brief.render_appendix([])`` -- a scout
    call that found nothing (or failed to parse) must not append any text,
    so the system prompt stays byte-identical to the brief-only case."""
    assert render_scout_appendix([]) == ""


def test_render_scout_appendix_includes_the_requirement_and_exact_terms() -> None:
    additions = [{"kind": "evidence", "requirement": "Cite a baseline study",
                 "must_mention": ["peak-hour"], "reason": "needs a measured baseline"}]
    text = render_scout_appendix(additions)
    assert "[S1] (scout/evidence) Cite a baseline study" in text
    assert "EXACT: peak-hour" in text
    assert "needs a measured baseline" in text


# ---------------------------------------------------------------------------
# End-to-end wiring
# ---------------------------------------------------------------------------

def test_scout_additions_land_in_the_recorded_system_prompt(
        drive: Callable[..., dict[str, Any]]) -> None:
    """Proves the scout's additions actually reach the recorded
    ``trace.input.system_prompt`` after the brief's own appendix -- not
    just that ``render_scout_appendix`` produces the right string in
    isolation (mirrors brief_revise_agent's own
    ``test_non_empty_brief_lands_in_the_recorded_system_prompt``)."""
    script = [
        BRIEF_TURN_EMPTY,
        SCOUT_TURN_ONE_ADDITION,
        model_turn(reasoning=["Search once."], tool_calls=[tool_call(
            "search", {"query": "congestion pricing traffic reduction",
                      "search_engine": "hybrid"}, id="s1")]),
        model_turn(text="Keep this.", tool_calls=[tool_call(
            "commit_context", {"documents": [
                {"docid": D[0], "reason": "quantified effect"}]}, id="c1")]),
        model_turn(text=f"Congestion pricing cut peak traffic. [{D[0]}]"),
    ]
    result = drive(list(script), pre_final_hook=None)
    assert result["summary"]["status"] == "completed"
    system_prompt = result["trace"]["input"]["system_prompt"]
    assert "blind scout additions" in system_prompt
    assert "Cite a before/after volume study" in system_prompt
    assert "EXACT: peak-hour" in system_prompt


def test_plan_critic_false_skips_the_scout_call_entirely(
        drive: Callable[..., dict[str, Any]]) -> None:
    """``plan_critic=False`` must consume no turn at all for the scout (not
    just render an empty appendix) -- proven by a script one turn shorter
    than the scout-on path above still completing cleanly."""
    script = [
        BRIEF_TURN_EMPTY,
        model_turn(reasoning=["Search once."], tool_calls=[tool_call(
            "search", {"query": "congestion pricing traffic reduction",
                      "search_engine": "hybrid"}, id="s1")]),
        model_turn(text="Keep this.", tool_calls=[tool_call(
            "commit_context", {"documents": [
                {"docid": D[0], "reason": "core evidence"}]}, id="c1")]),
        model_turn(text=f"Congestion pricing reduced peak traffic. [{D[0]}]"),
    ]
    result = drive(list(script), pre_final_hook=None, plan_critic=False)
    assert result["summary"]["status"] == "completed"
    assert "blind scout" not in result["trace"]["input"]["system_prompt"]


def test_pre_final_hook_none_disables_the_review_pass_but_not_the_brief(
        drive: Callable[..., dict[str, Any]]) -> None:
    """Same independence guarantee brief_revise_agent's own tests pin: the
    review pass is a separate opt-out from the brief/scout stages, and
    artifacts land under THIS system's own name."""
    from ragrun import validate_rag_output

    script = [
        BRIEF_TURN_EMPTY,
        SCOUT_TURN_EMPTY,
        model_turn(reasoning=["Search once."], tool_calls=[tool_call(
            "search", {"query": "congestion pricing traffic reduction",
                      "search_engine": "hybrid"}, id="s1")]),
        model_turn(text="Keep this.", tool_calls=[tool_call(
            "commit_context", {"documents": [
                {"docid": D[0], "reason": "core evidence"}]}, id="c1")]),
        model_turn(text=f"Congestion pricing reduced peak traffic. [{D[0]}]"),
    ]
    result = drive(list(script), pre_final_hook=None)
    assert result["summary"]["status"] == "completed"
    assert result["summary"]["paths"]["output"].parent.name == SYSTEM_NAME \
        == "open_weight_agent"
    assert validate_rag_output(result["output"]) == []
    # Only the brief's, the scout's, and the harness's own TASK_PROMPT were
    # ever sent -- no reviewer call happened.
    assert len(result["provider"].user_messages) == 3


def test_review_pass_wired_end_to_end_sends_the_model_back_once(
        drive: Callable[..., dict[str, Any]]) -> None:
    """Proves the reused ``review.hook`` mechanism (unmodified from
    brief_revise_agent) is still reachable through open_weight_agent's own closure
    -- the one end-to-end proof of wiring, not the mechanism twice (unit
    coverage for ``review.hook`` itself lives in
    ``test_brief_revise_agent.py``)."""
    draft = (f"Congestion pricing directly cuts peak traffic. [{D[0]}]\n"
             "Revenue from the tolls often funds transit upgrades.")
    revised = (f"Congestion pricing directly cuts peak traffic. [{D[0]}]\n"
               f"Revenue from the tolls often funds transit upgrades. [{D[0]}]")
    script = [
        BRIEF_TURN_EMPTY,
        SCOUT_TURN_EMPTY,
        model_turn(reasoning=["Search once."], tool_calls=[tool_call(
            "search", {"query": "congestion pricing traffic reduction",
                      "search_engine": "hybrid"}, id="s1")]),
        model_turn(text="Keep this.", tool_calls=[tool_call(
            "commit_context", {"documents": [
                {"docid": D[0], "reason": "core evidence"}]}, id="c1")]),
        model_turn(text=draft),
        model_turn(text=json.dumps({"requirements": [], "issues": []})),  # reviewer turn
        model_turn(text=revised),  # revision turn
    ]
    result = drive(list(script))
    assert result["summary"]["status"] == "completed"
    assert result["provider"].user_messages[-1].startswith(
        "Before this report is accepted")
    assert result["output"]["answer"][-1]["citations"]


def test_review_scout_obligations_widens_the_reviewer_requirement_list(
        drive: Callable[..., dict[str, Any]]) -> None:
    """``review_scout_obligations=True`` (the additive follow-up both sol
    and Opus converged on after synthesis_compiler's negative result --
    worklogs/assets/2026-08-09-open-weight-agent-sol-plan-review.md) must widen
    what the REVIEWER grades to include the scout's own obligations
    (``S1``), not just the brief's -- proven by the scout's requirement
    text reaching the reviewer's own prompt, which is recorded as a user
    message on the shared provider."""
    draft = f"Congestion pricing directly cuts peak traffic. [{D[0]}]"
    script = [
        BRIEF_TURN_EMPTY,
        SCOUT_TURN_ONE_ADDITION,
        model_turn(reasoning=["Search once."], tool_calls=[tool_call(
            "search", {"query": "congestion pricing traffic reduction",
                      "search_engine": "hybrid"}, id="s1")]),
        model_turn(text="Keep this.", tool_calls=[tool_call(
            "commit_context", {"documents": [
                {"docid": D[0], "reason": "core evidence"}]}, id="c1")]),
        model_turn(text=draft),
        model_turn(text=json.dumps({"requirements": [
            {"id": "S1", "status": "MISSING",
             "missing_specific": "no before/after volume study cited",
             "fix": "cite one"}], "issues": []})),  # reviewer turn
        model_turn(text=f"Congestion pricing directly cuts peak traffic. "
                       f"[{D[0]}] A 2019 study found volumes fell 12%. [{D[0]}]"),
    ]
    result = drive(list(script), review_scout_obligations=True)
    assert result["summary"]["status"] == "completed"
    assert any("Cite a before/after volume study" in msg
              for msg in result["provider"].user_messages)
    # The reviewer's own PATCH feedback (rendered from the S1 grade above)
    # must name the scout obligation by id, proving it was graded, not
    # silently ignored the way it would be without the widened list.
    assert any("[S1]" in msg for msg in result["provider"].user_messages)


def test_brief_scout_review_roles_can_be_decoupled_from_the_main_model(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """``brief_model``/``scout_model``/``review_model`` must reach
    ``make_provider`` independently of the main run's ``model`` -- and
    every one of the four must still be allowlisted (mirrors
    ``test_brief_revise_agent.py``'s own decoupling test, plus the
    allowlist this system adds)."""
    calls: list[tuple[str, str | None, str | None]] = []

    def fake_make_provider(backend: str, model: str | None,
                           region: str | None = None,
                           max_tokens: int | None = None) -> Any:
        calls.append((backend, model, region))
        return ScriptedProvider([BRIEF_TURN_EMPTY, SCOUT_TURN_EMPTY])

    def fake_run_agent(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"status": "completed", "paths": {}}

    monkeypatch.setattr(agent_harness_mod, "make_provider", fake_make_provider)
    monkeypatch.setattr(open_weight_agent_mod, "_run_agent", fake_run_agent)

    open_weight_agent_mod.run_agent(
        QID, QUERY, model="qwen.qwen3-next-80b-a3b",
        brief_model="openai.gpt-oss-120b-1:0", brief_region="ap-southeast-2",
        scout_model="openai.gpt-oss-120b-1:0", scout_region="ap-southeast-2",
        review_model="openai.gpt-oss-120b-1:0", review_region="ap-southeast-2",
        system_prompt=load_base_system_prompt(40))

    assert calls == [
        ("bedrock", "openai.gpt-oss-120b-1:0", "ap-southeast-2"),  # brief
        ("bedrock", "openai.gpt-oss-120b-1:0", "ap-southeast-2"),  # scout
        ("bedrock", "openai.gpt-oss-120b-1:0", "ap-southeast-2"),  # reviewer
    ]


@pytest.mark.live
def test_run_agent_live() -> None:
    """Same path against the real ClimbMix + Bedrock endpoints (needs
    creds) -- default model (gpt-oss-120b, reachable in the repo's own
    default Bedrock region, unlike qwen/kimi)."""
    summary = oss_run_agent(
        "live_smoke", QUERY, safety_max_rounds=20, k=5,
        system_prompt=load_base_system_prompt(40))
    assert summary["status"] in ("completed", "budget_exhausted")
    assert summary["n_references"] > 0
