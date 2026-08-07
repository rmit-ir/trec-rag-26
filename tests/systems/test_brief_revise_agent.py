"""End-to-end + unit coverage for ``src/systems/brief_revise_agent`` -- a
fork of aus_agent (see ``tests/systems/test_aus_agent.py`` for the shared
loop mechanics, not re-tested here) plus two additions: a pre-flight
requirements brief (``brief.py``) and a review-and-revise ``pre_final_hook``
(``review.py``). PLAN.md §6 Phase 3 names six specific cases this file must
cover; the module docstrings on ``brief.py``/``review.py`` explain WHY each
one matters (never-block-a-run, blanket exception guard, substitution-not-
addition feedback), so this file's own docstrings stay short and point back
there rather than re-deriving the rationale per test.

``review.hook`` is mostly tested DIRECTLY (a plain function taking a context
dict, a ``requirements`` list, and a ``provider``) rather than through a full
``run_agent`` drive: every fired hook consumes one MORE scripted turn on top
of the run's own (the reviewer's own ``one_shot`` call), on the SAME shared
``ScriptedProvider`` queue the brief step and the main loop already draw
from (``agent.py`` builds every provider via the same monkeypatched
``make_provider`` factory) -- so most tests get a faster, more precise
assertion out of calling ``review.hook`` in isolation, and the one true
end-to-end test (``test_review_pass_wired_end_to_end_...``) exists purely to
prove the wiring reaches it, not the mechanism twice (same principle as
``facets_agent``'s own end-to-end ``coverage_gate`` test).
"""
from __future__ import annotations

import json
from typing import Any, Callable

import pytest
from conftest import CLIMBMIX_DOCIDS, ScriptedProvider, model_turn, tool_call

from agent_harness import agent as agent_harness_mod

from brief_revise_agent import brief, review
from brief_revise_agent.agent import (
    DEFAULT_MAX_COMMITTED_PER_STEP,
    DEFAULT_PROMPT_VARIANT,
    SYSTEM_NAME,
    load_system_prompt,
)
from brief_revise_agent.agent import run_agent as brief_revise_run_agent

QID = "mock_brief_revise_001"
QUERY = "How effective is congestion pricing at reducing traffic?"
D = CLIMBMIX_DOCIDS

# A brief turn that yields zero requirements (either because the analyst
# genuinely found nothing, or -- indistinguishable to the harness, and that
# is the point -- because parsing failed): the appendix is then empty and the
# system prompt is aus_agent's own. Used by every end-to-end test that is not
# specifically about the brief's own content.
BRIEF_TURN_EMPTY = model_turn(text=json.dumps({"requirements": []}))


@pytest.fixture
def drive(monkeypatch: pytest.MonkeyPatch,
          stub_search_tool: dict[str, list[dict[str, Any]]]
          ) -> Callable[..., dict[str, Any]]:
    """Run ``brief_revise_agent.agent.run_agent`` against one scripted
    provider shared by every internal call this system makes.

    ``agent.py`` builds THREE providers per run via the same
    ``agent_harness.agent.make_provider`` factory call (the brief's own, the
    main loop's own, and -- when the review pass is active -- the
    reviewer's own); monkeypatching that one factory to always hand back the
    SAME ``ScriptedProvider`` means all three draw from one ordered turn
    queue, so a script for an end-to-end test here reads top to bottom as:
    [brief turn, ...main loop turns..., (reviewer turn), (revision turn)].
    """
    def _drive(script: list[dict[str, Any]], *, query_id: str = QID,
               query: str = QUERY, **kwargs: Any) -> dict[str, Any]:
        provider = ScriptedProvider(script)
        monkeypatch.setattr(agent_harness_mod, "make_provider",
                            lambda backend, model: provider)
        kwargs.setdefault("k", 2)
        kwargs.setdefault("safety_max_rounds", 20)
        kwargs.setdefault("system_prompt", load_system_prompt(
            kwargs.get("max_committed_per_step",
                       DEFAULT_MAX_COMMITTED_PER_STEP),
            kwargs.get("prompt_variant", DEFAULT_PROMPT_VARIANT)))
        summary = brief_revise_run_agent(query_id, query, **kwargs)
        output = json.loads(summary["paths"]["output"].read_text())
        return {"summary": summary, "provider": provider, "output": output,
                "trace": output["trace"], "calls": stub_search_tool}
    return _drive


# ---------------------------------------------------------------------------
# review.py -- direct unit coverage (PLAN.md §6 Phase 3, cases i-iii)
# ---------------------------------------------------------------------------

