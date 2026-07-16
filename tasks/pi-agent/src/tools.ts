/**
 * pi AgentTool definitions — the ONLY retrieval surface of the agent.
 * Everything talks to the hosted ClimbMix services; there is no web search.
 */
import { Type } from "@mariozechner/pi-ai";
import type { AgentTool } from "@mariozechner/pi-agent-core";
import { classifyId, fetchDoc, search, type SearchHit } from "./search.js";

/** Per-hit summary recorded in the trajectory (parent docids). */
export interface ReturnedHit {
  docid: string;
  score: number;
}

/** Structured details every tool returns for trajectory recording. */
export interface ToolDetails {
  returned?: ReturnedHit[];
  returnedDocids?: string[];
}

const SNIPPET_CHARS = 900;
const DOC_MAX_CHARS = 20_000;

function formatHits(hits: SearchHit[]): string {
  if (hits.length === 0) return "No results.";
  const lines: string[] = [];
  for (const h of hits) {
    const snippet = (h.text ?? "").replace(/\s+/g, " ").trim().slice(0, SNIPPET_CHARS);
    const sources = JSON.stringify(h.meta.sources ?? {});
    lines.push(
      `${h.rank}. docid=${h.docid} (unit=${h.id}) rrf_score=${h.score.toFixed(5)} sources=${sources}\n   ${snippet}`,
    );
  }
  return lines.join("\n");
}

export function createSearchTool(defaultK: number): AgentTool<any, ToolDetails> {
  return {
    name: "search",
    label: "ClimbMix hybrid search",
    description:
      "Search the ClimbMix corpus with a hybrid dense (Jina-v5) + sparse (BM25) retriever fused via " +
      "Reciprocal Rank Fusion. Returns ranked passages with their parent document ids (docid) and text " +
      "snippets. Issue focused keyword-style or natural-language queries; iterate with different phrasings " +
      "to cover all aspects of the topic.",
    parameters: Type.Object({
      query: Type.String({ description: "The search query." }),
      k: Type.Optional(
        Type.Integer({
          minimum: 1,
          maximum: 50,
          description: `Number of fused results to return (default ${defaultK}).`,
        }),
      ),
    }),
    // Stateless HTTP call — safe to run concurrently with other same-turn calls.
    executionMode: "parallel",
    execute: async (_toolCallId, params) => {
      const { query, k: pk } = params as { query: string; k?: number };
      const k = pk ?? defaultK;
      const hits = await search(query, k);
      const returned: ReturnedHit[] = hits.map((h) => ({ docid: h.docid, score: h.score }));
      return {
        content: [{ type: "text", text: formatHits(hits) }],
        details: { returned, returnedDocids: returned.map((r) => r.docid) },
      };
    },
  };
}

export function createGetDocumentTool(): AgentTool<any, ToolDetails> {
  return {
    name: "get_document",
    label: "ClimbMix document fetch",
    description:
      "Fetch the full text of one ClimbMix document by its docid (e.g. shard_00459_61697). Use this to read " +
      "a promising document in full before citing it. Chunk ids like <docid>_p3 are accepted; the parent " +
      "document is fetched.",
    parameters: Type.Object({
      docid: Type.String({ description: "ClimbMix document id (chunk ids are mapped to their parent doc)." }),
    }),
    // Stateless HTTP call — safe to run concurrently with other same-turn calls.
    executionMode: "parallel",
    execute: async (_toolCallId, params) => {
      const { docid } = classifyId((params as { docid: string }).docid);
      const doc = await fetchDoc(docid);
      let text = doc.text;
      if (text.length > DOC_MAX_CHARS) {
        text = `${text.slice(0, DOC_MAX_CHARS)}\n...[truncated ${text.length - DOC_MAX_CHARS} chars]`;
      }
      return {
        content: [{ type: "text", text: `docid=${doc.docid}\n${text}` }],
        details: { returnedDocids: [doc.docid] },
      };
    },
  };
}
