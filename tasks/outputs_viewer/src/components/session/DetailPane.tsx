"use client";
import * as React from "react";
import useSWR from "swr";
import Box from "@mui/material/Box";
import Paper from "@mui/material/Paper";
import Tabs from "@mui/material/Tabs";
import Tab from "@mui/material/Tab";
import Typography from "@mui/material/Typography";
import Stack from "@mui/material/Stack";
import Chip from "@mui/material/Chip";
import Button from "@mui/material/Button";
import Collapse from "@mui/material/Collapse";
import Tooltip from "@mui/material/Tooltip";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import Alert from "@mui/material/Alert";
import ErrorOutlineIcon from "@mui/icons-material/ErrorOutline";
import ThumbUpIcon from "@mui/icons-material/ThumbUp";
import ThumbDownIcon from "@mui/icons-material/ThumbDown";
import HorizontalRuleIcon from "@mui/icons-material/HorizontalRule";
import { fetcher } from "@/lib/client/api";
import { fmtDuration, stepDurationMs } from "@/lib/gantt";
import { fmtMelbourne } from "@/lib/time";
import type { FeedbackRecord, OutputFile, TraceFile, TraceStep } from "@/lib/types";
import AnswerView from "./AnswerView";
import CitationChip from "./CitationChip";
import { StepIcon, stepKind, TruncText, useStepColor, type NodeSelection } from "./stepMeta";

const STEP_TABS = ["details", "raw"] as const;
const ANSWER_TABS = ["answer", "sentences", "raw", "feedback"] as const;

export function normalizeDtab(selection: NodeSelection, dtab: string | null): string {
  if (selection === "answer") {
    return (ANSWER_TABS as readonly string[]).includes(dtab ?? "") ? (dtab as string) : "answer";
  }
  return (STEP_TABS as readonly string[]).includes(dtab ?? "") ? (dtab as string) : "details";
}

const KNOWN_KEYS = new Set([
  "type",
  "tool_name",
  "input",
  "arguments",
  "output",
  "tool_call_id",
  "failed",
  "returned",
  "returned_docids",
  "id",
  "parent_id",
  "t_start",
  "t_end",
  "turn",
  "stats",
  "context",
]);

