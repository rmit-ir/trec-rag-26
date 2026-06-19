# AI Agent ↔ Sanity & Contentful: Integration Landscape

Research date: 2026-06-19. All claims carry inline source URLs. Tool inventories pulled from primary sources (vendor docs, GitHub source files, npm registry) where possible; unverifiable items flagged in the "Unverified / gaps" section.

---

## PART 1 — SANITY

Sanity is a structured-content platform ("Content Lake") queried with **GROQ** (Graph-Relational Object Queries). Agents reach Sanity through several distinct surfaces, summarized below.

### 1.1 Sanity MCP server — REMOTE (current, official)

- **What/where:** Hosted MCP endpoint at `https://mcp.sanity.io`. Official Sanity offering. ([Sanity Docs – MCP server](https://www.sanity.io/docs/ai/mcp-server)) ([Changelog: remote server, schema deployment, new tools](https://www.sanity.io/docs/changelog/e75b1d45-03be-4fa6-994b-248750b3fa9f))
- **Pattern:** Hosted (remote) MCP server — managed infrastructure, auto-updated.
- **Transport:** Streamable HTTP (remote MCP). ([Sanity Docs – MCP server](https://www.sanity.io/docs/ai/mcp-server))
- **Auth:** OAuth login (default, "no API tokens to manage") OR scoped API tokens. ([Changelog](https://www.sanity.io/docs/changelog/e75b1d45-03be-4fa6-994b-248750b3fa9f))
- **Source:** Closed — proprietary hosted service (no npm package). The remote replaced the local package.
- **Connection to CMS:** Direct to Sanity projects/datasets; schema-aware (relies on a deployed schema, see Agent Actions §1.4).
- **Latest documented:** "v2.6.0", release date Dec 11, 2025, advertising "40+ tools." ([Changelog](https://www.sanity.io/docs/changelog/e75b1d45-03be-4fa6-994b-248750b3fa9f))
- **GROQ querying:** Agents run GROQ via the `query_documents` tool — natural-language requests are compiled to GROQ and executed against the dataset with schema awareness. ([Sanity Docs – MCP server](https://www.sanity.io/docs/ai/mcp-server)) ([Sanity blog – Introducing Sanity MCP](https://www.sanity.io/blog/introducing-sanity-model-context-protocol-server))

**Tool inventory (remote MCP, from docs — 40+ total; representative set):**

| Tool | Category | What it does |
|---|---|---|
| `query_documents` | Search | Run GROQ query against dataset |
| `semantic_search` | Search | Vector/semantic search over embeddings indices |
| `get_document` | Docs | Retrieve a document by ID |
| `create_documents` / `create_document_from_json` / `create_document_from_markdown` | Docs | Create docs (multiple input formats) |
| `patch_documents` / `patch_document` | Docs | Field-level mutations |
| `publish_documents` / `unpublish_documents` / `discard_drafts` | Docs | Publishing lifecycle |
| `get_schema` / `list_workspace_schemas` / `deploy_schema` | Schema | Inspect & deploy schema |
| `deploy_studio` | Studio | Deploy Sanity Studio |
| `create_release` / `list_releases` / `create_version` / `version_discard` | Releases | Content Release management |
| `generate_image` | Media | AI image **generation** (consumes AI credits) |
| `transform_image` | Media | AI image **transformation** (consumes AI credits) |
| `list_organizations` / `list_projects` / `create_project` / `get_project_studios` | Project | Org/project management |
| `list_datasets` / `create_dataset` / `update_dataset` / `add_cors_origin` | Dataset | Dataset config |
| `search_docs` / `read_docs` | Docs(help) | Search/read Sanity documentation |
| `whoami` / `list_sanity_rules` / `get_sanity_rules` / `give_feedback` | Utility | Identity, rules, feedback |

Sources: tool names from [Sanity Docs – MCP server](https://www.sanity.io/docs/ai/mcp-server) and the [changelog](https://www.sanity.io/docs/changelog/e75b1d45-03be-4fa6-994b-248750b3fa9f) (which explicitly names `deploy_schema`, `create_project`, `generate_image`, `transform_image`, `create_document_from_json`, `create_document_from_markdown`, `get_document`, `patch_document`).

**Media/file upload — KNOWN GAP:** The remote MCP exposes AI image *generation*/*transformation* (`generate_image`, `transform_image`) but **no documented tool for uploading an arbitrary binary file / local asset to the Media Library**. Image operations are AI-driven. ([Sanity Docs – MCP server](https://www.sanity.io/docs/ai/mcp-server)) This is a genuine gap versus Contentful's `upload_asset`.

### 1.2 Sanity MCP server — LOCAL (`@sanity/mcp-server`, DEPRECATED)

- **What/where:** npm `@sanity/mcp-server`; repo `github.com/sanity-io/sanity-mcp-server` (now **archived**). ([GitHub – sanity-io/sanity-mcp-server](https://github.com/sanity-io/sanity-mcp-server))
- **Status:** Deprecated. GitHub description literally reads "Deprecated: Use the remote MCP server at https://mcp.sanity.io instead." The local server "will continue to work but won't receive new features." ([GitHub](https://github.com/sanity-io/sanity-mcp-server)) ([Changelog](https://www.sanity.io/docs/changelog/e75b1d45-03be-4fa6-994b-248750b3fa9f))
- **Version/date/license:** latest npm `0.12.2`, published **2026-03-12**, **MIT**, zero runtime deps in published manifest. (npm registry: `registry.npmjs.org/@sanity/mcp-server`)
- **Pattern/transport:** Local stdio MCP server (run via `npx`), self-hosted with a Sanity API token. (Implied by local-server model; see "Unverified" — exact env-var names `SANITY_API_TOKEN` / `MCP_USER_ROLE` not re-confirmed from the archived README in this pass.)

### 1.3 Sanity Context — read-only MCP endpoint (official)

- **What/where:** A **separate, read-only** MCP endpoint distinct from the full `mcp.sanity.io`. ([Sanity Docs – Sanity Context](https://www.sanity.io/docs/ai/sanity-context))
- **Pattern:** Hosted read-only MCP, scoped by a "Sanity Context document" that defines what an agent may see + behavior/filters.
- **Endpoint:** `https://api.sanity.io/:apiVersion/context/mcp/:projectId/:dataset/:slug`. ([Sanity Docs – Sanity Context](https://www.sanity.io/docs/ai/sanity-context))
- **Auth:** Bearer token — a Sanity API **read** token in the `Authorization` header.
- **Cannot write** to the dataset (strictly query published/draft content).

**Tool inventory (Sanity Context — 4 tools, from docs):**

| Tool | What it does |
|---|---|
| `initial_context` | Schema overview |
| `schema_explorer` | Detailed type information |
| `groq_query` | Execute GROQ query against the dataset |
| `array_field_reader` | Read large array fields and Portable Text |

Source: [Sanity Docs – Sanity Context](https://www.sanity.io/docs/ai/sanity-context).

### 1.4 Sanity Agent Actions — programmatic AI API (official, BETA) ★ editorial-workflow relevant

- **What/where:** A schema-aware AI API on the JS client namespace **`client.agent.action.*`**. "Programmatically run schema-aware AI instructions to create and modify Sanity documents." Marked experimental/beta ("APIs … subject to change"). ([Sanity Docs – Agent Actions introduction](https://www.sanity.io/docs/agent-actions/introduction)) ([Sanity blog – Agent Actions](https://www.sanity.io/blog/agent-actions-ai-building-blocks-for-structured-content))
- **Pattern:** SDK / HTTP API (NOT MCP). Embeds AI building-blocks into code so editorial workflows can be encoded deterministically.
- **Client/version:** requires `@sanity/client` ≥ **7.1.0** (one doc fetch said vX/7.1.0; Agent Actions namespace). ([Sanity Docs – Agent Actions introduction](https://www.sanity.io/docs/agent-actions/introduction)) ([@sanity/client npm](https://www.npmjs.com/package/@sanity/client))
- **Auth/transport:** Standard Sanity client auth (API token) over HTTPS; any JS-client or HTTP-capable environment.
- **Trigger contexts:** Sanity Functions, webhook listeners, CI/CD pipelines, migration scripts, custom Studio components. ([Sanity Docs – Agent Actions introduction](https://www.sanity.io/docs/agent-actions/introduction)) — this is what makes it suited to encoding editorial workflows.
- **Schema-awareness:** Requires an **up-to-date deployed schema version** (`sanity deploy` or manual schema deploy). Actions map content to the right fields using the schema. ([Sanity Docs – Agent Actions introduction](https://www.sanity.io/docs/agent-actions/introduction))
- **Cost:** Each Agent Action request consumes AI credits; org spend limits configurable in Manage.

**Action inventory (from docs + cheatsheet):**

| Action (`client.agent.action.*`) | Purpose | Key params (req/opt) |
|---|---|---|
| `generate()` | Create new structured content (whole docs or fields) from instructions; **additive only** (won't replace/remove existing content or array items); can generate images & reference connections | `schemaId` (req, string); `targetDocument` (req, `{operation:'create', _type}` or doc ID); `instruction` (req, string); `instructionParams` (opt); `documentId` (opt); `path` (opt); `target` (opt `{path,include,exclude}`); `noWrite` (opt bool); `async` (opt bool); `conditionalPaths` (opt) |
| `transform()` | Modify existing content in place (e.g. change tone, rename products); edits present content only, can't add new fields/array items | `schemaId` (req); `documentId` (req); `instruction` (req); `target` (opt); `noWrite` (opt); `conditionalPaths` (opt) |
| `translate()` | Schema-aware document/field translation (deep through nested objects/arrays/Portable Text), style guides + protected phrases | `schemaId` (req); `documentId` (req); `fromLanguage` (req `{id,title}`); `toLanguage` (req `{id,title}`); `noWrite` (opt); `conditionalPaths` (opt) |
| `prompt()` | Direct LLM request using your Sanity content as context; **returns text/JSON, no document write** | instruction-template params (see "Unverified" for exact signature) |
| `patch()` | Schema-validated patching **without LLM** — validates paths/values are schema-compliant, handles `setIfMissing` for deep ops | schema-aware patch params (see "Unverified" for exact signature) |

Sources: [Sanity Docs – Agent Actions introduction](https://www.sanity.io/docs/agent-actions/introduction); [Agent Actions cheatsheet](https://www.sanity.io/docs/agent-actions/agent-action-cheatsheet); [Sanity blog – Agent Actions](https://www.sanity.io/blog/agent-actions-ai-building-blocks-for-structured-content).

**Agent Actions media/field limits (KNOWN GAP probe):**
- `generate`/`transform` can create images **but won't save them to the Media Library** — only to the project containing the target document. Image fields need extra config; reference fields need the Embeddings API. ([Sanity Docs – Agent Actions introduction](https://www.sanity.io/docs/agent-actions/introduction))
- **`file` type is NOT supported.** `slug` (no uniqueness validation), `url` (only if instruction includes links), `image`/`reference`/`date`/`datetime` require additional config. `generate` cannot create annotations, custom marks, or inline blocks in Portable Text. ([Sanity Docs – Agent Actions introduction](https://www.sanity.io/docs/agent-actions/introduction))

### 1.5 Sanity AI Assist — Studio plugin (official)

- **What/where:** `@sanity/assist` plugin (npm `@sanity/assist`), repo `github.com/sanity-io/assist`. Open source. ([GitHub – sanity-io/assist](https://github.com/sanity-io/assist)) ([Sanity Docs – Install AI Assist](https://www.sanity.io/docs/studio/install-and-configure-sanity-ai-assist)) ([Sanity.io plugin page](https://www.sanity.io/plugins/ai-assist))
- **Pattern:** In-Studio AI plugin (UI-embedded), not an agent endpoint. Attach **reusable natural-language instructions to fields/documents** — "document-aware AI assistant" for editorial chores.
- **Translation:** Full document translation, deep through nested objects/arrays and Portable Text annotations, driven by a language field. ([Sanity Docs – AI Assist content translation](https://www.sanity.io/docs/studio/ai-assist-content-translation))
- **Requirements:** Studio ≥ v3.26.0; Growth plan and up; sends data to OpenAI for processing. ([Sanity Docs – Install AI Assist](https://www.sanity.io/docs/studio/install-and-configure-sanity-ai-assist))

### 1.6 Community: Purple-Horizons Sanity MCP (community, self-hosted)

- **What/where:** npm `@purple-horizons/sanity-mcp`, repo `github.com/Purple-Horizons/sanity-mcp`. MIT. Markets itself as "the self-hosted Sanity MCP that Sanity deprecated" — full CRUD + tools the official server lacks. ([GitHub – Purple-Horizons/sanity-mcp](https://github.com/Purple-Horizons/sanity-mcp))
- **Pattern/transport:** Local stdio MCP via `npx @purple-horizons/sanity-mcp`.
- **Auth/connection:** Simple token — env vars `SANITY_PROJECT_ID`, `SANITY_DATASET`, `SANITY_TOKEN` (`sk-…`). Works offline / air-gapped (no OAuth). ([GitHub](https://github.com/Purple-Horizons/sanity-mcp))

**Tool inventory (community, from README):**

| Tool | Type | What it does |
|---|---|---|
| `sanity_query` | Read | Execute any GROQ query |
| `sanity_get_document` | Read | Fetch single document by ID |
| `sanity_list_documents` | Read | List documents by type (paginated) |
| `sanity_search` | Read | Full-text search |
| `sanity_get_types` | Read | Discover all document types |
| `sanity_get_type_info` | Read | Schema info for a type |
| `sanity_count` | Read | Count documents matching a filter |
| `sanity_create` | Write | Create a document |
| `sanity_update` | Write | Replace an entire document |
| `sanity_patch` | Write | Partial field update |
| `sanity_delete` | Write | Delete a document |
| `sanity_publish` / `sanity_unpublish` | Write | Publishing lifecycle |
| `sanity_references` | Unique | Find all docs referencing a given doc (pre-delete safety) |
| `sanity_diff` | Unique | Compare two documents (draft vs published) |
| `sanity_history` | Unique | Revision history (who changed what) |
| `sanity_bulk` | Unique | Atomic batch ops (all-or-nothing) |
| `sanity_draft_status` | Unique | Check draft/published/both state |

Source: [GitHub – Purple-Horizons/sanity-mcp](https://github.com/Purple-Horizons/sanity-mcp). (No asset-upload tool here either — same media gap.)

### 1.7 Sanity — other agent surfaces (context)

- **GROQ query API & `@sanity/client`** are the underlying CRUD/query backbone every agent integration ultimately calls. GROQ is how agents query structured content. ([Sanity Docs – How queries work](https://www.sanity.io/docs/content-lake/how-queries-work)) ([@sanity/client](https://github.com/sanity-io/client))
- **Sanity Functions + webhooks** are the event triggers that fire Agent Actions in editorial workflows (see §1.4 trigger contexts).
- IDE/agent client cookbooks exist (e.g. Continue.dev integrates the Sanity MCP). ([Continue docs – Sanity MCP cookbook](https://docs.continue.dev/guides/sanity-mcp-continue-cookbook))

---

## PART 2 — CONTENTFUL

Contentful's **Content Management API (CMA)** is the CRUD backbone all agent integrations sit on. Two MCP servers (remote + local) share the same toolset; AI Actions and the AI Content Type Generator are native AI features.

### 2.1 Contentful MCP server — REMOTE (official, hosted)

- **What/where:** Hosted at `https://mcp.contentful.com/mcp` (EU: `https://mcp.eu.contentful.com/mcp`). Official. ([Contentful Docs – MCP server](https://www.contentful.com/developers/docs/tools/mcp-server/))
- **Pattern/transport:** HTTP MCP.
- **Auth:** **OAuth 2.1** with browser sign-in; per-session individual Contentful identity. Two-layer permission gating = user permissions + per-environment MCP **app** configuration. ([Contentful Docs – MCP server](https://www.contentful.com/developers/docs/tools/mcp-server/))
- **Scope:** Spaces/environments selected during the OAuth flow, scoped per session.
- **Security guidance:** Contentful recommends client-side human confirmation of tool calls and starting read-only before enabling writes.

### 2.2 Contentful MCP server — LOCAL (`@contentful/mcp-server`, official, open source)

- **What/where:** npm `@contentful/mcp-server`; repo `github.com/contentful/contentful-mcp-server` (monorepo; tools live in `packages/mcp-tools/src/tools/...`). **MIT**, TypeScript. ([GitHub – contentful/contentful-mcp-server](https://github.com/contentful/contentful-mcp-server))
- **Version/date:** latest npm **1.12.3**, published **2026-06-19** (very actively maintained). (npm registry: `registry.npmjs.org/@contentful/mcp-server`)
- **Pattern/transport:** Local **stdio** MCP process (`npx -y @contentful/mcp-server`). Also ships a Claude Desktop `.dxt` config in releases. ([GitHub README](https://github.com/contentful/contentful-mcp-server))
- **Auth/env vars (from README):** `CONTENTFUL_MANAGEMENT_ACCESS_TOKEN` (req, CMA PAT), `SPACE_ID` (req), `ENVIRONMENT_ID` (opt, default `master`), `CONTENTFUL_HOST` (opt, default `api.contentful.com`), `PROTECTED_ENVIRONMENTS` (opt — comma-separated env IDs blocked from write/delete). Token-owner identity for all ops. ([GitHub README](https://github.com/contentful/contentful-mcp-server))
- **Connection to CMS:** Direct to the **Contentful Management API**; every tool call also accepts `spaceId`/`environmentId` args to retarget. ([Contentful Docs – MCP server](https://www.contentful.com/developers/docs/tools/mcp-server/))
- **How tools are defined:** One file per tool under `packages/mcp-tools/src/tools/<domain>/<toolName>.ts`, each defining a **Zod** schema (`...ToolParams = BaseToolSchema.extend({...})`) and a handler; registered via per-domain `register.ts`. Extensible (open-source monorepo, `@contentful/mcp-tools` package). (Verified from repo source: `uploadAsset.ts`, `invokeAiAction.ts`, full file tree at `git/trees/main?recursive=1`.)

**Tool inventory (official MCP, verified from README table + repo file tree):**

| Category | Tool | What it does |
|---|---|---|
| Context | `get_initial_context` | Initialize connection / get usage instructions (mandatory first call) |
| Content Types | `list_content_types`, `get_content_type`, `create_content_type`, `update_content_type`, `publish_content_type`, `unpublish_content_type`, `delete_content_type` | Content-model CRUD + publish lifecycle. Repo also has field-level: `deleteContentTypeField`, `disableContentTypeField`, `omitContentTypeField` |
| Entries | `search_entries`, `semantic_search` (vector), `get_entry`, `get_entry_snapshot`, `create_entry`, `update_entry`, `publish_entry` (single/bulk), `unpublish_entry` (single/bulk), `delete_entry` | Entry CRUD, search, snapshots/version history. Repo also: `archiveEntry`, `unarchiveEntry`, `resolveEntryReferences` |
| Assets | `upload_asset`, `list_assets`, `get_asset`, `update_asset`, `publish_asset`, `unpublish_asset`, `delete_asset` | Asset CRUD + publish. Repo also: `archiveAsset`, `unarchiveAsset` |
| Spaces/Envs | `list_spaces`, `get_space`, `list_environments`, `create_environment`, `delete_environment` | Space/env discovery + management |
| Locales | `list_locales`, `get_locale`, `create_locale`, `update_locale`, `delete_locale` | Multi-language locale config |
| Tags | `list_tags`, `create_tag` | Content tagging/organization |
| AI Actions | `list_ai_actions`, `get_ai_action`, `create_ai_action`, `update_ai_action`, `publish_ai_action`, `unpublish_ai_action`, `delete_ai_action`, `invoke_ai_action`, `get_ai_action_invocation` | Full AI Action CRUD + invoke + poll invocation result |
| Editor Interfaces | `getEditorInterface`, `listEditorInterfaces`, `updateEditorInterface` | Field presentation config (repo source) |
| Jobs | space-to-space migration: `exportSpace`, `importSpace` | Bulk migration jobs (repo source) |

Sources: README "Available Tools" table ([GitHub README](https://github.com/contentful/contentful-mcp-server)) + verified repo file tree under `packages/mcp-tools/src/tools/`. Remote-server docs additionally list **Taxonomy** (concepts / concept schemes) and **Organizations** discovery tools. ([Contentful Docs – MCP server](https://www.contentful.com/developers/docs/tools/mcp-server/))

**Media/file upload — SOLVED (verified from source `uploadAsset.ts`):**
`upload_asset` params (Zod): `title` (req string), `description` (opt), `file` (req: `{ fileName` (req), `contentType` (req MIME), `upload` (opt) }`), `metadata`, `locale` (opt, default `en-US`). The `upload` field "accepts either a publicly accessible `https://` URL, **or a base64-encoded data URI** (`data:image/png;base64,...`). Use the data URI format to upload local files — the MCP client should base64-encode the file." Internally it decodes base64 to a Buffer and uploads to the CMA. So Contentful's local file upload IS supported (base64), unlike Sanity's MCP.
The **remote** server uses a different two-phase flow for binaries (docs): `create_upload_session` → returns temp URL + handle → PUT raw bytes (handle acts as capability token, unauthenticated) → `upload_asset` with the handle. Sessions expire after 1 hour, single-use. (ChatGPT clients skip step 1 — files attach to the conversation.) ([Contentful Docs – MCP server](https://www.contentful.com/developers/docs/tools/mcp-server/))

**AI Action invocation (verified from source `invokeAiAction.ts`):** `invoke_ai_action` params: `aiActionId` (req string) + `fields` (array of `{ outputFormat` (enum), `variables` (array of variable assignments) }`). The tool **polls** the invocation (default 30s interval, up to 10 attempts) on `aiActionInvocation.get` until status `COMPLETED` (returns `result.content`, a string or rich-text `Document`) or `FAILED`/`CANCELLED`.

### 2.3 Contentful AI Actions — native AI feature (official)

- **What:** Native module embedding generative AI in CMS workflows. Reusable AI Action = name, description, **instruction template**, instruction variables (**up to 10 per action**, placeholders like `{{var.t82kaxhw0s13}}`), model config, test cases. ([Contentful Help – AI Actions](https://www.contentful.com/help/ai-automations/ai-actions/)) ([Contentful blog – AI Actions workflow automation](https://www.contentful.com/blog/ai-actions-workflow-automation/))
- **Agentic features:** Workflow Automation (AI Actions tied to workflow steps, auto-progressing on completion); contextual awareness via Variables + **External References** (e.g. Shopify, brand tone, locale); pre-built templates (translation, SEO, alt-text generation, grammar). ([Contentful blog – AI Actions workflow automation](https://www.contentful.com/blog/ai-actions-workflow-automation/))
- **REST/CMA:** AI Actions live under the CMA at `/spaces/{spaceId}/ai/actions`; invocation is a CMA entity (media type `application/vnd.contentful.management.v1+json`). ([contentful-management.js endpoints](https://github.com/contentful/contentful-management.js/blob/master/lib/adapters/REST/endpoints/index.ts)) ([Contentful Help – AI Actions instructions](https://www.contentful.com/help/ai-automations/ai-actions/work-with-ai-actions/instructions/))
- **Agent access:** exposed to agents via the MCP `*_ai_action` tools (§2.2) — agents can create AND invoke AI Actions.

### 2.4 Contentful AI Content Type Generator + AI Content Generator (official)

- **AI Content Type Generator:** Generally available; designs/builds content models (content types) from a natural-language prompt. Built on OpenAI; no content-modeling expertise needed. ([Contentful Docs – AI Content Type Generator](https://www.contentful.com/developers/docs/tools/ai-content-type-generator/)) ([Contentful blog](https://www.contentful.com/blog/jumpstart-your-content-modeling-with-the-ai-content-type-generator/))
- **AI Content Generator app:** In-editor app to generate field content with prompts. ([Contentful Help – AI Content Generator app](https://www.contentful.com/help/apps/ai-content-generator-app/))

### 2.5 Contentful — other agent surfaces (context)

- **CMA / `contentful-management.js`** = the CRUD backbone behind every integration. ([contentful-management.js](https://github.com/contentful/contentful-management.js))
- **App Framework — App Actions & Functions** are programmatic extension points (custom server-side actions / functions) that can wrap AI/agent logic into Contentful. ([Contentful Docs – App Actions](https://www.contentful.com/developers/docs/extensibility/app-framework/app-actions/)) ([Contentful Docs – Functions](https://www.contentful.com/developers/docs/extensibility/app-framework/functions/))
- **`@contentful/mcp-tools`** is published separately on npm — the reusable tool library powering the MCP server (extensible). ([npm @contentful/mcp-tools](https://www.npmjs.com/package/@contentful/mcp-tools))
- **Community MCP:** `ivo-toby/contentful-mcp` predates the official server — a separate community CMA MCP. ([GitHub – ivo-toby/contentful-mcp](https://github.com/ivo-toby/contentful-mcp))

---

## CROSS-PLATFORM PATTERN MAP

| Pattern | Sanity | Contentful |
|---|---|---|
| Official hosted MCP (HTTP, OAuth) | `mcp.sanity.io` (full r/w, 40+ tools) | `mcp.contentful.com/mcp` (OAuth 2.1) |
| Official read-only MCP | Sanity Context (4 tools, bearer token) | (read-only achieved via permission gating, not a separate endpoint) |
| Official local MCP (stdio, token) | `@sanity/mcp-server` (**deprecated**, MIT) | `@contentful/mcp-server` (**active**, MIT, v1.12.3) |
| Native programmatic AI API | **Agent Actions** (`client.agent.action.*`: generate/transform/translate/prompt/patch) | **AI Actions** (instruction templates, invoke via CMA/MCP) |
| Native model-building AI | (schema via Studio) | **AI Content Type Generator** |
| In-editor AI plugin | **AI Assist** (`@sanity/assist`) | **AI Content Generator app** |
| Query language for agents | **GROQ** | CMA queries + `semantic_search` |
| CRUD backbone | Content Lake API / `@sanity/client` | **CMA** / `contentful-management.js` |
| Local file upload via agent | ✗ not supported in MCP/Agent Actions | ✓ `upload_asset` (https URL or base64 data URI) |
| Community self-hosted MCP | `@purple-horizons/sanity-mcp` (adds refs/diff/history/bulk) | `ivo-toby/contentful-mcp` |
| Event triggers for AI workflows | Sanity Functions + webhooks → Agent Actions | Workflow Automation steps + App Actions/Functions |

---

## UNVERIFIED / GAPS

1. **Sanity remote MCP exact full tool list (all 40+) and per-tool parameter schemas** — not individually enumerated; the remote server is closed-source, so I have category-level + named tools from docs/changelog but no tool-definition source file to confirm parameter types/required status. Tool count "40+" is a marketing figure.
2. **Sanity Agent Actions `prompt()` and `patch()` exact signatures** — docs confirm they exist and their behavior, but one cheatsheet fetch returned signatures only for `generate`/`transform`/`translate`. The `prompt`/`patch` parameter lists (e.g. `instruction` template params, patch op shapes) are described prose-only, not confirmed field-by-field here.
3. **Local `@sanity/mcp-server` env vars / transport / `MCP_USER_ROLE`** — the repo is archived and the fetched README surfaced only the deprecation notice; I could NOT re-confirm the exact env-var names (`SANITY_API_TOKEN`, `SANITY_PROJECT_ID`, `SANITY_DATASET`) or the documented `MCP_USER_ROLE` (developer/editor/agent) gating from primary source in this pass. Treat the stdio/token model as inferred.
4. **Agent Actions return shapes** — docs describe `noWrite` preview behavior and image/field limits but did not give explicit JSON return schemas.
5. **Contentful remote-server extra tool domains (Taxonomy, Organizations)** — named in remote docs but their exact tool names weren't pulled from source (remote/hosted; the open-source `mcp-tools` repo is the closest verifiable proxy and does NOT show a `taxonomy/` dir in the file slice I captured, though `AssetMetadataSchema` imports from `types/taxonomySchema.ts`).
6. **Pricing/credit specifics** — both vendors meter AI (Sanity AI credits; Contentful AI Action usage), but exact rates not researched (out of scope).
7. **`ivo-toby/contentful-mcp` tool inventory** — identified as the notable community server but its specific tools weren't enumerated this pass.
