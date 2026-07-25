import http from 'k6/http';
import { check } from 'k6';
import { SharedArray } from 'k6/data';

// Real SSR GCL queries harvested from data/outputs/aus_agent trajectories.
// Regenerate the query set with:  ssr_loadtest.sh --harvest
const queries = new SharedArray('ssr', () => JSON.parse(open('./ssr_loadtest_queries.json')));

// VUs + duration are set per ramp step by ssr_loadtest.sh (--vus/--duration).
export default function () {
  const q = queries[Math.floor(Math.random() * queries.length)];
  const res = http.post(
    __ENV.SSR_URL || 'http://127.0.0.1:8099/search',
    JSON.stringify({ query: q, k: Number(__ENV.K || 10) }),
    { headers: { 'Content-Type': 'application/json' }, timeout: '60s' }
  );
  check(res, { 'status 200': (r) => r.status === 200 });
}
