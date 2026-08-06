"""Harness-owned obligation/evidence ledger for the terminal answer path.

The original v2 pipeline hands a prose plan to the research model and later
accepts any globally valid cited report.  That leaves no executable link
between a planned obligation, the search issued for it, the evidence retained,
and the sentence that finally answers it.  This module supplies that link
without asking another model to rewrite the answer.

The contract is intentionally semantic-light.  The harness can prove that all
rows were routed through the pipeline, that exact required terms survived, and
that cited evidence was explicitly mapped to the row it is claimed to support.
It cannot prove entailment; the research model still owns that judgment.
"""
from __future__ import annotations

import copy
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from aus_agent.tools import COMMIT_CONTEXT_TOOL


_PLAN_ITEM_RE = re.compile(
    r"(?ms)^\s*\d+\.\s*([A-Z][A-Z _/-]{1,30}):\s*(.*?)"
    r"(?=^\s*\d+\.|\Z)"
)
_EXACT_RE = re.compile(r"\s+EXACT:\s*(.*?)(?=\s+SEARCH:|\.?\s*$)", re.I)
_SEARCH_SUFFIX_RE = re.compile(r"\s+SEARCH:\s*.*?\.?\s*$", re.I)
_CITATIONISH_RE = re.compile(r"\[[\w.-]+(?:[,;\s]+[\w.-]+)*\]")

_NO_ANSWER_KINDS = {"budget", "penalty"}
_NO_RESEARCH_KINDS = {"deliverable", "audience", "format", "budget", "penalty"}


@dataclass(frozen=True)
class ContractItem:
    """One stable, independently checkable answer obligation."""

    id: str
    origin: str
    kind: str
    requirement: str
    must_mention: tuple[str, ...] = ()
    must_research: bool = True
    must_answer: bool = True


@dataclass(frozen=True)
class EvidenceAnchor:
    """A model-selected statement that one committed unit establishes."""

    document_id: str
    claim: str
    value_scope: str = ""


@dataclass
class EvidenceLedger:
    """Deterministic search and support state keyed by contract item id."""

    attempted_queries: dict[str, list[str]] = field(default_factory=dict)
    anchors: dict[str, list[EvidenceAnchor]] = field(default_factory=dict)

    def record_search(self, requirement_ids: list[str], query: str) -> None:
        """Record one actually dispatched query against every declared row."""
        compact = " ".join(query.split())[:500]
        for requirement_id in requirement_ids:
            values = self.attempted_queries.setdefault(requirement_id, [])
            if compact and compact not in values:
                values.append(compact)

    def record_supports(
        self,
        supports: dict[str, list[EvidenceAnchor]],
    ) -> None:
        """Merge validated commit anchors without duplicating retries."""
        for requirement_id, additions in supports.items():
            current = self.anchors.setdefault(requirement_id, [])
            for anchor in additions:
                if anchor not in current:
                    current.append(anchor)


SUBMIT_ANSWER_TOOL: dict[str, Any] = {
    "name": "submit_answer",
    "description": (
        "Submit the final answer and its obligation coverage in one terminal "
        "call. Use only after research is complete and no staged batch is "
        "open. Each item is one answer sentence or a short nonfactual label. "
        "Attach committed evidence ids and the exact coverage-contract ids "
        "that the item satisfies. Every must-answer id must be satisfied or "
        "listed as unresolved. This call replaces a free-prose answer turn."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "sentences": {
                "type": "array",
                "minItems": 1,
                "maxItems": 96,
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {
                            "type": "string",
                            "description": (
                                "One final answer sentence, or a short "
                                "nonfactual part label when the requested "
                                "deliverable needs visible parts. Do not put "
                                "citation markers in this field."
                            ),
                        },
                        "evidence_ids": {
                            "type": "array",
                            "maxItems": 3,
                            "items": {"type": "string"},
                        },
                        "satisfies": {
                            "type": "array",
                            "maxItems": 8,
                            "items": {"type": "string"},
                        },
                    },
                    "required": ["text", "evidence_ids", "satisfies"],
                },
            },
            "unresolved": {
                "type": "array",
                "maxItems": 24,
                "items": {"type": "string"},
                "description": (
                    "Contract ids that cannot be answered honestly from the "
                    "available evidence. A research-required id may appear "
                    "here only after at least one tagged search attempt."
                ),
            },
        },
        "required": ["sentences", "unresolved"],
    },
}


