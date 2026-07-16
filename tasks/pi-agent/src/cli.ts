/**
 * CLI — run the TREC RAG 2026 pi agent on one query, one topic id, or all
 * topics from a TSV (qid \t narrative).
 *
 *   pnpm agent -- --query "..."                    # ad-hoc query
 *   pnpm agent -- --qid 6847...493 [--topics t.tsv]
 *   pnpm agent -- --all [--topics t.tsv]
 *   flags: --model <bedrock id> --k <int> --max-rounds <int> --thinking <level>
 */
import fs from "node:fs";
import { parseArgs } from "node:util";
import type { ThinkingLevel } from "@mariozechner/pi-agent-core";
import { DEFAULT_K, DEFAULT_MAX_ROUNDS, DEFAULT_MODEL_ID, DEFAULT_TOPICS_TSV } from "./config.js";
import { runResearchAgent } from "./agent.js";

interface Topic {
  qid: string;
  narrative: string;
}

function readTopics(tsvPath: string): Topic[] {
  const topics: Topic[] = [];
  for (const line of fs.readFileSync(tsvPath, "utf-8").split("\n")) {
    if (!line.trim()) continue;
    const tab = line.indexOf("\t");
    if (tab === -1) continue;
    topics.push({ qid: line.slice(0, tab).trim(), narrative: line.slice(tab + 1).trim() });
  }
  return topics;
}

async function main(): Promise<void> {
  const { values } = parseArgs({
    options: {
      query: { type: "string" },
      qid: { type: "string" },
      all: { type: "boolean", default: false },
      topics: { type: "string", default: DEFAULT_TOPICS_TSV },
      model: { type: "string", default: DEFAULT_MODEL_ID },
      k: { type: "string", default: String(DEFAULT_K) },
      "max-rounds": { type: "string", default: String(DEFAULT_MAX_ROUNDS) },
      thinking: { type: "string", default: "medium" },
    },
  });

  const modes = [values.query, values.qid, values.all ? "all" : undefined].filter(Boolean);
  if (modes.length !== 1) {
    console.error("Usage: exactly one of --query <text> | --qid <id> | --all is required.");
    process.exit(2);
  }

  const jobs: Topic[] = [];
  if (values.query) {
    jobs.push({ qid: "adhoc", narrative: values.query });
  } else {
    const topics = readTopics(values.topics!);
    if (values.qid) {
      const t = topics.find((x) => x.qid === values.qid);
      if (!t) {
        console.error(`qid ${values.qid} not found in ${values.topics}`);
        process.exit(2);
      }
      jobs.push(t);
    } else {
      jobs.push(...topics);
    }
  }

  const common = {
    modelId: values.model!,
    k: parseInt(values.k!, 10),
    maxRounds: parseInt(values["max-rounds"]!, 10),
    thinkingLevel: values.thinking as ThinkingLevel,
  };

  let failures = 0;
  for (const [i, job] of jobs.entries()) {
    console.error(`\n=== [${i + 1}/${jobs.length}] qid=${job.qid} model=${common.modelId} ===`);
    try {
      const res = await runResearchAgent({ queryId: job.qid, query: job.narrative, ...common });
      console.error(`[cli] status=${res.trajectory.status}`);
      console.error(`[cli] tool_call_counts=${JSON.stringify(res.trajectory.tool_call_counts)}`);
      console.error(`[cli] retrieved_docids=${res.trajectory.retrieved_docids.length}`);
      console.error(`[cli] references=${res.output.references.length} sentences=${res.output.answer.length}`);
      console.error(`[cli] trajectory: ${res.paths.trajectory}`);
      console.error(`[cli] output:     ${res.paths.output}`);
      if (res.violations.length) {
        failures += 1;
        console.error(`[cli] OUTPUT VIOLATIONS: ${JSON.stringify(res.violations, null, 2)}`);
      } else {
        console.error("[cli] output passes track citation rules");
      }
      if (res.trajectory.status === "failed") failures += 1;
    } catch (err) {
      failures += 1;
      console.error(`[cli] run failed for qid=${job.qid}: ${err}`);
    }
  }
  process.exit(failures > 0 ? 1 : 0);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