/** "Details" tab body for a step — args, output, returned docids, extras. */
function StepDetails({
  step,
  activeDoc,
  onOpenDoc,
}: {
  step: TraceStep;
  activeDoc: string | null;
  onOpenDoc: (docid: string) => void;
}) {
  const docids: string[] =
    step.returned_docids ??
    (Array.isArray(step.returned) ? step.returned.map((r) => r.docid) : []);
  const scores = new Map(
    Array.isArray(step.returned)
      ? step.returned.filter((r) => r.score != null).map((r) => [r.docid, r.score as number])
      : [],
  );
  const context = step.context;
  const stats = step.stats;
  const tokens = stats?.tokens;
  const cumulativeTokens = stats?.cumulative_tokens;
  const extras = Object.entries(step).filter(
    ([k, v]) => !KNOWN_KEYS.has(k) && v != null && typeof v !== "object",
  );
  const [showExtras, setShowExtras] = React.useState(false);
  const hasArgs =
    step.arguments != null &&
    !(typeof step.arguments === "object" && Object.keys(step.arguments as object).length === 0) &&
    step.arguments !== "";
  const hasInput = step.input != null;
  const hasOutput =
    step.output != null &&
    step.output !== "" &&
    !(typeof step.output === "object" && Object.keys(step.output as object).length === 0);

  return (
    <Stack spacing={1.5}>
      {stats ? (
        <Box>
          <Typography variant="overline" color="text.secondary">
            Step stats
          </Typography>
          <Box sx={{ display: "flex", flexWrap: "wrap", gap: 0.5, mt: 0.25 }}>
            {stats.duration_ms != null ? (
              <Chip size="small" variant="outlined" label={`latency ${fmtDuration(stats.duration_ms)}`} />
            ) : null}
            {tokens?.input != null ? (
              <Chip size="small" variant="outlined" label={`input ${tokens.input.toLocaleString()} tok`} />
            ) : null}
            {tokens?.output != null ? (
              <Chip size="small" variant="outlined" label={`output ${tokens.output.toLocaleString()} tok`} />
            ) : null}
            {tokens?.cache_read != null ? (
              <Chip size="small" variant="outlined" label={`cache read ${tokens.cache_read.toLocaleString()}`} />
            ) : null}
            {tokens?.cache_write != null ? (
              <Chip size="small" variant="outlined" label={`cache write ${tokens.cache_write.toLocaleString()}`} />
            ) : null}
            {tokens?.total != null ? (
              <Chip size="small" color="primary" variant="outlined" label={`this generation ${tokens.total.toLocaleString()} tok`} />
            ) : null}
            {cumulativeTokens?.processed != null ? (
              <Chip
                size="small"
                color="primary"
                label={`processed so far ${cumulativeTokens.processed.toLocaleString()} tok`}
                title={`Input ${cumulativeTokens.processed_input?.toLocaleString() ?? "—"} + output ${cumulativeTokens.output?.toLocaleString() ?? "—"}`}
              />
            ) : null}
            {stats.context_tokens != null ? (
              <Chip
                size="small"
                color="secondary"
                variant="outlined"
                label={
                  stats.context_budget_tokens
                    ? `context ${stats.context_tokens.toLocaleString()} / ${stats.context_budget_tokens.toLocaleString()} (${((stats.context_tokens / stats.context_budget_tokens) * 100).toFixed(1)}%)`
                    : `context ${stats.context_tokens.toLocaleString()} tok`
                }
              />
            ) : null}
            {stats.peak_context_tokens != null &&
            stats.peak_context_tokens !== stats.context_tokens ? (
              <Chip
                size="small"
                color="secondary"
                variant="outlined"
                label={`peak context ${stats.peak_context_tokens.toLocaleString()} tok`}
              />
            ) : null}
            {stats.elapsed_ms != null ? (
              <Chip size="small" variant="outlined" label={`elapsed ${fmtDuration(stats.elapsed_ms)}`} />
            ) : null}
            {stats.cost_usd != null ? (
              <Chip size="small" variant="outlined" label={`$${stats.cost_usd.toFixed(4)}`} />
            ) : null}
          </Box>
        </Box>
      ) : null}

      {context &&
      ((context.staged?.length ?? 0) > 0 ||
        (context.committed?.length ?? 0) > 0 ||
        (context.rejected?.length ?? 0) > 0) ? (
        <Box>
          <Typography variant="overline" color="text.secondary">
            Context decision
          </Typography>
          <Stack spacing={0.75} sx={{ mt: 0.25 }}>
            {(context.staged?.length ?? 0) > 0 ? (
              <Box>
                <Typography variant="caption" color="text.secondary">
                  Staged ({context.staged?.length})
                </Typography>
                <Box sx={{ display: "flex", flexWrap: "wrap", gap: 0.5, mt: 0.25 }}>
                  {context.staged?.map((docid) => (
                    <Chip
                      key={`staged-${docid}`}
                      size="small"
                      variant="outlined"
                      label={docid}
                      clickable
                      onClick={() => onOpenDoc(docid)}
                      sx={{ fontFamily: "monospace", fontSize: "0.68rem" }}
                    />
                  ))}
                </Box>
              </Box>
            ) : null}
            {(context.committed?.length ?? 0) > 0 ? (
              <Box>
                <Typography variant="caption" color="success.main" sx={{ fontWeight: 700 }}>
                  Committed / selected ({context.committed?.length})
                </Typography>
                <Box sx={{ display: "flex", flexWrap: "wrap", gap: 0.5, mt: 0.25 }}>
                  {context.committed?.map((docid) => (
                    <Chip
                      key={`committed-${docid}`}
                      size="small"
                      color="success"
                      label={docid}
                      clickable
                      onClick={() => onOpenDoc(docid)}
                      sx={{ fontFamily: "monospace", fontSize: "0.68rem" }}
                    />
                  ))}
                </Box>
              </Box>
            ) : null}
            {(context.rejected?.length ?? 0) > 0 ? (
              <Box>
                <Typography variant="caption" color="text.secondary">
                  Rejected ({context.rejected?.length})
                </Typography>
                <Box sx={{ display: "flex", flexWrap: "wrap", gap: 0.5, mt: 0.25 }}>
                  {context.rejected?.map((item) => (
                    <Tooltip key={`rejected-${item.docid}`} title={item.reason ?? "Agent marked this document irrelevant"}>
                      <Chip
                        size="small"
                        label={item.docid}
                        clickable
                        onClick={() => onOpenDoc(item.docid)}
                        sx={{ fontFamily: "monospace", fontSize: "0.68rem", opacity: 0.7 }}
                      />
                    </Tooltip>
                  ))}
                </Box>
              </Box>
            ) : null}
          </Stack>
        </Box>
      ) : null}

      {extras.length > 0 ? (
        <Box>
          <Button size="small" onClick={() => setShowExtras((s) => !s)}>
            {showExtras ? "hide details" : `details (${extras.length})`}
          </Button>
          <Collapse in={showExtras} unmountOnExit>
            <Box sx={{ display: "flex", flexWrap: "wrap", gap: 0.5, mt: 0.5 }}>
              {extras.map(([k, v]) => (
                <Chip key={k} size="small" variant="outlined" label={`${k}: ${String(v)}`} sx={{ height: 20 }} />
              ))}
            </Box>
          </Collapse>
        </Box>
      ) : null}

      {hasArgs ? (
        <Box>
          <Typography variant="overline" color="text.secondary">
            Arguments
          </Typography>
          <TruncText
            mono
            text={
              typeof step.arguments === "string"
                ? step.arguments
                : JSON.stringify(step.arguments, null, 2)
            }
          />
        </Box>
      ) : null}

      {hasInput ? (
        <Box>
          <Typography variant="overline" color="text.secondary">
            Generation input
          </Typography>
          <TruncText
            mono
            limit={1800}
            text={
              typeof step.input === "string"
                ? step.input
                : JSON.stringify(step.input, null, 2)
            }
          />
        </Box>
      ) : null}

      {hasOutput ? (
        <Box>
          <Typography variant="overline" color="text.secondary">
            {step.type === "reasoning"
              ? "Reasoning"
              : step.type === "output_text"
                ? "Output text"
                : step.type === "generation"
                  ? "Generation output"
                  : "Tool output"}
          </Typography>
          <TruncText
            text={
              typeof step.output === "string"
                ? step.output
                : JSON.stringify(step.output, null, 2)
            }
            mono={step.type === "tool_call" || typeof step.output === "object"}
            limit={step.type === "tool_call" ? 500 : 1800}
          />
        </Box>
      ) : null}

      {docids.length > 0 ? (
        <Box>
          <Typography variant="overline" color="text.secondary">
            Returned ({docids.length})
          </Typography>
          <Box sx={{ display: "flex", flexWrap: "wrap", gap: 0.5, mt: 0.25 }}>
            {docids.map((d) => (
              <Tooltip key={d} title={scores.has(d) ? `score ${scores.get(d)?.toFixed(4)}` : d}>
                <Chip
                  size="small"
                  label={d}
                  clickable
                  color={activeDoc === d ? "primary" : "default"}
                  variant={activeDoc === d ? "filled" : "outlined"}
                  onClick={() => onOpenDoc(d)}
                  sx={{ height: 20, fontFamily: "monospace", fontSize: "0.68rem" }}
                />
              </Tooltip>
            ))}
          </Box>
        </Box>
      ) : null}
    </Stack>
  );
}

