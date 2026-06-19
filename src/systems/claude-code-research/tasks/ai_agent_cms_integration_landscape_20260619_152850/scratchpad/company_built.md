# Company-built CMS / content stacks connected to AI agents

How individual companies (not general CMS frameworks) expose their *own* editorial/business-workflow
knowledge to agents. Organized by company/example. Each entry: what it is, where it lives, the
integration pattern, and **how business-flow knowledge is encoded**. Primary sources flagged;
marketing vs. verifiable fact distinguished.

---

## 1. Block / Square — "goose" agent + internal MCP fleet

**What it is.** Block (Square's parent) open-sourced **`goose`** ("codename goose"), an on-machine,
MCP-compatible AI agent (CLI + desktop). Goose was the **first public MCP client**; Block contributed
to the MCP spec before it shipped after raising integration friction with Anthropic.
- Announcement (primary): https://block.xyz/inside/block-open-source-introduces-codename-goose
- Block OSS / goose engineering blog (primary): https://dev.to/goose_oss/mcp-in-the-enterprise-real-world-adoption-at-block-ci5

**Where it lives.** Maintained by Block Open Source. Repo: github.com/block/goose (referenced across
sources). Thousands of Block employees use it daily; one secondary tally cites "60+ internal MCP
servers across ~12,000 employees / 15+ job functions" (mcpbundles/guptadeepak secondary — treat the
exact numbers as unverified).

**Integration pattern.** Goose connects to internal systems purely through **MCP servers authored by
Block's own engineers** — "all MCP servers used internally are authored by our own engineers. This
allows us to tailor each integration to our systems and use cases." Named internal connectors from the
blog: **Snowflake** (data), **GitHub** and **Jira** (dev), **Slack** and **Google Drive** (info
gathering), and **internal APIs** for **compliance checks** and **support triage**. Non-engineering
teams (design, product, support, risk) use goose to **generate documentation, triage tickets, build
prototypes** — i.e., content-adjacent ops, though the blog gives no proprietary CMS tool names.

**How business-flow knowledge is encoded (verifiable):**
- **Custom, in-house MCP servers per system** are the primary encoding mechanism — business logic
  lives in engineer-authored servers tailored to Block's systems, not in generic wrappers.
- **Approval / gating via tool annotation:** Block annotates tools as **"read-only" or "destructive"
  to require user confirmation when necessary** — a human-in-the-loop gate expressed at the tool level.
- **Data-governance gating:** "some servers enforce LLM allowlists or restrict tool output from being
  shared across systems."
