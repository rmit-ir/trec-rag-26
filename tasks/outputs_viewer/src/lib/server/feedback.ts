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

/**
 * Tag vocabulary: a single-column CSV at data/output_feedbacks/tags.csv, one
 * tag per line.
 *
 * Append-only on purpose. Everyone shares this one file, so a whole-file
 * rewrite (the previous tags.json) made every concurrent tag addition a merge
 * conflict, and resolving one by picking a side silently dropped the other
 * person's tag. Appending keeps each addition on its own line, which lets the
 * `merge=union` driver in .gitattributes take both sides automatically.
 *
 * The corollary: never sort or rewrite the file. Ordering and de-duplication
 * happen on read, because union merges interleave the sides and can repeat a
 * tag both people added.
 */

function csvEncode(value: string): string {
  return /[",]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value;
}

function csvDecode(line: string): string {
  const s = line.trim();
  if (!s.startsWith('"')) return s;
  return s.slice(1).replace(/"$/, "").replace(/""/g, '"');
}

export function readTags(): string[] {
  let text: string;
  try {
    text = fs.readFileSync(TAGS_FILE, "utf8");
  } catch {
    return []; // not created until the first tag is added
  }
  const set = new Set<string>();
  for (const line of text.split("\n")) {
    const tag = csvDecode(line);
    if (tag) set.add(tag);
  }
  return [...set].sort((a, b) => a.localeCompare(b));
}

export function addTags(tags: string[]): string[] {
  const known = new Set(readTags());
  const fresh: string[] = [];
  for (const raw of tags) {
    // A newline would split one tag across two rows; collapse rather than
    // reject so a stray paste still yields a usable tag.
    const tag = raw.replace(/[\r\n]+/g, " ").trim();
    if (tag && !known.has(tag) && !fresh.includes(tag)) fresh.push(tag);
  }
  if (fresh.length) {
    ensureDir(path.dirname(TAGS_FILE));
    // O_APPEND single write: atomic against concurrent server writes, and one
    // line per tag keeps the file union-mergeable.
    fs.appendFileSync(TAGS_FILE, fresh.map(csvEncode).join("\n") + "\n");
  }
  return readTags();
}
