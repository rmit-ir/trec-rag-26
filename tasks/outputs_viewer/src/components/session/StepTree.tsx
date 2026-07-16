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
import InputIcon from "@mui/icons-material/Input";
import CheckCircleOutlineIcon from "@mui/icons-material/CheckCircleOutline";
import ErrorOutlineIcon from "@mui/icons-material/ErrorOutline";
import Chip from "@mui/material/Chip";
import type { TraceStep } from "@/lib/types";
import { fmtDuration, stepDurationMs } from "@/lib/gantt";
import {
  StepIcon,
  stepKind,
  stepSummary,
  useStepColor,
  type NodeSelection,
} from "./stepMeta";

/**
 * PostHog-style trace tree:
 *
 * Input
 *   Generation turn
 *     Tool calls issued by that generation
 *   Generation turn
 *     Tool calls issued by that generation
 * Answer
 */
export default function StepTree({
  steps,
  traceInput,
  answerSummary,
  selected,
  onSelect,
}: {
  steps: TraceStep[];
  traceInput?: unknown;
  answerSummary: string;
  selected: NodeSelection;
  onSelect: (sel: NodeSelection) => void;
}) {
  const colorOf = useStepColor();
  const [filter, setFilter] = React.useState("");
  const q = filter.trim().toLowerCase();

  const matches = React.useCallback(
    (step: TraceStep): boolean => {
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
  const visibleIndices = new Set(visible.map(({ i }) => i));
  const generationByTurn = new Map<number, { step: TraceStep; i: number }>();
  for (const item of visible) {
    if (item.step.type === "generation" && typeof item.step.turn === "number") {
      generationByTurn.set(item.step.turn, item);
    }
  }
  const groupedIndices = new Set<number>();
  const groups = [...generationByTurn.entries()]
    .sort(([a], [b]) => a - b)
    .map(([turn, generation]) => {
    groupedIndices.add(generation.i);
    const children = visible.filter(({ step, i }) => {
      if (i === generation.i) return false;
      return Boolean(generation.step.id && step.parent_id === generation.step.id);
    });
    children.forEach(({ i }) => groupedIndices.add(i));
    return { turn, generation, children };
  });
  const ungrouped = visible.filter(({ i }) => !groupedIndices.has(i));
  const answerVisible = !q || `answer ${answerSummary}`.toLowerCase().includes(q);
  const inputText = JSON.stringify(traceInput ?? "").toLowerCase();
  const inputVisible = !q || `input ${inputText}`.includes(q);

  const stepRow = (
    step: TraceStep,
    i: number,
    {
      indent = 0,
      generation = false,
    }: { indent?: number; generation?: boolean } = {},
  ) => (
    <ListItemButton
      key={i}
      selected={selected === i}
      onClick={() => onSelect(i)}
      sx={{
        alignItems: "flex-start",
        py: generation ? 0.65 : 0.45,
        pl: 1 + indent * 2.25,
        ml: indent ? 2.25 : 0,
        borderLeft: indent ? 1 : 0,
        borderColor: "divider",
      }}
    >
      <Box
        sx={{
          width: generation ? 22 : 20,
          height: generation ? 22 : 20,
          borderRadius: "50%",
          display: "grid",
          placeItems: "center",
          color: "#fff",
          bgcolor: colorOf(step),
          flexShrink: 0,
          mr: 1,
          mt: 0.35,
          p: "2px",
          boxSizing: "border-box",
          fontSize: 12,
        }}
      >
        <StepIcon step={step} fontSize="inherit" />
      </Box>
      <ListItemText
        primary={
          <Typography variant="body2" sx={{ fontWeight: generation ? 700 : 600, display: "flex", alignItems: "center", gap: 0.5 }}>
            {generation && typeof step.turn === "number"
              ? `Turn ${step.turn + 1} · generation`
              : `${i + 1}. ${stepKind(step)}`}
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
  );

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
        {inputVisible ? (
          <ListItemButton
            selected={selected === "input"}
            onClick={() => onSelect("input")}
            sx={{ alignItems: "flex-start", py: 0.65 }}
          >
            <InputIcon color="primary" sx={{ fontSize: 20, mr: 1, mt: 0.3, flexShrink: 0 }} />
            <ListItemText
              primary={
                <Typography variant="body2" sx={{ fontWeight: 700 }}>
                  Input
                </Typography>
              }
              secondary={
                <Typography variant="caption" color="text.secondary">
                  System prompt, user request, and available tools
                </Typography>
              }
            />
          </ListItemButton>
        ) : null}
        {groups.map(({ turn, generation, children }) => (
          <React.Fragment key={`turn-${turn}`}>
            {stepRow(generation.step, generation.i, { generation: true })}
            {children.map(({ step, i }) => stepRow(step, i, { indent: 1 }))}
          </React.Fragment>
        ))}
        {ungrouped.map(({ step, i }) => stepRow(step, i))}
        {visibleIndices.size === 0 && !inputVisible && !answerVisible ? (
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
