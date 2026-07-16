"use client";
import * as React from "react";
import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import CheckCircleOutlineIcon from "@mui/icons-material/CheckCircleOutline";
import { STEP_COLORS } from "@/lib/palette";
import type { TraceFile, TraceStep } from "@/lib/types";
import { computeGanttLayout, fmtDuration, type GanttLayout } from "@/lib/gantt";
import {
  STEP_LEGEND,
  StepIcon,
  stepKind,
  stepSummary,
  useIsDark,
  useStepColor,
  type NodeSelection,
} from "./stepMeta";

/** PostHog-style timed Gantt for output.json.trace v2. */
export default function Timeline({
  steps,
  trace,
  selected,
  onSelect,
}: {
  steps: TraceStep[];
  trace?: TraceFile | null;
  selected: NodeSelection;
  onSelect: (sel: NodeSelection) => void;
}) {
  const layout = React.useMemo(
    () => computeGanttLayout(steps, trace ?? undefined),
    [steps, trace],
  );
  return (
    <Box
      sx={{
        bgcolor: "background.paper",
        border: 1,
        borderColor: "divider",
        borderRadius: 1,
        px: 1.5,
        py: 1,
      }}
    >
      {layout ? (
        <GanttTrack steps={steps} layout={layout} selected={selected} onSelect={onSelect} />
      ) : (
        <Typography variant="body2" color="error.main">
          Invalid trace: every generation and tool step must include t_start and t_end.
        </Typography>
      )}
      <Legend />
    </Box>
  );
}

// ---------------------------------------------------------------------------
// Gantt rendering (timed sessions)
// ---------------------------------------------------------------------------

const AXIS_H = 18;
const TURN_H = 20;
const LANE_H = 26;
const BAR_H = 20;

