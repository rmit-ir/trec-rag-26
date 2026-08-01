#!/usr/bin/env bash
# Rehearse the whole bm25_tune pipeline on a FOREIGN synthetic index with plain
# TSV queries, spending $0.00. The evidence behind
# worklogs/2026-07-31-bm25-tune-generalization-skill.md.
#
# Two indexes are built: one with text stored (the healthy case) and one via
# DefaultLuceneDocumentGenerator with no --storeRaw (no retrievable text at all),
# because probe_index.py's exit-2 verdict is the one that cannot be checked by
# reading. Building the second is what caught the probe's own bug — it reported
# the healthy index as broken whenever the default probe term was absent.
#
# Run from the repo root. Needs the task env + JDK 21; makes no network call.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
export JAVA_HOME="$PWD/tasks/bm25_tune/env/lib/jvm"
RUN="uv run --project tasks/bm25_tune"

WORK=/tmp/bm25-generic-check
NOTEXT=/tmp/bm25-notext
DATA=/tmp/rehearse-data
rm -rf "$WORK" "$NOTEXT" "$DATA"
mkdir -p "$WORK/corpus" "$NOTEXT/corpus"

# ---------------------------------------------------------------------------
# 1. A synthetic corpus: two topics with DISJOINT vocabularies plus filler.
#    Disjoint so relevance is unambiguous without a judge — which is what lets
#    score/stats be rehearsed from a synthetic qrels file (step 7).
# ---------------------------------------------------------------------------
$RUN python - "$WORK/corpus/docs.jsonl" <<'PY'
import json, random, sys
random.seed(11)
VOCAB = {
    "soil": "soil moisture irrigation tensiometer sensors water scheduling growers".split(),
    "lib":  "library funding levy municipal branches budget public allocation".split(),
    "filler": "weather transport culture history science economy policy".split(),
}
rows = []
for i in range(400):
    kind = "soil" if i % 4 == 0 else "lib" if i % 4 == 1 else "filler"
    words = [random.choice(VOCAB[kind]) for _ in range(60)]
    rows.append({"id": f"doc_{i}_p1", "contents": " ".join(words)})
with open(sys.argv[1], "w") as fh:
    for r in rows:
        fh.write(json.dumps(r) + "\n")
print(f"wrote {len(rows)} docs -> {sys.argv[1]}")
PY
cp "$WORK/corpus/docs.jsonl" "$NOTEXT/corpus/docs.jsonl"

# ---------------------------------------------------------------------------
# 2. Two indexes. The second deliberately stores no retrievable text.
# ---------------------------------------------------------------------------
$RUN python -m pyserini.index.lucene --collection JsonCollection \
    --input "$WORK/corpus" --index "$WORK/idx" \
    --generator DefaultLuceneDocumentGenerator \
    --threads 2 --storePositions --storeDocvectors --storeRaw

$RUN python -m pyserini.index.lucene --collection JsonCollection \
    --input "$NOTEXT/corpus" --index "$NOTEXT/idx" \
    --generator DefaultLuceneDocumentGenerator --threads 2

# ---------------------------------------------------------------------------
# 3. Probe both. Expect 0 on the healthy one, 2 on the textless one, 3 when no
#    query matches, 1 on a missing dir.
# ---------------------------------------------------------------------------
probe() { $RUN python skills/bm25-parameter-tuning/scripts/probe_index.py "$@"; }
set +e
probe "$WORK/idx" --query "soil moisture irrigation" --query "library funding levy"
echo "ok=$?"
probe "$NOTEXT/idx" --query "soil moisture irrigation"; echo "notext=$?"
probe "$WORK/idx" --query "zzzzz-nonexistent-term";     echo "nohits=$?"
probe /tmp/definitely-not-here;                          echo "missing=$?"
set -e

# ---------------------------------------------------------------------------
# 4. Profile: num_docs read off the live index, not typed. Grid cut to 2x2.
# ---------------------------------------------------------------------------
$RUN python skills/bm25-parameter-tuning/scripts/make_profile.py \
    --name rehearse --index "$WORK/idx" --data-dir "$DATA" \
    --grid-k1 "0.9,1.2" --grid-b "0.4,0.75" --out /tmp/rehearse.env --force
