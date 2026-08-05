# facet_rag §3.2/§3.4/§3.5 fixes, full-eval verification, and a §3.3 HyDE change

2026-08-05, continuing the same day's work (see
`2026-08-05-facet-rag-honest-rebaseline.md`,
`2026-08-05-facet-rag-maxchars-verification.md`,
`2026-08-05-facet-rag-top5floor-and-cost-timing.md`). User asked to pick
concrete PLAN.md §3 items and run the "full evaluation" on the same 5
dev-topic set used all session — first confirmed that set (CSGO/SCALING/
RETIRE/PRESCHOOL/SWARM) really is aus_agent's top-5 by UMBRELA out of all 29
judged dev topics (means 2.083 down to 1.294; 6th place is 1.200 — a real
gap), so no topic-selection change was needed.

## Part 1: §3.2/§3.4/§3.5 (commit `5c122c7`)

### §3.2 — analyzer note quality

`ANALYZER_PROMPT` (`prompts.py`) rewritten to demand the specific facts a
passage contributes (numbers/dates/names) and its role (support /
counter-argument / example / background), and to explicitly ask for
counter-evidence — matching aus_agent's `commit_context` reasons this
section's own diagnosis quoted. Same call, same schema, no cost.

### §3.4 — formatter never saw evidence text (root cause of a real failure)

`format_answer()` (`ali_deepresearch/answer_format.py`) gained an optional
`evidence_text: dict[str, str] | None` param. When given, each ALLOWED DOCIDS
entry becomes `{"docid": ..., "excerpt": "<800 chars>"}` instead of a bare
string, so the model can verify a citation against real text instead of
matching an opaque id blind. `EXCERPT_CHARS = 800` truncates deliberately —
this call only needs enough to check one fact, not facet_rag's full (now
20 000-char) passage. `ali_deepresearch`/`o3_deep_research` don't pass
`evidence_text` (they don't keep per-docid text at their call site), so their
prompt shape is byte-identical to before — verified by
`test_format_answer_llm_without_evidence_text_is_unchanged`.

facet_rag's `pipeline.py` now builds `evidence_text = {e["docid"]: e["text"]
for e in evidence}` and passes it through.

### §3.5 — the uncited-sentence spec violation

`FORMAT_ANSWER_PROMPT` no longer says "zero citations is valid and correct"
for a sentence nothing supports. It now says: delete such a sentence (an
uncited factual claim is pure loss under `rag-task.md:131` — excluded from
precision scoring, scores 0 for recall) — except a sentence that asserts
nothing about the world (a pure transition/framing clause), which may still
stay uncited since there's nothing in it to verify. Shared file — full
`scripts/test.sh` run, not just facet_rag's tests.

### Tests

`tests/shared/test_pricing.py` already existed from the prior session's §6.1
work; this round added 3 tests to `tests/systems/test_ali_deepresearch.py`
(`_render_allowed_docids`'s three branches: with evidence text, truncation,
without evidence text unchanged) and fixed 2 existing test helpers
(`tests/systems/test_facet_rag.py::_format_text`,
`tests/dummy_api/test_dummy_api.py`'s orchestrator responder) that parsed
`ALLOWED DOCIDS:` assuming a flat string list — now handle both shapes.
Full suite: 1548 passed (was 1545), 0 skipped.

## Part 2: full evaluation — `facet_rag.improved_5topic`

```sh
for q in 6847465956a0f6376a605404 6847465956a0f6376a60542a 683a58c9a7e7fe4e76958498 \
         684397d188c1deceb49af32d 6847465956a0f6376a60547e; do
  uv run --group facet-rag python src/systems/facet_rag/run.py --qid "$q" \
    --run-id facet_rag.improved_5topic \
    --run-desc "PLAN.md §3.2/§3.4/§3.5: analyzer notes, formatter evidence text, uncited-sentence fix"
