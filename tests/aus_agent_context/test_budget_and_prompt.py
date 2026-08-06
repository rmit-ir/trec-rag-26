"""The context-budget instrumentation, and the staging adapter that feeds it.

Three small surfaces that only make sense next to the ledger, because they are
how the budget the ledger protects is *measured*, *reported*, and *bounded*:

- ``_budget_status_line`` / ``DEFAULT_CONTEXT_TOKEN_BUDGET`` — the readout the
  model self-paces against, appended to every tool result;
- ``_usage_token_stats``'s two distinct totals — logical context size (which the
  stop condition compares against the budget) versus processed/billed tokens.
  Conflating them either stops research early or bills a cache hit as a fresh
  prefill;
- ``truncate_result_text`` / ``execute_full_text_search`` — the per-result bound
  that makes "extra queries are cheap" true. Without it a single long document
  can consume the whole budget in one call, and no amount of committing later
  gets those tokens back.

Plus the system prompt loader, which is where the ledger's per-step cap becomes
something the model knows about.

Scope note: ``tests/systems/test_aus_agent.py`` also covers ``_usage_token_stats``
(cross-backend name normalization) and per-result truncation end-to-end through
the loop. What is here is the unit-level arithmetic and the adapter called
directly — the failure modes are different enough to be worth both.
"""
from __future__ import annotations

import json
from typing import Any

import pytest

from aus_agent import agent
from aus_agent.tools.search import (
    CHARS_PER_TOKEN_BUDGET,
    DEFAULT_BUDGET_TOKENS_PER_RESULT,
    execute_full_text_search,
    truncate_result_text,
)


# ---------------------------------------------------------------------------
# The budget readout
# ---------------------------------------------------------------------------
def test_the_default_context_budget_is_500k() -> None:
    """500k is the number the system prompt quotes, so the two must agree.

    The prompt tells the model its ceiling in words; this constant is what the
    loop enforces. If they diverge the model paces itself against a limit that is
    not the real one — either stopping early or being cut off mid-research.
    """
    assert agent.DEFAULT_CONTEXT_TOKEN_BUDGET == 500_000
    assert "500,000 tokens" in agent.load_system_prompt(10)


def test_the_status_line_renders_tokens_percent_and_elapsed() -> None:
    """This one line is the model's entire view of its remaining budget.

    It rides on every tool result rather than in a separate message, so it costs
    no turn and cannot be missed. Thousands separators and one decimal place are
    part of the contract: the model reads this as prose and compares it against
    the prompt's "500,000 tokens", so a raw ``82410`` reads as a different scale.
    """
    assert agent._budget_status_line(82_410, 500_000, 252_000) == (
        "[context budget: 82,410 / 500,000 tokens (16.5%) · "
        "elapsed: 4m 12s]")


def test_the_status_line_survives_a_zero_budget() -> None:
    """A zero budget must not raise on the division.

    ``run_agent`` rejects a non-positive budget up front, but this helper is also
    called while building trace stats, and a ``ZeroDivisionError`` there would
    take down a run over a formatting concern.
    """
    assert "(0.0%)" in agent._budget_status_line(10, 0, 0)


# ---------------------------------------------------------------------------
# Token accounting
# ---------------------------------------------------------------------------
def test_logical_context_and_billed_throughput_are_separate_totals() -> None:
    """One usage dict, two different questions — and they must not be conflated.

    ``input`` (170) is the logical context the model actually saw: uncached +
    cache reads + cache writes. That is what the stop condition compares against
    the budget. ``processed_input`` (120) excludes cache reads because a read is
    not a fresh prefill — that is the cost figure. Using ``processed`` as the
    context size would let a heavily-cached run believe it had budget left long
    after its conversation outgrew the window.
    """
    stats = agent._usage_token_stats({
        "inputTokens": 100,
        "outputTokens": 10,
        "cacheReadInputTokens": 50,
        "cacheWriteInputTokens": 20,
    })
    assert stats["input"] == 170
    assert stats["processed_input"] == 120
    assert stats["processed"] == 130
    assert stats["total"] == 180


