import "server-only";
import fs from "node:fs";
import { scanOutputs, sessionPaths } from "./fileIndex";
import type { SessionDetail, TrajectoryFile } from "@/lib/types";

/** Load one session's full content on demand (raw_messages stripped). */
export function loadSession(system: string, sessionId: string): SessionDetail | null {
  const paths = sessionPaths(system, sessionId);
  if (!paths) return null;

  const output = JSON.parse(fs.readFileSync(paths.outPath, "utf8"));

  let trajectory: TrajectoryFile | null = null;
  if (paths.trajPath) {
    try {
      const raw = JSON.parse(fs.readFileSync(paths.trajPath, "utf8"));
      // raw_messages can dominate the payload; the UI renders `result` steps.
      delete raw.raw_messages;
      trajectory = raw;
    } catch {
      trajectory = null;
    }
  }

  const idx = scanOutputs();
  const header =
    idx.sessions.find((s) => s.system === system && s.sessionId === sessionId) ??
    ({
      system,
      sessionId,
      ts: sessionId.split(".")[0] ?? sessionId,
      slug: sessionId.split(".").slice(1).join("."),
      mtime: 0,
      hasTrajectory: trajectory != null,
    } as SessionDetail["header"]);

  return { header, output, trajectory };
}
