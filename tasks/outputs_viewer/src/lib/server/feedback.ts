import "server-only";
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { FEEDBACK_DIR, TAGS_FILE } from "./env";
import { targetKey, type FeedbackRecord } from "@/lib/types";

/**
 * Feedback store: append-only JSONL per session under
 * data/output_feedbacks/<system>/<sessionId>.feedback.jsonl.
 *
 * Append = single write() with O_APPEND (atomic for these small records on
 * POSIX). Tags.json rewrites go through temp-file + rename (atomic replace).
 * "Edit" = append a new record with the same (user, target); latest wins when
 * reading with `latestOnly`.
 */

function ensureDir(dir: string) {
  fs.mkdirSync(dir, { recursive: true });
}

function safeName(s: string): boolean {
  // `+` allowed: new session stamps carry a +1000-style offset suffix.
  return /^[\w.+-]+$/.test(s);
}

function feedbackFile(system: string, sessionId: string): string | null {
  if (!safeName(system) || !safeName(sessionId)) return null;
  return path.join(FEEDBACK_DIR, system, `${sessionId}.feedback.jsonl`);
}

export function appendFeedback(
  rec: Omit<FeedbackRecord, "id" | "createdAt"> & Partial<FeedbackRecord>,
): FeedbackRecord | null {
  const file = feedbackFile(rec.system, rec.sessionId);
  if (!file) return null;
  const full: FeedbackRecord = {
    id: rec.id ?? crypto.randomUUID(),
    user: rec.user,
    system: rec.system,
    sessionId: rec.sessionId,
    target: rec.target,
    rating: rec.rating ?? null,
    comment: rec.comment ?? "",
    tags: rec.tags ?? [],
    createdAt: new Date().toISOString(),
  };
  ensureDir(path.dirname(file));
  const fd = fs.openSync(file, "a");
  try {
    fs.writeSync(fd, JSON.stringify(full) + "\n");
  } finally {
    fs.closeSync(fd);
  }
  if (full.tags.length > 0) addTags(full.tags);
  return full;
}

export interface FeedbackFilter {
  system?: string;
  sessionId?: string;
  user?: string;
  latestOnly?: boolean; // per (user, system, session, target) keep newest
}

export function readFeedback(filter: FeedbackFilter = {}): FeedbackRecord[] {
  const records: FeedbackRecord[] = [];
  let systems: string[] = [];
  try {
    systems = fs
      .readdirSync(FEEDBACK_DIR, { withFileTypes: true })
      .filter((d) => d.isDirectory())
      .map((d) => d.name);
  } catch {
    return [];
  }
  for (const system of systems) {
    if (filter.system && system !== filter.system) continue;
    const dir = path.join(FEEDBACK_DIR, system);
    let files: string[] = [];
    try {
      files = fs.readdirSync(dir).filter((f) => f.endsWith(".feedback.jsonl"));
    } catch {
      continue;
    }
    for (const f of files) {
      const sessionId = f.replace(/\.feedback\.jsonl$/, "");
      if (filter.sessionId && sessionId !== filter.sessionId) continue;
      let lines: string[] = [];
      try {
        lines = fs.readFileSync(path.join(dir, f), "utf8").split("\n");
      } catch {
        continue;
      }
      for (const line of lines) {
        const t = line.trim();
        if (!t) continue;
        try {
          const rec = JSON.parse(t) as FeedbackRecord;
          if (filter.user && rec.user !== filter.user) continue;
          records.push(rec);
        } catch {
          // skip malformed line
        }
      }
    }
  }
  records.sort((a, b) => a.createdAt.localeCompare(b.createdAt));
  if (!filter.latestOnly) return records;
  const latest = new Map<string, FeedbackRecord>();
  for (const rec of records) {
    const key = `${rec.user}|${rec.system}|${rec.sessionId}|${targetKey(rec.target)}`;
    latest.set(key, rec); // records are createdAt-ascending: last write wins
  }
  return [...latest.values()].sort((a, b) => b.createdAt.localeCompare(a.createdAt));
}

// ---- tags -----------------------------------------------------------------

export function readTags(): string[] {
  try {
    const data = JSON.parse(fs.readFileSync(TAGS_FILE, "utf8"));
    if (Array.isArray(data?.tags)) return data.tags.filter((t: unknown) => typeof t === "string");
  } catch {
    // fall through: create the file
  }
  ensureDir(FEEDBACK_DIR);
  atomicWriteJson(TAGS_FILE, { tags: [] });
  return [];
}

export function addTags(tags: string[]): string[] {
  const current = readTags();
  const set = new Set(current);
  let changed = false;
  for (const raw of tags) {
    const t = raw.trim();
    if (t && !set.has(t)) {
      set.add(t);
      changed = true;
    }
  }
  const next = [...set].sort((a, b) => a.localeCompare(b));
  if (changed) atomicWriteJson(TAGS_FILE, { tags: next });
  return next;
}

function atomicWriteJson(file: string, data: unknown) {
  ensureDir(path.dirname(file));
  const tmp = `${file}.${process.pid}.${Date.now()}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify(data, null, 2) + "\n");
  fs.renameSync(tmp, file);
}
