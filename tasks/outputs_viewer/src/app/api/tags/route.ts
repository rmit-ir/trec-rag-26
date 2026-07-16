import { NextResponse } from "next/server";
import { addTags, readTags } from "@/lib/server/feedback";

export const dynamic = "force-dynamic";

export async function GET() {
  return NextResponse.json({ tags: readTags() });
}

/** POST {"tag": "..."} or {"tags": ["..."]} — adds new tags to tags.json. */
export async function POST(req: Request) {
  let body: { tag?: string; tags?: string[] };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "invalid JSON body" }, { status: 400 });
  }
  const tags = [
    ...(typeof body.tag === "string" ? [body.tag] : []),
    ...(Array.isArray(body.tags) ? body.tags.filter((t) => typeof t === "string") : []),
  ];
  if (tags.length === 0) {
    return NextResponse.json({ error: "no tags given" }, { status: 400 });
  }
  return NextResponse.json({ tags: addTags(tags) });
}
