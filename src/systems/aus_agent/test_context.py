from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from systems.aus_agent import agent
from systems.aus_agent.context import (
    ContextLedger,
    DUPLICATE_PREFIX,
    REJECTION_PREFIX,
)
from systems.aus_agent.providers.base import Provider
from systems.aus_agent.providers.bedrock import BedrockProvider
from systems.aus_agent.tools import (
    documents_from_search,
    truncate_result_text,
)
from systems.aus_agent.tools import search as aus_search


def _turn(*, text: str = "", calls: list[dict] | None = None,
          input_tokens: int = 100, output_tokens: int = 10) -> dict:
    calls = calls or []
    blocks = []
    if text:
        blocks.append({"type": "text", "text": text})
    blocks.extend({"type": "tool_call", "call": call} for call in calls)
    return {
        "blocks": blocks,
        "reasoning_blocks": [],
        "tool_calls": calls,
        "text": text or None,
        "stop_reason": "tool_use" if calls else "end_turn",
        "usage": {
            "inputTokens": input_tokens,
            "outputTokens": output_tokens,
            "totalTokens": input_tokens + output_tokens,
        },
        "raw": {},
    }


def _call(call_id: str, name: str, **arguments: object) -> dict:
    return {"id": call_id, "name": name, "arguments": arguments}


class FakeProvider(Provider):
    model_id = "fake-model"

    def __init__(self, turns: list[dict]) -> None:
        self.turns = iter(turns)
        self.messages: list[dict] = []
        self.tool_results: dict[str, str] = {}

    def start(self, system_prompt: str, tools: list[dict]) -> None:
        self.system_prompt = system_prompt
        self.tools = tools

    def add_user_message(self, text: str) -> None:
        self.messages.append({"role": "user", "text": text})

    def run_turn(self) -> dict:
        turn = next(self.turns)
        self.messages.append({"role": "assistant", "turn": turn})
        return turn

    def add_tool_results(self, results: list[dict]) -> None:
        for result in results:
            self.tool_results[result["id"]] = result["content"]
        self.messages.append({"role": "tool", "results": results})

    def compact_tool_results(self, replacements: dict[str, str]) -> None:
        for call_id, content in replacements.items():
            if call_id not in self.tool_results:
                raise KeyError(call_id)
            self.tool_results[call_id] = content

    @property
    def raw_messages(self) -> list:
        return self.messages


def _search_output(query: str, k: int = 10, **_: object) -> str:
    bases = {
        "alpha": ("a", "b", "c"),
        "beta": ("d", "e", "f"),
        "gamma": ("g", "h", "i"),
    }
    docids = bases[query]
    return json.dumps({
        "query": query,
        "k": k,
        "results": [
            {
                "rank": rank,
                "id": docid,
                "docid": docid,
                "kind": "document",
                "rrf_score": 1 / rank,
                "text": f"full staged text for {docid}",
            }
            for rank, docid in enumerate(docids, 1)
        ],
    })


