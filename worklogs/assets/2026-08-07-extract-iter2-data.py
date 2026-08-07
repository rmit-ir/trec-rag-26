#!/usr/bin/env python3
"""Extract raw per-topic data for sol iteration 2: brief_revise_agent
(v2, coverage-gated review) vs the NEW, much stronger aus_agent_v2 baseline,
over the 15-topic experimental set."""
import glob
import json
import re
from pathlib import Path

ROOT = Path("/home/el7/E103037/repos/trec-rag-26")
OUT = Path("/tmp/claude-200103037/-home-el7-E103037-repos-trec-rag-26/"
          "df99835e-2a3b-451d-a8ff-36c7c7a48daa/scratchpad/sol_iter2_data.md")
BRV_LOG = Path("/tmp/claude-200103037/-home-el7-E103037-repos-trec-rag-26/"
              "df99835e-2a3b-451d-a8ff-36c7c7a48daa/tasks/b0qm7xod6.output")


def load(sysdir, run_id):
    out = {}
    for f in glob.glob(str(ROOT / "data/outputs" / sysdir / "*.output.json")):
        d = json.loads(Path(f).read_text())
        if d["metadata"]["run_id"] == run_id:
            out[d["metadata"]["narrative_id"]] = d
    return out


def answer_block(d):
    lines = []
    for i, s in enumerate(d["answer"], 1):
        cites = ",".join(str(c) for c in (s.get("citations") or [])) or "none"
        lines.append(f"  {i}. [{cites}] {s['text']}")
    words = sum(len(s["text"].split()) for s in d["answer"])
    uncited = sum(1 for s in d["answer"] if not s.get("citations"))
    return "\n".join(lines), words, uncited, len(d["answer"])


def _step_output(s):
    out = s.get("output")
    if isinstance(out, str):
        try:
            obj, _ = json.JSONDecoder().raw_decode(out)
            return obj if isinstance(obj, dict) else {}
        except (json.JSONDecodeError, TypeError):
            return {}
    return out or {}


def search_log(d):
    lines, n = [], 0
    for s in d["trace"]["steps"]:
        if s["type"] == "tool_call" and s.get("tool_name") == "search":
            a = s["arguments"]
            lines.append(f"    [{a.get('search_engine')}] {a.get('query')}")
            n += 1
    return "\n".join(lines), n


def commit_stats(d):
    committed = rejected = 0
    for s in d["trace"]["steps"]:
        if s["type"] == "tool_call" and s.get("tool_name") == "commit_context":
            out = _step_output(s)
            committed += len(out.get("committed", []) or [])
            rejected += len(out.get("rejected", []) or [])
    return committed, rejected


def brief_entries(d):
    sp = d["trace"]["input"].get("system_prompt", "")
    marker = "## Requirements brief (advisory)"
    if marker not in sp:
        return "(no brief)"
    section = sp.split(marker, 1)[1]
    lines = [ln for ln in section.splitlines() if ln.strip().startswith("- [")]
    return "\n".join(f"    {ln.strip()}" for ln in lines) if lines else "(empty)"


def review_status(qid, log_text):
    starts = [m.start() for m in re.finditer(
        r"\[" + re.escape(qid) + r"\] starting:", log_text)]
    if not starts:
        return "unknown"
    start = starts[0]
    nxt = re.search(r"\n=== \w", log_text[start:])
    seg = log_text[start:start + nxt.start()] if nxt else log_text[start:]
    fires = re.findall(r"review\.hook: usage=(\{.*?\})", seg)
    retried = "retrying once with a repair prompt" in seg
    both_failed = "repair retry also failed to parse" in seg
    if not fires:
        return "did not fire (draft accepted first pass)"
    s = f"fired ({len(fires)} reviewer call(s))"
    if retried:
        s += ", PARSE FAILED -> retried"
    if both_failed:
        s += ", BOTH ATTEMPTS FAILED -> accepted as-is (review_failed)"
    return s


def main():
    baseline = load("aus_agent_v2", "aus-agent-v2-exp15-luna")
    brv = load("brief_revise_agent", "brief-revise-iter1-exp15")
    judgments = [json.loads(l) for l in (
        ROOT / "evaluation-results/arena/aus_agent_v2-vs-brief_revise_agent-iter1-exp15"
        "/judgments.jsonl").read_text().splitlines()]
    by_topic = {}
    for r in judgments:
        by_topic.setdefault(r["topic_id"], {})[r["orientation"]] = r
    log_text = BRV_LOG.read_text() if BRV_LOG.exists() else ""

    qids = sorted(set(baseline) & set(brv))
    groups = {}
    for qid in qids:
        prefs = {by_topic[qid][o]["preferred_run_id"] for o in (0, 1)
                if o in by_topic.get(qid, {})}
        if prefs == {"aus_agent_v2"}:
            groups[qid] = "CLEAN LOSS (aus_agent_v2 won both orientations)"
        elif prefs == {"brief_revise_agent"}:
            groups[qid] = "CLEAN WIN (brief_revise_agent won both orientations)"
        else:
            groups[qid] = "AMBIGUOUS"
    order = {"CLEAN LOSS (aus_agent_v2 won both orientations)": 0,
            "AMBIGUOUS": 1,
            "CLEAN WIN (brief_revise_agent won both orientations)": 2}
    ordered = sorted(qids, key=lambda q: order[groups[q]])

    out = [f"# 15-topic iteration-1 result, per topic\n"]
    for qid in ordered:
        a, b = baseline[qid], brv[qid]
        a_ans, a_words, a_unc, a_n = answer_block(a)
        b_ans, b_words, b_unc, b_n = answer_block(b)
        b_committed, b_rejected = commit_stats(b)
        b_search, b_nsearch = search_log(b)
        j0 = by_topic.get(qid, {}).get(0, {})
        j1 = by_topic.get(qid, {}).get(1, {})
        out.append(f"\n{'='*100}\n## Topic `{qid}` -- {groups[qid]}\n{'='*100}\n")
        out.append(f"NARRATIVE:\n{a['metadata']['narrative']}\n")
        out.append("ARENA VERDICT (judge=gpt-5.6-terra):")
        out.append(f"  o0 (A=aus_agent_v2,B=brief_revise_agent): "
                   f"preferred={j0.get('preferred_run_id')} raw={j0.get('raw_output','')[:200]!r}")
        out.append(f"  o1 (A=brief_revise_agent,B=aus_agent_v2): "
                   f"preferred={j1.get('preferred_run_id')} raw={j1.get('raw_output','')[:200]!r}")
        out.append(f"\n--- brief_revise_agent's brief ---")
        out.append(brief_entries(b))
        out.append(f"\n--- brief_revise_agent's search log ({b_nsearch} calls, "
                   f"{b_committed} committed / {b_rejected} rejected) ---")
        out.append(b_search)
        out.append(f"\n--- brief_revise_agent's review pass ---")
        out.append(f"  {review_status(qid, log_text)}")
        out.append(f"\n--- aus_agent_v2's ANSWER ({a_words}w, {a_n} sentences, {a_unc} uncited) ---")
        out.append(a_ans)
        out.append(f"\n--- brief_revise_agent's ANSWER ({b_words}w, {b_n} sentences, {b_unc} uncited) ---")
        out.append(b_ans)

    OUT.write_text("\n".join(out), encoding="utf-8")
    print(f"wrote {OUT} (~{OUT.stat().st_size // 4} tokens)")


if __name__ == "__main__":
    main()
