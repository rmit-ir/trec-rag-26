#!/usr/bin/env python3
"""Generate ``prompts/system/*.md`` variants from ``default.md`` by named patches.

Every variant is ``default.md`` plus an explicit, ordered list of anchored
string replacements. Nothing is hand-edited, so a variant differs from its
control *only* where a patch says it does, and two variants that share a patch
share it byte-for-byte. That is the property the whole A/B rests on: when
``evidence-paired`` scores differently from ``evidence-dense``, the difference is
the pairing patch and nothing else.

It also removes the drift risk the 2026-08-05 worklog named — six near-identical
16 KB files that nothing keeps in step. ``--check`` re-derives every generated
variant and diffs it against what is on disk, so a hand-edit anywhere is a
failing command rather than a silent divergence discovered months later.

``paired-lead.md`` and ``evidence-dense.md`` were originally produced by an
equivalent but unsaved script; their patches are transcribed here and
``--check`` confirms the transcription reproduces both files exactly.

    uv run --no-project python \\
        tasks/task-comparison/scripts/build_prompt_variants.py --check
    uv run --no-project python \\
        tasks/task-comparison/scripts/build_prompt_variants.py --write
"""
from __future__ import annotations

import argparse
import difflib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PROMPTS = ROOT / "src/systems/aus_agent/prompts/system"
CONTROL = "default.md"

# ---------------------------------------------------------------------------
# Patches. Each is (name, anchor, replacement); the anchor must occur exactly
# once in the text it is applied to, or the build fails loudly rather than
# producing a variant that silently lost one of its changes.

# RETIRED 2026-08-05. This told the model not to attach a country, regulator or
# emergency number the request never named. The cause was not the model: every
# request began with "Current date and time: ... (Australia/Melbourne)" from
# `agent.now_full()`, and every prompt was titled "# AUS research agent". Both
# are fixed at source, so the rule now corrects nothing and only spends prompt
# budget. Kept in the file as the record of a patch that should never have been
# written -- fix the toolchain, not the symptom.
LOCALIZATION_RETIRED = (
    "localization",
    "yours to build.\n\n## Scope interpretation",
    """yours to build.

Answer the asker in front of you, and only them. Do not attach a country,
jurisdiction, legal regime, regulator, emergency number, currency, or agency
to an answer whose request named none and whose evidence named none. If the
request is unlocalised, the answer is unlocalised: name the specific place only
where a committed document is what put it there, and say whose rules they are.
Telling an asker with no stated country to call a particular emergency number
or to follow a particular nation's employment law is wrong guidance, however
confidently the rest of the answer is grounded.

## Scope interpretation""",
)

STATED_FORM = (
    "stated-form",
    """Resolve ambiguity toward the most useful reasonable reading — which for a
narrow question is a direct answer, not an expanded survey of the topic around
it. Do not ask the user clarifying or confirming questions; proceed on the
strongest reasonable reading.""",
    """A stated form is a requirement like any other: a request for an article, a
letter, a brief, or a script wants that shape — continuous paragraphs with a
lead and a through-line for an article, not the same facts served as a list of
flat declaratives. Resolve ambiguity toward the most useful reasonable reading
— which for a narrow question is a direct answer, not an expanded survey of the
topic around it. Do not ask the user clarifying or confirming questions;
proceed on the strongest reasonable reading.""",
)

DECISION_ITEM = (
    "decision-item",
    """   actually needs, and the plan is revised as it does.

Use these requirements""",
    """   actually needs, and the plan is revised as it does.
5. **The decision behind the request.** Most requests exist because someone
   has to decide, build, buy, argue, or advise. Name what that is. A fact that
   would change the decision belongs in the answer even when no part of the
   request asked for it — the disqualifying legal constraint, the finding that
   rebuts the asker's stated premise, the evidence that the obvious remedy does
   not work. Watch for these while reading, and when one appears, say it.

Use these requirements""",
)

