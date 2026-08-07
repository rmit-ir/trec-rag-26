#!/usr/bin/env python3
"""Extract everything gpt-5.6-sol needs to diagnose brief_revise_agent's
shortfall vs aus_agent, for all 30 dev-set topics: both systems' full
answers, brief_revise_agent's brief/search-log/commit stats, the arena
verdict per topic (both orientations + judge's raw reasoning snippet), and
whether the review pass fired. Writes one big structured markdown doc.
"""
import glob
import json
import re
from pathlib import Path

ROOT = Path("/home/el7/E103037/repos/trec-rag-26")
OUT = Path("/tmp/claude-200103037/-home-el7-E103037-repos-trec-rag-26/"
          "df99835e-2a3b-451d-a8ff-36c7c7a48daa/scratchpad/sol_improve_data.md")

DEV30_LOG = Path("/tmp/claude-200103037/-home-el7-E103037-repos-trec-rag-26/"
                 "df99835e-2a3b-451d-a8ff-36c7c7a48daa/tasks/bld4o4max.output")


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
        # commit_context's output string is a JSON object followed by a
        # trailing "[context budget: ...]" note -- json.loads rejects the
        # extra data, so decode just the leading object.
        try:
            obj, _ = json.JSONDecoder().raw_decode(out)
            return obj if isinstance(obj, dict) else {}
        except (json.JSONDecodeError, TypeError):
            return {}
    return out or {}


def search_log(d):
    lines = []
    n = 0
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
        return "(no brief -- analyst produced zero usable requirements this topic)"
    section = sp.split(marker, 1)[1]
    lines = [ln for ln in section.splitlines() if ln.strip().startswith("- [")]
    return "\n".join(f"    {ln.strip()}" for ln in lines) if lines else "(empty)"


def review_fired(qid, log_text):
    # crude but effective: our own log.info lines are qid-scoped by the
    # preceding "starting: ..." line block; find the review.hook usage line
    # that falls between this qid's start and the next topic's start.
    starts = [m.start() for m in re.finditer(
        r"\[" + re.escape(qid) + r"\] starting:", log_text)]
    if not starts:
        return "unknown (topic not found in log)"
    start = starts[0]
    next_topic = re.search(r"\n=== \w", log_text[start:])
    end = start + next_topic.start() if next_topic else len(log_text)
    segment = log_text[start:end]
    m = re.search(r"review\.hook: usage=(\{.*?\})", segment)
    if not m:
        return "did not fire (report accepted on first pass, or never reached review)"
    parse_fail = "reviewer response did not parse" in segment
    return f"fired, usage={m.group(1)}" + (" -- REVIEWER JSON PARSE FAILED (degraded to zero issues)" if parse_fail else "")


def main():
    aus = load("aus_agent", "aus-agent-dev30-luna-e2708ab")
    brief = load("brief_revise_agent", "brief-revise-dev30-6252022")
    judgments = [json.loads(l) for l in
                (ROOT / "evaluation-results/arena/aus_agent-vs-brief_revise_agent-dev30-rubric/judgments.jsonl").read_text().splitlines()]
    by_topic = {}
    for r in judgments:
        by_topic.setdefault(r["topic_id"], {})[r["orientation"]] = r

    log_text = DEV30_LOG.read_text() if DEV30_LOG.exists() else ""

    qids = sorted(set(aus) & set(brief))
    groups = {}
    for qid in qids:
        prefs = {by_topic[qid][o]["preferred_run_id"] for o in (0, 1) if o in by_topic.get(qid, {})}
        if prefs == {"aus_agent"}:
            groups[qid] = "CLEAN LOSS (aus_agent won both orientations)"
        elif prefs == {"brief_revise_agent"}:
            groups[qid] = "CLEAN WIN (brief_revise_agent won both orientations)"
        else:
            groups[qid] = "AMBIGUOUS (judge disagreed by orientation)"

    order = {"CLEAN LOSS (aus_agent won both orientations)": 0,
            "AMBIGUOUS (judge disagreed by orientation)": 1,
            "CLEAN WIN (brief_revise_agent won both orientations)": 2}
    ordered_qids = sorted(qids, key=lambda q: order[groups[q]])

    out = []
    n_loss = sum(1 for g in groups.values() if g.startswith("CLEAN LOSS"))
    n_win = sum(1 for g in groups.values() if g.startswith("CLEAN WIN"))
    n_amb = sum(1 for g in groups.values() if g.startswith("AMBIGUOUS"))
    out.append(f"# Per-topic raw data, all 30 dev-set topics\n\n"
               f"Ordered: clean losses first ({n_loss}), then ambiguous ({n_amb}), "
               f"then clean wins ({n_win}) -- {aus[qids[0]]['metadata']['run_desc'][:0]}"
               f"aus_agent vs brief_revise_agent, both on openai/gpt-5.6-luna.\n")

    for qid in ordered_qids:
        a, b = aus[qid], brief[qid]
        group = groups[qid]
        a_ans, a_words, a_unc, a_n = answer_block(a)
        b_ans, b_words, b_unc, b_n = answer_block(b)
        b_committed, b_rejected = commit_stats(b)
        j0 = by_topic.get(qid, {}).get(0, {})
        j1 = by_topic.get(qid, {}).get(1, {})

        out.append(f"\n{'='*100}\n## Topic `{qid}` -- {group}\n{'='*100}\n")
        out.append(f"NARRATIVE:\n{a['metadata']['narrative']}\n")
        out.append(f"\nARENA VERDICT (judge=gpt-5.6-terra, rubric-guided, official ResearchRubrics criteria):")
        out.append(f"  orientation 0 (A=aus_agent, B=brief_revise_agent): "
                   f"preferred={j0.get('preferred_run_id')} | judge said: {j0.get('raw_output','')[:250]!r}")
        out.append(f"  orientation 1 (A=brief_revise_agent, B=aus_agent): "
                   f"preferred={j1.get('preferred_run_id')} | judge said: {j1.get('raw_output','')[:250]!r}")

        out.append(f"\n--- brief_revise_agent's requirements brief ---")
        out.append(brief_entries(b))

        b_search_log, b_n_searches = search_log(b)
        out.append(f"\n--- brief_revise_agent's search log ({b_n_searches} calls, "
                   f"{b_committed} committed / {b_rejected} rejected docs) ---")
        out.append(b_search_log)

        out.append(f"\n--- review pass ---")
        out.append(f"  {review_fired(qid, log_text)}")

        out.append(f"\n--- aus_agent's ANSWER ({a_words} words, {a_n} sentences, "
                   f"{a_unc} uncited) ---")
        out.append(a_ans)

        out.append(f"\n--- brief_revise_agent's ANSWER ({b_words} words, {b_n} sentences, "
                   f"{b_unc} uncited) ---")
        out.append(b_ans)

    OUT.write_text("\n".join(out), encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes, "
         f"~{OUT.stat().st_size // 4} tokens estimate)")
    print(f"clean losses={n_loss} ambiguous={n_amb} clean wins={n_win}")


if __name__ == "__main__":
    main()
