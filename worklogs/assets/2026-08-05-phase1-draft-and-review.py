#!/usr/bin/env python3
"""Draft (gpt-5.6-luna) + review (gpt-5.6-terra) facets_agent's Phase-1
prompt rewrite, per src/systems/facets_agent/PLAN.md section 1.3. Tracks
token usage/cost against the user's $10 cap.
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

PLAN_EXCERPT = r"""
**Opening paragraph — replace the prior-knowledge line.** Today: "Prior knowledge may shape how you search and read, but it must never support a factual claim in your answer." Proposed:

> Prior knowledge is your best source of QUERIES and never a source of CLAIMS. If you already know names, works, people, events, techniques, or products that a requirement probably involves, search for them by name — do not wait for the corpus to volunteer them, and do not confine your queries to the request's own vocabulary. What you know decides what you look for; only what you commit decides what you may assert. When the corpus turns out not to hold something you were confident about, that is a finding about the corpus, not a licence to assert it anyway.

**Step 1 — replace.** Today: "Decompose the request into a small set of independent facets…". Proposed:

> 1. Before searching, list every requirement the request states — each explicit instruction and each one it implies (a named comparison, a stated audience or scope, a demanded structure, a concrete deliverable). Take them one at a time, in the request's own words. Then group them into facets: distinct sub-questions that each need their own evidence, where every requirement on your list belongs to a facet. A requirement no facet covers gets no searches and will be missing from your answer. A narrow question may be one requirement and one facet; a multi-part request usually has many of both. Work the facets as separate research tasks: search, curate, and judge coverage one facet at a time.

**Step 2 — append the named-candidates clause** (goes after the existing step-2 text about engines/HyDE, as a new sentence or two within step 2, not a new numbered step):

> When a requirement asks for concrete specifics — named partners, products, tools, techniques, works, people, events — write one query naming your own best candidates and one query for the category around them, so the corpus can both test the candidates you brought and offer ones you did not think of. `keyword` is the engine for a named candidate; `semantic` or `hybrid` for the category. A candidate you supplied is a hypothesis to test, not a finding: the query is where it belongs, the report is not.

**Step 3 — trim.** The release mechanic is currently explained at length in the prompt (the whole existing step 3 paragraph) *and* verbatim again in `tools.py`'s schema. Cut the prompt paragraph down to just the judgment call ("when two results cover the same point, keep the better one; when a newly committed result makes an already-committed one redundant, release the older one") and drop the mechanical/detailed explanation of HOW release works (that lives in the tool schema description already). Keep the "minimal evidence" framing and the "actively look for counter-evidence" sentence — those are not the mechanical part.

**Step 4 — rewrite for a checkable stop condition.** Today: "Keep searching a facet until it is genuinely covered by what you've committed, or further search on it stops helping — then move to the next facet, or to the report once every facet is resolved that way." Proposed:

> 4. A facet is done when every requirement in it is covered by what you've committed, or you've searched hard enough on more than one engine to conclude the corpus doesn't have it. Do not search again for a requirement that already has its evidence — spend that call on one that has none. Write the report only when no requirement is left unresolved.

(Note: the plan's original phase-2 wording uses formal "ledger"/`covered`/`open`/`unavailable` status words tied to a tool schema field that does NOT exist yet in phase 1 — there is no `coverage` argument on `commit_context` in phase 1, only prompt text. Adapt this instruction so it reads as a self-tracked mental discipline the model follows in its own reasoning, not as a reference to a structured field it doesn't have. Avoid the word "ledger" unless you make clear it means an informal, self-maintained tracking habit, not a tool argument.)

**Step 5 — extend the existing self-check.** Today: "Before you write the final report, re-check your own citations: for each committed result you plan to cite, confirm it actually and specifically supports the claim you're attaching it to, not just the same general topic. Drop or fix any citation that doesn't hold up." Proposed addition (prepend a coverage check, append an expectation check, to the existing citation check):

> Before you write the report, review what you set out to cover: every requirement you identified, and whether you have committed evidence for it. If one is still unresolved and the corpus hasn't been properly asked, run one more targeted search for exactly that, then finish. Where a query came from something you already knew rather than something the corpus had already shown you, check that the committed document actually says what you're attributing to it — not what you expected it to say — and that anything you expected but never found is either left out of the report or named as something the corpus doesn't cover.

**Final-report paragraph — two appends** (added to the existing final paragraph about writing the report):

Structure-is-a-requirement:
> When the request names a shape — a section per item, an ordered plan to act on, a notation, a stated audience — the report must literally take that shape, not merely cover the content it asked about; the shape is a requirement like any other.

Citation discipline aimed at the uncited-sentence channel:
> Every sentence that states a fact, a name, a number, an event, or a mechanism ends with its committed ids. The only sentences without ids are ones that organise or connect what the cited sentences already established — a heading-like topic sentence, a transition, a conclusion drawn from cited material. A sentence with no ids may never introduce something new.

