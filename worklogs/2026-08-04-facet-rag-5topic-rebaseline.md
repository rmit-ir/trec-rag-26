# facet_rag 5-topic re-baseline, trace recovery, and a PLAN.md audit

2026-08-04. Three things happened: `PLAN.md`'s factual claims were audited
against disk (a Fable subagent, ~60 claims), the two blockers the plan called
fatal turned out to be resolved, and all 5 comparison topics were run. The most
consequential finding is a **mechanistic error in the plan's own root-cause
story** (§1.1) that would have silently invalidated the next session's
re-baseline.

Raw assets: `worklogs/assets/2026-08-04-facet-rag-5topic/`.

---

## 1. Repo sync (start of session)

`main` was already level with `origin/main` (0 ahead / 0 behind, clean tree, head
`65cf0fa`). Three stale remote-tracking branches pruned (`docs/test-count-947`,
`feat/bm25-tune`, `ragdoll-evaluation` — all deleted upstream).

Two submodules were **uninitialized** (empty dirs) in this clone —
`data/official/trec-rag-2026-data` and `evaluation/ragdoll`. Ran
`git submodule update --init --recursive`; both pins were already at their own
upstream `main` tip, so no bump needed. This mattered: the topics TSV
(`research-rubrics-topics-dev.tsv`) and the ragdoll source that §2.2 cites live
inside those submodules, so nothing in §2 was runnable before this step.

`python scripts/check_vendored_skills.py` — all clean against upstream
`f281e88`: `pyserini-rest-api` v0.3.0, `trec-rag-2026-track-guidelines` v0.6.0,
`trec-rag-climbmix-corpus-creation` v0.1.0. No validator fallout this time.

---

## 2. The blockers in PLAN.md §2.3/§5.5 were stale

The plan states every AWS credential path is expired and "a human must
`aws sso login`". Re-checked:

| check | result |
|---|---|
| `sts.get_caller_identity()` (boto3) | **valid** — `arn:aws:sts::507363615341:assumed-role/AWSReservedSSO_RMIT-ResearchAdmin_…/oleg.zendel@rmit.edu.au` |
| `aws` CLI | not installed (irrelevant — boto3 is what the code uses) |
| `.env` at 18:xx | **absent** — all search engines 401 |
| `.env` at 19:10 | **present** — `SEARCH_API_KEY` + `DENSE_/SPARSE_/PYSERINI_SEARCH_URL` + `SSR_SEARCH_URL` |

Search was genuinely broken until `.env` appeared mid-session; all three
mandatory engines (`loop.py:65` `MANDATORY_ENGINES = ("semantic","keyword","hybrid")`)
went 401 → live hits. Both blockers gone, so §2.3 was executable.

Exact probe used (hits confirmed on all three):

```py
from dotenv import load_dotenv; load_dotenv()
from src.utils.search_dense import search_dense      # + search_sparse, search_pyserini
search_dense('counter strike global offensive history', k=2)
```

Note: hits come back as **dicts** (`['id','docid','kind','score']`), not objects
— an early probe asserting `.docid` failed misleadingly against a working
backend.

---

## 3. facet_rag on all 5 topics

```sh
for q in 6847465956a0f6376a605404 6847465956a0f6376a60542a 683a58c9a7e7fe4e76958498 \
         684397d188c1deceb49af32d 6847465956a0f6376a60547e; do
  uv run --group facet-rag python src/systems/facet_rag/run.py --qid "$q" \
    --run-id facet_rag.opus_plan_5topic \
    --run-desc "facet_rag vs aus_agent: aus_agent's top-5 dev topics, re-baseline"
done
```

All 5 `status=completed`, 5 output + 5 trajectory files in
`data/outputs/facet_rag/`. Full log:
`assets/2026-08-04-facet-rag-5topic/facet_rag_5topic.run.log`.

**Full result matrix** (computed from the `*.output.json`; words =
whitespace-split over `answer[].text`):

```
topic      sents  words  cited%  tot_cits  refs  cits/cited_sent  facets
CSGO          19    365    100%        21    14       1.11          5
SCALING       33    460    100%        39    15       1.18          5
RETIRE        36    734    100%        41    12       1.14          4
PRESCHOOL     31    437     94%        30    14       1.03          5
SWARM         20    363     90%        18    15       1.00          5
```

Searches issued per run, from `trajectory.tool_call_counts`:
CSGO 22, SCALING 15, RETIRE 27, PRESCHOOL 25, SWARM 46 — **135 total**.

