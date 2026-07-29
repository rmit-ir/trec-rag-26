# 2026-07-28 — proper test harness for `src/` (systems + shared layers)

Branch `feat/systems-test-harness`. Rebased onto `origin/main` (`4a2a29d`,
"feat: search backends comparison") before starting — that commit touches only
`tasks/task-comparison/`, so no overlap with `src/` or the harness.

## Problem

The repo had test *assets* but no test *harness*. Five systems under
`src/systems/`, and:

| system | test before | how it ran |
| --- | --- | --- |
| `facet_rag` | `test_mock.py` (194 L) | `python …/test_mock.py`, `__main__` script |
| `ali_deepresearch` | `test_mock.py` (197 L) | ditto |
| `aus_agent` | `test_context.py` (1408 L) | `unittest`, never collected |
| `o3_deep_research` | — | none |
| `claude-code-research` | — | none |
| shared `utils`/`tools`/`ragrun` | — | none |
| `src/mcp` server | `test_smoke.py` (101 L) | `__main__` script, real endpoints + creds |

Consequences: `pytest` wasn't a dependency anywhere, nothing was collectable, so
CI could not run tests at all; each suite had a different invocation; and — worst
— **both `test_mock.py` files hit the real ClimbMix endpoints**, so with no
`SEARCH_API_KEY` they printed `SKIPPED` and exited 0. A green run proved nothing.

## Design decisions

**Tests live under `tests/`, not beside the code.** Nothing under `src/` is a
test file any more. pytest owns discovery (`testpaths = ["tests"]`). Four files
were retired once their coverage had a home under `tests/`:

| deleted | why it was safe |
| --- | --- |
| `src/systems/facet_rag/test_mock.py` | every assertion diffed against `tests/systems/test_facet_rag.py` before deleting |
| `src/systems/ali_deepresearch/test_mock.py` | ditto, vs `tests/systems/test_ali_deepresearch.py` |
| `src/systems/aus_agent/test_context.py` | migrated to `tests/aus_agent_context/` (see below) |
| `src/mcp/test_smoke.py` | `tests/shared/test_mcp_server.py::test_smoke_end_to_end_against_the_real_backends` boots the same server as a real subprocess (`subprocess.Popen`) and drives it with the official MCP client over streamable-HTTP — the same flow, now collected and marked `live` |

The `src/mcp/test_smoke.py` deletion is worth spelling out because the obvious
objection is wrong: the script was the *documented* operator smoke tool, so the
question was whether pytest could replace a real subprocess boot. It can, and
does — the entry point is now `bash scripts/test.sh live` instead of
`python src/mcp/test_smoke.py`. Keeping both would have meant two copies of one
flow, drifting.

**`pythonpath = ["src", "src/systems", "tests"]`** — `src/systems` and not just
`src`, because the system packages import each other *flat*
(`from aus_agent.providers…`, `from ali_deepresearch.answer_format…`), matching
the import-surgery header every `run.py` carries. This replaces that surgery in
tests rather than duplicating it. `--import-mode=importlib` lets same-named test
modules coexist across directories without `__init__.py` files.

**Three tiers of network access**, because "mock everything" and "hit the real
thing" is a false binary:

| tier | marker | network | creds | in CI |
| --- | --- | --- | --- | --- |
| offline | *(none)* | none — blocked | none | yes |
| dummy API | `local_socket` | loopback only | none | yes |
| live | `live` | hosted endpoints | required | no (deselected) |

`addopts` carries `-m 'not live'`, so bare `pytest` is hermetic; `pytest -m live`
opts in; `-m 'live or not live'` runs everything.

**Hermeticism is enforced, not trusted.** Three autouse fixtures in
`tests/conftest.py`:

- `no_network` — patches `urllib.request.urlopen` *and*
  `socket.create_connection` (clients use urllib; a model SDK would use socket
  directly). Failure names the URL that was attempted.
- `isolated_data_dir` — repoints `RAGRUN_DATA_DIR` at a tmp dir. `save_run`
  writes into `data/outputs/<system>/`, and the outputs viewer polls those
  files; a test run must not litter or race them. `ragrun.outputs.data_dir()`
  reads the env var on every call, so setting it is sufficient — no patching.
