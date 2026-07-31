from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("generate_titles.py")
SPEC = importlib.util.spec_from_file_location("generate_titles", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class GenerateTitlesTests(unittest.TestCase):
    def test_unique_queries_preserve_order_and_collect_qids(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "answers.jsonl"
            source.write_text(
                "\n".join([
                    json.dumps({"qid": "q1", "query": "Same query"}),
                    json.dumps({"qid": "q2", "query": "Other query"}),
                    json.dumps({"qid": "q3", "query": "Same query"}),
                ]) + "\n",
                encoding="utf-8",
            )
            self.assertEqual(MODULE.unique_queries(source), [
                {"query": "Same query", "qids": ["q1", "q3"]},
                {"query": "Other query", "qids": ["q2"]},
            ])

    def test_extract_title_removes_label_and_quotes(self):
        response = {
            "output": {"message": {"content": [
                {"text": 'Title: "Competition Geometry Beyond the Classroom"'}
            ]}}
        }
        self.assertEqual(
            MODULE.extract_title(response),
            "Competition Geometry Beyond the Classroom",
        )

    def test_generate_title_uses_expected_converse_shape(self):
        class FakeClient:
            def converse(self, **kwargs):
                self.kwargs = kwargs
                return {"output": {"message": {"content": [
                    {"text": "A Useful Title"}
                ]}}}

        client = FakeClient()
        title = MODULE.generate_title(
            client, "Explain the topic", "openai.gpt-oss-20b-1:0")
        self.assertEqual(title, "A Useful Title")
        self.assertEqual(
            client.kwargs["modelId"], "openai.gpt-oss-20b-1:0")
        self.assertEqual(
            client.kwargs["messages"][0]["content"][0]["text"],
            "Explain the topic",
        )
        self.assertEqual(client.kwargs["inferenceConfig"]["maxTokens"], 512)

    def test_generate_title_retries_contentless_response(self):
        class FakeClient:
            def __init__(self):
                self.budgets = []

            def converse(self, **kwargs):
                self.budgets.append(kwargs["inferenceConfig"]["maxTokens"])
                if len(self.budgets) == 1:
                    return {
                        "stopReason": "max_tokens",
                        "output": {"message": {"content": []}},
                    }
                return {"output": {"message": {"content": [
                    {"text": "Title After Reasoning"}
                ]}}}

        client = FakeClient()
        self.assertEqual(
            MODULE.generate_title(client, "query", MODULE.DEFAULT_MODEL),
            "Title After Reasoning",
        )
        self.assertEqual(client.budgets, [512, 1024])


if __name__ == "__main__":
    unittest.main()