Judged by reading against the plan's §0 aims (no metric run — these are
unjudged; see §5):

- **A1 (word budget) confirmed, unfixed.** 363–734 words against a 1024 cap
  (35–72%). RETIRE's 734 is the best any facet_rag run has recorded, still under
  the old 767 max and far from the ≥850 target.
- **A5's headline advantage is eroding.** PRESCHOOL 94% / SWARM 90% are the
  first sub-100%-cited facet_rag answers ever produced; SWARM already violates
  the ≥95% target. Both are the *deliverable-shaped* topics §0's A7 predicts are
  weakest — the prediction landed.
- **A3 has never been met by a surviving run.** 1.00–1.18 vs a ≥1.3 target.
- **SWARM is the sharpest indictment of §3.3.** 46 searches → 363 words;
  aus_agent got 967 words on the same topic from 13 searches.
- **§3.1's "the ref count is mechanical" is too strong.** 12/14/14/15/15 over
  4–5 planned facets: bounded and driven by `facets × DEFAULT_TOP_N` (RETIRE: 4
  facets → 12) but not pinned to it (CSGO: 5 facets → 14).

---

## 4. aus_agent traces: recovered PRESCHOOL + SWARM (3 topics → 5)

The plan's §3 claims its evidence comes from "`tmp/aus-agent-traces/` (15 runs,
5 topics)". The bundle
(`/research/remote/petabyte/users/oleg/aus-agent-traces-3topics.tar.gz`, extracted
to `tmp/`) is **15 runs over 3 topics** — retirement 10, CS:GO 3, scaling 2.
PRESCHOOL (`684397d188c1deceb49af32d`) and SWARM
(`6847465956a0f6376a60547e`) had **no trajectories at all**, while §0's A7/A8
quote their answer text. Those quotes were fine — the text is in
`evaluation-results/aus-agent/answers.resolved.jsonl` — but the provenance line
conflated two sources.

Both topics were recoverable from the git object store, the same way the original
three were: `data/outputs/` was untracked in `fe171d3` **and** matched
`.gitattributes:1` (`data/outputs/**/*.json filter=lfs`), so recent commits hold
131-byte LFS pointers while the **pre-LFS plaintext blobs** remain reachable.

Method (scripts in assets, reproducible):

1. `recover_scan.py` — `git rev-list --all --objects -- data/outputs/aus_agent`
   → 1,256 unique blobs; `git cat-file --batch-check` filtered to **728** >5 KB
   (real content, not pointers).
2. `find_topics.py` — filenames are **slug**-based
   (`…i_am_a_pre_school.*`, `…i_m_trying_to_scope.*`), *not* qid-based, so each
   blob's content was scanned for the `narrative_id`. 10 matches = 5 runs × 2
   artifacts. Blob shas recorded in `topic_hits.json`.
3. `extract_2topics.py` — wrote them under the existing directory convention and
   merged 10 entries into `manifest.json` (30 → 40).

Recovered runs (verified against `tool_call_counts` + `references`):

| topic | run_id | tool calls | docids | refs |
|---|---|---|---|---|
| PRESCHOOL | aus-agent-dev-full | 9 | 60 | 15 |
| PRESCHOOL | aus-agent-creative-check | 7 | 50 | 6 |
| PRESCHOOL | aus-agent-sat-go | 10 | 64 | 12 |
| SWARM | aus-agent-dev-full | 16 | 130 | 17 |
| SWARM | aus-agent-sat-go | 12 | 79 | 17 |

`tmp/aus-agent-traces/README.md` updated to 5 topics / 20 runs with the recovery
method. Two gotchas recorded there: the "tool calls" column is
`sum(tool_call_counts)` (the manifest sums search+commit — easy to double-count),
and SWARM's `20260717T010209745002+1000` is the **only** run where
`tool_call_counts_all` (17) ≠ `tool_call_counts` (16).

---

## 5. PLAN.md audit — what was wrong

A Fable subagent verified ~60 checkable claims (every `file.py:NN` citation,
artifact path, runnable command, and metric). **All code line-numbers, spec
citations, and aus_agent metrics were correct** — every UMBRELA per-topic mean
and n reproduced exactly, as did the support figures and the whole appendix
answer-shape table. Three real defects:

### 5.1 §1.1's root cause was mechanistically wrong (the important one)