EMPTY_REVIEW_TURN = model_turn(text=json.dumps({"requirements": [], "issues": []}))
SAMPLE_REQ = brief.Requirement(
    id="R1", requirement="State a quantified effect on traffic volume",
    origin="implicit", why="how effective", specific_form="a percentage")


def test_review_hook_is_a_noop_on_a_clean_draft() -> None:
    """A fully cited draft with no PARTIAL/MISSING requirements and no
    reviewer-found issues must return ``None`` -- the harness treats that
    identically to no hook at all (PLAN.md §3.3 step 3), so this is the one
    case that must never generate feedback."""
    context = {"query": QUERY, "ledger": None, "candidate_sentences": [
        {"text": "A fully supported claim.", "citations": [D[0]]}]}
    provider = ScriptedProvider([model_turn(text=json.dumps(
        {"requirements": [{"id": "R1", "status": "FULL",
                           "missing_specific": "", "fix": ""}],
         "issues": []}))])
    assert review.hook(context, requirements=[SAMPLE_REQ],
                       provider=provider) is None


def test_review_hook_names_uncited_sentence_indices_in_feedback() -> None:
    """The deterministic uncited-sentence scan is the one check PLAN.md §2.1
    identifies as NOT already enforced upstream (``_parse_final_prose`` only
    refuses a report when EVERY sentence is uncited); the feedback must name
    the specific sentence number so the model does not have to re-derive
    which claim needs fixing."""
    context = {"query": QUERY, "ledger": None, "candidate_sentences": [
        {"text": "A supported claim.", "citations": [D[0]]},
        {"text": "An unsupported claim.", "citations": []},
    ]}
    provider = ScriptedProvider([EMPTY_REVIEW_TURN])
    feedback = review.hook(context, requirements=[], provider=provider)
    assert feedback is not None
    assert "#2" in feedback
    assert "1 sentence" in feedback


def test_review_hook_names_a_partial_requirement_and_forbids_touching_full_ones() -> None:
    """v2's requirement-grading schema (PLAN §3.3 v2, sol improvement-analysis
    Priority 1): a requirement graded PARTIAL must be named in the feedback
    by id and requirement text, with its missing specific and fix -- and the
    feedback must explicitly forbid touching FULL-graded content, the
    PATCH-not-rewrite framing that targets the dominant loss pattern
    (compressing/dropping content that was already correct)."""
    context = {"query": QUERY, "ledger": None, "candidate_sentences": [
        {"text": "Traffic fell.", "citations": [D[0]]}]}
    provider = ScriptedProvider([model_turn(text=json.dumps({
        "requirements": [{"id": "R1", "status": "PARTIAL",
                          "missing_specific": "a percentage figure",
                          "fix": "add the specific percentage from the evidence"}],
        "issues": []}))])
    feedback = review.hook(context, requirements=[SAMPLE_REQ], provider=provider)
    assert feedback is not None
    assert "R1" in feedback and "a percentage figure" in feedback
    assert "PATCH" in feedback and "FULL" in feedback


def test_review_hook_accepts_the_draft_when_the_reviewer_call_raises() -> None:
    """PLAN.md §3.3 step 4's blanket guard: an exception anywhere in the
    reviewer call must degrade to accepting the draft, even when the
    deterministic scan (evaluated BEFORE the exception) would otherwise have
    produced feedback -- a review failure must never fail a topic. An empty
    ``ScriptedProvider`` raises on ``run_turn()``, which is exactly the
    'reviewer call raises' case."""
    context = {"query": QUERY, "ledger": None, "candidate_sentences": [
        {"text": "An unsupported claim.", "citations": []}]}
    provider = ScriptedProvider([])
    assert review.hook(context, requirements=[], provider=provider) is None


def test_review_hook_retries_once_on_garbage_then_uses_the_repaired_response() -> None:
    """v2's fail-CLOSED retry (the sol-improvement-analysis correction to v1,
    which silently treated any unparseable reviewer response as 'zero
    issues'): a first garbled response must trigger exactly one retry, and if
    the retry parses, its content is used -- not discarded."""
    context = {"query": QUERY, "ledger": None, "candidate_sentences": [
        {"text": "Traffic fell.", "citations": [D[0]]}]}
    provider = ScriptedProvider([
        model_turn(text="not json at all, sorry"),
        model_turn(text=json.dumps({
            "requirements": [{"id": "R1", "status": "MISSING",
                              "missing_specific": "a percentage figure",
                              "fix": "add it"}],
            "issues": []})),
    ])
    feedback = review.hook(context, requirements=[SAMPLE_REQ], provider=provider)
    assert feedback is not None and "MISSING" in feedback and "R1" in feedback


