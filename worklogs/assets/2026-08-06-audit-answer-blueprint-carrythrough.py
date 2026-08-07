"""Measure whether blueprint claims and commit-time facts reach final prose."""
from __future__ import annotations

import glob
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUN_ID = "sol-aus-v2-answer-blueprint-low8-20260806"
CLAIM_RE = re.compile(r"^\s+CLAIM: (.*?) EVIDENCE:", re.MULTILINE)
FACT_MARKER = "COMMIT-TIME FACT CARDS FOR MAPPED EVIDENCE\n"
TOKEN_RE = re.compile(r"[a-z0-9]+")


def normalized(text: str) -> str:
    return " ".join(TOKEN_RE.findall(text.lower()))


def token_recall(needle: str, haystack: str) -> float:
    wanted = set(TOKEN_RE.findall(needle.lower()))
    present = set(TOKEN_RE.findall(haystack.lower()))
    return len(wanted & present) / len(wanted) if wanted else 0.0


rows = []
for filename in sorted(glob.glob(str(
        ROOT / "data/outputs/aus_agent_v2/*.output.json"))):
    obj = json.loads(Path(filename).read_text())
    if obj.get("metadata", {}).get("run_id") != RUN_ID:
        continue
    if obj.get("trace", {}).get("status") != "completed":
        continue
    qid = obj["metadata"]["narrative_id"]
    answer = " ".join(item["text"] for item in obj["answer"])
    packet = next(
        str(step.get("output") or "")
        for step in obj["trace"]["steps"]
        if step.get("tool_name") == "prepare_answer"
    )
    claims = CLAIM_RE.findall(packet)
    facts = []
    if FACT_MARKER in packet:
        tail = packet.split(FACT_MARKER, 1)[1]
        fact_obj, _ = json.JSONDecoder().raw_decode(tail)
        facts = [fact for cards in fact_obj.values() for fact in cards]
    claim_exact = sum(normalized(claim) in normalized(answer) for claim in claims)
    claim_lexical = sum(token_recall(claim, answer) >= 0.60 for claim in claims)
    fact_exact = sum(
        normalized(fact["value"]) in normalized(answer) for fact in facts)
    fact_lexical = sum(
        token_recall(fact["value"], answer) >= 0.60 for fact in facts)
    numeric = [fact for fact in facts if re.search(r"\d", fact["value"])]
    numeric_used = sum(
        set(re.findall(r"\d[\d.,:/%-]*", fact["value"]))
        <= set(re.findall(r"\d[\d.,:/%-]*", answer))
        for fact in numeric
    )
    summary = obj["trace"]["summary"]["answer_blueprint"]
    rows.append({
        "qid": qid,
        "words": len(answer.split()),
        "requirements": summary["requirements"],
        "claims": len(claims),
        "claim_exact": claim_exact,
        "claim_lexical_60": claim_lexical,
        "mapped_fact_cards": len(facts),
        "fact_value_exact": fact_exact,
        "fact_value_lexical_60": fact_lexical,
        "numeric_facts": len(numeric),
        "numeric_values_used": numeric_used,
        "handoff_chars": summary["handoff_chars"],
    })

print("\t".join(rows[0]) if rows else "no completed outputs")
for row in rows:
    print("\t".join(str(value) for value in row.values()))
if rows:
    totals = {
        key: sum(row[key] for row in rows)
        for key in (
            "claims", "claim_exact", "claim_lexical_60",
            "mapped_fact_cards", "fact_value_exact", "fact_value_lexical_60",
            "numeric_facts", "numeric_values_used",
        )
    }
    print("\nTOTALS " + json.dumps(totals, sort_keys=True))
    print(
        "RATES "
        f"claims_exact={totals['claim_exact']/totals['claims']:.3f} "
        f"claims_lexical60={totals['claim_lexical_60']/totals['claims']:.3f} "
        f"facts_exact={totals['fact_value_exact']/totals['mapped_fact_cards']:.3f} "
        f"facts_lexical60={totals['fact_value_lexical_60']/totals['mapped_fact_cards']:.3f} "
        f"numeric_used={totals['numeric_values_used']/max(1, totals['numeric_facts']):.3f}"
    )
