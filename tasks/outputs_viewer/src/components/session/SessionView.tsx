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
import type { SessionDetail, TokenStats, TraceStep } from "@/lib/types";
import Timeline from "./Timeline";
import StepTree from "./StepTree";
import DetailPane from "./DetailPane";
import DocSidebar from "./DocSidebar";
import type { NodeSelection } from "./stepMeta";
import { fmtDuration } from "@/lib/gantt";
import { computeCost, fmtUsd } from "@/lib/pricing";

function withCumulativeTokenUsage(steps: TraceStep[]): TraceStep[] {
  const keys: (keyof TokenStats)[] = [
    "input",
    "input_uncached",
    "output",
    "cache_read",
    "cache_write",
    "total",
    "processed_input",
    "processed",
  ];
  const cumulative: TokenStats = {};
  let sawUsage = false;
  return steps.map((step) => {
    const direct = step.stats?.tokens;
    if (direct) {
      sawUsage = true;
      for (const key of keys) {
        const value = direct[key];
        if (typeof value === "number") cumulative[key] = (cumulative[key] ?? 0) + value;
      }
    }
    if (!sawUsage || step.stats?.cumulative_tokens) return step;
    return {
      ...step,
      stats: {
        ...step.stats,
        cumulative_tokens: { ...cumulative },
      },
    };
  });
}

