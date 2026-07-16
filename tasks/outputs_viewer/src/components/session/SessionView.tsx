"use client";
import * as React from "react";
import useSWR from "swr";
import Link from "next/link";
import Box from "@mui/material/Box";
import Typography from "@mui/material/Typography";
import Breadcrumbs from "@mui/material/Breadcrumbs";
import MuiLink from "@mui/material/Link";
import Chip from "@mui/material/Chip";
import Skeleton from "@mui/material/Skeleton";
import Alert from "@mui/material/Alert";
import Stack from "@mui/material/Stack";
import { fetcher } from "@/lib/client/api";
import { useUrlState } from "@/lib/client/urlState";
import type { SessionDetail } from "@/lib/types";
import Timeline from "./Timeline";
import StepTree from "./StepTree";
import DetailPane from "./DetailPane";
import DocSidebar from "./DocSidebar";
import type { NodeSelection } from "./stepMeta";

/**
 * Session view, PostHog-LLM-trace style: one unified layout instead of
 * top-level Answer/Trajectory tabs.
 *
 *   TOP    header stat chips, then the ALWAYS-visible step timeline
 *          (sequence-based — trajectories carry no timings; markers select).
 *   BELOW  master-detail: step tree (filterable, Answer node appended) |
 *          tabbed detail pane | doc sidebar (opens on citation/docid click).
 *
 * URL state: ?step=<index|answer> (default answer), ?dtab=<detail tab>,
 * ?doc=<docid>. Legacy ?tab=answer|trajectory URLs are migrated in place.
 */
export default function SessionView({
  system,
  sessionId,
}: {
  system: string;
  sessionId: string;
}) {
  const { data, error, isLoading } = useSWR<SessionDetail>(
    `/api/outputs/${encodeURIComponent(system)}/${encodeURIComponent(sessionId)}`,
    fetcher,
  );
  const { get, set, setMany } = useUrlState();

  // ---- legacy ?tab= migration (old links keep working) --------------------
  const legacyTab = get("tab");
  React.useEffect(() => {
    if (legacyTab == null) return;
    // trajectory → select the first step; answer → default (answer node)
    setMany({ tab: null, step: legacyTab === "trajectory" ? "0" : null });
  }, [legacyTab, setMany]);

  // ---- selection from URL --------------------------------------------------
  const stepParam = get("step");
  const selection: NodeSelection = React.useMemo(() => {
    if (stepParam == null || stepParam === "answer") return "answer";
    const n = Number(stepParam);
    return Number.isInteger(n) && n >= 0 ? n : "answer";
  }, [stepParam]);
  const dtab = get("dtab");
  const doc = get("doc");

  const select = React.useCallback(
    (sel: NodeSelection) =>
      // changing node resets the detail tab to that node's default
      setMany({ step: sel === "answer" ? null : String(sel), dtab: null }),
    [setMany],
  );
  const setDtab = React.useCallback((v: string | null) => set("dtab", v), [set]);
  const openDoc = React.useCallback((docid: string) => set("doc", docid), [set]);
  const closeDoc = React.useCallback(() => set("doc", null), [set]);

  if (error) {
    return <Alert severity="error">Failed to load session: {String(error.message)}</Alert>;
  }
  if (isLoading || !data) {
    return (
      <>
        <Skeleton height={40} />
        <Skeleton height={72} />
        <Skeleton height={280} />
      </>
    );
  }

  const trajectory = data.trajectory;
  const steps = trajectory?.result ?? [];
  const meta = trajectory?.metadata ?? {};
  const counts = trajectory?.tool_call_counts ?? {};
  const answerSummary =
    data.output.answer?.[0]?.text ?? data.output.metadata?.narrative ?? "";

  return (
    <Box>
      <Stack direction="row" alignItems="center" spacing={2} sx={{ mb: 1 }} flexWrap="wrap" useFlexGap>
        <Breadcrumbs>
          <MuiLink component={Link} href="/systems" underline="hover" color="inherit">
            Systems
          </MuiLink>
          <MuiLink
            component={Link}
            href={`/systems?system=${encodeURIComponent(system)}`}
            underline="hover"
            color="inherit"
          >
            {system}
          </MuiLink>
          <Typography color="text.primary" variant="body2" sx={{ fontFamily: "monospace" }}>
            {sessionId}
          </Typography>
        </Breadcrumbs>
      </Stack>

      {/* header stats — always visible */}
      <Stack direction="row" spacing={0.75} flexWrap="wrap" useFlexGap alignItems="center" sx={{ mb: 1 }}>
        {trajectory?.status ? (
          <Chip
            size="small"
            label={`status: ${trajectory.status}`}
            color={trajectory.status === "completed" ? "success" : "warning"}
            variant="outlined"
          />
        ) : null}
        {typeof meta.model === "string" ? (
          <Chip size="small" variant="outlined" label={`model: ${meta.model}`} />
        ) : null}
        {Object.entries(counts).map(([tool, n]) => (
          <Chip key={tool} size="small" variant="outlined" label={`${tool}: ${n}`} />
        ))}
        {trajectory ? (
          <Chip
            size="small"
            variant="outlined"
            label={`retrieved docids: ${trajectory.retrieved_docids?.length ?? 0}`}
          />
        ) : (
          <Chip size="small" variant="outlined" color="warning" label="no trajectory" />
        )}
        <Chip size="small" variant="outlined" label={`steps: ${steps.length}`} />
      </Stack>

      {/* timeline — always visible, never behind a tab */}
      <Box sx={{ mb: 1.5 }}>
        <Timeline steps={steps} trajectory={trajectory} selected={selection} onSelect={select} />
      </Box>

      {/* master-detail (+ doc sidebar) */}
      <Box
        sx={{
          display: "grid",
          gap: 1.5,
          alignItems: "start",
          gridTemplateColumns: {
            xs: "1fr",
            md: doc
              ? "240px minmax(0, 1fr) minmax(280px, 360px)"
              : "270px minmax(0, 1fr)",
          },
        }}
      >
        <StepTree
          steps={steps}
          answerSummary={answerSummary}
          selected={selection}
          onSelect={select}
        />
        <DetailPane
          selection={selection}
          dtab={dtab}
          onDtabChange={setDtab}
          steps={steps}
          output={data.output}
          system={system}
          sessionId={sessionId}
          activeDoc={doc}
          onOpenDoc={openDoc}
        />
        {doc ? (
          <DocSidebar docid={doc} system={system} sessionId={sessionId} onClose={closeDoc} />
        ) : null}
      </Box>
    </Box>
  );
}