# ---------------------------------------------------------------------------
# The system prompt
# ---------------------------------------------------------------------------
def test_the_prompt_renders_exactly_one_placeholder() -> None:
    """The per-step cap must reach the model, and only from one place.

    A second placeholder (or none) means the prompt and the enforced cap can
    disagree, which shows up as the model repeatedly over-selecting and losing
    documents to the clamp. Loudly refusing to load is better than rendering a
    prompt that lies — the check is a hard ``RuntimeError`` in
    ``load_system_prompt``.
    """
    default_path = (
        agent.SYSTEM_PROMPTS_DIR / f"{agent.DEFAULT_PROMPT_VARIANT}.md")
    template = default_path.read_text(encoding="utf-8")
    assert template.count(agent.MAX_COMMITTED_PLACEHOLDER) == 1

    prompt = agent.load_system_prompt(4)
    assert agent.MAX_COMMITTED_PLACEHOLDER not in prompt
    assert "Commit at most `4` results" in prompt


def _prompt_variants() -> list[str]:
    return sorted(p.stem for p in agent.SYSTEM_PROMPTS_DIR.glob("*.md"))


@pytest.mark.parametrize("variant", _prompt_variants())
def test_every_variant_keeps_the_shared_harness_contract(variant: str) -> None:
    """Variants are full copies, so the shared contract can drift silently.

    Each file under ``prompts/system/`` restates the whole system prompt, and
    an A/B is only single-variable if the parts that are NOT the experiment
    stay identical in substance. These are the clauses the harness itself
    enforces — the staged/committed protocol, the commit-then-report ordering,
    the budget the loop compares against, the report parser's two rules, and
    the one runtime placeholder. A variant that dropped any of them would fail
    as a run, not as a worse score, and the cause would be invisible in the
    scores it is being compared on.
    """
    template = (agent.SYSTEM_PROMPTS_DIR / f"{variant}.md").read_text(
        encoding="utf-8")
    assert template.count(agent.MAX_COMMITTED_PLACEHOLDER) == 1

    prompt = agent.load_system_prompt(7, variant)
    flat = " ".join(prompt.split())
    assert agent.MAX_COMMITTED_PLACEHOLDER not in prompt
    assert "Commit at most `7` results" in prompt
    assert "## Staged and committed evidence" in prompt
    assert "## Final response contract" in prompt
    assert "exactly one sentence per line" in prompt
    assert f"{agent.DEFAULT_CONTEXT_TOKEN_BUDGET:,} tokens" in prompt
    assert "commit first, and write the report on the following turn" in flat
    assert "Its results are staged exactly like a search batch" in flat
    # The two deliberate absences (see the default-prompt tests below).
    assert "ClimbMix" not in prompt
    assert "scratchpad" not in prompt.lower()


@pytest.mark.parametrize("variant", _prompt_variants())
def test_no_variant_reinstates_blanket_de_duplication(variant: str) -> None:
    """The selection rule is shared policy, not an experimental variable.

    ``commit_context``'s tool description now tells the model to adjudicate
    competing results against specificity criteria rather than discard
    similar-looking ones. A prompt that still said "skip semantically similar
    results" would contradict the tool on the one turn that matters, and would
    silently cancel a paired-engine round by throwing away the second engine's
    contribution as duplicate — the failure would look like "pairing did not
    help" rather than like a contradiction.
    """
    prompt = agent.load_system_prompt(7, variant)
    flat = " ".join(prompt.split())
    assert "Skip semantically similar results" not in flat
    assert "adjudicate" in flat.lower()


def test_the_prompt_teaches_the_commit_protocol_and_its_ordering() -> None:
    """The commit protocol is unusual enough that the prompt must state it.

    No pretrained model expects "your search results vanish unless you claim them
    next turn". Two specifics are load-bearing: the batch is staged for the
    IMMEDIATELY following turn, and the report comes the turn AFTER the commit —
    a run that reported straight from the staged batch burned 2x tokens redoing
    the round after its batch lapsed.
    """
    prompt = agent.load_system_prompt(10)
    flat = " ".join(prompt.split())
    assert "## Staged and committed evidence" in prompt
    assert "commit first, and write the report on the following turn" in flat