/**
 * Session view, PostHog-LLM-trace style: one unified layout instead of
 * top-level Answer/Trajectory tabs.
 *
 *   TOP    header stat chips, then the ALWAYS-visible step timeline
 *          (sequence-based — trajectories carry no timings; markers select).
 *   BELOW  master-detail: step tree (filterable, Answer node appended) |
 *          tabbed detail pane | doc sidebar (opens on citation/docid click).
 *
 * URL state: ?step=<index|input|answer> (default answer),
 * ?dtab=<detail tab>, ?doc=<docid>.
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

  // ---- selection from URL --------------------------------------------------
  const stepParam = get("step");
  const selection: NodeSelection = React.useMemo(() => {
    if (stepParam == null || stepParam === "answer") return "answer";
    if (stepParam === "input") return "input";
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

  const trace = data.trace;
  const runId = trace?.metadata?.run_id ?? data.output.metadata?.run_id;
  const steps = withCumulativeTokenUsage(trace?.steps ?? []);
  const meta = trace?.metadata ?? {};
  const counts = trace?.summary?.tool_call_counts ?? {};
  const runTokens = trace?.summary?.tokens;
  const generationTokens = steps
    .filter((step) => step.type === "generation")
    .map((step) => step.stats?.tokens);
  const processedTokens =
    runTokens?.processed ??
    generationTokens.reduce(
      (sum, tokens) => sum + (tokens?.processed ?? tokens?.total ?? 0),
      0,
    );
  const processedInputTokens =
    runTokens?.processed_input ??
    generationTokens.reduce(
      (sum, tokens) => sum + (tokens?.processed_input ?? tokens?.input ?? 0),
      0,
    );
  const generatedOutputTokens =
    runTokens?.output ??
    generationTokens.reduce((sum, tokens) => sum + (tokens?.output ?? 0), 0);
  const latestBudgetStats = [...steps]
    .reverse()
    .find((step) => step.stats?.context_tokens != null)?.stats;
  const cost = computeCost(
    typeof meta.model === "string" ? meta.model : null,
    runTokens,
  );
  const answerSummary =
    data.output.answer?.[0]?.text ?? data.output.metadata?.narrative ?? "";
  // Which engine surfaced each doc: keyword searches → sparse, else dense.
  // First retrieval wins; the doc sidebar fetches from that same source.
  // (Plain computation — this sits below an early return, so no hooks.)
  const docSources = new Map<string, "sparse" | "dense">();
  for (const step of steps) {
    if (step.type !== "tool_call" || step.tool_name !== "search") continue;
    let args: unknown = step.arguments;
    if (typeof args === "string") {
      try {
        args = JSON.parse(args);
      } catch {
        args = {};
      }
    }
    const engine =
      (args as { search_engine?: string } | null)?.search_engine === "keyword"
        ? ("sparse" as const)
        : ("dense" as const);
    const ids = [
      ...(step.returned_docids ?? []),
      ...(((step.output as { results?: { id?: string }[] } | undefined)
        ?.results ?? [])
        .map((r) => r.id)
        .filter((x): x is string => typeof x === "string")),
    ];
    for (const id of ids) if (!docSources.has(id)) docSources.set(id, engine);
  }

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
          <Typography
            color="text.primary"
            variant="body2"
            sx={{ fontFamily: "monospace", wordBreak: "break-all" }}
          >
            {sessionId}
          </Typography>
        </Breadcrumbs>
      </Stack>

      {/* header stats — always visible */}
      <Stack direction="row" spacing={0.75} flexWrap="wrap" useFlexGap alignItems="center" sx={{ mb: 1 }}>
        {trace?.status ? (
          <Chip
            size="small"
            label={`status: ${trace.status}`}
            color={trace.status === "completed" ? "success" : "warning"}
            variant="outlined"
          />
        ) : null}
        {typeof meta.model === "string" ? (
          <Chip size="small" variant="outlined" label={`model: ${meta.model}`} />
        ) : null}
        {typeof runId === "string" && runId ? (
          <Chip
            size="small"
            variant="outlined"
            label={`run: ${runId}`}
            component={Link}
            href={`/systems?system=${encodeURIComponent(system)}&runId=${encodeURIComponent(runId)}`}
            clickable
          />
        ) : null}
        {trace?.duration_ms != null ? (
          <Chip size="small" variant="outlined" label={`latency: ${fmtDuration(trace.duration_ms)}`} />
        ) : null}
        {processedTokens > 0 ? (
          <Chip
            size="small"
            variant="outlined"
            label={`processed: ${processedTokens.toLocaleString()} tok`}
            title={`Processed input ${processedInputTokens.toLocaleString()} + generated output ${generatedOutputTokens.toLocaleString()}`}
          />
        ) : null}
        {cost ? (
          <Chip
            size="small"
            color="success"
            variant="outlined"
            label={`cost: ${fmtUsd(cost.total)}`}
            title={
              `Full-price input ${fmtUsd(cost.fullInput)} + ` +
              `cached input ${fmtUsd(cost.cachedInput)} + ` +
              `output ${fmtUsd(cost.output)}  ·  ` +
              `${typeof meta.model === "string" ? meta.model : "?"} list price`
            }
          />
        ) : null}
        {latestBudgetStats?.context_tokens != null &&
        latestBudgetStats.context_budget_tokens != null ? (
          <Chip
            size="small"
            color="secondary"
            variant="outlined"
            label={`context: ${latestBudgetStats.context_tokens.toLocaleString()} / ${latestBudgetStats.context_budget_tokens.toLocaleString()}`}
          />
        ) : null}
        {latestBudgetStats?.peak_context_tokens != null &&
        latestBudgetStats.peak_context_tokens !== latestBudgetStats.context_tokens ? (
          <Chip
            size="small"
            color="secondary"
            variant="outlined"
            label={`peak context: ${latestBudgetStats.peak_context_tokens.toLocaleString()}`}
          />
        ) : null}
        {Object.entries(counts).map(([tool, n]) => (
          <Chip key={tool} size="small" variant="outlined" label={`${tool}: ${n}`} />
        ))}
        {trace ? (
          <Chip
            size="small"
            variant="outlined"
            label={`retrieved docids: ${trace.summary?.retrieved_docids?.length ?? 0}`}
          />
        ) : (
          <Chip size="small" variant="outlined" color="warning" label="no output trace" />
        )}
        <Chip size="small" variant="outlined" label={`steps: ${steps.length}`} />
      </Stack>

      {/* timeline — always visible, never behind a tab */}
      <Box sx={{ mb: 1.5 }}>
        <Timeline steps={steps} trace={trace} selected={selection} onSelect={select} />
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
              ? "300px minmax(0, 1fr) minmax(280px, 360px)"
              : "340px minmax(0, 1fr)",
            xl: doc
              ? "360px minmax(0, 1fr) minmax(300px, 400px)"
              : "380px minmax(0, 1fr)",
          },
        }}
      >
        <StepTree
          steps={steps}
          traceInput={trace?.input}
          answerSummary={answerSummary}
          selected={selection}
          onSelect={select}
        />
        <DetailPane
          selection={selection}
          dtab={dtab}
          onDtabChange={setDtab}
          steps={steps}
          trace={trace}
          output={data.output}
          system={system}
          sessionId={sessionId}
          activeDoc={doc}
          onOpenDoc={openDoc}
        />
        {doc ? (
          <DocSidebar
            docid={doc}
            source={docSources.get(doc)}
            system={system}
            sessionId={sessionId}
            onClose={closeDoc}
          />
        ) : null}
      </Box>
    </Box>
  );
}
