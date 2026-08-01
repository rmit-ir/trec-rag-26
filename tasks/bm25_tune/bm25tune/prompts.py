"""The judge-prompt registry (PLAN §3.2).

Four frozen variants, each identified by a `prompt_version` string that is a
**component of the judgment cache key** (`jkey = pv::topic_id::chunk_id`, PLAN
§5.3). That coupling is the whole reason this module is written the way it is:

- Templates are module-level constants, never assembled at call time, so the
  text a `prompt_version` names is a single literal a reviewer can read.
- Every `PromptSpec` carries `sha256(template)`, and `tests/bm25_tune/
  test_prompts.py` pins those digests. **Editing a template without minting a
  new version id therefore fails a test** — the alternative is silent cache
  poisoning, where judgments made under the old wording answer lookups under the
  new one and the sweep is scored against a label set that never existed.
- Rendering substitutes `{q}`/`{p}` by literal token replacement, not
  `str.format`. Passages are arbitrary web text and routinely contain braces
  (code, JSON, `{{`), which `format` would either interpret or raise on.

**Nothing here tells the judge how often each grade should occur, except
`facet-rare3-v1`.** The two measured variants land far apart (umbrela-v1: 10 % at
grade >=2; facet-v1: 75 %) because grade frequency is a side effect of rubric
wording rather than something either prompt states. `facet-rare3-v1` (added
2026-07-31) is the one variant that says it outright.

**Which of the five is right is an open question — see PLAN §3.3b.** A hand-read
of 22 real keyword hits put ~65 % of the *judged pool* at grade >=2, because the
pool is BM25 top-4-to-10 for agent-authored queries, not random crawl text. So
`facet-v1`'s measured 75 % is closer to defensible than it looks, and
`facet-rare3-v1`'s "MOST of them are not useful evidence" is a claim about the
corpus that may be false of the pool. It is a hypothesis WP0 tests, not a fix
already applied — do not treat it as the presumed winner, and do not tighten the
other prompts toward it before the 280-pair measurement exists.

`umbrela-v1`/`umbrela-kw-v1` reproduce the team's prior umbrela-bedrock prompt
**character-for-character** from
`evaluation-results/aus-agent/umbrela-bedrock/tasks.jsonl` so the sweep keeps a
column comparable with those runs — even though PLAN §1 measured the narrative
variant to be degenerate (72.5 % of grades exactly 1). They are kept for
continuity, not because they are expected to win.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Literal

QuerySlot = Literal["narrative", "keyword"]

#: Placeholders a template may contain. `{q}` is whatever `query_slot` selects.
Q_TOKEN = "{q}"
P_TOKEN = "{p}"

# ---------------------------------------------------------------------------
# Verbatim UMBRELA (copied character-for-character from the umbrela-bedrock
# `instruction` field; the only edits are the two slot substitutions).
# ---------------------------------------------------------------------------
UMBRELA_TEMPLATE = (
    "Given a query and a passage, you must provide a score on an integer scale "
    "of 0 to 3 with the following meanings:\n"
    "0 = represent that the passage has nothing to do with the query, \n"
    "1 = represents that the passage seems related to the query but does not "
    "answer it, \n"
    "2 = represents that the passage has some answer for the query, but the "
    "answer may be a bit unclear, or hidden amongst extraneous information "
    "and \n"
    "3 = represents that the passage is dedicated to the query and contains "
    "the exact answer.\n"
    "\n"
    "Important Instruction: Assign category 1 if the passage is somewhat "
    "related to the topic but not completely, category 2 if passage presents "
    "something very important related to the entire topic but also has some "
    "extra information and category 3 if the passage only and entirely refers "
    "to the topic. If none of the above satisfies give it category 0.\n"
    "\n"
    "Query: {q}\n"
    "Passage: {p}\n"
    "\n"
    "Split this problem into steps:\n"
    "Consider the underlying intent of the search.\n"
    "Measure how well the content matches a likely intent of the query (M).\n"
    "Measure how trustworthy the passage is (T).\n"
    "Consider the aspects above and the relative importance of each, and "
    "decide on a final score (O). Final score must be an integer value only.\n"
    "Do not provide any code in result. Provide each score in the format of: "
    "##final score: score without providing any reasoning."
)

# ---------------------------------------------------------------------------
# facet-v1 — the adapted multi-facet rubric, VERBATIM as measured at n=60
# (grades {0:7, 1:8, 2:36, 3:9}). Do not reword: the measurement in PLAN §1 is
# only evidence about *this* text.
# ---------------------------------------------------------------------------
FACET_V1_TEMPLATE = (
    "You are judging whether a retrieved passage is useful evidence for "
    "answering a complex, multi-part information need. The need is a narrative "
    "that usually spans several facets; no single passage is expected to cover "
    "all of it.\n"
    "Score on an integer scale of 0 to 3:\n"
    "3 = the passage directly and substantially addresses one or more facets "
    "of the need, with specific, concrete, usable content (data, methods, "
    "recommendations, or detailed explanation).\n"
    "2 = the passage partially addresses a facet, or gives clearly relevant "
    "background an answer would draw on, but is thin, generic, or tangential "
    "in places.\n"
    "1 = the passage is on the same broad topic but contributes little an "
    "answer could actually use.\n"
    "0 = the passage is unrelated to the need.\n"
    "Judge usefulness for one or more facets, NOT whether the passage answers "
    "the whole need. A passage that thoroughly covers a single facet deserves "
    "3.\n"
    "Information need: {q}\n"
    "Passage: {p}\n"
    "Decide the final score. Provide it in exactly this format and nothing "
    "else: ##final score: <0-3>"
)

# ---------------------------------------------------------------------------
# facet-name-v1 — facet-v1 plus a forced discrimination step. PLAN §3.2: name
# the facet in <=10 words first, and tighten grades 2 and 3, to attack the
# measured grade-2 pile-up (60 % modal share under facet-v1).
# ---------------------------------------------------------------------------
FACET_NAME_V1_TEMPLATE = (
    "You are judging whether a retrieved passage is useful evidence for "
    "answering a complex, multi-part information need. The need is a narrative "
    "that usually spans several facets; no single passage is expected to cover "
    "all of it.\n"
    "Before scoring, name in 10 words or fewer which facet of the need this "
    "passage addresses, or write \"none\" if it addresses no facet.\n"
    "Then score on an integer scale of 0 to 3:\n"
    "3 = a passage an answer writer would quote or directly build a section "
    "from: it addresses a named facet with specific, concrete, usable content "
    "(data, methods, recommendations, or detailed explanation).\n"
    "2 = relevant background or a partial treatment an answer would cite but "
    "could not rely on alone.\n"
    "1 = the passage is on the same broad topic but contributes little an "
    "answer could actually use.\n"
    "0 = the passage is unrelated to the need.\n"
    "Judge usefulness for one or more facets, NOT whether the passage answers "
    "the whole need. A passage that thoroughly covers a single facet deserves "
    "3.\n"
    "Information need: {q}\n"
    "Passage: {p}\n"
    "Answer in exactly this format and nothing else:\n"
    "##facet: <10 words or fewer, or none>\n"
    "##final score: <0-3>"
)

# ---------------------------------------------------------------------------
# facet-rare3-v1 — facet-name-v1 plus an explicit BASE RATE anchor. Added
# 2026-07-31 at the user's direction: "most of the documents in the collection
# are not relevant, and only very few should receive the highest score... Of
# course, it shouldn't be too harsh either, as it wouldn't be very useful."
#
# The two measured variants sit on opposite sides of that instruction —
# umbrela-v1 is too harsh (10 % at >=2, mode 1) and facet-v1 is too lenient
# (75 % at >=2), and NEITHER prompt tells the judge anything about how often
# relevance should occur. Grade frequency is currently an accident of wording.
# This variant states the target distribution as a calibration instruction and
# reserves 3 explicitly, while naming the failure mode in the other direction so
# it does not simply trade leniency for harshness.
#
# The percentages are deliberately soft ("roughly", "a small minority") rather
# than a quota: a hard "grade exactly 20 % as 3" would make the judge rank
# within the batch, but each call sees ONE passage with no batch to rank against,
# so a quota it cannot satisfy locally would just add noise.
# ---------------------------------------------------------------------------
FACET_RARE3_V1_TEMPLATE = (
    "You are judging whether a retrieved passage is useful evidence for "
    "answering a complex, multi-part information need. The need is a narrative "
    "that usually spans several facets; no single passage is expected to cover "
    "all of it.\n"
    "Calibration — this matters as much as the rubric below. These passages come "
    "from a broad web crawl retrieved by a keyword search, so MOST of them are "
    "not useful evidence: expect to give 0 or 1 to the majority, 2 to a "
    "substantial minority, and 3 to only a small minority of genuinely "
    "excellent passages. Do NOT reward a passage merely for being on the right "
    "topic or containing the right words. Equally, do not be stingy: a passage "
    "that really would help an answer writer must not be pushed down to 1 just "
    "because it is imperfect or covers only part of the need.\n"
    "Before scoring, name in 10 words or fewer which facet of the need this "
    "passage addresses, or write \"none\" if it addresses no facet.\n"
    "Then score on an integer scale of 0 to 3:\n"
    "3 = excellent and uncommon: a passage an answer writer would quote or "
    "directly build a section from, addressing a named facet with specific, "
    "concrete, usable content (data, methods, recommendations, or detailed "
    "explanation).\n"
    "2 = genuinely useful: relevant background or a partial treatment an answer "
    "would cite but could not rely on alone.\n"
    "1 = on the same broad topic, but contributes little or nothing an answer "
    "could actually use.\n"
    "0 = unrelated to the need, or purely navigational, boilerplate, or "
    "promotional text.\n"
    "Judge usefulness for one or more facets, NOT whether the passage answers "
    "the whole need. A passage that thoroughly covers a single facet well "
    "deserves 3.\n"
    "Information need: {q}\n"
    "Passage: {p}\n"
    "Answer in exactly this format and nothing else:\n"
    "##facet: <10 words or fewer, or none>\n"
    "##final score: <0-3>"
)

#: Grade line the judge must emit. `judge.parse_grade` uses the same pattern, so
#: prompt and parser can never disagree about the contract.
GRADE_RE = re.compile(r"##\s*final score:\s*([0-3])", re.IGNORECASE)
#: Facet line — `facet-name-v1` only; captured as metadata, never required.
FACET_RE = re.compile(r"##\s*facet:\s*(.+)", re.IGNORECASE)


def sha256_text(text: str) -> str:
    """`sha256` of a string's UTF-8 bytes, hex. Used for both pins and log records."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class UnknownPromptVersion(KeyError):
    """Raised for a `prompt_version` that is not in the registry.

    A hard failure on purpose: a typo'd version id would otherwise mint a fresh
    cache namespace and silently re-judge (and re-bill) the entire pool.
    """


