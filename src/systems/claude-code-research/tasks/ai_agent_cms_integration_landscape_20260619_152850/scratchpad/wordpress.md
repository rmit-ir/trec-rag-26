# WordPress AI-Agent Integration Landscape

Research date: 2026-06-19. Sub-agent strand: WordPress (largest CMS ecosystem).

## TL;DR / big picture

The WordPress agent stack went through a major **consolidation in late 2025 / early 2026**. Automattic incubated two libraries — the **Feature API** (`Automattic/wp-feature-api`) and the **WordPress MCP plugin** (`Automattic/wordpress-mcp`) — then donated/migrated both into the official **WordPress** GitHub org:

- Feature API → **WordPress Abilities API** (`WordPress/abilities-api`), landed in **WordPress 6.9 core (Nov 2025)**, with a client-side JS counterpart in **WordPress 7.0 (2026)**.
- `Automattic/wordpress-mcp` plugin → **`WordPress/mcp-adapter`** (a library, not a standalone plugin), which converts Abilities into MCP tools/resources/prompts.

So the modern architecture is layered:
**WordPress REST API + Application Passwords** (the universal backbone) → **Abilities API** (core registry of capabilities) → **mcp-adapter** (exposes abilities as MCP) → MCP clients (Claude, etc.), often via a **local proxy** (`@automattic/mcp-wordpress-remote`) because most MCP clients still speak stdio.

The extension point for everything is the **Abilities API**: plugins register abilities, and those abilities automatically become MCP tools.

---

## 1. WordPress Abilities API (the foundation)

