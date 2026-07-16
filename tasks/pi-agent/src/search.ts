/**
 * ClimbMix retrieval clients + RRF fusion — a faithful TS port of the Python
 * reference implementations in `src/utils/` (search.py, search_dense.py,
 * search_sparse.py, fetch_doc.py, search_types.py).
 */
import {
  DENSE_SEARCH_URL,
  PYSERINI_API_TOKEN,
  PYSERINI_DOC_URL,
  SEARCH_API_KEY,
  SPARSE_SEARCH_URL,
  USER_AGENT,
} from "./config.js";

export type Kind = "document" | "chunk";

/** One normalized retrieval result, uniform across all backends. */
export interface SearchHit {
  /** Retrieval-unit id: chunk id (`<docid>_p<n>`) or docid. */
  id: string;
  /** Parent document id (the `_p<n>`-stripped parent for chunks). */
  docid: string;
  kind: Kind;
  score: number;
  rank: number;
  text: string | null;
  meta: Record<string, unknown>;
}

/** Chunk ids follow `<docid>_p<page>` (page from 1). */
const CHUNK_SUFFIX_RE = /_p\d+$/;

export function classifyId(unitId: string): { kind: Kind; docid: string } {
  if (CHUNK_SUFFIX_RE.test(unitId)) {
    return { kind: "chunk", docid: unitId.replace(CHUNK_SUFFIX_RE, "") };
  }
  return { kind: "document", docid: unitId };
}

export function makeHit(
  unitId: string,
  opts: {
    score: number;
    rank: number;
    text: string | null;
    meta?: Record<string, unknown>;
    kind?: Kind;
    docid?: string;
  },
): SearchHit {
  let { kind, docid } = opts;
  if (kind === undefined || docid === undefined) {
    const derived = classifyId(unitId);
    kind = kind ?? derived.kind;
    docid = docid ?? derived.docid;
  }
  return {
    id: unitId,
    docid,
    kind,
    score: opts.score,
    rank: opts.rank,
    text: opts.text,
    meta: opts.meta ?? {},
  };
}

/** Authorization header from SEARCH_API_KEY ("user:pass" → base64 Basic). */
export function authHeaders(): Record<string, string> {
  if (!SEARCH_API_KEY) return {};
  const token = SEARCH_API_KEY.includes(":")
    ? Buffer.from(SEARCH_API_KEY, "utf-8").toString("base64")
    : SEARCH_API_KEY;
  return { Authorization: `Basic ${token}` };
}

async function postJson(
  url: string,
  body: unknown,
  headers: Record<string, string>,
  timeoutMs: number,
): Promise<any> {
  const res = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      // A non-default User-Agent is required: the endpoints 403 stock UAs.
      "User-Agent": USER_AGENT,
      ...headers,
    },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(timeoutMs),
  });
  if (!res.ok) {
    throw new Error(`POST ${url} -> HTTP ${res.status}: ${(await res.text()).slice(0, 300)}`);
  }
  return res.json();
}

/** Dense retrieval — Jina-v5 DiskANN `/search`. */
export async function searchDense(
  query: string,
  k = 10,
  opts: { withText?: boolean; timeoutMs?: number } = {},
): Promise<SearchHit[]> {
  const body = { query, k, with_text: opts.withText ?? true };
  const data = await postJson(`${DENSE_SEARCH_URL}/search`, body, authHeaders(), opts.timeoutMs ?? 30_000);
  const hits: SearchHit[] = [];
  const raw: any[] = data?.hits ?? [];
  raw.forEach((h, i) => {
    hits.push(
      makeHit(h.docid, {
        score: Number(h.score),
        rank: h.rank ?? i + 1,
        text: h.text ?? null,
        meta: { source: "dense" },
      }),
    );
  });
  return hits;
}

/** Sparse retrieval — Anserini/Lucene BM25 index-server `/api/search`. */
export async function searchSparse(
  query: string,
  k = 10,
  opts: { timeoutMs?: number } = {},
): Promise<SearchHit[]> {
  const body = { query, hits: k };
  const data = await postJson(`${SPARSE_SEARCH_URL}/api/search`, body, authHeaders(), opts.timeoutMs ?? 30_000);
  const hits: SearchHit[] = [];
  const raw: any[] = data?.hits?.hits ?? [];
  raw.forEach((h, i) => {
    const source = h._source ?? {};
    hits.push(
      makeHit(h._id, {
        score: Number(h._score),
        rank: i + 1,
        text: source.contents ?? null,
        meta: { source: "sparse", _index: h._index },
      }),
    );
  });
  return hits;
}