function GanttTrack({
  steps,
  layout,
  selected,
  onSelect,
}: {
  steps: TraceStep[];
  layout: GanttLayout;
  selected: NodeSelection;
  onSelect: (sel: NodeSelection) => void;
}) {
  const colorOf = useStepColor();
  const { total, spans, turns, laneCount, ticks, hasTurns } = layout;
  const turnRow = hasTurns ? TURN_H : 0;
  const trackH = AXIS_H + turnRow + laneCount * LANE_H;
  const pct = (ms: number) => (ms / total) * 100;

  return (
    <Box>
      <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 0.5 }}>
        <Typography variant="subtitle2">Timeline ({fmtDuration(total)})</Typography>
        <Box sx={{ flexGrow: 1 }} />
        <Tooltip title="Final answer">
          <Box
            component="button"
            aria-label="Select final answer"
            onClick={() => onSelect("answer")}
            sx={{
              display: "inline-flex",
              alignItems: "center",
              gap: 0.5,
              border: 1,
              borderColor: selected === "answer" ? "primary.main" : "divider",
              borderRadius: 4,
              bgcolor: "transparent",
              color: selected === "answer" ? "primary.main" : "text.secondary",
              px: 1,
              py: 0.25,
              cursor: "pointer",
              font: "inherit",
              fontSize: "0.74rem",
            }}
          >
            <CheckCircleOutlineIcon sx={{ fontSize: 15 }} /> answer
          </Box>
        </Tooltip>
      </Stack>

      <Box sx={{ position: "relative", height: trackH, minWidth: 360 }}>
        {/* tick gridlines + labels */}
        {ticks.map((t) => (
          <Box
            key={t.ms}
            sx={{
              position: "absolute",
              left: `${pct(t.ms)}%`,
              top: 0,
              bottom: 0,
              width: 0,
              borderLeft: 1,
              borderColor: "divider",
            }}
          >
            <Typography
              variant="caption"
              sx={{
                position: "absolute",
                top: -2,
                left: 2,
                fontSize: "0.66rem",
                color: "text.disabled",
                whiteSpace: "nowrap",
              }}
            >
              {t.label}
            </Typography>
          </Box>
        ))}

        {/* turn-group row */}
        {turns.map((t) => (
          <Tooltip key={t.turn} title={`turn ${t.turn} · ${fmtDuration(t.end - t.start)}`}>
            <Box
              sx={{
                position: "absolute",
                top: AXIS_H,
                left: `${pct(t.start)}%`,
                width: `${pct(t.end - t.start)}%`,
                minWidth: 8,
                height: TURN_H - 4,
                bgcolor: "action.selected",
                borderRadius: 0.5,
                overflow: "hidden",
                px: 0.5,
                display: "flex",
                alignItems: "center",
              }}
            >
              <Typography
                variant="caption"
                sx={{ fontSize: "0.64rem", color: "text.secondary", whiteSpace: "nowrap" }}
              >
                turn {t.turn} · {fmtDuration(t.end - t.start)}
              </Typography>
            </Box>
          </Tooltip>
        ))}

        {/* step spans — same-turn overlaps stack into lanes */}
        {spans.map((sp) => {
          const step = steps[sp.index];
          if (!step) return null;
          const dur = sp.end - sp.start;
          const isSelected = selected === sp.index;
          return (
            <Tooltip
              key={sp.index}
              title={`${sp.index + 1}. ${stepKind(step)}${step.failed ? " (failed)" : ""} · ${fmtDuration(dur)} — ${stepSummary(step)}`}
            >
              <Box
                component="button"
                aria-label={`step ${sp.index + 1}: ${stepKind(step)}`}
                onClick={() => onSelect(sp.index)}
                sx={{
                  position: "absolute",
                  top: AXIS_H + turnRow + sp.lane * LANE_H + (LANE_H - BAR_H) / 2,
                  left: `${pct(sp.start)}%`,
                  width: `${pct(dur)}%`,
                  // very short spans stay clickable
                  minWidth: 20,
                  height: BAR_H,
                  bgcolor: colorOf(step),
                  color: "#fff",
                  border: "1.5px solid",
                  borderColor: step.failed ? "error.main" : "transparent",
                  outline: isSelected ? "2px solid" : "none",
                  outlineColor: "primary.main",
                  outlineOffset: "1px",
                  borderRadius: 0.5,
                  cursor: "pointer",
                  p: 0,
                  overflow: "hidden",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "flex-start",
                  gap: 0.4,
                  fontSize: 13,
                  lineHeight: 1,
                  zIndex: 1,
                  px: 0.55,
                  "&:hover": { filter: "brightness(1.15)" },
                }}
              >
                <Box
                  component="span"
                  sx={{ display: "inline-grid", placeItems: "center", flexShrink: 0, p: "1px" }}
                >
                  <StepIcon step={step} fontSize="inherit" />
                </Box>
                <Box
                  component="span"
                  sx={{
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                    fontSize: "0.63rem",
                    fontWeight: 600,
                  }}
                >
                  {stepKind(step)} · {fmtDuration(dur)}
                </Box>
              </Box>
            </Tooltip>
          );
        })}
      </Box>
    </Box>
  );
}

function Legend() {
  const dark = useIsDark();
  return (
    <Stack direction="row" spacing={1.5} sx={{ mt: 0.5 }} flexWrap="wrap" useFlexGap>
      {STEP_LEGEND.map((l) => (
        <Stack key={l.key} direction="row" spacing={0.5} alignItems="center">
          <Box
            sx={{
              width: 18,
              height: 18,
              borderRadius: "50%",
              bgcolor: STEP_COLORS[l.key][dark ? "dark" : "light"],
              color: "#fff",
              display: "grid",
              placeItems: "center",
              p: "2px",
              boxSizing: "border-box",
            }}
          >
            {l.icon}
          </Box>
          <Typography variant="caption" color="text.secondary">
            {l.label}
          </Typography>
        </Stack>
      ))}
      <Stack direction="row" spacing={0.5} alignItems="center">
        <CheckCircleOutlineIcon sx={{ fontSize: 14, color: "text.secondary" }} />
        <Typography variant="caption" color="text.secondary">
          answer
        </Typography>
      </Stack>
    </Stack>
  );
}