def _compact(value: Any, limit: int = 600) -> str:
    """Collapse model whitespace while keeping bounded trace strings."""
    return " ".join(str(value or "").split())[:limit]


def build_coverage_contract(
    plan: str,
    scout_additions: list[dict[str, Any]] | None = None,
) -> list[ContractItem]:
    """Parse the plan and structured scout rows into stable ``P``/``S`` ids.

    ``merge_plan_critique`` flattens a scout row to the label ``SCOUT``.  When
    its structured source is available, use that instead so ``format`` and
    ``penalty`` keep their distinct closure semantics.
    """
    items: list[ContractItem] = []
    p_index = 0
    s_index = 0
    for match in _PLAN_ITEM_RE.finditer(plan):
        raw_kind = _compact(match.group(1), 40).casefold().replace(" ", "_")
        body = _compact(match.group(2))
        if not body:
            continue
        is_scout = raw_kind == "scout"
        if is_scout and scout_additions is not None:
            continue
        if is_scout:
            s_index += 1
            item_id = f"S{s_index:02d}"
            origin = "scout"
            kind = "scout"
        else:
            p_index += 1
            item_id = f"P{p_index:02d}"
            origin = "planner"
            kind = raw_kind

        exact_match = _EXACT_RE.search(body)
        mentions = tuple(
            value.strip()[:80]
            for value in (exact_match.group(1).split(";") if exact_match else [])
            if value.strip()
        )
        requirement = _EXACT_RE.sub("", body)
        requirement = _SEARCH_SUFFIX_RE.sub("", requirement).strip().rstrip(".")
        if not requirement:
            continue
        items.append(ContractItem(
            id=item_id,
            origin=origin,
            kind=kind,
            requirement=requirement,
            must_mention=mentions,
            must_research=kind not in _NO_RESEARCH_KINDS,
            must_answer=kind not in _NO_ANSWER_KINDS,
        ))
    if scout_additions is not None:
        for raw in scout_additions:
            requirement = _compact(raw.get("requirement"))
            if not requirement:
                continue
            s_index += 1
            kind = _compact(raw.get("kind"), 40).casefold() or "term"
            mentions = tuple(
                _compact(value, 80)
                for value in raw.get("must_mention", [])[:3]
                if _compact(value, 80)
            )
            items.append(ContractItem(
                id=f"S{s_index:02d}",
                origin="scout",
                kind=kind,
                requirement=requirement,
                must_mention=mentions,
                must_research=kind not in _NO_RESEARCH_KINDS,
                must_answer=kind not in _NO_ANSWER_KINDS,
            ))
    return items


def render_research_contract(items: list[ContractItem]) -> str:
    """Render the compact protocol and stable ids for the research context."""
    lines = [
        "EXECUTABLE COVERAGE CONTRACT",
        "The ids below are harness-owned. Tag every search with the ids it "
        "investigates, map committed evidence to the ids it directly supports, "
        "and finish with submit_answer. Do not write a free-prose final turn.",
        "A nonfactual label may satisfy a deliverable/format row without a "
        "citation; factual rows need directly mapped committed evidence. "
        "Untagged synthesis sentences are allowed. For a requested series or "
        "repeated deliverable, use a plain label prefix on each part's opening "
        "sentence (for example, 'Blog post 1 — ...'); do not enable broad "
        "Markdown, tables, or uncited factual cells.",
    ]
    for item in items:
        flags = []
        if item.must_research:
            flags.append("research")
        if item.must_answer:
            flags.append("answer")
        line = f"{item.id} [{item.kind}; {'+'.join(flags) or 'constraint'}] {item.requirement}"
        if item.must_mention:
            line += " | EXACT: " + "; ".join(item.must_mention)
        lines.append(line)
    return "\n".join(lines)