def test_the_prompt_never_names_the_corpus_or_an_unstaged_fetch() -> None:
    """Two deliberate absences, each with a failure mode behind it.

    Naming ClimbMix invites the model to answer from what it knows about the
    corpus instead of from retrieval. A scratchpad invites text nobody staged
    and nobody can compact.

    ``get_documents`` is the *staged* navigation tool — its results go through
    the same stage/commit protocol as a search batch, so it does not reopen the
    unbounded-growth hole an unstaged fetch would. The prompt must therefore
    present it as staged rather than as a free read.
    """
    prompt = agent.load_system_prompt(10)
    assert "ClimbMix" not in prompt
    assert "scratchpad" not in prompt.lower()
    flat = " ".join(prompt.split())
    assert "`get_documents`" in flat
    assert "Its results are staged exactly like a search batch" in flat


def test_the_report_contract_is_stated_in_the_prompt() -> None:
    """The parser rejects non-conforming reports, so the rules must be up front.

    Every bounce costs a full turn at full context, and by report time that is the
    most expensive turn of the run. The two rules the parser actually enforces —
    one sentence per line, square-bracket citations — are the two asserted here.
    """
    prompt = agent.load_system_prompt(10)
    assert "## Final response contract" in prompt
    assert "exactly one sentence per line" in prompt
    assert "square-bracket markers" in prompt


def test_the_word_count_excludes_citation_markers() -> None:
    """A report is measured on its prose, not on its bookkeeping.

    ``MAX_REPORT_WORDS`` is a rejection threshold, and rejection costs a turn.
    Counting markers would penalise a well-cited report — the report that cites
    most heavily would be the one most likely to be bounced for length.
    """
    text = " ".join(["word"] * 1024) + " [a]"
    sentences, errors, _ = agent._parse_final_prose(text, {"a"})
    assert errors == []
    assert agent._word_count(sentences) == 1024
    assert sentences[0]["citations"] == ["a"]


# ---------------------------------------------------------------------------
# Per-result staging bounds
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text,budget,expected,truncated", [
    pytest.param("short", 10, "short", False, id="under-budget-untouched"),
    pytest.param("first line\nsecond line\nthird line is beyond", 4,
                 "first line", True, id="cut-at-the-last-line-break"),
    pytest.param("a" * 100, 4, "a" * 20, True, id="no-line-break-hard-cut"),
])
def test_truncation_prefers_a_line_boundary(
        text: str, budget: int, expected: str, truncated: bool) -> None:
    """Cutting mid-line hands the model a fragment it may cite as a whole claim.

    The budget is in tokens and the bound is ``tokens × 5`` characters, so the
    boundary rarely falls on a sentence. Backing up to the last line break inside
    the budget keeps every retained line complete; with no break available the
    hard cut is the only option, which is why that case is pinned too.
    """
    result, did_truncate = truncate_result_text(text, budget_tokens=budget)
    assert result == expected
    assert did_truncate is truncated


def test_a_non_positive_budget_raises_rather_than_returning_nothing() -> None:
    """Zero would truncate every result to the empty string.

    A silent "every document is blank" is the worst failure mode available here:
    the run would continue, commit documents with no text, and produce a report
    citing evidence that says nothing. ``execute_full_text_search`` validates the
    argument before it reaches this function, and this is the backstop.
    """
    with pytest.raises(ValueError, match="must be positive"):
        truncate_result_text("text", budget_tokens=0)


def test_full_text_is_requested_from_the_engine_and_bounded_locally(
        fake_engine: dict[str, list[dict]], monkeypatch) -> None:
    """The adapter asks for UNBOUNDED text, then applies its own bound.

    ``max_chars=None`` is deliberate: the shared search tool defaults to 500
    characters, which would silently cap staging at a fraction of the AUS budget
    and make ``budget_tokens_per_result`` unable to raise it. So the character cap
    has to be this adapter's, applied after retrieval.
    """
    from tools import search_tool

    long_text = "x" * 900
    seen: list[dict[str, Any]] = []

    def _long(query: str, k: int = 10, **kw: Any) -> list[dict[str, Any]]:
        from utils.search_types import make_hit
        seen.append({"query": query, "k": k, **kw})
        return [make_hit("long", score=1.0, rank=1, text=long_text)]

    monkeypatch.setattr(search_tool, "_DISPATCH",
                        {e: _long for e in search_tool._DISPATCH})
    execution = execute_full_text_search(
        {"query": "full text", "search_engine": "semantic"},
        default_k=10, seen_docids=set())

    assert execution.failed is False
    # 900 chars is well under the 4096-token default bound, so nothing was cut.
    assert len(execution.documents[0]["text"]) == 900
    assert long_text in execution.output


