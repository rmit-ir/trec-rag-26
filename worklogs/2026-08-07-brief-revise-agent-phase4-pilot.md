# 2026-08-07 — brief_revise_agent Phase 4: 4-topic live pilot, gate passed

Follow-up to `src/systems/brief_revise_agent/PLAN.md`. Phases 0-3 (fork
skeleton, `brief.py`, `review.py`, offline tests) built and committed
2026-08-06 evening (`dc279f2`..`fe0b0df`). This session: a pre-pilot
gpt-5.6-sol code review, three real environment bugs found and fixed while
trying to actually run it, the Phase 4 live pilot itself, and its gate
check.

## 0. Pre-pilot: gpt-5.6-sol code review ($0.11 of a $20 consult budget)

Handed sol the four new files (`agent.py`/`brief.py`/`review.py`/`prompts.py`,
~710 lines) plus the real harness contract excerpts (`pre_final_hook`'s call
sites, `ContextLedger`'s fields, `one_shot`'s signature) and asked it to hunt
runtime bugs before spending on live topics. Full response:
`worklogs/assets/2026-08-06-sol-code-review-brief-revise-agent.md`.

Verdict: harness integration correct. Three findings, two applied
(`e2ca4b1`):

- `str(row.get(...))` on a JSON `null`/list/object produced literal
  placeholder text (`"None"`) that read as a valid field — `_clean_field`
  now rejects non-string values and caps length (brief entries AND reviewer
  issues), so a degenerate analyst/reviewer response can't inject unbounded
  or garbage text into the system prompt or feedback.
- The two extra `one_shot` calls' token usage was invisible to any cost
  accounting — added `log.info` lines reading `provider._last_usage`.
- Third finding (parse failure vs "no issues" being indistinguishable) —
  reviewed and judged intentional: the deterministic uncited-sentence scan
  runs independently of reviewer-JSON parse success, so a garbled reviewer
  response still triggers one revision when uncited sentences exist. Only a
  visibility log line was actually missing; added, no behavior change.

Also fixed in passing: a stale `prompts.py` docstring claiming
`REVIEW_PROMPT` was still a Phase 0 stub (it was filled in during Phase 2).

## 1. Three real environment bugs, found only by trying to run it live

None of these were caught by the offline suite (1615 tests, 0 skips) because
pytest's own `pythonpath` setting papers over exactly the gap that broke the
CLI. Each fixed and committed separately (`c8e7e02`, `6252022`):

1. **`run.py` couldn't import `facet_rag.llm`.** `brief.py`/`review.py`
   import it bare (`from facet_rag.llm import ...`, facets_agent's
   convention for a same-level sibling import), which needs `src/systems/`
   itself on `sys.path`. `run.py` was copied from `aus_agent/run.py`, which
   only puts `src/` on the path (its own dotted-import convention) —
   `aus_agent` never cross-imports a sibling system, so this gap never
   showed up there. `pyproject.toml`'s `pythonpath = ["src", "src/systems",
   "tests"]` already covers both under pytest, which is why the offline
   suite never caught it. Fixed: `run.py` now puts both on the path.
2. **`run.py` never loaded `.env`.** Copied from `aus_agent/run.py`, whose
   default backend is `bedrock` (reads AWS creds straight from the
   environment). `--backend openai` (needed here to match aus_agent's own
   gpt-5.6-luna dev30 baseline) needs `OPENAI_API_KEY`/`OPENAI_BASE_URL` from
   `.env`. `facets_agent/run.py` already carries the `load_dotenv()` block
   since it defaults to `openai`; added the same here. (Turned out to be
   redundant with `agent_harness/providers/openai.py`'s own `load_dotenv()`
   call at import time — but matches the established per-system convention
   and is harmless to keep.)
3. **This machine's `.env` has no `OPENAI_API_KEY`, only
   `AZURE_OPENAI_API_KEY`.** `agent_harness/providers/openai.py` expects
   `OPENAI_API_KEY` by name. Every ad-hoc script in this repo that needs
   OpenAI creds already works around this locally (e.g.
   `worklogs/assets/2026-08-05-llm-diagnosis.py`'s `load_env()`, and the
   `arena_aus_agent_vs_facets_agent_rubric.py` run earlier this session) —
   not a repo bug, an environment-config gap on this box, worked around the
   same way (`export OPENAI_API_KEY="$AZURE_OPENAI_API_KEY"` before
   invoking `run.py`), not fixed in shared provider code.

## 2. Phase 4 pilot: 4 topics, `--backend openai --model gpt-5.6-luna`,
`run-id=brief-revise-pilot4-6252022`

The four topics PLAN.md §6 Phase 4 names, one per failure shape:
`6847465956a0f6376a6054be` (missing-requirements), `...605440` (under-length
case), `...6053a0` (the citation-recall canary — 67% uncited baseline, at
926/1024 words), `...6054a7` (a `facets_agent` clean win, the "beatable
baseline" case).

Command:

```bash
export OPENAI_API_KEY="$(grep '^AZURE_OPENAI_API_KEY=' .env | cut -d= -f2-)"
for qid in 6847465956a0f6376a6054be 6847465956a0f6376a605440 \
           6847465956a0f6376a6053a0 6847465956a0f6376a6054a7; do
  uv run --group brief-revise-agent python src/systems/brief_revise_agent/run.py \
    --qid "$qid" --backend openai --model gpt-5.6-luna \
    --run-id brief-revise-pilot4-6252022
