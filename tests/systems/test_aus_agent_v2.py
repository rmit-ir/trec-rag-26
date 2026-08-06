"""End-to-end protection for v2's plan -> research -> evidence-patch pipeline.

The research loop itself deliberately reuses the well-tested ``aus_agent``
ledger and tools. These tests defend the new stage boundaries and the critical
property the failed whole-answer writer lacked: finishing cannot delete an
unmentioned draft claim.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

import pytest
from conftest import CLIMBMIX_DOCIDS, ScriptedProvider, model_turn, tool_call

from aus_agent_v2 import agent as agent_mod
from aus_agent_v2 import pipeline as pipeline_mod
from aus_agent_v2.agent import run_agent

QID = "mock_aus_v2_001"
QUERY = "How effective is congestion pricing at reducing traffic?"
D = CLIMBMIX_DOCIDS


def test_run_script_imports_sibling_systems_without_pytest_path_help() -> None:
    """Direct CLI execution lacks pytest's src/systems path and must add it."""
    root = Path(__file__).resolve().parents[2]
    completed = subprocess.run(
        [sys.executable, str(root / "src/systems/aus_agent_v2/run.py"), "--help"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "--coverage-plan" in completed.stdout
    assert "--plan-critic" in completed.stdout
    assert "--coverage-scout" in completed.stdout
    assert "--plan-reconcile" in completed.stdout


def test_public_pipeline_uses_only_the_confirmed_default_stages(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Experimental editors must not silently replace the full-30 winner."""
    captured: dict[str, Any] = {}

    def fake_run_agent(qid: str, narrative: str, **kwargs: Any) -> dict[str, Any]:
        captured.update({"qid": qid, "narrative": narrative, **kwargs})
        return {"status": "completed"}

    monkeypatch.setattr(pipeline_mod, "run_agent", fake_run_agent)

    result = pipeline_mod.run_one(
        qid=QID,
        narrative=QUERY,
        run_id="confirmed-default",
    )

    assert result == {"status": "completed"}
    assert captured["k"] == 20
    assert captured["safety_max_rounds"] == 40
    assert captured["coverage_plan"] is True
    assert captured["plan_critic"] is True
    assert captured["observable_scout"] is False
    assert captured["plan_reconcile"] is False
    assert captured["coverage_verify"] is False
    assert captured["audience_verify"] is False
    assert captured["finish_review"] is False
    assert captured["answer_blueprint"] is False


@pytest.fixture
def drive(monkeypatch: pytest.MonkeyPatch,
          stub_search_tool: dict[str, list[dict[str, Any]]],
          ) -> Callable[..., dict[str, Any]]:
    """Substitute only model transport; retrieval and artifact code stay real."""
    def _drive(script: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
        provider = ScriptedProvider(script)
        monkeypatch.setattr(
            agent_mod,
            "make_provider",
            lambda backend, model, region=None: provider,
        )
        kwargs.setdefault("k", 1)
        kwargs.setdefault("safety_max_rounds", 20)
        kwargs.setdefault("finish_review", True)
        kwargs.setdefault("plan_critic", False)
        kwargs.setdefault("plan_reconcile", False)
        kwargs.setdefault("coverage_verify", False)
        kwargs.setdefault("audience_verify", False)
        summary = run_agent(QID, QUERY, run_id="aus-agent-v2.mock", **kwargs)
        trajectory = json.loads(summary["paths"]["trajectory"].read_text())
        output = json.loads(summary["paths"]["output"].read_text())
        return {
            "summary": summary,
            "provider": provider,
            "trajectory": trajectory,
            "output": output,
            "trace": output["trace"],
            "calls": stub_search_tool,
        }

    return _drive


def _script(patch_response: str) -> list[dict[str, Any]]:
    """The five turns make every architecture boundary observable in tests."""
    draft = (
        f"Toll revenue funds the capital plan. [{D[0]}]\n"
        f"Peak-period drivers earn more than transit riders. [{D[0]}]"
    )
    return [
        model_turn(text=(
            "1. DELIVERABLE: explain effects.\n"
            "2. EVIDENCE: find measured traffic and equity results."
        )),
        model_turn(tool_calls=[tool_call(
            "search",
            {"query": "congestion pricing measured effects",
             "search_engine": "semantic", "k": 1},
            id="s1",
        )]),
        model_turn(tool_calls=[tool_call(
            "commit_context",
            {"documents": [{"id": D[0], "reason": "measured effects"}]},
            id="c1",
        )]),
        model_turn(text=draft),
        model_turn(text=patch_response),
    ]


def test_pipeline_applies_one_patch_without_rewriting_other_claims(
        drive: Callable[..., dict[str, Any]]) -> None:
    """A local precision edit must leave the unrelated equity point intact."""
    response = json.dumps({"edits": [{
        "line": 1,
        "replacement": (
            f"Toll revenue from the program funds the capital plan. [{D[0]}]"
        ),
    }]})

    result = drive(_script(response))

    assert result["summary"]["status"] == "completed"
    assert result["provider"].turn_index == 5
    assert result["output"]["answer"] == [
        {
            "text": "Toll revenue from the program funds the capital plan.",
            "citations": [0],
        },
        {
            "text": "Peak-period drivers earn more than transit riders.",
            "citations": [0],
        },
    ]
    finish = result["trace"]["summary"]["finish_review"]
    assert finish["patches"] == {"proposed": 1, "accepted": 1, "rejected": 0}
    assert finish["patch_errors"] == []
    assert result["provider"].tools == []


def test_non_json_whole_answer_falls_back_to_original_draft(
        drive: Callable[..., dict[str, Any]]) -> None:
    """A model that tries the old destructive rewrite path gets no write access."""
    result = drive(_script(f"Traffic changed. [{D[0]}]"))

    assert [item["text"] for item in result["output"]["answer"]] == [
        "Toll revenue funds the capital plan.",
        "Peak-period drivers earn more than transit riders.",
    ]
    finish = result["trace"]["summary"]["finish_review"]
    assert finish["patches"] == {"proposed": 0, "accepted": 0, "rejected": 0}
    assert finish["patch_errors"]


def test_fresh_context_boundaries_are_archived_in_order(
        drive: Callable[..., dict[str, Any]]) -> None:
    """Stage isolation is only reproducible when the raw trace names transitions."""
    result = drive(_script('{"edits":[]}'))

    boundaries = [
        item["phase"] for item in result["trajectory"]["raw_messages"]
        if item.get("type") == "phase_boundary"
    ]
    assert boundaries == [
        "coverage_plan_to_research",
        "research_to_evidence_patcher",
    ]
    assert "CITATION-LOCAL EVIDENCE CARDS" in result["provider"].user_messages[-1]


def test_answer_blueprint_replays_commit_facts_before_accepting_prose(
        drive: Callable[..., dict[str, Any]]) -> None:
    """Extracted facts must reach the writer's newest context, not die in history."""
    early_draft = f"Traffic fell after pricing. [{D[0]}]"
    finished = (
        f"Traffic volume fell by 12% in the priced zone in 2025. [{D[0]}]"
    )
    script = [
        model_turn(text="1. EFFECT: quantify the measured traffic change."),
        model_turn(tool_calls=[tool_call(
            "search",
            {"query": "congestion pricing measured traffic change",
             "search_engine": "semantic", "k": 1},
            id="s1",
        )]),
        model_turn(tool_calls=[tool_call(
            "commit_context",
            {"documents": [{
                "id": D[0],
                "reason": "measured effect",
                "facts": [{
                    "claim": "Traffic volume",
                    "value": "fell by 12%",
                    "scope": "priced zone in 2025",
                    "source": "transport authority evaluation",
                }],
            }]},
            id="c1",
        )]),
        model_turn(text=early_draft),
        model_turn(tool_calls=[tool_call(
            "prepare_answer",
            {
                "requirements": [{
                    "requirement": "Quantify the measured traffic change.",
                    "claims": [{
                        "claim": (
                            "Traffic volume fell by 12% in the priced zone "
                            "in 2025."
                        ),
                        "evidence_ids": [D[0]],
                    }],
                }],
                "unresolved": [],
            },
            id="b1",
        )]),
        model_turn(text=finished),
    ]

    result = drive(
        script,
        answer_blueprint=True,
        finish_review=False,
    )

    assert result["summary"]["status"] == "completed"
    assert result["provider"].turn_index == 6
    assert result["output"]["answer"][0]["text"] == finished.rsplit(" [", 1)[0]
    assert "prepare_answer now" in result["provider"].user_messages[-1]
    handoff = result["provider"].tool_results[-1][0]["content"]
    assert "ANSWER BLUEPRINT ACCEPTED" in handoff
    assert "fell by 12%" in handoff
    assert "transport authority evaluation" in handoff
    blueprint = result["trace"]["summary"]["answer_blueprint"]
    assert blueprint["prepared"] is True
    assert blueprint["mapped_claims"] == 1
    assert blueprint["fact_cards"] == 1


def test_fresh_verifier_routes_gap_to_preservation_safe_claim_patcher(
        monkeypatch: pytest.MonkeyPatch,
        stub_search_tool: dict[str, list[dict[str, Any]]]) -> None:
    """A planned fact lost in drafting must be patched without answer authority."""
    first_draft = f"Toll revenue requires institutional oversight. [{D[0]}]"
    repaired = (
        f"Toll revenue requires institutional oversight and funds the MTA "
        f"capital plan. [{D[0]}]"
    )
    research = ScriptedProvider([
        model_turn(text="11. SAFETY: name the MTA capital plan explicitly."),
        model_turn(tool_calls=[tool_call(
            "search",
            {"query": "MTA capital plan oversight",
             "search_engine": "semantic", "k": 1},
            id="s1",
        )]),
        model_turn(tool_calls=[tool_call(
            "commit_context",
            {"documents": [{"id": D[0], "reason": "capital oversight"}]},
            id="c1",
        )]),
        model_turn(text=first_draft),
    ])
    verifier = ScriptedProvider([model_turn(text=json.dumps({
        "verdict": "repair",
            "missing": [{
                "plan_item": 11,
                "requirement": "Name the MTA capital plan explicitly.",
                "draft_gap": "The draft says oversight but omits the named plan.",
            }],
        }))])
    patcher = ScriptedProvider([model_turn(text=json.dumps({
        "patches": [{
            "finding": 1,
            "mode": "replace",
            "line": 1,
            "sentence": repaired,
        }],
    }))])
    transient_failure = ScriptedProvider([])
    providers = iter([research, transient_failure, verifier, patcher])
    monkeypatch.setattr(
        agent_mod,
        "make_provider",
        lambda backend, model, region=None: next(providers),
    )

    summary = run_agent(
        QID,
        QUERY,
        run_id="aus-agent-v2.verify.mock",
        k=1,
        safety_max_rounds=20,
        coverage_plan=True,
        plan_critic=False,
        coverage_verify=True,
        audience_verify=False,
        finish_review=False,
    )
    output = json.loads(summary["paths"]["output"].read_text())

    assert output["answer"][0]["text"].endswith("the MTA capital plan.")
    assert "MATERIAL FINDINGS" in patcher.user_messages[-1]
    verify = output["trace"]["summary"]["coverage_verify"]
    assert verify["verdict"] == "repair"
    assert verify["missing"][0]["plan_item"] == 11
    assert len(verify["attempt_errors"]) == 1
    assert verify["patches"] == {
        "proposed": 1, "accepted": 1, "rejected": 0}
    assert verifier.tools == []


def test_fresh_plan_critic_adds_a_searchable_requirement_before_research(
        monkeypatch: pytest.MonkeyPatch,
        stub_search_tool: dict[str, list[dict[str, Any]]]) -> None:
    """A second context must change evidence acquisition, not merely annotate trace."""
    research = ScriptedProvider([
        model_turn(text="1. EXPLICIT: compare measured traffic effects."),
        model_turn(tool_calls=[tool_call(
            "search",
            {"query": "congestion pricing equity distribution measured",
             "search_engine": "semantic", "k": 1},
            id="s1",
        )]),
        model_turn(tool_calls=[tool_call(
            "commit_context",
            {"documents": [{"id": D[0], "reason": "equity evidence"}]},
            id="c1",
        )]),
        model_turn(text=(
            f"Traffic fell and distributional effects varied by group. [{D[0]}]"
        )),
    ])
    critic = ScriptedProvider([model_turn(text=json.dumps({
        "verdict": "add",
        "additions": [{
            "requirement": "Compare distributional effects across groups.",
            "reason": "A policy-effectiveness answer is incomplete without equity.",
            "search_leads": ["congestion pricing equity distribution measured"],
        }],
    }))])
    providers = iter([research, critic])
    monkeypatch.setattr(
        agent_mod,
        "make_provider",
        lambda backend, model, region=None: next(providers),
    )

    summary = run_agent(
        QID,
        QUERY,
        run_id="aus-agent-v2.critic.mock",
        k=1,
        safety_max_rounds=20,
        coverage_plan=True,
        plan_critic=True,
        observable_scout=False,
        plan_reconcile=False,
        coverage_verify=False,
        finish_review=False,
    )
    output = json.loads(summary["paths"]["output"].read_text())

    assert "Compare distributional effects" in research.user_messages[-1]
    critic_summary = output["trace"]["summary"]["plan_critic"]
    assert critic_summary["verdict"] == "add"
    assert len(critic_summary["additions"]) == 1
    assert critic.tools == []


def test_plan_reconciler_replaces_additive_breadth_with_priority_contract(
        monkeypatch: pytest.MonkeyPatch,
        stub_search_tool: dict[str, list[dict[str, Any]]]) -> None:
    """Research should receive the compiled contract, not every proposed item."""
    research = ScriptedProvider([
        model_turn(text="1. CORE: compare traffic effects."),
        model_turn(tool_calls=[tool_call(
            "search",
            {"query": "congestion pricing measured effects",
             "search_engine": "semantic", "k": 1},
            id="s1",
        )]),
        model_turn(tool_calls=[tool_call(
            "commit_context",
            {"documents": [{"id": D[0], "reason": "measured effects"}]},
            id="c1",
        )]),
        model_turn(text=f"Traffic fell after pricing. [{D[0]}]"),
    ])
    critic = ScriptedProvider([model_turn(text=json.dumps({
        "verdict": "add",
        "additions": [{
            "requirement": "Name the accountable authority.",
            "reason": "Implementation needs ownership.",
            "search_leads": ["transport authority implementation"],
        }],
    }))])
    reconciled = """\
1. DELIVERABLE: Produce one concise policy assessment.
2. AUDIENCE: Define congestion pricing for a general reader.
3. CORE: State the measured traffic effect.
4. CORE: Explain the comparison baseline and time scope.
5. SAFETY: Avoid unsupported causal generalization.
6. EVIDENCE: Use one measured result with place and period.
7. LATENT: Name the accountable transport authority.
8. BUDGET: Allocate 840 first-draft words across evidence, tradeoffs, and conclusion."""
    reconciler = ScriptedProvider([model_turn(text=reconciled)])
    providers = iter([research, critic, reconciler])
    monkeypatch.setattr(
        agent_mod,
        "make_provider",
        lambda backend, model, region=None: next(providers),
    )

    summary = run_agent(
        QID,
        QUERY,
        run_id="aus-agent-v2.reconcile.mock",
        k=1,
        safety_max_rounds=20,
        coverage_plan=True,
        plan_critic=True,
        observable_scout=False,
        plan_reconcile=True,
        coverage_verify=False,
        audience_verify=False,
        finish_review=False,
    )
    output = json.loads(summary["paths"]["output"].read_text())

    assert reconciled in research.user_messages[-1]
    assert output["trace"]["summary"]["plan_reconcile"]["applied"] is True
    assert reconciler.tools == []


def test_observable_scout_adds_a_distinct_countable_unit(
        monkeypatch: pytest.MonkeyPatch,
        stub_search_tool: dict[str, list[dict[str, Any]]]) -> None:
    """The second lens must reach research rather than exist only in trace."""
    research = ScriptedProvider([
        model_turn(text="1. CORE: compare traffic effects."),
        model_turn(tool_calls=[tool_call(
            "search",
            {"query": "congestion pricing named software measured effects",
             "search_engine": "semantic", "k": 1},
            id="s1",
        )]),
        model_turn(tool_calls=[tool_call(
            "commit_context",
            {"documents": [{"id": D[0], "reason": "measured effects"}]},
            id="c1",
        )]),
        model_turn(text=f"Traffic fell after pricing. [{D[0]}]"),
    ])
    critic = ScriptedProvider([model_turn(text=json.dumps({
        "verdict": "pass", "additions": [],
    }))])
    observable = ScriptedProvider([model_turn(text=json.dumps({
        "verdict": "add",
        "additions": [{
            "kind": "term",
            "requirement": "Name one usable analysis package.",
            "must_mention": ["pandas"],
            "reason": "A novice needs an actionable tool.",
            "search_leads": ["congestion pricing pandas analysis"],
        }],
    }))])
    providers = iter([research, critic, observable])
    monkeypatch.setattr(
        agent_mod,
        "make_provider",
        lambda backend, model, region=None: next(providers),
    )

    summary = run_agent(
        QID,
        QUERY,
        run_id="aus-agent-v2.observable.mock",
        k=1,
        safety_max_rounds=20,
        coverage_plan=True,
        plan_critic=True,
        observable_scout=True,
        plan_reconcile=False,
        coverage_verify=False,
        finish_review=False,
    )
    output = json.loads(summary["paths"]["output"].read_text())

    assert "Name one usable analysis package" in research.user_messages[-1]
    scout = output["trace"]["summary"]["observable_scout"]
    assert scout["requested"] is True
    assert scout["combined_additions"] == 1
    assert observable.tools == []


def test_claim_patcher_never_restarts_research_search(
        monkeypatch: pytest.MonkeyPatch,
        stub_search_tool: dict[str, list[dict[str, Any]]]) -> None:
    """Post-draft completion can only use evidence research already committed."""
    draft = f"Toll revenue requires institutional oversight. [{D[0]}]"
    repaired = (
        f"Toll revenue requires institutional oversight and funds the MTA "
        f"capital plan. [{D[0]}]"
    )
    research = ScriptedProvider([
        model_turn(text="1. SAFETY: name the MTA capital plan explicitly."),
        model_turn(tool_calls=[tool_call(
            "search",
            {"query": "MTA capital plan", "search_engine": "semantic", "k": 1},
            id="s1",
        )]),
        model_turn(tool_calls=[tool_call(
            "commit_context",
            {"documents": [{"id": D[0], "reason": "capital evidence"}]},
            id="c1",
        )]),
        model_turn(text=draft),
    ])
    verifier = ScriptedProvider([model_turn(text=json.dumps({
        "verdict": "repair",
            "missing": [{
                "plan_item": 1,
                "requirement": "Name the MTA capital plan explicitly.",
                "draft_gap": "The draft only says institutional oversight.",
            }],
        }))])
    patcher = ScriptedProvider([model_turn(text=json.dumps({
        "patches": [{
            "finding": 1,
            "mode": "replace",
            "line": 1,
            "sentence": repaired,
        }],
    }))])
    providers = iter([research, verifier, patcher])
    monkeypatch.setattr(
        agent_mod,
        "make_provider",
        lambda backend, model, region=None: next(providers),
    )

    summary = run_agent(
        QID,
        QUERY,
        run_id="aus-agent-v2.repair-budget.mock",
        k=1,
        safety_max_rounds=20,
        coverage_plan=True,
        plan_critic=False,
        coverage_verify=True,
        audience_verify=False,
        finish_review=False,
    )
    output = json.loads(summary["paths"]["output"].read_text())

    assert len(stub_search_tool["semantic"]) == 1
    verify = output["trace"]["summary"]["coverage_verify"]
    assert verify["repair_search_batches"] == 0
    assert verify["repair_search_batch_cap"] == 1
    assert verify["patches"]["accepted"] == 1
    assert output["answer"][0]["text"].endswith("the MTA capital plan.")


@pytest.mark.parametrize("strategy", ["patch-first", "research-first"])
def test_zero_grounded_patches_reopen_one_bounded_research_batch(
        monkeypatch: pytest.MonkeyPatch,
        stub_search_tool: dict[str, list[dict[str, Any]]],
        strategy: str) -> None:
    """Both policies must reach evidence retrieval when local evidence is absent."""
    first_draft = f"Traffic fell after congestion pricing. [{D[0]}]"
    repaired_draft = (
        f"Traffic fell after congestion pricing. [{D[0]}]\n"
        f"The MTA capital plan is the closest measured implementation "
        f"precedent. [{D[1]}]"
    )
    research = ScriptedProvider([
        model_turn(text="1. EVIDENCE: name the measured implementation."),
        model_turn(tool_calls=[tool_call(
            "search",
            {"query": "congestion pricing measured effects",
             "search_engine": "semantic", "k": 2},
            id="s1",
        )]),
        model_turn(tool_calls=[tool_call(
            "commit_context",
            {"documents": [{"id": D[0], "reason": "measured effects"}]},
            id="c1",
        )]),
        model_turn(text=first_draft),
        model_turn(tool_calls=[tool_call(
            "search",
            {"query": "MTA capital plan measured implementation precedent",
             "search_engine": "keyword", "k": 2},
            id="s2",
        )]),
        model_turn(tool_calls=[tool_call(
            "commit_context",
            {"documents": [{"id": D[1], "reason": "named precedent"}]},
            id="c2",
        )]),
        model_turn(text=repaired_draft),
    ])
    verifier = ScriptedProvider([model_turn(text=json.dumps({
        "verdict": "repair",
        "missing": [{
            "plan_item": 1,
            "requirement": "Name a measured implementation precedent.",
            "draft_gap": "The draft gives an effect but no named precedent.",
        }],
    }))])
    patcher = ScriptedProvider([model_turn(text='{"patches":[]}')])
    providers = iter(
        [research, verifier, patcher]
        if strategy == "patch-first" else [research, verifier])
    monkeypatch.setattr(
        agent_mod,
        "make_provider",
        lambda backend, model, region=None: next(providers),
    )

    summary = run_agent(
        QID,
        QUERY,
        run_id="aus-agent-v2.research-repair.mock",
        k=2,
        safety_max_rounds=20,
        coverage_plan=True,
        plan_critic=False,
        coverage_verify=True,
        coverage_repair_strategy=strategy,
        audience_verify=False,
        finish_review=False,
    )
    output = json.loads(summary["paths"]["output"].read_text())

    assert [item["text"] for item in output["answer"]] == [
        "Traffic fell after congestion pricing.",
        "The MTA capital plan is the closest measured implementation precedent.",
    ]
    assert len(stub_search_tool["semantic"]) == 1
    assert len(stub_search_tool["keyword"]) == 1
    verify = output["trace"]["summary"]["coverage_verify"]
    assert verify["repair_strategy"] == strategy
    assert verify["patches"] == {
        "proposed": 0, "accepted": 0, "rejected": 0}
    assert verify["research_repair_active"] is True
    assert verify["repair_search_batches"] == 1
    assert "at most one parallel search batch" in research.user_messages[-1]


def test_plan_independent_audience_gap_joins_the_grounded_repair(
        monkeypatch: pytest.MonkeyPatch,
        stub_search_tool: dict[str, list[dict[str, Any]]]) -> None:
    """A planner blind spot must reach the evidence-owning writer without a new answerer."""
    draft = f"Traffic fell after congestion pricing. [{D[0]}]"
    research = ScriptedProvider([
        model_turn(text="1. EXPLICIT: report measured traffic effects."),
        model_turn(tool_calls=[tool_call(
            "search",
            {"query": "congestion pricing measured effects",
             "search_engine": "semantic", "k": 1},
            id="s1",
        )]),
        model_turn(tool_calls=[tool_call(
            "commit_context",
            {"documents": [{"id": D[0], "reason": "measured effects"}]},
            id="c1",
        )]),
        model_turn(text=draft),
    ])
    plan_verifier = ScriptedProvider([model_turn(text=json.dumps({
        "verdict": "pass", "missing": [],
    }))])
    audience_verifier = ScriptedProvider([model_turn(text=json.dumps({
        "verdict": "repair",
        "missing": [{
            "requirement": "Name the authority accountable for capital oversight.",
            "draft_gap": "The implementation owner is absent.",
            "search_lead": "transport authority capital oversight",
        }],
    }))])
    patcher = ScriptedProvider([model_turn(text=json.dumps({
        "insertions": [{
            "finding": 1,
            "after_line": 1,
            "sentence": (
                f"The transport authority is accountable for capital "
                f"oversight. [{D[0]}]"
            ),
        }],
    }))])
    providers = iter([research, plan_verifier, audience_verifier, patcher])
    monkeypatch.setattr(
        agent_mod,
        "make_provider",
        lambda backend, model, region=None: next(providers),
    )

    summary = run_agent(
        QID,
        QUERY,
        run_id="aus-agent-v2.audience-verify.mock",
        k=1,
        safety_max_rounds=20,
        coverage_plan=True,
        plan_critic=False,
        coverage_verify=True,
        audience_verify=True,
        finish_review=False,
    )
    output = json.loads(summary["paths"]["output"].read_text())

    assert [item["text"] for item in output["answer"]] == [
        "Traffic fell after congestion pricing.",
        "The transport authority is accountable for capital oversight.",
    ]
    audience = output["trace"]["summary"]["audience_verify"]
    assert audience["verdict"] == "repair"
    assert audience["missing"][0]["requirement"].startswith("Name the authority")
    assert audience["patches"] == {
        "proposed": 1, "accepted": 1, "rejected": 0}
    assert audience_verifier.tools == []
    assert patcher.tools == []


@pytest.mark.live
def test_run_agent_v2_live() -> None:
    """The real provider/search path stays exercisable outside hermetic CI."""
    result = run_agent(
        QID,
        QUERY,
        backend="openai",
        run_id="aus-agent-v2-live-test",
        safety_max_rounds=20,
    )
    assert result["status"] in {"completed", "budget_exhausted"}
    assert result["n_references"] > 0
