"""Selection-ratio-by-query-type analysis for the SSR (Cottontail GCL Boolean) arm.

Within-engine, first-surfacer-committed selection ratio: for each SSR search
query, what fraction of its returned docids ended up in the topic's final
committed reference set, crediting only the FIRST query to surface each docid
(novelty-corrected — removes the "duplicate/already committed" deflation).

Structural query-type tags (has_phrase / has_or / has_prox / and_arity /
n_atoms / has_entity) are parsed from the GCL query string, then rolled up into
one primary shape bucket per query, so we can ask which STRUCTURAL query shapes
the agent found most productive *within* the SSR runs.

Run-id: cmp-ssr-fork-v2 — the CURRENT FORK arm, identified by matching its
per-topic search counts (14/9/12/20/9/13/18/14/16/11 = 136) to the published
fork matrix. (cmp-ssr = old Hazel; cmp-ssr-fork = a different earlier fork with
163 searches.)

Usage: python3 selection_ratio.py
Stdlib only. Writes selection_ratio_by_type.md next to this file.
"""
import glob
import json
import re
import statistics
from collections import defaultdict, OrderedDict

ROOT = "/scratch/fast/kun/projects/trec-rag-26"
OUT_DIR = f"{ROOT}/data/outputs/aus_agent"
DEST = f"{ROOT}/data/task-comparison"
RUN_ID = "cmp-ssr-fork-v2"

# Published fork matrix (searches per topic) used to pick the right SSR run_id.
EXPECTED = {
    "rag2026-0": 14, "rag2026-1": 9, "rag2026-2": 12, "rag2026-3": 20,
    "rag2026-4": 9, "rag2026-5": 13, "rag2026-6": 18, "rag2026-7": 14,
    "rag2026-8": 16, "rag2026-9": 11,
}


# ---------------------------------------------------------------------------
# Query-type parsing
# ---------------------------------------------------------------------------
def and_arity(q):
    """Largest count of whitespace-separated atoms inside any top-level (^ ...)
    group — a crude over-constraint proxy (counts atoms, ignores nesting)."""
    best = 0
    for m in re.finditer(r"\(\^([^()]*)\)", q or ""):
        best = max(best, len(m.group(1).split()))
    return best


def has_phrase(q):
    return bool(re.search(r'"[^"]+"', q or ""))


def has_or(q):
    # GCL OR group is "(+ ...)"
    return "(+ " in (q or "")


def has_prox(q):
    q = q or ""
    return ("<<" in q) or (">>" in q) or ("(# " in q)


_ENTITY_TOK = re.compile(r"[A-Za-z0-9]+")


def has_entity(q):
    """Rare named-entity proxy: any token with a leading/internal uppercase
    letter, or an all-caps token of length >= 3. Bare lowercase words don't
    count. Original query case is preserved so this works."""
    for tok in _ENTITY_TOK.findall(q or ""):
        # all-caps of len>=3, e.g. HALEU, NRC
        if len(tok) >= 3 and tok.isupper() and any(c.isalpha() for c in tok):
            return True
        # leading or internal uppercase, e.g. Australia, Kazatomprom, iPhone
        if any(c.isupper() for c in tok):
            return True
    return False


def n_atoms(q):
    """Rough size: token count (word-ish atoms, ignoring GCL punctuation)."""
    return len(_ENTITY_TOK.findall(q or ""))


def primary_bucket(q):
    """One shape bucket per query. Precedence order (first match wins):
      1. anchor+OR    : has an OR group (+ ...)
      2. phrase-bearing: has a quoted "phrase"
      3. multi-AND    : and_arity >= 3 (heavily conjunctive), no OR
      4. single-facet : and_arity <= 1 and no OR and no phrase
      5. other        : everything else (e.g. 2-term AND, prox-only)
    OR is placed first because an anchor+OR query is structurally defined by the
    disjunction regardless of what else it carries; phrase next as it is the
    strongest remaining exact-match signal.
    """
    if has_or(q):
        return "anchor+OR"
    if has_phrase(q):
        return "phrase-bearing"
    a = and_arity(q)
    if a >= 3:
        return "multi-AND"
    if a <= 1 and not has_phrase(q):
        return "single-facet"
    return "other"