done
```

All 5 `status=completed` — **no `no_references` failures this time** (the
prior `top5floor_5topic` run had one on SCALING). Resolved through
`--doc-url` with an empty `--trajectory-dir` (median segment length 4016
chars, 0 pinned at 2000 — confound-free), then UMBRELA (83 candidates) and
support (144 citations) judged the same way as every prior run this session.

### Result matrix (vs. the immediately-prior `top5floor_5topic` variant)

```
topic       words(t5+floor->improved)  cited%       UMBRELA mean          support p_o_f
CSGO           571 -> 264              86% -> 100%   1.650 -> 1.917        0.923 -> 0.846
SCALING        987 -> 354              73% -> 95%    1.300 -> 1.105        0.759 -> 0.929
RETIRE         733 -> 529              97% -> 100%   1.579 -> 1.500        1.000 -> 0.854
PRESCHOOL      722 -> 406             100% -> 100%   0.762 -> 0.812        0.807 -> 0.833
SWARM          539 -> 640             100% -> 100%   1.087 -> 1.000        0.783 -> 0.935
mean words     710.4 -> 438.6
```

aus_agent-dev-full UMBRELA for reference: CSGO 2.083, SCALING 1.667, RETIRE
1.583, PRESCHOOL 1.467, SWARM 1.294.

Aggregate support: `total=144, full_support=64, partial_support=63,
no_support=12, judge_errors=5, full_support_rate=0.444444,
partial_or_full_rate=0.881944` (up from `top5floor_5topic`'s 0.408/0.841).

### Verdict: §3.5 fixed exactly what it targeted, and cost exactly what §3.1 just bought

Citation coverage recovered precisely as designed: CSGO 86%→100%, SCALING
73%→95% — both back at or above the ≥95% target. Support `partial_or_full`
improved on 3/5 topics (aggregate 0.841→0.882). CSGO's UMBRELA (1.917) is the
closest facet_rag has come to aus_agent (2.083) on any topic, any variant,
all session.

But mean words dropped 710.4→438.6 — **worse than the very first
`opus_plan_5topic` baseline (471.8)**, undoing essentially all of the prior
session's `DEFAULT_TOP_N`/formatter-floor gain. Mechanism: §3.5's rule
deletes a sentence the formatter can't verify support for; §3.4 made the
formatter more able to *verify* (good for precision) but also, apparently,
more willing to *delete* once it actually checks (bad for volume) — the two
fixes landed in the same session and their interaction wasn't measured
separately. A1 (word budget) and A5 (citation coverage) are not independent
knobs: they trade against each other through the same mechanism, how many
unverifiable sentences survive the formatter. §5's precision-vs-recall
question is now demonstrated with real numbers on both sides, not resolved by
either side unilaterally.

**Bonus data point (§6.1 cost tracking, first time used on a full 5-topic
run):** total cost across all 5 topics was **$0.34**, every model call
(166 calls total) priced, no unknowns.

## Part 3: §3.3 HyDE-for-hybrid (commit pending at time of writing — see git log)

Separate from the plan's own §3.3 diagnosis (which recommends replacing "one
question × 3 mandatory engines" with "N distinct sub-questions, engine of
your choice" — still open), the user asked for a narrower, specific change:
make the hybrid engine's query a HyDE (hypothetical-document-embedding)
hypothetical answer instead of a short search phrase, with a wider retrieval
net to match, and make sure the model always writes a confident hypothetical
answer rather than hedging when unsure.

Implemented:
- `loop.py`: `HYBRID_K = 15` (vs `DEFAULT_K = 10` for semantic/keyword);
  the per-engine search call now does `k = HYBRID_K if engine == "hybrid"
  else DEFAULT_K`.
- `prompts.py` (`ORCHESTRATOR_QUERY_PROMPT`): the hybrid line no longer
  routes through the generic engine blurb. It now reads: "write a
  HYPOTHETICAL ANSWER, not a search-style query — a short, confident passage
  (2-4 sentences) that WOULD answer this facet's need, as if it were an
  excerpt from a real ClimbMix document... ALWAYS write a complete
  hypothetical answer, even if you are not certain of the specific facts,
  dates, or numbers — invent plausible-sounding specifics rather than
  hedging, staying generic, or declining; this text is never shown to anyone
  and only used to find real matching documents, so a confident wrong guess
  retrieves better than a vague true one."
- Removed the now-unused `hybrid_blurb` kwarg from the `.format()` call.

New test: `test_run_one_hybrid_engine_retrieves_more_than_the_others`
(`tests/systems/test_facet_rag.py`) — asserts `calls["hybrid"][0]["k"] == 15`
against `calls["semantic"/"keyword"][0]["k"] == 10`. Full suite: 1549 passed.

**Not yet measured** — this was implemented and tested but a fresh 5-topic
run + judge to see its effect wasn't run this session (time/budget). Next
session should run it the same way as every other §3.x change here and
compare against `improved_5topic` as the new baseline.

## Artifacts

- `evaluation-results/facet_rag/improved_5topic/` (resolved answers, UMBRELA
  and support judgments)
- Code: `src/systems/facet_rag/prompts.py`, `pipeline.py`, `loop.py`;
  `src/systems/ali_deepresearch/answer_format.py`, `prompts.py`
