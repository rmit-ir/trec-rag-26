import "server-only";
import path from "node:path";
import fs from "node:fs";
import dotenv from "dotenv";

/**
 * Repo-root anchored paths + secrets. The app lives at
 * <repo>/tasks/outputs_viewer, so the repo root is two levels up from cwd.
 * Secrets are read from the repo-root .env and NEVER re-exported to the
 * client (this module is server-only).
 */
export const REPO_ROOT = path.resolve(process.cwd(), "..", "..");
export const OUTPUTS_DIR = path.join(REPO_ROOT, "data", "outputs");
export const FEEDBACK_DIR = path.join(REPO_ROOT, "data", "output_feedbacks");
export const TAGS_FILE = path.join(FEEDBACK_DIR, "tags.json");

let loaded = false;
function loadEnv() {
  if (loaded) return;
  const envPath = path.join(REPO_ROOT, ".env");
  if (fs.existsSync(envPath)) dotenv.config({ path: envPath });
  loaded = true;
}

export function getEnv(name: string, fallback?: string): string | undefined {
  loadEnv();
  return process.env[name] ?? fallback;
}

export const DEFAULT_DENSE_URL = "https://index-climbmix-jina-v5-nano.dsync.net";
export const DEFAULT_PYSERINI_SEARCH_URL =
  "http://api.castorini.uwaterloo.ca/v1/climbmix-400b/search";

export function denseBaseUrl(): string {
  return (getEnv("DENSE_SEARCH_URL", DEFAULT_DENSE_URL) as string).replace(/\/+$/, "");
}

/** Base URL for pyserini doc fetch: PYSERINI_SEARCH_URL minus trailing /search. */
export function pyseriniBaseUrl(): string {
  const search = getEnv("PYSERINI_SEARCH_URL", DEFAULT_PYSERINI_SEARCH_URL) as string;
  return search.replace(/\/+$/, "").replace(/\/search$/, "");
}

export function pyseriniToken(): string | undefined {
  return getEnv("PYSERINI_API_TOKEN");
}

/** HTTP Basic token from SEARCH_API_KEY ("user:pass" auto-encoded, else as-is). */
export function denseBasicToken(): string | undefined {
  const key = getEnv("SEARCH_API_KEY");
  if (!key) return undefined;
  return key.includes(":") ? Buffer.from(key).toString("base64") : key;
}