source /tmp/rehearse.env

# ---------------------------------------------------------------------------
# 5. Bring-your-own-queries: a plain headed TSV, no labeled search log anywhere.
# ---------------------------------------------------------------------------
printf 'topic_id\tquery\tnarrative\n' > /tmp/rehearse-queries.tsv
cat >> /tmp/rehearse-queries.tsv <<'EOF'
t-1	soil moisture irrigation	How do growers use soil moisture sensors to schedule irrigation?
t-1	tensiometer scheduling	How do growers use soil moisture sensors to schedule irrigation?
t-2	library funding levy	How is public library funding allocated across branches?
t-2	municipal budget branches	How is public library funding allocated across branches?
EOF
$RUN python -m bm25tune make-queries /tmp/rehearse-queries.tsv --per-topic 1

# ---------------------------------------------------------------------------
# 6. Sweep (search only, no spend), then draw the --from-pool calibration sample
#    WITHOUT invoking the judge — proving the any-corpus gate path reads a real
#    pool.jsonl/pool-texts.jsonl pair at $0.00.
# ---------------------------------------------------------------------------
$RUN python -m bm25tune search-sweep --stage A --run-id rehearse-a

$RUN python - <<'PY'
import argparse
from bm25tune import cli
from bm25tune.config import Config
cfg = Config.from_env()
sample = cli._pool_calibration_hits(
    cfg, argparse.Namespace(from_pool="rehearse-a", n=8, seed=7, queries=None))
print("drawn:", len(sample))
print("topics:", sorted({h.topic_id for h in sample}))
print("classes:", {h.agent_class for h in sample})   # must be {'unjudged'}
print("narrative:", sample[0].topic)                 # off the query file, not the pool
PY

# The spend ceiling has no default: calibrate must refuse before any call.
set +e
env -u BM25_TUNE_BUDGET_USD $RUN python -m bm25tune calibrate \
    --from-pool rehearse-a --n 8 2>&1 | tail -2
echo "no-budget rc=${PIPESTATUS[0]}   (expect 1)"
set -e

# ---------------------------------------------------------------------------
# 7. Synthetic qrels from the pool (vocabulary overlap), so score/stats run with
#    zero Bedrock spend. All cells tie at 1.0 — the expected null on a 2-topic
#    corpus with disjoint vocabularies, and what inflation_vs_single=1.20x says.
# ---------------------------------------------------------------------------
$RUN python - <<'PY'
import json, pathlib
run = pathlib.Path("/tmp/rehearse-data/runs/rehearse-a")
texts = {json.loads(l)["chunk_id"]: json.loads(l)["text"]
         for l in (run / "pool-texts.jsonl").read_text().splitlines() if l}
vocab = {"t-1": {"soil", "moisture", "irrigation", "tensiometer", "sensors"},
         "t-2": {"library", "funding", "levy", "municipal", "branches"}}
out = []
for line in (run / "pool.jsonl").read_text().splitlines():
    if not line:
        continue
    r = json.loads(line)
    hits = len(set(texts.get(r["chunk_id"], "").split()) & vocab[r["topic_id"]])
    out.append(f'{r["topic_id"]} 0 {r["chunk_id"]} {min(hits, 3)}')
pathlib.Path("/tmp/rehearse-qrels.txt").write_text("\n".join(out) + "\n")
print(len(out), "qrels rows")
PY

export BM25_TUNE_BUDGET_USD=50.0
$RUN python -m bm25tune score --run-id rehearse-a \
    --qrels /tmp/rehearse-qrels.txt --prompt-version facet-v1 --label synthetic
$RUN python -m bm25tune stats --run-id rehearse-a \
    --qrels /tmp/rehearse-qrels.txt --prompt-version facet-v1 \
    --candidates k1_1.2__b_0.75 --metrics ndcg10_exp --bootstrap 200

echo "REHEARSAL COMPLETE — \$0.00 spent (no Bedrock call was made)"