TAGS = ["has_phrase", "has_or", "has_prox", "has_entity"]
TAG_FN = {
    "has_phrase": has_phrase, "has_or": has_or,
    "has_prox": has_prox, "has_entity": has_entity,
}
BUCKETS = ["single-facet", "anchor+OR", "multi-AND", "phrase-bearing", "other"]


# ---------------------------------------------------------------------------
# Load + compute
# ---------------------------------------------------------------------------
def load_topics(run_id):
    """Return OrderedDict topic -> {references:set, searches:[step...]}."""
    topics = {}
    for path in glob.glob(f"{OUT_DIR}/*.output.json"):
        try:
            o = json.load(open(path))
        except (OSError, json.JSONDecodeError):
            continue
        m = o.get("metadata", {})
        if m.get("run_id") != run_id:
            continue
        qid = str(m.get("narrative_id"))
        steps = o.get("trace", {}).get("steps", [])
        searches = []
        for s in steps:
            if s.get("type") == "tool_call" and s.get("tool_name") == "search":
                searches.append({
                    "query": (s.get("arguments") or {}).get("query") or "",
                    "returned": list(s.get("returned_docids") or []),
                    "failed": bool(s.get("failed")),
                })
        topics[qid] = {
            "references": set(o.get("references") or []),
            "searches": searches,
        }
    return OrderedDict(sorted(topics.items(), key=lambda kv: int(kv[0].split("-")[-1])))


def analyze_topic(topic):
    """Per-query rows for one topic, with first-surfacer credit."""
    committed = topic["references"]
    first_surfacer = {}  # docid -> index of first search that returned it
    for i, s in enumerate(topic["searches"]):
        for d in s["returned"]:
            if d not in first_surfacer:
                first_surfacer[d] = i
    rows = []
    for i, s in enumerate(topic["searches"]):
        q = s["query"]
        returned = len(s["returned"])
        fs_committed = sum(
            1 for d in s["returned"]
            if first_surfacer.get(d) == i and d in committed
        )
        raw_committed = sum(1 for d in s["returned"] if d in committed)
        sel = (fs_committed / returned) if returned else 0.0
        rows.append({
            "query": q,
            "bucket": primary_bucket(q),
            "tags": {t: TAG_FN[t](q) for t in TAGS},
            "and_arity": and_arity(q),
            "n_atoms": n_atoms(q),
            "returned": returned,
            # zero-result == empty returned list (per spec: "empty list =>
            # zero-result"), independent of the failed flag — 5 of the 7
            # empties in this arm also carry failed=True.
            "zero": returned == 0,
            "failed": s["failed"],
            "fs_committed": fs_committed,
            "raw_committed": raw_committed,
            "sel_ratio": sel,
        })
    return rows


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
def pooled(rows, pred):
    sel = [r["sel_ratio"] for r in rows if pred(r)]
    ret = sum(r["returned"] for r in rows if pred(r))
    fs = sum(r["fs_committed"] for r in rows if pred(r))
    raw = sum(r["raw_committed"] for r in rows if pred(r))
    n = len(sel)
    return dict(
        n=n, returned=ret, fs=fs, raw=raw,
        mean_sel=statistics.mean(sel) if sel else 0.0,
        pooled=(fs / ret) if ret else 0.0,
    )


def fmt_tags(t):
    on = [k.replace("has_", "") for k, v in t.items() if v]
    return ",".join(on) if on else "—"