def test_a_bounded_result_reports_what_it_cut(
        monkeypatch) -> None:
    """Truncation is announced in the payload, not applied silently.

    The model has to know a document is incomplete before it decides to commit it
    — otherwise it retains a fragment believing it holds the whole document, and
    cites it accordingly. ``original_chars``/``returned_chars`` also let a
    reviewer see how much of the corpus a run never actually read.
    """
    from tools import search_tool
    from utils.search_types import make_hit

    text = "first line\nsecond line\nthird line is beyond"

    def _long(query: str, k: int = 10, **kw: Any) -> list[dict[str, Any]]:
        return [make_hit("long", score=1.0, rank=1, text=text)]

    monkeypatch.setattr(search_tool, "_DISPATCH",
                        {e: _long for e in search_tool._DISPATCH})
    execution = execute_full_text_search(
        {"query": "bounded", "search_engine": "semantic",
         "budget_tokens_per_result": 4},
        default_k=10, seen_docids=set())

    payload = json.loads(execution.output)
    result = payload["results"][0]
    assert result["text"] == "first line"
    assert result["truncated"] is True
    assert result["original_chars"] == len(text)
    assert result["returned_chars"] == 10
    assert payload["budget_tokens_per_result"] == 4


def test_the_model_engine_choice_is_the_only_thing_that_routes(
        monkeypatch) -> None:
    """Only the model's own ``search_engine`` reaches the dispatch table.

    There is deliberately no harness-side fallback: if the adapter picked an
    engine for a silent call, a trajectory row would attribute the hits to a
    backend the model never chose, and the per-engine effectiveness comparison
    that the whole single-engine run mode exists for would be measuring the
    harness's default instead of the experiment's engine.
    """
    from tools import search_tool

    routed: list[str] = []

    def _make(engine: str):
        def _spy(query: str, k: int = 10, **kw: Any) -> list[dict[str, Any]]:
            routed.append(engine)
            return []
        return _spy

    monkeypatch.setattr(search_tool, "_DISPATCH",
                        {e: _make(e) for e in search_tool._DISPATCH})
    for engine in ("keyword", "ssr"):
        execute_full_text_search({"query": "q", "search_engine": engine},
                                 default_k=10, seen_docids=set(),
                                 engines=["semantic", "keyword", "ssr"])

    assert routed == ["keyword", "ssr"]


def test_an_omitted_engine_is_an_error_naming_the_enabled_set(
        monkeypatch) -> None:
    """A silent ``search_engine`` costs the call, not a guess.

    ``search_engine`` is required by the schema, so an omission is a model
    mistake; answering it with an error that names the run's enabled engines
    lets the model retry on the next turn, whereas routing it to a default
    would hide the mistake and corrupt the engine attribution in the trace.
    """
    from tools import search_tool

    monkeypatch.setattr(search_tool, "_DISPATCH",
                        {e: lambda *a, **kw: pytest.fail("must not dispatch")
                         for e in search_tool._DISPATCH})
    execution = execute_full_text_search({"query": "q"}, default_k=10,
                                         seen_docids=set(),
                                         engines=["semantic", "ssr"])
    assert execution.failed and execution.documents == []
    assert "search_engine is required" in execution.trace_output["error"]
    assert "'semantic', 'ssr'" in execution.trace_output["error"]


def test_the_default_staging_budget_is_the_documented_one() -> None:
    """4096 tokens × 5 chars is the number the tool schema advertises.

    The model reads the default from the tool description and reasons about how
    many queries it can afford; a constant that drifted from the schema's
    ``default`` would make that reasoning wrong in a way nothing else surfaces.
    """
    assert DEFAULT_BUDGET_TOKENS_PER_RESULT == 4096
    assert CHARS_PER_TOKEN_BUDGET == 5
    from aus_agent.tools.search import build_search_tool_def
    schema = build_search_tool_def(["semantic"])["input_schema"]
    assert (schema["properties"]["budget_tokens_per_result"]["default"]
            == DEFAULT_BUDGET_TOKENS_PER_RESULT)