/** Fuse ranked SearchHit lists via RRF into a single ranked list.
 *  rrf_score(d) = sum over lists: weight * 1 / (rrf_k + rank_in_list) */
export function rrfFuse(
  rankings: SearchHit[][],
  opts: { rrfK?: number; weights?: number[]; sourceNames?: string[] } = {},
): SearchHit[] {
  const rrfK = opts.rrfK ?? 60;
  const weights = opts.weights ?? rankings.map(() => 1.0);
  const sourceNames = opts.sourceNames ?? rankings.map((_, i) => `src${i}`);

  // Fuse on the retrieval-unit id so distinct chunks of a doc stay separate.
  const fused = new Map<string, SearchHit>();
  rankings.forEach((ranking, li) => {
    const w = weights[li];
    const name = sourceNames[li];
    ranking.forEach((hit, idx) => {
      const rank = idx + 1;
      const unitId = hit.id;
      let entry = fused.get(unitId);
      if (!entry) {
        entry = {
          id: unitId,
          docid: hit.docid,
          kind: hit.kind,
          score: 0.0,
          rank: 0,
          text: null,
          meta: { sources: {} as Record<string, { rank: number; score: number }> },
        };
        fused.set(unitId, entry);
      }
      entry.score += w * (1.0 / (rrfK + rank));
      (entry.meta.sources as Record<string, { rank: number; score: number }>)[name] = {
        rank,
        score: hit.score,
      };
      // Keep any available text (backends may or may not include it).
      if (entry.text === null && hit.text != null) entry.text = hit.text;
    });
  });

  const ordered = [...fused.values()].sort((a, b) => b.score - a.score);
  ordered.forEach((e, i) => {
    e.rank = i + 1;
  });
  return ordered;
}

/** Hybrid dense+sparse search fused with RRF; returns top-k fused hits.
 *  Per-backend depth defaults to max(k, 50) so fusion has enough candidates. */
export async function search(
  query: string,
  k = 10,
  opts: {
    denseK?: number;
    sparseK?: number;
    rrfK?: number;
    withText?: boolean;
    weights?: [number, number];
    timeoutMs?: number;
  } = {},
): Promise<SearchHit[]> {
  const depth = Math.max(k, 50);
  const dk = opts.denseK ?? depth;
  const sk = opts.sparseK ?? depth;

  const [dense, sparse] = await Promise.all([
    searchDense(query, dk, { withText: opts.withText ?? true, timeoutMs: opts.timeoutMs }),
    searchSparse(query, sk, { timeoutMs: opts.timeoutMs }),
  ]);

  const fused = rrfFuse([dense, sparse], {
    rrfK: opts.rrfK ?? 60,
    weights: opts.weights ? [...opts.weights] : undefined,
    sourceNames: ["dense", "sparse"],
  });
  return fused.slice(0, k);
}

function docText(doc: unknown): string {
  if (typeof doc === "string") return doc;
  if (doc && typeof doc === "object") {
    for (const key of ["text", "contents", "segment", "body"]) {
      const v = (doc as Record<string, unknown>)[key];
      if (typeof v === "string") return v;
    }
  }
  return JSON.stringify(doc);
}

/** Fetch full ClimbMix document text by docid — Pyserini hosted API. */
export async function fetchDoc(
  docid: string,
  opts: { timeoutMs?: number } = {},
): Promise<{ docid: string; text: string }> {
  const url = `${PYSERINI_DOC_URL}/${encodeURIComponent(docid)}`;
  const headers: Record<string, string> = { "User-Agent": USER_AGENT };
  if (PYSERINI_API_TOKEN) headers.Authorization = `Bearer ${PYSERINI_API_TOKEN}`;
  const res = await fetch(url, {
    method: "GET",
    headers,
    signal: AbortSignal.timeout(opts.timeoutMs ?? 30_000),
  });
  if (!res.ok) {
    throw new Error(`GET ${url} -> HTTP ${res.status}: ${(await res.text()).slice(0, 300)}`);
  }
  const data: any = await res.json();
  return { docid: data?.docid ?? docid, text: docText(data?.doc) };
}
