#!/usr/bin/env python3
"""Revision pass: tighten draft_v1.py to the ~80-84 line target, then
re-review with the ORIGINAL file included so the reviewer doesn't flag
pre-existing structure (the "Tools:" section) as new bloat.
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


ORIGINAL = open(f"{ROOT}/src/systems/facets_agent/prompts.py", encoding="utf-8").read()
DRAFT_V1 = open(f"{SCRATCH}/draft_v1.py", encoding="utf-8").read()

SYSTEM_REVISE = (
    "You are a precise technical prose editor tightening a draft AI system "
    "prompt file. You will be given a draft that is too long. Cut it to "
    "the target line count by removing redundancy and tightening phrasing "
    "-- NOT by deleting substantive content. Every distinct instruction, "
    "safeguard, and check in the draft must survive in some form. Preferred "
    "cuts: merge sentences that restate the same point, drop qualifying "
    "clauses that repeat what an earlier sentence already established, "
    "shorten examples. Output ONLY the raw Python file content, no "
    "commentary, no code fences.")

USER_REVISE = f"""DRAFT (too long -- the SYSTEM_PROMPT string body is ~95 lines,
counting from the opening triple-quote to the closing one; target is 80-84 lines,
matching this file's existing line-wrapping style, around 78-80 chars/line):

```python
{DRAFT_V1}
```

Specific targets, in priority order:
1. Step 4 (starts "A facet is done when every requirement...") is verbose.
   Tighten it -- keep the checkable stop condition, keep SOME notion of
   tracking requirement status informally, but say it in fewer words.
2. Step 5 (starts "Before you write the report, review what you set out to
   cover...") does three jobs (coverage check, citation check, expectation
   check) in one long block. Tighten without dropping any of the three
   checks.
3. The final paragraph (after "When every facet is resolved...") can also be
   trimmed slightly if needed, but the two appended requirements (structure-
   is-a-requirement, and "every fact-bearing sentence ends with ids / a
   sentence with no ids may never introduce something new") must both survive
   clearly.
4. Do NOT touch the "Tools:" section (the `search`/`get_documents`/
   `commit_context` bullet list) -- it is unchanged from the pre-existing
   file and correctly so; leave it exactly as-is.
5. Do NOT touch the module docstring (the text before the SYSTEM_PROMPT
   assignment) unless it also needs trimming to stay proportionate -- it's
   currently reasonable, leave it unless you see an obvious redundancy.

Produce the tightened full file now."""


def main():
    load_env()
    api = client()
    total_in = total_out = 0

    print("=== REVISE (gpt-5.6-luna) ===")
    resp = api.chat.completions.create(
        model="gpt-5.6-luna",
        messages=[{"role": "system", "content": SYSTEM_REVISE},
                  {"role": "user", "content": USER_REVISE}])
    revised = resp.choices[0].message.content
    total_in += resp.usage.prompt_tokens
    total_out += resp.usage.completion_tokens
    open(f"{SCRATCH}/draft_v2.py", "w").write(revised)
    body_lines = revised.split('SYSTEM_PROMPT = """\\')[1].count("\n") if 'SYSTEM_PROMPT = """\\' in revised else -1
    est = total_in/1e6*EST_RATE_IN_PER_1M + total_out/1e6*EST_RATE_OUT_PER_1M
    print(f"revised: {len(revised.splitlines())} total lines, tokens in={total_in} out={total_out}, est cost so far ${est:.4f}")

    print("\n=== RE-REVIEW (gpt-5.6-terra), now with ORIGINAL file for contrast ===")
    system_review = (
        "You are a strict reviewer checking whether a rewritten AI system "
        "prompt file correctly and completely implements a written "
        "specification, starting from a given ORIGINAL file. You will be "
        "given the ORIGINAL file, the specification of changes, and the "
        "REVISED file. Check EVERY item in the specification against the "
        "revised file. Do NOT flag anything present unchanged in the "
        "ORIGINAL file (e.g. the 'Tools:' bullet list) as a new problem -- "
        "only flag things the SPECIFICATION asked for that are missing, "
        "wrong, or garbled in the revised file, or genuine new problems the "
        "revision introduced. Return STRICT JSON only: "
        '{"missing_or_wrong": [{"item": "<spec item>", "issue": "<issue>"}], '
        '"line_count_ok": <bool: is the SYSTEM_PROMPT body roughly 78-86 '
        'lines>, "actual_body_line_count": <int>, "voice_consistent": '
        '<bool>, "content_preserved_from_v1": <bool: did the tightening '
        'accidentally drop any of the 3 checks in step 5, or the stop '
        'condition in step 4>, "other_concerns": ["..."], '
        '"overall_verdict": "<one of: ship_as_is, minor_fixes_needed, redo>"}')
    plan_spec = open(f"{SCRATCH}/draft_and_review_prompt.py", encoding="utf-8").read()
    plan_spec = plan_spec.split('PLAN_EXCERPT = r"""')[1].split('"""')[0]
    user_review = f"""ORIGINAL file (before any changes):
```python
{ORIGINAL}
```

SPECIFICATION:
{plan_spec}

REVISED file (after draft + tightening pass):
```python
{revised}
```

Check the revised file against the specification now, using the original only for contrast (to avoid flagging pre-existing content)."""
    review_resp = api.chat.completions.create(
        model="gpt-5.6-terra", response_format={"type": "json_object"},
        messages=[{"role": "system", "content": system_review},
                  {"role": "user", "content": user_review}])
    review = review_resp.choices[0].message.content
    total_in += review_resp.usage.prompt_tokens
    total_out += review_resp.usage.completion_tokens
    open(f"{SCRATCH}/review_v2.json", "w").write(review)
    est = total_in/1e6*EST_RATE_IN_PER_1M + total_out/1e6*EST_RATE_OUT_PER_1M
    print(f"TOTAL est cost so far (all calls this run + previous) tracked separately -- this call's tokens in={total_in} out={total_out}, est ${est:.4f}")
    print(review)


if __name__ == "__main__":
    main()