- DataHub's MCP server is one documented data-catalog connector Block uses
  (https://datahub.com/blog/datahub-mcp-server-block-ai-agents-use-case/ — vendor blog, secondary).

**Marketing vs fact:** The "50–75% time saved" figures come from Block's own/vendor framing — treat as
self-reported. The MCP-client-first and engineer-authored-server claims are well-corroborated.

---

## 2. Anthropic — "Claude Agent Skills" as a pattern for encoding company workflows

**What it is.** **Agent Skills** = folders containing a **`SKILL.md`** (YAML frontmatter + instructions),
optionally bundling scripts/resources. Claude loads them dynamically via **progressive disclosure**
(name/description first; full body and referenced files only when relevant), keeping context cheap.
- Docs (primary): https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview
- Public skills repo (primary): https://github.com/anthropics/skills
- Became an open standard (agentskills.io / agentskills.io) in Dec 2025; adopted by Copilot, Cursor,
  Codex, Gemini CLI, Goose, etc. (secondary corroboration: Nimble, swirlai).

**Integration pattern (workflow-as-skill).** A Skill packages a *repeatable company workflow* as
natural-language instructions + optional helper scripts. "Teams that can build high-quality Skills
reliably can encode any domain workflow into Claude." Documented content/CMS-like examples:
- **`brand-guidelines`** skill (in anthropics/skills): enforces Anthropic's color palette, typography
  (Poppins headings / Lora body), and accent rules; applies them programmatically (e.g., RGB-accurate
  color via `python-pptx`). This is a concrete **editorial/brand workflow encoded as a skill**.
  - https://github.com/anthropics/skills ; https://mcpservers.org/agent-skills/anthropic/brand-guidelines
- Document skills (**docx / pptx / xlsx** read-write-edit) in the same repo — content-production ops.
- Vendor-shipped **Canva** skill (generate/edit/template designs with brand awareness) — secondary
  (lobehub/awesomeskill listings); treat as community/marketplace, verify against Canva primary if cited.

**How business-flow knowledge is encoded:** The **SKILL.md body itself is the encoded workflow** —
brand rules, required steps, ordering, and "when to use" triggers live in plain text + scripts.
Progressive disclosure is the delivery mechanism. This is the cleanest documented pattern for turning
*editorial/business rules* (brand, formatting, "always do X before Y") into agent-consumable artifacts.

---

## 3. Anthropic engineering — best-practice PATTERN for workflow-as-tools

**Source (primary):** "Writing effective tools for AI agents" —
https://www.anthropic.com/engineering/writing-tools-for-agents
Companion: "Effective context engineering for AI agents" —
https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents

**Key, directly-quotable guidance for encoding business workflows into tools:**
- **Don't wrap every API endpoint.** "A common error we've observed is tools that merely wrap existing
  software functionality or API endpoints." Build **a few high-impact tools that correspond to
  workflows the agent will often need.**
- **Name tools after the business action / human task subdivision**, and **consolidate multiple API
  calls under one tool**: e.g., a single `schedule_event` (finds availability *and* books) instead of
  `list_users` + `list_events` + `create_event`; `search_contacts` over `list_contacts`.
  → This is exactly how a homegrown-CMS team would expose `publish_article`, `request_review`,
  `assign_editor` rather than raw CRUD — the workflow *is* the tool surface.
- **Namespacing** by service/resource (`asana_search`, `asana_projects_search`, `jira_search`) to
  delineate boundaries among many tools.
- **Return high-signal, semantic context**; resolve UUIDs to human-meaningful names; offer a
  `response_format` ("concise"/"detailed").
- *Note:* this specific article does **not** give explicit approval / human-in-the-loop tool design;
  that guidance shows up in Block's annotation approach (§1) and Sanity/Contentful gating (§4–5).

---

## 4. Notion — official hosted MCP server (Notion-as-CMS for agents)

**What it is.** Notion's **hosted/official MCP server** exposes a Notion workspace to agents (Claude
Code, Cursor, ChatGPT, etc.).
- Inside-look (primary): https://www.notion.com/blog/notions-hosted-mcp-server-an-inside-look
- Docs (primary): https://developers.notion.com/guides/mcp/overview
- Repo (primary): https://github.com/makenotion/notion-mcp-server (open-source predecessor; ~22 tools)

**Integration pattern.** Two tool classes: (1) **AI-first tools** built specifically for agents —
`create-pages`, `update-page`, and a semantic `search` (spans Notion + connected third-party apps);
(2) **wrapped v1 endpoints** with AI-friendly descriptions (e.g., `create-comment`). Open-source repo
tool names include `query-data-source`, `retrieve-a-data-source`, `update-a-data-source`,
`create-a-data-source`, `retrieve-page-markdown`, `update-page-markdown`, `move-page`.

**Content representation (key design choice):** **Notion-flavored Markdown** instead of nested block
JSON — "efficient content density per LLM token, requiring fewer tool interactions and less cost."
This is how Notion makes its *content model* legible to an agent.

