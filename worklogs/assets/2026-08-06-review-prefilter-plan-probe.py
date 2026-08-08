import os
from openai import OpenAI

for raw in open(".env"):
    line = raw.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
if "OPENAI_API_KEY" not in os.environ and "AZURE_OPENAI_API_KEY" in os.environ:
    os.environ["OPENAI_API_KEY"] = os.environ["AZURE_OPENAI_API_KEY"]

client = OpenAI(base_url=os.environ["OPENAI_BASE_URL"], api_key=os.environ["OPENAI_API_KEY"], timeout=180)

plan = open("/private/tmp/claude-501/-Users-e103037-repos-trec-rag-26/11f55252-b0e1-4b10-855a-99a893005e83/scratchpad/prefilter-plan-draft.md").read()

PROMPT = f"""You are reviewing an engineering plan for a RAG research-agent codebase (TREC RAG track). Be a critical, skeptical reviewer -- your job is to find real flaws, risky assumptions, missing considerations, or better alternatives, not to validate the plan. Do not be diplomatic filler; be direct and specific, referencing the plan's own section numbers.

Context you need: this repo runs two RAG agents, aus_agent and facets_agent, sharing a tool-calling harness. facets_agent was measured to retrieve ~2x more documents/context than aus_agent but scores LOWER on rubric grading, with no per-topic correlation between context volume and grade (i.e. NOT a clean "too much context confuses the model" story). A prior finding (cited in the plan's §1) established facets_agent's actual failure mode is under-decomposition and under-specific answers, and that facets_agent was deliberately given MORE retrieval freedom than its sibling system aus_agent specifically because facets_agent's problem is RECALL (missing things), not precision (asserting wrong things) -- so a new filter that could suppress recall is a real regression risk, not a hypothetical one.

PLAN TO REVIEW:
---
{plan}
---

Give your review as a numbered list of concrete issues/risks/questions, each 1-3 sentences, ordered most-important first. Cover at minimum: (1) whether the conservative "keep adjacent_not_relevant" design choice in §2.2 actually protects recall or is still risky, (2) whether the validation plan in §3 is sufficient to catch a recall regression before it ships, (3) any assumption in the plan that isn't actually justified by the grounding data in §0, (4) implementation/engineering risks not addressed, (5) whether there's a simpler or fundamentally different approach that better fits what §0's data actually showed (wasted effort budget, not context dilution). End with a one-line verdict: proceed as-is / proceed with changes / reconsider entirely."""

resp = client.chat.completions.create(model="gpt-5.6-terra", messages=[{"role": "user", "content": PROMPT}])
text = resp.choices[0].message.content
print(text)
open("/private/tmp/claude-501/-Users-e103037-repos-trec-rag-26/11f55252-b0e1-4b10-855a-99a893005e83/scratchpad/terra_review.txt", "w").write(text)
