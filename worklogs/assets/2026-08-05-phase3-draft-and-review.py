#!/usr/bin/env python3
"""Draft (gpt-5.6-luna) + review (gpt-5.6-terra) facets_agent's Phase-3
prompt fix: a minimal step-1 addition so single-sentence multi-item
requests (e.g. "compare UBI pilots in Finland, Ontario, and the US...")
get split into one requirement per item instead of one bundled requirement
that closes out early. Diagnosed in
worklogs/2026-08-05-facets-agent-phase2-implementation-and-smoke-test.md's
6054a7 finding. Tracks token usage/cost against the user's $5 cap.
"""
from __future__ import annotations

import os

ROOT = "/home/el7/E103037/repos/trec-rag-26"
SCRATCH = "/tmp/claude-200103037/-home-el7-E103037-repos-trec-rag-26/6eb02a90-5386-45ae-a290-a6bd7b4f00df/scratchpad"
EST_RATE_IN_PER_1M = 3.0
EST_RATE_OUT_PER_1M = 12.0


def load_env():
    for raw in open(f"{ROOT}/.env", encoding="utf-8").read().splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    if "OPENAI_API_KEY" not in os.environ and "AZURE_OPENAI_API_KEY" in os.environ:
        os.environ["OPENAI_API_KEY"] = os.environ["AZURE_OPENAI_API_KEY"]


def client():
    from openai import OpenAI
    return OpenAI(base_url=os.environ["OPENAI_BASE_URL"],
                  api_key=os.environ["OPENAI_API_KEY"], timeout=180.0, max_retries=4)


CURRENT_PROMPT = open(f"{ROOT}/src/systems/facets_agent/prompts.py", encoding="utf-8").read()

DIAGNOSIS = """
DIAGNOSED FAILURE (from a real smoke-test run, topic 6054a7 -- "Compare the
effectiveness and potential long-term consequences of Universal Basic Income
(UBI) pilots in various countries (e.g., Finland, Ontario, US)... using data
from peer-reviewed economic studies... policy analysis and commentary from
experts published post-2015"):

The model's own step-1 requirement list collapsed the whole multi-country
comparison into ONE requirement ("Compare the effectiveness and potential
long-term consequences of Universal Basic Income (UBI) pilots..." -- the
entire sentence, verbatim) instead of splitting it into one requirement per
named comparandum (Finland pilot, Ontario pilot, US/Stockton pilot). Because
the coverage ledger is keyed to the model's own step-1 list, and that list
only had 4 coarse entries, the model marked the bundled requirement
"covered" once it had SOME evidence touching some of the countries, and
never separately checked itself against each country's own eligibility
criteria, employment effects, or political-feasibility angle. The final
answer is factually dense and well-cited but never covers Ontario pilot
eligibility criteria or political feasibility specifically -- not because
the corpus lacks it or the model didn't search enough overall (18 searches
ran), but because nothing in the model's own requirement list ever named
those as separate things to check off.

This is a general failure mode, not specific to UBI: any request that names
or implies a LIST of comparanda in one sentence (multiple countries,
sources, products, examples, time periods, criteria) rather than as an
explicit numbered list is at risk of being enumerated as a single bundled
requirement in step 1, which then lets the coverage ledger close out early
against only the union of whatever the searches happened to surface, rather
than checking each named item on its own.
"""

TASK_SPEC = """
TASK: propose the SMALLEST possible edit to step 1 of SYSTEM_PROMPT (and
ONLY step 1 -- do not touch any other step, the opening paragraph, the
Tools section, or the final-report paragraph) that fixes the diagnosed
failure mode above. The fix must be a general instruction (do not mention
UBI, Finland, Ontario, or any topic-specific example) telling the model:
when a requirement names or implies more than one item to cover -- several
countries, sources, categories, examples, or comparison points bundled into
one sentence -- split it into one requirement per item, not one requirement
covering all of them, because a single bundled requirement can get marked
covered from partial evidence and never get checked item by item.

Constraints:
- Add ONLY 1-2 sentences to step 1 (insert them at the most natural point in
  the existing step-1 paragraph; do not restructure step 1's existing
  sentences or reorder them beyond what the insertion requires).
- Do not add a new numbered step.
- Do not change word count of any OTHER step or paragraph in the file.
- Match the file's existing plain-paragraph, backslash-continued prose
  style exactly (no bullets, no headers).
- The full SYSTEM_PROMPT body should grow by no more than ~4 lines from its
  current length once re-wrapped at the file's existing line width.
- Also add a short (3-5 sentence) paragraph to the MODULE DOCSTRING (not the
  SYSTEM_PROMPT) explaining this is Phase 3 of PLAN.md, dated 2026-08-05,
  citing the diagnosis above in your own words, and noting explicitly why
  this is a prompt-only fix (the ledger's granularity is bounded by step 1's
  own enumeration; this raises that floor without any schema/harness
  change).

Output ONLY the full new prompts.py file content (module docstring +
SYSTEM_PROMPT string, same Python module format), no commentary, no code
fences.
"""

