from __future__ import annotations

import unittest

from tests.injection import generate_keywords as MODULE


class GenerateKeywordsTests(unittest.TestCase):
    def test_parse_keywords_deduplicates_case_insensitively(self):
        self.assertEqual(
            MODULE.parse_keywords(
                '```json\n{"keywords":["AIME","aime","Ceva theorem"]}\n```'),
            ["AIME", "Ceva theorem"],
        )

    def test_generate_keywords_uses_expected_converse_shape(self):
        class FakeClient:
            def converse(self, **kwargs):
                self.kwargs = kwargs
                return {"output": {"message": {"content": [
                    {"text": '{"keywords":["geometry","AIME"]}'}
                ]}}}

        client = FakeClient()
        self.assertEqual(
            MODULE.generate_keywords(
                client, "Explain geometry", MODULE.DEFAULT_MODEL),
            ["geometry", "AIME"],
        )
        self.assertEqual(client.kwargs["modelId"], MODULE.DEFAULT_MODEL)
        self.assertEqual(
            client.kwargs["messages"][0]["content"][0]["text"],
            "Explain geometry",
        )
        self.assertEqual(
            client.kwargs["inferenceConfig"]["maxTokens"], 1024)
        self.assertEqual(
            client.kwargs["additionalModelRequestFields"],
            {"reasoning_effort": "low"},
        )

    def test_generate_keywords_retries_contentless_response(self):
        class FakeClient:
            def __init__(self):
                self.budgets = []

            def converse(self, **kwargs):
                self.budgets.append(kwargs["inferenceConfig"]["maxTokens"])
                if len(self.budgets) == 1:
                    return {"output": {"message": {"content": []}}}
                return {"output": {"message": {"content": [
                    {"text": '{"keywords":["retrieval"]}'}
                ]}}}

        client = FakeClient()
        self.assertEqual(
            MODULE.generate_keywords(client, "query", MODULE.DEFAULT_MODEL),
            ["retrieval"],
        )
        self.assertEqual(client.budgets, [1024, 2048])

    def test_invalid_json_is_fatal(self):
        with self.assertRaises(RuntimeError):
            MODULE.parse_keywords("not json")

    def test_generate_keywords_retries_malformed_json(self):
        class FakeClient:
            def __init__(self):
                self.budgets = []

            def converse(self, **kwargs):
                self.budgets.append(kwargs["inferenceConfig"]["maxTokens"])
                text = (
                    '{"keywords":["truncated"'
                    if len(self.budgets) == 1
                    else '{"keywords":["complete"]}'
                )
                return {"output": {"message": {"content": [{"text": text}]}}}

        client = FakeClient()
        self.assertEqual(
            MODULE.generate_keywords(client, "query", MODULE.DEFAULT_MODEL),
            ["complete"],
        )
        self.assertEqual(client.budgets, [1024, 2048])


if __name__ == "__main__":
    unittest.main()