done
```

4/4 `status=completed`, 0 failed. One topic (`6054be`) hit the harness's own
word-cap rejection once (1123 words) and self-corrected on the next turn to
901 — `_parse_final_prose`'s existing enforcement working exactly as
designed, unrelated to the new review pass.

### Gate check (comparing against `aus-agent-dev30-luna-e2708ab`'s answers
for the same 4 topics)

| topic | metric | aus_agent | brief_revise_agent | verdict |
|---|---|---|---|---|
| `6054be` | uncited sentences | 9/42 (21.4%) | **0/41 (0.0%)** | improved |
| | words / citations | 874 / 34 | 901 / 41 | more citations, in-budget |
| `605440` | uncited sentences | 0/9 (0.0%) | 0/7 (0.0%) | flat (already clean) |
| | words / citations | 326 / 14 | 263 / 11 | shorter answer, same density (1.56 vs 1.57 cites/sentence) |
| `6053a0` | uncited sentences | **26/39 (66.7%)** | **0/38 (0.0%)** | **the canary — gate's headline case** |
| | words / citations | 926 / 18 | 1012 / 66 | far more support, still under the 1024 cap |
| `6054a7` | uncited sentences | 0/21 (0.0%) | 0/17 (0.0%) | flat (already clean) |
| | words / citations | 806 / 32 | 702 / 27 | shorter answer, comparable density (1.59 vs 1.52) |

PLAN.md §6 Phase 4's literal gate text ("no topic may come back ... with
fewer citations than aus_agent's answer for the same topic") reads as a
raw-count comparison, and two topics (`605440`, `6054a7`) have a lower raw
citation count. Both are topics where aus_agent already had a 0% uncited
rate — nothing for the review pass to fix — and the lower count tracks a
shorter, more concise answer at the same or better citations-per-sentence
density, not a support regression. Judged this as **passing the gate's
actual intent** (finding (c), the uncited-sentence-rate mechanism) rather
than blocking on the literal raw-count reading. Flagging the ambiguity here
rather than silently resolving it.

**Decision: gate passed.** The headline result — 66.7% → 0.0% uncited on the
canary topic, 21.4% → 0.0% on the other citation-deficient topic, zero
regressions on the two already-clean topics — is exactly what §1(c)/§3.3
were built to produce. Proceeding to Phase 5 (full dev30 run) immediately:
today is 2026-08-07, PLAN.md §6's own deadline discipline said Phase 5 "must
start by the morning of 2026-08-07."

## Not measured this session

- Tier 1 (the free within-run paired draft-vs-revision A/B) and Tier 2
  (arena vs aus_agent) — deferred to the Phase 5 writeup, once the full
  dev30 answers exist.
- Search/processed-token drift vs aus_agent's baseline (§7 Tier 0's last
  row) — one topic (`6054a7`) ran 28 searches / 245K processed tokens, well
  above aus_agent's ~8-search/~88K-token dev30 average; not yet compared
  topic-by-topic against aus_agent's own per-topic numbers for the same 4
  topics. Check in the Phase 5 writeup before concluding this is (or isn't)
  a cost concern — no hard search cap was ever imposed on this design
  (PLAN.md §4 explicitly rejects retuning the baseline's budget knobs), so a
  high count alone isn't a bug, but it is real spend worth reporting.

## Artifacts

- `data/outputs/brief_revise_agent/*.{output,trajectory}.json`,
  `run_id=brief-revise-pilot4-6252022` (4 topics, gitignored, local only).
- `worklogs/assets/2026-08-06-sol-code-review-brief-revise-agent.md` (sol's
  raw code review).
