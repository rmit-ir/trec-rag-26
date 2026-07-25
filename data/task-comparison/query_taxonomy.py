"""Cross-backend "commit ratio by query type" analysis over aus_agent trajectories.

Pure offline analysis + luna intent classification. Does NOT re-run any search
engine or research agent. Reuses the first-surfacer commit-credit logic from
``selection_ratio.py`` verbatim, but generalizes it across all four
single-backend arms and swaps the structural GCL parser for a luna-judged,
trajectory-aware INTENT taxonomy.

Four single-backend runs (10 topics each, filter on metadata.run_id):
    cmp-dense, cmp-keyword, cmp-lucene, cmp-ssr-fork-v2

Pipeline (each step callable standalone; see __main__ dispatch):
  extract   -> per-(topic,backend) ordered trajectories with fs credit
  sample    -> representative query sample for taxonomy induction
  induce    -> luna proposes the intent taxonomy (writes query_type_taxonomy.md)
  classify  -> luna labels every query with trajectory context
               (writes query_classifications.jsonl)
  aggregate -> backend x type + role x backend matrices
               (writes commit_ratio_by_type.md)

Usage:
    uv run --no-project --with 'openai,python-dotenv' python query_taxonomy.py extract
    ... induce
    ... classify
    ... aggregate
    ... all        # induce -> classify -> aggregate (extract is implicit)
"""
from __future__ import annotations

import glob
import json
import os
import re
import sys
import time
from collections import OrderedDict, defaultdict

ROOT = "/scratch/fast/kun/projects/trec-rag-26"
OUT_DIR = f"{ROOT}/data/outputs/aus_agent"
DEST = f"{ROOT}/data/outputs/engine-comparison"

RUN_IDS = ["cmp-dense", "cmp-keyword", "cmp-lucene", "cmp-ssr-fork-v2"]
# Short, stable backend labels for the matrices.
BACKEND = {
    "cmp-dense": "dense",
    "cmp-keyword": "keyword",
    "cmp-lucene": "lucene",
    "cmp-ssr-fork-v2": "ssr",
}

TAXONOMY_MD = f"{DEST}/query_type_taxonomy.md"
CLASSIFICATIONS_JSONL = f"{DEST}/query_classifications.jsonl"
REPORT_MD = f"{DEST}/commit_ratio_by_type.md"
SAMPLE_JSON = f"{DEST}/.query_sample.json"          # intermediate
TAXONOMY_JSON = f"{DEST}/.query_taxonomy.json"      # machine-readable taxonomy

MODEL = os.environ.get("OPENAI_MODEL_ID") or "gpt-5.6-luna"

# Thin-cell thresholds for the aggregation flags.
THIN_NQ = 3
THIN_RET = 20


# ---------------------------------------------------------------------------
# 1. EXTRACT — ordered per-(topic,backend) trajectories + first-surfacer credit
#    (first-surfacer logic reused EXACTLY from selection_ratio.py)
# ---------------------------------------------------------------------------
def load_run(run_id):
    """topic -> {narrative, references:set, searches:[{query,engine,returned}]}."""
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
                args = s.get("arguments") or {}
                searches.append({
                    "query": args.get("query") or "",
                    "engine": args.get("search_engine") or "",
                    "returned": list(s.get("returned_docids") or []),
                    "failed": bool(s.get("failed")),
                })
        topics[qid] = {
            "narrative": m.get("narrative") or "",
            "references": set(o.get("references") or []),
            "searches": searches,
        }
    return OrderedDict(
        sorted(topics.items(), key=lambda kv: int(kv[0].split("-")[-1])))