READING_A_RESULT = (
    "reading-a-result",
    "per-document evidence depth.\n\n## Staged and committed evidence",
    """per-document evidence depth.

## Reading a result

Read for what a document *states*, not for what it is *about*. A passage on the
right topic is worth nothing until you have the specific thing in it: the
figure, the date, the named study or programme, the mechanism, the quoted
finding, the exception. When you decide to commit a result, note what those
specifics are — that note is what you write from later, and it is the
difference between an answer that reports evidence and one that summarises
subject matter.

The most common way this run fails is quiet: a document is retrieved, read,
committed, cited — and the number inside it never reaches the answer, which
instead says "a contested case" where the document said "22,700 to 25,000" or
"significant contracts" where the document named the contract and its value.
The material was in hand and got dropped in the writing. Before writing any
sentence about something a committed document covers, look back at what that
document actually said and carry the specific across.

## Staged and committed evidence""",
)

CITE_OR_CUT = (
    "cite-or-cut",
    """- Cite at most three ids per sentence, and only ids that directly support that
  sentence. Every factual sentence should carry at least one citation. Use only
  committed ids; never fabricate facts or identifiers.""",
    """- Cite at most three ids per sentence, and only ids that directly support that
  sentence. Use only committed ids; never fabricate facts or identifiers.
- **Every sentence that asserts something about the world carries a citation.**
  A sentence you cannot cite is a sentence you have not established, and the
  fix is to cut it, not to ship it bare. Advice, procedure, and recommendation
  are assertions like any other: "ask the supplier for the factory's legal
  name" is a claim about what works and needs its support exactly as a date
  does. Cut the uncitable sentence and let the cited ones carry the answer;
  a shorter grounded answer beats a longer half-grounded one. Two narrow
  exceptions: the single permitted sentence saying you could not establish
  something, and, where the request asks you to invent — a story, a scene, a
  name, a design of your own — the invented material itself, which is the
  deliverable rather than a claim about the world.
- Cite the passage that states the claim, not one that merely discusses the
  topic. Check the direction and the scope: a passage about one city does not
  support a national claim, a passage about one year does not support a trend,
  a passage reporting an association does not support a cause, and a passage
  reporting what someone argued does not make the argument true. Where the
  passage says something narrower than you want to say, narrow the sentence to
  what it says rather than stretching the citation to cover it.
- Prefer the specific over the categorical, always. Write the number, the year,
  the name, the study, the amount, the rate — the thing your source actually
  says — rather than a word that stands in for it. "Contested", "significant",
  "substantial", "various", "a range of", "several studies" are placeholders
  where a committed document gives you the real value; replace each one with
  what the document says. Where sources disagree, give both figures and say who
  says what, which is more useful than calling the point disputed and moving
  on.
- Assert what your evidence establishes. Reach for "may", "might", "could",
  "should", or "can" when the source itself is uncertain or the claim is
  genuinely conditional — not as a default register. A page of hedged
  recommendations reads as an opinion piece; the same page with its figures and
  named findings in place reads as evidence.""",
)

ENGLISH_ONLY = (
    "english-only",
    """  to leave it out or to retreat to describing it from a distance.
- Every line is a sentence""",
    """  to leave it out or to retreat to describing it from a distance.
- Write in English throughout. A non-Latin script belongs in the report only
  inside a name or term you are quoting and immediately glossing; never leave a
  word in another language standing in for the English one.
- Every line is a sentence""",
)

NO_META_REFERENCE = (
    "no-meta-reference",
    """  supported, nor what supports it, nor how far that support reaches.
- Exactly one kind""",
    """  supported, nor what supports it, nor how far that support reaches.
- The retrieval is not a character in the answer. Never write "the research
  describes", "the sources indicate", "the corpus contains", "the documents
  reviewed", or any other phrase that makes your searching the subject of a
  sentence. Say what is true about the world and let the marker attribute it.
- Exactly one kind""",
)

