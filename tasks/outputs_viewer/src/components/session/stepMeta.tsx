"use client";
import * as React from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Typography from "@mui/material/Typography";
import PsychologyOutlinedIcon from "@mui/icons-material/PsychologyOutlined";
import SearchIcon from "@mui/icons-material/Search";
import DescriptionOutlinedIcon from "@mui/icons-material/DescriptionOutlined";
import NotesIcon from "@mui/icons-material/Notes";
import FactCheckOutlinedIcon from "@mui/icons-material/FactCheckOutlined";
import { useColorScheme } from "@mui/material/styles";
import { STEP_COLORS } from "@/lib/palette";
import type { TraceStep } from "@/lib/types";

/** Selection in the master-detail session view. */
export type NodeSelection = number | "input" | "answer";

export function stepKind(step: TraceStep): string {
  if (step.type === "tool_call") return step.tool_name ?? "tool_call";
  return step.type;
}

export function stepColorKey(step: TraceStep): keyof typeof STEP_COLORS {
  const kind = stepKind(step);
  if (
    kind === "generation" ||
    kind === "reasoning" ||
    kind === "search" ||
    kind === "get_document" ||
    kind === "commit_context" ||
    kind === "output_text"
  ) {
    return kind;
  }
  return "other";
}

export function StepIcon({
  step,
  fontSize = "small",
}: {
  step: TraceStep;
  fontSize?: "small" | "inherit";
}) {
  const kind = stepColorKey(step);
  if (kind === "generation" || kind === "reasoning") {
    return <PsychologyOutlinedIcon fontSize={fontSize} />;
  }
  if (kind === "search") return <SearchIcon fontSize={fontSize} />;
  if (kind === "get_document") return <DescriptionOutlinedIcon fontSize={fontSize} />;
  if (kind === "commit_context") return <FactCheckOutlinedIcon fontSize={fontSize} />;
  return <NotesIcon fontSize={fontSize} />;
}

export function useIsDark(): boolean {
  const { mode, systemMode } = useColorScheme();
  return (mode === "system" ? systemMode : mode) === "dark";
}

export function useStepColor() {
  const dark = useIsDark();
  return React.useCallback(
    (step: TraceStep) => STEP_COLORS[stepColorKey(step)][dark ? "dark" : "light"],
    [dark],
  );
}

export const STEP_LEGEND: { key: keyof typeof STEP_COLORS; label: string; icon: React.ReactNode }[] = [
  { key: "generation", label: "generation", icon: <PsychologyOutlinedIcon sx={{ fontSize: 14 }} /> },
  { key: "reasoning", label: "reasoning", icon: <PsychologyOutlinedIcon sx={{ fontSize: 14 }} /> },
  { key: "search", label: "search", icon: <SearchIcon sx={{ fontSize: 14 }} /> },
  { key: "get_document", label: "get_document", icon: <DescriptionOutlinedIcon sx={{ fontSize: 14 }} /> },
  { key: "commit_context", label: "commit_context", icon: <FactCheckOutlinedIcon sx={{ fontSize: 14 }} /> },
  { key: "output_text", label: "output_text", icon: <NotesIcon sx={{ fontSize: 14 }} /> },
];

/** One-line summary for the tree row: query, docid, or leading words. */
export function stepSummary(step: TraceStep): string {
  const kind = stepKind(step);
  const args = step.arguments;
  if (kind === "generation" && step.output && typeof step.output === "object") {
    const generated = step.output as Record<string, unknown>;
    const calls = Array.isArray(generated.tool_calls) ? generated.tool_calls : [];
    if (calls.length > 0) {
      const names = calls
        .map((call) =>
          call && typeof call === "object"
            ? String((call as Record<string, unknown>).name ?? "tool")
            : "tool",
        )
        .join(", ");
      return `issued ${calls.length} tool call${calls.length === 1 ? "" : "s"}: ${names}`;
    }
    if (typeof generated.text === "string" && generated.text) {
      return generated.text.trim().split(/\s+/).slice(0, 12).join(" ");
    }
    return "continued the agent conversation";
  }
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
