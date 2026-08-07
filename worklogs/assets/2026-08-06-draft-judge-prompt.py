import os, json
from openai import OpenAI

for raw in open(".env"):
    line = raw.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
if "OPENAI_API_KEY" not in os.environ and "AZURE_OPENAI_API_KEY" in os.environ:
    os.environ["OPENAI_API_KEY"] = os.environ["AZURE_OPENAI_API_KEY"]

client = OpenAI(base_url=os.environ["OPENAI_BASE_URL"], api_key=os.environ["OPENAI_API_KEY"], timeout=120)

CURRENT_PROMPT = '''You are a strict relevance judge. Given a REQUIREMENT and a set of DOCUMENTS, decide for EACH document whether it actually states or supports what the requirement needs (relevant), is only topically adjacent -- about the same general subject but not the specific thing asked for (adjacent_not_relevant), or is unrelated (irrelevant). If NONE are relevant, also suggest ONE concrete query reformulation likely to do better: a narrower phrase, a named entity to add, or which engine to prefer (keyword for exact names/ids, semantic for concepts). Return STRICT JSON only, no other text: {"verdicts": [{"id": "<id>", "verdict": "relevant|adjacent_not_relevant|irrelevant", "reason": "<short reason>"}, ...], "suggested_reformulation": "<string, or null if any document is relevant>"}'''

META = f'''You are a prompt engineer. I run a relevance-judging tool with openai.gpt-oss-120b-1:0 (a smaller open-weight model served on AWS Bedrock's Converse API, NOT GPT-4-class) as a secondary judge inside a RAG research agent.

TASK the judge model performs, one call at a time:
- Input: a REQUIREMENT (a specific sub-question/need from a research request, e.g. "the specific real-time message delivery mechanism recommended") and a batch of DOCUMENTS (short passages, each with an id).
- Output: for EACH document, a 3-way verdict:
  - relevant: the document actually states/supports what the requirement needs
  - adjacent_not_relevant: same general topic, but doesn't state the specific thing the requirement asks for (the main failure mode we're hunting: "similar but not relevant" -- e.g. requirement asks about a NAMED company's role in a game's development, document is general game-development history that never names the company)
  - irrelevant: unrelated
  - a short one-line reason per verdict
- If NONE of the documents are relevant, also produce ONE concrete, actionable query reformulation suggestion (a narrower phrase, a named entity to add, or which search engine to prefer -- "keyword" for exact names/ids vs "semantic" for concepts).
- Output must be STRICT JSON only (the caller parses it programmatically), matching this exact schema:
  {{"verdicts": [{{"id": "<id>", "verdict": "relevant|adjacent_not_relevant|irrelevant", "reason": "<short reason>"}}, ...], "suggested_reformulation": "<string, or null if any document is relevant>"}}

My CURRENT prompt (may not be well-tuned for a smaller open-weight model -- possibly needs to be more explicit/structured, since smaller models often need more scaffolding than GPT-4-class ones, e.g. numbered steps, an explicit definition of each category with a worked example, explicit "no markdown, no code fences" reminder):

"""
{CURRENT_PROMPT}
"""

Give me an IMPROVED system prompt for openai.gpt-oss-120b-1:0 specifically, optimized for: (1) reliably distinguishing "adjacent but not relevant" from "relevant" -- this is the hardest category and the whole point of the tool, (2) reliable strict-JSON output with no markdown fences or extra prose, (3) staying concise since this runs on every doubtful batch and token cost matters. You may restructure entirely (e.g. add category definitions with a short example, add explicit anti-patterns like "do not use markdown", ask for the JSON on its own without any preamble). Output ONLY the new system prompt text, nothing else -- no explanation, no meta-commentary, ready to paste directly into code as a Python string.'''

resp = client.chat.completions.create(model="gpt-5.6-luna", messages=[{"role": "user", "content": META}])
text = resp.choices[0].message.content
print(text)
open("/private/tmp/claude-501/-Users-e103037-repos-trec-rag-26/11f55252-b0e1-4b10-855a-99a893005e83/scratchpad/drafted_judge_prompt.txt", "w").write(text)
