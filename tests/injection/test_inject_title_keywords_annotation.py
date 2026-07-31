from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests.injection import inject_title_keywords_annotation as MODULE


class InjectTitleKeywordsAnnotationTests(unittest.TestCase):
    def test_append_annotation(self):
        self.assertEqual(
            MODULE.append_annotation("Original answer.", "experiment-2"),
            "Original answer.\n\nAdditional text: experiment-2",
        )

    def test_injection_text_variable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "answers.jsonl"
            path.write_text(
                json.dumps({"answer_text": "Original answer."}) + "\n",
                encoding="utf-8",
            )
            row = MODULE.build_rows(path)[0]
            self.assertEqual(
                row["answer_text"],
                "Original answer.\n\nAdditional text: Like this",
            )

    def test_build_rows_updates_both_answer_representations(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "answers.jsonl"
            path.write_text(
                json.dumps({
                    "qid": "q1",
                    "query": "query",
                    "answer_text": "Title: Example\nKeywords: one\n\nAnswer.",
                    "answer": [{"text": "stale"}],
                    "injection": {"kind": "title_keywords"},
                }) + "\n",
                encoding="utf-8",
            )
            row = MODULE.build_rows(path)[0]
            self.assertTrue(
                row["answer_text"].endswith(
                    "\n\nAdditional text: Like this"
                )
            )
            self.assertEqual(row["answer"][0]["text"], row["answer_text"])
            self.assertEqual(
                row["injection"]["prior"], {"kind": "title_keywords"}
            )


if __name__ == "__main__":
    unittest.main()
