"""Live request-only probe for the archetype-expanded blind coverage scout."""
from __future__ import annotations

import json
from pathlib import Path

from aus_agent_v2.agent import make_provider
from aus_agent_v2.plan_critic import (
    PLAN_CRITIC_SYSTEM,
    normalize_plan_critique,
    plan_critic_request,
)


TOPICS = Path("data/task-comparison/topics-aus-v2-probe6.tsv")
SKIP_QID = "6847465956a0f6376a605493"  # Markov scored 1.0 in confirmation.
MODEL = "openai.gpt-5.6-sol"


def main() -> None:
    """Persist exact packets and raw responses for all five non-ceiling topics."""
    for line in TOPICS.read_text(encoding="utf-8").splitlines():
        qid, query = line.split("\t", 1)
        if qid == SKIP_QID:
            continue
        request = plan_critic_request(query)
        provider = make_provider("openai", MODEL)
        provider.start(PLAN_CRITIC_SYSTEM, [])
        provider.add_user_message(request)
        turn = provider.run_turn()
        print(json.dumps({
            "qid": qid,
            "query": query,
            "system": PLAN_CRITIC_SYSTEM,
            "request": request,
            "raw": turn.get("text"),
            "normalized": normalize_plan_critique(turn.get("text")),
            "usage": turn.get("usage"),
        }, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
