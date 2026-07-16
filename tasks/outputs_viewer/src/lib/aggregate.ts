import type { FeedbackRecord, FeedbackTargetType } from "./types";

/** Ratings tallied over a set of latest-wins feedback records. */
export interface RatingAgg {
  up: number;
  down: number;
  rated: number; // up + down
  net: number;
  pctUp: number | null; // null when nothing rated
}

export function tallyRatings(records: FeedbackRecord[]): RatingAgg {
  let up = 0;
  let down = 0;
  for (const r of records) {
    if (r.rating === "up") up += 1;
    else if (r.rating === "down") down += 1;
  }
  const rated = up + down;
  return { up, down, rated, net: up - down, pctUp: rated ? up / rated : null };
}

export interface SystemAgg {
  system: string;
  answer: RatingAgg;
  sentence: RatingAgg;
  citation: RatingAgg;
  tagCounts: Record<string, number>;
  total: number;
}

export function aggregateBySystem(records: FeedbackRecord[]): SystemAgg[] {
  const bySystem = new Map<string, FeedbackRecord[]>();
  for (const r of records) {
    const list = bySystem.get(r.system) ?? [];
    list.push(r);
    bySystem.set(r.system, list);
  }
  const out: SystemAgg[] = [];
  for (const [system, recs] of bySystem) {
    const byType = (t: FeedbackTargetType) => recs.filter((r) => r.target.type === t);
    const tagCounts: Record<string, number> = {};
    for (const r of recs) {
      for (const tag of r.tags) tagCounts[tag] = (tagCounts[tag] ?? 0) + 1;
    }
    out.push({
      system,
      answer: tallyRatings(byType("answer")),
      sentence: tallyRatings(byType("sentence")),
      citation: tallyRatings(byType("citation")),
      tagCounts,
      total: recs.length,
    });
  }
  return out.sort((a, b) => a.system.localeCompare(b.system));
}

export function countBy<T>(items: T[], key: (item: T) => string): Record<string, number> {
  const out: Record<string, number> = {};
  for (const it of items) {
    const k = key(it);
    out[k] = (out[k] ?? 0) + 1;
  }
  return out;
}

export function fmtPct(v: number | null): string {
  return v == null ? "—" : `${Math.round(v * 100)}%`;
}
