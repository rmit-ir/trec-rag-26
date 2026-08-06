"""What `bm25tune/prompts.py` defends: the honesty of the cache key.

A judgment is cached under `(prompt_version, topic_id, chunk_id)`. The version id
is the *only* thing standing between two prompts' judgments, so the registry has
exactly one dangerous failure mode: **someone edits a template without minting a
new version id.** Every cached grade made under the old wording then answers
lookups under the new one, the sweep is scored against a label set that never
existed, and nothing anywhere looks wrong — the qrel is well-formed, the counts
are right, the run completes.

The sha256 pins below are the defence. They are not a style check; they are the
mechanism that converts an invisible science error into a failing test. When one
fails, the fix is to add a new `PromptSpec` (`facet-v2`, …), never to update the
digest in place.

The secondary concern is rendering: a passage is arbitrary web text, so brace
characters, `{q}`-looking strings, and 4 kB of prose all have to survive
substitution untouched.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from bm25tune import prompts
from bm25tune.prompts import (CALIBRATION_ORDER, DEFAULT_PROMPT_VERSION,
                              PROMPTS, UnknownPromptVersion, all_versions,
                              get_prompt, registry_digests, sha256_text)

REPO_ROOT = Path(__file__).resolve().parents[2]

#: sha256 of each variant's template text, pinned. **Do not edit a digest to
#: make this pass** — a changed template needs a new `version_id`, because the
#: judgment cache is keyed on that id (PLAN §5.3).
EXPECTED_DIGESTS = {
    "umbrela-v1":
        "e2a8594f0175be580f173fb8b7f5ada51fb06b52993b6fbc29f9c069ebfeecf5",
    "umbrela-kw-v1":
        "e2a8594f0175be580f173fb8b7f5ada51fb06b52993b6fbc29f9c069ebfeecf5",
    "facet-v1":
        "99229ef649208a5272ee1873a16a53142c3405df65da2e5faab0e00e326d404f",
    "facet-name-v1":
        "0adef718499e24aa64d60b6d070a3b3d24e7810decedac5f54facf941abd18dd",
    "facet-rare3-v1":
        "6c3898c45743441b78142ce25f4197a9efd35d828e897adae10e5102719e409c",
}


def test_registry_digests_are_pinned() -> None:
    """A silent template edit must fail here, not surface as a poisoned qrel.

    This is the test the whole module exists for. If it fails and the change was
    intentional, the correct response is a NEW version id — updating the digest
    in place re-uses a cache namespace for different text, which is exactly the
    bug WP0's multi-variant calibration would otherwise walk into.
    """
    assert registry_digests() == EXPECTED_DIGESTS


def test_every_registered_variant_is_pinned() -> None:
    """Adding a variant without pinning it must fail.

    Otherwise a fifth prompt could be added, spend real Bedrock money, and have
    its text drift afterwards with no test noticing — the pins would still be
    green because they only cover the four they know about.
    """
    assert set(PROMPTS) == set(EXPECTED_DIGESTS)
    assert set(all_versions()) == set(PROMPTS)
    assert all_versions() == CALIBRATION_ORDER


def test_umbrela_template_is_byte_identical_to_the_prior_bedrock_run() -> None:
    """`umbrela-v1` must reproduce the team's earlier prompt character-for-character.

    Its entire purpose is comparability with the existing umbrela-bedrock
    judgments (PLAN §3.2) — the plan knows the variant is degenerate on
    narratives and keeps it anyway as a continuity column. A single reworded
    clause makes that column incomparable, which is worse than not having it,
    because the report would present it as continuous with the old numbers.
    """
    # evaluation-results/ is gitignored (synced via Downloads, not git), so this
    # reads a committed one-row fixture copied from that run's tasks.jsonl instead
    # of the ~35 MB original — same first row, so the pin still holds.
    fixture = Path(__file__).parent / "data" / "umbrela_bedrock_sample_row.jsonl"
    row = json.loads(fixture.read_text(encoding="utf-8"))
    rendered = PROMPTS["umbrela-v1"].render(row["metadata"]["query"],
                                            row["metadata"]["passage"])
    assert rendered == row["instruction"]


def test_facet_v1_matches_the_text_measured_in_the_plan() -> None:
    """`facet-v1` must be the exact wording behind the n=60 measurement.

    PLAN §1 records grades `{0:7, 1:8, 2:36, 3:9}` for this prompt, and WP0's
    gate decision is made against that prior. The measurement is evidence about
    one specific string; a paraphrase inherits none of it, so the gate would be
    applied to a prompt nobody has ever measured.
    """
    plan = (REPO_ROOT / "tasks" / "bm25_tune" / "PLAN.md").read_text()
    start = plan.index("```\nYou are judging whether")
    end = plan.index("```", start + 4)
    assert plan[start + 4:end].rstrip("\n") == prompts.FACET_V1_TEMPLATE


def test_the_two_umbrela_variants_share_a_template_but_not_a_version() -> None:
    """Same rubric, different query slot — and therefore different cache keys.

    `umbrela-kw-v1` exists to isolate how much of `umbrela-v1`'s measured
    collapse is caused by the narrative target rather than the rubric. That only
    works if the two are separate cache namespaces despite identical text: a
    shared key would have the narrative run's grades served to the keyword run
    and the comparison would be vacuous.
    """
    narrative, keyword = PROMPTS["umbrela-v1"], PROMPTS["umbrela-kw-v1"]
    assert narrative.template == keyword.template
    assert narrative.version_id != keyword.version_id
    assert narrative.query_slot == "narrative"
    assert keyword.query_slot == "keyword"


@pytest.mark.parametrize("version_id", sorted(EXPECTED_DIGESTS))
def test_render_pair_puts_the_right_string_in_the_query_slot(
        version_id: str) -> None:
    """Each variant must receive the query text its `query_slot` names.

    Getting this backwards for one variant would mislabel a whole
    prompt-version's worth of cached judgments — they would be *valid* judgments
    of the wrong question, so the grade distribution would look plausible and the
    WP0 comparison across variants would be meaningless.
    """
    spec = PROMPTS[version_id]
    narrative = "NARRATIVE-SENTINEL about several facets of a need"
    keyword = "KEYWORD-SENTINEL terms"
    out = spec.render_pair(narrative=narrative, keyword=keyword,
                           passage="PASSAGE-SENTINEL")
    assert "PASSAGE-SENTINEL" in out
    if spec.query_slot == "narrative":
        assert narrative in out and keyword not in out
    else:
        assert keyword in out and narrative not in out


@pytest.mark.parametrize("version_id", sorted(EXPECTED_DIGESTS))
def test_render_leaves_no_unfilled_placeholder(version_id: str) -> None:
    """No `{q}`/`{p}` may survive rendering.

    A leftover placeholder would be sent to Bedrock verbatim: the judge would
    score a passage against the literal string `{q}`, return a confident grade,
    and the call would be billed and cached like any other. Nothing downstream
    distinguishes that from a real judgment.
    """
    out = PROMPTS[version_id].render("a query", "a passage")
    assert prompts.Q_TOKEN not in out
    assert prompts.P_TOKEN not in out


def test_rendering_preserves_braces_in_the_passage() -> None:
    """Passage text containing braces must survive verbatim.

    ClimbMix is web text: code blocks, JSON samples, and template syntax are
    routine. `str.format` would raise `KeyError`/`IndexError` on some of these and
    silently rewrite `{{` in others, so a fraction of passages would either crash
    the judge loop or reach the model altered.
    """
    passage = 'code: {"k": 1} and {q} and {p} and a lone { brace'
    out = PROMPTS["facet-v1"].render("Q", passage)
    assert passage in out


def test_rendering_does_not_let_the_query_inject_the_passage_slot() -> None:
    """A query containing `{p}` must not expand into the passage.

    Narratives are user-authored text. A single-pass substitution means a
    `{p}`-bearing narrative is inserted literally rather than being re-scanned —
    otherwise a crafted (or merely unlucky) topic could duplicate or displace the
    passage the judge is supposed to grade.
    """
    out = PROMPTS["facet-v1"].render("need mentioning {p} explicitly",
                                     "REAL-PASSAGE")
    assert out.count("REAL-PASSAGE") == 1
    assert "{p} explicitly" in out


def test_grade_line_contract_is_shared_with_the_parser() -> None:
    """The regex that reads the grade must match what the prompts ask for.

    Prompt and parser are one contract. If they drifted, every call would be
    billed, return a perfectly good `##final score:` line, and be recorded as a
    parse failure — burning the budget while producing an empty qrel.
    """
    for version_id in all_versions():
        spec = PROMPTS[version_id]
        assert "##final score:" in spec.template
        assert prompts.GRADE_RE.search("##final score: 2").group(1) == "2"
        assert prompts.GRADE_RE.search("##Final Score:  3").group(1) == "3"
        assert prompts.GRADE_RE.search("final score: 4") is None
        assert spec.emits_facet == ("##facet:" in spec.template)


FACET_EMITTERS = ("facet-name-v1", "facet-rare3-v1")


@pytest.mark.parametrize("version_id", FACET_EMITTERS)
def test_facet_naming_variants_ask_for_and_can_parse_a_facet_line(
        version_id: str) -> None:
    """The facet-naming variants request `##facet:` first, in a parseable format.

    The forced facet naming is the entire mechanism by which these variants are
    supposed to break the measured 60 % grade-2 pile-up (PLAN §3.2). If the line
    were unrequested, misordered, or unparseable, a variant would be
    indistinguishable from `facet-v1` while costing a second full 280-pair pass to
    find that out.
    """
    spec = PROMPTS[version_id]
    assert spec.emits_facet is True
    assert spec.template.index("##facet:") < spec.template.index(
        "##final score:")
    match = prompts.FACET_RE.search("##facet: hiring and promotion\n"
                                    "##final score: 3")
    assert match is not None and match.group(1).strip() == \
        "hiring and promotion"


def test_only_the_facet_naming_variants_emit_a_facet_line() -> None:
    """`emits_facet` must be false for every other variant.

    The driver uses the flag to decide whether a missing `##facet:` is worth
    recording. A variant flagged as an emitter without asking for the line would
    log a facet-parse miss on every single call — thousands of spurious warnings
    that would train the operator to ignore the one that matters.
    """
    assert {v for v in all_versions()
            if PROMPTS[v].emits_facet} == set(FACET_EMITTERS)


def test_only_facet_rare3_states_a_base_rate_and_states_it_both_ways() -> None:
    """`facet-rare3-v1` must carry the base-rate anchor AND its counterweight.

    This is the one variant that answers the user's 2026-07-31 constraint ("most
    of the documents in the collection are not relevant, and only very few should
    receive the highest score… it shouldn't be too harsh either"), and it is the
    only place in the harness where grade *frequency* is stated rather than left to
    emerge from rubric wording. Half of it is load-bearing on its own: keep only
    the scarcity clause and the variant becomes a deliberately harsh judge, which
    PLAN §3.3's lower bound then rejects — the second full 280-pair pass spent
    finding that out is the cost of this test not existing.
    """
    spec = PROMPTS["facet-rare3-v1"]
    assert "MOST of them are not useful evidence" in spec.template
    assert "3 to only a small minority" in spec.template
    assert "do not be stingy" in spec.template
    # The other four say nothing about frequency; if one starts to, the variant
    # comparison stops isolating the anchor and this must be revisited.
    for other in (v for v in all_versions() if v != "facet-rare3-v1"):
        assert "stingy" not in PROMPTS[other].template
        assert "small minority" not in PROMPTS[other].template


def test_facet_rare3_keeps_facet_name_v1s_rubric_skeleton() -> None:
    """The new variant must differ from `facet-name-v1` *only* by calibration.

    WP0 reads the pair as a controlled contrast: same forced facet-naming step,
    same four-grade scale, same output format, one added base-rate paragraph. If
    the rubric drifted too, a distribution difference between them would no longer
    attribute to the anchor, and the plan's going-in expectation (§3.3) would be
    resting on a comparison that does not isolate anything.
    """
    base, anchored = PROMPTS["facet-name-v1"], PROMPTS["facet-rare3-v1"]
    assert base.query_slot == anchored.query_slot
    assert base.emits_facet == anchored.emits_facet
    for shared in ("Before scoring, name in 10 words or fewer",
                   "##facet: <10 words or fewer, or none>",
                   "##final score: <0-3>",
                   "Judge usefulness for one or more facets"):
        assert shared in base.template and shared in anchored.template
    assert "Calibration" not in base.template
    assert len(anchored.template) > len(base.template)


def test_unknown_version_raises_instead_of_defaulting() -> None:
    """A typo'd `prompt_version` must fail, not silently mint a cache namespace.

    Defaulting would be expensive as well as wrong: an unrecognized id maps to no
    cached judgments, so the run would re-judge — and re-bill — the entire pool
    while writing its results under a name no report refers to.
    """
    with pytest.raises(UnknownPromptVersion, match="facet-v9"):
        get_prompt("facet-v9")
    assert get_prompt(DEFAULT_PROMPT_VERSION).version_id == \
        DEFAULT_PROMPT_VERSION
    assert DEFAULT_PROMPT_VERSION in PROMPTS


def test_specs_are_frozen_so_a_template_cannot_be_patched_at_runtime() -> None:
    """`PromptSpec` immutability keeps the digest a true description of the text.

    A mutable spec could be edited after `registry_digests()` was read — by a
    test helper, or by a well-meant "just tweak the wording" in the driver — and
    the logged `prompt_sha256` would then describe a prompt that was never sent.
    """
    spec = PROMPTS["facet-v1"]
    with pytest.raises(Exception):
        spec.template = "something else"  # type: ignore[misc]
    assert spec.template_sha256 == sha256_text(spec.template)
