import type { TrajectoryStep, TrajectoryFile } from "./types";

/**
 * Pure Gantt layout for the session timeline (no React/MUI imports so it is
 * unit-testable standalone).
 *
 * Timing contract (src/ragrun/trajectory.py): optional per-item `t_start` /
 * `t_end` (ISO 8601 with offset — Melbourne local, e.g.
 * `2026-07-16T18:25:52.490+10:00`) and 0-based `turn`; optional run-level
 * `started_at` / `ended_at`. Date parsing handles offsets, so all layout math
 * is epoch-ms based and timezone-proof.
 */

export interface GanttSpan {
  /** index into trajectory.result */
  index: number;
  /** ms offsets relative to layout t0 */
  start: number;
  end: number;
  /** parallel lane (0 = top). Same-turn overlapping spans get distinct lanes. */
  lane: number;
  turn: number | null;
}

export interface GanttTurn {
  turn: number;
  start: number;
  end: number;
}

export interface GanttTick {
  /** ms offset from t0 */
  ms: number;
  label: string;
}

export interface GanttLayout {
  /** epoch ms of the layout origin */
  t0: number;
  /** total ms spanned (>= 1) */
  total: number;
  spans: GanttSpan[];
  turns: GanttTurn[];
  laneCount: number;
  ticks: GanttTick[];
  hasTurns: boolean;
}

function parseMs(iso: string | undefined): number | null {
  if (!iso) return null;
  const ms = Date.parse(iso);
  return Number.isFinite(ms) ? ms : null;
}

/** True when EVERY step carries parseable t_start/t_end (per-session detection). */
export function hasFullTimings(steps: TrajectoryStep[]): boolean {
  return (
    steps.length > 0 &&
    steps.every((s) => parseMs(s.t_start) != null && parseMs(s.t_end) != null)
  );
}

/** Human duration: 850ms · 1.2s · 25.4s · 1m 05s */
export function fmtDuration(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return "";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(1)}s`;
  const m = Math.floor(s / 60);
  const rest = Math.round(s - m * 60);
  return `${m}m ${String(rest).padStart(2, "0")}s`;
}

/** Per-step duration in ms, when the step carries timings. */
export function stepDurationMs(step: TrajectoryStep): number | null {
  const a = parseMs(step.t_start);
  const b = parseMs(step.t_end);
  if (a == null || b == null || b < a) return null;
  return b - a;
}

/** Axis tick label: whole-unit friendly (0s, 5s, 10s, 1m, 1m30s). */
function tickLabel(ms: number): string {
  const s = ms / 1000;
  if (s < 60) {
    return Number.isInteger(s) ? `${s}s` : `${s.toFixed(1)}s`;
  }
  const m = Math.floor(s / 60);
  const rest = Math.round(s - m * 60);
  return rest === 0 ? `${m}m` : `${m}m${rest}s`;
}

const TICK_STEPS_MS = [
  100, 200, 250, 500,
  1_000, 2_000, 5_000, 10_000, 15_000, 30_000,
  60_000, 120_000, 300_000, 600_000, 900_000, 1_800_000, 3_600_000,
];

/** Pick the smallest nice step giving at most ~8 intervals. */
export function niceTicks(totalMs: number, maxTicks = 8): GanttTick[] {
  const step =
    TICK_STEPS_MS.find((s) => totalMs / s <= maxTicks) ??
    TICK_STEPS_MS[TICK_STEPS_MS.length - 1];
  const ticks: GanttTick[] = [];
  for (let ms = 0; ms <= totalMs; ms += step) {
    ticks.push({ ms, label: tickLabel(ms) });
  }
  return ticks;
}

/**
 * Compute the full layout, or null when timings are absent/unparseable.
 *
 * Lane assignment (PostHog-style): spans are grouped by `turn` (all
 * turn-less spans share one group), each group sorted by t_start, then
 * greedily packed — a span takes the first lane in its group whose previous
 * span ended before this one starts (1 ms tolerance); overlapping same-turn
 * spans therefore stack into parallel lanes. Turns are sequential in time,
 * so lanes are reused across turns.
 */
export function computeGanttLayout(
  steps: TrajectoryStep[],
  trajectory?: Pick<TrajectoryFile, "started_at" | "ended_at">,
): GanttLayout | null {
  if (!hasFullTimings(steps)) return null;

  const parsed = steps.map((s, index) => ({
    index,
    startAbs: parseMs(s.t_start) as number,
    endAbs: Math.max(parseMs(s.t_end) as number, parseMs(s.t_start) as number),
    turn: typeof s.turn === "number" ? s.turn : null,
  }));

  const runStart = parseMs(trajectory?.started_at);
  const runEnd = parseMs(trajectory?.ended_at);
  const t0 = Math.min(...parsed.map((p) => p.startAbs), ...(runStart != null ? [runStart] : []));
  const t1 = Math.max(...parsed.map((p) => p.endAbs), ...(runEnd != null ? [runEnd] : []));
  const total = Math.max(t1 - t0, 1);

  // group by turn (turn-less spans share a single group)
  const groups = new Map<string, typeof parsed>();
  for (const p of parsed) {
    const key = p.turn == null ? "_noturn" : `t${p.turn}`;
    const list = groups.get(key) ?? [];
    list.push(p);
    groups.set(key, list);
  }

  const EPS = 1; // ms tolerance: touching spans share a lane
  const laneOf = new Map<number, number>(); // step index -> lane
  let laneCount = 1;
  for (const list of groups.values()) {
    const sorted = [...list].sort((a, b) => a.startAbs - b.startAbs || a.index - b.index);
    const laneEnds: number[] = []; // per-lane last end time within this group
    for (const p of sorted) {
      let lane = laneEnds.findIndex((end) => end <= p.startAbs + EPS);
      if (lane === -1) {
        lane = laneEnds.length;
        laneEnds.push(p.endAbs);
      } else {
        laneEnds[lane] = p.endAbs;
      }
      laneOf.set(p.index, lane);
    }
    laneCount = Math.max(laneCount, laneEnds.length);
  }

  const spans: GanttSpan[] = parsed.map((p) => ({
    index: p.index,
    start: p.startAbs - t0,
    end: p.endAbs - t0,
    lane: laneOf.get(p.index) ?? 0,
    turn: p.turn,
  }));

  // turn header spans
  const turnMap = new Map<number, { start: number; end: number }>();
  for (const p of parsed) {
    if (p.turn == null) continue;
    const cur = turnMap.get(p.turn);
    turnMap.set(p.turn, {
      start: Math.min(cur?.start ?? Infinity, p.startAbs - t0),
      end: Math.max(cur?.end ?? -Infinity, p.endAbs - t0),
    });
  }
  const turns: GanttTurn[] = [...turnMap.entries()]
    .map(([turn, v]) => ({ turn, ...v }))
    .sort((a, b) => a.turn - b.turn);

  return {
    t0,
    total,
    spans,
    turns,
    laneCount,
    ticks: niceTicks(total),
    hasTurns: turns.length > 0,
  };
}
