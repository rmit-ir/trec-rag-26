# AI Agent Integration: Payload CMS & Strapi

Research date: 2026-06-19. Scope: ALL ways AI agents connect to each CMS — official + community MCP servers, agent skills, IDE/agent plugins, in-product AI features, REST/GraphQL wrappers, webhooks, RAG. Media/file upload probed specifically. Tool inventories from primary sources where available.

---

# PART A — PAYLOAD CMS

## A1. Official MCP plugin — `@payloadcms/plugin-mcp` (PRIMARY, vendor-official)

- **What/where:** Official Payload-maintained plugin that turns a Payload app into an MCP server. Docs: https://payloadcms.com/docs/plugins/mcp . Source is open-source (docs say "completely open-source", source linked from docs page; package `@payloadcms/plugin-mcp` on npm). Announced via RFC: https://github.com/payloadcms/payload/discussions/14318 . Docs mdx source: https://github.com/payloadcms/payload/blob/main/docs/plugins/mcp.mdx . Status: beta (community tutorials dated Dec 2025; docs live as of Jun 2026).
- **Category:** Embedded MCP server (runs inside the Payload/Next.js app), exposing CRUD over your collections + globals.
- **Install:** `pnpm add @payloadcms/plugin-mcp`; add `mcpPlugin({ collections: { posts: { enabled: true } } })` to the `plugins` array of `buildConfig`.
- **Transport:** HTTP (Streamable HTTP). Endpoint: `POST http://localhost:3000/api/mcp` (i.e. `/api/mcp` on the Payload app). GET/other handled per MCP spec. Recommended client connection uses `npx mcp-remote` bridge for stdio-only clients; native HTTP clients connect directly with `"type":"http"`.
- **Auth:** Bearer token = a Payload-managed **API Key**. Plugin adds an "MCP → API Keys" collection in admin. Every request MUST carry `Authorization: Bearer MCP-USER-API-KEY`; unauthenticated requests rejected. Keys are **user-associated**, so all existing Payload access control, hooks, and multi-tenant restrictions apply at the Payload level (`overrideAccess: false`, `req.user` = key owner). Custom auth via `overrideAuth(req, getDefaultMcpAccessSettings)`.
- **Two-step access model (important):** (1) enable the collection/global in plugin config; (2) in admin, toggle each capability ON for the specific API Key. Enabling in config alone does NOT expose it.
- **Client configs documented:** VSCode (`mcp.servers`), Cursor (`mcpServers` + mcp-remote), Claude Code (`claude mcp add --transport http Payload http://127.0.0.1:3000/api/mcp --header "Authorization: Bearer ..."`), generic `{"type":"http","url":...,"headers":{...}}`.
- **How tools are DEFINED / extensibility:** Tools auto-generated per enabled collection/global. Fully extensible — `mcp.tools[]` (custom tools), `mcp.prompts[]` (MCP prompts), `mcp.resources[]` (static or dynamic via `ResourceTemplate`). Custom tool: `{ name, description, handler:(args,req)=>{...}, parameters: z.object({...}).shape }` — **parameters are a Zod schema** (`.shape`). Handler receives `(args, req)` where `req` = full `PayloadRequest` (`req.payload`, `req.user`, `req.locale`, `req.headers`). Prompts use `argsSchema` (Zod) + `handler` returning `{messages:[...]}`. Server identity configurable via `mcp.serverOptions.serverInfo.{name,version}` (defaults: name `'Payload MCP Server'`, version `'1.0.0'`).
- **Localization:** If Payload localization enabled, all collection/global tools auto-gain `locale` + `fallbackLocale` params (`locale:"all"` returns all locales).
- **Token-saving / response control:** `select` param (JSON string, Payload Select API syntax) limits returned fields. `overrideResponse(response, doc, req)` to sanitize/redact (e.g. strip `hash`/`salt`). Virtual (computed) fields auto-excluded from create/update schemas. `onEvent` callback for audit/analytics. `maxDuration` default 60s.