def test_review_hook_accepts_the_draft_when_both_reviewer_attempts_return_garbage() -> None:
    """When BOTH the first call and the repair retry fail to parse, a fully
    cited draft with nothing else to flag must still be accepted (never
    block a run on an unusable reviewer) -- this is the fail-closed path's
    terminal case, distinct from v1's silent 'treat as zero issues'."""
    context = {"query": QUERY, "ledger": None, "candidate_sentences": [
        {"text": "A fully supported claim.", "citations": [D[0]]}]}
    provider = ScriptedProvider([
        model_turn(text="not json at all, sorry"),
        model_turn(text="still not json"),
    ])
    assert review.hook(context, requirements=[], provider=provider) is None


def test_review_hook_still_flags_uncited_sentences_when_both_reviewer_attempts_fail() -> None:
    """The deterministic uncited-sentence scan does not depend on the LLM
    reviewer parsing at all -- even when both reviewer attempts return
    garbage, an uncited sentence must still be sent back for revision."""
    context = {"query": QUERY, "ledger": None, "candidate_sentences": [
        {"text": "An unsupported claim.", "citations": []}]}
    provider = ScriptedProvider([
        model_turn(text="not json at all, sorry"),
        model_turn(text="still not json"),
    ])
    feedback = review.hook(context, requirements=[], provider=provider)
    assert feedback is not None and "#1" in feedback


# ---------------------------------------------------------------------------
# brief.py -- direct unit coverage (PLAN.md §6 Phase 3, case iv)
# ---------------------------------------------------------------------------

def test_parse_brief_survives_bad_json_and_yields_an_empty_brief() -> None:
    """``parse_brief`` must never raise: bad JSON, an empty response, and
    JSON missing the expected top-level key must all fall back to ``[]`` --
    the same 'parse defensively, never block a run' policy as
    ``facet_rag.planner.fallback_facets`` (PLAN.md §3.1)."""
    assert brief.parse_brief("not json at all", QUERY) == []
    assert brief.parse_brief("", QUERY) == []
    assert brief.parse_brief(json.dumps({"unexpected_key": []}), QUERY) == []


def test_parse_brief_enforces_the_entry_caps() -> None:
    """An analyst that invents obligations is worse than none (PLAN.md
    §3.1): every entry competes for a binding 1024-word budget, so the 8
    total / 4 implicit caps must hold even when the model's JSON obeys the
    schema but ignores the count instructions."""
    explicit_rows = [
        {"id": f"R{i}", "requirement": f"requirement {i}", "origin": "explicit",
         "why": "", "specific_form": f"form {i}"}
        for i in range(10)
    ]
    parsed = brief.parse_brief(json.dumps({"requirements": explicit_rows}), QUERY)
    assert len(parsed) == brief.MAX_ENTRIES

    implicit_rows = [
        {"id": f"I{i}", "requirement": f"implicit requirement {i}",
         "origin": "implicit", "why": "congestion pricing",
         "specific_form": f"form {i}"}
        for i in range(6)
    ]
    parsed_implicit = brief.parse_brief(
        json.dumps({"requirements": implicit_rows}), QUERY)
    assert len(parsed_implicit) == brief.MAX_IMPLICIT


def test_parse_brief_drops_an_implicit_entry_whose_why_cannot_be_traced() -> None:
    """The anti-hunch rule (PLAN.md §3.1): an implicit entry's ``why`` must
    quote or closely paraphrase actual wording in the request. A ``why`` that
    shares nothing with the narrative is a hunch, not a requirement, and must
    be dropped at parse time -- exactly the ``facet_rag`` planner failure
    mode (inventing obligations) this rule exists to keep out."""
    hunch = [{"id": "H1", "requirement": "an invented obligation",
             "origin": "implicit", "why": "totally unrelated made-up reasoning",
             "specific_form": "x"}]
    assert brief.parse_brief(json.dumps({"requirements": hunch}), QUERY) == []


# ---------------------------------------------------------------------------
# End-to-end (PLAN.md §6 Phase 3, cases v-vi, plus the wiring proof)
# ---------------------------------------------------------------------------

GOOD_BRIEF_TURN = model_turn(text=json.dumps({"requirements": [
    {"id": "R1", "requirement": "State a quantified effect on traffic volume",
     "origin": "implicit",
     "why": 'the request asks "how effective is congestion pricing"',
     "specific_form": "a percentage or volume change, not just 'it helped'"},
]}))


