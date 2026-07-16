import { Suspense } from "react";
import SessionView from "@/components/session/SessionView";

export default async function SessionPage({
  params,
}: {
  params: Promise<{ system: string; sessionId: string }>;
}) {
  const { system, sessionId } = await params;
  return (
    <Suspense>
      <SessionView system={decodeURIComponent(system)} sessionId={decodeURIComponent(sessionId)} />
    </Suspense>
  );
}
