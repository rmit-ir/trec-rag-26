/**
 * Config — loaded from the repo-root `.env` (dotenv), mirroring the Python
 * reference clients in `src/utils/`.
 */
import { config as loadDotenv } from "dotenv";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

/** Repo root = parents[2] of tasks/pi-agent/src/config.ts. */
export const REPO_ROOT = path.resolve(__dirname, "..", "..", "..");

loadDotenv({ path: path.join(REPO_ROOT, ".env") });

export const DEFAULT_DENSE_URL = "https://index-climbmix-jina-v5-nano.dsync.net";
export const DEFAULT_SPARSE_URL = "https://index-climbmix-bm25.dsync.net";
export const DEFAULT_PYSERINI_DOC_URL =
  "http://api.castorini.uwaterloo.ca/v1/climbmix-400b/doc";

export const DENSE_SEARCH_URL = (process.env.DENSE_SEARCH_URL || DEFAULT_DENSE_URL).replace(/\/+$/, "");
export const SPARSE_SEARCH_URL = (process.env.SPARSE_SEARCH_URL || DEFAULT_SPARSE_URL).replace(/\/+$/, "");
/** Doc-fetch base. PYSERINI_DOC_URL wins; else derive from PYSERINI_SEARCH_URL
 * (its `/search` suffix swapped for `/doc`); else the hosted default. */
export const PYSERINI_DOC_URL = (
  process.env.PYSERINI_DOC_URL ||
  (process.env.PYSERINI_SEARCH_URL
    ? process.env.PYSERINI_SEARCH_URL.replace(/\/+$/, "").replace(/\/search$/, "") + "/doc"
    : DEFAULT_PYSERINI_DOC_URL)
).replace(/\/+$/, "");

export const SEARCH_API_KEY = process.env.SEARCH_API_KEY || "";
export const PYSERINI_API_TOKEN = process.env.PYSERINI_API_TOKEN || "";

/** Both hosted search endpoints 403 the default UA — send a custom one. */
export const USER_AGENT = "trec-rag-search/1.0";

export const DEFAULT_MODEL_ID = "au.anthropic.claude-sonnet-5";
export const DEFAULT_K = 10;
export const DEFAULT_MAX_ROUNDS = 12;

export const TEAM_ID = "rmit-ir";

export const DEFAULT_TOPICS_TSV = path.join(
  REPO_ROOT,
  "data/official/trec-rag-2026-data/trec-rag-2026/development-data/topics/research-rubrics-topics-dev.tsv",
);

/** Run artifacts always land under repo-root data/, never under tasks/. */
export const OUTPUT_DIR = path.join(REPO_ROOT, "data", "outputs", "pi-agent");