def analyze_topic(topic):
    """Per-query rows for one topic with first-surfacer commit credit.

    Mirrors selection_ratio.analyze_topic exactly: a committed docid is
    credited to the FIRST search (by trajectory order) that returned it.
    """
    committed = topic["references"]
    first_surfacer = {}
    for i, s in enumerate(topic["searches"]):
        for d in s["returned"]:
            if d not in first_surfacer:
                first_surfacer[d] = i
    rows = []
    for i, s in enumerate(topic["searches"]):
        returned = len(s["returned"])
        fs_committed = sum(
            1 for d in s["returned"]
            if first_surfacer.get(d) == i and d in committed)
        raw_committed = sum(1 for d in s["returned"] if d in committed)
        rows.append({
            "idx": i,
            "query": s["query"],
            "engine": s["engine"],
            "returned": returned,
            "n_returned": returned,
            "zero": returned == 0,
            "failed": s["failed"],
            "fs_committed": fs_committed,
            "raw_committed": raw_committed,
            "sel_ratio": (fs_committed / returned) if returned else 0.0,
        })
    return rows


def extract_all():
    """[{run_id, backend, topic, narrative, rows:[per-query...]}] per topic-backend."""
    out = []
    for run_id in RUN_IDS:
        topics = load_run(run_id)
        for qid, top in topics.items():
            out.append({
                "run_id": run_id,
                "backend": BACKEND[run_id],
                "topic": qid,
                "narrative": top["narrative"],
                "rows": analyze_topic(top),
            })
    return out


def cmd_extract():
    data = extract_all()
    nq = sum(len(d["rows"]) for d in data)
    nz = sum(1 for d in data for r in d["rows"] if r["zero"])
    print(f"topic-backend trajectories: {len(data)}  queries: {nq}  zeros: {nz}")
    by_b = defaultdict(lambda: [0, 0])
    for d in data:
        by_b[d["backend"]][0] += len(d["rows"])
        by_b[d["backend"]][1] += sum(r["returned"] for r in d["rows"])
    for b, (n, ret) in sorted(by_b.items()):
        print(f"  {b:<8} n_queries={n:>4}  Sigma_returned={ret:>5}")
    return data


# ---------------------------------------------------------------------------
# luna helpers
# ---------------------------------------------------------------------------
def _client():
    from dotenv import load_dotenv
    load_dotenv(f"{ROOT}/.env")
    from openai import OpenAI
    return OpenAI(timeout=600.0, max_retries=5)


def _chat(client, system, user, *, max_retries=4):
    """One chat.completions call; returns text. Retries on transient error."""
    last = None
    for attempt in range(max_retries):
        try:
            r = client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
            return r.choices[0].message.content or ""
        except Exception as e:  # noqa: BLE001 — transient Azure/network
            last = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"luna call failed after {max_retries} tries: {last}")


def _extract_json(text):
    """Pull the first top-level JSON object/array out of a model reply."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text.strip())
    # try direct
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # find first { ... } or [ ... ] spanning balanced braces
    for opn, cls in (("{", "}"), ("[", "]")):
        start = text.find(opn)
        if start < 0:
            continue
        depth = 0
        for i in range(start, len(text)):
            if text[i] == opn:
                depth += 1
            elif text[i] == cls:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        break
    raise ValueError(f"no JSON found in reply:\n{text[:500]}")


# ---------------------------------------------------------------------------
# 2. SAMPLE + INDUCE taxonomy
# ---------------------------------------------------------------------------
def build_sample(data, per_backend=14):
    """Representative queries: spread across backends + several topics.

    Round-robins topics within each backend so the sample includes NL dense /
    keyword queries AND GCL ssr AND lucene syntax.
    """
    sample = []
    by_backend = defaultdict(list)
    for d in data:
        for r in d["rows"]:
            if r["query"].strip():
                by_backend[d["backend"]].append({
                    "backend": d["backend"], "topic": d["topic"],
                    "query": r["query"], "n_returned": r["n_returned"],
                })
    for b, rows in by_backend.items():
        # spread by topic: take up to 2 per topic until we hit per_backend
        seen_topic = defaultdict(int)
        picked = []
        for r in rows:
            if seen_topic[r["topic"]] < 2:
                picked.append(r)
                seen_topic[r["topic"]] += 1
            if len(picked) >= per_backend:
                break
        # top up if we ran short
        if len(picked) < per_backend:
            for r in rows:
                if r not in picked:
                    picked.append(r)
                if len(picked) >= per_backend:
                    break
        sample.extend(picked)
    return sample


INDUCE_SYSTEM = """You are an expert in information-retrieval query intent \
analysis. You will design an engine-AGNOSTIC INTENT taxonomy for search \
queries issued by a research agent across four different search backends \
(a dense semantic retriever, a keyword retriever, a Lucene Boolean/phrase \
engine, and an SSR GCL Boolean engine using operators like (^ a b) for OR, \
(+ a b) for AND, "phrase", and >>/<< containment).