def search_tool_with_contract(tool: dict[str, Any]) -> dict[str, Any]:
    """Require every search to declare which contract rows it investigates."""
    result = copy.deepcopy(tool)
    schema = result["input_schema"]
    schema["properties"]["for_requirements"] = {
        "type": "array",
        "minItems": 1,
        "maxItems": 12,
        "items": {"type": "string"},
        "description": (
            "Stable coverage-contract ids this query investigates. Tag the "
            "purpose, not documents: adjacent pages do not count as support "
            "until commit_context maps them explicitly."
        ),
    }
    required = list(schema.get("required", []))
    if "for_requirements" not in required:
        required.append("for_requirements")
    schema["required"] = required
    return result


def commit_tool_with_contract() -> dict[str, Any]:
    """Return the v2-local commit schema with bounded requirement anchors."""
    tool = copy.deepcopy(COMMIT_CONTEXT_TOOL)
    item = tool["input_schema"]["properties"]["documents"]["items"]
    item["properties"]["supports"] = {
        "type": "array",
        "maxItems": 12,
        "description": (
            "Coverage rows this exact selected unit directly supports. Keep "
            "the anchor concrete and source-bounded; an empty list is valid "
            "for a document retained only as background."
        ),
        "items": {
            "type": "object",
            "properties": {
                "requirement_id": {"type": "string"},
                "claim": {
                    "type": "string",
                    "description": "What this unit directly establishes.",
                },
                "value_scope": {
                    "type": "string",
                    "description": (
                        "Exact value, population, jurisdiction, date, or other "
                        "boundary needed to finish the claim."
                    ),
                },
            },
            "required": ["requirement_id", "claim"],
        },
    }
    return tool


def normalize_requirement_ids(
    values: Any,
    items: list[ContractItem],
) -> tuple[list[str], list[str]]:
    """Validate a model-supplied id list against the current contract."""
    if not isinstance(values, list) or not values:
        return [], ["for_requirements must be a non-empty array"]
    known = {item.id for item in items}
    clean: list[str] = []
    errors: list[str] = []
    for value in values[:12]:
        item_id = str(value).strip()
        if item_id not in known:
            errors.append(f"unknown coverage-contract id {item_id!r}")
        elif item_id not in clean:
            clean.append(item_id)
    return clean, errors


def normalize_commit_supports(
    arguments: dict[str, Any],
    items: list[ContractItem],
) -> tuple[dict[str, list[EvidenceAnchor]], list[str]]:
    """Validate selected-unit support mappings before mutating context state."""
    known = {item.id for item in items}
    supports: dict[str, list[EvidenceAnchor]] = {}
    errors: list[str] = []
    documents = arguments.get("documents")
    if not isinstance(documents, list):
        return supports, ["documents must be an array"]
    for doc_index, document in enumerate(documents, 1):
        if not isinstance(document, dict):
            continue  # base commit validation reports this more precisely
        document_id = str(document.get("id") or "").strip()
        raw_supports = document.get("supports", [])
        if not isinstance(raw_supports, list):
            errors.append(f"document {doc_index} supports must be an array")
            continue
        for support_index, raw in enumerate(raw_supports[:12], 1):
            if not isinstance(raw, dict):
                errors.append(
                    f"document {doc_index} support {support_index} is not an object")
                continue
            requirement_id = str(raw.get("requirement_id") or "").strip()
            claim = _compact(raw.get("claim"), 500)
            value_scope = _compact(raw.get("value_scope"), 300)
            if requirement_id not in known:
                errors.append(
                    f"unknown coverage-contract id {requirement_id!r} in "
                    f"document {document_id!r}")
                continue
            if not document_id or not claim:
                errors.append(
                    f"document {doc_index} support {support_index} needs id and claim")
                continue
            anchor = EvidenceAnchor(document_id, claim, value_scope)
            values = supports.setdefault(requirement_id, [])
            if anchor not in values:
                values.append(anchor)
    return supports, errors


