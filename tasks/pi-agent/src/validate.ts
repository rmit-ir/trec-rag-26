/**
 * Standalone validator for *.output.json artifacts against the TREC RAG 2026
 * citation rules (rag-task.md).
 *
 *   pnpm exec tsx src/validate.ts <path/to/*.output.json> [...]
 */
import fs from "node:fs";
import { validateRagOutput } from "./outputs.js";

const files = process.argv.slice(2);
if (files.length === 0) {
  console.error("Usage: tsx src/validate.ts <output.json> [...]");
  process.exit(2);
}

let bad = 0;
for (const f of files) {
  const obj = JSON.parse(fs.readFileSync(f, "utf-8"));
  const errs = validateRagOutput(obj);
  if (errs.length === 0) {
    const words = obj.answer.reduce(
      (n: number, s: { text: string }) => n + s.text.split(/\s+/).filter(Boolean).length,
      0,
    );
    console.log(
      `OK   ${f} (${obj.references.length} references, ${obj.answer.length} sentences, ${words} words)`,
    );
  } else {
    bad += 1;
    console.log(`FAIL ${f}`);
    for (const e of errs) console.log(`  - ${e}`);
  }
}
process.exit(bad > 0 ? 1 : 0);
