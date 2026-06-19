# AI Agent Integration Landscape: Storyblok & Directus

Sub-agent research strand. All claims carry inline source URLs. Last updated 2026-06-19.

---

## PART A — STORYBLOK

Storyblok is a headless CMS with a **Content Delivery API** (read) and a **Management API** (write/CRUD). AI-agent connectivity spans an official hosted MCP server, native "AI Suite" features, official SDKs/REST, community MCP servers, and webhooks.

### A1. Official Storyblok MCP Server (HOSTED) — primary agent integration

- **What/where:** Official, maintained by Storyblok. Hosted endpoint `https://mcp.labs.storyblok.com/mcp`; setup landing page `https://mcp.labs.storyblok.com/`. Source: <https://mcp.labs.storyblok.com/>, <https://github.com/storyblok/mcp-server>.
- **Status of the repo:** The original self-hosted repo `storyblok/mcp-server` (TypeScript) is **ARCHIVED as of 2026-03-30** and explicitly superseded by the hosted server (no local clone / Node.js needed). Source: <https://github.com/storyblok/mcp-server>. So the current official path is **closed-hosted** (the archived local code remains open under the repo, but the live hosted service is the supported route).
- **Pattern/category:** Remote/hosted MCP server fronting the Storyblok Management API; "still in Innovation phase" per repo. Source: <https://github.com/storyblok/mcp-server>.
- **Transport:** HTTP (streamable HTTP). Source: <https://mcp.labs.storyblok.com/>.
- **Auth:** Bearer token = Storyblok **Personal Access Token / Management Token** in the `Authorization` header. Token from Storyblok app → My Account → Personal access tokens. Source: <https://mcp.labs.storyblok.com/>.
- **Connection to CMS:** Wraps the Storyblok **Management API** as a generic, schema-driven gateway (it does not hard-code one MCP tool per endpoint; instead it exposes search/describe/execute meta-tools over the API's OpenAPI operations).
- **Role scoping:** Access can be filtered with a `?role=` query parameter on the MCP URL. Source: <https://mcp.labs.storyblok.com/>.
- **Install (Claude Code example):** `claude mcp add --transport http Storyblok https://mcp.labs.storyblok.com/mcp --header "Authorization: Bearer <token>"`. Clients listed: Claude Code, Claude Desktop, Cursor, Windsurf, VS Code, Gemini CLI, LM Studio. Source: <https://github.com/storyblok/mcp-server>, <https://mcp.labs.storyblok.com/>.
- **Extensibility of tools:** Tools are NOT one-per-resource. They are generic meta-operations over the Management API's operation catalog, so new API operations become reachable automatically via `search`/`describe`/`execute_*` rather than requiring new tool code. (Design inference from the tool set below; the meta-tool design is documented on the setup page.)

**Tool inventory (PRIMARY SOURCE: hosted setup page <https://mcp.labs.storyblok.com/>):**

| Tool | What it does | Notes / params (as documented) |
|---|---|---|
| `search` | Discover available Storyblok API operations by keyword. | Returns matching `operationId`s, behavior hints, summaries, available response fields. Keyword input. |
| `describe` | Get full parameter docs for an operation. | Path/query params + request-body schema for a given operationId. |
| `execute_readonly` | Run safe read-only (GET) operations. | Listing/retrieving resources. |
| `execute_mutating` | Run write operations (POST/PUT/PATCH). | Creating/updating content. |
| `execute_destructive` | Run delete operations. | Requires explicit user confirmation before executing. |
| `upload_asset` | **Step 1 of asset upload.** Generates a signed S3 URL + a ready-to-use `curl` command. | Returns signed upload target. |
| `upload_asset_finish` | **Step 2 of asset upload.** Finalizes the upload after the file is transferred to S3. | Completes the multi-step signed upload. |

> Exact JSON parameter schemas (types/required) for these tools are NOT published on the setup page in a copyable form — descriptions only. The signed-upload split (`upload_asset` + `upload_asset_finish`) is confirmed. **UNVERIFIED:** precise field-level schemas of each tool.

**Media/file upload handling (probed):** Storyblok asset upload is intrinsically **multi-step (signed upload)**. Via the MCP server it is modeled as TWO tools: `upload_asset` (returns a signed S3 `post_url` + fields + a curl command) then `upload_asset_finish` (finalize). This mirrors the underlying Management API 3-step flow: (1) sign request → (2) POST the file as `multipart/form-data` to the returned Amazon S3 `post_url` including all `fields`, (3) finalize so Storyblok records MIME type + content length. Sources: <https://mcp.labs.storyblok.com/>, <https://www.storyblok.com/docs/api/management/assets/upload-and-replace-assets>, <https://www.storyblok.com/docs/api/management/assets/get-signed-response>. The "agent can't directly stream a binary" gap is handled by the MCP server emitting a curl command for the out-of-band S3 POST.

### A2. Storyblok native AI features ("AI Suite" / Ideation Room)

- **AI Suite** (launched ~Jan 2025): localization, SEO, accessibility helpers built into the editor. Includes **AI Translations** (translate full pages or individual fields one-click), **AI SEO**, and **AI Alt-Text** generation. Sources: <https://www.storyblok.com/lp/ai-suite>, <https://www.storyblok.com/mp/ai-features>.
- **AI Alt-text generation:** Suggested directly in the Image Upload / Image Editor UI on upload; supports non-English alt text when the language is configured in i18n settings and the Alt text field is translatable. Source: <https://www.storyblok.com/cl/2025-march-ai-alt-text-generation>, <https://www.storyblok.com/docs/manuals/ai-assistance>.
- **Ideation Room (Beta):** Collaborative AI brainstorming — editors describe a need, AI generates outlines, headlines, drafts; used to draft/improve articles. AI features there are optional. Source: <https://www.storyblok.com/docs/guide/in-depth/ideation-room>.
- **Bring-your-own-provider:** Storyblok AI is BYO-credentials — connect your own OpenAI / Google Gemini (and per marketing also Perplexity/Claude) API key and pick the model (GPT-4, GPT-4 Turbo, GPT-4o, Gemini, etc.). You control usage/cost/compliance; "no hidden layers." Sources: <https://www.storyblok.com/mp/ai-features>, <https://www.storyblok.com/mp/custom-ai-features>.
- **Custom AI Features:** Storyblok also lets teams define their own AI features (custom prompts/black-box-free), per <https://www.storyblok.com/mp/custom-ai-features>.

> These are **editor-facing native AI**, not an agent-callable API per se. An external agent reaches them indirectly (via the CMS/Management API content they produce), not as MCP tools.

### A3. Storyblok REST / SDK layer (DIY agent wrappers)

- **`storyblok-js-client`** — official universal JS client for both Content Delivery + Management APIs. npm: `storyblok-js-client`. Repo <https://github.com/storyblok/storyblok-js-client>. Source: <https://www.npmjs.com/package/storyblok-js-client>, <https://www.storyblok.com/docs/libraries/js/universal-api-client>. This is the standard building block for a custom REST/GraphQL wrapper or agent SDK tool.
- **Asset upload via SDK = 3 steps** (sign → POST to S3 multipart/form-data with all `fields` + the file → finalize). Source: <https://github.com/storyblok/storyblok-docs/blob/master/content/management/v1/core-resources/assets/upload-asset.md>, <https://www.storyblok.com/docs/concepts/assets>.
- Storyblok also has a **GraphQL Content Delivery API** (read-only) usable by agents for retrieval. (General platform feature.)
- Tutorial showing the "code your own MCP server against Storyblok data" pattern: <https://www.storyblok.com/tp/bring-your-storyblok-data-into-claude-by-coding-an-mcp-server>.

### A4. Community / third-party Storyblok MCP servers

| Repo | Maintainer | Scale / notable | License | Source |
|---|---|---|---|---|
| `hypescale/storyblok-mcp-server` | Community (Martin Kogut / hypescale) | **160 tools across 30 modules** (Stories 18, Components 9, Assets 9; Workflows/Releases/Datasources/Tags/Webhooks 5 each; Space Roles/Collaborators 4-5; +20 modules). One-tool-per-resource design (opposite of the official meta-tool design). | MIT | <https://github.com/hypescale/storyblok-mcp-server> |
| `Kiran1689/storyblok-mcp-server` | Community | Modular/extensible MCP for spaces, stories, components, assets, workflows. | (repo) | <https://github.com/Kiran1689/storyblok-mcp-server> |
| `ArjunCodess/storyblok-mcp` | Community | Natural-language CMS management. Listed on mcpservers.org. | (repo) | <https://github.com/ArjunCodess/storyblok-mcp> |
| `zerdos/mcp-storyblok-server` | Community | Manage Storyblok. | (repo) | <https://github.com/zerdos/mcp-storyblok-server> |
| `harlley/storyblok-mcp` | Community | Manage **components** via natural-language descriptions. | (repo) | <https://github.com/harlley/storyblok-mcp> |

- **hypescale transport/auth:** native fetch over HTTP/HTTPS; three env vars (Space ID, Management API token, Public/Preview token); assets uploaded/organized into folders via bulk tools. Community-maintained, NOT official. Source: <https://github.com/hypescale/storyblok-mcp-server>.

### A5. Storyblok webhooks
- Storyblok supports webhooks (publish/unpublish/etc.) — surfaced as a manageable resource in the community MCP servers (e.g. hypescale "Webhooks: 5 tools"). Useful as an event-driven trigger into agent pipelines. Source: <https://github.com/hypescale/storyblok-mcp-server>.

---

## PART B — DIRECTUS

Directus is an open-source data platform / headless CMS over any SQL DB, with REST + GraphQL APIs, **Directus Automate (Flows)** for automation, and — notably — a **native MCP server built into core**.

### B1. Directus NATIVE MCP (built into core) — the headline integration

- **What/where:** Native Model Context Protocol support **built into Directus core**, shipped in **v11.13 (released 2025-11-07)**; MCP baseline requires **v11.12+**. Sources: <https://directus.com/resources/directus-v11-13-release>, <https://directus.com/docs/guides/ai/mcp>, search result confirming "MCP requires Directus v11.12+".
- **Open source:** Directus core is open source (BSL/with Directus license terms); the MCP ships inside it. Distinct from the standalone package below.
- **Pattern/category:** First-party, in-process MCP server embedded in the CMS runtime (not a sidecar). This is the notable "built-in MCP" — no separate process for current versions.
- **Enable:** Settings → AI → Model Context Protocol; enable MCP, then enable OAuth/client registration as needed. Generate an access token for a dedicated MCP user. Source: <https://directus.com/resources/directus-v11-13-release>, <https://directus.io/docs/guides/ai/mcp/installation>.
- **Auth:** **Token-based** (static access token for a dedicated MCP user); v11.13 also adds OAuth client registration toggle. MCP runs through Directus's **existing permissions system** — the agent operates with the same role/access controls as any user, and every change is written to the **audit/activity log**. Source: <https://directus.com/resources/directus-v11-13-release>.
- **Transport:** HTTP (the MCP is served by the Directus app). Exact "streamable HTTP vs SSE" wording NOT explicitly confirmed in fetched sources → **UNVERIFIED transport label** (token + Settings enablement confirmed; precise transport string not).
- **Clients:** Claude Desktop, Claude Code, ChatGPT, Cursor, VS Code, Raycast. Source: <https://directus.com/resources/directus-v11-13-release>, <https://directus.com/docs/guides/ai/mcp>.
- **Security controls:** Global delete protection (disabled by default). Source: <https://directus.com/resources/directus-v11-13-release>.
- **Custom system prompt:** Settings → AI → Custom System Prompt customizes assistant behavior. File uploads in the AI assistant require a built-in provider (OpenAI, Anthropic, or Google). Source: search result from <https://directus.io/docs/guides/ai/assistant/setup>, <https://directus.io/docs/configuration/ai>.

### B2. Directus standalone local MCP — `@directus/content-mcp`

- **What/where:** Separate npm package **`@directus/content-mcp`** (the "Directus Content MCP Server"). Open source, MIT. Repo: <https://github.com/directus/mcp>. Runs via `npx @directus/content-mcp@latest`. Sources: <https://github.com/directus/mcp>, search result. (DeepWiki overview: <https://deepwiki.com/directus/mcp/1-overview>.)
- **Relationship to native:** This is the **local/standalone** server (useful for older Directus or local dev). The native in-core MCP (B1) is the v11.12+ path. (Docs reference both; native = built-in, content-mcp = separate Node process.)
- **Transport:** stdio (spawned via npx). Source: <https://github.com/directus/mcp>.
- **Auth:** static token OR email/password. Connects over HTTP to the Directus instance URL. Source: <https://github.com/directus/mcp>.
- **Build mechanics:** Uses `@modelcontextprotocol/sdk` for the MCP server + `@directus/sdk` for type-safe REST calls. Tools registered in `src/tools/index.ts`. Source: <https://deepwiki.com/directus/mcp/1-overview>, <https://github.com/directus/mcp/blob/main/src/tools/index.ts>.
- **Extensibility / tool gating:** `DISABLE_TOOLS` env var disables specific (e.g. destructive) tools; system prompt + prompt collections configurable via env. Source: <https://github.com/directus/mcp>, <https://directus.com/docs/guides/ai/mcp/local-mcp/tools>.

**Tool inventory (PRIMARY SOURCE: `src/tools/index.ts` registration list + `src/tools/items.ts`/`files.ts` Zod schemas, GitHub raw; cross-checked with docs <https://directus.com/docs/guides/ai/mcp/local-mcp/tools>):**

| Tool (registered name) | What it does | Key params (name : type, required?) — from Zod source |
|---|---|---|
| `users-me` (`usersMeTool`) | Current user info / permissions. | none |
| `read-users` (`readUsersTool`) | Read users. | query (optional) |
| `read-collections` / schema (`schemaTool`) | Retrieve schema of all collections. | none |
| `read-items` (`readItemsTool`) | Fetch items from any collection (read/search). | `collection`: string (**required**); `query`: itemQuerySchema (**required**) — filter/sort/fields/limit/deep etc. |
| `create-item` (`createItemTool`) | Create new item(s). | `collection`: string (**required**); `item`: record<string,unknown> (**required**); `query`: itemQuerySchema (optional, fields/meta only) |
| `update-item` (`updateItemTool`) | Modify existing item. | `collection`: string (**required**); `id`: string\|number (**required**); `data`: record<string,unknown> (**required**); `query`: itemQuerySchema (optional) |
| `delete-item` (`deleteItemTool`) | Remove item (destructive-annotated). | `collection`: string (**required**); `id`: string\|number (**required**) |
| `read-fields` (`readFieldsTool`) | Field definitions for collections. | collection (per docs) |
| `read-field` (`readFieldTool`) | Specific field info. | collection, field |
| `create-field` (`createFieldTool`) | Add new field. | collection, field config |
| `update-field` (`updateFieldTool`) | Modify field. | collection, field, changes |
| `read-folders` (`readFoldersTool`) | List file folders. | (per source registration) |
| `read-files` (`readFilesTool`) | Access file metadata or raw content. | `query`: itemQuerySchema (optional); `id`: string (optional); `raw`: boolean (optional) — `raw:true` returns **base64** (for vision/image analysis) |
| `import-file` (`importFileTool`) | **File ingest — from a web URL only.** | `url`: string (**required**); `data`: FileSchema (optional metadata: title, folder, …) |
| `update-files` (`updateFilesTool`) | Update file metadata. | `data`: array of FileSchema (**required**) — each `{id, fields…}` (title/description/tags/folder) |
| `read-comments` (`readCommentsTool`) | View comments on items. | item ref |
| `upsert-comment` (`upsertCommentTool`) | Add/update a comment. | item ref, comment |
| `markdown-tool` (`markdownTool`) | Convert markdown ↔ HTML. | content, direction |
| `create-system-prompt` (`createSystemPrompt`, conditional) | Injects role/system context. | conditional on config |
| `get-prompts` / `get-prompt` | List / execute stored prompt templates. | prompt name, variables |
| `read-flows` (`readFlowsTool`) | List automation flows. | none |
| `trigger-flow` (`triggerFlowTool`) | Execute a flow. | flow id (+ payload) |

> Tool **names** and the items/files **Zod schemas** above are from primary source (GitHub raw `src/tools/index.ts`, `items.ts`, `files.ts`). Some non-items/files tools' exact field types come from the docs tools page rather than their individual source files → field types for fields/comments/prompts tools are doc-level, not schema-verified. **UNVERIFIED:** exact `itemQuerySchema` and `FileSchema` field lists; precise param schemas for field/comment/prompt tools.

**Media/file upload handling (probed — KNOWN GAP CONFIRMED):**
- The MCP `import-file` tool **only accepts a URL** — there is **no direct binary/multipart upload tool** in `@directus/content-mcp`. Source: `files.ts` ("Import a file to Directus from a web URL"; "No direct binary upload mechanism exists in this codebase"). <https://raw.githubusercontent.com/directus/mcp/main/src/tools/files.ts>.
- To upload an actual local binary, an agent must fall back to the **Directus REST `/files` endpoint** (multipart/form-data POST) directly — outside MCP. So MCP-based file creation is URL-import only; raw upload = REST `/files`.
- Reading binary content IS supported via `read-files` with `raw:true` → base64 (good for vision tools).
- The **native** AI assistant's own file uploads require a built-in provider (OpenAI/Anthropic/Google). Source: <https://directus.io/docs/guides/ai/assistant/setup>.

### B3. Directus Automate (Flows) + AI operations — automation-pattern agent integration

- **Flows** are Directus's automation engine (event/webhook/schedule/manual triggers → chained operations). Agents integrate by **triggering flows** (`trigger-flow` MCP tool, or REST flow trigger / webhook URL). Source: <https://directus.io/docs/guides/automate/flows>, <https://directus.io/docs/guides/automate/operations>.
- **Native-ish AI operations** are delivered as **Directus Labs flow operation extensions** (install from Marketplace). The AI provider is BYO-key per operation. The full set (repo `directus-labs/extensions`, <https://github.com/directus-labs/extensions>):
  - **AI Writer** (`@directus-labs/ai-writer-operation`) — text generation via OpenAI / Anthropic / Mistral / Meta Llama (latter via Replicate). Config: API key, model, prompt, text input (supports `{{$last.data}}` refs); System/User/Assistant role messages; returns a string. Source: <https://directus.io/extensions/@directus-labs/ai-writer-operation>, <https://www.npmjs.com/package/@directus-labs/ai-writer-operation>.
  - **AI Image Generation** — OpenAI DALL·E, prompt + quality + size. Source: <https://github.com/directus-labs/extensions/tree/main/packages/ai-image-generation-operation>.
  - **AI Transcription** — Deepgram speech-to-text, timestamped transcript. Source: <https://directus.io/blog/directus-ai-extensions>.
  - **AI Translator** — DeepL, 30+ languages, source-language detect. Source: same.
  - **AI Alt Text Writer** — image captions via Clarifai (`directus-labs/extension-ai-alt-text-writer`). Source: <https://github.com/directus-labs/extension-ai-alt-text-writer>.
  - Others: **AI Focal Point Detection, AI Image Moderation, AI Speech Generation, AI Text Extraction, AI Text Intelligence, AI Web Scraper**, plus an **AI Researcher Bundle**. Categories: data transformation / data generation / data analysis. Source: <https://directus.io/blog/directus-ai-extensions>.
- **AI pack bundle (community):** `br41nslug/directus-extension-ai-pack`. Source: <https://github.com/br41nslug/directus-extension-ai-pack>.

### B4. Directus REST / GraphQL / SDK layer (DIY agent wrappers)

- Full **REST API** + **GraphQL API** over all collections; **`@directus/sdk`** (type-safe) is the official client (also used internally by the MCP). The native MCP ultimately calls these. Direct REST/GraphQL is the most general agent integration (e.g. `/items/{collection}`, `/files` for true uploads). Source: <https://deepwiki.com/directus/mcp/1-overview>, <https://github.com/directus/mcp>.

### B5. Directus webhooks / events
- Webhooks exist both as a legacy feature and as **Flow triggers** (Webhook trigger / Event hook), enabling event-driven agent pipelines (content change → flow → AI operation / external agent). Source: <https://directus.io/docs/guides/automate/flows>, <https://directus.io/docs/guides/automate/operations>.

### B6. Other community Directus MCP servers
- `radata/mcp_directus`, `pixelsock/directus-mcp` — community MCP servers for Directus API. Source: <https://github.com/radata/mcp_directus>, <https://github.com/pixelsock/directus-mcp/>.

---

## CROSS-PLATFORM SUMMARY — integration patterns that emerged

1. **First-party MCP server** — Storyblok (hosted, meta-tool/OpenAPI-driven) vs Directus (built into core v11.13, permission-scoped). Storyblok = remote hosted; Directus = embedded + a separate stdio `@directus/content-mcp`.
2. **Meta-tool vs resource-tool design** — Storyblok official = ~7 generic meta-tools over the whole Management API; Directus official = ~20 fixed resource tools; community hypescale Storyblok = 160 fine-grained tools. Trade-off: breadth/auto-coverage vs explicit/predictable.
3. **Native in-editor AI** — Storyblok AI Suite/Ideation (BYO OpenAI/Gemini) and Directus AI assistant + Directus Labs flow AI operations (BYO per-op keys). Editor-facing, not directly agent-callable except via produced content / flow triggers.
4. **Automation/flow trigger** — Directus Flows (`trigger-flow`, webhooks) is a distinct agent surface; Storyblok webhooks similar but lighter.
5. **REST/GraphQL + official SDK** — `storyblok-js-client` and `@directus/sdk`: the DIY substrate every wrapper/MCP sits on.
6. **Asset upload is the consistent friction point** — Storyblok solves the multi-step signed-S3 upload inside MCP (`upload_asset` + `upload_asset_finish`, emitting curl); Directus MCP does NOT support raw binary upload at all (`import-file` = URL-only) → agents must drop to REST `/files`.

---

## UNVERIFIED / GAPS

- **Storyblok hosted MCP exact tool JSON schemas** (param types/required for `search`/`describe`/`execute_*`/`upload_asset*`) — descriptions only on the setup page; field-level schema not published in copyable form.
- **Storyblok official MCP licensing of the live hosted service** — the archived repo is open (TypeScript); the live hosted service's licensing/source-availability after archival is not explicitly stated.
- **Storyblok hosted MCP versioning/date** — "Innovation phase"; no semver/version number surfaced. Repo archived 2026-03-30.
- **Directus native (in-core) MCP transport string** — token auth + Settings enablement confirmed; exact "streamable HTTP / SSE" label NOT explicitly confirmed in fetched sources.
- **Directus native vs `@directus/content-mcp` tool-set parity** — assumed similar tool catalog; not byte-for-byte confirmed that the in-core MCP exposes the identical 20-tool list as the standalone package.
- **`@directus/content-mcp` exact version number** — `@latest` referenced; specific semver not captured.
- **Directus `itemQuerySchema` / `FileSchema` full field lists** — referenced/imported in source but not expanded in fetched excerpts.
- **Field/comment/prompt tool param types (Directus)** — taken from docs page, not each tool's individual source file.
- Some Storyblok community repos (`Kiran1689`, `ArjunCodess`, `zerdos`, `harlley`) — only summary-level metadata captured (not full tool inventories/licenses).
