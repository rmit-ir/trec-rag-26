import { NextResponse } from "next/server";
import { fetchDoc } from "@/lib/server/docFetch";

export const dynamic = "force-dynamic";

export async function GET(
  req: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id: rawId } = await params;
  let id: string;
  try {
    id = decodeURIComponent(rawId);
  } catch {
    id = rawId;
  }
  if (!/^[\w.-]+$/.test(id)) {
    return NextResponse.json({ error: "malformed docid" }, { status: 400 });
  }
  // Get the doc/chunk by id, as-is — no backend hint, no full-doc mode.
  const doc = await fetchDoc(id);
  if (!doc) {
    return NextResponse.json(
      { error: `docid '${id}' not found on any backend` },
      { status: 404 },
    );
  }
  return NextResponse.json(doc);
}
