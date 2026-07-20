"use client";
import * as React from "react";
import useSWR from "swr";
import Box from "@mui/material/Box";
import Tabs from "@mui/material/Tabs";
import Tab from "@mui/material/Tab";
import Paper from "@mui/material/Paper";
import Typography from "@mui/material/Typography";
import IconButton from "@mui/material/IconButton";
import Chip from "@mui/material/Chip";
import Stack from "@mui/material/Stack";
import Skeleton from "@mui/material/Skeleton";
import Alert from "@mui/material/Alert";
import Tooltip from "@mui/material/Tooltip";
import CloseIcon from "@mui/icons-material/Close";
import ArticleOutlinedIcon from "@mui/icons-material/ArticleOutlined";
import { fetcher } from "@/lib/client/api";
import type { DocResult } from "@/lib/types";
import FeedbackWidget from "@/components/FeedbackWidget";

/**
 * Persistent right-hand document column. Shows docid, kind (document/chunk),
 * and which backend served the text (dense endpoint vs Pyserini; chunk ids
 * that fell back to the parent doc are flagged). Stays open across citation
 * clicks; the close button clears the ?doc= param.
 */
export default function DocSidebar({
  docid,
  source,
  system,
  sessionId,
  onClose,
}: {
  docid: string;
  /** engine that surfaced this doc in the trace — fetch from the same side */
  source?: "sparse" | "dense";
  system: string;
  sessionId: string;
  onClose: () => void;
}) {
  const [view, setView] = React.useState<"retrieved" | "full">("retrieved");
  // A new docid resets to the retrieved unit.
  React.useEffect(() => setView("retrieved"), [docid]);

  const retrieved = useSWR<DocResult>(
    `/api/doc/${encodeURIComponent(docid)}${source ? `?source=${source}` : ""}`,
    fetcher,
  );
  // Full parent document via the sparse (Pyserini) full-doc API; only
  // fetched once the tab is opened.
  const full = useSWR<DocResult>(
    view === "full" ? `/api/doc/${encodeURIComponent(docid)}?full=1` : null,
    fetcher,
  );
  const { data, error, isLoading } = view === "full" ? full : retrieved;

  return (
    <Paper
      variant="outlined"
      sx={{
        position: "sticky",
        top: 64,
        maxHeight: "calc(100vh - 88px)",
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
      }}
    >
      <Box sx={{ p: 1.5, pb: 1 }}>
        <Stack direction="row" alignItems="center" spacing={1}>
          <ArticleOutlinedIcon fontSize="small" color="primary" />
          <Typography
            variant="subtitle2"
            sx={{ fontFamily: "monospace", flexGrow: 1, wordBreak: "break-all" }}
          >
            {docid}
          </Typography>
          <Tooltip title="Close document panel">
            <IconButton size="small" onClick={onClose}>
              <CloseIcon fontSize="small" />
            </IconButton>
          </Tooltip>
        </Stack>
        {data ? (
          <Stack direction="row" spacing={0.5} sx={{ mt: 0.75 }} flexWrap="wrap" useFlexGap>
            <Chip size="small" variant="outlined" label={data.kind} sx={{ height: 18 }} />
            <Chip
              size="small"
              variant="outlined"
              color="primary"
              label={`source: ${data.source}`}
              sx={{ height: 18 }}
            />
            {data.parentFallback ? (
              <Tooltip title={`Chunk id not addressable directly — showing parent document ${data.resolvedId}`}>
                <Chip size="small" color="warning" variant="outlined" label={`parent doc: ${data.resolvedId}`} sx={{ height: 18 }} />
              </Tooltip>
            ) : null}
          </Stack>
        ) : null}
        <Box sx={{ mt: 0.75 }}>
          <FeedbackWidget
            system={system}
            sessionId={sessionId}
            target={{ type: "citation", docid }}
            label="Rate this citation"
          />
        </Box>
      </Box>
      <Tabs
        value={view}
        onChange={(_e, v) => setView(v)}
        variant="scrollable"
        scrollButtons="auto"
        allowScrollButtonsMobile
        sx={{ px: 1, minHeight: 32, borderBottom: 1, borderColor: "divider" }}
      >
        <Tab
          value="retrieved"
          label="Retrieved"
          sx={{ minHeight: 32, py: 0, textTransform: "none" }}
        />
        <Tab
          value="full"
          label="Full document"
          sx={{ minHeight: 32, py: 0, textTransform: "none" }}
        />
      </Tabs>
      <Box sx={{ p: 1.5, overflowY: "auto", flexGrow: 1 }}>
        {isLoading ? (
          <>
            <Skeleton /> <Skeleton /> <Skeleton /> <Skeleton width="70%" />
          </>
        ) : error ? (
          <Alert severity="error" variant="outlined">
            {String(error.message)}
          </Alert>
        ) : (
          <Typography
            variant="body2"
            component="pre"
            sx={{
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
              fontFamily: "inherit",
              m: 0,
            }}
          >
            {data?.text}
          </Typography>
        )}
      </Box>
    </Paper>
  );
}
