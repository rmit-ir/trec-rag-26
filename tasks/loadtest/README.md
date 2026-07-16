# loadtest

Load-test jobs for TREC RAG 2026 services, driven by [k6](https://k6.io).
This task owns **all** load-test jobs — each job is one k6 script under
`tests/`. Unlike the Python tasks, this is a pnpm project (k6 scripts are
JavaScript); `@types/k6` provides editor IntelliSense only — k6 itself is a
standalone binary (`brew install k6`), not a node dependency.

## Setup

```bash
cd tasks/loadtest
pnpm install          # dev types only
```

## Jobs

### search — `/search` REST endpoint

POSTs queries to the search API with basic auth and checks status +
non-empty results. Queries come from a 1-column CSV (no header, one query
per line); each request appends a globally unique sequence number to the
query so no query string is ever repeated (defeats response caches, always
exercises the encode path).

```bash
pnpm search:smoke     # 1 VU, 1 iteration — sanity check
pnpm search           # 1 VU, 30s
pnpm search:load      # 8 VUs, 60s
pnpm search:stress    # breakpoint test: ramp 1 → 200 req/s over 10m, abort on failure
```

`search:stress` keeps increasing the request rate until the server breaks:
it aborts as soon as the error rate exceeds 5% or p95 latency exceeds 5 s
(sustained for 15 s). Read the breaking point off the final report — the
req/s (`http_reqs` rate around abort time) and active VUs when the threshold
tripped. Tune the ramp with `-e MAX_RATE=… -e STRESS_DURATION=… -e MAX_VUS=…`.
A non-zero exit code in stress mode is expected — it means the threshold
tripped, i.e. the breaking point was found.

Tunables via `k6 run -e KEY=VALUE tests/search.js`:

| Var        | Default                                          | Meaning                  |
|------------|--------------------------------------------------|--------------------------|
| `BASE_URL` | `https://index-climbmix-jina-v5-nano.dsync.net`  | target server            |
| `USERNAME` | `rmitir`                                         | basic-auth user          |
| `PASSWORD` | `rmitir`                                         | basic-auth password      |
| `K`        | `10`                                             | top-k results            |
| `WITH_TEXT`| `true`                                           | include segment text     |
| `QUERIES_CSV` | `../data/queries.csv`                         | 1-column CSV of queries (no header). Relative paths resolve against `tests/`, so prefer absolute paths |
| `MODE`     | `constant`                                       | `constant` or `stress`   |
| `VUS`      | `1`                                              | [constant] concurrent virtual users |
| `DURATION` | `30s`                                            | [constant] test duration |
| `MAX_RATE` | `200`                                            | [stress] req/s ceiling of the ramp |
| `STRESS_DURATION` | `10m`                                     | [stress] ramp length     |
| `MAX_VUS`  | `500`                                            | [stress] VU pool cap     |

### bm25 — `/api/search` REST endpoint

Same idea as `search`, but for the BM25 service — a GET, Elasticsearch-style
endpoint: `GET /api/search?q=<query>&hits=<n>` with basic auth. Results come
back under `body.hits.hits[]`. Each request appends a globally unique sequence
number to the query so no query string is ever repeated.

```bash
pnpm bm25:smoke     # 1 VU, 1 iteration — sanity check
pnpm bm25           # 1 VU, 30s
pnpm bm25:load      # 8 VUs, 60s
pnpm bm25:stress    # breakpoint test: ramp 1 → 200 req/s over 10m, abort on failure
```

Stress mode behaves exactly like `search:stress` (see above) — it aborts as
soon as the error rate exceeds 5% or p95 latency exceeds 5 s (sustained 15 s);
the req/s at abort time is the breaking point. A non-zero exit code is expected.

Tunables via `k6 run -e KEY=VALUE tests/bm25.js`:

| Var        | Default                                     | Meaning                  |
|------------|---------------------------------------------|--------------------------|
| `BASE_URL` | `https://index-climbmix-bm25.dsync.net`     | target server            |
| `USERNAME` | `rmitir`                                    | basic-auth user          |
| `PASSWORD` | `rmitir`                                    | basic-auth password      |
| `HITS`     | `10`                                        | top-k results (`hits` param) |
| `QUERIES_CSV` | `../data/queries.csv`                    | 1-column CSV of queries (no header). Relative paths resolve against `tests/`, so prefer absolute paths |
| `MODE`     | `constant`                                  | `constant` or `stress`   |
| `VUS`      | `1`                                         | [constant] concurrent virtual users |
| `DURATION` | `30s`                                       | [constant] test duration |
| `MAX_RATE` | `200`                                       | [stress] req/s ceiling of the ramp |
| `STRESS_DURATION` | `10m`                                | [stress] ramp length     |
| `MAX_VUS`  | `500`                                       | [stress] VU pool cap     |

## Adding a job

1. Add `tests/<job>.js` (k6 script; keep tunables as `__ENV` vars with defaults).
2. Add `"<job>"` / `"<job>:smoke"` entries to `package.json` scripts.
3. Document it here.