PAIRED_LEAD = (
    "paired-lead",
    "Notes on the loop:\n\n- If reformulated question-term queries",
    """Notes on the loop:

- Resolve each lead against both engines before you judge it. The dense engine
  and the keyword engine return almost entirely different documents for the
  same need, and nothing in either result set tells you what the other would
  have found — so a lead searched on one engine has been judged on roughly half
  its available evidence, with no signal that anything is missing. A lead is
  ready to judge when both engines have answered it, not before. This is not
  extra work: it is the same number of searches in a round, spent as fewer
  leads covered properly rather than more leads covered half. Write each query
  of the pair for its own engine — natural, conceptual phrasing for the dense
  one; bare distinctive terms, proper names, and verbatim strings for the
  keyword one — so the pair is two views of one lead rather than one query sent
  twice. Expect both engines to return documents supporting the same point:
  that is the pairing working, and `commit_context` is where you weigh them
  against each other.
- If reformulated question-term queries""",
)

# --- new patches ----------------------------------------------------------

# The 2026-08-05 run measured paired-lead at +31% searches and +29% commits, so
# the prompt's own "same number of searches in a round" claim is false. Leaving
# it in would be an instruction the model demonstrably does not follow, which
# teaches it that the surrounding sentences are aspirational too.
PAIRING_HONEST_COST = (
    "pairing-honest-cost",
    """  ready to judge when both engines have answered it, not before. This is not
  extra work: it is the same number of searches in a round, spent as fewer
  leads covered properly rather than more leads covered half. Write each query""",
    """  ready to judge when both engines have answered it, not before. Cover fewer
  leads per round rather than issuing more searches: two leads resolved
  against both engines beats four leads seen through one. Write each query""",
)

DECISION_LEAD = (
    "decision-lead",
    """- Organize the report through sentence order and clear topic sentences. Do not
  use Markdown syntax (headings, bullets, numbering, bold, fences) or JSON.""",
    """- Lead with what the answer turns on. The opening sentences carry the finding
  that decides the question — the figure, the constraint, the rebuttal, the
  thing that changes what the asker does — not background the asker already had
  when they wrote the request. Context earns its place after that, and only
  where the answer does not stand without it.
- Where you have a fact that completes the topic and a fact that would change
  the asker's decision, and room for one, write the second. A survey that
  covers every part of the request and buries the one disqualifying constraint
  in its last third has answered the question and failed the reader.
- Organize the report through sentence order and clear topic sentences. Do not
  use Markdown syntax (headings, bullets, numbering, bold, fences) or JSON.""",
)

# Deliberately names a word figure, against the usual rule that a number in a
# prompt becomes a target — here the target IS the experiment. Our published
# runs are 1.16-1.18x the winning baseline's length and lose anyway, so
# "shorter" is the one direction on the length axis nobody has tested.
COMPRESSION = (
    "compression",
    """- Length follows the question, not the limit. Answer a narrow question in a
  sentence or two and stop; there is nothing to be gained by surrounding a
  one-line answer with background, and a reader who asked something simple
  will not read an essay. Only a genuinely broad, multi-part request should
  run long, and even then about 950 words is the practical ceiling: 1024 is a
  hard limit set by the evaluation and going over costs a full rewrite. Never
  pad toward a length.""",
    """- Length follows the question, not the limit, and the honest length is shorter
  than it feels while writing. Answer a narrow question in a sentence or two
  and stop; there is nothing to be gained by surrounding a one-line answer with
  background, and a reader who asked something simple will not read an essay.
  Even a genuinely broad, multi-part request is usually finished in about 600
  words once every sentence in it is carrying evidence; 950 is the practical
  ceiling and 1024 a hard limit set by the evaluation. Never pad toward a
  length.
- Before you write the final turn, take one pass with the question: which
  sentences would the reader not miss? A sentence that restates the one above
  it in different words, that introduces a section, that summarises what you
  are about to say, or that closes by recapping what you said — none of these
  carry evidence, and each one displaces a sentence that would. Cut them and
  spend the room on a figure, a named finding, or a case you had to leave out.""",
)

# ---------------------------------------------------------------------------
# Variants. Each is (filename, base, [patches], one-line rationale).

