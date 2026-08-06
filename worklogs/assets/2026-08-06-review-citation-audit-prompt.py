import os, json
from openai import OpenAI

for raw in open(".env"):
    line = raw.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
if "OPENAI_API_KEY" not in os.environ and "AZURE_OPENAI_API_KEY" in os.environ:
    os.environ["OPENAI_API_KEY"] = os.environ["AZURE_OPENAI_API_KEY"]

client = OpenAI(base_url=os.environ["OPENAI_BASE_URL"], api_key=os.environ["OPENAI_API_KEY"], timeout=180)

DRAFT_PROMPT = open("/private/tmp/claude-501/-Users-e103037-repos-trec-rag-26/11f55252-b0e1-4b10-855a-99a893005e83/scratchpad/citation_audit_draft.txt").read()

FINDINGS = """
CONTEXT: facets_agent is a RAG research agent (TREC RAG track) with a "two-tier" retrieval mode:
search returns short LLM-generated previews (not full text, not citable); a separate tool,
get_documents(ids), fetches full text for specific ids and is the ONLY path to citable evidence.
commit_context then keeps/drops fetched documents as committed evidence. The final report is
plain prose, one sentence per line, each factual sentence ending with [docid] citation markers
(max 3 ids/sentence) for committed evidence only.

We measured citation SUPPORT quality (does the cited source actually back the specific claim,
judged by a separate LLM support-judge on a full/partial/no-support 3-way scale) across several
configurations on 5 diagnostic topics:

  aus_agent (sibling system, much longer/more-tuned prompt): 38.7% full-support, using only
    9.6 searches/topic and seeing 60 documents/topic on average.
  facets_agent DEFAULT (full text staged directly from search, no two-tier): 23.6% full-support,
    19.0 searches/topic, 170 documents/topic.
  facets_agent TWO-TIER (current, after two prior fix rounds -- whitespace/word-boundary-aware
    truncation, then LLM-generated query-relevant previews using the FULL original request, not
    just the narrow sub-requirement): 12.5% full-support, 20.2 searches/topic, 172 documents/topic.

Key point: MORE retrieval volume is not the lever -- aus_agent gets the best result with 1/3 the
search volume of either facets_agent configuration. The citation-support gap must be about
DECISION QUALITY at commit/citation time, not about how much material was gathered.

We sampled the actual FAILING citations (support-judge labeled "no support") from the two-tier
run and found two recurring, concrete failure patterns:

PATTERN 1 -- right general topic, wrong specific page/fact:
  STATEMENT: "Assign a cookie held i seats from the target weight 2^-|i|."
  CITED DOCUMENT (truncated): "Page 74 of document: About the Author Pranav Sriram graduated
    from high school... 6. COUNTING IN TWO WAYS Introduction Several combinatorics problems ask
    us to count something..."
  The document IS a combinatorics text and the general subject (counting techniques) is right,
  but this specific formula/weight-assignment scheme is not what that page states.

  STATEMENT: "Case study five should examine Apple's use of LSTMs in QuickType predictive text."
  CITED DOCUMENT (truncated): "Page 2 of document: The Long Short-Term Memory (LSTM) cell can
    process data sequentially... 2015: Google started using an LSTM for speech recognition on
    Google Voice... cut transcription errors by 49%..."
  Cited document is about GOOGLE's LSTM use, not Apple/QuickType at all -- a topically-adjacent
  but factually wrong citation.

PATTERN 2 -- the model's own recommendation/synthesis is given a citation as if it were a sourced fact:
  STATEMENT: "Verify the publication status of industry articles and historical summaries before
    citing them as scholarship, using them for deployment history only when a peer-reviewed or
    primary source is unavailable."
  CITED DOCUMENT (truncated): "...the Institute for Electronic and Electrical Engineers (IEEE)
    has taken the lead in developing guidelines and standards. IEEE's Global Initiative is
    designed to ensure every technologist is educated..."
  This is the MODEL's own methodological advice to the reader -- the cited IEEE document never
  says anything like this.

  STATEMENT: "Twenty users for two weeks is reasonable for an exploratory usability and
    feasibility pilot, but it is too small and short to establish clinical effectiveness, so
    report confidence intervals, safety issues..."
  CITED DOCUMENT (truncated): a paper ABSTRACT about a mobile mood-monitoring study -- the
  abstract never makes this specific methodological judgment about sample-size adequacy.
  This again reads as the model's own evaluative judgment, not a fact from the source.

facets_agent's BASE system prompt already has a rule that "a sentence that organizes or connects
what earlier cited sentences already established -- a topic sentence, a transition, a conclusion
drawn from cited material -- may omit ids, and such a sentence must never introduce something
new." Pattern 2 suggests the model is NOT applying this carve-out to recommendation/heuristic-
style sentences, and is instead attaching a citation out of habit.

A prior fix round already added a citation re-verification instruction ("before writing each
cited sentence, re-read the committed get_documents text... confirm it states the SPECIFIC fact...")
which helped some (full-support went from 7.9% to 12.5%, arena result improved from a loss to a
tie with aus_agent) but clearly did not fully close the gap -- both patterns above are still
present in significant numbers (104 of 192 citations were "no support" before this round; even
the BEST-performing topic in the sample still had 35% no-support citations).

THE TASK NOW: the user wants us to go further than re-verify-and-narrow-or-drop. Specifically:
(a) explicitly ask the agent to self-identify these two failure patterns in its own draft, and
(b) when it finds one, actually GO BACK AND SEARCH MORE (new search queries, different engines,
    or get_documents on adjacent pages) to find better evidence that actually supports the claim
    -- not just narrow the sentence or drop the citation as a fallback.

This instruction is delivered via the harness's existing "pre_final_hook" mechanism: it fires
ONCE, as a plain-text user message injected right before a valid draft report would otherwise be
accepted, and the model's next turn can freely make new tool calls (search/get_documents/
commit_context) before attempting the report again -- so "another retrieval cycle" is already
mechanically possible, no new tooling is needed, only the prompt/instruction text matters.

Constraints: this fires only ONCE per run (a structural safety limit against infinite loops), so
the instruction has to get real mileage out of a single shot. It's injected as a user message in
an ongoing tool-calling conversation, not a system prompt -- so it should read as a direct,
actionable instruction, not a rules document.
"""

REVIEW_REQUEST = f"""{FINDINGS}

DRAFT INSTRUCTION TO REVIEW (this is what gets injected as the one-shot user message):
---
{DRAFT_PROMPT}
---

Please critically review this draft instruction and improve it. Specifically assess: does it
clearly ask the model to self-identify BOTH failure patterns (not just pattern 1)? Does it make
"search for better evidence" the clearly preferred first response rather than an equal option
alongside narrowing/dropping? Is the {{ids_list}} placeholder usage going to be clear to the
model (it will be a comma-separated list of the docids cited in the draft)? Is anything
ambiguous, too long, too vague, or missing given the concrete failure examples above? Would a
smaller/cheaper model correctly follow this in one shot?

If you need more information about the codebase, the harness, the exact prompt this gets
appended to, or anything else to give a good answer, ask -- I can provide it. Otherwise, give me
your critique followed by a complete, ready-to-use REVISED version of the instruction text
(keep the {{ids_list}} placeholder)."""

resp = client.chat.completions.create(model="gpt-5.6-sol", messages=[{"role": "user", "content": REVIEW_REQUEST}])
text = resp.choices[0].message.content
print(text)
open("/private/tmp/claude-501/-Users-e103037-repos-trec-rag-26/11f55252-b0e1-4b10-855a-99a893005e83/scratchpad/sol_review_round1.txt", "w").write(text)