### A1 Tool inventory (PRIMARY — from official docs)
Tools are generated per enabled collection/global based on enabled operations. Exact tool names verified for globals; collection tool names follow same pattern (verified: `findPosts` named explicitly in docs `tools/call` examples).

| Tool (pattern) | Applies to | Op | Params (type, required) | Returns |
|---|---|---|---|---|
| `find{Collection}` | collection (e.g. `findPosts`) | find/read | `select` (string JSON, optional); `locale`/`fallbackLocale` (string, optional, if i18n); standard query/where args | document(s) as text content |
| `create{Collection}` | collection | create | document fields per collection schema (virtual fields excluded); types from field schema | created doc |
| `update{Collection}` | collection | update | id + fields | updated doc |
| `delete{Collection}` | collection | delete | id | result |
| `findSiteSettings` | global (e.g. `site-settings`) | find | `select`/locale optional | global doc |
| `updateSiteSettings` | global | update | global fields | updated global |

- Globals produce exactly `find{Global}` + `update{Global}` (no create/delete — singletons). Docs example: `findSiteSettings`, `updateSiteSettings`.
- **VERIFIED naming convention** for collections from docs: `findPosts` (used in curl `tools/call` examples). Other op prefixes (`create`/`update`/`delete`) inferred from the same camelCase `{op}{Collection}` pattern — exact strings for non-find collection ops NOT shown verbatim in docs; flag as inferred.
- Exact JSON parameter schema for collection create/update (full field list, required flags) is generated at runtime from each project's collection config — not enumerable generically. To get exact schema, run `tools/list` against a live server.

### A1 Media/file upload (PROBED)
- Payload **upload collections** (collections with `upload: true`, e.g. `Media`) are ordinary collections. The MCP plugin treats them as collections, so `create`/`update` tools can be enabled. **However**, the docs do NOT show a documented mechanism for the agent to transmit binary file bytes over MCP (no multipart, no base64 file param documented in the tool reference). The documented create flow passes JSON document fields only. **Conclusion: agent-driven binary upload over the official MCP plugin is NOT documented/verified.** An agent can likely set fields and reference existing media, but uploading a new image file via the plugin's standard tools is unverified — likely requires a custom `mcp.tools` handler that calls `payload.create({ collection, file, data })` itself. FLAG as gap / needs live verification.

## A2. Payload Skills for AI coding agents — `payloadcms/skills` (PRIMARY, vendor-official)

- **What/where:** Official repo https://github.com/payloadcms/skills — "A collection of skills for AI coding agents." Install: `npx skills add payloadcms/skills`. Also distributed as a Claude Code plugin/marketplace (claudemarketplaces.com/skills/payloadcms/payload/payload). Announced ~May 2026 ("Introducing Payload Skills"). Latest commit Apr 2026 (cms-migration skill added).
- **Category:** Agent skill (packaged instructions + scripts for coding agents like Claude Code) — NOT a runtime CMS connector. It teaches the agent how to write Payload code.
- **Two skills:**
  - `payload`: dev guidelines — collections (auth, uploads, drafts, live preview), all field types (relationships, arrays, blocks, joins, virtual), hooks (beforeChange/afterChange/beforeValidate/field hooks), access control (collection/field/global, RBAC, multi-tenant), queries (Local API/REST/GraphQL), DB adapters (Mongo/Postgres/SQLite, transactions), jobs queue, custom endpoints, localization, plugins. "When to use: working with Payload projects / debugging validation, security, relationship queries, transactions, hooks."
  - `cms-migration`: interactive workflow to design Payload collections from a source CMS (WordPress, Contentful, Strapi, Sanity, Webflow) — maps JSON/CSV exports to collections.