@dataclass(frozen=True)
class PromptSpec:
    """One frozen judge prompt.

    `version_id` is the cache-key component and the on-disk qrel filename, so it
    must change whenever `template` does — enforced by the sha256 pins in
    `test_prompts.py`.

    `query_slot` records *what goes in `{q}`*: the full topic narrative
    (`"narrative"`) or the keyword string aus_agent actually issued
    (`"keyword"`). PLAN §0 settles the narrative as the judge target for the
    headline; `umbrela-kw-v1` exists to measure what that choice costs.

    `emits_facet` tells the driver whether a missing `##facet:` line is worth
    recording — for the three variants that never ask for one, `facet` in the
    judgment record is simply `None`.
    """

    version_id: str
    template: str
    query_slot: QuerySlot
    emits_facet: bool
    notes: str

    @property
    def template_sha256(self) -> str:
        return sha256_text(self.template)

    def render(self, query: str, passage: str) -> str:
        """Substitute the query and passage slots.

        Literal token replacement, single pass over the template, so neither the
        narrative nor the passage can inject a placeholder that a later
        substitution would expand — and so braces in the passage (code, JSON)
        survive untouched, which `str.format` would not allow.
        """
        out: list[str] = []
        for chunk in _split_tokens(self.template):
            if chunk == Q_TOKEN:
                out.append(query)
            elif chunk == P_TOKEN:
                out.append(passage)
            else:
                out.append(chunk)
        return "".join(out)

    def query_for(self, *, narrative: str, keyword: str) -> str:
        """Pick the `{q}` value this variant wants from a (topic, query) pair."""
        return narrative if self.query_slot == "narrative" else keyword

    def render_pair(self, *, narrative: str, keyword: str,
                    passage: str) -> str:
        """`render` with the query slot chosen by `query_slot`.

        The call site the driver uses: it always has both strings and must not
        have to remember which variant wants which — getting that wrong would
        mislabel a whole prompt-version's worth of cached judgments.
        """
        return self.render(self.query_for(narrative=narrative,
                                          keyword=keyword), passage)