The plan blamed the segment-length confound on two fetch endpoints
(`--api-base-url` vs `--doc-url`). The resolver's **primary** path is neither: it
resolves from local `*.trajectory.json` first
(`scripts/resolve-rag-output-references.py:269-271`), APIs are fallbacks only for
unresolved docids. Independently confirmed by reading the script — and note
`trajectory_texts(path, args.trajectory_dir)` with `trajectory_dir or
output_path.parent` (line 107), so trajectories sitting *beside* the outputs are
picked up automatically.

Consequences, verified by Fable:

- aus_agent's judged segments **byte-match its trajectory-staged texts, 77/77**
  across all 5 dev-full topics. Its "full documents" came from its search tool's
  4,096-token staging budget (`aus_agent/tools/search.py:10-11`), **not** from
  `--doc-url`.
- Re-running §2.1 exactly as written would resolve every docid from 2,000-char
  trajectory text and **reproduce the exact confound the plan exists to
  eliminate** — then report a "re-established" baseline. Measured on the fresh
  runs: 70/70 refs resolved from trajectories, median exactly 2,000, 56/70
  pinned at the cap.
- Pyserini's full doc for `shard_04677_48238` is 3,632 chars, matching
  aus_agent's staged text — confirming the other half of the story.

Fix now in §2.1: `--trajectory-dir /tmp/no-trajectories` to force the
full-document fallback.

### 5.2 The data loss was worse than the plan admits

§1.2 said `data/outputs/facet_rag/` was empty but the derived
`evaluation-results/facet_rag/*/answers.resolved.jsonl` survived. They did not:
the whole `evaluation-results/facet_rag/` tree is absent from the clone **and
from every commit tree in git history**, including unreachable/stash commits
(checked via `git ls-tree` over `rev-list --all` plus `git fsck`). Not
recoverable as blobs, unlike the aus_agent traces. So §0's "current facet_rag"
column, the appendix 20-run table, the 1.429→0.875 variance claim, and
"analyzer rubber-stamps ~76%" are **historical and unreproducible** — marked as
such rather than deleted, since the aus_agent half of every parallel claim did
reproduce.

### 5.3 Two smaller corrections

- §1.1's aus_agent median range was **3,338–3,971**, not 3,741–3,971 (CSGO 3,494
  and SWARM 3,338 were omitted; the appendix had it right).
- §6.2's "facet_rag has no run-level timing anywhere" is wrong —
  `trace.duration_ms` exists (`run_one` passes `started_at`/`ended_at`; fresh
  CSGO run = 92.6 s). The real gap is **per-stage** timing: only 4 of 47 steps
  carry `stats.duration_ms`, because replayed loop events never set
  `t_start`/`t_end`.

Also measured, superseding §2.4/§4-item-1.6's "0/39": Boolean engine selection is
**3 lucene_bool / 135 calls (2.2%), ssr 0** — direction confirmed, but not
literally zero, so the deletion criterion was sharpened to "check whether those
3 calls contributed kept evidence first".

`PLAN.md` edits: 14 changes, +183/−68, structure and voice preserved; corrections
are dated and additive rather than overwriting the original text.

---

## 6. Off-repo archive

`/research/remote/petabyte/users/oleg/trec_rag_26_data/` — 522 MB:
`facet_rag-runs/` (the 5 runs), `aus-agent-traces/` (5 topics / 20 runs),
`evaluation-results/`, `logs/` (recovery scripts + blob shas), plus a README
documenting provenance and the caveat that no `facet_rag/` eval dir exists.
All three copies verified byte-identical to the working tree (`diff -rq`).

This exists because `data/outputs/` is untracked + LFS'd, so run artifacts do not
survive a clone — the mechanism that lost the last session's work. It protects
**completed** runs only; a mid-run crash still loses everything, so §6.3's
partial-save item stands.

---

## 7. Next session

§2.1 → §2.2 are now immediately executable: real inputs on disk, credentials
live, and the trajectory-first trap disarmed. Two cautions:

1. **Use `--trajectory-dir <empty>`** or the re-baseline is confounded again
   (§5.1). Sanity check: median segment must be ~3,500–4,000, not 2,000.
2. **Single trials still aren't evidence.** §1.2's noise band (the same topic
   scored 1.429 then 0.875 under identical code) is unresolved — 3 trials/topic
   before trusting any delta. Everything in §3 remains keyed to that.

Session tokens expire; re-check `sts get-caller-identity` at session start.
