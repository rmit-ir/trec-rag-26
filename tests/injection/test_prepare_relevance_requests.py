from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests.injection import prepare_relevance_requests as MODULE


class PrepareRelevanceRequestsTests(unittest.TestCase):
    def test_answer_text_becomes_the_candidate_passage(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "answers.injected.jsonl"
            source.write_text(json.dumps({
                "run_id": "run-a",
                "qid": "q1",
                "query": "Original query",
                "answer_text": "Title: Generated\nKeywords: one\n\nAnswer.",
            }) + "\n", encoding="utf-8")
            rows = MODULE.build_requests(source)
            self.assertEqual(rows[0]["task_id"], "run-a::q1")
            self.assertEqual(
                rows[0]["query"],
                {"qid": "run-a::q1", "text": "Original query"},
            )
            self.assertEqual(
                rows[0]["candidates"][0]["doc"]["segment"],
                "Title: Generated\nKeywords: one\n\nAnswer.",
            )
            self.assertEqual(
                rows[0]["candidates"][0]["doc"]["docid"],
                "injected-answer",
            )


if __name__ == "__main__":
    unittest.main()
