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

from .answer_form import AnswerFormPolicy


_PLAN_ITEM_RE = re.compile(
    r"(?ms)^\s*\d+\.\s*(?:\*\*)?([A-Z][A-Z _/-]{1,30}):"
    r"(?:\*\*)?\s*(.*?)"
    r"(?=^\s*\d+\.|\Z)"
)
_EXACT_RE = re.compile(r"\s+EXACT:\s*(.*?)(?=\s+SEARCH:|\.?\s*$)", re.I)
_SEARCH_SUFFIX_RE = re.compile(r"\s+SEARCH:\s*.*?\.?\s*$", re.I)
_CITATIONISH_RE = re.compile(r"\[[\w.-]+(?:[,;\s]+[\w.-]+)*\]")

_NO_ANSWER_KINDS = {"budget", "penalty"}
_NO_RESEARCH_KINDS = {"deliverable", "audience", "format", "budget", "penalty"}
_UNINFORMATIVE_ANCHOR_TERMS = {
    "a", "amount", "amounts", "an", "and", "article", "authors", "change",
    "changes", "claim", "data", "date", "dates", "document", "effect",
    "effects", "evidence", "finding", "findings", "for", "from", "in",
    "information", "measure", "measured", "number", "numbers", "of", "paper",
    "population", "populations", "reported", "research", "result", "results",
    "said", "scope", "source", "states", "study", "that", "the", "this", "to",
    "value", "values", "with",
}
_ANCHOR_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")
_ANCHOR_CLAIM_MAX_CHARS = 500
_ANCHOR_SCOPE_MAX_CHARS = 300
_ANCHOR_TERM_MAX_CHARS = 80
_ANCHOR_TERMS_MAX_ITEMS = 4
_NEGATIVE_ANCHOR_TOKENS = {
    "failed", "failure", "lack", "lacked", "lacks", "neither", "never",
    "no", "none", "not", "without", "zero",
}


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
    must_include: tuple[str, ...] = ()


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
        "open. Each typed item is prose, a request-authorized nonfactual "
        "label, or request-authorized raw Python. "
        "Attach committed evidence ids and the exact coverage-contract ids "
        "that the item satisfies. Every must-answer id must be satisfied or "
        "listed as unresolved. This call replaces a free-prose answer turn."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "answer_items": {
                "type": "array",
                "minItems": 1,
                "maxItems": 96,
                "items": {
                    "type": "object",
                    "properties": {
                        "kind": {
                            "type": "string",
                            "enum": ["prose", "label", "code"],
                            "description": (
                                "Use prose normally. Use label only for an "
                                "explicit repeated deliverable and code only "
                                "when the coverage contract authorizes Python."
                            ),
                        },
                        "text": {
                            "type": "string",
                            "maxLength": 8000,
                            "description": (
                                "One prose answer unit, a short nonfactual "
                                "part label, or raw complete multiline Python. "
                                "Code has no Markdown fences. Do not put "
                                "citation markers in prose or label text."
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
                    "required": [
                        "kind", "text", "evidence_ids", "satisfies"],
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
        "required": ["answer_items", "unresolved"],
    },
}


def submit_answer_tool(policy: AnswerFormPolicy) -> dict[str, Any]:
    """Return a tool description that advertises only request-authorized forms."""
    tool = copy.deepcopy(SUBMIT_ANSWER_TOOL)
    if policy.python_code:
        tool["description"] += (
            " This request authorizes raw Python code items; their syntax is "
            "compiled before acceptance."
        )
    else:
        tool["description"] += " This request does not authorize code items."
    if policy.minimum_labels:
        tool["description"] += (
            f" Use at least {policy.minimum_labels} distinct "
            f"{policy.repeated_label} label items."
        )
    return tool


def _compact(value: Any, limit: int = 600) -> str:
    """Collapse model whitespace while keeping bounded trace strings."""
    return " ".join(str(value or "").split())[:limit]


def _contains_exact_term(text: str, term: str) -> bool:
    """Match a normalized literal without accepting alphanumeric substrings."""
    normalized_text = " ".join(str(text or "").split())
    normalized_term = " ".join(str(term or "").split())
    if not normalized_term:
        return False
    left = r"(?<![A-Za-z0-9])" if normalized_term[0].isalnum() else ""
    right = r"(?![A-Za-z0-9])" if normalized_term[-1].isalnum() else ""
    return bool(re.search(
        left + re.escape(normalized_term) + right,
        normalized_text,
        re.IGNORECASE,
    ))


def _material_anchor_term(term: str) -> bool:
    """Reject generic or fragmentary literals that do not finish a claim."""
    tokens = _ANCHOR_TOKEN_RE.findall(term)
    if not tokens or term.casefold() in _UNINFORMATIVE_ANCHOR_TERMS:
        return False
    if any(any(character.isdigit() for character in token) for token in tokens):
        return True
    content = [
        token for token in tokens
        if token.casefold() not in _UNINFORMATIVE_ANCHOR_TERMS
    ]
    # A source-verbatim negative finding can be substantive even when the
    # noun by itself is generic ("no evidence", "no effect"). Exact claim,
    # source, route, and final-answer checks still apply to the whole phrase.
    if (len(tokens) >= 2
            and any(token.casefold() in _NEGATIVE_ANCHOR_TOKENS
                    for token in tokens)):
        return True
    if len(content) >= 2:
        return True
    if len(content) == 1:
        token = content[0]
        return (
            (len(token) >= 2 and any(character.isupper() for character in token))
            or len(token) >= 4
        )
    return False


def build_coverage_contract(
    plan: str,
    scout_additions: list[dict[str, Any]] | None = None,
    *,
    answer_form: AnswerFormPolicy | None = None,
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
    answer_form = answer_form or AnswerFormPolicy()
    f_index = 0
    if answer_form.python_code:
        f_index += 1
        items.append(ContractItem(
            id=f"F{f_index:02d}",
            origin="request",
            kind="python_code",
            requirement=(
                "Provide syntactically valid raw Python for the requested key "
                "components, preserving indentation and operators"
            ),
            must_research=False,
            must_answer=True,
        ))
    if answer_form.minimum_labels:
        f_index += 1
        items.append(ContractItem(
            id=f"F{f_index:02d}",
            origin="request",
            kind="repeated_labels",
            requirement=(
                f"Separate the requested series with at least "
                f"{answer_form.minimum_labels} distinct plain "
                f"{answer_form.repeated_label} labels"
            ),
            must_research=False,
            must_answer=True,
        ))
    return items


def render_research_contract(
    items: list[ContractItem],
    answer_form: AnswerFormPolicy | None = None,
) -> str:
    """Render the compact protocol and stable ids for the research context."""
    lines = [
        "EXECUTABLE COVERAGE CONTRACT",
        "The ids below are harness-owned. Tag every search with the ids it "
        "investigates, map committed evidence to the ids it directly supports, "
        "and finish with submit_answer. Do not write a free-prose final turn.",
        "Factual prose rows need directly mapped committed evidence and must "
        "carry the selected anchor's exact name/value/scope terms. Untagged "
        "synthesis prose is allowed. Do not enable broad Markdown, tables, or "
        "uncited factual cells.",
    ]
    answer_form = answer_form or AnswerFormPolicy()
    if answer_form.minimum_labels:
        lines.append(
            f"This request authorizes plain nonfactual label items: use at "
            f"least {answer_form.minimum_labels} distinct "
            f"'{answer_form.repeated_label} N —' labels. Labels carry no "
            "citations; cite the factual prose item that follows."
        )
    if answer_form.python_code:
        lines.append(
            "This request authorizes raw multiline Python code items without "
            "Markdown fences. Preserve indentation and bracket expressions. "
            "Code may be uncited original synthesis; keep evidence-grounded "
            "architecture and performance claims in cited prose items."
        )
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
                    "maxLength": _ANCHOR_CLAIM_MAX_CHARS,
                    "description": "What this unit directly establishes.",
                },
                "value_scope": {
                    "type": "string",
                    "maxLength": _ANCHOR_SCOPE_MAX_CHARS,
                    "description": (
                        "Exact value, population, jurisdiction, date, or other "
                        "boundary needed to finish the claim."
                    ),
                },
                "must_include": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": _ANCHOR_TERMS_MAX_ITEMS,
                    "items": {
                        "type": "string",
                        "maxLength": _ANCHOR_TERM_MAX_CHARS,
                    },
                    "description": (
                        "One to four short, complete, exact source-supported "
                        "names, values, dates, populations, negative findings, "
                        "or scope qualifiers that occur verbatim in claim or "
                        "value_scope and that a final sentence using this "
                        "anchor must repeat verbatim. Never paste a long "
                        "sentence or rely on truncation."
                    ),
                },
            },
            "required": ["requirement_id", "claim", "must_include"],
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
        if len(raw_supports) > 12:
            errors.append(
                f"document {document_id!r} has {len(raw_supports)} supports; "
                "maximum is 12")
            continue
        for support_index, raw in enumerate(raw_supports, 1):
            if not isinstance(raw, dict):
                errors.append(
                    f"document {doc_index} support {support_index} is not an object")
                continue
            requirement_id = str(raw.get("requirement_id") or "").strip()
            raw_claim = raw.get("claim")
            raw_value_scope = raw.get("value_scope", "")
            claim = (
                " ".join(raw_claim.split())
                if isinstance(raw_claim, str) else ""
            )
            value_scope = (
                " ".join(raw_value_scope.split())
                if isinstance(raw_value_scope, str) else ""
            )
            raw_must_include = raw.get("must_include")
            if requirement_id not in known:
                errors.append(
                    f"unknown coverage-contract id {requirement_id!r} in "
                    f"document {document_id!r}")
                continue
            if not isinstance(raw_claim, str):
                errors.append(
                    f"document {document_id!r} support {support_index} claim "
                    "must be a string")
                continue
            if not document_id or not claim:
                errors.append(
                    f"document {doc_index} support {support_index} needs id and claim")
                continue
            if len(claim) > _ANCHOR_CLAIM_MAX_CHARS:
                errors.append(
                    f"document {document_id!r} support {support_index} claim "
                    f"is {len(claim)} characters; maximum is "
                    f"{_ANCHOR_CLAIM_MAX_CHARS}")
                continue
            if not isinstance(raw_value_scope, str):
                errors.append(
                    f"document {document_id!r} support {support_index} "
                    "value_scope must be a string")
                continue
            if len(value_scope) > _ANCHOR_SCOPE_MAX_CHARS:
                errors.append(
                    f"document {document_id!r} support {support_index} "
                    f"value_scope is {len(value_scope)} characters; maximum "
                    f"is {_ANCHOR_SCOPE_MAX_CHARS}")
                continue
            if not isinstance(raw_must_include, list) or not raw_must_include:
                errors.append(
                    f"document {document_id!r} support {support_index} needs "
                    "a non-empty must_include array")
                continue
            if len(raw_must_include) > _ANCHOR_TERMS_MAX_ITEMS:
                errors.append(
                    f"document {document_id!r} support {support_index} has "
                    f"{len(raw_must_include)} must_include terms; maximum is "
                    f"{_ANCHOR_TERMS_MAX_ITEMS}")
                continue
            must_include: list[str] = []
            term_errors: list[str] = []
            for raw_term in raw_must_include:
                if not isinstance(raw_term, str):
                    term_errors.append(
                        f"document {document_id!r} support {support_index} has "
                        "a non-string must_include term")
                    continue
                term = " ".join(raw_term.split())
                if len(term) > _ANCHOR_TERM_MAX_CHARS:
                    term_errors.append(
                        f"document {document_id!r} support {support_index} has "
                        f"a {len(term)}-character must_include term; maximum is "
                        f"{_ANCHOR_TERM_MAX_CHARS}; submit a shorter complete "
                        "source-verbatim fragment")
                    continue
                if not term or not _material_anchor_term(term):
                    term_errors.append(
                        f"document {document_id!r} support {support_index} has "
                        f"an uninformative must_include term {term!r}")
                elif not _contains_exact_term(
                        f"{claim} {value_scope}", term):
                    term_errors.append(
                        f"document {document_id!r} support {support_index} has "
                        f"must_include term {term!r} outside its claim/scope")
                elif term not in must_include:
                    must_include.append(term)
            # Never silently filter a bad requested invariant. A mixed row is
            # corrected as a unit so trace state and model intent cannot
            # disagree about which literals the final answer must carry.
            if term_errors:
                errors.extend(term_errors)
                continue
            anchor = EvidenceAnchor(
                document_id, claim, value_scope, tuple(must_include))
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
    source_text: dict[str, str] = {}
    for document in staged_documents:
        document_id = str(document.get("id") or "").strip()
        metadata = document.get("metadata")
        values = metadata.get("for_requirements", []) if isinstance(
            metadata, dict) else []
        purposes.setdefault(document_id, set()).update(
            str(value).strip() for value in values if str(value).strip())
        source_text[document_id] = str(document.get("text") or "").casefold()
    errors: list[str] = []
    for requirement_id, anchors in supports.items():
        for anchor in anchors:
            if requirement_id not in purposes.get(anchor.document_id, set()):
                errors.append(
                    f"document {anchor.document_id!r} was not retrieved for "
                    f"coverage row {requirement_id}")
            missing_terms = [
                term for term in anchor.must_include
                if not _contains_exact_term(
                    source_text.get(anchor.document_id, ""), term)
            ]
            if missing_terms:
                errors.append(
                    f"document {anchor.document_id!r} does not contain exact "
                    "must_include term(s): " + ", ".join(missing_terms))
    return errors


def validate_submission(
    arguments: dict[str, Any],
    items: list[ContractItem],
    ledger: EvidenceLedger,
    committed_ids: set[str],
    *,
    answer_form: AnswerFormPolicy | None = None,
    max_words: int = 1024,
) -> tuple[list[dict[str, Any]] | None, list[str], dict[str, Any]]:
    """Validate a terminal answer against every executable contract row."""
    answer_form = answer_form or AnswerFormPolicy()
    by_id = {item.id: item for item in items}
    raw_answer_items = arguments.get("answer_items")
    raw_unresolved = arguments.get("unresolved")
    errors: list[str] = []
    if not isinstance(raw_answer_items, list) or not raw_answer_items:
        return None, ["answer_items must be a non-empty array"], {}
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
    tagged_kinds: dict[str, set[str]] = {}
    satisfied: set[str] = set()
    python_items = 0
    label_ordinals: list[int] = []
    for index, raw in enumerate(raw_answer_items[:96], 1):
        if not isinstance(raw, dict):
            errors.append(f"answer item {index} is not an object")
            continue
        kind = str(raw.get("kind") or "").strip().casefold()
        if kind not in {"prose", "label", "code"}:
            errors.append(
                f"answer item {index} kind must be prose, label, or code")
            continue
        raw_text = str(raw.get("text") or "")
        if kind == "code":
            text = raw_text.replace("\r\n", "\n").replace("\r", "\n")
            text = text.strip("\n")
        else:
            text = _compact(raw_text, 8_000)
        if not text:
            errors.append(f"answer item {index} has empty text")
            continue
        if kind != "code" and _CITATIONISH_RE.search(text):
            errors.append(
                f"answer item {index} contains citation markers; use evidence_ids")
        if kind == "code":
            python_items += 1
            oversized = len(text) > 8_000
            if not answer_form.python_code:
                errors.append(
                    f"answer item {index} uses code not authorized by the request")
            if oversized:
                errors.append(
                    f"answer item {index} code is {len(text)} characters; "
                    "hard maximum is 8000")
            if "```" in text or "\x00" in text:
                errors.append(
                    f"answer item {index} code must be raw source without "
                    "Markdown fences or NUL bytes")
            elif not oversized:
                try:
                    compile(text, "<submitted-python>", "exec")
                except SyntaxError as exc:
                    errors.append(
                        f"answer item {index} Python syntax error at line "
                        f"{exc.lineno}: {exc.msg}")
        elif kind == "label":
            if not answer_form.minimum_labels:
                errors.append(
                    f"answer item {index} uses a label not authorized by the request")
            if "\n" in raw_text or len(text.split()) > 18:
                errors.append(
                    f"answer item {index} label must be one short nonfactual line")
            elif answer_form.repeated_label:
                label_match = re.match(
                    rf"^{re.escape(answer_form.repeated_label)}\s+"
                    r"(?P<ordinal>\d+)\s*[—–:-]",
                    text,
                    re.IGNORECASE,
                )
                if label_match is None:
                    errors.append(
                        f"answer item {index} label must begin with "
                        f"'{answer_form.repeated_label} N —'")
                else:
                    ordinal = int(label_match.group("ordinal"))
                    if ordinal in label_ordinals:
                        errors.append(
                            f"answer item {index} duplicates "
                            f"{answer_form.repeated_label} {ordinal}")
                    label_ordinals.append(ordinal)
        raw_evidence = raw.get("evidence_ids")
        raw_satisfies = raw.get("satisfies")
        if not isinstance(raw_evidence, list):
            errors.append(f"answer item {index} evidence_ids must be an array")
            raw_evidence = []
        if not isinstance(raw_satisfies, list):
            errors.append(f"answer item {index} satisfies must be an array")
            raw_satisfies = []

        evidence_ids: list[str] = []
        for value in raw_evidence[:3]:
            document_id = str(value).strip()
            if document_id not in committed_ids:
                errors.append(
                    f"answer item {index} cites uncommitted id {document_id!r}")
            elif document_id not in evidence_ids:
                evidence_ids.append(document_id)
        if kind in {"code", "label"} and evidence_ids:
            errors.append(
                f"answer item {index} {kind} must not carry citations; put "
                "source-grounded claims in an adjacent prose item")
        satisfies: list[str] = []
        for value in raw_satisfies[:8]:
            item_id = str(value).strip()
            if item_id not in by_id:
                errors.append(
                    f"answer item {index} tags unknown coverage-contract id "
                    f"{item_id!r}")
            elif item_id not in satisfies:
                satisfies.append(item_id)
                satisfied.add(item_id)
                tagged_text.setdefault(item_id, []).append(text)
                tagged_kinds.setdefault(item_id, set()).add(kind)

        for item_id in satisfies:
            item = by_id[item_id]
            if not item.must_research:
                continue
            mapped_anchors = [
                anchor for anchor in ledger.anchors.get(item_id, [])
                if anchor.document_id in evidence_ids
            ]
            if not evidence_ids:
                errors.append(
                    f"answer item {index} satisfies research row {item_id} "
                    "without evidence_ids")
            elif not mapped_anchors:
                errors.append(
                    f"answer item {index} has no evidence explicitly mapped "
                    f"to {item_id}")
            elif kind != "prose":
                errors.append(
                    f"answer item {index} satisfies research row {item_id} "
                    f"with {kind} instead of cited prose")
            elif not any(
                all(_contains_exact_term(text, term)
                    for term in anchor.must_include)
                for anchor in mapped_anchors
            ):
                choices = [
                    " + ".join(anchor.must_include)
                    for anchor in mapped_anchors
                ]
                errors.append(
                    f"answer item {index} does not finish research row "
                    f"{item_id}; include every exact term from one cited "
                    "anchor: " + " OR ".join(choices))
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
        if item.id in satisfied and item.must_mention:
            haystack = " ".join(tagged_text.get(item.id, [])).casefold()
            absent = [
                term for term in item.must_mention
                if not _contains_exact_term(haystack, term)
            ]
            if absent:
                errors.append(
                    f"coverage row {item.id} is tagged but omits exact term(s): "
                    + ", ".join(absent))
        if (item.id in satisfied and item.kind == "python_code"
                and "code" not in tagged_kinds.get(item.id, set())):
            errors.append(
                f"coverage row {item.id} requires a code answer item")
        if (item.id in satisfied and item.kind == "repeated_labels"
                and "label" not in tagged_kinds.get(item.id, set())):
            errors.append(
                f"coverage row {item.id} requires a label answer item")

    if answer_form.python_code and python_items == 0:
        errors.append("the request requires at least one valid Python code item")
    if answer_form.minimum_labels:
        required_ordinals = set(range(1, answer_form.minimum_labels + 1))
        missing_ordinals = required_ordinals - set(label_ordinals)
        if missing_ordinals:
            errors.append(
                f"the requested series requires distinct "
                f"{answer_form.repeated_label} labels numbered 1 through "
                f"{answer_form.minimum_labels}; missing "
                + ", ".join(str(value) for value in sorted(missing_ordinals)))

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
        "python_items": python_items,
        "label_items": len(label_ordinals),
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
                + (" | USE EXACT: " + "; ".join(anchor.must_include)
                   if anchor.must_include else "")
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
        "tag every final answer item with the coverage ids it satisfies. Every "
        f"must-answer id must be satisfied or honestly unresolved: {required}."
    )
    if ledger is not None:
        request += "\n\n" + render_contract_status(items, ledger)
    return request