def validate_support_routes(
    supports: dict[str, list[EvidenceAnchor]],
    staged_documents: list[dict[str, Any]],
) -> list[str]:
    """Require commit support to follow the search purpose that found the unit."""
    purposes: dict[str, set[str]] = {}
    for document in staged_documents:
        document_id = str(document.get("id") or "").strip()
        metadata = document.get("metadata")
        values = metadata.get("for_requirements", []) if isinstance(
            metadata, dict) else []
        purposes.setdefault(document_id, set()).update(
            str(value).strip() for value in values if str(value).strip())
    errors: list[str] = []
    for requirement_id, anchors in supports.items():
        for anchor in anchors:
            if requirement_id not in purposes.get(anchor.document_id, set()):
                errors.append(
                    f"document {anchor.document_id!r} was not retrieved for "
                    f"coverage row {requirement_id}")
    return errors


def validate_submission(
    arguments: dict[str, Any],
    items: list[ContractItem],
    ledger: EvidenceLedger,
    committed_ids: set[str],
    *,
    max_words: int = 1024,
) -> tuple[list[dict[str, Any]] | None, list[str], dict[str, Any]]:
    """Validate a terminal answer against every executable contract row."""
    by_id = {item.id: item for item in items}
    raw_sentences = arguments.get("sentences")
    raw_unresolved = arguments.get("unresolved")
    errors: list[str] = []
    if not isinstance(raw_sentences, list) or not raw_sentences:
        return None, ["sentences must be a non-empty array"], {}
    if not isinstance(raw_unresolved, list):
        return None, ["unresolved must be an array"], {}

    unresolved: list[str] = []
    for value in raw_unresolved[:24]:
        item_id = str(value).strip()
        if item_id not in by_id:
            errors.append(f"unknown unresolved coverage-contract id {item_id!r}")
        elif item_id not in unresolved:
            unresolved.append(item_id)

    sentences: list[dict[str, Any]] = []
    tagged_text: dict[str, list[str]] = {}
    satisfied: set[str] = set()
    for index, raw in enumerate(raw_sentences[:96], 1):
        if not isinstance(raw, dict):
            errors.append(f"sentence {index} is not an object")
            continue
        text = _compact(raw.get("text"), 8_000)
        if not text:
            errors.append(f"sentence {index} has empty text")
            continue
        if _CITATIONISH_RE.search(text):
            errors.append(
                f"sentence {index} contains citation markers; use evidence_ids")
        raw_evidence = raw.get("evidence_ids")
        raw_satisfies = raw.get("satisfies")
        if not isinstance(raw_evidence, list):
            errors.append(f"sentence {index} evidence_ids must be an array")
            raw_evidence = []
        if not isinstance(raw_satisfies, list):
            errors.append(f"sentence {index} satisfies must be an array")
            raw_satisfies = []

        evidence_ids: list[str] = []
        for value in raw_evidence[:3]:
            document_id = str(value).strip()
            if document_id not in committed_ids:
                errors.append(
                    f"sentence {index} cites uncommitted id {document_id!r}")
            elif document_id not in evidence_ids:
                evidence_ids.append(document_id)
        satisfies: list[str] = []
        for value in raw_satisfies[:8]:
            item_id = str(value).strip()
            if item_id not in by_id:
                errors.append(
                    f"sentence {index} tags unknown coverage-contract id {item_id!r}")
            elif item_id not in satisfies:
                satisfies.append(item_id)
                satisfied.add(item_id)
                tagged_text.setdefault(item_id, []).append(text)

        for item_id in satisfies:
            item = by_id[item_id]
            if not item.must_research:
                continue
            mapped = {
                anchor.document_id for anchor in ledger.anchors.get(item_id, [])
            }
            if not evidence_ids:
                errors.append(
                    f"sentence {index} satisfies research row {item_id} "
                    "without evidence_ids")
            elif not any(document_id in mapped for document_id in evidence_ids):
                errors.append(
                    f"sentence {index} has no evidence explicitly mapped to {item_id}")
        sentences.append({"text": text, "citations": evidence_ids})

    overlap = satisfied.intersection(unresolved)
    if overlap:
        errors.append(
            "coverage ids cannot be both satisfied and unresolved: "
            + ", ".join(sorted(overlap)))
    required = {item.id for item in items if item.must_answer}
    missing = required - satisfied - set(unresolved)
    if missing:
        errors.append(
            "must-answer coverage ids missing from both sentences and unresolved: "
            + ", ".join(sorted(missing)))
    for item_id in unresolved:
        item = by_id[item_id]
        if item.must_research and not ledger.attempted_queries.get(item_id):
            errors.append(
                f"unresolved research row {item_id} has no tagged search attempt")
    for item in items:
        if item.id not in satisfied or not item.must_mention:
            continue
        haystack = " ".join(tagged_text.get(item.id, [])).casefold()
        absent = [term for term in item.must_mention if term.casefold() not in haystack]
        if absent:
            errors.append(
                f"coverage row {item.id} is tagged but omits exact term(s): "
                + ", ".join(absent))

    words = sum(len(sentence["text"].split()) for sentence in sentences)
    if words > max_words:
        errors.append(f"answer is {words} words; hard maximum is {max_words}")
    if committed_ids and not any(sentence["citations"] for sentence in sentences):
        errors.append("no answer sentence cites committed evidence")

    stats = {
        "contract_items": len(items),
        "must_answer": len(required),
        "satisfied": len(satisfied),
        "unresolved": len(unresolved),
        "missing": sorted(missing),
        "words": words,
        "search_rows": len(ledger.attempted_queries),
        "supported_rows": len(ledger.anchors),
        "anchors": sum(len(values) for values in ledger.anchors.values()),
    }
    if errors:
        return None, errors, stats
    return sentences, [], stats


