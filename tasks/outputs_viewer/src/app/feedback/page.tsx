"use client";
import * as React from "react";
import { Suspense } from "react";
import useSWR from "swr";
import Link from "next/link";
import Box from "@mui/material/Box";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Typography from "@mui/material/Typography";
import Stack from "@mui/material/Stack";
import Chip from "@mui/material/Chip";
import ToggleButton from "@mui/material/ToggleButton";
import ToggleButtonGroup from "@mui/material/ToggleButtonGroup";
import MenuItem from "@mui/material/MenuItem";
import TextField from "@mui/material/TextField";
import Skeleton from "@mui/material/Skeleton";
import Alert from "@mui/material/Alert";
import Button from "@mui/material/Button";
import ThumbUpIcon from "@mui/icons-material/ThumbUp";
import ThumbDownIcon from "@mui/icons-material/ThumbDown";
import HorizontalRuleIcon from "@mui/icons-material/HorizontalRule";
import OpenInNewIcon from "@mui/icons-material/OpenInNew";
import { fetcher } from "@/lib/client/api";
import { fmtMelbourne } from "@/lib/time";
import { useIdentity } from "@/lib/client/identity";
import { useUrlState } from "@/lib/client/urlState";
import type { FeedbackRecord } from "@/lib/types";

function targetLabel(r: FeedbackRecord): string {
  if (r.target.type === "sentence") return `sentence ${(r.target.sentenceIndex ?? 0) + 1}`;
  if (r.target.type === "citation") return `citation ${r.target.docid}`;
  return "full answer";
}

function sessionHref(r: FeedbackRecord): string {
  const base = `/session/${encodeURIComponent(r.system)}/${encodeURIComponent(r.sessionId)}`;
  return r.target.type === "citation" && r.target.docid
    ? `${base}?doc=${encodeURIComponent(r.target.docid)}`
    : base;
}

function RatingIcon({ rating }: { rating: FeedbackRecord["rating"] }) {
  if (rating === "up") return <ThumbUpIcon fontSize="small" color="primary" />;
  if (rating === "down") return <ThumbDownIcon fontSize="small" color="error" />;
  return <HorizontalRuleIcon fontSize="small" color="disabled" />;
}

/**
 * Feedback browser. URL state: ?who=me|all (default me), ?user=<name> (when
 * who=all, optional user filter), ?system=, ?type=. Username itself is never
 * in the URL — "me" resolves from localStorage.
 */
function FeedbackList() {
  const { user } = useIdentity();
  const { get, setMany } = useUrlState();
  const who = get("who") === "all" ? "all" : "me";
  const userFilter = get("user"); // only meaningful for who=all
  const systemFilter = get("system");
  const typeFilter = get("type");

  const { data, error, isLoading } = useSWR<{ records: FeedbackRecord[] }>(
    "/api/feedback",
    fetcher,
  );

  const records = React.useMemo(() => {
    let recs = data?.records ?? [];
    if (who === "me") recs = recs.filter((r) => r.user === user);
    else if (userFilter) recs = recs.filter((r) => r.user === userFilter);
    if (systemFilter) recs = recs.filter((r) => r.system === systemFilter);
    if (typeFilter) recs = recs.filter((r) => r.target.type === typeFilter);
    return recs;
  }, [data, who, user, userFilter, systemFilter, typeFilter]);

  const allUsers = React.useMemo(
    () => [...new Set((data?.records ?? []).map((r) => r.user))].sort(),
    [data],
  );
  const allSystems = React.useMemo(
    () => [...new Set((data?.records ?? []).map((r) => r.system))].sort(),
    [data],
  );

  if (error) return <Alert severity="error">Failed to load feedback: {String(error.message)}</Alert>;

  return (
    <Box>
      <Stack direction="row" spacing={1.5} sx={{ mb: 2 }} flexWrap="wrap" useFlexGap alignItems="center">
        <ToggleButtonGroup
          size="small"
          exclusive
          value={who}
          onChange={(_e, v) => v && setMany({ who: v === "me" ? null : v, user: null })}
        >
          <ToggleButton value="me">My feedback</ToggleButton>
          <ToggleButton value="all">Everyone</ToggleButton>
        </ToggleButtonGroup>
        {who === "all" ? (
          <TextField
            select
            size="small"
            label="User"
            value={userFilter ?? ""}
            onChange={(e) => setMany({ user: e.target.value || null })}
            sx={{ minWidth: 140 }}
          >
            <MenuItem value="">all users</MenuItem>
            {allUsers.map((u) => (
              <MenuItem key={u} value={u}>
                {u}
              </MenuItem>
            ))}
          </TextField>
        ) : null}
        <TextField
          select
          size="small"
          label="System"
          value={systemFilter ?? ""}
          onChange={(e) => setMany({ system: e.target.value || null })}
          sx={{ minWidth: 160 }}
        >
          <MenuItem value="">all systems</MenuItem>
          {allSystems.map((s) => (
            <MenuItem key={s} value={s}>
              {s}
            </MenuItem>
          ))}
        </TextField>
        <TextField
          select
          size="small"
          label="Target"
          value={typeFilter ?? ""}
          onChange={(e) => setMany({ type: e.target.value || null })}
          sx={{ minWidth: 140 }}
        >
          <MenuItem value="">all targets</MenuItem>
          <MenuItem value="answer">answer</MenuItem>
          <MenuItem value="sentence">sentence</MenuItem>
          <MenuItem value="citation">citation</MenuItem>
        </TextField>
        <Typography variant="body2" color="text.secondary">
          {records.length} record{records.length === 1 ? "" : "s"} (latest per target)
        </Typography>
      </Stack>

      {isLoading ? (
        <>
          <Skeleton height={70} />
          <Skeleton height={70} />
        </>
      ) : records.length === 0 ? (
        <Typography color="text.secondary" sx={{ p: 2 }}>
          No feedback yet{who === "me" ? " from you" : ""}. Open a session and start judging.
        </Typography>
      ) : (
        <Stack spacing={1}>
          {records.map((r) => (
            <Card key={r.id}>
              <CardContent sx={{ py: 1.25, "&:last-child": { pb: 1.25 } }}>
                <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
                  <RatingIcon rating={r.rating} />
                  <Chip size="small" variant="outlined" label={r.system} />
                  <Chip size="small" variant="outlined" label={targetLabel(r)} sx={{ fontFamily: r.target.type === "citation" ? "monospace" : undefined }} />
                  {who === "all" ? <Chip size="small" label={r.user} color="secondary" variant="outlined" /> : null}
                  <Typography variant="caption" color="text.secondary" sx={{ flexGrow: 1 }}>
                    {fmtMelbourne(r.createdAt)} · {r.sessionId}
                  </Typography>
                  <Button
                    component={Link}
                    href={sessionHref(r)}
                    size="small"
                    endIcon={<OpenInNewIcon />}
                  >
                    Open session
                  </Button>
                </Stack>
                {r.comment ? (
                  <Typography variant="body2" sx={{ mt: 0.75 }}>
                    {r.comment}
                  </Typography>
                ) : null}
                {r.tags.length > 0 ? (
                  <Box sx={{ display: "flex", gap: 0.5, mt: 0.75, flexWrap: "wrap" }}>
                    {r.tags.map((t) => (
                      <Chip key={t} size="small" label={t} sx={{ height: 20 }} />
                    ))}
                  </Box>
                ) : null}
              </CardContent>
            </Card>
          ))}
        </Stack>
      )}
    </Box>
  );
}

export default function FeedbackPage() {
  return (
    <Suspense>
      <FeedbackList />
    </Suspense>
  );
}
