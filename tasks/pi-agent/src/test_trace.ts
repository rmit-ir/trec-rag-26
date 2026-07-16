import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  buildRagOutput,
  saveRun,
  toSubmissionOutput,
} from "./outputs.js";
import { TrajectoryBuilder } from "./trajectory.js";

const tb = new TrajectoryBuilder("test-qid", "test query", { model: "test-model" });
tb.addReasoning(
  "plan",
  {
    t_start: "2026-07-16T19:00:00.000+10:00",
    t_end: "2026-07-16T19:00:01.000+10:00",
    turn: 0,
  },
  { stats: { tokens: { input: 100, output: 20, total: 120 } } },
);
tb.addToolCall(
  "search",
  { query: "evidence" },
  "results",
  {
    returned: [{ docid: "shard_00001_1", score: 0.9 }],
    timing: {
      t_start: "2026-07-16T19:00:01.000+10:00",
      t_end: "2026-07-16T19:00:01.500+10:00",
      turn: 0,
    },
    documents: [{
      id: "shard_00001_1_p1",
      docid: "shard_00001_1",
      kind: "chunk",
      rank: 1,
      score: 0.9,
      text: "evidence text",
    }],
    context: { staged: ["shard_00001_1"] },
    stats: {
      returned_documents: 1,
      context_tokens: 100,
      context_budget_tokens: 500_000,
      elapsed_ms: 1_500,
    },
    extras: { k: 10 },
  },
);
tb.addOutputText("answer", {
  t_start: "2026-07-16T19:00:02.000+10:00",
  t_end: "2026-07-16T19:00:03.000+10:00",
  turn: 1,
});

const trajectory = tb.finalize("completed", []);
assert.deepEqual(Object.keys(trajectory).sort(), [
  "metadata",
  "query_id",
  "raw_messages",
  "result",
  "retrieved_docids",
  "status",
  "tool_call_counts",
  "tool_call_counts_all",
].sort());
for (const item of trajectory.result) {
  for (const forbidden of [
    "id", "parent_id", "t_start", "t_end", "turn", "stats",
    "documents", "context", "failed",
  ]) {
    assert.equal(forbidden in item, false, `${forbidden} leaked into trajectory`);
  }
}

const trace = tb.finalizeTrace("completed", [], {
  startedAt: "2026-07-16T19:00:00.000+10:00",
  endedAt: "2026-07-16T19:00:03.000+10:00",
});
assert.equal(trace.duration_ms, 3_000);
assert.equal(trace.steps.length, 3);
assert.equal(trace.steps[1].documents?.[0]?.text, "evidence text");
assert.deepEqual(trace.steps[1].context?.staged, ["shard_00001_1"]);

const output = buildRagOutput({
  narrativeId: "test-qid",
  narrative: "test query",
  runId: "test-run",
  runDesc: "test",
  references: ["shard_00001_1"],
  answer: [{ text: "answer", citations: [0] }],
});
const dir = fs.mkdtempSync(path.join(os.tmpdir(), "pi-agent-trace-"));
try {
  const paths = saveRun("test query", trajectory, output, {
    outDir: dir,
    timestamp: "test",
    trace,
  });
  const savedTrajectory = JSON.parse(fs.readFileSync(paths.trajectory, "utf8"));
  const savedOutput = JSON.parse(fs.readFileSync(paths.output, "utf8"));
  assert.equal("trace" in savedTrajectory, false);
  assert.equal(savedOutput.trace.schema_version, "trec-rag-trace/1");
  assert.deepEqual(Object.keys(toSubmissionOutput(savedOutput)).sort(), [
    "answer", "metadata", "references",
  ]);
} finally {
  fs.rmSync(dir, { recursive: true, force: true });
}

console.log("pi-agent trace tests: OK");
