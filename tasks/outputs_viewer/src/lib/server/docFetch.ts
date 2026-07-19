import "server-only";
import {
  denseBaseUrl,
  denseBasicToken,
  pyseriniBaseUrl,
  pyseriniToken,
  sparseDocUrl,
} from "./env";
import { isChunkId, parentDocid, type DocResult } from "@/lib/types";

const UA = "trec-rag-outputs-viewer/1.0";
const TIMEOUT_MS = 25_000;

/** Tiny LRU so repeated citation clicks don't re-hit the backends. */
const cache = new Map<string, DocResult>();
const CACHE_MAX = 300;
function cachePut(id: string, r: DocResult) {
  if (cache.size >= CACHE_MAX) {
    const oldest = cache.keys().next().value;
    if (oldest !== undefined) cache.delete(oldest);
  }
  cache.set(id, r);
}

async function fetchDense(docid: string): Promise<string | null> {
  const token = denseBasicToken();
  const headers: Record<string, string> = { "User-Agent": UA };
  if (token) headers.Authorization = `Basic ${token}`;
  const res = await fetch(`${denseBaseUrl()}/doc/${encodeURIComponent(docid)}`, {
    headers,
    signal: AbortSignal.timeout(TIMEOUT_MS),
    cache: "no-store",
  });
  if (!res.ok) return null;
  const data = (await res.json()) as { docid?: string; text?: string };
  return typeof data.text === "string" ? data.text : null;
}

/**
 * Doc-by-id on the sparse (BM25) server. Tolerant to the response shapes the
 * proxy might use ({text} | {doc} | {contents} | ES {_source:{contents}}).
 * Returns null while the proxy lacks the route (404 today).
 */
async function fetchSparse(docid: string): Promise<string | null> {
  const token = denseBasicToken(); // same SEARCH_API_KEY guards both dsync services
  const headers: Record<string, string> = { "User-Agent": UA };
  if (token) headers.Authorization = `Basic ${token}`;
  const res = await fetch(`${sparseDocUrl()}/${encodeURIComponent(docid)}`, {
    headers,
    signal: AbortSignal.timeout(TIMEOUT_MS),
    cache: "no-store",
  });
  if (!res.ok) return null;
  const data = (await res.json()) as {
    text?: string;
    doc?: string;
    contents?: string;
    _source?: { contents?: string };
  };
  const text = data.text ?? data.doc ?? data.contents ?? data._source?.contents;
  return typeof text === "string" ? text : null;
}

async function fetchPyserini(docid: string): Promise<string | null> {
  const token = pyseriniToken();
  const headers: Record<string, string> = { "User-Agent": UA };
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(`${pyseriniBaseUrl()}/doc/${encodeURIComponent(docid)}`, {
    headers,
    signal: AbortSignal.timeout(TIMEOUT_MS),
    cache: "no-store",
  });
  if (!res.ok) return null;
  const data = (await res.json()) as { docid?: string; doc?: string };
  return typeof data.doc === "string" ? data.doc : null;
}

/**
 * Fetch a document / chunk by id, server-side only (tokens stay here).
 *
 * Strategy — the dense endpoint (search_serve FastAPI, GET /doc/{docid}) is
 * preferred: it is the same corpus and ~1 ms per fetch. Probing showed its
 * docstore is keyed by PLAIN docids (chunk ids `_p<n>` 404), so chunk ids are
 * attempted as-is first, then fall back to the parent docid. Pyserini
 * (Bearer token) is the fallback when the dense endpoint is unavailable.
 */
/**
 * Fetch the FULL parent document. Only doc-level (sparse-side) indexes hold
 * whole documents — the dense index is (becoming) page-only — so this tries
 * our sparse BM25 server's doc-by-id first, then the official Pyserini REST
 * API. Page ids (`_p<n>`) resolve to their parent docid first.
 */
export async function fetchFullDoc(requestedId: string): Promise<DocResult | null> {
  const cacheKey = `full:${requestedId}`;
  const hit = cache.get(cacheKey);
  if (hit) return hit;

  const parent = parentDocid(requestedId);
  for (const source of ["sparse", "pyserini"] as const) {
    try {
      const text =
        source === "sparse" ? await fetchSparse(parent) : await fetchPyserini(parent);
      if (text != null) {
        const result: DocResult = {
          requestedId,
          resolvedId: parent,
          kind: "document",
          source,
          parentFallback: isChunkId(requestedId),
          text,
        };
        cachePut(cacheKey, result);
        return result;
      }
    } catch {
      // unreachable backend — try the next source
    }
  }
  return null;
}

export async function fetchDoc(
  requestedId: string,
  prefer?: "sparse" | "dense",
): Promise<DocResult | null> {
  const cacheKey = prefer ? `${prefer}:${requestedId}` : requestedId;
  const hit = cache.get(cacheKey);
  if (hit) return hit;

  const chunk = isChunkId(requestedId);
  const parent = parentDocid(requestedId);

  // Candidate (id, parentFallback) pairs in preference order.
  const candidates: { id: string; parentFallback: boolean }[] = chunk
    ? [
        { id: requestedId, parentFallback: false },
        { id: parent, parentFallback: true },
      ]
    : [{ id: requestedId, parentFallback: false }];

  // Lead with the engine that actually retrieved the unit: a keyword hit is
  // served by the sparse side, a semantic hit by the dense endpoint. The
  // Pyserini REST API is the always-available fallback.
  const sources: ("sparse" | "dense" | "pyserini")[] =
    prefer === "sparse"
      ? ["sparse", "pyserini", "dense"]
      : ["dense", "pyserini"];

  for (const source of sources) {
    for (const c of candidates) {
      try {
        const text =
          source === "dense"
            ? await fetchDense(c.id)
            : source === "sparse"
              ? await fetchSparse(c.id)
              : await fetchPyserini(c.id);
        if (text != null) {
          const result: DocResult = {
            requestedId,
            resolvedId: c.id,
            kind: chunk && !c.parentFallback ? "chunk" : "document",
            source,
            parentFallback: c.parentFallback,
            text,
          };
          cachePut(cacheKey, result);
          return result;
        }
      } catch {
        // network error / timeout on this backend: try the next candidate/source
      }
    }
  }
  return null;
}
