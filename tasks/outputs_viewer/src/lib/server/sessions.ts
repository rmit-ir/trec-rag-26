import "server-only";
import fs from "node:fs";
import { scanOutputs, sessionPaths } from "./fileIndex";
import type { SessionDetail, TraceFile } from "@/lib/types";

/** Load one session exclusively from its output.json artifact. */
export function loadSession(system: string, sessionId: string): SessionDetail | null {
  const paths = sessionPaths(system, sessionId);
  if (!paths) return null;

  const output = JSON.parse(fs.readFileSync(paths.outPath, "utf8"));
  const trace: TraceFile | null =
    output?.trace && typeof output.trace === "object" ? output.trace : null;
  // Avoid sending the same potentially large trace twice in the API payload.
  // Both values still originate exclusively from output.json.
  delete output.trace;

  const idx = scanOutputs();
  const header =
    idx.sessions.find((s) => s.system === system && s.sessionId === sessionId) ??
    ({
      system,
      sessionId,
      ts: sessionId.split(".")[0] ?? sessionId,
      slug: sessionId.split(".").slice(1).join("."),
      mtime: 0,
      hasTrace: trace != null,
    } as SessionDetail["header"]);

  return { header, output, trace };
}
