// k6 load-test job: /search endpoint of the search REST API.
//
// Usage (from tasks/loadtest/):
//   pnpm search:smoke                                  # 1 VU, 1 iteration
//   pnpm search                                        # default: 1 VU, 30s
//   k6 run -e VUS=8 -e DURATION=60s tests/search.js
//   k6 run -e QUERIES_CSV=data/my-queries.csv tests/search.js
//
// Tunables (all via -e):
//   BASE_URL     target server        (default https://index-climbmix-jina-v5-nano.dsync.net)
//   USERNAME     basic-auth user      (default rmitir)
//   PASSWORD     basic-auth password  (default rmitir)
//   K            top-k results        (default 10)
//   WITH_TEXT    include segment text (default true)
//   QUERIES_CSV  1-column CSV of queries, no header (default ../data/queries.csv,
//                resolved relative to this script's directory)
//   MODE         'constant' | 'stress' (default constant)
//   VUS          [constant] concurrent virtual users (default 1)
//   DURATION     [constant] test duration (default 30s)
//   MAX_RATE     [stress] req/s ceiling of the ramp (default 200)
//   STRESS_DURATION [stress] ramp length (default 10m)
//   MAX_VUS      [stress] VU pool cap for the arrival-rate executor (default 500)

import http from 'k6/http';
import exec from 'k6/execution';
import { check } from 'k6';
import { Trend } from 'k6/metrics';
import { SharedArray } from 'k6/data';
import encoding from 'k6/encoding';

const BASE_URL = __ENV.BASE_URL || 'https://index-climbmix-jina-v5-nano.dsync.net';
const USERNAME = __ENV.USERNAME || 'rmitir';
const PASSWORD = __ENV.PASSWORD || 'rmitir';
const K = parseInt(__ENV.K || '10', 10);
const WITH_TEXT = (__ENV.WITH_TEXT || 'true') === 'true';
// NB: k6's open() resolves relative paths against this script's directory
// (tests/), not the cwd — pass an absolute path or one relative to tests/.
const QUERIES_CSV = __ENV.QUERIES_CSV || '../data/queries.csv';

// MODE=constant (default): fixed VUs for a fixed duration.
// MODE=stress: breakpoint test — request rate ramps linearly from 1 req/s to
// MAX_RATE over STRESS_DURATION and the run aborts itself as soon as the
// error-rate/latency thresholds break. The req/s at abort time is the
// server's breaking point.
const MODE = __ENV.MODE || 'constant';

export const options =
  MODE === 'stress'
    ? {
        scenarios: {
          stress: {
            executor: 'ramping-arrival-rate',
            startRate: 1,
            timeUnit: '1s',
            preAllocatedVUs: 50,
            maxVUs: parseInt(__ENV.MAX_VUS || '500', 10),
            stages: [
              {
                duration: __ENV.STRESS_DURATION || '10m',
                target: parseInt(__ENV.MAX_RATE || '200', 10),
              },
            ],
          },
        },
        thresholds: {
          http_req_failed: [
            { threshold: 'rate<0.05', abortOnFail: true, delayAbortEval: '15s' },
          ],
          http_req_duration: [
            { threshold: 'p(95)<5000', abortOnFail: true, delayAbortEval: '15s' },
          ],
        },
      }
    : {
        vus: parseInt(__ENV.VUS || '1', 10),
        duration: __ENV.DURATION || '30s',
        thresholds: {
          http_req_failed: ['rate<0.01'],
          http_req_duration: ['p(95)<2000'],
        },
      };

// 1-column CSV, no header: every non-empty line is a query.
// SharedArray parses once and shares read-only across all VUs.
const QUERIES = new SharedArray('queries', () =>
  open(QUERIES_CSV)
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line.length > 0)
);

const searchLatency = new Trend('search_req_duration', true);

export default function () {
  // iterationInTest is globally unique across all VUs, so the appended
  // sequence number guarantees no query string is ever sent twice —
  // defeating any response cache and always exercising the encode path.
  const seq = exec.scenario.iterationInTest;
  const query = `${QUERIES[seq % QUERIES.length]} ${seq}`;
  const payload = JSON.stringify({ query, k: K, with_text: WITH_TEXT });

  const res = http.post(`${BASE_URL}/search`, payload, {
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Basic ${encoding.b64encode(`${USERNAME}:${PASSWORD}`)}`,
    },
  });

  searchLatency.add(res.timings.duration);

  check(res, {
    'status is 200': (r) => r.status === 200,
    'has results': (r) => {
      try {
        const body = r.json();
        const hits = body.results || body.hits || body;
        return Array.isArray(hits) ? hits.length > 0 : hits != null;
      } catch (e) {
        return false;
      }
    },
  });
}