class ContextLedgerTest(unittest.TestCase):
    def test_compaction_keeps_selected_text_and_replaces_rejected_text(self):
        payload = _search_output("alpha")
        status_line = (
            "[context budget: 100 / 500,000 tokens (0.0%) · elapsed: 0m 1s]")
        output = payload + "\n" + status_line
        documents = documents_from_search(json.loads(payload))
        ledger = ContextLedger()
        ledger.stage("search-1", "search", output, documents)

        decision = ledger.commit(
            [{"docid": "b", "reason": "direct evidence"}],
            max_documents=2,
        )
        compacted_text = decision.replacements["search-1"]
        compacted = json.loads(compacted_text.splitlines()[0])

        self.assertEqual(decision.committed, ["b"])
        self.assertEqual([r["docid"] for r in decision.rejected], ["a", "c"])
        self.assertIn("text", compacted["results"][1])
        self.assertNotIn("text", compacted["results"][0])
        self.assertTrue(
            compacted["results"][0]["decision"].startswith(REJECTION_PREFIX))
        self.assertTrue(compacted_text.endswith(status_line))
        self.assertFalse(ledger.has_staged)

    def test_commit_rejects_unknown_and_clamps_oversized_selections(self):
        output = _search_output("alpha")
        documents = documents_from_search(json.loads(output))
        ledger = ContextLedger()
        ledger.stage("search-1", "search", output, documents)
        with self.assertRaisesRegex(ValueError, "outside the staged"):
            ledger.commit(
                [{"docid": "missing", "reason": "no"}], max_documents=2)
        with self.assertRaisesRegex(ValueError, "distinct evidence reason"):
            ledger.commit(
                [{"docid": "a", "reason": ""}], max_documents=2)
        decision = ledger.commit([
            {"docid": "a", "reason": "one"},
            {"docid": "b", "reason": "two"},
            {"docid": "c", "reason": "three"},
        ], max_documents=2)
        self.assertEqual(decision.committed, ["a", "b"])
        self.assertEqual(
            decision.rejected,
            [{"docid": "c",
              "reason": "selection exceeded per-step maximum of 2"}],
        )

    def test_already_committed_docid_is_never_retained_twice(self):
        output = _search_output("alpha")
        documents = documents_from_search(json.loads(output))
        ledger = ContextLedger()
        ledger.stage("first", "search", output, documents)
        first = ledger.commit(
            [{"docid": "a", "reason": "first distinct fact"}],
            max_documents=3,
        )
        self.assertEqual(first.committed, ["a"])

        ledger.stage("second", "search", output, documents)
        second = ledger.commit([
            {"docid": "a", "reason": "same fact again"},
            {"docid": "b", "reason": "materially different evidence"},
        ], max_documents=3)

        self.assertEqual(second.committed, ["b"])
        self.assertIn({
            "docid": "a",
            "reason": "duplicate/already committed; later occurrence compacted",
        }, second.rejected)
        compacted = second.replacements["second"]
        payload = json.loads(compacted.splitlines()[0])
        by_docid = {item["docid"]: item for item in payload["results"]}
        self.assertNotIn("text", by_docid["a"])
        self.assertIn(DUPLICATE_PREFIX, by_docid["a"]["decision"])
        self.assertIn("text", by_docid["b"])

    def test_parallel_duplicate_occurrence_is_kept_in_full_only_once(self):
        output = _search_output("alpha")
        documents = documents_from_search(json.loads(output))
        ledger = ContextLedger()
        ledger.stage("q1", "search", output, documents)
        ledger.stage("q2", "search", output, documents)

        decision = ledger.commit(
            [{"docid": "a", "reason": "the one distinct retained fact"}],
            max_documents=3,
        )

        first = json.loads(decision.replacements["q1"].splitlines()[0])
        second = json.loads(decision.replacements["q2"].splitlines()[0])
        first_a = next(r for r in first["results"] if r["docid"] == "a")
        second_a = next(r for r in second["results"] if r["docid"] == "a")
        self.assertIn("text", first_a)
        self.assertNotIn("text", second_a)
        self.assertIn(DUPLICATE_PREFIX, second_a["decision"])
        self.assertIn({
            "docid": "a",
            "reason": (
                "duplicate/already committed; repeated occurrence within the "
                "staged batch compacted"
            ),
        }, decision.rejected)

    def test_search_requests_and_records_text_beyond_500_characters(self):
        long_text = "x" * 900

        def full_search(*, query, k, max_chars):
            self.assertIsNone(max_chars)
            return json.dumps({
                "query": query,
                "k": k,
                "results": [{
                    "rank": 1,
                    "id": "long",
                    "docid": "long",
                    "kind": "document",
                    "rrf_score": 1.0,
                    "text": long_text,
                }],
            })

        with patch.object(
                aus_search, "run_search_tool", side_effect=full_search):
            execution = aus_search.execute_full_text_search(
                {"query": "full text"}, default_k=10, seen_docids=set())

        self.assertFalse(execution.failed)
        self.assertEqual(len(execution.documents[0]["text"]), 900)
        self.assertIn(long_text, execution.output)

    def test_search_result_budget_truncates_at_last_line_break(self):
        text = "first line\nsecond line\nthird line is beyond"
        truncated, did_truncate = truncate_result_text(
            text, budget_tokens=4)
        self.assertTrue(did_truncate)
        self.assertEqual(truncated, "first line")

        def long_search(*, query, k, max_chars):
            self.assertIsNone(max_chars)
            return json.dumps({
                "query": query,
                "k": k,
                "results": [{
                    "rank": 1,
                    "id": "long",
                    "docid": "long",
                    "kind": "document",
                    "rrf_score": 1.0,
                    "text": text,
                }],
            })

        with patch.object(
                aus_search, "run_search_tool", side_effect=long_search):
            execution = aus_search.execute_full_text_search(
                {
                    "query": "bounded",
                    "budget_tokens_per_result": 4,
                },
                default_k=10,
                seen_docids=set(),
            )
        payload = json.loads(execution.output)
        self.assertEqual(payload["results"][0]["text"], "first line")
        self.assertTrue(payload["results"][0]["truncated"])
        self.assertEqual(payload["results"][0]["original_chars"], len(text))
        self.assertEqual(payload["results"][0]["returned_chars"], 10)
        self.assertEqual(payload["budget_tokens_per_result"], 4)


