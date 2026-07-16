import { NextResponse } from "next/server";
import { loadSession } from "@/lib/server/sessions";

export const dynamic = "force-dynamic";

/** Next.js hands route params percent-encoded; decode before using as file
 * names (clients encode `+` as %2B — a raw `+` in a path stays `+`). */
function safeDecode(s: string): string {
  try {
    return decodeURIComponent(s);
  } catch {
    return s;
  }
}

export async function GET(
  _req: Request,
  { params }: { params: Promise<{ system: string; sessionId: string }> },
) {
  const raw = await params;
  const system = safeDecode(raw.system);
  const sessionId = safeDecode(raw.sessionId);
  try {
    const detail = loadSession(system, sessionId);
    if (!detail) {
      return NextResponse.json({ error: "session not found" }, { status: 404 });
    }
    return NextResponse.json(detail);
  } catch (e) {
    return NextResponse.json(
      { error: `failed to load session: ${String(e)}` },
      { status: 500 },
    );
  }
}
