# Cross-Cutting Integration Patterns: AI Agents ↔ CMS Platforms

Sub-agent research strand. Every claim carries an inline source URL. Prioritizes primary
sources (MCP spec at modelcontextprotocol.io, vendor docs, GitHub issues) over roundups.
"Unverified / gaps" list at the end.

---

## 1. The integration-pattern taxonomy

Seven recurring patterns connect AI agents to CMS platforms. Each is defined, exemplified,
and sourced below.

### (a) MCP servers — remote/hosted HTTP vs local/stdio

**Definition.** A Model Context Protocol (MCP) server exposes a CMS's capabilities as
standardized JSON-RPC tools/resources that any MCP-compliant client (Claude Code/Desktop,
Cursor, etc.) can call. "With MCP, you write the integration once as a server, and any
MCP-compliant client … can call it"
([code.claude.com/docs/en/mcp](https://code.claude.com/docs/en/mcp)). MCP defines two
standard transports: **stdio** (client launches the server as a local subprocess; JSON-RPC
over stdin/stdout, newline-delimited) and **Streamable HTTP** (server is an independent
process at a single HTTP endpoint supporting POST and GET, optionally SSE for streaming)
([modelcontextprotocol.io/specification/2025-11-25/basic/transports](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)).
"Clients **SHOULD** support stdio whenever possible" (ibid).

- **Local/stdio example:** A self-hosted Contentful or Strapi MCP server run as an `npx`
  subprocess on the developer's machine
  ([npmjs.com/package/@contentful/mcp-tools](https://www.npmjs.com/package/@contentful/mcp-tools)).
- **Remote/hosted HTTP example:** The official Sanity MCP server runs as a hosted remote
  service at `https://mcp.sanity.io`; clients that lack remote support proxy it via
  `mcp-remote --transport http-only`
  ([sanity.io/docs/ai/mcp-server](https://www.sanity.io/docs/ai/mcp-server)).

### (b) Agent skills (Claude Agent Skills, SKILL.md manifests)

**Definition.** A Skill is a modular capability packaged as a `SKILL.md` file (markdown
with YAML frontmatter + body, plus optional bundled `scripts/`, `references/`, `assets/`)
that Claude loads on demand when a task matches the skill's description
([platform.claude.com/docs/en/agents-and-tools/agent-skills/overview](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview)).
The defining mechanic is **progressive disclosure**: only the name + one-line description
(~80 tokens/skill) load at startup; the full SKILL.md body loads when the skill is selected;
bundled scripts/references load only at the execution step that needs them
([leehanchung.github.io/blogs/2025/10/26/claude-skills-deep-dive](https://leehanchung.github.io/blogs/2025/10/26/claude-skills-deep-dive/),
[swirlai.com/p/agent-skills-progressive-disclosure](https://www.newsletter.swirlai.com/p/agent-skills-progressive-disclosure)).
"The frontmatter configures HOW the skill runs … the markdown content tells Claude WHAT to do"
([termdock.com/blog/skill-md-vs-claude-md-vs-agents-md](https://www.termdock.com/blog/skill-md-vs-claude-md-vs-agents-md)).
Contrast with `CLAUDE.md`/`AGENTS.md`, which are persistent context, not on-demand.

- **Example (CMS-relevant):** A `SKILL.md` that teaches an agent a platform's content-model
  conventions and bundles helper scripts to call its API — loaded only when the task is
  about that CMS.

### (c) Agent/IDE plugins

**Definition.** A plugin packages skills, MCP server definitions, slash commands, and hooks
into one installable unit distributed via a marketplace (a GitHub repo registry). "Plugins
define MCP servers in `.mcp.json` at the plugin root or inline in `plugin.json` · When a
plugin is enabled, its MCP servers start automatically"
([clarista.io/blog/claude-code-mcp-plugins-guide](https://www.clarista.io/blog/claude-code-mcp-plugins-guide)).
For Claude Desktop, the analogous one-click unit is a **Desktop Extension** (`.dxep`/`.mcpb`)
that bundles an MCP server so non-technical users install with one click
([anthropic.com/engineering/desktop-extensions](https://www.anthropic.com/engineering/desktop-extensions)).

- **Example:** Installing a CMS plugin from `anthropics/claude-plugins-official` or a
  community marketplace, which auto-starts the CMS MCP server
  ([claudemarketplaces.com](https://claudemarketplaces.com/)).

### (d) Agent SDKs wrapping CMS APIs

**Definition.** Code frameworks that let developers define tools (often thin wrappers over
CMS REST/GraphQL endpoints) and hand them to a model with an agent loop. Key SDKs:
- **Vercel AI SDK** — unified TypeScript API across providers; v6 adds programmatic tool
  calling and `needsApproval` human-in-the-loop
  ([vercel.com/blog/ai-sdk-6](https://vercel.com/blog/ai-sdk-6)).
- **OpenAI Agents SDK** — lightweight multi-agent framework (handoffs) launched March 2025
  ([dev.to/muhammad_moeed/claude-agent-sdk-vs-vercel-ai-sdk-6](https://dev.to/muhammad_moeed/claude-agent-sdk-vs-vercel-ai-sdk-6-which-to-pick-in-2026-2jj)).
- **Claude Agent SDK** — Anthropic's toolkit for long-running agents, with subagents,
  hooks, built-in tools, prompt caching, and Skills support
  ([platform.claude.com/docs/en/agent-sdk/skills](https://platform.claude.com/docs/en/agent-sdk/skills)).
- **LangChain** — orchestration framework; the Vercel AI SDK ships a LangChain adapter
  ([strapi.io/blog/langchain-vs-vercel-ai-sdk-vs-openai-sdk-comparison-guide](https://strapi.io/blog/langchain-vs-vercel-ai-sdk-vs-openai-sdk-comparison-guide)).

- **Example:** A developer wraps `contentful.entry.createDraft()` and `.publish()` as SDK
  tools and gives them to a Claude/OpenAI agent — distinct from running a standalone MCP server.

### (e) REST/GraphQL wrappers / function-calling over existing CMS APIs

**Definition.** The lowest-level pattern: expose existing CMS Content Management API (REST)
or GraphQL operations as model function/tool definitions. This is what (a) and (d) ultimately
wrap; many CMS MCP servers are literally a tool-per-endpoint over the Management API. Example:
the Contentful MCP server's CRUD tools map to the Content Management API
([contentful.com/developers/docs/references/content-management-api](https://www.contentful.com/developers/docs/references/content-management-api/));
Sanity's tools wrap GROQ queries + document patches
([sanity.io/docs/ai/mcp-server](https://www.sanity.io/docs/ai/mcp-server)).

### (f) Native in-product AI features

**Definition.** AI built directly into the CMS UI/API by the vendor, rather than connected
externally. "AI is no longer a plugin in modern CMS platforms"
([codebrewtools.com/blogs/best-ai-native-cms-2026](https://codebrewtools.com/blogs/best-ai-native-cms-2026)).
- **Sanity:** AI Assist + **Agent Actions** — "schema-aware AI APIs that … create, modify,
  translate and transform structured content at scale," governed with auditability
  ([sanity.io/blog/compute-event-handlers-for-document-actions](https://www.sanity.io/blog/compute-event-handlers-for-document-actions),
  [webstacks.com/blog/sanity-agent-actions-ai-content-workflow-automation](https://www.webstacks.com/blog/sanity-agent-actions-ai-content-workflow-automation)).
- **Contentful AI Actions** — AI-assisted tooling focused on localization/global scale
  ([represent.no/articles/contentful-vs-sanity-vs-storyblok](https://www.represent.no/articles/contentful-vs-sanity-vs-storyblok-a-practical-comparison-for-modern-web-development)).
- **Storyblok** — AI writing assistance in the visual editor; can suggest component layouts
  ([monterail.com/blog/which-cms-to-choose](https://www.monterail.com/blog/which-cms-to-choose)).

### (g) Webhooks / event-driven + serverless functions that trigger agents

**Definition.** Content events (create/update/delete) fire webhooks or run serverless
functions that invoke an agent. **Sanity Functions** are "serverless, event-driven code
execution units running on Sanity's managed cloud infrastructure (Node.js v22.x)"; on a
document change they "execute custom logic to maintain data consistency, trigger workflows,
or perform automated tasks," with GROQ filters in triggers
([sanity.io/blog/compute-event-handlers-for-document-actions](https://www.sanity.io/blog/compute-event-handlers-for-document-actions),
[webstacks.com/blog/sanity-webhooks-functions-serverless-automation](https://www.webstacks.com/blog/sanity-webhooks-functions-serverless-automation)).
Agent Actions "can be triggered from … Sanity Functions (serverless), custom Studio
components, webhooks and any HTTP-capable code execution environment"
([focusreactive.com/sanity-agent-actions-functions-and-blueprints](https://focusreactive.com/sanity-agent-actions-functions-and-blueprints/)).
Contentful exposes webhook configuration as well
([npmjs.com/package/@contentful/mcp-tools](https://www.npmjs.com/package/@contentful/mcp-tools)).

> **Synthesis note for the lead:** (a)–(g) form a layered spectrum from raw API exposure
> (e) up through wrappers (a, d), packaging (b, c), vendor-native (f), and event triggers (g).
> Most real CMS integrations combine several — e.g. an MCP server (a) over the REST API (e),
> installed as a plugin (c), with Functions (g) for autonomous triggers.

---

## 2. MCP transport + auth landscape

### Transport evolution: stdio → SSE → Streamable HTTP
- **2024-11-05** spec defined stdio + HTTP+SSE as the two transports.
- **2025-03-26** introduced **Streamable HTTP** and **deprecated HTTP+SSE**. The spec page
  states Streamable HTTP "replaces the HTTP+SSE transport from protocol version 2024-11-05"
  ([modelcontextprotocol.io/specification/2025-11-25/basic/transports](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)).
- Streamable HTTP uses **one** MCP endpoint for POST+GET; SSE is optional within it for
  server→client streaming. Stateful sessions via the `MCP-Session-Id` header (assigned at
  init; "globally unique and cryptographically secure (e.g., a securely generated UUID, a
  JWT, or a cryptographic hash)") (ibid).
- Clients must send `MCP-Protocol-Version` header on every request (ibid).

### Auth: OAuth 2.1 for remote servers
- The MCP Authorization spec mandates OAuth 2.1 for remote HTTP servers: "Authorization
  servers MUST implement OAuth 2.1 with appropriate security measures for both confidential
  and public clients"
  ([modelcontextprotocol.io/specification/2025-11-25/basic/authorization](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization)).
- **PKCE required for all clients** (incl. confidential), per OAuth 2.1
  ([descope.com/blog/post/mcp-auth-spec](https://www.descope.com/blog/post/mcp-auth-spec)).
- MCP servers act as **OAuth Resource Servers** and MUST implement Protected Resource
  Metadata (RFC 9728); clients use it for auth-server discovery (ibid).
- All AS endpoints over **HTTPS**; access tokens **MUST NOT** appear in URI query strings —
  use the `Authorization` header (ibid).

### API-key / PAT auth
- Many CMS MCP servers support a simpler **token / PAT** path alongside or instead of OAuth.
  Sanity: "When configured with the header, the server will not use OAuth. Tool calls will
  use the API token in accordance with its role and scoped to its permissions"; OAuth is the
  default with sessions that "typically expire after 7 days"
  ([sanity.io/docs/ai/mcp-server](https://www.sanity.io/docs/ai/mcp-server)).
- Contentful MCP uses **Content Management API tokens** for full read-write access
  ([trusted-mcp.org/servers/contentful](https://trusted-mcp.org/servers/contentful/)).

### Security implications (transport-level)
- Streamable HTTP servers **MUST validate the `Origin` header** to prevent DNS rebinding
  (respond 403 if invalid); when local, **SHOULD bind only to 127.0.0.1**, not 0.0.0.0
  ([modelcontextprotocol.io/specification/2025-11-25/basic/transports](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)).
- **Token passthrough is forbidden:** "MCP servers MUST NOT accept any tokens that were not
  explicitly issued for the MCP server"
  ([modelcontextprotocol.io/specification/2025-11-25/basic/security_best_practices](https://modelcontextprotocol.io/specification/2025-11-25/basic/security_best_practices)).
- **Sessions are not auth:** "MCP servers MUST NOT use sessions for authentication"; bind
  session IDs to user info (`<user_id>:<session_id>`) to resist hijacking (ibid).

---

## 3. The media / file-upload gap

**Why uploading binary files through MCP/agent tools is hard.**

1. **MCP tool args are JSON — no native binary.** The protocol encodes messages as JSON-RPC
   (UTF-8)
   ([modelcontextprotocol.io/specification/2025-11-25/basic/transports](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)),
   so there is no first-class way to pass raw bytes. The MCP proposal SEP-1306 ("Binary Mode
   Elicitation for File Uploads") states the status quo requires "complex base64 encoding
   within text fields (inefficient, size-limited)"
   ([github.com/modelcontextprotocol/modelcontextprotocol/issues/1306](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/1306)).

2. **Base64 bloat + context-window cost.** Base64 expands payloads ~33% and, when routed
   through the model, "any modern image is too large to load as a base64 string and pass
   through the LLM, consuming tons of tokens"
   ([github.com/modelcontextprotocol/servers/issues/297](https://github.com/modelcontextprotocol/servers/issues/297)).
   Real bug reports show MCP file tools silently truncating uploads "around 10K base64 chars"
   and returning "The file content is not a valid base64 string"
   ([github.com/anthropics/claude-code/issues/50358](https://github.com/anthropics/claude-code/issues/50358),
   [github.com/anthropics/claude-code/issues/54137](https://github.com/anthropics/claude-code/issues/54137)).

3. **Multi-step signed-upload flows.** CMS asset APIs are multi-call. Contentful: creating an
   asset "requires three steps and API calls: Create an asset, Process an asset, and Publish
   an asset"; direct bytes go via the Upload API (`POST /spaces/{id}/uploads` → upload ID →
   reference in asset create)
   ([contentful.com/developers/docs/references/content-management-api](https://www.contentful.com/developers/docs/references/content-management-api/)).
   Each step is a separate tool call an agent must orchestrate.

4. **"Reference existing asset" vs "upload new bytes."** Referencing is cheap (pass a URL or
   an existing asset ID); uploading new bytes is the hard path. Contentful supports the easy
   path via an external URL in the `upload` field: `'upload': 'https://url.to/file.png'`, and
   "Contentful to serve remote files" without the agent ever handling bytes (ibid).

**Workarounds (synthesized):**
- **URL-based import** — pass a public URL; the CMS fetches the bytes (Contentful `upload`
  field) (ibid).
- **base64 data URIs** — inline small files; breaks down past ~10K chars / large media
  ([github.com/anthropics/claude-code/issues/50358](https://github.com/anthropics/claude-code/issues/50358)).
- **Two-phase / signed upload sessions** — upload bytes out-of-band to an upload endpoint,
  then reference the returned ID (Contentful Upload API) (ibid).
- **Out-of-band REST upload** — SEP-1306 notes current options include "External file hosting
  with URL sharing" and "Pre-uploading files to shared locations," flagged for security and UX
  cost; the proposed fix is a native `binary` **elicitation mode** reusing the
  accept/decline/cancel model
  ([github.com/modelcontextprotocol/modelcontextprotocol/issues/1306](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/1306)).

---

## 4. Security & maturity themes

- **Prompt injection via content.** Untrusted CMS content can carry instructions: "prompt
  injection attacks can exploit AI agents that interact with external content, such as
  injected prompts in public documents." The attack doesn't bypass RBAC — it "steers
  autonomous systems operating with legitimate access" to act
  ([goteleport.com/blog/prevent-prompt-injection](https://goteleport.com/blog/prevent-prompt-injection/),
  [obsidiansecurity.com/blog/prompt-injection](https://www.obsidiansecurity.com/blog/prompt-injection)).
  MCP spec notes a session-hijack-via-prompt-injection vector on resumable streams
  ([modelcontextprotocol.io/specification/2025-11-25/basic/security_best_practices](https://modelcontextprotocol.io/specification/2025-11-25/basic/security_best_practices)).

- **Over-broad permissions / RBAC scoping.** MCP spec's **Scope Minimization** section:
  "Poor scope design increases token compromise impact." Avoid publishing all scopes or
  wildcard/omnibus scopes (`*`, `all`, `full-access`); use a "progressive, least-privilege
  scope model" with incremental elevation via `WWW-Authenticate` challenges (ibid). Security
  guidance: agents "shouldn't have unrestricted access to databases, APIs, or privileged
  operations; restrict API permissions to only essential functions"
  ([goteleport.com/blog/prevent-prompt-injection](https://goteleport.com/blog/prevent-prompt-injection/)).
  CMS-side: Sanity tool calls are "scoped to [the token's] permissions" and Sanity offers
  field-level permissions; Contentful's MCP permission layer is coarser
  ([sanity.io/docs/ai/mcp-server](https://www.sanity.io/docs/ai/mcp-server),
  [skywork.ai/.../unlocking-content-ai-sanity-cms](https://skywork.ai/skypage/en/unlocking-content-ai-sanity-cms/1979016150189199360)).

- **"Destructive operation" gating pattern.** Two layers: (1) tool annotations — Contentful
  MCP tools carry "readOnly, destructive, idempotent, and openWorld" semantic annotations
  ([trusted-mcp.org/servers/contentful](https://trusted-mcp.org/servers/contentful/)); (2)
  draft-safety — Sanity writes never touch published content directly: `create_documents`
  makes drafts unless a `releaseId` is given, `patch_documents` saves "to the draft or release
  version; published content is never modified directly," with separate `publish_documents` /
  `unpublish_documents` tools
  ([sanity.io/docs/ai/mcp-server](https://www.sanity.io/docs/ai/mcp-server)). General pattern:
  "AI-generated actions that could result in security risks should require human approval"
  ([goteleport.com/blog/prevent-prompt-injection](https://goteleport.com/blog/prevent-prompt-injection/));
  Vercel AI SDK 6 implements this as one-line `needsApproval`
  ([vercel.com/blog/ai-sdk-6](https://vercel.com/blog/ai-sdk-6)).

- **Beta/experimental status of CMS MCP servers.** Mixed and moving. Sanity's official server
  reads as **production-ready** (changelog June 10 2026, v2.21.0; no beta label in docs)
  ([sanity.io/docs/ai/mcp-server](https://www.sanity.io/docs/ai/mcp-server)) — note this
  contradicts the common "everything is beta" framing; one secondary source still calls it
  "official and experimental"
  ([skywork.ai/.../unlocking-content-ai-sanity-cms](https://skywork.ai/skypage/en/unlocking-content-ai-sanity-cms/1979016150189199360)).
  Many other CMS MCP servers are community-maintained (e.g. third-party Contentful, Strapi
  servers), so maturity varies per server — verify per vendor.

- **Audit logging.** Sanity's governed AI (AI Assist + Agent Actions) is positioned around
  "full auditability"
  ([webstacks.com/blog/sanity-agent-actions-ai-content-workflow-automation](https://www.webstacks.com/blog/sanity-agent-actions-ai-content-workflow-automation)).
  MCP spec ties audit integrity to forbidding token passthrough (otherwise "downstream … logs
  may show requests that appear to come from a different source")
  ([modelcontextprotocol.io/specification/2025-11-25/basic/security_best_practices](https://modelcontextprotocol.io/specification/2025-11-25/basic/security_best_practices)).

---

## 5. Common content workflows → generic primitives

Platform-independent canonical tasks and the generic API steps each needs. Primitives drawn
from Contentful CMA + Sanity tool docs (cited above); these are the building blocks any CMS
agent composes.

| # | Workflow | Generic primitives (in order) |
|---|----------|------------------------------|
| (a) | **Draft + publish a localized article** | `create draft` entry → set field values **per locale** (`{ "title": { "en-US": …, "de-DE": … } }`) → `publish`. Contentful `fields` are always locale-keyed; Sanity `create_documents` makes drafts then `publish_documents`. |
| (b) | **Bulk-update entries matching a query** | `query/filter` (GROQ / CMA search) → iterate → `patch` each (idempotent partial update) → optional `publish`/`republish`. |
| (c) | **Upload + attach media** | `upload asset bytes` (out-of-band Upload API) **or** `reference external URL` → `create asset` → `process asset` → `publish asset` → `patch` entry to link the asset reference. |
| (d) | **Scaffold a new content type / schema** | `schema mutation` — create content-type/document-type with field definitions, locales, validations (schema-as-code in Sanity; content-type create in Contentful CMA). Highest-privilege, most "destructive" class. |
| (e) | **Run an editorial approval** | `status transition` — move entry through draft → in-review → approved/published states; often gated by human-in-the-loop (`needsApproval`) before the publish primitive. |
| (f) | **Launch a marketing campaign (custom styles + web pages)** | composite: `schema mutation` (new page/component types) → `create draft`(s) → `set locale`(s) → `asset upload`/attach (styles, images) → `status transition` (review) → `publish`; often wired to `webhook/function` triggers for downstream rebuilds. |

**The seven generic primitives** recurring across all workflows: **query**, **create draft**,
**set locale**, **patch**, **publish** (+ status transition), **asset upload/reference**,
**schema mutation**. (Sources for the concrete shapes:
[contentful.com/developers/docs/references/content-management-api](https://www.contentful.com/developers/docs/references/content-management-api/),
[sanity.io/docs/ai/mcp-server](https://www.sanity.io/docs/ai/mcp-server).)

---

## Unverified / gaps

- **Contentful Functions** (parallel to Sanity Functions) — I confirmed Sanity Functions in
  primary/vendor sources but did **not** fetch a primary Contentful Functions doc this round;
  the existence of Contentful Functions as an event/serverless trigger should be verified
  against contentful.com docs before asserting in answer.md. Contentful webhooks are confirmed.
- **OpenAI Agents SDK** launch date (March 2025) and **Vercel AI SDK 6** feature claims come
  from secondary/blog sources, not the canonical SDK changelogs — corroborate via official
  docs if used as load-bearing claims.
- **Sanity MCP maturity:** docs imply production-ready (v2.21.0) but a secondary source labels
  it "experimental." Resolve by quoting the vendor changelog directly. Avoid the blanket claim
  that "most CMS MCP servers are beta" — it's true for many community servers but not Sanity's
  official one; state per-vendor.
- **Strapi / WordPress / Storyblok MCP servers** not deeply verified here (only Storyblok's
  native AI editor and a Strapi MCP reference surfaced); treat their MCP specifics as unconfirmed.
- The Contentful three-step asset flow and external-URL `upload` field were read via a
  fetch summary of the CMA reference, not a line-by-line spec quote — wording is paraphrased
  but consistent with the official reference URL cited.
- **base64 ~10K-char truncation** is a client-specific bug (Google Drive MCP via Claude Code),
  illustrative of the general limitation but not a universal MCP constraint.