- `no_ambient_creds` — strips `SEARCH_API_KEY`, `PYSERINI_API_TOKEN`,
  `OPENAI_API_KEY`, `AWS_*`. `utils.env` auto-loads the repo `.env` at import,
  so without this an "offline" test can pass on a dev box *only because it
  silently authenticated* — and then fail in CI. This makes local and CI
  behaviour identical.

## The dummy API server (`tests/dummy_api/`)

The `stub_search_tool` fixture patches `tools.search_tool._DISPATCH`, which
proves the tool layer but **skips the retrieval clients entirely** — URL
construction, auth headers, HTTP verb, request-body shape, and
response→`SearchHit` mapping all go untested. Those are exactly the parts with a
production failure history (the hosted proxy 403s the stock
`Python-urllib/x.y` UA; the five endpoints disagree on verb and payload shape).

So `dummy_server.py` is a real stdlib `HTTPServer` on `127.0.0.1:0` (OS-assigned
port, so parallel tests never collide) that speaks each backend's **documented
wire format**:

| endpoint | flavor | response envelope |
| --- | --- | --- |
| `POST /search` | dense (Jina-v5 DiskANN) | `{"hits": [...]}` |
| `POST /api/search` | sparse (Anserini BM25) | `{"hits": {"hits": [...]}}` (ES-style) |
| `POST /search` | ssr (Cottontail GCL) | `{"results": [...]}` |
| `GET /v1/<index>/search` | pyserini hosted | `{"candidates": [...]}` |
| `GET /v1/<index>/doc/<docid>` | doc fetch | `{"docid", "doc"}` |

Dense and SSR share `POST /search`, so a server is constructed with a `flavor`
and answers only as that backend; tests that need both spin up two servers.

Tests point the clients' env vars at `api.base_url` and **patch nothing else** —
the client code runs byte-for-byte as against the hosted service, over a real
socket. The server records every request (verb, path, headers, body, params), so
the *request* side is asserted too: a client that sends the wrong verb, field
name, or header fails here instead of in production.

Cases covered (`test_dummy_api.py`, 15 tests, all passing):
response mapping per engine; SSR's synthesized `1/rank` score; `doc` as string
*and* as object (the spec allows both); docid URL-quoting; the `User-Agent`
override; Basic auth (`SEARCH_API_KEY` → `Basic dXNlcjpwYXNz`) vs Bearer
(`PYSERINI_API_TOKEN`); a 401 raising `HTTPError` from the client but arriving at
the agent as an `{"error": …}` envelope; `max_chars` truncation of
over-the-wire text; and a **full `facet_rag` pipeline** — dummy search over HTTP
+ scripted LLM → spec-clean TREC artifacts, asserting each engine was reached
over its own socket.

`tests/dummy_api/conftest.py` shadows `no_network` for this package: it permits
loopback but **still blocks non-loopback**, so a client with a hardcoded hosted
URL fails rather than quietly reaching the internet from CI. Verified by probe:
calling `search_dense` with the default hosted URL under `local_socket` raises
`NON-loopback`. These tests are deliberately *not* marked `live` — `live` means
"needs credentials", and these need none.

## Shared fixtures (`tests/conftest.py`)

- `stub_search_tool` — patches the engine dispatch table, not `run_search_tool`,
  so real serialization / truncation / error-envelope logic stays under test.
  Returns a `calls` dict for asserting engine routing and query text.
- `scripted_provider` (`ScriptedProvider`) — the full
  `aus_agent.providers.base.Provider` contract, incl. `compact_tool_results`.
  Two modes: a list of `ModelTurn`s replayed in order, or a
  `responder(pending_text, turn_index)` callable for stage-dependent turns
  (facet_rag distinguishes plan/synthesize/format by prompt content). Records
  `system_prompt`, `tools`, `user_messages`, `tool_results`, `compactions`,
  `raw_messages`. Raises when exhausted — catches a system running more turns
  than expected instead of silently reusing the last one.
- `fake_hits` / `fake_search_response` — canonical ClimbMix payloads. `fake_hits`
  builds through the real `make_hit`, so `kind`/`docid` derivation is the code
  under test, not a copy of it.
- `read_artifacts(paths)` → `{trajectory, output, violations}` with `violations`
  defaulting to `[]`, so a test asserts `== []` rather than probing for a
  missing file.
- `model_turn(...)` / `tool_call(...)` module-level builders.

