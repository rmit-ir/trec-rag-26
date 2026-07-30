"""Probe: does RAGDoll's support scoring match arXiv:2504.15205 §3.4?

Run from the submodule so the `ragdoll` package resolves:

    cd evaluation/ragdoll && uv run python ../../worklogs/assets/2026-07-30-support-metric-paper-probe.py

Recorded output (2026-07-30, ragdoll @ 1f06719):

    weighted_precision_first_citation: 0.75 (paper: 0.75)
    weighted_recall_first_citation:    0.5 (paper: 0.5)
    hard_precision: 0.5 hard_recall: 0.3333333333333333
    all-cited -> P == R: 0.75 0.75
    with one unjudged: 1.0 1.0 sentences= 2
    multi-cite all_judged P: 0.5 first-cite P: 1.0
"""

from ragdoll.support.metrics import support_metric

# Paper §3.4 worked example: p1 partially supports a1, p2 fully supports a2,
# a3 has zero citations. Paper states precision 0.75, recall 0.5.
row = {
    "topic_id": "t1",
    "run_id": "r1",
    "sentences": [
        {"text": "a1", "citations": [{"support": 1}]},  # PS -> 0.5
        {"text": "a2", "citations": [{"support": 2}]},  # FS -> 1.0
        {"text": "a3", "citations": []},  # zero citations
    ],
}
m = support_metric(row)
print("weighted_precision_first_citation:", m.weighted_precision_first_citation, "(paper: 0.75)")
print("weighted_recall_first_citation:   ", m.weighted_recall_first_citation, "(paper: 0.5)")
print("hard_precision:", m.hard_precision, "hard_recall:", m.hard_recall)

# §3.4 claim: under first-citation-only judging, P and R are identical when
# every answer sentence carries at least one citation.
row2 = {
    "topic_id": "t",
    "run_id": "r",
    "sentences": [
        {"text": "a1", "citations": [{"support": 1}]},
        {"text": "a2", "citations": [{"support": 2}]},
    ],
}
m2 = support_metric(row2)
print("all-cited -> P == R:", m2.weighted_precision_first_citation, m2.weighted_recall_first_citation)

# RAGDoll extension (not a paper label): -1 marks an unjudged citation. Expect
# the sentence to leave BOTH denominators rather than score 0 like a true NS.
row3 = {
    "topic_id": "t",
    "run_id": "r",
    "sentences": [
        {"text": "a1", "citations": [{"support": -1}]},
        {"text": "a2", "citations": [{"support": 2}]},
    ],
}
m3 = support_metric(row3)
print(
    "with one unjudged:",
    m3.weighted_precision_first_citation,
    m3.weighted_recall_first_citation,
    "sentences=",
    m3.sentences,
)

# RAGDoll extension: the all-judged-citations numerator is the MEAN over a
# sentence's judged citations, so [FS, NS] -> 0.5 rather than 1.0.
row4 = {
    "topic_id": "t",
    "run_id": "r",
    "sentences": [{"text": "a1", "citations": [{"support": 2}, {"support": 0}]}],
}
m4 = support_metric(row4)
print(
    "multi-cite all_judged P:",
    m4.weighted_precision_all_judged_citations,
    "first-cite P:",
    m4.weighted_precision_first_citation,
)