EVIDENCE_DENSE_PATCHES = [LOCALIZATION_RETIRED, STATED_FORM, DECISION_ITEM,
                          READING_A_RESULT, CITE_OR_CUT, ENGLISH_ONLY,
                          NO_META_REFERENCE]

NAME_THE_SOURCE = (
    "name-the-source",
    """- Write in your own voice, as the researcher. Every sentence asserts something
  about the subject the request asks about, and carries its markers. The
  markers do the attributing, so a sentence never announces that it is
  supported, nor what supports it, nor how far that support reaches.""",
    """- Write in your own voice, as the researcher. Every sentence asserts something
  about the subject the request asks about, and carries its markers.
- Name the source inside the sentence when the source is part of what makes the
  claim credible. The markers are stripped before your answer is read, so a
  reader sees your prose and nothing else: "a 2019 randomised trial found",
  "the EU AI Act requires", "Hebb's 1949 account", "Statista puts the figure
  at", "AMC 12 2018 Problem 8". Give the study, author, year, law, regulator,
  publication, dataset, or competition and round that your committed document
  names. This is not a citation and does not replace the markers — it is the
  attribution the reader can actually see.
- Do not invent one. Name only what a committed document states, and where it
  names no source, write the claim without one rather than inventing a
  plausible attribution. Naming a study that does not exist is far worse than
  naming none.
- Where the evidence behind a load-bearing claim is a forum post, a wiki, or an
  undated page, say so plainly or leave the claim out; do not dress it up in the
  register of a scholarly source.""",
)

# Derived from the baseline failure profile, not from a hypothesis: 25.2% of
# reward criteria score *partially satisfied* (463 of 1,839 pooled gradings) —
# half credit for a point the answer raised but did not land. That pool is worth
# ~0.08-0.10 of the headline score and, unlike the 33.4% scored "missing", it
# costs almost no extra words: a partial is usually a claim already present that
# is missing its figure, its source, or its scope. Every other patch so far has
# fought the 1,024-word cap; this one does not.
FINISH_THE_CLAIM = (
    "finish-the-claim",
    """- Cite at most three ids per sentence, and only ids that directly support that
  sentence. Every factual sentence should carry at least one citation. Use only
  committed ids; never fabricate facts or identifiers.""",
    """- Cite at most three ids per sentence, and only ids that directly support that
  sentence. Every factual sentence should carry at least one citation. Use only
  committed ids; never fabricate facts or identifiers.
- Finish every point you start. A half-made point earns nothing: raising a
  topic, gesturing at a mechanism, or saying that something matters without
  saying what it is, how much, or on whose authority, spends the words of a
  full answer and delivers part of one. Before a point is done, it carries the
  three things that make it checkable — the specific value (a figure, date,
  name, threshold, or worked step), the scope it holds under (who, where, when,
  under what condition), and where it comes from when the source is what makes
  it credible.
- Prefer finishing a point to adding another. When space is short — and it
  usually is — a smaller number of complete points beats a longer list of
  gestures. Cut the weakest point and spend its words completing the ones that
  remain, rather than covering one more topic in a sentence that settles
  nothing.
- Hedged, general, and vague are the same failure wearing different clothes.
  "can have significant impacts", "several studies suggest", "may vary
  considerably", "is an important consideration" — each of these is a point
  started and abandoned. If the evidence supports the specific version, write
  the specific version; if it does not, the point is not yet established and
  belongs out of the answer.""",
)

