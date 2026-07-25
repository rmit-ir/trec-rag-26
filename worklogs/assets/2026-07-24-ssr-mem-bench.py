#!/usr/bin/env python3
"""Memory-over-time bench for cottontail-jsonl-server.

Launches ONE server on a single-shard burrow, drives a diverse repeated GCL /
text query workload for many rounds, and samples the server process RSS +
smaps anonymous/Private_Dirty at intervals. Emits a TSV trace and a verdict.

Usage:
  mem_bench.py --binary <server> --burrow <path> --port <n> --rounds <n>
               --trace <out.tsv> [--cache-budget-mb <n>] [--label <name>]
"""
import argparse, json, os, random, re, signal, subprocess, sys, time, urllib.request

# A small FIXED probe set of hand-written queries (common terms, phrases,
# (^ ...) OR, (+ ...) AND) whose RESULTS we snapshot for parity checking across
# the baseline and fixed builds. ClimbMix is a general web/pretraining corpus.
PROBE_QUERIES = [
    ("search_text", {"query": "climate change", "top_k": 20}),
    ("search_text", {"query": "machine learning models", "top_k": 20}),
    ("search_text", {"query": "how to bake sourdough bread", "top_k": 20}),
    ("search_gcl", {"query": '(+ "neural" "network")', "top_k": 20}),
    ("search_gcl", {"query": '(^ "python" "javascript" "rust")', "top_k": 20}),
    ("search_gcl", {"query": '"world war two"', "top_k": 20}),
    ("search_gcl", {"query": '(+ "electric" "vehicle" "battery")', "top_k": 20}),
    ("count_matches", {"query": "government", "is_gcl": False}),
    ("count_matches", {"query": '(+ "artificial" "intelligence")', "is_gcl": True}),
    ("count_matches", {"query": "recipe", "is_gcl": False}),
]


def build_round_queries_count_only(vocab, rng, n_per_round=200):
    """Count-only variant: GCL count_matches over rare terms. Every query builds
    hoppers via SimpleIdx::load_cache (the exact leak path) but skips SSR
    ranking, so it is fast and cleanly isolates cache memory from rank-thread
    transient buffers. Mixes (^ ...) OR, (+ ...) AND, phrases, single-term."""
    qs = []
    w = lambda: rng.choice(vocab)
    for _ in range(n_per_round):
        r = rng.random()
        if r < 0.5:
            q = "(^ " + " ".join(f'"{w()}"' for _ in range(5)) + ")"
        elif r < 0.75:
            q = "(+ " + " ".join(f'"{w()}"' for _ in range(2)) + ")"
        elif r < 0.9:
            q = '"' + " ".join(w() for _ in range(2)) + '"'
        else:
            q = f'"{w()}"'
        qs.append(("count_matches", {"query": q, "is_gcl": True}))
    return qs


def build_round_queries(vocab, rng, n_per_round=200):
    """A diverse, distinct-HEAVY workload drawn from the real burrow vocabulary.

    Each round draws fresh random words so the SimpleIdx posting cache churns
    through MANY distinct postings -- the condition that exposes unbounded
    small-posting accumulation in `cache_`. Every query type below is a GCL /
    text query that builds hoppers via SimpleIdx::load_cache (the exact leak
    path). We lean on GCL count_matches over rare terms: it exercises load_cache
    for every operand yet skips the multi-second SSR ranking pass, so hundreds
    of rounds are feasible. A slice of real search queries keeps the mix diverse
    (they hit the same cache path). Mixes (^ ...) OR, (+ ...) AND, phrases,
    single-term, across text and GCL endpoints."""
    qs = []
    w = lambda: rng.choice(vocab)
    for _ in range(n_per_round):
        r = rng.random()
        if r < 0.45:  # (^ 5 rare) OR  -- GCL count (loads 5 distinct postings)
            q = "(^ " + " ".join(f'"{w()}"' for _ in range(5)) + ")"
            qs.append(("count_matches", {"query": q, "is_gcl": True}))
        elif r < 0.65:  # (+ 2 rare) AND -- GCL count
            q = "(+ " + " ".join(f'"{w()}"' for _ in range(2)) + ")"
            qs.append(("count_matches", {"query": q, "is_gcl": True}))
        elif r < 0.80:  # phrase -- GCL count
            q = '"' + " ".join(w() for _ in range(2)) + '"'
            qs.append(("count_matches", {"query": q, "is_gcl": True}))
        elif r < 0.92:  # single rare term -- GCL count
            qs.append(("count_matches", {"query": f'"{w()}"', "is_gcl": True}))
        elif r < 0.97:  # (^ 4 rare) OR search (real ranked query, same cache path)
            q = "(^ " + " ".join(f'"{w()}"' for _ in range(4)) + ")"
            qs.append(("search_gcl", {"query": q, "top_k": 20}))
        else:  # (+ 2 rare) AND search
            q = "(+ " + " ".join(f'"{w()}"' for _ in range(2)) + ")"
            qs.append(("search_gcl", {"query": q, "top_k": 20}))
    return qs


def read_smaps(pid):
    """Return (rss_kb, anon_kb, private_dirty_kb) from smaps_rollup."""
    rss = anon = pd = 0
    try:
        with open(f"/proc/{pid}/smaps_rollup") as f:
            for line in f:
                if line.startswith("Rss:"):
                    rss = int(line.split()[1])
                elif line.startswith("Anonymous:"):
                    anon = int(line.split()[1])
                elif line.startswith("Private_Dirty:"):
                    pd = int(line.split()[1])
    except FileNotFoundError:
        return None
    return rss, anon, pd


