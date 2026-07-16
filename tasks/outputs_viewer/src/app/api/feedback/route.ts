import { NextResponse } from "next/server";
import { appendFeedback, readFeedback } from "@/lib/server/feedback";
import type { FeedbackTargetType } from "@/lib/types";

export const dynamic = "force-dynamic";

/**
 * GET /api/feedback?system=&sessionId=&user=&all=1
 * Default returns latest-wins records (one per user+target); all=1 returns
 * the full append history.
 */
export async function GET(req: Request) {
  const url = new URL(req.url);
  const records = readFeedback({
    system: url.searchParams.get("system") ?? undefined,
    sessionId: url.searchParams.get("sessionId") ?? undefined,
    user: url.searchParams.get("user") ?? undefined,
    latestOnly: url.searchParams.get("all") !== "1",
  });
  return NextResponse.json({ records });
}

const TARGET_TYPES: FeedbackTargetType[] = ["answer", "paragraph", "citation"];

export async function POST(req: Request) {
  let body: Record<string, unknown>;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "invalid JSON body" }, { status: 400 });
  }
  const user = normalizeUser(String(body.user ?? ""));
  const system = String(body.system ?? "");
  const sessionId = String(body.sessionId ?? "");
  const target = body.target as
    | { type?: string; paragraphIndex?: number; docid?: string }
    | undefined;
  if (!user) return NextResponse.json({ error: "user required" }, { status: 400 });
  if (!system || !sessionId) {
    return NextResponse.json({ error: "system and sessionId required" }, { status: 400 });
  }
  if (!target || !TARGET_TYPES.includes(target.type as FeedbackTargetType)) {
    return NextResponse.json(
      { error: `target.type must be one of ${TARGET_TYPES.join(", ")}` },
      { status: 400 },
    );
  }
  const rating = body.rating === "up" || body.rating === "down" ? body.rating : null;
  const rec = appendFeedback({
    user,
    system,
    sessionId,
    target: {
      type: target.type as FeedbackTargetType,
      ...(target.type === "paragraph" ? { paragraphIndex: Number(target.paragraphIndex ?? 0) } : {}),
      ...(target.type === "citation" ? { docid: String(target.docid ?? "") } : {}),
    },
    rating,
    comment: typeof body.comment === "string" ? body.comment : "",
    tags: Array.isArray(body.tags)
      ? (body.tags as unknown[]).filter((t): t is string => typeof t === "string")
      : [],
  });
  if (!rec) return NextResponse.json({ error: "invalid system/sessionId" }, { status: 400 });
  return NextResponse.json({ record: rec }, { status: 201 });
}

/** Same normalization as the client identity gate. */
function normalizeUser(raw: string): string {
  return raw.trim().toLowerCase().replace(/[^a-z0-9]/g, "");
}