Intent means WHAT the query is trying to accomplish, independent of whether \
it is phrased in natural language or Boolean syntax. The SAME intent can \
appear as an NL question or a Boolean expression."""

INDUCE_USER_TMPL = """Below is a representative sample of real queries the \
agent issued across all four backends and several topics.

SAMPLE (backend | query | n_docs_returned):
{sample_block}

TASK
Propose an engine-AGNOSTIC INTENT taxonomy of 10-15 query TYPES that captures \
the intent of these queries and applies equally to NL and Boolean phrasings. \
Ground the list in what you actually see in the sample. Cover intents such as \
(adapt / rename / merge / add as the data warrants): broad-exploratory, \
facet-drilldown, named-entity-lookup, fact-or-claim-verification, \
disambiguation, exact-phrase-or-quote, quantitative-evidence-seeking, \
relational-cooccurrence, definitional-or-conceptual, temporal-or-recency, and \
comparative. Each TYPE needs a short kebab-case id and a crisp one-line \
definition (<= 22 words).

ALSO define a small ORTHOGONAL set of TRAJECTORY-ROLES describing the query's \
role in the topic's search sequence: opening, narrowing, broadening, \
retry-after-zero, pivot-to-new-subtopic, refinement. Keep these six unless a \
clearly-missing role is warranted; give each a one-line definition.

Return STRICT JSON only, no prose, in this shape:
{{
  "types": [{{"id": "kebab-id", "def": "one-line definition"}}, ...],
  "roles": [{{"id": "opening", "def": "one-line definition"}}, ...]
}}"""


def cmd_induce():
    data = extract_all()
    sample = build_sample(data)
    json.dump(sample, open(SAMPLE_JSON, "w"), indent=2)
    block = "\n".join(
        f'- {s["backend"]:<8} | {s["query"]}  | ret={s["n_returned"]}'
        for s in sample)
    client = _client()
    reply = _chat(client, INDUCE_SYSTEM,
                  INDUCE_USER_TMPL.format(sample_block=block))
    tax = _extract_json(reply)
    assert isinstance(tax.get("types"), list) and tax["types"], "bad taxonomy"
    assert isinstance(tax.get("roles"), list) and tax["roles"], "bad roles"
    json.dump(tax, open(TAXONOMY_JSON, "w"), indent=2)
    _write_taxonomy_md(tax, sample)
    print(f"induced {len(tax['types'])} types, {len(tax['roles'])} roles "
          f"from {len(sample)} sampled queries")
    for t in tax["types"]:
        print(f"  - {t['id']}: {t['def']}")
    return tax


def _write_taxonomy_md(tax, sample):
    L = []
    W = L.append
    W("# Query intent taxonomy (luna-induced, engine-agnostic)\n")
    W(f"**Model:** `{MODEL}` (luna). **Induced from** {len(sample)} queries "
      f"sampled across the four single-backend arms "
      f"(`{'`, `'.join(RUN_IDS)}`), spread over topics and backends so the "
      f"sample mixes NL (dense/keyword) and Boolean (lucene/ssr GCL) phrasings.\n")
    W("The taxonomy is **intent-based**: each type describes what a query is "
      "trying to accomplish, independent of NL-vs-Boolean surface form, so "
      "like-intent queries can be compared across engines.\n")
    W("## Query types\n")
    W("| id | definition |")
    W("|---|---|")
    for t in tax["types"]:
        W(f"| `{t['id']}` | {t['def']} |")
    W("")
    W("## Trajectory roles (orthogonal)\n")
    W("A query's role in its topic's ordered search sequence.\n")
    W("| id | definition |")
    W("|---|---|")
    for r in tax["roles"]:
        W(f"| `{r['id']}` | {r['def']} |")
    W("")
    with open(TAXONOMY_MD, "w") as f:
        f.write("\n".join(L))


# ---------------------------------------------------------------------------
# 3. CLASSIFY — per topic-backend, one luna call labelling every query
# ---------------------------------------------------------------------------
CLASSIFY_SYSTEM = """You are an expert IR query-intent classifier. You label \
each search query a research agent issued with (a) a primary intent TYPE, \
(b) an optional secondary TYPE, and (c) its TRAJECTORY-ROLE in the topic's \
ordered search sequence. Use the trajectory context — the full ordered list \
of queries and their hit counts — to distinguish an opener from a retry from \
a pivot. Return ONLY the strict JSON asked for; use exactly the given type \
and role ids."""

