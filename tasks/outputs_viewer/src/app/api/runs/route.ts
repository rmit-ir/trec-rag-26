import { NextResponse } from "next/server";
import { listRuns, startRun } from "@/lib/server/runManager";

export const dynamic = "force-dynamic";

/** GET /api/runs — in-flight runs plus recent history. */
export async function GET() {
  return NextResponse.json(listRuns());
}

/**
 * POST /api/runs { query } — spawn an aus_agent run and return at once.
 *
 * Never blocks on the child: the response carries the queued record, and the
 * client polls GET /api/runs (and /api/outputs) for progress.
 */
export async function POST(req: Request) {
  let body: Record<string, unknown>;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "invalid JSON body" }, { status: 400 });
  }
  if (typeof body.query !== "string") {
    return NextResponse.json({ error: "query required" }, { status: 400 });
  }
  const result = startRun(body.query);
  if (!result.ok) {
    return NextResponse.json({ error: result.error }, { status: result.status ?? 400 });
  }
  return NextResponse.json({ record: result.record }, { status: 202 });
}
