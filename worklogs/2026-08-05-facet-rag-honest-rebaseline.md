# facet_rag honest re-baseline (§2.1/§2.2/§2.3 of PLAN.md)

2026-08-05. Executed the blocking measurement steps in
`src/systems/facet_rag/PLAN.md` §2. No code changes this session — pure
measurement.

## 1. Input recovery

`data/outputs/facet_rag/` was empty on this machine (the `opus_plan_5topic`
run from the prior session never made it into this clone) and the off-repo
archive path the plan cites, `/research/remote/petabyte/users/oleg/trec_rag_26_data/`,
does not mount here. User pointed to a local mirror instead:
`/Users/e103037/Downloads/trec_rag_26_data/facet_rag-runs/` — 5 output.json +
5 trajectory.json pairs, timestamp-named
(`20260805T09{12,14,17,20,24}...+1000.<slug>.{output,trajectory}.json`), all
`metadata.run_id == "facet_rag.opus_plan_5topic"`, all `trace.status ==
"completed"`, covering all 5 narrative_ids:

- `6847465956a0f6376a605404` — CSGO feature essay
- `6847465956a0f6376a60542a` — scaling to 1M users
- `683a58c9a7e7fe4e76958498` — retirement blog series
- `684397d188c1deceb49af32d` — pre-school teacher strategy
- `6847465956a0f6376a60547e` — decentralized swarm proposal

Copied verbatim into `data/outputs/facet_rag/` (gitignored, `data/*` in
`.gitignore:61` — stays local, as intended).

## 2. §2.1 — resolve through full documents, defeating the trajectory-first path

```sh
mkdir -p /tmp/no-trajectories evaluation-results/facet_rag/opus_plan_5topic
uv run --no-project --with python-dotenv python scripts/resolve-rag-output-references.py \
    data/outputs/facet_rag/ \
    --trajectory-dir /tmp/no-trajectories \
    --ragdoll-output evaluation-results/facet_rag/opus_plan_5topic/answers.resolved.jsonl
```

Output: `resolved 0/70 from local trajectories` → `API fallback resolved
70/70` → `wrote 5 RAGDoll answer rows with 70 unique references`.