Two weaknesses in these shared fakes surfaced while migrating the ContextLedger
suite (below). One was fixed in the shared fixture, one deliberately left local:

- **Fixed: `ScriptedProvider.compact_tool_results` was lenient.** It silently
  ignored a tool-use id that was not in history, where the real
  `BedrockProvider` (`providers/bedrock.py:237`) raises `KeyError` and
  `run_agent` treats that as fatal. A lenient mock lets a harness that compacts
  the wrong batch pass here and die against the real backend — so the shared
  mock now raises too, with the same message shape. The local
  `StrictScriptedProvider` that had been compensating shrank to just its
  read-side `content_by_id` helper. The full suite stayed green through the
  change, so nothing was depending on the leniency.
- **Left local: `stub_search_tool` returns the same 4 docids for every query.**
  Most tests want that (stable ids to assert on), and rewriting it would touch
  every file whose assertions are written against `CLIMBMIX_DOCIDS` for no gain.
  The staged/committed protocol *does* need per-query result sets — "keep `b`
  from alpha and `d` from beta, compact the rest" is the whole behaviour — so
  `tests/aus_agent_context/conftest.py::fake_engine` provides three disjoint
  doc sets, and `stub_search_tool`'s docstring now points at it so the next
  author finds it instead of reinventing it.

## Migrating the ContextLedger suite (`tests/aus_agent_context/`)

`src/systems/aus_agent/test_context.py` was 1408 lines of `unittest` that pytest
never collected — 45 tests that passed when run by hand and were invisible to CI.
Five of its behaviour clusters were covered by **nothing** anywhere under
`tests/`: cache-point placement, `atomic_write_text` (including the umask/0600
invariant), contentless-response retry, throttled partial saves, and token
accounting. So it could not simply be deleted like the two `test_mock.py`
scripts; it had to be migrated first.

It became 7 modules / 125 test functions / 134 cases. The growth is partly
splitting conflated tests into per-property ones, partly genuinely new coverage
(`test_commit_tool.py` — tool schema wording, `apply_commit` argument handling,
`expire_staged` semantics — did not exist in any form).

Verification before deleting the original: the migrated directory passes (134),
the full suite passes with no skips, **the original still passed on disk**
(`Ran 45 tests … OK`) so nothing was papered over, and each of the five
previously-uncovered clusters was confirmed present by name.

**One test was corrected rather than ported.** The original
`test_search_engine_argument_is_forwarded_only_when_supplied` patched
`run_search_tool` and asserted `search_engine` appears in the forwarded kwargs.
Patching one level deeper at `_DISPATCH` shows `run_search_tool` *consumes* that
kwarg for routing and never forwards it — the original assertion was an artifact
of its patch point, not a property of the code, and was unreachable from where
the replacement sits. The replacement asserts the actual three-level routing
fallback (`routed == ["keyword", "ssr", "semantic"]`), which is the behaviour the
original was protecting. So the migration is faithful in coverage but **not
literally 1:1**, and this is the one place that matters.

## Documentation standard

Every test function carries a docstring, and the bar is that **the docstring must
say something the test name does not**. A prose restatement of the name is worse
than nothing — it costs a reader three lines and tells them what they already
read. So each one states either *why the behaviour matters* or *what breaks if it
regresses*, e.g.:

- `test_climbmix_docid_pattern` — a docid that doesn't match `shard_<d>_<d>`
  can't be resolved against the corpus, so the row is unjudgeable: it scores as
  if never retrieved.
- `test_generation_span_is_rich_only` — the reference sample has no `generation`
  item type, so a leak produces a `trajectory.json` that serializes and validates
  fine but is no longer sample-compatible. Nothing else reads item `type`, so
  this assertion is the only detector.
- `test_bool_is_inferred_before_int` — `bool` subclasses `int`, so a flipped
  isinstance order returns `1` instead of `True`: truthy, hence invisible until
  something does `is True` or serializes it into an artifact.
- `test_empty_file_is_reported` — the failure a `[]`-means-valid validator cannot
  catch: a run that crashed before writing a row satisfies every per-row rule
  because there are no rows, and scores zero on every topic.

Enforced by an AST sweep (no docstring, or two stacked docstrings from a bad
merge), run over `tests/` until it reports nothing:

```bash
uv run --no-project python - <<'EOF'
import ast, pathlib
for p in sorted(pathlib.Path("tests").rglob("*.py")):
    for n in ast.walk(ast.parse(p.read_text())):
        if isinstance(n, ast.FunctionDef) and n.name.startswith("test"):
            strs = [i for i, st in enumerate(n.body)
                    if isinstance(st, ast.Expr)
                    and isinstance(st.value, ast.Constant)
                    and isinstance(st.value.value, str)]
            if not strs: print("MISSING", p, n.lineno, n.name)
            elif len(strs) > 1 or strs[0] != 0:
                print("DUPLICATE", p, n.lineno, n.name)
EOF
```

Module docstrings do the layer-level explaining (what this file defends and why
that property is fragile), so the per-test docstrings stay short.

## The runner (`scripts/test.sh`) — one entry point, two modes

Everything now goes through one script, because the two things that make a run
*mean* something (all three dep groups, and treating a skip as failure) were
being restated in three places and were easy to get wrong by hand:

```bash
bash scripts/test.sh                    # full suite (792 cases, ~7s)
bash scripts/test.sh contract           # shorthands: contract shared systems dummy-api aus-agent
bash scripts/test.sh tests/shared/test_fusion.py::test_rrf_fuse_orders_by_score
bash scripts/test.sh -k "rrf or fuse"   # anything pytest accepts passes through
bash scripts/test.sh live               # only the live tests (needs creds)
```

No args = full suite; any arg = selective. Unrecognised args are forwarded to
pytest verbatim, so the script never becomes a thing you have to work around.

**Why the full run is the recommended default, and how that's communicated.**
The five systems all sit on `src/utils/` (retrieval clients), `src/tools/`
(dispatch), and `src/ragrun/` (artifact writing), so a per-system or per-file run
cannot clear a change to any of those. It is also cheaper to run everything than
to reason about which tests an edit reached — 7 seconds. Rather than only
documenting that, a **selective run prints the recommendation on success**, naming
the four directories that mandate a full run:

```
Selected tests passed. Before committing — and after ANY change under
src/utils/, src/tools/, src/ragrun/ or src/systems/ — run the whole suite:

    bash scripts/test.sh
```