**How business-flow knowledge is encoded:** Primarily via the **schema/data-source model**
(`retrieve-a-data-source` exposes document types, properties, validation) + **OAuth scoping** — the
integration gets "the permissions they have normally in the app," and MCP scope is deliberately
narrower than the API (e.g., can't delete databases). **No native approval-state / review-gating
workflow is documented** in the MCP server itself — teams using Notion-as-CMS inherit Notion's own
permission model rather than a publish-gate tool. (Gap flagged below.)

---

## 5. Sanity & Contentful — vendor agent tooling customers build on (workflow + approval gating)

**Sanity "Content Agent" / "Content Context" (primary):**
- https://www.sanity.io/content-agent ; https://www.sanity.io/context
- **Schema-aware operations:** understands document types, required fields, validation; enforces
  required fields, references, and data types.
- **Approval / staged review (human-in-the-loop):** "All edits are staged as **proposed changes**.
  Review in one place, adjust what to include, then **release together**" — gated via **Content
  Releases**. For "critical operations like publishing or deleting, **human approval can be required**,
  and agents can **create drafts for review**."
- **Workflow + auditability:** agents can "trigger and move through review/publish workflows" with
  "full auditability of agent actions"; operates over Slack and APIs while keeping governance rules.
- This is the clearest vendor example of **approval states + review gating exposed to an agent.**

**Contentful MCP (primary-ish vendor blog):**
- https://www.contentful.com/blog/model-context-protocol-introduction/
- Use cases: "Intelligent Content Workflow Automation," AI-assisted content creation, and integration
  with LangChain/LangGraph agent frameworks. Workflow automation streamlines content approval/publishing.
  (More marketing-flavored than Sanity's; verify specific gating claims against Contentful docs.)

**Encoding pattern:** business-flow knowledge = **schema validation + workflow states (draft →
proposed change → release/publish) + required-human-approval flags**, exposed as the agent's allowable
operations. A customer building on these inherits the gating rather than hand-rolling it.

---

## 6. Shopify — commerce-content via MCP + Sidekick (workflow-as-tool, push notifications)

**Primary sources:** https://shopify.dev/docs/apps/build/storefront-mcp ;
https://shopify.dev/docs/apps/build/storefront-mcp/servers/storefront ;
https://shopify.dev/docs/agents/catalog/storefront-catalog

**What it is.** Shopify's **AI Toolkit** (Winter '26): a **Dev MCP** server (for coding agents),
four **UCP-compliant MCP servers** (Storefront, Catalog, Customer Accounts, Dev) for shopping agents,
plus the **Universal Commerce Protocol** spec. **Sidekick** is Shopify's built-in merchant agent.

**How business-flow knowledge is encoded:**
- **Sidekick uses the Dev MCP** to inspect theme code, find perf bottlenecks, and **suggest/author
  Shopify Flow automations** — i.e., the agent operates on the merchant's *workflow engine* (Flow),
  which is where business rules live.
- Documented agentic workflow example: Sidekick "automatically pause[s] marketing campaigns and
  notif[ies] waitlisted customers when an item is gone, offering a contextually relevant alternative"
  — a business workflow (waitlist + substitution) driven through MCP tools.
- **Push-notification tool (MCP standard):** Storefront MCP pushes real-time inventory updates to
  external buying agents instead of polling — event-driven workflow encoding.
- *Caveat:* the granular Sidekick examples come partly from secondary roundups (weaverse, revize,
  presta); the MCP server structure and UCP/Flow integration are documented on shopify.dev.

---

## 7. News / media organizations (verifiable primary facts only)

These predate the "agent + MCP" era and are **template/NLG automation**, not LLM agents — included
because the task asked, but clearly distinguished.

- **Washington Post "Heliograf"** (primary-ish, Poynter/Digiday reporting + WaPo statements): a
  **template-based NLG system**, not an agent. Pulled real-time data (incl. AP feeds) to auto-generate
  Olympics and 2016 election/governor-race updates; ~850 articles in its first year. Director Jeremy
  Gilbert framed it as augmenting, not replacing, reporters.
  https://www.poynter.org/.../the-washington-post-will-use-automation-to-help-cover-the-election/435297/ ;
  https://digiday.com/media/washington-posts-robot-reporter-published-500-articles-last-year/
- **Associated Press + Automated Insights "Wordsmith"** (since 2012): NLG for earnings and sports;
  AP reports freeing ~20% of reporters' time and lower error rates at >10x volume.
- **Bloomberg "Cyborg":** assists reporters on quarterly earnings; up to ~1/3 of stories use some
  automation.

**Encoding pattern (historical):** business/editorial rules were encoded as **NLG templates + data
triggers**, with **human editorial review** before/around publication — conceptually the ancestor of
today's "workflow-as-tool + approval gate." **No verified primary source** found for these orgs using
MCP/agent-skill-based content systems as of mid-2026 (gap flagged).

---

## Synthesis — how business-flow knowledge gets encoded for agents

Across verified examples, four recurring encoding mechanisms emerge:

1. **Custom MCP servers named after business actions, not raw CRUD.** Block authors in-house servers
   per system; Anthropic's tool-design guidance explicitly says to build *workflow-shaped* tools
   (`schedule_event`, `publish_article`) that consolidate multiple API calls — the workflow becomes the
   tool surface. Notion ships AI-first `create-pages`/`update-page` rather than exposing raw block JSON.

2. **Skills (SKILL.md) as encoded editorial rulebooks.** Anthropic's brand-guidelines/document skills
   show business rules (brand, formatting, ordering, "when to use") packaged as text + scripts, surfaced
   via progressive disclosure. This is the most portable way to capture *editorial* (not just data) rules.

3. **Workflow states + approval gating as first-class tool/operation concepts.** Sanity stages edits as
   **proposed changes / releases** and can **require human approval** for publish/delete; Block annotates
   tools **read-only vs destructive** to force confirmation. The approval workflow is represented either
   as content states (draft → proposed → release) or as tool-level destructive flags.

4. **Schema + permission scoping as guardrails.** Schema-aware operations (Sanity, Notion data-sources)
   constrain agents to valid document types/fields; OAuth/scope (Notion) and LLM allowlists / output
   restrictions (Block) bound what the agent may touch. Content representation choices (Notion-flavored
   Markdown) make the content model legible and token-cheap.

**Net:** a company encodes its editorial/business flow for an agent by (a) shaping tools to its real
workflow verbs, (b) packaging rules as skills, (c) modeling approval as states or destructive-tool
gates with a human in the loop, and (d) fencing the agent with schema + permission scope.

---

## Unverified / gaps

- **No published, named primary source** found of a company describing wrapping a *homegrown/internal*
  CMS specifically with an MCP server *and* detailing its approval-workflow representation. Block is the
  closest (internal engineer-authored servers, read-only/destructive gating) but does not name a CMS
  server or show its publish-gate. The "internal homegrown systems wrapped with MCP" claim appears only
  in secondary roundups (mcpbundles, guptadeepak, decoupled.io) without a company case study.
- **Block's "60+ MCP servers / 12,000 employees / 50–75% time saved"** numbers are self-reported or from
  secondary aggregators — not independently verified.
- **Notion MCP** has **no documented native approval/review-gating tool**; teams rely on Notion's own
  permission model. Whether teams build approval workflows *on top* is undocumented in primary sources.
- **Contentful MCP** workflow-approval claims are vendor-marketing-flavored; the specific gating
  mechanism wasn't confirmed against Contentful product docs in this pass.
- **Canva agent skill** seen only in third-party marketplaces (lobehub, awesomeskill); not confirmed as
  Canva-authored/official.
- **Shopify Sidekick** granular workflow examples (campaign-pause/waitlist-substitution) partly from
  secondary blogs; the MCP/UCP/Flow architecture is documented on shopify.dev.
- **News orgs (WaPo/AP/Bloomberg):** Heliograf/Wordsmith/Cyborg are **template NLG, not LLM agents**;
  no verified primary source ties them to MCP/agent-skill content systems as of mid-2026.
- Did not locate a Box-authored content/CMS agent-skill primary example (only generic doc skills).