def main():
    topics = load_topics(RUN_ID)

    # sanity: search + zero counts vs expected matrix
    per_topic_rows = OrderedDict()
    all_rows = []
    for qid, top in topics.items():
        rows = analyze_topic(top)
        per_topic_rows[qid] = rows
        all_rows.extend(rows)

    n_search = len(all_rows)
    n_zero = sum(1 for r in all_rows if r["zero"])
    counts_ok = all(
        len(per_topic_rows.get(q, [])) == c for q, c in EXPECTED.items()
    ) and n_search == sum(EXPECTED.values())

    lines = []
    W = lines.append

    W("# SSR selection-ratio by query type (first-surfacer, novelty-corrected)\n")
    W(f"**Run:** `{RUN_ID}` — the current SSR fork arm. Chosen because its "
      f"per-topic search counts (14/9/12/20/9/13/18/14/16/11 = 136) match the "
      f"published fork matrix exactly; `cmp-ssr` is the old Hazel arm and "
      f"`cmp-ssr-fork` an earlier fork (163 searches).\n")
    W("**Metric:** for each SSR search query Q, `sel_ratio = fs_committed / "
      "returned`, where `fs_committed` counts only docids that Q was the FIRST "
      "query to surface AND that ended up in the topic's final committed "
      "reference set. `raw_committed` is the un-corrected count (any returned "
      "docid in the committed set) and is kept only to show the novelty gap. "
      "`returned == 0` (zero-result) => `sel_ratio = 0`.\n")
    W("**Caveats — read before using any number here:**\n")
    W("1. **Within-engine only.** These ratios describe productivity *inside "
      "the SSR trajectories* and are NOT comparable to the dense/keyword/lucene "
      "arms — each engine walked a different trajectory over a different "
      "candidate pool, so the committed sets and the queries differ.\n")
    W("2. **Agent-relevance, not ground truth.** \"Committed\" means the agent "
      "kept the doc as evidence, not that a qrel judged it relevant. The same "
      "model wrote the query and judged the commit, so there is a "
      "self-consistency bias inflating any query shape the model favours.\n")
    W("3. **Small N.** 10 topics, 136 queries. Per-bucket cells are tiny; treat "
      "this as a first-pass hypothesis generator, not a verdict.\n")

    # -- sanity line
    W("---\n")
    W(f"**Parse sanity:** {n_search} searches, {n_zero} zero-result "
      f"(expected 136 searches / 7 zeros) — "
      f"{'MATCH' if (n_search == 136 and n_zero == 7 and counts_ok) else 'MISMATCH'}.\n")

    # -- per-query table, grouped by topic
    W("## Per-query detail (grouped by topic)\n")
    W("| topic | query | bucket | tags | ret | fs_c | raw_c | sel |")
    W("|---|---|---|---|--:|--:|--:|--:|")
    for qid, rows in per_topic_rows.items():
        for r in rows:
            q = r["query"].replace("|", "\\|")
            fl = []
            if r["zero"]:
                fl.append("0")
            if r["failed"]:
                fl.append("FAIL")
            flag = (" (" + "/".join(fl) + ")") if fl else ""
            W(f"| {qid} | `{q}`{flag} | {r['bucket']} | {fmt_tags(r['tags'])} "
              f"| {r['returned']} | {r['fs_committed']} | {r['raw_committed']} "
              f"| {r['sel_ratio']:.3f} |")
    W("")

    # -- KEY aggregation: by shape bucket, ranked by pooled ratio
    W("## KEY — aggregation by shape bucket (ranked by pooled ratio)\n")
    bucket_stats = []
    for b in BUCKETS:
        st = pooled(all_rows, lambda r, b=b: r["bucket"] == b)
        if st["n"]:
            bucket_stats.append((b, st))
    bucket_stats.sort(key=lambda x: x[1]["pooled"], reverse=True)
    W("| rank | shape bucket | n_q | Σret | Σfs_c | mean sel | **pooled** |")
    W("|--:|---|--:|--:|--:|--:|--:|")
    for i, (b, st) in enumerate(bucket_stats, 1):
        W(f"| {i} | {b} | {st['n']} | {st['returned']} | {st['fs']} "
          f"| {st['mean_sel']:.3f} | **{st['pooled']:.3f}** |")
    W("")

    # -- by tag
    W("## Aggregation by structural tag\n")
    W("| tag | n_q | Σret | Σfs_c | mean sel | pooled |")
    W("|---|--:|--:|--:|--:|--:|")
    for t in TAGS:
        st = pooled(all_rows, lambda r, t=t: r["tags"][t])
        W(f"| {t}=True | {st['n']} | {st['returned']} | {st['fs']} "
          f"| {st['mean_sel']:.3f} | {st['pooled']:.3f} |")
    # also the complement / all
    allst = pooled(all_rows, lambda r: True)
    W(f"| ALL queries | {allst['n']} | {allst['returned']} | {allst['fs']} "
      f"| {allst['mean_sel']:.3f} | {allst['pooled']:.3f} |")
    W("")

    # -- novelty gap
    W("## Novelty gap (raw vs first-surfacer)\n")
    W(f"Pooled **raw_committed = {allst['raw']}** returned-slots landed in a "
      f"committed set, but only **fs_committed = {allst['fs']}** were credited "
      f"after first-surfacer correction — the correction removed "
      f"**{allst['raw'] - allst['fs']}** double-counted re-surfacings "
      f"({100*(allst['raw']-allst['fs'])/max(1,allst['raw']):.0f}% of raw). "
      f"Raw pooled ratio would have been "
      f"{allst['raw']/max(1,allst['returned']):.3f} vs corrected "
      f"{allst['pooled']:.3f}.\n")

    # -- written finding
    top_b = bucket_stats[0][0]
    bot_b = bucket_stats[-1][0]
    ent = pooled(all_rows, lambda r: r["tags"]["has_entity"])
    noent = pooled(all_rows, lambda r: not r["tags"]["has_entity"])
    phr = pooled(all_rows, lambda r: r["tags"]["has_phrase"])
    orr = pooled(all_rows, lambda r: r["tags"]["has_or"])
    W("## Finding\n")
    W(
        f"Ranked by first-surfacer productivity the **{top_b}** shape leads "
        f"(pooled {bucket_stats[0][1]['pooled']:.3f}) while **{bot_b}** trails "
        f"(pooled {bucket_stats[-1][1]['pooled']:.3f}). "
        f"On the tag axis, entity-bearing queries pool at "
        f"{ent['pooled']:.3f} vs {noent['pooled']:.3f} for non-entity queries, "
        f"phrase-bearing at {phr['pooled']:.3f}, and OR-anchored at "
        f"{orr['pooled']:.3f}. "
        f"The standing hypothesis is that SSR shines on "
        f"fact-heavy/entity/exact-phrase/co-occurrence queries. "
        f"{'The entity and phrase signals ' + ('support' if ent['pooled'] >= noent['pooled'] else 'run counter to') + ' that story' } "
        f"within this arm, but the effect sizes are small and rest on tiny "
        f"per-cell N. Because the model both wrote and judged, a high ratio "
        f"reflects what the agent chose to trust, not independent relevance — "
        f"so read these as hypotheses to test against qrels, not a verdict.\n")

    out = f"{DEST}/selection_ratio_by_type.md"
    with open(out, "w") as f:
        f.write("\n".join(lines))

    # console echo
    print(f"run_id={RUN_ID}  searches={n_search}  zeros={n_zero}  "
          f"counts_ok={counts_ok}  (expect 136/7)")
    print("\nby-bucket (ranked by pooled):")
    for i, (b, st) in enumerate(bucket_stats, 1):
        print(f"  {i}. {b:<14} n={st['n']:>3} ret={st['returned']:>4} "
              f"fs={st['fs']:>3} mean={st['mean_sel']:.3f} pooled={st['pooled']:.3f}")
    print("\nby-tag:")
    for t in TAGS:
        st = pooled(all_rows, lambda r, t=t: r["tags"][t])
        print(f"  {t:<12} n={st['n']:>3} ret={st['returned']:>4} "
              f"fs={st['fs']:>3} mean={st['mean_sel']:.3f} pooled={st['pooled']:.3f}")
    print(f"\nnovelty gap: raw={allst['raw']} fs={allst['fs']} "
          f"(removed {allst['raw']-allst['fs']})")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