class ProviderCompactionTest(unittest.TestCase):
    def _provider(self, *, caching: bool = True) -> BedrockProvider:
        provider = object.__new__(BedrockProvider)
        provider.caching = caching
        provider._messages = []
        provider._settled_count = 0
        return provider

    def _staged(self, call_id: str) -> dict:
        return {
            "role": "user",
            "content": [{"toolResult": {
                "toolUseId": call_id,
                "content": [{"text": f"full staged payload {call_id}"}],
                "status": "success",
            }}],
        }

    def _signed_assistant(self) -> dict:
        return {
            "role": "assistant",
            "content": [{"reasoningContent": {
                "reasoningText": {"text": "", "signature": "signed"}}}],
        }

    def test_bedrock_compaction_rewrites_only_tool_result_messages(self):
        provider = self._provider()
        signed_assistant = self._signed_assistant()
        provider._messages = [signed_assistant, self._staged("s1")]
        replacement = json.dumps({"decision": f"{REJECTION_PREFIX} a"})

        provider.compact_tool_results({"s1": replacement})

        self.assertIs(provider._messages[0], signed_assistant)
        self.assertEqual(
            provider._messages[1]["content"][0]["toolResult"]["content"],
            [{"text": replacement}],
        )

    def test_compaction_settles_every_message_then_in_history(self):
        provider = self._provider()
        provider._messages = [
            {"role": "user", "content": [{"text": "task"}]},
            self._signed_assistant(),
            self._staged("s1"),
            self._signed_assistant(),
        ]
        self.assertEqual(provider._settled_count, 0)

        provider.compact_tool_results({"s1": "compacted"})

        self.assertEqual(provider._settled_count, 4)

    def test_failed_compaction_does_not_settle_history(self):
        provider = self._provider()
        provider._messages = [self._staged("s1")]
        with self.assertRaises(KeyError):
            provider.compact_tool_results({"missing": "x"})
        self.assertEqual(provider._settled_count, 0)

    def test_rolling_cache_point_lands_on_last_settled_user_message(self):
        provider = self._provider()
        provider._messages = [
            {"role": "user", "content": [{"text": "task"}]},
            self._signed_assistant(),
            self._staged("s1"),
            self._signed_assistant(),
        ]
        provider.compact_tool_results({"s1": "compacted"})
        provider._messages.append(self._staged("s2"))  # fresh, still volatile

        provider._place_rolling_cache_point()

        # Anchored on the settled tool-result message (index 2), not the
        # signed assistant that follows it, and not the volatile new batch.
        self.assertEqual(provider._messages[2]["content"][-1],
                         {"cachePoint": {"type": "default"}})
        for index in (0, 1, 3, 4):
            content = provider._messages[index]["content"]
            self.assertFalse(any("cachePoint" in b for b in content),
                             f"unexpected cachePoint on message {index}")

    def test_rolling_cache_point_moves_and_never_duplicates(self):
        provider = self._provider()
        provider._messages = [
            {"role": "user", "content": [{"text": "task"}]},
            self._signed_assistant(),
            self._staged("s1"),
            self._signed_assistant(),
        ]
        provider.compact_tool_results({"s1": "compacted"})
        provider._place_rolling_cache_point()

        provider._messages.append(self._staged("s2"))
        provider._messages.append(self._signed_assistant())
        provider.compact_tool_results({"s2": "compacted"})
        provider._place_rolling_cache_point()

        points = [
            index for index, message in enumerate(provider._messages)
            if any("cachePoint" in b for b in message["content"])
        ]
        self.assertEqual(points, [4])  # moved off msg 2, exactly one remains

    def test_no_cache_point_before_first_compaction(self):
        provider = self._provider()
        provider._messages = [{"role": "user", "content": [{"text": "task"}]}]
        provider._place_rolling_cache_point()
        self.assertEqual(provider._messages[0]["content"], [{"text": "task"}])

    def test_caching_disabled_places_no_cache_points(self):
        provider = self._provider(caching=False)
        provider._messages = [self._staged("s1")]
        provider.compact_tool_results({"s1": "compacted"})
        provider._place_rolling_cache_point()
        content = provider._messages[0]["content"]
        self.assertFalse(any("cachePoint" in b for b in content))


