"use client";
import * as React from "react";
import { Suspense } from "react";
import useSWR from "swr";
import Box from "@mui/material/Box";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Typography from "@mui/material/Typography";
import Stack from "@mui/material/Stack";
import Skeleton from "@mui/material/Skeleton";
import Alert from "@mui/material/Alert";
import { BarChart } from "@mui/x-charts/BarChart";
import { useColorScheme } from "@mui/material/styles";
import { fetcher } from "@/lib/client/api";
import { aggregateBySystem, countBy, fmtPct, tallyRatings } from "@/lib/aggregate";
import { VIZ_DARK, VIZ_LIGHT } from "@/lib/palette";
import type { FeedbackRecord } from "@/lib/types";

/** Hero-number stat tile (dataviz: a single headline is not a chart). */
function StatTile({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <Card sx={{ flexGrow: 1, minWidth: 140 }}>
      <CardContent sx={{ py: 1.5, "&:last-child": { pb: 1.5 } }}>
        <Typography variant="overline" color="text.secondary" display="block">
          {label}
        </Typography>
        <Typography variant="h1" component="div">
          {value}
        </Typography>
        {hint ? (
          <Typography variant="caption" color="text.secondary">
            {hint}
          </Typography>
        ) : null}
      </CardContent>
    </Card>
  );
}

function ChartCard({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
}) {
  return (
    <Card>
      <CardContent sx={{ py: 1.5, "&:last-child": { pb: 1.5 } }}>
        <Typography variant="h5">{title}</Typography>
        {subtitle ? (
          <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
            {subtitle}
          </Typography>
        ) : null}
        <Box sx={{ overflowX: "auto" }}>{children}</Box>
      </CardContent>
    </Card>
  );
}

/**
 * Summary metrics + charts over latest-wins feedback.
 * Colors are the validated dataviz palette: blue/red diverging pair for the
 * up/down polarity, single blue hue for magnitude-only bars (no legend for
 * single series; legend + distinct hues for the two-series chart).
 */
function SummaryView() {
  const { data, error, isLoading } = useSWR<{ records: FeedbackRecord[] }>(
    "/api/feedback",
    fetcher,
  );
  const { mode, systemMode } = useColorScheme();
  const dark = (mode === "system" ? systemMode : mode) === "dark";
  const viz = dark ? VIZ_DARK : VIZ_LIGHT;

  const records = React.useMemo(() => data?.records ?? [], [data]);
  const bySystem = React.useMemo(() => aggregateBySystem(records), [records]);
  const overall = React.useMemo(() => tallyRatings(records), [records]);
  const tagFreq = React.useMemo(() => {
    const counts: Record<string, number> = {};
    for (const r of records) for (const t of r.tags) counts[t] = (counts[t] ?? 0) + 1;
    return Object.entries(counts).sort((a, b) => b[1] - a[1]);
  }, [records]);
  const byType = React.useMemo(
    () => countBy(records, (r) => r.target.type),
    [records],
  );
  const byUser = React.useMemo(
    () => Object.entries(countBy(records, (r) => r.user)).sort((a, b) => b[1] - a[1]),
    [records],
  );

  if (error) return <Alert severity="error">Failed to load feedback: {String(error.message)}</Alert>;
  if (isLoading) {
    return (
      <>
        <Skeleton height={90} />
        <Skeleton height={260} />
      </>
    );
  }
  if (records.length === 0) {
    return (
      <Typography color="text.secondary" sx={{ p: 2 }}>
        No feedback recorded yet — nothing to summarize.
      </Typography>
    );
  }

  const typeOrder = ["answer", "sentence", "citation"];

  return (
    <Stack spacing={2}>
      <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap>
        <StatTile label="Feedback records" value={String(records.length)} hint="latest per user × target" />
        <StatTile label="Judges" value={String(new Set(records.map((r) => r.user)).size)} />
        <StatTile
          label="Sessions covered"
          value={String(new Set(records.map((r) => `${r.system}/${r.sessionId}`)).size)}
        />
        <StatTile
          label="Overall thumbs-up"
          value={fmtPct(overall.pctUp)}
          hint={`${overall.up} up / ${overall.down} down`}
        />
      </Stack>

      <Box
        sx={{
          display: "grid",
          gap: 2,
          gridTemplateColumns: { xs: "1fr", lg: "1fr 1fr" },
          alignItems: "start",
        }}
      >
        <ChartCard
          title="Rating distribution per system"
          subtitle="thumbs up vs down, all target types"
        >
          <BarChart
            height={260}
            xAxis={[{ data: bySystem.map((s) => s.system), scaleType: "band" }]}
            yAxis={[{ label: "ratings", tickMinStep: 1 }]}
            series={[
              { data: bySystem.map((s) => s.answer.up + s.sentence.up + s.citation.up), label: "up", color: viz.up },
              { data: bySystem.map((s) => s.answer.down + s.sentence.down + s.citation.down), label: "down", color: viz.down },
            ]}
            borderRadius={4}
            grid={{ horizontal: true }}
            slotProps={{ legend: { position: { vertical: "top", horizontal: "end" } } }}
          />
        </ChartCard>

        <ChartCard title="Tag frequency" subtitle="times each tag was applied">
          <BarChart
            height={Math.max(220, tagFreq.length * 34 + 80)}
            layout="horizontal"
            yAxis={[{ data: tagFreq.map(([t]) => t), scaleType: "band", width: 140 }]}
            xAxis={[{ label: "count", tickMinStep: 1 }]}
            series={[{ data: tagFreq.map(([, n]) => n), color: viz.series[0] }]}
            borderRadius={4}
            grid={{ vertical: true }}
            hideLegend
          />
        </ChartCard>

        <ChartCard title="Feedback per target type" subtitle="answer vs sentence vs citation">
          <BarChart
            height={220}
            xAxis={[{ data: typeOrder, scaleType: "band" }]}
            yAxis={[{ label: "records", tickMinStep: 1 }]}
            series={[{ data: typeOrder.map((t) => byType[t] ?? 0), color: viz.series[0] }]}
            borderRadius={4}
            grid={{ horizontal: true }}
            hideLegend
          />
        </ChartCard>

        <ChartCard title="Feedback per judge" subtitle="records by user">
          <BarChart
            height={220}
            xAxis={[{ data: byUser.map(([u]) => u), scaleType: "band" }]}
            yAxis={[{ label: "records", tickMinStep: 1 }]}
            series={[{ data: byUser.map(([, n]) => n), color: viz.series[0] }]}
            borderRadius={4}
            grid={{ horizontal: true }}
            hideLegend
          />
        </ChartCard>
      </Box>
    </Stack>
  );
}

export default function SummaryPage() {
  return (
    <Suspense>
      <SummaryView />
    </Suspense>
  );
}
