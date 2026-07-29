"use client";
import * as React from "react";
import useSWR from "swr";
import Box from "@mui/material/Box";
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
 * Persistent right-hand document column. Fetches the retrieval unit by id,
 * AS-IS, via `/api/doc/{id}` — a chunk id yields that chunk (dense and sparse
 * both return page/chunk ids now), so there is no per-backend id parsing and
 * no separate "full document" view. Shows docid, kind (document/chunk), and
 * which docstore served the text. Stays open across citation clicks; the close
 * button clears the ?doc= param.
 */
export default function DocSidebar({
  docid,
  system,
  sessionId,
  onClose,
}: {
  docid: string;
  system: string;
  sessionId: string;
  onClose: () => void;
}) {
  const { data, error, isLoading } = useSWR<DocResult>(
    `/api/doc/${encodeURIComponent(docid)}`,
    fetcher,
  );

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
      <Box sx={{ p: 1.5, overflowY: "auto", flexGrow: 1, borderTop: 1, borderColor: "divider" }}>
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