- **Mechanics:** Skills = markdown SKILL.md + scripts loaded by the agent (Claude Code loads from `.claude/skills/`). No transport/auth — local files. Extensible (open-source repo, MIT-style community contribution).

## A3. Community / third-party MCP servers for Payload

These are alternatives to the official plugin. Treat as community.

- **`payload-plugin-mcp`** (community, by Antler Digital / "disruption-hub") — https://payload-plugin-mcp.vercel.app/ , LobeHub listing, mcp.directory. Install `pnpm install payload-plugin-mcp`. Embedded plugin, auto-generates MCP tools for all collections.
  - Transport: **HTTP** (deliberately chose HTTP over SSE; also exposes `enableStdioTransport` option default true). Endpoint `GET/POST /api/plugin/mcp`.
  - Auth: API key via `MCP_API_KEY` env, `Authorization: Bearer` header (or `?api_key=`).
  - Config: `PayloadPluginMcp({ apiKey, collections:'all'|[...], defaultOperations:{list,get,create,update,delete}, port, host, enableHttpTransport, enableStdioTransport, serverName })`. Per-collection: `{ collection, options:{ operations, toolPrefix, description, excludeFields, metadata } }`.
  - **Tool inventory (PRIMARY, from its docs):** tools named `{prefix}_{op}` where op ∈ `list,get,create,update,delete`. Examples given: `posts_list`, `posts_get`, `user_create`, `user_update`, `file_list`, `file_get`, `file_create`, `file_delete`. `list` tool input: `where` (object), `limit` (number), `page` (number), `sort` (string), `depth` (number). `create` tool input: `data` (object), `depth` (number). Schemas auto-generated from collection fields ("Rich JSON Schemas"). `excludeFields` removes fields (e.g. `password`).
  - **Media/upload:** Media is just a collection; you can enable `create`/`delete` and name it `file`/`asset` prefix. But again, NO documented binary-upload mechanism — `create` input is `{data, depth}` JSON only. Same gap as official.
- **`ohnicholas93/payload-mcp-server`** — LobeHub listing https://lobehub.com/mcp/ohnicholas93-payload-mcp-server — standalone MCP server talking to Payload via REST API. (Not deeply verified — lead only.)
- **`matmax-worldwide/payloadcmsmcp`** — https://claudemarketplaces.com/mcp/matmax-worldwide/payloadcmsmcp — a DEV-focused MCP server: wraps validation, code generation, and scaffolding for Payload 3.0 development (not content CRUD). It's an AI dev assistant for building Payload, not for editing content. (Reddit r/PayloadCMS Mar 2025.)
- **`disruption-hub` "Payload CMS"** on mcp.directory — community server providing AI tools via MCP (likely same family as payload-plugin-mcp). Lead only.

## A4. In-admin AI agent / authoring plugins (native-ish AI features)

- **`@ai-stack/payloadcms` (ashbuilds/payload-ai)** (PRIMARY community) — https://github.com/ashbuilds/payload-ai . Install `pnpm add @ai-stack/payloadcms`. Beta, tested w/ Payload v3.38.0. Open-source.
  - **Category:** In-product AI authoring / copilot embedded in the Payload admin (field-level AI), NOT an agent connector.
  - Features: Text/RichText — Compose, Proofread(beta), Translate, Rephrase(beta); coming: Expand/Summarize/Simplify. Upload fields — **Voice Generation** (ElevenLabs, OpenAI TTS), **Image Generation** (OpenAI DALL-E + GPT-Image-1). BYO model (OpenAI, Anthropic Claude, Google Gemini, MiniMax). Field-level prompts, access control, prompt editor, i18n, custom components. Coming: Document Analyzer, Fact Checking, Automated Workflows, Editor Suggestions, AI Chat Assistant.
  - **Media/upload (RELEVANT):** This plugin DOES write generated media into a Payload upload collection. Config `uploadCollectionSlug: "media"` (for GPT-Image-1) and a custom `mediaUpload: async (result, { request, collection }) => request.payload.create({ collection, data: result.data, file: result.file })` hook — shows the pattern for uploading a file via Payload Local API (`payload.create({ collection, file, data })`). So AI-generated images ARE attached as real media assets. Auth = provider API keys in `.env` (OPENAI_API_KEY, ANTHROPIC_API_KEY, GOOGLE_GENERATIVE_AI_API_KEY, ELEVENLABS_API_KEY, MINIMAX_API_KEY, optional OPENAI_BASE_URL/OPENAI_ORG_ID). Lexical editor feature `PayloadAiPluginLexicalEditorFeature()` adds the AI UI to richText fields.