def test_non_empty_brief_lands_in_the_recorded_system_prompt(
        drive: Callable[..., dict[str, Any]]) -> None:
    """The brief is appended to ``system_prompt``, a per-call harness
    parameter (PLAN.md §2.4 -- no shared-code change needed): this proves the
    appendix actually reaches the recorded ``trace.input.system_prompt``, not
    just that ``render_appendix`` produces the right string in isolation."""
    script = [
        GOOD_BRIEF_TURN,
        model_turn(reasoning=["Search once."], tool_calls=[tool_call(
            "search", {"query": "congestion pricing traffic reduction",
                      "search_engine": "semantic"}, id="s1")]),
        model_turn(text="Keep this.", tool_calls=[tool_call(
            "commit_context", {"documents": [
                {"docid": D[0], "reason": "quantified effect"}]}, id="c1")]),
        model_turn(text=f"Congestion pricing cut peak traffic by a measurable "
                        f"share. [{D[0]}]"),
    ]
    result = drive(list(script), pre_final_hook=None)
    assert result["summary"]["status"] == "completed"
    system_prompt = result["trace"]["input"]["system_prompt"]
    assert "Requirements brief (advisory)" in system_prompt
    assert "State a quantified effect on traffic volume" in system_prompt


def test_pre_final_hook_none_disables_the_review_pass(
        drive: Callable[..., dict[str, Any]]) -> None:
    """``pre_final_hook=None`` must disable ONLY the review pass -- the
    brief step is an independent addition (PLAN.md §3) and still runs -- and
    artifacts must still land under this system's own name, never
    aus_agent's (the regression a copy-paste of aus_agent's hardcoded
    system_name would silently reintroduce)."""
    from ragrun import validate_rag_output

    script = [
        BRIEF_TURN_EMPTY,
        model_turn(reasoning=["Search once."], tool_calls=[tool_call(
            "search", {"query": "congestion pricing traffic reduction",
                      "search_engine": "semantic"}, id="s1")]),
        model_turn(text="Keep this.", tool_calls=[tool_call(
            "commit_context", {"documents": [
                {"docid": D[0], "reason": "core evidence"}]}, id="c1")]),
        model_turn(text=f"Congestion pricing reduced peak traffic. [{D[0]}]"),
    ]
    result = drive(list(script), pre_final_hook=None)
    assert result["summary"]["status"] == "completed"
    assert result["summary"]["paths"]["output"].parent.name == SYSTEM_NAME \
        == "brief_revise_agent"
    assert validate_rag_output(result["output"]) == []
    assert result["output"]["answer"][0]["text"] == (
        "Congestion pricing reduced peak traffic.")
    # Only the brief's own prompt and the harness's own TASK_PROMPT were
    # ever sent -- no reviewer call happened, proving the WHOLE pass (not
    # just its feedback) was skipped, not merely that it accepted silently.
    assert len(result["provider"].user_messages) == 2


def test_review_pass_wired_end_to_end_sends_the_model_back_once(
        drive: Callable[..., dict[str, Any]]) -> None:
    """Proves ``agent.py``'s closure -- the parsed brief and a second
    provider, both built inside ``run_agent`` and bound into
    ``review.hook`` -- actually reaches the harness's ``pre_final_hook``
    mechanism end to end. The direct unit tests above exercise
    ``review.hook`` in isolation; this is the one test that proves the
    wiring, not the mechanism twice (same principle as ``facets_agent``'s
    own end-to-end ``coverage_gate`` test)."""
    draft = (f"Congestion pricing directly cuts peak traffic. [{D[0]}]\n"
             "Revenue from the tolls often funds transit upgrades.")
    revised = (f"Congestion pricing directly cuts peak traffic. [{D[0]}]\n"
               f"Revenue from the tolls often funds transit upgrades. [{D[0]}]")
    script = [
        BRIEF_TURN_EMPTY,
        model_turn(reasoning=["Search once."], tool_calls=[tool_call(
            "search", {"query": "congestion pricing traffic reduction",
                      "search_engine": "semantic"}, id="s1")]),
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
    assert "#2" in result["provider"].user_messages[-1]
    assert result["output"]["answer"][-1]["citations"]


@pytest.mark.live
def test_run_agent_live() -> None:
    """Same path against the real ClimbMix + Bedrock endpoints (needs creds)."""
    system_prompt = load_system_prompt(DEFAULT_MAX_COMMITTED_PER_STEP)
    summary = brief_revise_run_agent(
        "live_smoke", QUERY, safety_max_rounds=20, k=5,
        system_prompt=system_prompt)
    assert summary["status"] in ("completed", "budget_exhausted")
    assert summary["n_references"] > 0
