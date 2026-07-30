# 2026-07-30 — Mandatory 429/5xx backoff across every hosted client (#10)

Closes #10, filed earlier today out of the vendored-skill re-vendor
(`worklogs/2026-07-30-spec-revendor-validator-relax.md`). The
`pyserini-rest-api` skill went v0.2.0 → v0.3.0 and gained a **"Request Pacing
and Rate Limits"** section that is mandatory, not advisory — the Pyserini API is
shared infrastructure the whole track hits.

## What the policy requires, and where we stood

| Rule | Status before | Action |
|---|---|---|
| ≤1 in-flight request per worker | **compliant by construction** — every client is a synchronous `urlopen` | none |
| fixed modest worker pool (~12) | **compliant** — pools cap at 2 (`utils.search`) and 8 (`aus_agent`) | none |
| back off on `429`, honour `Retry-After` | **absent** | implemented |
| same for transient `5xx` / timeouts | **absent** | implemented |
| health check probed one-shot, not retried | n/a (no retry existed) | `max_retries=0` supported |

The concurrency half was already fine; the backoff half was entirely missing.
Five call sites each did a bare `urlopen`.

## `src/utils/http_retry.py` (new)

One place for the policy instead of five slightly-different retry loops.

- `RETRY_STATUSES = {429, 500, 502, 503, 504, 507, 509}`. **Nothing else.** A
  `401` is a missing token and a `404` a missing docid — retrying either wastes
  the shared endpoint's allowance and delays the real error by the full
  schedule.
- `parse_retry_after` handles **both** documented header forms: delay-seconds
  (`Retry-After: 30`) and HTTP-date (`Retry-After: Wed, 21 Oct 2026 07:28:00
  GMT`). Honouring only the integer form would fall through to our own guessed
  backoff at exactly the moment the server stated its need precisely.
  - past date → `0.0`, not a negative (`time.sleep` raises on negative);
  - unparseable → `None` so the caller uses exponential backoff. Returning
    `0.0` there would turn a garbled header into a tight loop against a
    rate-limited endpoint.
  - zoneless HTTP-date is read as UTC per spec — reading it as local would skew
    the wait by the machine's offset, differently in CI than on a laptop.
- Exponential backoff 1/2/4/8s, capped at `MAX_DELAY = 60`, `MAX_RETRIES = 4`.
  The cap also applies to a server-stated `Retry-After` — a server asking for an
  hour must not make a batch job look hung.
- Exhausted retries **re-raise the last error**. A swallowed failure would show
  up as a narrative with no retrieval, silently scoring zero.

Two binding-order decisions, both commented in the source because both are the
kind of thing a later "cleanup" would undo:

1. `opener` and `sleep` are resolved **per call**, not defaulted in the
   signature. A default argument binds at import time, so it would bypass
   `tests/dummy_api/conftest.py`'s monkeypatch of `urllib.request.urlopen`.
2. The `except urllib.error.HTTPError` branch must precede
   `except urllib.error.URLError` — **`HTTPError` subclasses `URLError`**. Wrong
   order and every `HTTPError` is swallowed by the connection-drop branch, so a
   `404` would be retried four times.

Plus a module-level `_sleep = time.sleep` indirection, so a test can neutralize
the waiting without patching `time.sleep` process-wide (which would also hit the
dummy server's thread) and without threading a `sleep=` kwarg through five
clients that have no business exposing one.

## Call sites routed through it (all five from the issue)

| File | Function |
|---|---|
| `src/utils/search_dense.py` | `post_json` — dense, **and via it sparse + SSR** (both import it from here) |
| `src/utils/search_pyserini.py` | `_get_json` |
| `src/utils/fetch_doc.py` | `fetch_doc` |
| `src/tools/search_boolean_tool.py` | `_post` |
| `src/systems/aus_agent/tools/get_documents.py` | `_fetch_one` |

`get_documents._fetch_one` was the interesting one: its pre-existing bare
`except Exception: return uid, None` means a `429` used to become a silent
"missing". That is *worse* than a visible failure — an id in `missing` reads to
the agent as "this chunk does not exist", indistinguishable from an
out-of-range `_p<page>`, so it stops asking rather than retrying. Commented in
place.

## Two defects the tests surfaced (neither was the thing being tested)

Writing the loopback test for `get_documents` failed, and the reason wasn't the
backoff:

1. **`DENSE` was bound at import time.** `get_documents.py` had
   `DENSE = os.environ.get("DENSE_SEARCH_URL", ...)` at module level, so unlike
   every sibling client it could not be repointed at runtime — a `.env` loaded
   after import, or a test, was silently ignored and the request went to the
   hosted endpoint. Replaced with a `_dense_base()` call-time resolver matching
   `search_dense`. Pinned by
   `test_get_documents_reads_dense_search_url_at_call_time`.
2. **The dummy server's `/doc/` handler only spoke Pyserini's shape.** It
   returned `{"docid", "doc"}`, but the dense service returns `{"docid",
   "text"}` (`tasks/search_serve/scripts/server.py:337-349`), which is what
   `_fetch_one` reads. Made the handler flavor-aware — a gap in the dummy API's
   fidelity, not in `src/`.

## Tests

`tests/dummy_api/dummy_server.py` gained `fail_times` / `fail_status` /
`retry_after`: answer the first N requests with `429` (optionally carrying the
header), then behave normally. Lock-guarded countdown since the handler runs on
the server thread.

| File | Cases | Covers |
|---|---|---|
| `tests/shared/test_http_retry.py` | 30 | the decision logic with a fake opener — both `Retry-After` forms, past/zoneless/malformed dates, retried vs non-retried statuses, `HTTPError`-before-`URLError` ordering, the 1/2/4/8 schedule and its bound, `max_retries=0`, timeout forwarding, no-sleep-on-success |
| `tests/dummy_api/test_rate_limit.py` | 10 | each of the five call sites (7 clients incl. sparse/SSR) recovering from a real `429` over loopback; the retry budget terminating; `Retry-After` surviving the real `urlopen` → `HTTPError.headers` path; a real `401` still failing on attempt one |

The unit tests alone would not have caught a *missed* call site — five
independent chances to have forgotten one, invisible until the hosted endpoint
rate-limits us mid-run and one client fails alone. Hence the loopback layer:
a client still calling `urllib.request.urlopen` directly fails those tests.

Every sleep is neutralized. A real 1/2/4/8s schedule across 40 cases would have
dominated a 14-second suite.

Full suite: **836 passed** (was 792 before today's work, 835 before the
env-var test), 14s, zero skips.
