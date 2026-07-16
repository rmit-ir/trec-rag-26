"use client";
import * as React from "react";
import Box from "@mui/material/Box";
import Paper from "@mui/material/Paper";
import List from "@mui/material/List";
import ListItemButton from "@mui/material/ListItemButton";
import ListItemText from "@mui/material/ListItemText";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import InputAdornment from "@mui/material/InputAdornment";
import Divider from "@mui/material/Divider";
import SearchIcon from "@mui/icons-material/Search";
import CheckCircleOutlineIcon from "@mui/icons-material/CheckCircleOutline";
import ErrorOutlineIcon from "@mui/icons-material/ErrorOutline";
import Chip from "@mui/material/Chip";
import type { TrajectoryStep } from "@/lib/types";
import { fmtDuration, stepDurationMs } from "@/lib/gantt";
import {
  StepIcon,
  stepKind,
  stepSummary,
  useStepColor,
  type NodeSelection,
} from "./stepMeta";

/**
 * PostHog-trace-style step list ("tree"): one row per trajectory step plus a
 * distinct terminal Answer node. A small filter box narrows rows by text
 * (kind, summary, arguments, output). Clicking selects.
 */
export default function StepTree({
  steps,
  answerSummary,
  selected,
  onSelect,
}: {
  steps: TrajectoryStep[];
  answerSummary: string;
  selected: NodeSelection;
  onSelect: (sel: NodeSelection) => void;
}) {
  const colorOf = useStepColor();
  const [filter, setFilter] = React.useState("");
  const q = filter.trim().toLowerCase();

  const matches = React.useCallback(
    (step: TrajectoryStep): boolean => {
      if (!q) return true;
      const hay = [
        stepKind(step),
        stepSummary(step),
        typeof step.arguments === "string" ? step.arguments : JSON.stringify(step.arguments ?? ""),
        typeof step.output === "string" ? step.output : "",
      ]
        .join(" ")
        .toLowerCase();
      return hay.includes(q);
    },
    [q],
  );

  const visible = steps
    .map((step, i) => ({ step, i }))
    .filter(({ step }) => matches(step));
  const answerVisible = !q || `answer ${answerSummary}`.toLowerCase().includes(q);

  return (
    <Paper
      variant="outlined"
      sx={{
        display: "flex",
        flexDirection: "column",
        maxHeight: { md: "calc(100vh - 260px)" },
        minHeight: 200,
        overflow: "hidden",
      }}
    >
      <Box sx={{ p: 1, pb: 0.5 }}>
        <TextField
          fullWidth
          size="small"
          placeholder="Search trace…"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          slotProps={{
            input: {
              startAdornment: (
                <InputAdornment position="start">
                  <SearchIcon fontSize="small" />
                </InputAdornment>
              ),
            },
          }}
        />
      </Box>
      <List dense disablePadding sx={{ overflowY: "auto", flexGrow: 1 }}>
        {visible.map(({ step, i }) => (
          <ListItemButton
            key={i}
            selected={selected === i}
            onClick={() => onSelect(i)}
            sx={{ alignItems: "flex-start", py: 0.5 }}
          >
            <Box
              sx={{
                width: 20,
                height: 20,
                borderRadius: "50%",
                display: "grid",
                placeItems: "center",
                color: "#fff",
                bgcolor: colorOf(step),
                flexShrink: 0,
                mr: 1,
                mt: 0.4,
                fontSize: 12,
              }}
            >
              <StepIcon step={step} fontSize="inherit" />
            </Box>
            <ListItemText
              primary={
                <Typography variant="body2" sx={{ fontWeight: 600, display: "flex", alignItems: "center", gap: 0.5 }}>
                  {i + 1}. {stepKind(step)}
                  {step.failed ? <ErrorOutlineIcon color="error" sx={{ fontSize: 14 }} /> : null}
                  {(() => {
                    const d = stepDurationMs(step);
                    return d != null ? (
                      <Chip
                        size="small"
                        variant="outlined"
                        label={fmtDuration(d)}
                        sx={{ height: 16, fontSize: "0.62rem", ml: "auto" }}
                      />
                    ) : null;
                  })()}
                </Typography>
              }
              secondary={
                <Typography
                  variant="caption"
                  color="text.secondary"
                  sx={{
                    display: "block",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {stepSummary(step)}
                </Typography>
              }
            />
          </ListItemButton>
        ))}
        {visible.length === 0 && !answerVisible ? (
          <Typography variant="caption" color="text.secondary" sx={{ p: 2, display: "block" }}>
            No steps match “{filter}”.
          </Typography>
        ) : null}
        {answerVisible ? (
          <>
            <Divider />
            <ListItemButton
              selected={selected === "answer"}
              onClick={() => onSelect("answer")}
              sx={{
                alignItems: "flex-start",
                py: 0.75,
                borderLeft: 3,
                borderColor: selected === "answer" ? "primary.main" : "transparent",
                bgcolor: selected === "answer" ? undefined : "action.hover",
              }}
            >
              <CheckCircleOutlineIcon
                color="primary"
                sx={{ fontSize: 20, mr: 1, mt: 0.3, flexShrink: 0 }}
              />
              <ListItemText
                primary={
                  <Typography variant="body2" sx={{ fontWeight: 700 }}>
                    Answer
                  </Typography>
                }
                secondary={
                  <Typography
                    variant="caption"
                    color="text.secondary"
                    sx={{
                      display: "block",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {answerSummary}
                  </Typography>
                }
              />
            </ListItemButton>
          </>
        ) : null}
      </List>
    </Paper>
  );
}