CLASSIFY_USER_TMPL = """TAXONOMY — allowed primary/secondary TYPE ids (use these exact ids):
{types_block}

Allowed TRAJECTORY-ROLE ids (use these exact ids):
{roles_block}

TOPIC NARRATIVE:
{narrative}

FULL ORDERED TRAJECTORY for this topic on the "{backend}" backend \
(index: query  -> returned N docs; ZERO means zero results):
{traj_block}

TASK
Classify EACH query in the trajectory above. For every query index, choose \
one primary_type (required), one secondary_type (or null), one \
trajectory_role, and a confidence in [0,1]. Judge role using the surrounding \
queries (e.g. a query repeating an intent right after a ZERO result is \
retry-after-zero; the first query is usually opening; a jump to an unrelated \
subtopic is pivot-to-new-subtopic).

Return STRICT JSON only — a single array, one object per query index, in order:
[{{"idx": 0, "primary_type": "id", "secondary_type": "id-or-null", \
"trajectory_role": "id", "confidence": 0.0}}, ...]"""


def _traj_block(rows):
    lines = []
    for r in rows:
        q = r["query"] if r["query"].strip() else "(empty)"
        tag = "ZERO" if r["zero"] else f"{r['n_returned']}"
        fl = " FAILED" if r["failed"] else ""
        lines.append(f"[{r['idx']}] {q}  -> returned {tag}{fl}")
    return "\n".join(lines)