def contract_trace(items: list[ContractItem], ledger: EvidenceLedger) -> dict[str, Any]:
    """Serialize current contract state for durable diagnostics."""
    return {
        "items": [
            {**asdict(item), "must_mention": list(item.must_mention)}
            for item in items
        ],
        "attempted_queries": {
            key: list(values) for key, values in ledger.attempted_queries.items()
        },
        "anchors": {
            key: [asdict(anchor) for anchor in values]
            for key, values in ledger.anchors.items()
        },
    }


def render_contract_status(
    items: list[ContractItem],
    ledger: EvidenceLedger,
    *,
    max_chars: int = 6_000,
) -> str:
    """Render a bounded recency handoff from selected anchors, not all facts."""
    lines = ["COVERAGE CLOSURE STATUS"]
    for item in items:
        anchors = ledger.anchors.get(item.id, [])
        if anchors:
            anchor_text = " ; ".join(
                f"[{anchor.document_id}] {anchor.claim}"
                + (f" | {anchor.value_scope}" if anchor.value_scope else "")
                for anchor in anchors[:2]
            )
            line = f"{item.id} SUPPORTED: {anchor_text}"
        elif item.must_research:
            attempts = len(ledger.attempted_queries.get(item.id, []))
            line = f"{item.id} OPEN: no committed support; searches={attempts}"
        else:
            line = f"{item.id} STRUCTURAL: answer directly from the request"
        if sum(len(value) + 1 for value in lines) + len(line) > max_chars:
            lines.append("... status truncated at the harness bound")
            break
        lines.append(line)
    return "\n".join(lines)


def submit_answer_request(
    items: list[ContractItem],
    ledger: EvidenceLedger | None = None,
) -> str:
    """Compact correction when the model tries free prose or misses rows."""
    required = ", ".join(item.id for item in items if item.must_answer)
    request = (
        "Do not write the final answer as free prose. Research is complete only "
        "through the terminal submit_answer tool. Call submit_answer now and "
        "tag every final sentence with the coverage ids it satisfies. Every "
        f"must-answer id must be satisfied or honestly unresolved: {required}."
    )
    if ledger is not None:
        request += "\n\n" + render_contract_status(items, ledger)
    return request
