/**
 * TREC RAG 2026 output object + run persistence — TS port of
 * `src/ragrun/outputs.py`. Writes both run artifacts to `data/outputs/pi-agent/`
 * (repo-root data/, never inside tasks/).
 */
import fs from "node:fs";
import path from "node:path";
import { OUTPUT_DIR, TEAM_ID } from "./config.js";
import { runTimestamp } from "./time.js";
import type { Trajectory } from "./trajectory.js";

export { runTimestamp } from "./time.js";

export interface AnswerSentence {
  text: string;
  citations: number[];
}

export interface RagOutput {
  metadata: {
    team_id: string;
    narrative_id: string;
    narrative: string;
    run_id: string;
    run_desc: string;
  };
  references: string[];
  answer: AnswerSentence[];
}

/** First `nWords` of the query, sanitised: `write_a_blog_post_contrasting`. */
export function querySlug(query: string, nWords = 5): string {
  const words = (query.toLowerCase().match(/[a-z0-9]+/g) ?? []).slice(0, nWords);
  return words.join("_") || "query";
}

export function buildRagOutput(opts: {
  narrativeId: string;
  narrative: string;
  runId: string;
  runDesc: string;
  references: string[];
  answer: AnswerSentence[];
  teamId?: string;
}): RagOutput {
  return {
    metadata: {
      team_id: opts.teamId ?? TEAM_ID,
      narrative_id: opts.narrativeId,
      narrative: opts.narrative,
      run_id: opts.runId,
      run_desc: opts.runDesc,
    },
    references: [...opts.references],
    answer: opts.answer,
  };
}

/** Return violations of the track's answer/validation rules (empty = valid).
 *  Mirrors rag-task.md and the Python `validate_rag_output`. */
export function validateRagOutput(obj: any): string[] {
  const errs: string[] = [];
  let meta = obj?.metadata;
  if (typeof meta !== "object" || meta === null || Array.isArray(meta)) {
    errs.push("metadata missing or not an object");
    meta = {};
  }
  const required = ["team_id", "narrative_id", "narrative", "run_id", "run_desc"];
  const missing = required.filter((k) => !(k in meta));
  if (missing.length) errs.push(`metadata missing keys: ${JSON.stringify(missing.sort())}`);
  const extra = Object.keys(meta).filter((k) => !required.includes(k));
  if (extra.length) errs.push(`metadata has extra keys (not allowed): ${JSON.stringify(extra.sort())}`);

  let refs = obj?.references;
  if (!Array.isArray(refs) || !refs.every((r: unknown) => typeof r === "string")) {
    errs.push("references must be a list of docid strings");
    refs = [];
  }
  let answer = obj?.answer;
  if (!Array.isArray(answer) || answer.length === 0) {
    errs.push("answer must be a non-empty list");
    answer = [];
  }

  const cited = new Set<number>();
  let totalWords = 0;
  answer.forEach((sent: any, i: number) => {
    if (typeof sent !== "object" || sent === null || !("text" in sent) || !("citations" in sent)) {
      errs.push(`answer[${i}] must have 'text' and 'citations'`);
      return;
    }
    totalWords += String(sent.text).split(/\s+/).filter(Boolean).length;
    const cits = sent.citations;
    if (!Array.isArray(cits) || cits.length > 3) {
      errs.push(`answer[${i}].citations must be a list of at most 3 indices`);
      return;
    }
    for (const c of cits) {
      if (!Number.isInteger(c) || c < 0 || c >= refs.length) {
        errs.push(`answer[${i}] cites invalid reference index ${JSON.stringify(c)}`);
      } else {
        cited.add(c);
      }
    }
  });
  if (totalWords > 1024) errs.push(`answer is ${totalWords} words (max 1024)`);
  const uncited = refs.map((_: string, i: number) => i).filter((i: number) => !cited.has(i));
  if (uncited.length) errs.push(`references never cited: indices ${JSON.stringify(uncited)}`);
  return errs;
}

export interface SavedPaths {
  trajectory: string;
  output: string;
  violations?: string;
}

/** Persist the two run artifacts; returns their paths.
 *  Writes `data/outputs/pi-agent/<ts>.<slug>.{trajectory,output}.json` where
 *  `<ts>` is the compact Melbourne-local stamp (`20260716T163259123000+1000`).
 *  Violations of the track rules (if any) are stored alongside — visibility
 *  over failure. */
export function saveRun(
  query: string,
  trajectory: Trajectory,
  output: RagOutput,
  opts: { timestamp?: string; validate?: boolean; outDir?: string } = {},
): SavedPaths {
  const ts = opts.timestamp ?? runTimestamp();
  const slug = querySlug(query);
  const outDir = opts.outDir ?? OUTPUT_DIR;
  fs.mkdirSync(outDir, { recursive: true });

  const paths: SavedPaths = {
    trajectory: path.join(outDir, `${ts}.${slug}.trajectory.json`),
    output: path.join(outDir, `${ts}.${slug}.output.json`),
  };
  fs.writeFileSync(paths.trajectory, JSON.stringify(trajectory, null, 2));
  fs.writeFileSync(paths.output, JSON.stringify(output, null, 2));

  if (opts.validate ?? true) {
    const errs = validateRagOutput(output);
    if (errs.length) {
      paths.violations = path.join(outDir, `${ts}.${slug}.output.violations.json`);
      fs.writeFileSync(paths.violations, JSON.stringify(errs, null, 2));
    }
  }
  return paths;
}