def _split_tokens(template: str) -> list[str]:
    """Split a template into literal chunks and `{q}`/`{p}` tokens."""
    parts: list[str] = []
    rest = template
    while rest:
        idx_q = rest.find(Q_TOKEN)
        idx_p = rest.find(P_TOKEN)
        candidates = [i for i in (idx_q, idx_p) if i >= 0]
        if not candidates:
            parts.append(rest)
            break
        cut = min(candidates)
        token = Q_TOKEN if cut == idx_q else P_TOKEN
        if cut:
            parts.append(rest[:cut])
        parts.append(token)
        rest = rest[cut + len(token):]
    return parts


PROMPTS: dict[str, PromptSpec] = {
    spec.version_id: spec
    for spec in (
        PromptSpec(
            version_id="umbrela-v1",
            template=UMBRELA_TEMPLATE,
            query_slot="narrative",
            emits_facet=False,
            notes=("verbatim UMBRELA from evaluation-results/aus-agent/"
                   "umbrela-bedrock/tasks.jsonl, narrative in the query slot; "
                   "[measured] degenerate on narratives (72.5% grade 1). Kept "
                   "as a continuity column."),
        ),
        PromptSpec(
            version_id="umbrela-kw-v1",
            template=UMBRELA_TEMPLATE,
            query_slot="keyword",
            emits_facet=False,
            notes=("verbatim UMBRELA with the keyword search_query in the "
                   "query slot — isolates how much of umbrela-v1's collapse is "
                   "the narrative target rather than the rubric."),
        ),
        PromptSpec(
            version_id="facet-v1",
            template=FACET_V1_TEMPLATE,
            query_slot="narrative",
            emits_facet=False,
            notes=("adapted multi-facet rubric, verbatim as measured at n=60 "
                   "({0:7, 1:8, 2:36, 3:9}); the going-in PRIMARY candidate."),
        ),
        PromptSpec(
            version_id="facet-name-v1",
            template=FACET_NAME_V1_TEMPLATE,
            query_slot="narrative",
            emits_facet=True,
            notes=("facet-v1 plus a forced <=10-word facet naming step and "
                   "tightened grade-2/grade-3 wording, aimed at breaking the "
                   "measured 60% grade-2 pile-up."),
        ),
        PromptSpec(
            version_id="facet-rare3-v1",
            template=FACET_RARE3_V1_TEMPLATE,
            query_slot="narrative",
            emits_facet=True,
            notes=("facet-name-v1 plus an explicit base-rate anchor (most "
                   "passages are 0/1, grade 3 is uncommon) with a stated "
                   "do-not-be-stingy counterweight. Added 2026-07-31 at the "
                   "user's direction; the only variant that says anything about "
                   "how OFTEN each grade should occur. Untested — WP0 measures "
                   "it against the two-sided gate."),
        ),
    )
}

