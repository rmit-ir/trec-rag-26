from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests.injection import inject_titles_keywords as MODULE


class InjectTitlesKeywordsTests(unittest.TestCase):
    def test_injected_text_format(self):
        self.assertEqual(
            MODULE.injected_text(
                "Competition Geometry",
                ["AIME", "Ceva theorem"],
                "Original answer.",
            ),
            "Title: Competition Geometry\n"
            "Keywords: AIME, Ceva theorem\n\n"
            "Original answer.",
        )

    def test_build_rows_preserves_resolved_data_and_updates_length(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "answers.jsonl"
            path.write_text(json.dumps({
                "qid": "q1",
                "query": "Explain geometry",
                "answer_text": "Original answer.",
                "response_length": 2,
                "segments": {"doc1": "Evidence"},
            }) + "\n", encoding="utf-8")
            rows = MODULE.build_rows(
                path,
                {"Explain geometry": "Geometry Title"},
                {"Explain geometry": ["geometry", "theorems"]},
            )
            self.assertEqual(rows[0]["segments"], {"doc1": "Evidence"})
            self.assertEqual(
                rows[0]["answer_text"],
                "Title: Geometry Title\n"
                "Keywords: geometry, theorems\n\n"
                "Original answer.",
            )
            self.assertEqual(
                rows[0]["answer"],
                [{
                    "text": (
                        "Title: Geometry Title\n"
                        "Keywords: geometry, theorems\n\n"
                        "Original answer."
                    ),
                    "citations": [],
                }],
            )
            self.assertEqual(
                rows[0]["response_length"],
                len(rows[0]["answer_text"].split()),
            )

    def test_missing_title_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "answers.jsonl"
            path.write_text(json.dumps({
                "qid": "q1",
                "query": "query",
                "answer_text": "answer",
            }) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "no generated title"):
                MODULE.build_rows(path, {}, {"query": ["keyword"]})


if __name__ == "__main__":
    unittest.main()