def cmd_classify():
    data = extract_all()
    tax = json.load(open(TAXONOMY_JSON))
    valid_types = {t["id"] for t in tax["types"]}
    valid_roles = {r["id"] for r in tax["roles"]}
    types_block = "\n".join(f'- {t["id"]}: {t["def"]}' for t in tax["types"])
    roles_block = "\n".join(f'- {r["id"]}: {r["def"]}' for r in tax["roles"])
    client = _client()

    out_rows = []
    n_topic_backends = len(data)
    for k, d in enumerate(data, 1):
        rows = d["rows"]
        if not rows:
            continue
        user = CLASSIFY_USER_TMPL.format(
            types_block=types_block, roles_block=roles_block,
            narrative=d["narrative"][:2500], backend=d["backend"],
            traj_block=_traj_block(rows))
        reply = _chat(client, CLASSIFY_SYSTEM, user)
        labels = _extract_json(reply)
        by_idx = {int(x["idx"]): x for x in labels if "idx" in x}
        for r in rows:
            lab = by_idx.get(r["idx"], {})
            pt = lab.get("primary_type")
            st = lab.get("secondary_type")
            role = lab.get("trajectory_role")
            # sanitize against taxonomy; fall back gracefully
            if pt not in valid_types:
                pt = "unclassified"
            if st in ("null", "", None) or st not in valid_types:
                st = None
            if role not in valid_roles:
                role = "unclassified"
            try:
                conf = float(lab.get("confidence"))
            except (TypeError, ValueError):
                conf = None
            out_rows.append({
                "run_id": d["run_id"], "backend": d["backend"],
                "topic": d["topic"], "idx": r["idx"], "query": r["query"],
                "engine": r["engine"], "n_returned": r["n_returned"],
                "returned": r["returned"], "zero": r["zero"],
                "failed": r["failed"], "fs_committed": r["fs_committed"],
                "raw_committed": r["raw_committed"],
                "sel_ratio": r["sel_ratio"],
                "primary_type": pt, "secondary_type": st,
                "trajectory_role": role, "confidence": conf,
            })
        print(f"[{k}/{n_topic_backends}] {d['backend']} {d['topic']}: "
              f"labelled {len(rows)} queries")

    with open(CLASSIFICATIONS_JSONL, "w") as f:
        for row in out_rows:
            f.write(json.dumps(row) + "\n")
    print(f"\nwrote {len(out_rows)} labels -> {CLASSIFICATIONS_JSONL}")
    return out_rows


# ---------------------------------------------------------------------------
# 4. AGGREGATE — backend x type + role x backend matrices
# ---------------------------------------------------------------------------
def _load_labels():
    rows = []
    with open(CLASSIFICATIONS_JSONL) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _pooled(rows):
    ret = sum(r["returned"] for r in rows)
    fs = sum(r["fs_committed"] for r in rows)
    raw = sum(r["raw_committed"] for r in rows)
    return {
        "n": len(rows), "returned": ret, "fs": fs, "raw": raw,
        "pooled": (fs / ret) if ret else 0.0,
    }


def cmd_aggregate():
    labels = _load_labels()
    tax = json.load(open(TAXONOMY_JSON))
    type_ids = [t["id"] for t in tax["types"]]
    role_ids = [r["id"] for r in tax["roles"]]
    type_def = {t["id"]: t["def"] for t in tax["types"]}
    backends = ["dense", "keyword", "lucene", "ssr"]

    # backend x type cells
    cell = {}       # (type, backend) -> pooled dict
    for t in type_ids + ["unclassified"]:
        for b in backends:
            sub = [r for r in labels
                   if r["primary_type"] == t and r["backend"] == b]
            if sub:
                cell[(t, b)] = _pooled(sub)
    present_types = [t for t in type_ids + ["unclassified"]
                     if any((t, b) in cell for b in backends)]

    # role x backend cells
    rcell = {}
    for role in role_ids + ["unclassified"]:
        for b in backends:
            sub = [r for r in labels
                   if r["trajectory_role"] == role and r["backend"] == b]
            if sub:
                rcell[(role, b)] = _pooled(sub)
    present_roles = [role for role in role_ids + ["unclassified"]
                     if any((role, b) in rcell for b in backends)]

    def thin(st):
        return st["n"] < THIN_NQ or st["returned"] < THIN_RET

    # best backend per type
    ranked = []
    for t in present_types:
        opts = [(b, cell[(t, b)]) for b in backends if (t, b) in cell]
        opts.sort(key=lambda x: x[1]["pooled"], reverse=True)
        ranked.append((t, opts))

    _write_report(labels, tax, type_def, backends, present_types, cell,
                  present_roles, rcell, ranked, thin)

    # console echo
    print(f"labels: {len(labels)}  types present: {len(present_types)}")
    print("\nbest backend per type (pooled fs-ratio):")
    for t, opts in ranked:
        b, st = opts[0]
        flag = " [THIN]" if thin(st) else ""
        print(f"  {t:<28} -> {b:<8} {st['pooled']:.3f} "
              f"(n={st['n']}, ret={st['returned']}){flag}")
    return labels


