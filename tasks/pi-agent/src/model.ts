/**
 * Bedrock model resolution for pi-ai.
 *
 * pi-ai ships a built-in `amazon-bedrock` provider (api
 * `bedrock-converse-stream`, backed by @aws-sdk/client-bedrock-runtime with
 * the standard AWS credential chain — AWS_ACCESS_KEY_ID / SECRET / SESSION
 * TOKEN env vars — and AWS_REGION for the endpoint). Its model catalog covers
 * many `au.anthropic.*` ids but not all of the ones we use (e.g.
 * `au.anthropic.claude-sonnet-5`), so unknown ids get a custom Model spec —
 * pi-ai supports custom models natively.
 */
import { getModels, type Model } from "@mariozechner/pi-ai";

/**
 * Claude models from 4.6 on (Sonnet 5, Opus 4.8, ...) only accept
 * `thinking.type: "adaptive"` + `output_config.effort`; the older
 * budget-token `thinking.type: "enabled"` payload is rejected.
 * pi-ai 0.73.1 gates its adaptive-thinking payload behind a substring match
 * on the model id/name ("opus-4-6" | "opus-4-7" | "sonnet-4-6"), which
 * predates these ids — so for such models we embed a "sonnet-4-6" marker in
 * the (display-only) model name to route them onto the adaptive path.
 */
const ADAPTIVE_ONLY_RE = /claude-(sonnet-5|opus-4-([89]|\d{2,})|sonnet-4-([7-9]|\d{2,}))/;

export function resolveBedrockModel(modelId: string): Model<"bedrock-converse-stream"> {
  const known = getModels("amazon-bedrock").find((m) => m.id === modelId);
  if (known) return known as Model<"bedrock-converse-stream">;

  // Custom model spec. With AWS_REGION configured, pi-ai's Bedrock provider
  // resolves the endpoint from the region and ignores baseUrl.
  const region = process.env.AWS_REGION || process.env.AWS_DEFAULT_REGION || "us-east-1";
  const adaptiveMarker = ADAPTIVE_ONLY_RE.test(modelId) ? " [sonnet-4-6 adaptive-thinking compat]" : "";
  return {
    id: modelId,
    name: `Bedrock ${modelId}${adaptiveMarker}`,
    api: "bedrock-converse-stream",
    provider: "amazon-bedrock",
    baseUrl: `https://bedrock-runtime.${region}.amazonaws.com`,
    reasoning: true,
    input: ["text"],
    // Cost table unknown for custom ids; zeros keep usage accounting harmless.
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
    contextWindow: 200_000,
    maxTokens: 64_000,
  };
}