/** "Sentences" tab — the raw sentence/citation table. */
function SentencesTable({
  output,
  activeDoc,
  onOpenDoc,
}: {
  output: OutputFile;
  activeDoc: string | null;
  onOpenDoc: (docid: string) => void;
}) {
  const refs = output.references ?? [];
  return (
    <Box sx={{ overflowX: "auto" }}>
      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell sx={{ width: 40 }}>#</TableCell>
            <TableCell>Sentence</TableCell>
            <TableCell sx={{ width: 140 }}>Citations</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {(output.answer ?? []).map((s, i) => (
            <TableRow key={i} hover>
              <TableCell sx={{ verticalAlign: "top", color: "text.secondary" }}>{i + 1}</TableCell>
              <TableCell sx={{ verticalAlign: "top" }}>{s.text}</TableCell>
              <TableCell sx={{ verticalAlign: "top" }}>
                {(s.citations ?? []).map((c) => (
                  <CitationChip
                    key={c}
                    index={c}
                    docid={refs[c]}
                    active={activeDoc != null && refs[c] === activeDoc}
                    onOpen={onOpenDoc}
                  />
                ))}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Box>
  );
}

function RatingIcon({ rating }: { rating: FeedbackRecord["rating"] }) {
  if (rating === "up") return <ThumbUpIcon fontSize="small" color="primary" />;
  if (rating === "down") return <ThumbDownIcon fontSize="small" color="error" />;
  return <HorizontalRuleIcon fontSize="small" color="disabled" />;
}

function targetLabel(r: FeedbackRecord): string {
  if (r.target.type === "paragraph") return `¶${(r.target.paragraphIndex ?? 0) + 1}`;
  if (r.target.type === "citation") return `citation ${r.target.docid}`;
  return "full answer";
}

/** "Feedback" tab — all latest-wins feedback on this session, with user chips. */
function SessionFeedback({ system, sessionId }: { system: string; sessionId: string }) {
  const { data, error } = useSWR<{ records: FeedbackRecord[] }>(
    `/api/feedback?system=${encodeURIComponent(system)}&sessionId=${encodeURIComponent(sessionId)}`,
    fetcher,
  );
  if (error) return <Alert severity="error">Failed to load feedback.</Alert>;
  const records = data?.records ?? [];
  if (records.length === 0) {
    return (
      <Typography color="text.secondary" variant="body2" sx={{ p: 1 }}>
        No feedback on this session yet.
      </Typography>
    );
  }
  return (
    <Stack spacing={1}>
      {records.map((r) => (
        <Paper key={r.id} variant="outlined" sx={{ p: 1 }}>
          <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
            <RatingIcon rating={r.rating} />
            <Chip size="small" color="secondary" variant="outlined" label={r.user} sx={{ height: 20 }} />
            <Chip
              size="small"
              variant="outlined"
              label={targetLabel(r)}
              sx={{ height: 20, fontFamily: r.target.type === "citation" ? "monospace" : undefined }}
            />
            <Typography variant="caption" color="text.secondary">
              {fmtMelbourne(r.createdAt)}
            </Typography>
          </Stack>
          {r.comment ? (
            <Typography variant="body2" sx={{ mt: 0.5 }}>
              {r.comment}
            </Typography>
          ) : null}
          {r.tags.length > 0 ? (
            <Box sx={{ display: "flex", gap: 0.5, mt: 0.5, flexWrap: "wrap" }}>
              {r.tags.map((t) => (
                <Chip key={t} size="small" label={t} sx={{ height: 18 }} />
              ))}
            </Box>
          ) : null}
        </Paper>
      ))}
    </Stack>
  );
}

/**
 * Right-hand detail pane of the master-detail session view.
 * Answer node tabs: Answer | Sentences | Raw | Feedback.
 * Step node tabs: Details | Raw.
 */
export default function DetailPane({
  selection,
  dtab,
  onDtabChange,
  steps,
  trace,
  output,
  system,
  sessionId,
  activeDoc,
  onOpenDoc,
}: {
  selection: NodeSelection;
  dtab: string | null;
  onDtabChange: (dtab: string | null) => void;
  steps: TraceStep[];
  trace: TraceFile | null;
  output: OutputFile;
  system: string;
  sessionId: string;
  activeDoc: string | null;
  onOpenDoc: (docid: string) => void;
}) {
  const colorOf = useStepColor();
  const tab = normalizeDtab(selection, dtab);
  const step = typeof selection === "number" ? steps[selection] : undefined;

  const header =
    selection === "input" ? (
      <Typography variant="subtitle2" sx={{ px: 1.5, pt: 1 }}>
        Trace input
      </Typography>
    ) : selection === "answer" ? (
      <Typography variant="subtitle2" sx={{ px: 1.5, pt: 1 }}>
        Final answer
      </Typography>
    ) : step ? (
      <Stack direction="row" spacing={1} alignItems="center" sx={{ px: 1.5, pt: 1 }}>
        <Box
          sx={{
            width: 24,
            height: 24,
            borderRadius: "50%",
            display: "grid",
            placeItems: "center",
            color: "#fff",
            bgcolor: colorOf(step),
            flexShrink: 0,
            fontSize: 13,
          }}
        >
          <StepIcon step={step} fontSize="inherit" />
        </Box>
        <Typography variant="subtitle2">
          Step {selection + 1}: {stepKind(step)}
        </Typography>
        {(() => {
          const d = stepDurationMs(step);
          return d != null ? (
            <Chip size="small" variant="outlined" label={fmtDuration(d)} sx={{ height: 20 }} />
          ) : null;
        })()}
        {step.failed ? (
          <Chip size="small" color="error" icon={<ErrorOutlineIcon />} label="failed" sx={{ height: 20 }} />
        ) : null}
      </Stack>
    ) : (
      <Typography variant="subtitle2" sx={{ px: 1.5, pt: 1 }}>
        Step not found
      </Typography>
    );

  return (
    <Paper variant="outlined" sx={{ minWidth: 0 }}>
      {header}
      <Tabs
        value={tab}
        onChange={(_e, v) => onDtabChange(v)}
        sx={{ px: 1, minHeight: 36, borderBottom: 1, borderColor: "divider" }}
      >
        {(selection === "answer" ? ANSWER_TABS : STEP_TABS).map((t) => (
          <Tab key={t} value={t} label={t} sx={{ minHeight: 36, py: 0, textTransform: "capitalize" }} />
        ))}
      </Tabs>
      <Box sx={{ p: 1.5 }}>
        {selection === "input" ? (
          tab === "details" ? (
            <Stack spacing={1.5}>
              <Typography variant="body2" color="text.secondary">
                Initial model input. Later generations reference tool-result steps instead of duplicating their payloads.
              </Typography>
              <TruncText mono limit={6000} text={JSON.stringify(trace?.input ?? {}, null, 2)} />
            </Stack>
          ) : (
            <TruncText mono limit={6000} text={JSON.stringify(trace?.input ?? {}, null, 2)} />
          )
        ) : selection === "answer" ? (
          tab === "answer" ? (
            <AnswerView
              system={system}
              sessionId={sessionId}
              output={output}
              activeDoc={activeDoc}
              onOpenDoc={onOpenDoc}
            />
          ) : tab === "sentences" ? (
            <SentencesTable output={output} activeDoc={activeDoc} onOpenDoc={onOpenDoc} />
          ) : tab === "raw" ? (
            <TruncText
              mono
              limit={4000}
              text={JSON.stringify(
                {
                  metadata: output.metadata,
                  references: output.references,
                  answer: output.answer,
                },
                null,
                2,
              )}
            />
          ) : (
            <SessionFeedback system={system} sessionId={sessionId} />
          )
        ) : step ? (
          tab === "details" ? (
            <StepDetails step={step} activeDoc={activeDoc} onOpenDoc={onOpenDoc} />
          ) : (
            <TruncText mono limit={4000} text={JSON.stringify(step, null, 2)} />
          )
        ) : (
          <Typography color="text.secondary" variant="body2">
            This output trace has no step #{String(selection)}.
          </Typography>
        )}
      </Box>
    </Paper>
  );
}