# Evidence: of the high-weight Implicit criteria the best run MISSES, 20 of 20
# name an entity the question never mentions -- Roth, Nasdaq, Russell 2000,
# "board-certified dermatologists". The control prompt forbids searching for
# exactly those: round-one queries may use "only the question's own wording",
# and later rounds may never "introduce a candidate the corpus has not yet
# surfaced". So the agent is prohibited from looking for the content the rubric
# pays 4-5 points to cover. Implicit Criteria is 38.4% of all weight and sits at
# 0.651 with 0.134 recoverable -- nine times the entire References axis.
#
# The rule exists for a real reason: seeding a query with a guessed answer and
# then "confirming" it is how an agent hallucinates. The fix is to make the rule
# CONDITIONAL rather than absolute -- prior knowledge may say what to look FOR,
# but only retrieval may license an assertion. Naming the candidate is a search
# decision; asserting it is an evidence decision, and they are not the same.
KNOWN_CANDIDATES = (
    "known-candidates",
    """1. **Search.** Round one's queries come from the question: build them only
   from the question's own wording and plain paraphrases of it. Do not seed
   a query with candidate answers — specific names, techniques, causes,
   examples — that the question itself does not mention: you do not know
   what this corpus holds until it answers, no matter how well you know the
   subject. In every later round, each new content-bearing query term must
   be traceable to a document retrieved in an earlier round; prior knowledge
   may rephrase, disambiguate, and supply synonyms — it may never introduce
   a candidate the corpus has not yet surfaced.""",
    """1. **Search.** Round one's queries come from the question's own wording
   and plain paraphrases of it, so that what the corpus holds — not what you
   expect — sets the answer's shape.
   Once those opening rounds have shown you the territory, name the things a
   knowledgeable reader would expect this answer to cover even though the
   question never said them: the standard instruments in this domain, the
   competing options anyone comparing would weigh, the terms that must be
   defined, the regulation that governs it, the cost or scale dimension. A
   request about retirement saving implies Roth against traditional; one about
   US market performance implies the major indexes by name; one about a
   diagnostic model implies who provides the ground-truth labels. Search for
   those by name.
   Prior knowledge decides what to LOOK FOR; only retrieval decides what you
   may ASSERT. A candidate you name and then cannot find in the corpus does not
   enter the answer — say plainly that you could not establish it, or leave it
   out. Naming a candidate is a search decision and costs one query; asserting
   one is an evidence decision and requires a committed document.""",
)

WORDCAP_PROBE = (
    "wordcap-probe",
    """- Length follows the question, not the limit. Answer a narrow question in a
  sentence or two and stop; there is nothing to be gained by surrounding a
  one-line answer with background, and a reader who asked something simple
  will not read an essay. Only a genuinely broad, multi-part request should
  run long, and even then about 950 words is the practical ceiling: 1024 is a
  hard limit set by the evaluation and going over costs a full rewrite. Never
  pad toward a length.""",
    """- Length follows the question, not the limit. Answer a narrow question in a
  sentence or two and stop; there is nothing to be gained by surrounding a
  one-line answer with background, and a reader who asked something simple
  will not read an essay. Only a genuinely broad, multi-part request should
  run long, and such a request may run to about 2,000 words where the evidence
  genuinely supports that length. Never pad toward a length.""",
)

# Every patch that can stand alone as a single-factor arm. PAIRING_HONEST_COST
# is excluded: it edits text that only PAIRED_LEAD introduces, so it is a
# correction to that patch rather than an independent change, and its anchor
# does not exist in the control.
SOLO_PATCHES = [STATED_FORM, DECISION_ITEM, READING_A_RESULT,
                CITE_OR_CUT, ENGLISH_ONLY, NO_META_REFERENCE, PAIRED_LEAD,
                DECISION_LEAD, COMPRESSION, NAME_THE_SOURCE,
                FINISH_THE_CLAIM, KNOWN_CANDIDATES, WORDCAP_PROBE]

VARIANTS: list[tuple[str, str, list, str]] = [
    ("paired-lead.md", CONTROL, [PAIRED_LEAD],
     "search-side: a lead is ready to judge only once both engines answered it"),
    ("evidence-dense.md", CONTROL, EVIDENCE_DENSE_PATCHES,
     "answer-side: cite-or-cut, carry the specific across, no volunteered locale"),
    ("evidence-paired.md", CONTROL,
     EVIDENCE_DENSE_PATCHES + [PAIRED_LEAD, PAIRING_HONEST_COST],
     "the two arms that moved their structural targets, composed"),
    ("decision-first.md", CONTROL,
     EVIDENCE_DENSE_PATCHES + [PAIRED_LEAD, PAIRING_HONEST_COST, DECISION_LEAD],
     "evidence-paired + lead on the finding that decides the question"),
    ("compressed.md", CONTROL,
     EVIDENCE_DENSE_PATCHES + [PAIRED_LEAD, PAIRING_HONEST_COST, COMPRESSION],
     "evidence-paired + cut to ~600 words; tests the arena's length confound"),
]