- **What:** Standardized registry of "abilities" — discrete units of functionality with machine-readable input/output schemas, permissions, and metadata. Designed so developers, automation, and AI agents can discover and invoke WP capabilities. Source: [Abilities API — Common APIs Handbook](https://developer.wordpress.org/apis/abilities-api/), [Introducing the WordPress Abilities API (Developer Blog, Nov 2025)](https://developer.wordpress.org/news/2025/11/introducing-the-wordpress-abilities-api/).
- **Where it lives:** Official repo **`WordPress/abilities-api`** (the former `Automattic/wp-feature-api` is deprecated and redirects here). Open source, **GPL-2.0-or-later**.
- **Shipped in core:** **WordPress 6.9** (server-side PHP API). Source: [Abilities API in WordPress 6.9 — Make WordPress Core (2025-11-10)](https://make.wordpress.org/core/2025/11/10/abilities-api-in-wordpress-6-9/).
- **Client-side (JS) API:** **WordPress 7.0 (2026)** — JS counterpart for client-side abilities like navigating or inserting blocks. Source: [Client-Side Abilities API in WordPress 7.0 — Make WordPress Core (2026-03-24)](https://make.wordpress.org/core/2026/03/24/client-side-abilities-api-in-wordpress-7-0/).

### How abilities are defined (PRIMARY)
`wp_register_ability( string $name, array $args )`, called on the **`wp_abilities_api_init`** action hook. Name format: **`namespace/ability-name`** (namespace = plugin/component slug). Args array keys:
- `label` — human-readable name
- `description` — what it does
- `category` — category grouping
- `input_schema` — JSON Schema for inputs
- `output_schema` — JSON Schema for output
- `execute_callback` — PHP callable that runs the ability
- `permission_callback` — optional, determines user access
- `meta` — extra metadata (e.g. `show_in_rest`, and for MCP: `mcp.public`)

Returns `WP_Ability` on success, `null` on failure. Example ability in docs: `my-plugin/site-info` (returns site name, URL, active theme, plugins, PHP/WP version; gated by `manage_options`). Source: [Abilities API handbook](https://developer.wordpress.org/apis/abilities-api/).

---

## 2. WordPress/mcp-adapter (Abilities → MCP)

- **What:** "An MCP adapter that bridges the Abilities API to the Model Context Protocol, enabling MCP clients to discover and invoke WordPress plugin, theme, and core abilities programmatically." A **library** plugins/sites embed, not a standalone end-user plugin. Source: [WordPress/mcp-adapter (GitHub)](https://github.com/WordPress/mcp-adapter).
- **Maintainer:** WordPress org (migrated from `Automattic/wordpress-mcp`). **License GPL-2.0-or-later.** Version **v0.5.0 (2026-04-15)** at time of research.
- **What it does:** "Automatically converts WordPress abilities into MCP tools, resources, and prompts."
- **Transports:**
  - **STDIO** — process-based stdin/stdout, for local dev / CLI.
  - **HTTP** — unified transport implementing the **MCP 2025-11-25 spec** (streamable HTTP).
  - Custom transports via `McpTransportInterface`.
- **Auth/permissions:** Relies on WordPress authentication by default; granular per-ability permission checks; configurable per-transport permissions; custom permission callbacks supported.
- **Ability → MCP tool mapping:** Two modes:
  1. **Default discovery server** — abilities flagged `meta.mcp.public = true` are exposed through three meta-tools: `mcp-adapter/discover-abilities`, `mcp-adapter/get-ability-info`, `mcp-adapter/execute-ability` (the agent discovers then executes, rather than every ability being a direct tool).
  2. **Explicit server** — `create_server()` registers a server with chosen abilities as **direct MCP tools** (no public flag needed). Params: server ID, namespace, route, name, description, version, transports, error handler, observability handler, ability lists.
- Source: [WordPress/mcp-adapter](https://github.com/WordPress/mcp-adapter), [How to Create an MCP Server in WordPress with the Abilities API and MCP Adapter — WS Form](https://wsform.com/how-to-create-an-mcp-server-in-wordpress-with-the-abilities-api-and-mcp-adapter/).

---

## 3. Automattic/wordpress-mcp plugin (DEPRECATED, but widely deployed)

- **Status:** **Archived 2026-01-19**, deprecated in favor of `WordPress/mcp-adapter`. Still the thing most "WordPress MCP" tutorials from 2025 describe and many sites run. Source: [Automattic/wordpress-mcp (GitHub, archived)](https://github.com/Automattic/wordpress-mcp).
- **Version:** 0.2.5 (2025-07-24). **License GPL-2.0-or-later.**
- **Transports:** STDIO at `/wp/v2/wpmcp`; Streamable HTTP at `/wp/v2/wpmcp/streamable` (JSON-RPC 2.0).
- **Auth:** **JWT** (1–24h expiry, managed in a React admin UI) OR **Application Passwords**.
- **Standard MCP methods:** `initialize`, `tools/list`, `tools/call`, `resources/list`, `resources/read`, `prompts/list`, `prompts/get`.
- **Experimental generic REST CRUD tools:**
  - `list_api_functions` — discover WP REST API endpoints
  - `get_function_details` — endpoint metadata + params
  - `run_api_function` — execute CRUD on REST endpoints
- **Custom tools:** registered via `wp_mcp_register_tools` action hook, callback-based with inputSchema validation. Built-in tools register on the `wordpress_mcp_init` action.
- Tool definition files confirmed at `includes/Tools/`: `McpMediaTools`, `McpPostsTools`, `McpPagesTools`, `McpCustomPostTypesTools`, `McpUsersTools`, `McpSettingsTools`, `McpSiteInfo`, `McpRestApiCrud`, `McpWooProducts`, `McpWooOrders`. Source (read via GitHub API, archived `trunk`): [Automattic/wordpress-mcp/includes/Tools](https://github.com/Automattic/wordpress-mcp/tree/trunk/includes/Tools).

### FULL TOOL INVENTORY (PRIMARY — read from PHP tool-definition files, archived plugin v0.2.5)

Each tool maps to a WP REST route + HTTP method (`type` = read/create/update/delete drives permission gating).

**Posts** (`McpPostsTools.php`): `wp_posts_search` (GET /wp/v2/posts), `wp_get_post` (GET …/posts/{id}), `wp_add_post` (POST; content must be "valid Guttenberg block format"), `wp_update_post` (PUT), `wp_delete_post` (DELETE), `wp_list_categories`, `wp_add_category`, `wp_update_category`, `wp_delete_category`, `wp_list_tags`, `wp_add_tag`, `wp_update_tag`, `wp_delete_tag`.

**Pages** (`McpPagesTools.php`): `wp_pages_search`, `wp_get_page`, `wp_add_page` (params include parent page ID, menu order), `wp_update_page`, `wp_delete_page`.

**Custom post types** (`McpCustomPostTypesTools.php`): `wp_list_post_types`, `wp_cpt_search`, `wp_get_cpt`, `wp_add_cpt`, `wp_update_cpt`, `wp_delete_cpt` (all take a `post_type` arg + status/author filters).

**Media** (`McpMediaTools.php`) — **media upload IS supported** (contradicts the common "MCP can't upload images" claim for this plugin):
- `wp_list_media` (GET /wp/v2/media)
- `wp_get_media` (GET …/media/{id})
- `wp_get_media_file` — get actual file blob; param `size` (thumbnail/medium/large/full)
- **`wp_upload_media`** (POST /wp/v2/media, type=create) — **uploads a new media file**. Params: `file` (string, **base64-encoded**, required — a `wp_upload_media_pre_callback` strips any `data:*;base64,` URI prefix, base64-decodes, and sniffs MIME via `finfo`), `title`, `caption`, `description`, `alt_text`.
- `wp_update_media` (POST …/media/{id}) — update title/caption/description/alt_text
- `wp_delete_media` (DELETE, requires force=true)
- `wp_search_media` (search by title/caption/description, `media_type` filter)

**Users** (`McpUsersTools.php`): `wp_users_search`, `wp_get_user`, `wp_add_user`, `wp_update_user`, `wp_delete_user`, `wp_get_current_user`, `wp_update_current_user`.

**Settings** (`McpSettingsTools.php`): `wp_get_general_settings`, `wp_update_general_settings` (title, tagline, timezone, date/time format, posts-per-page, default category/format, comment/ping status, language, etc.).

**Site info** (`McpSiteInfo.php`): `get_site_info`.

**Generic REST CRUD** (`McpRestApiCrud.php`, experimental): `list_api_functions`, `get_function_details`, `run_api_function`.

**WooCommerce products** (`McpWooProducts.php`): `wc_products_search`, `wc_get_product`, `wc_add_product`, `wc_update_product`, `wc_delete_product`, `wc_list_product_categories`, `wc_add_product_category`, `wc_update_product_category`, `wc_delete_product_category`, `wc_list_product_tags`, `wc_add_product_tag`, `wc_update_product_tag`, `wc_delete_product_tag` (all → `/wc/v3/products...`).

**WooCommerce orders/reports** (`McpWooOrders.php`) — **READ-ONLY in this plugin**: `wc_orders_search` (GET /wc/v3/orders), `wc_reports_coupons_totals`, `wc_reports_customers_totals`, `wc_reports_orders_totals`, `wc_reports_products_totals`, `wc_reports_reviews_totals`, `wc_reports_sales`. NOTE: there is **no create/update order tool** here — marketing copy claiming "creating and managing orders" describes the newer native WooCommerce MCP / abilities, not this plugin's order tools.

---

## 4. WooCommerce MCP / Agentic Commerce

- **What:** WooCommerce has **native MCP support**, built **on top of Automattic's WordPress MCP / the Abilities system**. Source: [MCP Integration — WooCommerce developer docs](https://developer.woocommerce.com/docs/features/mcp/), [WooCommerce MCP (woocommerce.com)](https://woocommerce.com/posts/woocommerce-mcp/).
- **Architecture:** local proxy approach — MCP client (Claude Code) ↔ stdio/JSON-RPC ↔ local proxy **`@automattic/mcp-wordpress-remote`** ↔ HTTP ↔ WordPress MCP server, processed through the **WordPress Abilities system**.
- **Coverage (initial version):** product management (search/add/update products in catalog) and order management (create/manage orders). Some surfaces are read-only (catalog, categories, reviews, content). Source: [WooCommerce MCP post](https://woocommerce.com/posts/woocommerce-mcp/), [AI & Agentic Commerce in WooCommerce Roadmap (2025-10-03)](https://developer.woocommerce.com/2025/10/03/ai-agentic-commerce-in-woocommerce/).
- TO VERIFY: exact WooCommerce ability/tool names.

## 5. Native AI features

- **Jetpack AI Assistant:** content-generation AI inside the Gutenberg block editor (blog posts, titles, summaries, lists, tables, tone, spelling/grammar, translation across ~12 languages). Uses OpenAI API (GPT-3.5 Turbo as of early 2025, subject to change). Free Jetpack plugin + Jetpack AI add-on ($10/mo). NOT an MCP server — it's a built-in AI feature. Source: [Jetpack AI](https://jetpack.com/ai/), [Introducing Jetpack AI Assistant](https://jetpack.com/resources/introducing-jetpack-ai-assistant/).
- **WordPress.com "Big Sky":** AI site builder (chat-style) that generates logos, designs, typography, color schemes, content, and operates inside the real block editor. Launched early access April 2025 (free, first 30 prompts free; hosting plan to publish). Built on **`@automattic/big-sky-agents`** (npm/`Automattic/big-sky-agents`), a front-end library for AI-enhanced apps using Gutenberg UI components + WordPress.com APIs/auth. Source: [AI Site Builder — Matt Mullenweg](https://ma.tt/2025/04/ai-site-builder/), [@automattic/big-sky-agents (npm)](https://www.npmjs.com/package/@automattic/big-sky-agents), [Big Sky — Matías Ventura](https://matiasventura.com/post/big-sky/).

## 6. Community / other

- **emzimmer/server-wp-mcp** — community Node MCP server; multi-site, dynamic REST endpoint discovery (auto-maps endpoints per site), GET/POST/PUT/DELETE/PATCH, Application Passwords, JSON config (`wp-sites.json`). Source: [emzimmer/server-wp-mcp (GitHub)](https://github.com/emzimmer/server-wp-mcp).
- **WordPress.org MCP Server** — official MCP server for the wordpress.org plugin/theme directory (not a per-site server). Source: [Using the WordPress.org MCP Server — Plugin Handbook](https://developer.wordpress.org/plugins/wordpress-org/using-the-mcp-server/).
- **NavidArd/wordpress-mcp** — community "turn your site into an MCP server, build themes/plugins by chatting".

---

## 7. The REST API + Application Passwords backbone

- The **WordPress REST API** (`/wp-json/wp/v2/...`) is the universal agent backbone underneath all of the above — every wordpress-mcp tool is a thin wrapper over a REST route (e.g. media → `/wp/v2/media`, posts → `/wp/v2/posts`, Woo → `/wc/v3/...`).
- **Application Passwords** (core since WP 5.6, requires HTTPS) are the standard credential: a per-application token used over HTTP Basic auth, revocable independently of the main password, with capability-based authorization. This is what most community MCP servers and the remote proxy use. Source: [Creating WordPress Application Passwords for MCP — LearnDash](https://learndash.com/support/kb/learndash-mcp-server/getting-started-with-learndash-mcp-server/creating-wordpress-application-passwords-for-mcp/), [What is WordPress MCP Server — InstaWP](https://instawp.com/wordpress-mcp/).

## 8. WP-CLI as a transport

- The official **mcp-adapter** exposes **stdio transport via WP-CLI** (and streamable HTTP via the REST API). So an agent can drive WordPress over the command line as well as over HTTP. Source: [MCP Adapter — WordPress AI (2025-07-17, Pascal Birchler)](https://make.wordpress.org/ai/2025/07/17/mcp-adapter/).

## 9. @automattic/mcp-wordpress-remote (local proxy)

- npm package; runs locally, presents an MCP (stdio) server to the client and calls the WordPress site over HTTP/REST. Bridges stdio-only MCP clients to an HTTP WordPress MCP endpoint.
- **Auth supported:** OAuth 2.1 (recommended; PKCE + dynamic client registration, MCP auth-spec compliant), JWT tokens, and Application Passwords.
- **Env vars:** `WP_API_URL` (required), `OAUTH_ENABLED` (default true), `JWT_TOKEN`, `WP_API_USERNAME`/`WP_API_PASSWORD` (app password), `OAUTH_CALLBACK_PORT` (default 7665), `LOG_LEVEL` (0-3), `CUSTOM_HEADERS`. Adds WooCommerce-specific tools when configured.
- Source: [Automattic/mcp-wordpress-remote (GitHub)](https://github.com/Automattic/mcp-wordpress-remote), [webaistack setup guide](https://webaistack.com/automattic-mcp-wordpress-remote/).

---

## Integration-pattern categories (emergent)

1. **Core capability registry** — Abilities API (WP 6.9/7.0). The extension point; plugins register abilities.
2. **Protocol adapter (library)** — mcp-adapter: abilities → MCP tools/resources/prompts.
3. **Standalone MCP plugin** — Automattic/wordpress-mcp (deprecated) — ships its own fixed tool set.
4. **Local stdio↔HTTP proxy** — @automattic/mcp-wordpress-remote (+ community emzimmer/server-wp-mcp).
5. **REST API + Application Passwords** — the raw backbone any agent can use directly.
6. **WP-CLI** — stdio transport / scripted agent control.
7. **Vertical MCP** — WooCommerce MCP (commerce), LearnDash MCP (LMS), etc.
8. **Native in-product AI** — Jetpack AI Assistant (editor content gen), WordPress.com Big Sky (agentic site builder); not agent-connectable MCP servers but first-party AI.
9. **Directory MCP** — WordPress.org MCP server for the plugin/theme repository.

---

## Unverified / gaps
- **mcp-adapter transport naming:** sources variously say "STDIO + HTTP (MCP 2025-11-25 spec)" vs "Streamable HTTP via REST + stdio via WP-CLI." Both describe the same two-transport model; exact class names in current v0.5.0 not individually verified here.
- **Native WooCommerce MCP order-creation tools:** the WooCommerce roadmap/posts claim product AND order create/manage; the *deprecated* Automattic plugin's order tools are read-only. The exact ability names of the *new* native WooCommerce MCP (built on Abilities) were not pulled from primary source — only described in vendor blog posts.
- **Abilities → MCP `meta` flag exact key:** docs/secondary sources use `meta.mcp.public`; not confirmed verbatim against the abilities-api source schema.
- **Jetpack AI model** (GPT-3.5 Turbo "as of early 2025") is from a secondary roundup and Automattic notes it may change; not a current primary confirmation.
- **mcp-adapter v0.5.0 date (2026-04-15)** came from a WebFetch summary of the GitHub releases page, not independently cross-checked.
- Did not enumerate `wp_add_post`/`wp_add_user`/etc. full required-vs-optional parameter lists for every tool (only media `wp_upload_media` was fully parsed); the REST route + method is captured for all.
