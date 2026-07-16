import { NextResponse } from "next/server";
import { scanOutputs } from "@/lib/server/fileIndex";

export const dynamic = "force-dynamic";

export async function GET() {
  return NextResponse.json(scanOutputs());
}