**Line budget target: keep the total prompt content (the SYSTEM_PROMPT string body, not the module docstring) to roughly 80-84 lines** at the current line-wrapping style (backslash-continued paragraphs wrapped around 78-80 chars, matching the existing file's style exactly). The current prompt body is 62 lines. Do NOT add headers, bullet points, or restructure into a different visual format — match the existing plain-paragraph-with-backslash-continuations style exactly, same numbered-list-within-prose structure.

**Also needed: an updated module docstring** (the triple-quoted comment above SYSTEM_PROMPT, currently lines 1-28) that adds a clearly marked paragraph explaining the deliberate divergence from aus_agent's stricter "do not seed queries with candidate answers the corpus hasn't surfaced" rule (aus_agent's rule lives in `src/systems/aus_agent/prompts/system/default.md` around lines 72-80) -- state that this is a deliberate choice, not an oversight, with a one-paragraph justification: facets_agent's measured failure mode is false negatives (missed requirements/named entities), not false positives (invented facts) -- aus_agent's rule is a precision instrument aimed at a problem facets_agent doesn't have, while facets_agent's problem is recall. The safety net stays mechanical (uncommitted docids are stripped from the final answer regardless of prompt wording) plus the prompt's own repeated "query yes, claim no" discipline. Also state the ~80-line soft cap on the prompt body as a design constraint for future edits.
"""

SYSTEM_DRAFT = (
    "You are a precise technical prose editor working on a production AI "
    "system prompt for a research agent. You will be given the CURRENT "
    "prompts.py file (a Python module: a module docstring plus a "
    "SYSTEM_PROMPT string) and a detailed specification of edits to make. "
    "Produce the FULL NEW prompts.py file content (module docstring + "
    "SYSTEM_PROMPT string, in the same Python module format, with the same "
    "backslash-continuation prose-wrapping style as the original -- do not "
    "change the file's formatting conventions). Integrate every specified "
    "change so the result reads as one coherent, well-written document in "
    "the same voice as the original, not a mechanical concatenation of "
    "patches. Follow the specification's exact wording closely where it "
    "gives exact wording; use your own judgment only for connective "
    "tissue and formatting. Output ONLY the raw Python file content, no "
    "commentary, no code fences.")

USER_DRAFT = f"""CURRENT prompts.py:
```python
{CURRENT_PROMPT}
```

EDIT SPECIFICATION (from src/systems/facets_agent/PLAN.md, Phase 1 -- prompt-only changes):
{PLAN_EXCERPT}

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
    open(f"{SCRATCH}/draft_v1.py", "w").write(draft)
    est = total_in/1e6*EST_RATE_IN_PER_1M + total_out/1e6*EST_RATE_OUT_PER_1M
    print(f"draft: {len(draft.splitlines())} lines, tokens in={total_in} out={total_out}, est cost so far ${est:.4f}")

    print("\n=== REVIEW (gpt-5.6-terra) ===")
    system_review = (
        "You are a strict reviewer checking whether a rewritten AI system "
        "prompt file correctly and completely implements a written "
        "specification. You will be given the specification and the "
        "drafted file. Check EVERY numbered/bulleted item in the "
        "specification against the draft. Return STRICT JSON only: "
        '{"missing_or_wrong": [{"item": "<which spec item>", "issue": '
        '"<what is missing/wrong/garbled>"}], "line_count_ok": <bool, is '
        "the SYSTEM_PROMPT body roughly 80-84 lines and not restructured "
        'into a different format>, "voice_consistent": <bool, does it read '
        "as one coherent document in the original's plain-prose voice, not "
        'a patchwork>, "other_concerns": ["..."], "overall_verdict": '
        '"<one of: ship_as_is, minor_fixes_needed, redo>"}')
    user_review = f"""SPECIFICATION:
{PLAN_EXCERPT}

DRAFTED FILE:
```python
{draft}
```

Check the draft against the specification now."""
    review_resp = api.chat.completions.create(
        model="gpt-5.6-terra", response_format={"type": "json_object"},
        messages=[{"role": "system", "content": system_review},
                  {"role": "user", "content": user_review}])
    review = review_resp.choices[0].message.content
    total_in += review_resp.usage.prompt_tokens
    total_out += review_resp.usage.completion_tokens
    open(f"{SCRATCH}/review_v1.json", "w").write(review)
    est = total_in/1e6*EST_RATE_IN_PER_1M + total_out/1e6*EST_RATE_OUT_PER_1M
    print(f"review tokens in={total_in} out={total_out}, TOTAL est cost so far ${est:.4f}")
    print(review)


if __name__ == "__main__":
    main()
