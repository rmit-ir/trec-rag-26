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
import CircularProgress from "@mui/material/CircularProgress";
import StorageIcon from "@mui/icons-material/Storage";
import NewSearchButton from "@/components/NewSearchButton";
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

/** How many more rows each scroll-triggered append reveals. */
const PAGE_SIZE = 30;

/** Style objects are hoisted so a bailed-out row never rebuilds them. */
const rowSx = { alignItems: "flex-start", borderBottom: 1, borderColor: "divider" } as const;
const chipSx = { height: 18 } as const;

function SessionRowImpl({ s }: { s: SessionHeader }) {
  return (
    <ListItemButton
      component={Link}
      href={`/session/${encodeURIComponent(s.system)}/${encodeURIComponent(s.sessionId)}`}
      sx={rowSx}
    >
      <ListItemText
        primary={
          <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
            <Typography variant="subtitle2">{s.narrativeSnippet ?? s.slug}</Typography>
            {s.status ? (
              <Chip size="small" label={s.status} color={statusColor(s.status)} variant="outlined" sx={chipSx} />
            ) : null}
          </Stack>
        }
        secondary={
          <Typography variant="caption" color="text.secondary" component="span">
            {fmtTs(s.ts)}
            {s.model ? ` · ${s.model}` : ""}
            {s.runId ? ` · ${s.runId}` : ""}
            {!s.hasTrace ? " · no trace" : ""}
          </Typography>
        }
      />
    </ListItemButton>
  );
}

/**
 * Rows stay mounted once revealed (no virtualisation), so the list only stays
 * cheap if re-renders are kept off the rows already on screen. Two things would
 * otherwise re-render every row: SWR refetches on a 30s interval and hands back
 * freshly-parsed objects with new identities, and each scroll append rebuilds
 * the rendered slice. Comparing the fields actually rendered — rather than
 * relying on reference equality, which never holds after a refetch — lets every
 * unchanged row bail out, so an append costs only the rows it adds and a poll
 * costs only the rows whose content really moved (e.g. running -> completed).
 */
const SessionRow = React.memo(SessionRowImpl, (prev, next) => {
  const a = prev.s;
  const b = next.s;
  return (
    a.sessionId === b.sessionId &&
    a.system === b.system &&
    a.status === b.status &&
    a.ts === b.ts &&
    a.model === b.model &&
    a.runId === b.runId &&
    a.narrativeSnippet === b.narrativeSnippet &&
    a.slug === b.slug &&
    a.hasTrace === b.hasTrace
  );
});

function SystemsBrowser() {
  const { data, error, isLoading, mutate } = useSWR<OutputsIndex>("/api/outputs", fetcher, {
    refreshInterval: 30_000,
  });
  const { get, set } = useUrlState();
  const selected = get("system") ?? data?.systems[0]?.system ?? null;

  // Recomputed only when the payload or the system actually changes, so a
  // re-render for any other reason doesn't hand every row a new array.
  const sessions = React.useMemo(
    () => (data?.sessions ?? []).filter((s) => s.system === selected),
    [data?.sessions, selected],
  );

  const [visibleCount, setVisibleCount] = React.useState(PAGE_SIZE);
  const sentinelRef = React.useRef<HTMLDivElement | null>(null);
  const hasMore = visibleCount < sessions.length;

  // Switching systems shows a different list; start it from the top again.
  React.useEffect(() => {
    setVisibleCount(PAGE_SIZE);
  }, [selected]);

  React.useEffect(() => {
    if (!hasMore) return;
    const el = sentinelRef.current;
    if (!el) return;
    const io = new IntersectionObserver(
      (entries) => {
        // Functional update: the observer closes over nothing stale, so it
        // never needs re-creating as the count grows.
        if (entries[0]?.isIntersecting) setVisibleCount((n) => n + PAGE_SIZE);
      },
      // Reveal the next batch before the sentinel is actually on screen, so
      // scrolling doesn't stall at the bottom waiting for a render.
      { rootMargin: "600px" },
    );
    io.observe(el);
    return () => io.disconnect();
    // Re-attach when the sentinel remounts — it unmounts at the end of the
    // list, and reappears if a new run lands via the SWR poll.
  }, [hasMore]);

  const visibleSessions = React.useMemo(
    () => sessions.slice(0, visibleCount),
    [sessions, visibleCount],
  );

  if (error) return <Alert severity="error">Failed to load outputs index: {String(error.message)}</Alert>;

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
        <Stack
          direction="row"
          alignItems="center"
          justifyContent="space-between"
          sx={{ px: 2, pt: 1.5, pb: 0.5, gap: 1 }}
        >
          <Typography variant="overline" sx={{ color: "text.secondary" }}>
            {selected ?? "Sessions"} — {hasMore ? `${visibleCount} of ${sessions.length}` : sessions.length} session
            {sessions.length === 1 ? "" : "s"}
          </Typography>
          <NewSearchButton onStarted={() => void mutate()} />
        </Stack>
        {isLoading ? (
          <Box sx={{ p: 2 }}>
            <Skeleton height={44} /> <Skeleton height={44} />
          </Box>
        ) : sessions.length === 0 ? (
          <Typography sx={{ p: 2 }} color="text.secondary">
            No sessions in this system yet.
          </Typography>
        ) : (
          <>
            <List dense disablePadding>
              {visibleSessions.map((s) => (
                <SessionRow key={`${s.system}/${s.sessionId}`} s={s} />
              ))}
            </List>
            {hasMore ? (
              <Box
                ref={sentinelRef}
                sx={{ display: "flex", justifyContent: "center", py: 2, gap: 1 }}
              >
                <CircularProgress size={16} />
                <Typography variant="caption" color="text.secondary">
                  {sessions.length - visibleCount} more
                </Typography>
              </Box>
            ) : null}
          </>
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