- **JHB Software `payload-plugins` AI chat agent** (community) — https://github.com/jhb-software/payload-plugins — "a Payload CMS plugin that adds an AI chat agent for reading, creating, and updating content. Admin-panel chat view where users interact with [the agent]." (Lead from search snippet; not deeply verified — flag.)
- **Payload "Agentic Connections" plugin** (community) — Reddit r/PayloadCMS Dec 2025 (https://www.reddit.com/r/PayloadCMS/comments/1pspcbf/). Lets you define Agents with different behaviours and tool access via the Payload admin, adds custom admin views. Only a Reddit announcement found; no repo/npm verified. FLAG unverified.
- **MYGOM AI Content Generator** — https://mygom.tech/articles/... — an agency-built Payload AI content plugin (research + brand-aligned writing + review). Third-party article; not a public package verified.

## A5. Payload native AI (enterprise) + RAG framework

- **Enterprise AI** — https://payloadcms.com/enterprise/enterprise-ai — vendor page. Features: AI-Translations (LLM of choice), AI-Image Generation (DALL-E, "coming soon"), AI-Writing Assistant (highlight text → suggestions/rewrite), granular permissions. These are enterprise-tier in-admin features (overlap conceptually with the open-source ashbuilds plugin). Note: page marks image-gen and translation as "COMING SOON" — flag that vendor-native versions may not be GA.
- **RAG / AI Auto-Embedding** — https://payloadcms.com/enterprise/ai-framework — "Payload is the only RAG-ready CMS." Adds **vector indexes directly into your existing DB** (no separate vector DB). You control JSON→text conversion, chunking; based on your AI adapter Payload creates + auto-syncs embeddings per chunk; user-by-user access control on retrieval. This is RAG-readiness for building agent/retrieval apps ON Payload, not an agent-to-CMS connector per se.

## A6. Payload REST / GraphQL / Local API (agent substrate)

- Payload auto-generates **REST API**, **GraphQL API**, and a server-side **Local API** for every collection (covered in the `payload` skill and core docs). Agents/LangChain can call these directly with API-key or JWT auth. GitHub discussion #9833 (https://github.com/payloadcms/payload/discussions/9833) is the community asking about LangChain content generation — answer is "yes, via custom functions / the APIs." The official MCP plugin (A1) is effectively the standardized agent wrapper over these APIs.
- **Webhooks/hooks:** Payload doesn't ship outbound webhooks as a headline feature but has collection **hooks** (afterChange etc.) used to trigger external calls — relevant for event-driven agent pipelines (the MCP plugin itself uses the `MCP` API context inside hooks: `req.payloadAPI === 'MCP'`).

---

# PART B — STRAPI

## B1. Official built-in MCP server (Strapi core ≥ 5.47.0) (PRIMARY, vendor-official)

- **What/where:** Shipped **inside Strapi core** as of **v5.47.0** (Beta). Docs: https://docs.strapi.io/cms/features/strapi-mcp-server . Launch blog (Jun 8 2026): https://strapi.io/blog/the-strapi-mcp-server-is-out-wire-agents-to-your-content . Free, self-hosted, no tier gating, open-source (Strapi core). Status: **Beta**.
- **Category:** Built-in MCP server auto-generating content-management tools from your schema.
- **Enable:** No package install. Add `mcp: { enabled: true }` to `config/server.ts`/`.js`. Restart. Endpoint: `POST http://localhost:1337/mcp`.
- **Advanced config:** `connectTimeoutMs` (default 5000), `requestTimeoutMs` (default 60000).
- **Transport:** **Streamable HTTP**. Stateless — each POST creates a fresh ephemeral MCP server scoped to the token; no session IDs; permission/token changes take effect on next request. **GET and DELETE on `/mcp` return 405** (POST only). stdio clients (Claude Desktop) bridge via `npx mcp-remote`.
- **Auth:** **Admin API Tokens** (Settings → Admin Tokens) — NOT Content API Tokens (those get 401). `Authorization: Bearer <admin token>`. Token's RBAC permissions decide which tools, fields, and locales are exposed (tool visibility, field filtering, locale filtering, runtime enforcement incl. condition-based "only update your own").
- **Client configs documented:** Claude Desktop (mcp-remote), Claude Code (`claude mcp add strapi-mcp --transport http http://localhost:1337/mcp -H "Authorization: Bearer ..."`), Cursor (`type: streamable-http`), Windsurf (`serverUrl`), generic streamable-http.

### B1 Tool inventory (PRIMARY — from official docs, fully verified)
Tools generated per content type from schema. **Collection types → up to 8 tools; single types → up to 6 tools.** Tool availability gated by the Admin token's permissions.

**Collection types:**
| Tool | Action | Permission | Description |
|---|---|---|---|
| `list` | Read | `read` | List entries; supports pagination, sorting, filtering |
| `get` | Read | `read` | Get single entry by documentId |
| `create` | Create | `create` | Create entry (draft if Draft&Publish on) |
| `update` | Update | `update` | Update entry by documentId |
| `delete` | Delete | `delete` | Delete entry by documentId |
| `publish` | Publish | `publish` | Publish a draft (only if D&P on) |
| `unpublish` | Unpublish | `publish` | Unpublish (only if D&P on) |
| `discard_draft` | Discard draft | `publish` | Revert draft to published version (only if D&P on) |

**Single types** (no `list`; create+update merged into `write`):
`get`, `write` (create-or-update; needs `create` and/or `update`), `delete`, `publish`, `unpublish`, `discard_draft`.

**Built-in utility tool:** `log` (development mode only, when `autoReload` enabled) — logs a message at level `info|warn|error|http|log`; no permission needed.

**`list` tool params (verified):** `page` (number, 1-indexed, default 1), `pageSize` (number, default 25, max 100), `sort` (string `"title:asc"` | array of strings | object | array of objects), `filters` (Strapi filter syntax: operators `$eq,$ne,$in,$notIn,$lt,$lte,$gt,$gte,$between,$contains,$notContains,$startsWith,$endsWith,$null,$notNull` + case-insensitive `i` variants; logical `$and,$or,$not`; implicit equality). Sort/filter fields constrained to **scalar attributes only** (no relations/components/dynamic zones/media/JSON).
**Relations:** to-one accepts documentId string | `{documentId, locale?, status?}` | null. to-many accepts `{connect|disconnect|set}` with `position` ordering hints (`{before,after,start,end}`, default `{end:true}`).
**i18n:** when enabled, tools gain optional `locale` param; locales narrowed per-action by token perms.

### B1 Media/file upload (PROBED — confirmed GAP, vendor-documented)
- **Official docs "Known limitations" state verbatim:** "**Media upload**: Media fields accept existing media asset references but the MCP server cannot upload new files. Use Strapi's media library or upload API to add files first, then reference them in MCP tool calls." So the official Strapi MCP server CANNOT upload files — the agent can only reference already-uploaded asset IDs. Other documented limitations: dynamic zones passed as untyped arrays; no nested population params on list/get; custom fields mapped to underlying type (fallback `unknown`); circular components fall back to open `record<string,unknown>`.

### B1 Extensibility — Plugin API (`strapi.ai.mcp`) (PRIMARY)
- Plugins/apps can register custom MCP tools via **`strapi.ai.mcp.registerTool({...})`**. Walkthrough: https://strapi.io/blog/how-to-extend-strapi-s-mcp-server-with-a-custom-tools-via-a-plugin (Jun 2026).
- Register during `register()` (app `src/index.ts`) or `register()`/`bootstrap()` (plugin) — must run **before MCP server starts** (boot order: plugin register → plugin bootstrap → MCP starts → app bootstrap). `strapi.ai.mcp.isEnabled()` guard.
- Required tool fields: `name`, `title`, `description`, `resolveOutputSchema`, and either `auth` or `devModeOnly`. Optional: `resolveInputSchema`. **Schemas are functions** (called per request, receive caller's `context.userAbility`), so a tool can return a narrower schema for a less-privileged token. **Use `z` from `@strapi/utils`** (Strapi's bundled Zod), not the `zod` package.
- Custom tool handlers are NOT HTTP requests → they bypass controller sanitization; if returning entity data you must call `strapi.contentAPI.sanitize.output(...)` with the caller's permissions yourself. Built-in tools already sanitize.
- A `setup-strapi-mcp` Claude Code skill ships in the example repo to scaffold all of this. MCP capabilities supported: tools (auto-loaded by LLM), prompts (user-triggered), resources (client-dependent; Claude Code does NOT auto-fetch), server instructions (injected at connect) — but **out of the box Strapi only emits tools** (no prompts/resources/instructions by default).
- RFC for the core MCP API: https://github.com/strapi/strapi/discussions/25398 ; native MCP discussed in community calls (https://strapi.io/blog/strapi-community-call-recap-... Mar 2026).

## B2. Official Strapi **Docs** MCP server (PRIMARY, vendor-official, separate)

- **What/where:** A SECOND official MCP server — for the **documentation**, not content. https://docs.strapi.io/cms/ai/docs-mcp-server . Powered by **Kapa** (same as the "Ask AI" button). URL: `https://strapi-docs.mcp.kapa.ai`. No auth shown (hosted). Add to `.cursor/mcp.json` / VS Code / Windsurf / Claude Code.
- **Category:** Docs-retrieval MCP for coding assistants (answers Strapi API questions, suggests implementations). Tip: prefix prompts with "Use the strapi-docs MCP server to answer:". Tool inventory not enumerated in docs (Kapa-managed retrieval tool).

## B3. Strapi AI (native in-product) (PRIMARY, vendor-official)

- **What/where:** **Strapi AI** — in-product AI for content modeling/authoring. GA Oct 14 2025 (https://strapi.io/blog/strapi-ai-is-now-generally-available); introduced May 13 2025 (https://strapi.io/blog/introducing-strapi-ai); hub https://strapi.io/ai .
- **Category:** Native AI copilot inside Strapi admin (NOT an agent connector).
- Features: **AI-powered Content-Type Builder** — generate full content schema (collection types, single types, components, relationships) from a chat prompt, from an uploaded **JavaScript app** (Next/Nuxt/Astro → reverse-engineered schema), or from a **Figma file/screenshot**. Iterate via AI chat. Per https://strapi.io/ai also: "Strapi AI automates content modeling, **media metadata**, and **translations**." The built-in MCP server is presented alongside it as the agent-addressable surface.

## B4. Community Strapi MCP servers

- **`@bschauer/strapi-mcp-server` (misterboe/strapi-mcp-server)** (PRIMARY community) — https://github.com/misterboe/strapi-mcp-server . Standalone MCP server (run via `npx -y @bschauer/strapi-mcp-server@2.6.0` in Claude Desktop). v2.6.0. MIT. **AI-developed, explicitly "NOT for production."**
  - Transport: stdio (Claude Desktop `command:npx`). Auth: **JWT / API token** in `~/.mcp/strapi-mcp-server.config.json` (`api_url`, `api_key`, `version`). Supports multiple Strapi instances + v4/v5 differences.
  - **Tool inventory (PRIMARY, from README):** `strapi_list_servers`, `strapi_get_content_types`, `strapi_get_components` (params `server`, `page`, `pageSize`), `strapi_rest` (params `server`, `endpoint`, `method` GET/POST/PUT/DELETE, `params`/`body`), `strapi_upload_media`.
  - **Media/upload (NOTABLE — this community server DOES support upload):** `strapi_upload_media({ server, url, format, quality, metadata:{name,caption,alternativeText} })` — fetches an image from a URL, optimizes/converts format (e.g. webp), uploads. Per mcpservers.org listing it has a **~1MB base64 limit (~750KB file)**. Write protection policy: POST/PUT/DELETE/upload require explicit authorization + logging.
- **`@sensinum/strapi-plugin-mcp` (VirtusLab-Open-Source/strapi-plugin-mcp)** (PRIMARY community) — https://github.com/VirtusLab-Open-Source/strapi-plugin-mcp . Strapi v5 plugin. **Dev/local only — security warning says NEVER enable in production.** Also see VirtusLab article https://virtuslab.com/expertise/introducing-strapi-mcp .
  - Transport: **Streamable HTTP** at `/api/mcp/streamable` (GET init, POST requests, DELETE close session). Session management: in-memory or **Redis** (configurable TTL, keyPrefix). **IP allowlist** (`allowedIPs`, default localhost only; non-allowed → 403). Install `@sensinum/strapi-plugin-mcp`.
  - **Focus = introspection, NOT content CRUD.** Tool inventory (PRIMARY, from README): `content-types` (list all), `content-type-by-name`, `components` (list all), `component-by-name`, `instance-info` (version/config/plugins), `services` (list services), `service-methods` (methods of a service). It's a schema/system explorer for devs.
  - Extensible: `strapi.plugin("mcp").service("custom").registerTool({ name, description, argsSchema (ZodRawShape), callback, annotations })` returning `{content:[{type:"text",text}]}`.
- **`l33tdawg/strapi-mcp`** — mcpservers.org/servers/l33tdawg/strapi-mcp & mcpmarket.com/server/strapi-1 — community server: create/update content types, list content types/components, upload media (the 1MB base64 note appears tied to this/misterboe family). Lead-level; overlaps with misterboe.

## B5. Strapi REST / GraphQL APIs + Upload API (agent substrate)

- Strapi auto-generates **REST** (`/api/...`) and **GraphQL** APIs per content type. Upload via REST **Upload API** (https://docs.strapi.io/cms/api/rest/upload) — `POST /api/upload` multipart, can attach files to entry fields (including component fields by index). This is the documented path agents must use for real file upload since the official MCP can't. Auth = Content API tokens (separate from Admin tokens). The misterboe community server effectively wraps this Upload API to give agents upload capability.
- **Webhooks:** Strapi has native outbound webhooks (entry create/update/delete/publish) — relevant for event-driven agent pipelines, though not an inbound agent connector.

---

# Cross-cutting comparison (quick)

| Aspect | Payload official MCP (`@payloadcms/plugin-mcp`) | Strapi official MCP (core ≥5.47) |
|---|---|---|
| Where it lives | Plugin you install | Built into core, one config line |
| Endpoint | `/api/mcp` | `/mcp` |
| Transport | HTTP (Streamable) | Streamable HTTP, stateless, POST-only |
| Auth | Payload API Key (user-bound) Bearer | Admin API Token (RBAC) Bearer |
| Tool gen | per collection+global; camelCase `findPosts` etc. | per content type; `list/get/create/update/delete/publish/unpublish/discard_draft` |
| Custom tools | `mcp.tools/prompts/resources` (Zod) | `strapi.ai.mcp.registerTool` (Zod from @strapi/utils) |
| Prompts/Resources | Yes (MCP prompts + resources supported) | Not by default (tools only); extensible |
| Media upload via MCP | NOT documented (gap) | Explicitly NOT supported (documented gap) |
| RAG native | Yes (vector auto-embedding, enterprise) | Not as a built-in vector framework |

---

# UNVERIFIED / GAPS

1. **Payload official MCP media upload** — no documented binary-upload tool; whether an agent can upload an actual image file through `@payloadcms/plugin-mcp` (vs. only referencing/creating doc fields) is **unverified**. Likely needs a custom `mcp.tools` handler calling `payload.create({collection,file,data})`. Needs live `tools/list` + test.
2. **Payload collection create/update MCP tool exact names** — only `findPosts`/`findSiteSettings`/`updateSiteSettings` shown verbatim; `createPosts`/`updatePosts`/`deletePosts` are inferred from the camelCase `{op}{Collection}` pattern, not quoted in docs.
3. **Payload `@payloadcms/plugin-mcp` version + npm publish date** — not captured; docs say beta, source open. Confirm on npm.
4. **JHB Software AI chat agent plugin** and **Payload "Agentic Connections" plugin** — only search-snippet/Reddit level; no repo/npm/tool list verified.
5. **`ohnicholas93/payload-mcp-server`, `matmax-worldwide/payloadcmsmcp`, `disruption-hub`** — not deeply verified; matmax is a DEV-scaffolding MCP (validation/codegen), not content CRUD — confirm scope.
6. **Strapi official MCP — exact JSON Schema of `create`/`update` per content type** — generated at runtime from schema; not enumerable generically. Tool names + permission map are verified; per-field input schema needs a live server.
7. **Strapi Docs MCP (Kapa)** — exact tool name(s) not documented (managed retrieval tool).
8. **Payload Enterprise native AI** (translations/image-gen) marked "COMING SOON" on vendor page — GA status of vendor-native (vs. ashbuilds open-source) versions unconfirmed.
9. **misterboe upload 1MB base64 limit** — sourced from mcpservers.org listing, not the GitHub README verbatim; README confirms `strapi_upload_media` exists with URL+format+quality+metadata params and that it's protected; the exact size cap should be re-confirmed in source.
10. Strapi single-type `write` tool merging create/update and the `discard_draft` tool — verified in official docs table.

## Key source URLs
- Payload MCP docs: https://payloadcms.com/docs/plugins/mcp
- Payload MCP RFC: https://github.com/payloadcms/payload/discussions/14318
- Payload skills: https://github.com/payloadcms/skills
- ashbuilds payload-ai: https://github.com/ashbuilds/payload-ai
- Payload Enterprise AI: https://payloadcms.com/enterprise/enterprise-ai ; RAG: https://payloadcms.com/enterprise/ai-framework
- payload-plugin-mcp (community): https://payload-plugin-mcp.vercel.app/
- Strapi MCP docs: https://docs.strapi.io/cms/features/strapi-mcp-server
- Strapi MCP launch: https://strapi.io/blog/the-strapi-mcp-server-is-out-wire-agents-to-your-content
- Strapi extend MCP: https://strapi.io/blog/how-to-extend-strapi-s-mcp-server-with-a-custom-tools-via-a-plugin
- Strapi Docs MCP: https://docs.strapi.io/cms/ai/docs-mcp-server
- Strapi AI: https://strapi.io/ai ; https://strapi.io/blog/introducing-strapi-ai ; https://strapi.io/blog/strapi-ai-is-now-generally-available
- misterboe community: https://github.com/misterboe/strapi-mcp-server
- VirtusLab community: https://github.com/VirtusLab-Open-Source/strapi-plugin-mcp
- Strapi Upload API: https://docs.strapi.io/cms/api/rest/upload