class AgentFlowTest(unittest.TestCase):
    def test_system_prompt_file_loads_with_one_safe_placeholder(self):
        self.assertTrue(agent.SYSTEM_PROMPT_PATH.is_file())
        template = agent.SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
        self.assertEqual(
            template.count(agent.MAX_COMMITTED_PLACEHOLDER), 1)

        prompt = agent.load_system_prompt(4)
        self.assertNotIn(agent.MAX_COMMITTED_PLACEHOLDER, prompt)
        self.assertIn("Commit at most `4` documents", prompt)
        self.assertIn("exactly one sentence per line", prompt)
        self.assertIn("square-bracket markers", prompt)
        self.assertIn("never act as a word in the sentence", prompt)
        self.assertNotIn('{"answer"', prompt)
        for section in (
            "## Scope interpretation",
            "## Internal success plan",
            "## Research workflow",
            "## Staged and committed evidence",
            "## Budget and stopping",
            "## Final response contract",
        ):
            self.assertIn(section, prompt)
        self.assertIn("Do not ask the user clarifying", prompt)
        self.assertIn("Concrete minimum requirements", prompt)
        self.assertIn("Target/excellence requirements", prompt)
        self.assertIn("multiple complementary queries in parallel", prompt)
        self.assertIn("counter-evidence, contradictions", prompt)
        self.assertIn("hard ceiling, not a spending target", prompt)
        self.assertIn("Do not call a tool solely to create another", prompt)
        self.assertIn("500,000 tokens", prompt)
        self.assertNotIn("ClimbMix", prompt)
        self.assertNotIn("get_document", prompt)
        self.assertNotIn("scratchpad", prompt.lower())

    def test_default_current_context_budget_is_500k(self):
        self.assertEqual(agent.DEFAULT_CONTEXT_TOKEN_BUDGET, 500_000)
        self.assertEqual(
            agent._budget_status_line(82_410, 500_000, 252_000),
            "[context budget: 82,410 / 500,000 tokens (16.5%) · "
            "elapsed: 4m 12s]",
        )

    def test_token_usage_separates_context_from_processed_throughput(self):
        stats = agent._usage_token_stats({
            "inputTokens": 100,
            "outputTokens": 10,
            "cacheReadInputTokens": 50,
            "cacheWriteInputTokens": 20,
        })
        self.assertEqual(stats["input"], 170)
        self.assertEqual(stats["processed_input"], 120)
        self.assertEqual(stats["processed"], 130)
        self.assertEqual(stats["total"], 180)

    def test_final_prose_parser_extracts_sentences_and_citations(self):
        sentences, errors, repairs = agent._parse_final_prose(
            "Vaccination reduced hospitalizations by 40% [a], with the "
            "largest effect in older adults. [b]\n"
            "\n"
            "Coverage remained uneven across regions. [a, c]\n"
            "Remaining evidence gaps include cost effectiveness.",
            {"a", "b", "c"},
        )
        self.assertEqual(errors, [])
        self.assertEqual(repairs, [])
        self.assertEqual(sentences, [
            {
                "text": (
                    "Vaccination reduced hospitalizations by 40%, with the "
                    "largest effect in older adults."
                ),
                "citations": ["a", "b"],
            },
            {
                "text": "Coverage remained uneven across regions.",
                "citations": ["a", "c"],
            },
            {
                "text": "Remaining evidence gaps include cost effectiveness.",
                "citations": [],
            },
        ])

    def test_citation_only_line_folds_into_preceding_sentence(self):
        # The format Sonnet 5 actually produces: markers on their own line.
        sentences, errors, repairs = agent._parse_final_prose(
            "That toolbox includes rigid transformations and the Pythagorean "
            "theorem.\n"
            "[a]\n"
            "\n"
            "Competition geometry adds a second toolbox.\n"
            "[b] [c]\n",
            {"a", "b", "c"},
        )
        self.assertEqual(errors, [])
        self.assertEqual([s["citations"] for s in sentences], [["a"], ["b", "c"]])
        self.assertEqual(len(repairs), 2)
        self.assertIn("folded a citation-only line", repairs[0])

    def test_markdown_is_repaired_rather_than_rejected(self):
        sentences, errors, repairs = agent._parse_final_prose(
            "## Findings\n"
            "```\n"
            "- A bullet point survives as a sentence. [a]\n"
            "1. So does a numbered one. [b]\n"
            "> And a quoted one. [c]\n"
            "This has **bold** and *italic* and `code`. [a]\n",
            {"a", "b", "c"},
        )
        self.assertEqual(errors, [])
        self.assertEqual([s["text"] for s in sentences], [
            "A bullet point survives as a sentence.",
            "So does a numbered one.",
            "And a quoted one.",
            "This has bold and italic and code.",
        ])
        self.assertTrue(any("dropped a Markdown heading" in r for r in repairs))
        self.assertTrue(any("code fence" in r for r in repairs))
        self.assertTrue(any("emphasis" in r for r in repairs))

    def test_bad_citations_are_repaired_rather_than_rejected(self):
        sentences, errors, repairs = agent._parse_final_prose(
            "Claim with a hallucinated id. [a] [missing]\n"
            "Overcited claim. [a] [b] [c] [d]\n",
            {"a", "b", "c", "d"},
        )
        self.assertEqual(errors, [])
        self.assertEqual(sentences[0]["citations"], ["a"])
        self.assertEqual(sentences[1]["citations"], ["a", "b", "c"])
        self.assertTrue(any("uncommitted docids missing" in r for r in repairs))
        self.assertTrue(any("beyond the first 3" in r for r in repairs))

    def test_final_prose_parser_rejects_only_unrepairable_reports(self):
        sentences, errors, _ = agent._parse_final_prose("", {"a"})
        self.assertIsNone(sentences)
        self.assertIn("empty", errors[0])

        sentences, errors, _ = agent._parse_final_prose("## Only a heading", {"a"})
        self.assertIsNone(sentences)
        self.assertIn("contains no sentences", errors[0])

        sentences, errors, _ = agent._parse_final_prose(
            "A report that never cites its committed evidence.", {"a"})
        self.assertIsNone(sentences)
        self.assertIn("no sentence carries a citation", errors[0])

        sentences, errors, _ = agent._parse_final_prose(
            " ".join(["word"] * 1025) + " [a]", {"a"})
        self.assertIsNone(sentences)
        self.assertIn("hard maximum is 1024", errors[0])
        self.assertIn("about 950 words", errors[0])

    def test_uncited_report_is_refused_when_nothing_was_committed(self):
        # Regression: a run that committed no evidence must not be allowed to
        # ship a report written from the model's prior knowledge.
        sentences, errors, _ = agent._parse_final_prose(
            "A skater tucking the arms in raises angular velocity.\n"
            "Angular momentum is conserved without external torque.",
            set(),
        )
        self.assertIsNone(sentences)
        self.assertIn("no evidence has been committed", errors[0])

    def test_uncited_report_is_allowed_once_the_budget_is_exhausted(self):
        sentences, errors, _ = agent._parse_final_prose(
            "No committed evidence supports the requested comparison.",
            set(), allow_uncited=True)
        self.assertEqual(errors, [])
        self.assertEqual(sentences[0]["citations"], [])

    def test_final_prose_word_count_excludes_citation_markers(self):
        text = " ".join(["word"] * 1024) + " [a]"
        sentences, errors, _ = agent._parse_final_prose(text, {"a"})
        self.assertEqual(errors, [])
        self.assertEqual(agent._word_count(sentences), 1024)
        self.assertEqual(sentences[0]["citations"], ["a"])

    def _run(self, provider: FakeProvider, **kwargs: object):
        captured: dict[str, object] = {}

        def save_run(system: str, query: str, *, trajectory, output):
            captured.update(
                system=system, query=query, trajectory=trajectory, output=output)
            return {"trajectory": "trajectory.json", "output": "output.json"}

        with (
            patch.object(agent, "make_provider", return_value=provider),
            patch.object(
                aus_search, "run_search_tool", side_effect=_search_output),
            patch.object(agent, "save_run", side_effect=save_run),
        ):
            config = {
                "context_token_budget": 10_000,
                "safety_max_rounds": 20,
                "max_committed_per_step": 3,
                **kwargs,
            }
            summary = agent.run_agent("qid", "research query", **config)
        return summary, captured

    def test_staged_commit_trace_and_strict_trajectory_projection(self):
        provider = FakeProvider([
            _turn(
                text="Search two aspects.",
                calls=[
                    _call("s1", "search", query="alpha"),
                    _call("s2", "search", query="beta"),
                ],
                input_tokens=100,
            ),
            _turn(
                text="Keep the strongest evidence and continue.",
                calls=[
                    _call("c1", "commit_context", documents=[
                        {"docid": "b", "reason": "direct alpha evidence"},
                        {"docid": "d", "reason": "direct beta evidence"},
                    ]),
                    _call("s3", "search", query="gamma"),
                ],
                input_tokens=200,
            ),
            _turn(
                calls=[
                    _call("c2", "commit_context", documents=[
                        {"docid": "g", "reason": "fills final gap"},
                    ]),
                ],
                input_tokens=300,
            ),
            _turn(text="Research is complete.", input_tokens=400),
            _turn(
                text="Supported finding. [b] [g]",
                input_tokens=500,
            ),
        ])

        summary, captured = self._run(provider)
        trajectory = captured["trajectory"]
        trace = trajectory.trace

        self.assertEqual(summary["status"], "completed")
        self.assertEqual(trace["schema_version"], "trec-rag-trace/2")
        self.assertEqual(summary["context_tokens"], 500)
        self.assertEqual(summary["peak_context_tokens"], 500)
        self.assertEqual(summary["committed_documents"], 3)
        self.assertEqual(summary["rejected_documents"], 6)
        self.assertEqual(captured["output"]["references"], ["b", "g"])
        self.assertEqual(trace["summary"]["tokens"]["context_tokens"], 500)
        self.assertEqual(
            trace["summary"]["tokens"]["peak_context_tokens"], 500)
        self.assertEqual(
            trace["summary"]["tokens"]["context_budget_tokens"], 10_000)
        self.assertEqual(trace["summary"]["tokens"]["input"], 1_500)
        self.assertEqual(trace["summary"]["tokens"]["output"], 50)
        self.assertEqual(trace["summary"]["tokens"]["processed"], 1_550)
        self.assertNotIn("ClimbMix", provider.system_prompt)
        self.assertNotIn("get_document", provider.system_prompt)
        self.assertEqual(
            {tool["name"] for tool in provider.tools},
            {"search", "commit_context"},
        )
        user_messages = [
            message["text"] for message in provider.messages
            if message["role"] == "user"
        ]
        self.assertEqual(len(user_messages), 2)
        self.assertIn("Research request:", user_messages[0])
        self.assertIn("did not satisfy", user_messages[1])
        self.assertNotIn("Now write the final", "\n".join(user_messages))
        self.assertFalse(any(
            step["type"] == "output_text" for step in trace["steps"]))
        self.assertEqual(
            trace["output"]["answer"], captured["output"]["answer"])
        self.assertNotIn("raw_messages", trace)
        self.assertNotIn("full staged text", json.dumps(trace))

        # Rich fields exist only on output trace, never trajectory.json.
        forbidden = {
            "t_start", "t_end", "turn", "stats", "documents", "context",
            "duration_ms", "tokens",
        }
        for item in trajectory["result"]:
            self.assertTrue(forbidden.isdisjoint(item))
        search_step = next(
            step for step in trace["steps"]
            if step.get("tool_name") == "search")
        self.assertNotIn("documents", search_step)
        self.assertTrue(all(
            "text" not in result
            for result in search_step["output"]["results"]))
        self.assertEqual(
            trace["steps"][0]["stats"]["cumulative_tokens"]["processed"],
            110,
        )
        first_commit = next(
            step for step in trace["steps"]
            if step.get("tool_call_id") == "c1")
        self.assertEqual(
            first_commit["stats"]["cumulative_tokens"]["processed"],
            320,
        )
        commits = [
            step for step in trace["steps"]
            if step.get("tool_name") == "commit_context"]
        self.assertEqual(commits[0]["context"]["committed"], ["b", "d"])
        self.assertEqual(commits[1]["context"]["committed"], ["g"])
        model_turns = {
            step["turn"] for step in trace["steps"]
            if step["type"] == "generation"
            and "turn" in step
        }
        self.assertTrue({0, 1, 2, 3, 4}.issubset(model_turns))
        self.assertEqual(
            len([step for step in trace["steps"]
                 if step["type"] == "generation"]),
            5,
        )
        generations = {
            step["turn"]: step for step in trace["steps"]
            if step["type"] == "generation"
        }
        for step in trace["steps"]:
            if step["type"] != "tool_call" or "turn" not in step:
                continue
            self.assertEqual(
                step["parent_id"], generations[step["turn"]]["id"])
            if not step.get("arguments", {}).get("automatic"):
                self.assertIsInstance(step.get("tool_call_id"), str)
        self.assertEqual(
            generations[0]["input"],
            {"kind": "initial", "ref": "trace.input"},
        )
        self.assertEqual(
            generations[1]["input"]["kind"], "tool_results")
        self.assertIn("system_prompt", trace["input"])
        self.assertIn("user_message", trace["input"])
        self.assertIn("tools", trace["input"])

        action_steps = [
            step for step in trace["steps"] if step["type"] == "tool_call"]
        for step in action_steps:
            self.assertTrue({
                "context_tokens", "peak_context_tokens",
                "context_budget_tokens", "elapsed_ms",
            }.issubset(step["stats"]))
            self.assertEqual(step["stats"]["context_budget_tokens"], 10_000)
            if isinstance(step["output"], str):
                self.assertRegex(
                    step["output"],
                    r"\n\[context budget: [\d,]+ / 10,000 tokens "
                    r"\(\d+\.\d%\) · elapsed: \d+m \d+s\]$",
                )

        compacted = provider.tool_results["s1"]
        self.assertIn("full staged text for b", compacted)
        self.assertNotIn("full staged text for a", compacted)
        self.assertIn(f"{REJECTION_PREFIX} a", compacted)
        self.assertRegex(
            provider.tool_results["c1"],
            r"\n\[context budget: 200 / 10,000 tokens \(2\.0%\) · "
            r"elapsed: \d+m \d+s\]$",
        )

    def test_context_token_budget_allows_commit_but_blocks_more_retrieval(self):
        provider = FakeProvider([
            _turn(
                text="Start.",
                calls=[_call("s1", "search", query="alpha")],
                input_tokens=100,
            ),
            _turn(
                text="Select and continue.",
                calls=[
                    _call("c1", "commit_context", documents=[
                        {"docid": "b", "reason": "evidence"},
                    ]),
                    _call("s2", "search", query="beta"),
                ],
                input_tokens=160,
            ),
            _turn(
                text="Budgeted finding. [b]",
                input_tokens=100,
            ),
        ])

        summary, captured = self._run(
            provider, context_token_budget=150)
        trajectory = captured["trajectory"]

        self.assertEqual(summary["status"], "budget_exhausted")
        self.assertEqual(trajectory["tool_call_counts"]["search"], 1)
        self.assertEqual(trajectory["tool_call_counts_all"]["search"], 2)
        self.assertEqual(
            trajectory.trace["summary"]["stop_reason"],
            "generation_context_tokens",
        )
        generations = [
            step for step in trajectory.trace["steps"]
            if step["type"] == "generation"
        ]
        self.assertTrue(
            generations[1]["stats"]["context_budget_exhausted"])
        self.assertIn(REJECTION_PREFIX, provider.tool_results["s1"])

    def test_unresolved_staged_batch_expires_after_exactly_one_turn(self):
        provider = FakeProvider([
            _turn(
                text="Retrieve evidence.",
                calls=[_call("s1", "search", query="alpha")],
                input_tokens=100,
            ),
            _turn(
                text="I incorrectly search without committing first.",
                calls=[_call("s2", "search", query="beta")],
                input_tokens=100,
            ),
            # alpha's batch expired and beta was refused, so nothing is
            # retained yet; retrieve again and commit properly.
            _turn(calls=[_call("s3", "search", query="gamma")],
                  input_tokens=100),
            _turn(calls=[_call("c1", "commit_context", documents=[
                {"docid": "g", "reason": "the one retained fact"}])],
                input_tokens=100),
            _turn(text="Supported finding. [g]", input_tokens=100),
        ])

        summary, captured = self._run(provider)
        trajectory = captured["trajectory"]
        self.assertEqual(summary["status"], "completed")
        self.assertEqual(summary["committed_documents"], 1)
        # a, b, c expired unresolved; h, i were staged but not selected.
        self.assertEqual(summary["rejected_documents"], 5)
        self.assertEqual(trajectory["tool_call_counts"]["search"], 2)
        self.assertEqual(trajectory["tool_call_counts_all"]["search"], 3)
        self.assertEqual(
            trajectory["tool_call_counts_all"]["commit_context"], 2)
        self.assertIn(REJECTION_PREFIX, provider.tool_results["s1"])
        self.assertIn("actions refused", provider.tool_results["s2"])

    def test_invalid_commit_expires_batch_instead_of_carrying_it_forward(self):
        provider = FakeProvider([
            _turn(
                text="Retrieve evidence.",
                calls=[_call("s1", "search", query="alpha")],
                input_tokens=100,
            ),
            _turn(
                text="Invalid selection plus another action.",
                calls=[
                    _call("c1", "commit_context", documents=[
                        {"docid": "unknown", "reason": "not actually staged"},
                    ]),
                    _call("s2", "search", query="beta"),
                ],
                input_tokens=100,
            ),
            # The invalid batch expired, so retrieve again and commit validly.
            _turn(calls=[_call("s3", "search", query="gamma")],
                  input_tokens=100),
            _turn(calls=[_call("c2", "commit_context", documents=[
                {"docid": "g", "reason": "the one retained fact"}])],
                input_tokens=100),
            _turn(text="Supported finding. [g]", input_tokens=100),
        ])

        summary, captured = self._run(provider)
        self.assertEqual(summary["status"], "completed")
        self.assertEqual(summary["committed_documents"], 1)
        # a, b, c expired after the invalid commit; h, i were not selected.
        self.assertEqual(summary["rejected_documents"], 5)
        self.assertIn(REJECTION_PREFIX, provider.tool_results["s1"])
        self.assertIn("batch expired", provider.tool_results["s2"])
        commit_steps = [
            step for step in captured["trajectory"].trace["steps"]
            if step.get("tool_name") == "commit_context"
        ]
        self.assertTrue(commit_steps[0]["failed"])
        self.assertEqual(len(commit_steps[0]["context"]["staged"]), 3)
        self.assertEqual(len(commit_steps[0]["context"]["rejected"]), 3)

    def test_valid_final_report_is_accepted_when_staged_batch_expires(self):
        provider = FakeProvider([
            _turn(
                text="Retrieve evidence.",
                calls=[_call("s1", "search", query="alpha")],
                input_tokens=100,
            ),
            _turn(calls=[_call("c1", "commit_context", documents=[
                {"docid": "b", "reason": "direct evidence"}])],
                input_tokens=100),
            # A fresh batch is staged and then left unresolved because the
            # model decides it already has what it needs.
            _turn(calls=[_call("s2", "search", query="gamma")],
                  input_tokens=100),
            _turn(text="Supported finding. [b]", input_tokens=100),
        ])

        summary, captured = self._run(provider)
        self.assertEqual(summary["status"], "completed")
        self.assertEqual(summary["committed_documents"], 1)
        self.assertEqual(captured["output"]["references"], ["b"])
        # The gamma batch expired rather than carrying forward.
        self.assertIn(REJECTION_PREFIX, provider.tool_results["s2"])
        # The expired batch does not cost an extra correction turn.
        user_messages = [
            message["text"] for message in provider.messages
            if message["role"] == "user"
        ]
        self.assertEqual(len(user_messages), 1)

    def test_safety_backstop_stops_commit_without_staged_loop(self):
        provider = FakeProvider([
            _turn(
                calls=[_call(f"c{i}", "commit_context", documents=[])],
                input_tokens=100,
            )
            for i in range(5)
        ])

        summary, captured = self._run(provider, safety_max_rounds=3)
        self.assertEqual(summary["status"], "failed")
        self.assertIn(
            "safety backstop", captured["output"]["answer"][0]["text"])


if __name__ == "__main__":
    unittest.main()