# One arm per patch: control + exactly ONE change, so a score difference is
# attributable to that change and nothing else. This is the screening stage;
# stacks are only built from patches that already banked a win on their own.
# `evidence-dense` is itself seven patches, which is why its published
# uncited-rate result cannot be credited to any one of them — decomposing it
# here is the point.
# The four single-factor arms with a positive headline AND no penalty
# regression, combined. `cite-or-cut` is excluded despite its positive mean:
# it drove satisfied severe penalties 16 -> 18, and condition (3) is a safety
# gate that does not trade against the headline.
#
# This is a NEW hypothesis, not an assumed sum. Each constituent was screened
# alone first, so a difference here is attributable to composition; and the
# combined effect (~4 x 0.014) is the first quantity in this study large enough
# for the instrument to resolve, since each part individually is not.
VARIANTS += [("combo-positive4.md", CONTROL,
              [NAME_THE_SOURCE, READING_A_RESULT, STATED_FORM,
               FINISH_THE_CLAIM],
              "combination of the four non-regressing positive single arms")]

VARIANTS += [(f"solo-{patch[0]}.md", CONTROL, [patch],
              f"single-factor arm: {patch[0]}")
             for patch in SOLO_PATCHES]

# Generated by an earlier, unsaved script. --check verifies the transcription
# above reproduces them; --write will not touch them unless --force is given,
# so a published A/B cannot be invalidated by a rebuild.
FROZEN = {"paired-lead.md", "evidence-dense.md"}


def apply(text: str, patches: list[tuple[str, str, str]], variant: str) -> str:
    for name, anchor, replacement in patches:
        count = text.count(anchor)
        if count != 1:
            raise SystemExit(
                f"{variant}: patch {name!r} anchor occurs {count} times, expected 1.\n"
                f"anchor starts: {anchor[:70]!r}")
        text = text.replace(anchor, replacement)
    return text


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true",
                      help="rebuild every variant and diff against disk")
    mode.add_argument("--write", action="store_true")
    parser.add_argument("--force", action="store_true",
                        help="also rewrite the frozen variants")
    args = parser.parse_args()

    control = (PROMPTS / CONTROL).read_text(encoding="utf-8")
    failures = 0
    for filename, base, patches, why in VARIANTS:
        base_text = control if base == CONTROL else (PROMPTS / base).read_text(
            encoding="utf-8")
        built = apply(base_text, patches, filename)
        path = PROMPTS / filename
        names = ", ".join(p[0] for p in patches)

        if args.check:
            if not path.exists():
                print(f"MISSING  {filename}  ({names})")
                failures += 1
                continue
            current = path.read_text(encoding="utf-8")
            if current == built:
                print(f"ok       {filename:22s} {len(patches)} patches — {why}")
            else:
                failures += 1
                print(f"DIFFERS  {filename:22s} ({names})")
                for line in list(difflib.unified_diff(
                        current.splitlines(), built.splitlines(),
                        "on disk", "rebuilt", lineterm=""))[:24]:
                    print(f"    {line}")
            continue

        if filename in FROZEN and not args.force:
            print(f"skipped  {filename:22s} frozen — pass --force to rewrite")
            continue
        path.write_text(built, encoding="utf-8")
        print(f"wrote    {filename:22s} {len(patches)} patches — {why}")

    if args.check and failures:
        print(f"\n{failures} variant(s) do not match their patch list. Either a "
              f"file was hand-edited, or a patch here is stale — fix the patch, "
              f"not the file.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