def post(port, endpoint, body, token=None):
    url = f"http://127.0.0.1:{port}/tools/{endpoint}"
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode())


def wait_healthz(port, timeout=600):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz",
                                        timeout=5) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(1)
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--binary", required=True)
    ap.add_argument("--burrow", required=True)
    ap.add_argument("--port", type=int, default=8099)
    ap.add_argument("--rounds", type=int, default=200)
    ap.add_argument("--threads", type=int, default=2)
    ap.add_argument("--rank-threads", type=int, default=None)
    ap.add_argument("--cache-budget-mb", type=int, default=None)
    ap.add_argument("--trace", required=True)
    ap.add_argument("--label", default="run")
    ap.add_argument("--vocab", required=True, help="word-per-line vocab file")
    ap.add_argument("--seed", type=int, default=1234,
                    help="RNG seed -- SAME seed => SAME query stream across builds")
    ap.add_argument("--queries-per-round", type=int, default=200)
    ap.add_argument("--count-only", action="store_true",
                    help="GCL count_matches only (fast, isolates cache memory)")
    ap.add_argument("--results-out", default=None,
                    help="write PROBE query hits here for parity checking")
    args = ap.parse_args()

    with open(args.vocab) as f:
        vocab = [line.strip() for line in f if line.strip()]
    print(f"[{args.label}] vocab={len(vocab)} words", flush=True)

    cmd = [args.binary, "--burrow", args.burrow, "--port", str(args.port),
           "--threads", str(args.threads), "--no-auth"]
    if args.rank_threads is not None:
        cmd += ["--rank-threads", str(args.rank_threads)]
    if args.cache_budget_mb is not None:
        cmd += ["--cache-budget-mb", str(args.cache_budget_mb)]

    print(f"[{args.label}] launching: {' '.join(cmd)}", flush=True)
    logf = open(args.trace + ".serverlog", "w")
    proc = subprocess.Popen(cmd, stdout=logf, stderr=subprocess.STDOUT)
    pid = proc.pid
    try:
        if not wait_healthz(args.port):
            print("server did not become healthy", file=sys.stderr)
            proc.terminate()
            return 2
        print(f"[{args.label}] healthy, pid={pid}", flush=True)

        trace = open(args.trace, "w")
        trace.write("round\tquery_idx\telapsed_s\trss_mb\tanon_mb\tpriv_dirty_mb\n")
        t_start = time.time()

        # baseline sample before any query
        s = read_smaps(pid)
        if s:
            trace.write(f"0\t-1\t{time.time()-t_start:.1f}\t{s[0]/1024:.1f}\t"
                        f"{s[1]/1024:.1f}\t{s[2]/1024:.1f}\n")
            trace.flush()

        # Parity probe: run the FIXED probe set once, up front, and snapshot the
        # result signatures (used to prove the fix doesn't change results).
        probe_sigs = []
        for endpoint, body in PROBE_QUERIES:
            try:
                resp = post(args.port, endpoint, body)
                probe_sigs.append(summarize(endpoint, body, resp))
            except Exception as e:
                print(f"probe error: {e}", file=sys.stderr)

        rng = random.Random(args.seed)
        q = 0
        for rnd in range(1, args.rounds + 1):
            # fresh distinct-heavy batch; identical stream across builds (seed).
            if args.count_only:
                batch = build_round_queries_count_only(
                    vocab, rng, args.queries_per_round)
            else:
                batch = build_round_queries(vocab, rng, args.queries_per_round)
            for qi, (endpoint, body) in enumerate(batch):
                try:
                    resp = post(args.port, endpoint, body)
                except Exception as e:
                    print(f"query error r{rnd} q{qi}: {e}", file=sys.stderr)
                    continue
                q += 1
            # sample memory once per round
            s = read_smaps(pid)
            if s is None:
                print("process gone", file=sys.stderr)
                break
            trace.write(f"{rnd}\t{q}\t{time.time()-t_start:.1f}\t{s[0]/1024:.1f}\t"
                        f"{s[1]/1024:.1f}\t{s[2]/1024:.1f}\n")
            trace.flush()
            if rnd % 20 == 0:
                print(f"[{args.label}] round {rnd}/{args.rounds}  "
                      f"rss={s[0]/1024:.0f}MB anon={s[1]/1024:.0f}MB "
                      f"pd={s[2]/1024:.0f}MB", flush=True)
        trace.close()

        if args.results_out:
            with open(args.results_out, "w") as rf:
                json.dump(probe_sigs, rf, indent=1)
        return 0
    finally:
        try:
            proc.send_signal(signal.SIGINT)
            proc.wait(timeout=15)
        except Exception:
            proc.kill()
        logf.close()


def summarize(endpoint, body, resp):
    """Stable signature of a response for parity checking across builds."""
    out = {"endpoint": endpoint, "query": body.get("query")}
    if endpoint == "count_matches":
        out["count"] = resp.get("match_count", resp.get("count"))
    else:
        hits = resp.get("results") or resp.get("hits") or []
        # signature = ordered list of (cp/docno-ish id, score) top hits
        sig = []
        for h in hits[:10]:
            cp = h.get("cp", h.get("docno", h.get("id")))
            sc = h.get("score")
            sig.append([cp, round(sc, 4) if isinstance(sc, (int, float)) else sc])
        out["hits"] = sig
    return out


if __name__ == "__main__":
    sys.exit(main())
