"use client";
import * as React from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Typography from "@mui/material/Typography";
import PsychologyOutlinedIcon from "@mui/icons-material/PsychologyOutlined";
import SearchIcon from "@mui/icons-material/Search";
import DescriptionOutlinedIcon from "@mui/icons-material/DescriptionOutlined";
import NotesIcon from "@mui/icons-material/Notes";
import { useColorScheme } from "@mui/material/styles";
import { STEP_COLORS } from "@/lib/palette";
import type { TrajectoryStep } from "@/lib/types";

/** Selection in the master-detail session view: a step index or the answer node. */
export type NodeSelection = number | "answer";

export function stepKind(step: TrajectoryStep): string {
  if (step.type === "tool_call") return step.tool_name ?? "tool_call";
  return step.type;
}

export function stepColorKey(step: TrajectoryStep): keyof typeof STEP_COLORS {
  const kind = stepKind(step);
  if (kind === "reasoning" || kind === "search" || kind === "get_document" || kind === "output_text") {
    return kind;
  }
  return "other";
}

export function StepIcon({
  step,
  fontSize = "small",
}: {
  step: TrajectoryStep;
  fontSize?: "small" | "inherit";
}) {
  const kind = stepColorKey(step);
  if (kind === "reasoning") return <PsychologyOutlinedIcon fontSize={fontSize} />;
  if (kind === "search") return <SearchIcon fontSize={fontSize} />;
  if (kind === "get_document") return <DescriptionOutlinedIcon fontSize={fontSize} />;
  return <NotesIcon fontSize={fontSize} />;
}

export function useIsDark(): boolean {
  const { mode, systemMode } = useColorScheme();
  return (mode === "system" ? systemMode : mode) === "dark";
}

export function useStepColor() {
  const dark = useIsDark();
  return React.useCallback(
    (step: TrajectoryStep) => STEP_COLORS[stepColorKey(step)][dark ? "dark" : "light"],
    [dark],
  );
}

export const STEP_LEGEND: { key: keyof typeof STEP_COLORS; label: string; icon: React.ReactNode }[] = [
  { key: "reasoning", label: "reasoning", icon: <PsychologyOutlinedIcon sx={{ fontSize: 14 }} /> },
  { key: "search", label: "search", icon: <SearchIcon sx={{ fontSize: 14 }} /> },
  { key: "get_document", label: "get_document", icon: <DescriptionOutlinedIcon sx={{ fontSize: 14 }} /> },
  { key: "output_text", label: "output_text", icon: <NotesIcon sx={{ fontSize: 14 }} /> },
];

/** One-line summary for the tree row: query, docid, or leading words. */
export function stepSummary(step: TrajectoryStep): string {
  const kind = stepKind(step);
  const args = step.arguments;
  if (kind === "search") {
    if (args && typeof args === "object") {
      const a = args as Record<string, unknown>;
      const q = a.query ?? a.q;
      if (typeof q === "string") return q;
    }
    if (typeof args === "string") return args;
  }
  if (kind === "get_document") {
    if (args && typeof args === "object") {
      const a = args as Record<string, unknown>;
      const d = a.docid ?? a.id;
      if (typeof d === "string") return d;
    }
    if (typeof step.docid === "string") return step.docid as string;
    const first = step.returned_docids?.[0];
    if (first) return first;
  }
  if (typeof step.output === "string" && step.output) {
    return step.output.trim().split(/\s+/).slice(0, 12).join(" ");
  }
  if (typeof args === "string") return args;
  if (args && typeof args === "object") return JSON.stringify(args);
  return "";
}

/** Truncated text block with an expand/collapse toggle. */
export function TruncText({
  text,
  limit = 700,
  mono,
}: {
  text: string;
  limit?: number;
  mono?: boolean;
}) {
  const [open, setOpen] = React.useState(false);
  const needsTrunc = text.length > limit;
  const shown = open || !needsTrunc ? text : text.slice(0, limit);
  return (
    <Box>
      <Typography
        variant="body2"
        component="pre"
        sx={{
          m: 0,
          whiteSpace: "pre-wrap",
          wordBreak: "break-word",
          fontFamily: mono ? "ui-monospace, SFMono-Regular, Menlo, monospace" : "inherit",
          fontSize: mono ? "0.76rem" : undefined,
          bgcolor: mono ? "action.hover" : undefined,
          p: mono ? 1 : 0,
          borderRadius: 1,
        }}
      >
        {shown}
        {!open && needsTrunc ? "…" : ""}
      </Typography>
      {needsTrunc ? (
        <Button size="small" onClick={() => setOpen((o) => !o)} sx={{ mt: 0.25 }}>
          {open ? "Show less" : `Show all (${text.length.toLocaleString()} chars)`}
        </Button>
      ) : null}
    </Box>
  );
}