def _write_report(labels, tax, type_def, backends, present_types, cell,
                  present_roles, rcell, ranked, thin):
    L = []
    W = L.append
    total = _pooled(labels)

    W("# Commit ratio by query type (backend x intent, first-surfacer)\n")
    W(f"**Model (classifier + taxonomy):** `{MODEL}` (luna). "
      f"**Runs:** four single-backend arms, 10 topics each — "
      f"`{'`, `'.join(RUN_IDS)}` (labels `dense`/`keyword`/`lucene`/`ssr`).\n")
    W("**Metric — first-surfacer commit ratio.** For each search query Q, "
      "`fs_committed` counts docids that Q was the FIRST query (in its "
      "topic-backend trajectory) to surface AND that ended up in the topic's "
      "final committed `references` set; `returned` is len(returned_docids). "
      "A cell's **pooled ratio = Sigma fs_committed / Sigma returned** over its "
      "queries. This is the identical first-surfacer credit rule used by "
      "`selection_ratio.py`, generalized across all four backends.\n")
    W("**Query TYPE** is a luna-judged engine-agnostic intent label; **role** "
      "is a luna-judged trajectory role. Each query was classified with its "
      "FULL topic-backend trajectory (every query + hit count) in context, so "
      "retries/openers/pivots are distinguished. See "
      "`query_type_taxonomy.md` for definitions and `query_classifications.jsonl` "
      "for per-query labels.\n")
    W(f"**Totals:** {total['n']} queries, Sigma_returned={total['returned']}, "
      f"Sigma_fs_committed={total['fs']}, overall pooled ratio "
      f"**{total['pooled']:.3f}**.\n")

    # -- taxonomy summary
    W("## Taxonomy summary\n")
    W("| type | definition |")
    W("|---|---|")
    for t in tax["types"]:
        W(f"| `{t['id']}` | {t['def']} |")
    W("")

    # -- backend x type matrix
    W("## Backend x query-type matrix (pooled first-surfacer ratio)\n")
    W("Cell = pooled ratio, with `n`=n_queries and `R`=Sigma_returned. "
      f"**†** flags THIN cells (n_queries < {THIN_NQ} or Sigma_returned < "
      f"{THIN_RET}) — unreliable.\n")
    header = "| query-type | " + " | ".join(backends) + " | row pooled |"
    W(header)
    W("|---|" + "---|" * (len(backends) + 1))
    for t in present_types:
        cells = []
        row_rows = [r for r in labels if r["primary_type"] == t]
        for b in backends:
            st = cell.get((t, b))
            if not st:
                cells.append("—")
                continue
            flag = "†" if thin(st) else ""
            cells.append(f"{st['pooled']:.3f}{flag} (n{st['n']},R{st['returned']})")
        rp = _pooled(row_rows)
        cells.append(f"**{rp['pooled']:.3f}** (n{rp['n']},R{rp['returned']})")
        W(f"| `{t}` | " + " | ".join(cells) + " |")
    # column totals
    coltot = []
    for b in backends:
        st = _pooled([r for r in labels if r["backend"] == b])
        coltot.append(f"**{st['pooled']:.3f}** (n{st['n']},R{st['returned']})")
    W(f"| **col pooled** | " + " | ".join(coltot)
      + f" | **{total['pooled']:.3f}** |")
    W("")

    # -- best backend per type
    W("## Best backend per query-type (ranked within type)\n")
    W("For each intent, backends ranked by pooled first-surfacer ratio. "
      "`†` = winning cell is THIN (treat as suggestive only). The runner-up "
      "is shown to gauge margin.\n")
    W("| query-type | best backend | pooled | n / R | runner-up | note |")
    W("|---|---|--:|---|---|---|")
    for t, opts in ranked:
        b, st = opts[0]
        winflag = "†" if thin(st) else ""
        if len(opts) > 1:
            rb, rst = opts[1]
            runner = f"{rb} {rst['pooled']:.3f}"
        else:
            runner = "(only backend)"
        note = "THIN — suggestive only" if thin(st) else ""
        W(f"| `{t}` | **{b}**{winflag} | {st['pooled']:.3f} "
          f"| {st['n']} / {st['returned']} | {runner} | {note} |")
    W("")

    # -- boolean-engine callout
    boolean_wins = [(t, opts[0]) for t, opts in ranked
                    if opts[0][0] in ("lucene", "ssr")]
    W("### Do the Boolean engines (lucene / ssr) win any intent?\n")
    if boolean_wins:
        for t, (b, st) in boolean_wins:
            fl = " (THIN — suggestive)" if thin(st) else ""
            W(f"- **{t}** -> **{b}** pooled {st['pooled']:.3f} "
              f"(n={st['n']}, R={st['returned']}){fl}")
    else:
        W("- Neither lucene nor ssr is the top backend for any intent type "
          "in this data.")
    W("")

    # -- role x backend matrix
    W("## Trajectory-role x backend matrix (pooled first-surfacer ratio)\n")
    W("Secondary cut: does a backend do better on openers vs retries vs "
      "pivots? Same pooled metric; `†` = thin cell.\n")
    W("| role | " + " | ".join(backends) + " | row pooled |")
    W("|---|" + "---|" * (len(backends) + 1))
    for role in present_roles:
        cells = []
        for b in backends:
            st = rcell.get((role, b))
            if not st:
                cells.append("—")
                continue
            flag = "†" if thin(st) else ""
            cells.append(f"{st['pooled']:.3f}{flag} (n{st['n']},R{st['returned']})")
        rp = _pooled([r for r in labels if r["trajectory_role"] == role])
        cells.append(f"**{rp['pooled']:.3f}** (n{rp['n']},R{rp['returned']})")
        W(f"| `{role}` | " + " | ".join(cells) + " |")
    W("")

    # -- caveats
    W("## CAVEATS — read before using any number here\n")
    W("1. **Behavioral / agent-relevance, NOT ground truth.** \"Committed\" "
      "means the agent kept the doc in `references`, not that a qrel judged it "
      "relevant. The same luna family wrote the queries, judged the commits, "
      "and (here) classified the intents — a self-consistency bias inflates "
      "whatever the model favours.\n")
    W("2. **Denominator inflation only PARTLY controlled.** Backends issued "
      "different query volumes and returned different pool sizes, which biases "
      "raw aggregate ratios. Comparing WITHIN a query-type controls for intent "
      "mix but NOT for per-cell denominator differences — a backend that "
      "returns more docs per query dilutes its own ratio.\n")
    W(f"3. **Thin cells.** Cells with n_queries < {THIN_NQ} or "
      f"Sigma_returned < {THIN_RET} are flagged `†`. Many per-(type x backend) "
      "cells are tiny (10 topics x 4 backends); treat flagged cells and any "
      "single-backend intent as hypothesis-generating, not conclusive.\n")
    W("4. **Classification is luna-judged.** Types and roles are model labels "
      "with a confidence field (in the JSONL); no human adjudication. "
      "Mislabels move queries between cells and can swing thin cells.\n")
    W("5. **First-surfacer credit is per topic-backend.** A doc committed in a "
      "topic is credited to the first query (in THAT backend's trajectory) to "
      "surface it, so ratios are not comparable to a hypothetical union across "
      "backends.\n")

    with open(REPORT_MD, "w") as f:
        f.write("\n".join(L))
    print(f"wrote {REPORT_MD}")


# ---------------------------------------------------------------------------
def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    if cmd == "extract":
        cmd_extract()
    elif cmd == "induce":
        cmd_induce()
    elif cmd == "classify":
        cmd_classify()
    elif cmd == "aggregate":
        cmd_aggregate()
    elif cmd == "all":
        cmd_induce()
        cmd_classify()
        cmd_aggregate()
    else:
        print(f"unknown command: {cmd}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