SYSTEM_DRAFT = (
    "You are a precise technical prose editor working on a production AI "
    "system prompt for a research agent. You make the SMALLEST edit that "
    "fixes a diagnosed problem -- you do not rewrite unrelated material, "
    "you do not take the opportunity to also improve unrelated wording, "
    "and you match the existing file's style and voice exactly. Output "
    "ONLY the raw Python file content, no commentary, no code fences.")

USER_DRAFT = f"""CURRENT prompts.py:
```python
{CURRENT_PROMPT}
```

{DIAGNOSIS}

{TASK_SPEC}

Produce the full new prompts.py file content now."""


def main():
    load_env()
    api = client()
    total_in = total_out = 0

    print("=== DRAFT (gpt-5.6-luna) ===")
    draft_resp = api.chat.completions.create(
        model="gpt-5.6-luna",
        messages=[{"role": "system", "content": SYSTEM_DRAFT},
                  {"role": "user", "content": USER_DRAFT}])
    draft = draft_resp.choices[0].message.content
    total_in += draft_resp.usage.prompt_tokens
    total_out += draft_resp.usage.completion_tokens
    open(f"{SCRATCH}/phase3_draft_v1.py", "w").write(draft)
    est = total_in/1e6*EST_RATE_IN_PER_1M + total_out/1e6*EST_RATE_OUT_PER_1M
    print(f"draft: {len(draft.splitlines())} lines, tokens in={total_in} out={total_out}, est cost so far ${est:.4f}")

    print("\n=== REVIEW (gpt-5.6-terra) ===")
    system_review = (
        "You are a strict reviewer checking whether a MINIMAL prompt edit "
        "correctly and completely implements a diagnosis + task spec, "
        "without scope creep. You will be given the diagnosis, the task "
        "spec, the ORIGINAL file, and the DRAFTED new file. Diff them "
        "mentally: check that step 1 changed as specified, that NOTHING "
        "else in SYSTEM_PROMPT changed (word-for-word identical outside "
        "step 1), that the module docstring gained the specified short "
        "paragraph and nothing else changed there either, and that the "
        "insertion is general (no topic-specific examples like UBI/"
        "Finland/Ontario). Return STRICT JSON only: "
        '{"step1_only_changed": <bool>, "other_steps_unchanged": <bool>, '
        '"docstring_addition_present_and_minimal": <bool>, '
        '"insertion_is_general_not_topic_specific": <bool>, '
        '"line_growth_acceptable": <bool, did SYSTEM_PROMPT body grow by '
        'no more than ~4 lines>, "issues": ["..."], "overall_verdict": '
        '"<one of: ship_as_is, minor_fixes_needed, redo>"}')
    user_review = f"""DIAGNOSIS:
{DIAGNOSIS}

TASK SPEC:
{TASK_SPEC}

ORIGINAL prompts.py:
```python
{CURRENT_PROMPT}
```

DRAFTED new prompts.py:
```python
{draft}
```

Check the draft now."""
    review_resp = api.chat.completions.create(
        model="gpt-5.6-terra", response_format={"type": "json_object"},
        messages=[{"role": "system", "content": system_review},
                  {"role": "user", "content": user_review}])
    review = review_resp.choices[0].message.content
    total_in += review_resp.usage.prompt_tokens
    total_out += review_resp.usage.completion_tokens
    open(f"{SCRATCH}/phase3_review_v1.json", "w").write(review)
    est = total_in/1e6*EST_RATE_IN_PER_1M + total_out/1e6*EST_RATE_OUT_PER_1M
    print(f"review tokens in={total_in} out={total_out}, TOTAL est cost so far ${est:.4f}")
    print(review)


if __name__ == "__main__":
    main()
