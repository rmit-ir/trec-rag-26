import "server-only";
import { denseBaseUrl, denseBasicToken, sparseDocUrl } from "./env";
import { isChunkId, type DocResult } from "@/lib/types";

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

/**
 * Get a document / chunk by id, AS-IS, from the search index docstore.
 *
 * Both dense and sparse now return page/chunk ids (`<docid>_p<page>`) with
 * chunk-segment text, so the id is passed through unchanged — a chunk id
 * yields exactly that chunk. There is no backend-specific id parsing and no
 * whole-document reconstruction: whichever docstore answers by id wins. The
 * dense endpoint (search_serve `GET /doc/{id}`, chunk-keyed) is tried first
 * because it is the same corpus at ~1 ms/fetch; the sparse doc-by-id is the
 * fallback. Tokens stay server-side.
 */
export async function fetchDoc(requestedId: string): Promise<DocResult | null> {
  const hit = cache.get(requestedId);
  if (hit) return hit;

  for (const source of ["dense", "sparse"] as const) {
    try {
      const text =
        source === "dense"
          ? await fetchDense(requestedId)
          : await fetchSparse(requestedId);
      if (text != null) {
        const result: DocResult = {
          requestedId,
          resolvedId: requestedId,
          kind: isChunkId(requestedId) ? "chunk" : "document",
          source,
          parentFallback: false,
          text,
        };
        cachePut(requestedId, result);
        return result;
      }
    } catch {
      // network error / timeout on this backend: try the next source
    }
  }
  return null;
}
