import type { TokenStats } from "./types";

/**
 * Per-model API pricing, USD per 1,000,000 tokens.
 *
 * These are OpenAI's public list prices (standard tier), verified against
 * https://developers.openai.com/api/docs/pricing on 2026-07-19. Azure OpenAI
 * *Global Standard* deployments are priced identically to these OpenAI list
 * prices, so the numbers below are correct for a Global Standard Azure backend.
 * If you run under Azure *Regional* / *Data Zone* Standard (a premium over
 * Global), a PTU deployment (hourly, not per-token), or any other contracted /
 * gateway rate, override the entry here — this map is the single source of
 * truth for the "cost" chip.
 *
 * `cacheRead` is the discounted rate for cache-hit input tokens (OpenAI bills
 * these at 10% of the input rate). `cacheWrite` defaults to the input rate when
 * omitted (OpenAI does not bill cache writes separately).
 */
export interface ModelPrice {
  input: number;
  output: number;
  cacheRead?: number;
  cacheWrite?: number;
}

export const MODEL_PRICING: Record<string, ModelPrice> = {
  "gpt-5.6-sol": { input: 5.0, cacheRead: 0.5, output: 30.0 },
  "gpt-5.6-terra": { input: 2.5, cacheRead: 0.25, output: 15.0 },
  "gpt-5.6-luna": { input: 1.0, cacheRead: 0.1, output: 6.0 },
  "gpt-5.5": { input: 5.0, cacheRead: 0.5, output: 30.0 },
  "gpt-5.4": { input: 2.5, cacheRead: 0.25, output: 15.0 },
};

/** Look up a price, tolerating case and a leading provider prefix (e.g. "openai/"). */
export function resolveModelPrice(model?: string | null): ModelPrice | null {
  if (!model) return null;
  const key = model.toLowerCase().trim();
  return MODEL_PRICING[key] ?? MODEL_PRICING[key.replace(/^[^/]+\//, "")] ?? null;
}

export interface CostBreakdown {
  total: number;
  fullInput: number;
  cachedInput: number;
  cacheWriteInput: number;
  output: number;
}

/**
 * Cache-aware run cost from `trace.summary.tokens` × model price.
 *
 * Full-price prompt tokens come from `input_uncached`; when that field is
 * absent we back it out of `input - cache_read - cache_write`. Cache-hit tokens
 * (`cache_read`) bill at the discounted `cacheRead` rate. Returns null when the
 * model has no price entry or there are no tokens to charge for.
 */
export function computeCost(
  model: string | null | undefined,
  tokens: TokenStats | null | undefined,
): CostBreakdown | null {
  const price = resolveModelPrice(model);
  if (!price || !tokens) return null;

  const cacheRead = tokens.cache_read ?? 0;
  const cacheWrite = tokens.cache_write ?? 0;
  const fullInputTokens =
    tokens.input_uncached ??
    (tokens.input != null ? tokens.input - cacheRead - cacheWrite : 0);
  const outputTokens = tokens.output ?? 0;

  const cacheReadRate = price.cacheRead ?? price.input;
  const cacheWriteRate = price.cacheWrite ?? price.input;

  const fullInput = (Math.max(fullInputTokens, 0) / 1e6) * price.input;
  const cachedInput = (cacheRead / 1e6) * cacheReadRate;
  const cacheWriteInput = (cacheWrite / 1e6) * cacheWriteRate;
  const output = (outputTokens / 1e6) * price.output;
  const total = fullInput + cachedInput + cacheWriteInput + output;

  if (total <= 0) return null;
  return { total, fullInput, cachedInput, cacheWriteInput, output };
}

/** Compact USD label: sub-cent → 4dp, small → 3dp, else 2dp. */
export function fmtUsd(amount: number): string {
  if (amount < 0.01) return `$${amount.toFixed(4)}`;
  if (amount < 1) return `$${amount.toFixed(3)}`;
  return `$${amount.toFixed(2)}`;
}