**The fail-on-skip gate moved into the script.** It greps the run for `N skipped`
and exits 1 with an explanation of what it means (a dep group didn't install, so
the `importorskip`-gated tests didn't run) and where to add the missing group.
Suppressed for `live`, where "no credentials configured" is a legitimate skip.
Verified by pointing the runner at a throwaway test that skips on an
uninstallable module — the gate fired and exited 1 — then deleting it.

**Bash trap worth recording: `GROUPS` is a built-in.** The first version held the
dep-group list in `GROUPS=(...)`; bash silently ignores assignments to it (it's
the caller's numeric group ids), so the command ran as
`uv run 1010 10000001 … pytest` → `error: Failed to spawn: '1010'`. Renamed
`DEP_GROUPS`, with a comment pointing at the same trap already documented in
`tasks/ssr_search/scripts/launch_fork_servers.sh:12`. The `GROUPS="…"` snippets I
had put in `AGENTS.md` and `SKILL.md` were broken for the same reason and are
fixed.

## Enforcement

- `scripts/test.sh` — dep groups + fail-on-skip, used by the two below so
  neither can drift from what a developer runs locally.
- `.github/workflows/tests.yml` — runs `bash scripts/test.sh` on every PR and
  push to `main`. No creds configured, which is the point.
- `scripts/git-hooks/pre-commit` — gained a test run gated on the commit
  touching `src/`, `tests/`, or `pyproject.toml`; also delegates to
  `scripts/test.sh`. Runs against the working tree (provisioning a venv in a
  `checkout-index` dir costs minutes and the working tree is what the developer
  just ran). Bypass: `SKIP_TEST_CHECK=1`. The existing arch-diagram check is
  unchanged and still bypasses independently via `SKIP_ARCH_VIZ_CHECK=1`.

## Scaffolder change

`skills/trec-rag-new-system/scripts/scaffold_system.py` emitted a
network-dependent `__main__` script at `src/systems/<name>/test_mock.py` — i.e.
it *reproduced* the problem for every new system. It now writes
`tests/systems/test_<name>.py`: a pytest module using `stub_search_tool` +
`read_artifacts`, with an offline artifact/validation test, an engine-routing
test, and a `@pytest.mark.live` counterpart. Verified by scaffolding a throwaway
`scaffold_probe` system — generated test collected as 2 offline + 1 deselected
`live` — then removing it.

`SKILL.md` gained a **Test Harness** section (commands, the three tiers, the
fixture table, marker discipline, where format conformance lives) and a fourth
non-automated requirement: fill in the generated test's scripted-provider TODO,
because an unfilled scaffold test proves nothing. `AGENTS.md` gained a
**Testing** section.

## What the harness found (asserted as-is, `src/` unchanged)

Writing the tests surfaced real defects. None are fixed here — each is pinned by a
test asserting the **current** behaviour with a `CURRENT BEHAVIOUR` comment, so
the suite is honest about what the code does and a fix will announce itself by
failing that test. Ordered by what I'd fix first:

1. **`src/utils/search_pyserini.py:64` — object `doc` is not unwrapped.**
   `text=c.get("doc")` copies the field verbatim, but the spec explicitly allows
   `doc` to be an object (*"If `doc` is an object, extract its text-bearing field
   such as `text` or `contents`"*). A parse-mode flip on the hosted API therefore
   puts a `dict` into `SearchHit["text"]`, which is typed `str | None`;
   `run_search_tool` then does `text[:max_chars]` and raises `TypeError` mid-run.
   The correct extractor already exists — `utils.fetch_doc._doc_text` — and is
   wired only into the doc-fetch path. **This is a one-line route-through and the
   one I'd actually apply.** Pinned by
   `test_search_pyserini_leaves_object_doc_unextracted_current_behaviour` and
   `test_pyserini_doc_as_object_is_NOT_unwrapped`.
2. **`src/utils/search_lucene_bool.py:28` — a hardcoded absolute path.**
   `_REPO_ROOT = "/scratch/fast/kun/projects/trec-rag-26"`, so `DEFAULT_BS` is
   broken on every host but one and `LUCENE_BOOL_BS` is mandatory in practice.
3. **`src/utils/search_lucene_bool.py:65` — snippet text can borrow the next hit's
   header.** `text = lines[i+1].strip()` is unconditional, so with no snippet
   between hits (`snippet_chars=0`) hit *n*'s text becomes
   `"[2] shard_… score=1.0"`. Ranks/docids/scores stay correct, so this corrupts
   only what the model reads.
4. **`src/utils/fetch_doc.py:52` — a missing `doc` yields the string `"null"`.**
   `json.dumps(None)`, not `""`, so the literal text `null` can reach a citation.
5. **`src/ragrun/outputs.py` — `validate_rag_output` crashes on a non-string
   `answer[].text`.** `len(sent["text"].split())` runs before any type check, so
   an `AttributeError` escapes `validate_rag_output` → `save_run`, losing the
   run's artifacts. Only reachable from a hand-built or LLM-parsed answer object.
6. **`build_rag_output(references="shard_…")` splats the string** into 17
   single-character "docids" (`list(references)`), and validation then reports
   them as *uncited references* rather than a type error — a confusing diagnosis
   of a trivial caller mistake.
7. **`src/utils/search.py:49` — a duplicate id within ONE ranking double-counts.**
   Its RRF contribution is added twice and `meta["sources"]` keeps only the later
   rank. No current backend returns duplicates, so this is latent, not live.
8. **U+2028/U+2029 pass through the JSONL unescaped.** `json.dumps` does not
   escape them, and `save_run` uses `ensure_ascii=False` deliberately (readable
   Unicode narratives). Records are still one physical line by the LF definition —
   so `json.loads` per `\n`-split line is safe, as is every reader we use — but
   `str.splitlines()` *does* break on them. If organizer-side tooling uses
   `splitlines()`, a U+2028 in an answer sentence truncates that record. Low
   likelihood (our formatters `re.sub(r"\s+", " ", …)`, and Python's `\s` matches
   U+2028), but it is a real property of the writer.
9. Minor, asserted for documentation value: duplicate docids in `references` are
   not flagged (`format_answer` dedups upstream); `True` validates as citation
   index 1 (`isinstance(True, int)`); `returned_docids` from a `failed=True` tool
   call still enter `retrieved_docids` (harmless today — failed calls return
   nothing — but "retrieved" reads as "successfully retrieved"); an unrecognised
   `MCP_SEARCH_ENGINE` silently falls back to hybrid instead of failing at boot.

**No `src/` runfile writer exists.** `grep -rn "Q0" src/` finds nothing; the only
producers are inline f-strings in `tasks/custom_index/scripts/eval_umbrela.py:89`
and `fetch_remote_run.py:140`, neither validated. So `tests/contract/runfile.py`
is currently the *only* enforcement of the retrieval output format in the repo —
six columns, the `Q0` literal, per-topic rank restart/ascent, score monotonicity,
the ClimbMix docid pattern, MS-MARCO-segment rejection, topic-block contiguity.
Its `rows_from_hits` also encodes the doc-level projection rule (`hit["docid"]`,
never `hit["id"]`); `test_chunk_level_hits_must_be_projected_to_parent_docids`
shows that a writer using `id` produces a fully rejected file.

## Deliberately not tested

- **`atomic_write_text`'s concurrency guarantee** — the temp-file + `os.replace`
  window is the whole point of it, and proving it needs a racing reader. Only its
  observable results are tested (files written, no `.tmp` debris).
- **Actual parallelism of `search()`'s `ThreadPoolExecutor`** — the fan-out is
  exercised, but asserting concurrency needs timing or barrier tricks that are
  flaky for little value.
- **`src/utils/search_sparse.chunked.py`** — marked `DRAFT — NOT APPLIED`,
  imported nowhere.
- **`src/tools/search_boolean_tool.py`** — a standalone duplicate of the SSR path
  (own `_post`, own default URL) that is not in `_DISPATCH` and is imported by no
  system.
- **"Answer claims must be supported by cited references"** — a semantic rule no
  unit test can check; that is what the RAGDoll/nugget layer is for.
- **The real `trec_rag_2026_queries.tsv`** is not in the repo, so topic fixtures
  use the spec's verbatim `rag2026-37` example plus the shape of
  `data/task-comparison/topics10.tsv`.

### Deferred: end-to-end suites for `o3_deep_research` and `claude-code-research`

Three of the five systems have end-to-end tests (`facet_rag`,
`ali_deepresearch`, `aus_agent`). The other two are deferred to a follow-up
rather than rushed into this branch: each needs a new fake of a *different*
shape, which deserves its own review, and neither blocks the enforcement wiring
(CI and the pre-commit hook are in place regardless). Tracked as
[issue #4](https://github.com/rmit-ir/trec-rag-26/issues/4), whose body is this
section — the reconnaissance below is what a follow-up starts from instead of
re-deriving. (Issues were disabled on the repo while this branch was being
written and got enabled shortly after; the defect list in "What the harness
found" is [issue #3](https://github.com/rmit-ir/trec-rag-26/issues/3).)

`o3_deep_research` — one 390-line `run.py`; testable surface `FormatLLM`,
`_docids_from_mcp_output`, `add_item_step`, `usage_stats`, `_retrieve`,
`run_one`, `load_topics`, `main`. Imports only stdlib + `ragrun` +
`ali_deepresearch.answer_format`, and `openai`/`boto3`/`mcp`/`dotenv` all
import under the `dev` group, so **no `importorskip` is needed**. `run_one`
drives cleanly against a hand-rolled fake SDK client: an event generator
yielding `response.created` / `output_item.added` / `output_item.done` /
`response.completed`, plus attribute-bag stand-ins for Responses items.
Current behaviour observed while probing (single-agent, **not independently
re-verified** — confirm before asserting):

- strict kinds `["tool_call", "reasoning", "tool_call", "tool_call", "output_text"]`
- `tool_call_counts == {"mcp_list_tools": 1, "search": 1, "fetch": 1}` — note
  `mcp_list_tools` counts as a tool call
- `retrieved_docids` picks up both search ids
- `usage_stats` derives `input_uncached = input - cached_tokens` and
  `processed = uncached + output`
- the MCP tool block gains `headers: {"Authorization": "Bearer <token>"}` only
  when `--mcp-token` is set
- `metadata.timing_resolution == "stream-events"` unless `--resume`

`claude-code-research` is **structurally unlike the other four** and needs a
different approach: it is not an importable package. The directory name is
hyphenated (not a valid module name) and holds `AGENTS.md`, `CLAUDE.md`,
`scripts/`, and ~9 committed `tasks/<slug>/` dirs of markdown — the "system" is
Claude Code itself driven by markdown workflows, with two standalone CLI
scripts as its corpus tool and artifact writer:

- `scripts/corpus.py` — `resolve_task_dir`, `append_log`, `_base_record`,
  `cmd_search`, `cmd_fetch`, `main`
- `scripts/save_run.py` — `load_narrative`, `read_tool_log`, `build_trajectory`,
  `map_citations`, `render_answer_text`, `main`. This one imports `ragrun` and
  does citation mapping, so it holds the real testable logic.

Load both **by file path**, the way `tests/shared/test_mcp_server.py` loads
`src/mcp/climbmix_server.py` (`importlib.util.spec_from_file_location`); the
`load_script` helper in `tests/systems/conftest.py` already exists for exactly
this.

## Verification

```bash
bash scripts/test.sh
# 792 passed, 4 deselected, 0 skipped
```

| directory | cases | what it covers |
| --- | --- | --- |
| `tests/contract/` | 228 | input/output format conformance vs the spec files |
| `tests/shared/` | 240 (1 `live`) | `utils` clients, RRF fusion, `env`, tool layer, `src/mcp` |
| `tests/systems/` | 178 (3 `live`) | `facet_rag`, `ali_deepresearch`, `aus_agent` pipelines |
| `tests/aus_agent_context/` | 135 | the context ledger (migrated from `unittest`) |
| `tests/dummy_api/` | 15 | real clients over loopback HTTP vs the dummy server |

The three dep groups are not optional: `test_mcp_server.py` `importorskip`s
`mcp.server.fastmcp` and `test_aus_agent.py` `importorskip`s `boto3`, so with
`--group dev` alone those tests **skip** and the run is green while proving
nothing about the code they cover. That is the same failure mode as the old
`test_mock.py` files printing `SKIPPED` and exiting 0, so CI and the pre-commit
hook both install all three, and CI additionally **fails the job on any skip** —
the suite is skip-free by design, so a skip means a dependency did not install.
Verified by running the gate against the pre-fix state: it caught the `boto3`
skip immediately.

Fixture-contract smoke probe (written first, to prove the fixtures work against
real code before the suites were built on them):
[assets/2026-07-28-harness-fixture-smoke.py](assets/2026-07-28-harness-fixture-smoke.py)
— 5 passed, then deleted from `tests/` since the real suites subsume it.

## Review round (2026-07-29)

Two fixture-level collision hazards from the PR review, both latent (nothing in
the suite triggered either yet) and both in helpers whose whole job is to keep
tests independent — so the failure mode would have been a *silently wrong pass*,
not a red test:

1. **`tests/conftest.py::tool_call` built its default id from
   `len(arguments)`**, so any two calls to the same tool with the same arity
   shared an id. A tool-call id is a key, not a label:
   `ScriptedProvider.compact_tool_results` looks results up by it and
   `StrictScriptedProvider.content_by_id` is a dict keyed on it, so colliding
   ids collapse two results into one. Now a process-wide `itertools.count`;
   explicit `id=` is unchanged, which is what every id-asserting test passes.
2. **`tests/systems/conftest.py::load_script` cached by `name` alone**, so
   reusing one name for a second path returned the *first* module — exactly the
   collision the helper exists to prevent (`o3_deep_research/run.py` is loaded
   under an explicit name precisely because bare `run.py` collides). It now
   compares the cached module's `__file__` against the requested path and raises
   on a mismatch. Verified both directions: two different files under one name
   raise; the same file under the same name still hits the cache.

Also corrected while re-verifying the PR's own claims, which had drifted after
the later `chunk-native commit` realignment on this branch: the case counts in
`AGENTS.md` and this worklog (786 → 792 total; `tests/systems/` 173 → 178,
`tests/aus_agent_context/` 134 → 135), and one duplicate test docstring the AST
sweep caught — `test_ali_deepresearch.py:168` and `test_facet_rag.py:137` shared
verbatim prose for the same no-violations invariant. The duplication is
legitimate coverage (two different pipelines), so the ReAct one now says what is
specific to it rather than being deleted. Sweep re-run: **546 test functions, 0
missing, 0 duplicate**.

```bash
bash scripts/test.sh
# 792 passed, 4 deselected, 1 warning in 9.88s
```

<!-- FINAL-COUNTS -->
