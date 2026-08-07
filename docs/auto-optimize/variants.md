# What each variant actually changes

Every arm is `default.md` plus **one** named patch, applied by anchored string
replacement (`tasks/task-comparison/scripts/build_prompt_variants.py`), except
`minimal`, which is a rewrite. Descriptions here are of the *behaviour asked
for*, not the wording — read the patch text for that.

Ordered by the size of the change they make to how the agent works.

---

## The two structural arms

**`default` — the control.** 15,910 bytes, 267 lines. Tells the agent how to
research in steps: form an internal success plan (end goal, minimum
requirements, excellence requirements, coverage areas), then loop
search → commit → decide, with rules for how to phrase round-one queries, how
to escalate to prior-knowledge probes when the corpus comes back empty, when to
reformulate, and when to stop. Roughly two-thirds of the file is procedure.

**`minimal` — a rewrite, not a patch.** 3,631 bytes, 43 lines: **77% smaller.**
Keeps only what the harness genuinely enforces — the staging protocol (results
vanish unless committed next turn), commit-before-report ordering, the citation
marker format, one-sentence-per-line, the 1,024-word cap, and the adjudication
rule for competing results. Everything procedural is deleted: no success plan,
no coverage areas, no query-formulation rules, no research loop, no stopping
heuristics. In their place, one instruction — *work out what a complete,
correct, genuinely useful answer would contain, find the evidence for it, and
write it.* This is the only arm that tests whether the prompt is
**over-prescriptive**; every other arm adds text.

---

## Arms that change how the agent searches

**`paired-lead`.** Today the two retrieval engines return almost entirely
different documents for the same need (93% disjoint), yet only ~4% of rounds
ever put both engines on the same lead — so nearly every lead has been judged on
roughly half its available evidence, with nothing signalling the other half
exists. This says a lead is not ready to judge until *both* engines have
answered it, with each query written in that engine's idiom (natural phrasing
for dense, bare distinctive terms for keyword). Fewer leads per round, each
covered properly. It is the only patch ever shown to move trajectory shape:
same-lead pairing 4% → 72%, engine mix 90:10 → 52:48.

**`decision-item`.** Adds a fifth item to the internal success plan: name the
decision the request exists to serve — someone has to decide, build, buy,
argue, or advise — and treat a fact that would change that decision as
belonging in the answer even when nothing in the request asked for it.

---

## Arms that change what gets carried out of the evidence

**`reading-a-result`.** Read a document for what it *states*, not what it is
*about*, and note the specific thing (figure, date, named study, mechanism)
at the moment you commit it. Motivated by the sharpest measured defect in the
project: **42–47% of the figures we omitted were sitting in documents we
ourselves cited.** The material was in hand and got dropped between reading and
writing.

**`finish-the-claim`.** Derived from the failure profile rather than a
hypothesis: 25.2% of reward criteria score *partially satisfied* — a point
raised but not landed. Says a point is not done until it carries the specific
value, the scope it holds under, and where it came from; and that when space is
short you finish the points you have rather than adding another. Explicitly
trades coverage for completeness, which is the opposite trade from most other
arms. It is also the only arm so far to cut serious errors materially (16 → 11).

**`name-the-source`.** Citation markers are stripped from `answer[].text`
before anyone reads it, so a reader sees confident prose with no visible
provenance — and 24 of 30 baseline answers name **zero** sources in the prose
itself while carrying 32 invisible docid markers each. This says to attribute
inside the sentence when the source is part of what makes the claim credible
("a 2019 randomised trial found", "the EU AI Act requires", "Statista puts it
at"), never to invent one, and never to dress a forum post in scholarly
register.

---

## Arms that change how the answer is written

**`cite-or-cut`.** Every world-asserting sentence carries a citation; a sentence
you cannot cite is one you have not established, so cut it rather than ship it
bare. Also: cite the passage that *states* the claim (check direction and
scope), prefer the specific over the categorical, and reserve hedging for
sources that are themselves uncertain. Targets a measured 13.5% uncited-object
rate against 0% for both organizer baselines.

**`compression`.** Names ~600 words as the honest length for a broad request
and adds a pass that removes any sentence the reader would not miss — restating,
section-introducing, summarising, recapping. Deliberately puts a number in the
prompt, against the usual rule that a number becomes a target, because the
number *is* the experiment: our answers run 844–891 words against a 1,024 cap
and the untested direction is shorter.

**`stated-form`.** A stated form is a requirement like any other — a request for
an article, a letter, a brief or a script wants that shape, with a lead and a
through-line, not the same facts served as flat declaratives. From a hand-read
case where a request for a ~10-minute-read article came back as 38 flat
sentences.

**`decision-lead`.** Lead with the finding that decides the question rather than
with background; and where you have a fact that completes the topic and a fact
that would change the asker's decision, and room for one, write the second.

---

## Arms that remove a specific defect

**`no-meta-reference`.** The retrieval is not a character in the answer — never
"the research describes", "the sources indicate", "the documents reviewed".
Say what is true about the world and let the citation marker attribute it.
Three such sentences appeared across the 119 test narratives; both organizer
baselines had zero.

**`english-only`.** Write in English throughout; a non-Latin script belongs only
inside a quoted-and-glossed term. One sentence in one topic came back with a
Japanese phrase standing in for the English.

---

## Retired

**~~`localization`~~** — told the agent not to attach a country, regulator, or
emergency number the request never named, after 9 of 119 narratives volunteered
Australian framing (preference 0.278 vs 0.509 where it happened). **Never
screened, because the cause was ours:** every request began with
`Current date and time: … (Australia/Melbourne)` from `agent.now_full()`, and
every prompt was titled `# AUS research agent`. Both fixed at source; the rule
now corrects nothing and only spends prompt budget. Kept in the builder as
`LOCALIZATION_RETIRED` as the record of a patch that should not have been
written.
