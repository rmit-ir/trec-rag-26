#!/usr/bin/env python3
"""Score a retrieved chunk's evidentiary density from its text alone.

**Why text alone.** The corpus exposes no provenance: the doc endpoint returns
``{api, index, docid, doc}`` with ``doc`` a bare string — no URL, no domain, no
author, no date. Domain is normally the single strongest credibility signal and
it simply is not available, so every judgement here is made from the prose.

**Why it matters.** The dev rubrics score this directly: −4 for citing
non-scholarly sources to justify a claim, −5 for citing nonexistent work or
made-up metrics, and positive weight for peer-reviewed research, named
regulations, and credible market-research houses. References & Citation Quality
is the agent's worst axis (0.21). Today the agent has *no* signal to prefer a
better source with — ``commit_context`` already tells it to prefer "the primary
or better-sourced account over a report of it", which is unactionable when
every result is an anonymous wall of text.

Three families of signal, deliberately cheap and deterministic (this runs on
every search result, so an LLM call per document is out of the question):

- **specificity** — figures, dates, percentages, named institutions, units,
  citation-shaped strings. Evidence that the text commits to checkable claims.
- **content-farm / SEO register** — second-person address, rhetorical openers,
  "in this article we will", listicle scaffolding. Marks text written to rank
  rather than to inform.
- **LLM-generated tells** — the well-known lexical fingerprint ("delve",
  "tapestry", "navigate the complexities", "testament to", "in today's
  fast-paced world") plus the structural flatness that comes with it.

The output is a score in [0, 1] and the reasons behind it, so a low score can
always be explained rather than merely asserted.

**This is a prefilter, not a fact-checker.** It cannot detect a confident
falsehood written in clean prose; nothing cheap can. It is aimed at the failure
the corpus actually presents in bulk — citing filler as if it were evidence.

Attached to every search result as ``evidence_density`` so the model can break
ties among equally relevant candidates. **An annotation, never a filter.**
Measured over 5,928 corpus documents and 144 the agent actually cited: it
already rejects filler far better than chance (31.7% of the corpus scores below
0.20; only 8.3% of its citations do) but selects evidential documents at the
base rate (11.8% cited vs 9.8% available). Gating on this score would replace a
filter that works with a cruder one; surfacing it addresses the half the agent
is blind to.
"""
from __future__ import annotations

import re


# --- specificity: does the text commit to anything checkable? ---------------
FIGURE = re.compile(r"(?<![\w.])\d{1,3}(?:,\d{3})+(?![\d,.])|"
                    r"(?<![\w.])\d+(?:\.\d+)?\s?(?:%|percent|per cent)|"
                    r"[$€£¥]\s?\d")
YEAR = re.compile(r"\b(?:1[89]\d{2}|20[0-2]\d)\b")
UNIT = re.compile(r"\b\d+(?:\.\d+)?\s?(?:kg|km|cm|mm|mg|ml|GHz|MHz|GB|TB|kW|MW|"
                  r"°C|°F|mph|km/h|years?|months?|days?|hours?)\b", re.I)
CITATIONISH = re.compile(
    r"\bet al\.|\(\d{4}\)|\bdoi:|\bISBN\b|\bvol\.\s?\d+|\bpp?\.\s?\d+|"
    r"\bJournal of\b|\bProceedings of\b|\barXiv\b", re.I)
INSTITUTION = re.compile(
    r"\b(?:University|Institute|Laborator(?:y|ies)|Ministry|Department of|"
    r"Commission|Bureau|Agency|Foundation|Association|Society|WHO|CDC|NIH|"
    r"NASA|OECD|IMF|IEEE|NIST|FDA|EPA)\b")

# --- content-farm / SEO register --------------------------------------------
SEO = re.compile(
    r"\bin this (?:article|post|guide|blog)\b|\bwe will (?:delve|explore|dive)\b|"
    r"\bkeep reading\b|\bread on\b|\blet'?s (?:dive|get started|explore)\b|"
    r"\bclick here\b|\byou might be (?:thinking|wondering)\b|"
    r"\bfrequently asked questions\b|\bthe ultimate guide\b|"
    r"\beverything you need to know\b|\bin conclusion\b", re.I)
SECOND_PERSON = re.compile(r"\b(?:you|your|you'?re|you'?ll)\b", re.I)

# --- LLM-generated fingerprint ----------------------------------------------
LLM_TELL = re.compile(
    r"\bdelve\b|\bdelving\b|\btapestry\b|\bnavigat(?:e|ing) the complexit|"
    r"\btestament to\b|\bin today'?s (?:fast-paced|digital|modern) world\b|"
    r"\bit'?s (?:important|worth) (?:to )?not(?:e|ing)\b|\bmultifaceted\b|"
    r"\bplays a (?:crucial|pivotal|vital) role\b|\bcaptivating\b|"
    r"\brealm of\b|\bunlock(?:ing)? the (?:power|potential|secrets)\b|"
    r"\bembark on a journey\b|\bever-(?:evolving|changing) landscape\b", re.I)


def rate(text: str) -> dict:
    """Score in [0,1] plus the evidence behind it. Higher = more trustworthy."""
    words = text.split()
    n = max(len(words), 1)
    per1k = lambda c: 1000.0 * c / n  # noqa: E731

    figures = per1k(len(FIGURE.findall(text)))
    years = per1k(len(YEAR.findall(text)))
    units = per1k(len(UNIT.findall(text)))
    cites = per1k(len(CITATIONISH.findall(text)))
    insts = per1k(len(INSTITUTION.findall(text)))
    seo = per1k(len(SEO.findall(text)))
    you = per1k(len(SECOND_PERSON.findall(text)))
    llm = per1k(len(LLM_TELL.findall(text)))

    # Saturating credit: the first few figures matter, the twentieth does not.
    sat = lambda v, k: min(v / k, 1.0)  # noqa: E731
    specificity = (0.30 * sat(figures, 4) + 0.20 * sat(years, 4)
                   + 0.15 * sat(units, 2) + 0.20 * sat(cites, 1.5)
                   + 0.15 * sat(insts, 2))
    # Penalties are capped so one stray "you" cannot sink a good document.
    penalty = min(0.45 * sat(seo, 2) + 0.25 * sat(you, 20)
                  + 0.45 * sat(llm, 2), 0.85)

    score = max(0.0, min(1.0, 0.15 + 0.85 * specificity - penalty))
    reasons = []
    if figures or units:
        reasons.append(f"{figures:.1f} figures/1k, {units:.1f} units/1k")
    if cites:
        reasons.append(f"{cites:.1f} citation-shaped/1k")
    if insts:
        reasons.append(f"{insts:.1f} named institutions/1k")
    if seo:
        reasons.append(f"SEO register ({seo:.1f}/1k)")
    if llm:
        reasons.append(f"LLM tells ({llm:.1f}/1k)")
    if you > 12:
        reasons.append(f"heavily second-person ({you:.0f}/1k)")
    return {"score": round(score, 3), "words": len(words),
            "reasons": reasons or ["no strong signal either way"]}