Sanity check (plan's stated bar: median should be ~3,500-4,000, not 2,000):

```
n=70, median=3987.5, mean=9694.14, pinned at 2000: 0
```

Confound confirmed gone — every prior facet_rag resolve (curator_full and the
first `opus_plan_5topic` attempt last session) had median exactly 2,000 with
the majority pinned at the cap.

## 3. §2.1 cont'd — UMBRELA judge

```sh
python3 scripts/ragdoll-answers-to-umbrela.py \
    evaluation-results/facet_rag/opus_plan_5topic/answers.resolved.jsonl \
    --output evaluation-results/facet_rag/opus_plan_5topic/umbrela.input.jsonl
# wrote 5 queries and 70 cited candidates

cd evaluation/ragdoll && uv run ragdoll umbrela judge \
    --provider amazon-bedrock --model openai.gpt-oss-120b-1:0 \
    --input-file ../../evaluation-results/facet_rag/opus_plan_5topic/umbrela.input.jsonl \
    --output-file ../../evaluation-results/facet_rag/opus_plan_5topic/umbrela-bedrock-120/judgments.jsonl
# processed=70
```

Per-topic mean UMBRELA judgment (0-3 scale), computed from
`judgments.jsonl`'s `judgment` field grouped by `qid`:

| topic | n | mean | aus_agent (`aus-agent-dev-full`) mean (n) |
|---|---|---|---|
| CSGO feature essay | 14 | 1.643 | 2.083 (12) |
| scaling to 1M users | 15 | 1.067 | 1.667 (21) |
| retirement blog series | 12 | 1.417 | 1.583 (12) |
| pre-school teacher strategy | 14 | 0.857 | 1.467 (15) |
| decentralized swarm proposal | 15 | 1.200 | 1.294 (17) |

facet_rag trails aus_agent on every topic even with the confound removed. Gap
is small on RETIRE (-0.17) and SWARM (-0.09), large on SCALING (-0.60) and
PRESCHOOL (-0.61, the biggest gap of the 5 — the deliverable-shaped topic
§0/A7 predicted would be weakest).

## 4. §2.2 — support judge (the metric that actually scores the submission)

```sh
cd evaluation/ragdoll && uv run ragdoll support judge \
    --provider amazon-bedrock --model openai.gpt-oss-120b-1:0 \
    --input-file  ../../evaluation-results/facet_rag/opus_plan_5topic/answers.resolved.jsonl \
    --output-file ../../evaluation-results/facet_rag/opus_plan_5topic/support-bedrock-120/judgments.jsonl \
    --raw-events-dir ../../evaluation-results/facet_rag/opus_plan_5topic/support-bedrock-120/raw-events
# processed=149

python3 scripts/ragdoll-support-to-csv.py \
    evaluation-results/facet_rag/opus_plan_5topic/support-bedrock-120/judgments.jsonl \
    --output evaluation-results/facet_rag/opus_plan_5topic/support-bedrock-120/judgments.csv \
    --summary-output evaluation-results/facet_rag/opus_plan_5topic/support-bedrock-120/judgments.summary.csv
```

Aggregate summary (`judgments.summary.csv`):

```
run_id,total,full_support,partial_support,no_support,judge_errors,full_support_rate,partial_or_full_rate
facet_rag.opus_plan_5topic,149,66,57,18,8,0.442953,0.825503
```

vs aus_agent-dev-full (`evaluation-results/aus-agent/support-bedrock/judgments.summary.csv`):

```
aus-agent-dev-full,781,271,407,83,20,0.346991,0.868118
```

Per-topic breakdown (`support_label` grouped by `metadata.topic_id`; FS=full,
PS=partial, NS=no-support, ERR=judge error):

| topic | n | FS | PS | NS | ERR | partial_or_full |
|---|---|---|---|---|---|---|
| CSGO | 21 | 11 | 7 | 1 | 2 | 0.857 |
| SCALING | 39 | 11 | 18 | 8 | 2 | 0.744 |
| RETIRE | 41 | 17 | 17 | 5 | 2 | 0.829 |
| PRESCHOOL | 30 | 18 | 8 | 4 | 0 | 0.867 |
| SWARM | 18 | 9 | 7 | 0 | 2 | 0.889 |

facet_rag's `full_support_rate` (0.443) **beats** aus_agent's aggregate
(0.347) — the curator's evidence-block precision work bought something real.
But `partial_or_full_rate` (0.826) is below both aus_agent (0.868) and the
plan's ≥0.87 target, and no-support (12.1%) misses the ≤10% target. SCALING
is the weakest topic on this metric too (0.744) — 39 citations judged, the
most of any topic, on the broadest-facet-count run.

## 5. Verdict on the plan's open question (§5.1: precision or recall?)

The curator trade (§3.1: CS:GO went 438-767 words pre-curator to 314-365
post-curator) is no longer a guess: it bought a real full-support-rate lead
over aus_agent's uncurated pool, at the cost of thin answers that still lose
on UMBRELA (reference-pool relevance) on every topic. Neither metric is
uniformly better — precision (support) partially favors facet_rag,
reference-pool relevance (UMBRELA) favors aus_agent everywhere. §3's content-
starvation diagnosis (raise `--max-chars`, richer analyzer notes) remains the
right next step to close the UMBRELA gap without giving up the support-rate
lead, but that is a code change, out of scope for this measurement-only
session.

## Artifacts

- `data/outputs/facet_rag/*.{output,trajectory}.json` — the 5 runs (gitignored,
  local only; source copy at `~/Downloads/trec_rag_26_data/facet_rag-runs/`)
- `evaluation-results/facet_rag/opus_plan_5topic/answers.resolved.jsonl`
- `evaluation-results/facet_rag/opus_plan_5topic/umbrela.input.jsonl`
- `evaluation-results/facet_rag/opus_plan_5topic/umbrela-bedrock-120/judgments.jsonl`
- `evaluation-results/facet_rag/opus_plan_5topic/support-bedrock-120/judgments.jsonl`
- `evaluation-results/facet_rag/opus_plan_5topic/support-bedrock-120/judgments.summary.csv`
