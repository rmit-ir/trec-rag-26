import { NextResponse } from "next/server";
import { fetchDoc, fetchFullDoc } from "@/lib/server/docFetch";

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
  const sp = new URL(req.url).searchParams;
  const full = sp.get("full") === "1";
  const src = sp.get("source");
  const prefer = src === "sparse" || src === "dense" ? src : undefined;
  const doc = await (full ? fetchFullDoc(id) : fetchDoc(id, prefer));
  if (!doc) {
    return NextResponse.json(
      { error: `docid '${id}' not found on any backend` },
      { status: 404 },
    );
  }
  return NextResponse.json(doc);
}
