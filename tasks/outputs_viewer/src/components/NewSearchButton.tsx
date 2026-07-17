"use client";
import * as React from "react";
import useSWR from "swr";
import Button from "@mui/material/Button";
import Dialog from "@mui/material/Dialog";
import DialogTitle from "@mui/material/DialogTitle";
import DialogContent from "@mui/material/DialogContent";
import DialogContentText from "@mui/material/DialogContentText";
import DialogActions from "@mui/material/DialogActions";
import TextField from "@mui/material/TextField";
import Alert from "@mui/material/Alert";
import Snackbar from "@mui/material/Snackbar";
import Chip from "@mui/material/Chip";
import Stack from "@mui/material/Stack";
import Tooltip from "@mui/material/Tooltip";
import CircularProgress from "@mui/material/CircularProgress";
import AddIcon from "@mui/icons-material/Add";
import { fetcher, postJson } from "@/lib/client/api";
import type { RunRecord } from "@/lib/types";

interface RunsResponse {
  running: RunRecord[];
  recent: RunRecord[];
}

/** Elapsed seconds, rendered as m:ss. */
function elapsed(startedAt: number, now: number): string {
  const s = Math.max(0, Math.round((now - startedAt) / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/**
 * "New search" control: starts an aus_agent run from a free-text query.
 *
 * The POST returns as soon as the child is spawned; progress is reflected by
 * polling /api/runs, and the run's artifact shows up in the sessions list on
 * its own (the outputs index already polls and renders trace.status).
 */
export default function NewSearchButton({ onStarted }: { onStarted?: () => void }) {
  const [open, setOpen] = React.useState(false);
  const [query, setQuery] = React.useState("");
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [toast, setToast] = React.useState<{ severity: "info" | "warning"; msg: string } | null>(
    null,
  );
  const [now, setNow] = React.useState(() => Date.now());

  const { data, mutate } = useSWR<RunsResponse>("/api/runs", fetcher, {
    refreshInterval: 5_000,
  });
  const running = data?.running ?? [];

  // Local ticker so the elapsed chip advances between polls.
  React.useEffect(() => {
    if (running.length === 0) return;
    const t = setInterval(() => setNow(Date.now()), 1_000);
    return () => clearInterval(t);
  }, [running.length]);

  // Surface each newly-finished run once. Seeding the ref on first load stops
  // history that predates this mount from toasting on arrival.
  const lastFinished = data?.recent?.[0];
  const seenFinishedId = React.useRef<string | null | undefined>(undefined);
  React.useEffect(() => {
    if (!data) return;
    const id = lastFinished?.id ?? null;
    if (seenFinishedId.current === undefined) {
      seenFinishedId.current = id; // first poll: adopt, don't announce
      return;
    }
    if (id === seenFinishedId.current) return;
    seenFinishedId.current = id;
    if (lastFinished && lastFinished.status !== "completed") {
      setToast({
        severity: "warning",
        msg: `Run ${lastFinished.status}${lastFinished.error ? `: ${lastFinished.error}` : ""}`,
      });
    }
  }, [data, lastFinished]);

  async function submit() {
    const q = query.trim();
    if (!q) return;
    setSubmitting(true);
    setError(null);
    try {
      await postJson<{ record: RunRecord }>("/api/runs", { query: q });
      setToast({ severity: "info", msg: "Run queued — it will appear in the list shortly." });
      setQuery("");
      setOpen(false);
      await mutate();
      onStarted?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <>
      <Stack direction="row" spacing={1} alignItems="center">
        {running.map((r) => (
          <Tooltip key={r.id} title={r.query}>
            <Chip
              size="small"
              variant="outlined"
              color="info"
              icon={<CircularProgress size={10} sx={{ ml: 1 }} />}
              label={`running ${elapsed(r.startedAt, now)}`}
              sx={{ height: 22 }}
            />
          </Tooltip>
        ))}
        <Button
          size="small"
          variant="outlined"
          startIcon={<AddIcon />}
          onClick={() => {
            setError(null);
            setOpen(true);
          }}
        >
          New search
        </Button>
      </Stack>

      <Dialog open={open} onClose={() => (submitting ? null : setOpen(false))} fullWidth maxWidth="sm">
        <DialogTitle>New search</DialogTitle>
        <DialogContent>
          <DialogContentText variant="body2" sx={{ mb: 2 }}>
            Starts a new <strong>aus_agent</strong> run. The run appears in the sessions list
            while it works and is stopped automatically after 10 minutes.
          </DialogContentText>
          <TextField
            autoFocus
            fullWidth
            multiline
            minRows={3}
            label="Research query"
            placeholder="How effective are influenza vaccines?"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) void submit();
            }}
            disabled={submitting}
            helperText="⌘/Ctrl + Enter to start"
          />
          {error ? (
            <Alert severity="error" sx={{ mt: 2 }}>
              {error}
            </Alert>
          ) : null}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setOpen(false)} disabled={submitting} color="inherit">
            Cancel
          </Button>
          <Button
            onClick={() => void submit()}
            disabled={submitting || query.trim().length === 0}
            variant="contained"
            startIcon={submitting ? <CircularProgress size={14} color="inherit" /> : null}
          >
            {submitting ? "Starting…" : "Start run"}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Floating, so run feedback never distorts the header row it sits in. */}
      <Snackbar
        open={toast !== null}
        autoHideDuration={toast?.severity === "warning" ? 12_000 : 5_000}
        onClose={() => setToast(null)}
        anchorOrigin={{ vertical: "bottom", horizontal: "center" }}
      >
        {toast ? (
          <Alert severity={toast.severity} variant="filled" onClose={() => setToast(null)}>
            {toast.msg}
          </Alert>
        ) : undefined}
      </Snackbar>
    </>
  );
}
