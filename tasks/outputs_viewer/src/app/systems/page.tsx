"use client";
import * as React from "react";
import useSWR from "swr";
import Link from "next/link";
import Box from "@mui/material/Box";
import Paper from "@mui/material/Paper";
import Typography from "@mui/material/Typography";
import List from "@mui/material/List";
import ListItemButton from "@mui/material/ListItemButton";
import ListItemText from "@mui/material/ListItemText";
import Chip from "@mui/material/Chip";
import Skeleton from "@mui/material/Skeleton";
import Alert from "@mui/material/Alert";
import Stack from "@mui/material/Stack";
import StorageIcon from "@mui/icons-material/Storage";
import { fetcher } from "@/lib/client/api";
import { useUrlState } from "@/lib/client/urlState";
import type { OutputsIndex, SessionHeader } from "@/lib/types";
import { Suspense } from "react";

function statusColor(status?: string): "success" | "warning" | "default" {
  if (status === "completed") return "success";
  if (status === "budget_exhausted") return "warning";
  return "default";
}

function fmtTs(ts: string): string {
  // 20260716T070136240796Z → 2026-07-16 07:01:36
  const m = /^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})/.exec(ts);
  if (!m) return ts;
  return `${m[1]}-${m[2]}-${m[3]} ${m[4]}:${m[5]}:${m[6]}`;
}

function SessionRow({ s }: { s: SessionHeader }) {
  return (
    <ListItemButton
      component={Link}
      href={`/session/${encodeURIComponent(s.system)}/${encodeURIComponent(s.sessionId)}`}
      sx={{ alignItems: "flex-start", borderBottom: 1, borderColor: "divider" }}
    >
      <ListItemText
        primary={
          <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
            <Typography variant="subtitle2">{s.narrativeSnippet ?? s.slug}</Typography>
            {s.status ? (
              <Chip size="small" label={s.status} color={statusColor(s.status)} variant="outlined" sx={{ height: 18 }} />
            ) : null}
          </Stack>
        }
        secondary={
          <Typography variant="caption" color="text.secondary" component="span">
            {fmtTs(s.ts)}
            {s.model ? ` · ${s.model}` : ""}
            {s.runId ? ` · ${s.runId}` : ""}
            {!s.hasTrajectory ? " · no trajectory" : ""}
          </Typography>
        }
      />
    </ListItemButton>
  );
}

function SystemsBrowser() {
  const { data, error, isLoading } = useSWR<OutputsIndex>("/api/outputs", fetcher, {
    refreshInterval: 30_000,
  });
  const { get, set } = useUrlState();
  const selected = get("system") ?? data?.systems[0]?.system ?? null;

  if (error) return <Alert severity="error">Failed to load outputs index: {String(error.message)}</Alert>;

  const sessions = (data?.sessions ?? []).filter((s) => s.system === selected);

  return (
    <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", md: "260px 1fr" }, gap: 2 }}>
      <Paper variant="outlined">
        <Typography variant="overline" sx={{ px: 2, pt: 1.5, display: "block", color: "text.secondary" }}>
          Systems
        </Typography>
        {isLoading ? (
          <Box sx={{ p: 2 }}>
            <Skeleton /> <Skeleton /> <Skeleton />
          </Box>
        ) : (
          <List dense disablePadding>
            {data?.systems.map((sys) => (
              <ListItemButton
                key={sys.system}
                selected={sys.system === selected}
                onClick={() => set("system", sys.system)}
              >
                <StorageIcon fontSize="small" sx={{ mr: 1, color: "text.disabled" }} />
                <ListItemText primary={sys.system} />
                <Chip size="small" label={sys.sessionCount} sx={{ height: 18 }} />
              </ListItemButton>
            ))}
          </List>
        )}
      </Paper>
      <Paper variant="outlined">
        <Typography variant="overline" sx={{ px: 2, pt: 1.5, display: "block", color: "text.secondary" }}>
          {selected ?? "Sessions"} — {sessions.length} session{sessions.length === 1 ? "" : "s"}
        </Typography>
        {isLoading ? (
          <Box sx={{ p: 2 }}>
            <Skeleton height={44} /> <Skeleton height={44} />
          </Box>
        ) : sessions.length === 0 ? (
          <Typography sx={{ p: 2 }} color="text.secondary">
            No sessions in this system yet.
          </Typography>
        ) : (
          <List dense disablePadding>
            {sessions.map((s) => (
              <SessionRow key={`${s.system}/${s.sessionId}`} s={s} />
            ))}
          </List>
        )}
      </Paper>
    </Box>
  );
}

export default function SystemsPage() {
  return (
    <Suspense>
      <SystemsBrowser />
    </Suspense>
  );
}