#: PLAN §3.2's table order — what `calibrate` iterates and the report rows use.
CALIBRATION_ORDER = ("umbrela-v1", "umbrela-kw-v1", "facet-v1",
                     "facet-name-v1", "facet-rare3-v1")
#: PLAN §0's going-in primary; `judge-pool --prompt-version` defaults to it, but
#: WP6's gate decides the real winner.
DEFAULT_PROMPT_VERSION = "facet-v1"


def get_prompt(version_id: str) -> PromptSpec:
    """Look up a spec, raising `UnknownPromptVersion` rather than defaulting."""
    try:
        return PROMPTS[version_id]
    except KeyError:
        known = ", ".join(sorted(PROMPTS))
        raise UnknownPromptVersion(
            f"unknown prompt_version {version_id!r}; known: {known}") from None


def all_versions() -> tuple[str, ...]:
    """Registered version ids in PLAN §3.2 table order."""
    assert set(CALIBRATION_ORDER) == set(PROMPTS), (
        "CALIBRATION_ORDER and PROMPTS disagree — a variant was added to one "
        "and not the other")
    return CALIBRATION_ORDER


def registry_digests() -> dict[str, str]:
    """`{version_id: sha256(template)}` — what `test_prompts.py` pins."""
    return {vid: PROMPTS[vid].template_sha256 for vid in all_versions()}
