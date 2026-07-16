"""Staged/committed context management for the AUS research agent.

Tool results are shown to the model in full exactly once.  On the following
model step, ``commit_context`` selects the small subset worth retaining.
Selected documents remain verbatim in provider history; every other document
is replaced by a compact decision marker. ``output.json.trace`` records docids
and decisions but omits document text; the Outputs Viewer fetches text through
its document API. ``trajectory.json`` remains strict.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

REJECTION_PREFIX = "the agent decided this document is irrelevant:"
DUPLICATE_PREFIX = "duplicate/already committed document compacted:"


def rejection_marker(docid: str, reason: str | None = None) -> str:
    if reason and reason.startswith("duplicate/already committed"):
        return f"{DUPLICATE_PREFIX} {docid}"
    return f"{REJECTION_PREFIX} {docid}"


@dataclass
class StagedResult:
    call_id: str
    tool_name: str
    output: str
    documents: list[dict[str, Any]]

    @property
    def docids(self) -> list[str]:
        return list(dict.fromkeys(str(d["docid"]) for d in self.documents))


@dataclass
class CommitDecision:
    staged: list[str]
    committed: list[str]
    rejected: list[dict[str, str]]
    replacements: dict[str, str]
    documents: list[dict[str, Any]]

    @property
    def context(self) -> dict[str, Any]:
        return {
            "staged": self.staged,
            "committed": self.committed,
            "rejected": self.rejected,
        }


@dataclass
class ContextLedger:
    """Tracks unresolved staged results and cumulative committed docids."""

    pending: list[StagedResult] = field(default_factory=list)
    committed_docids: set[str] = field(default_factory=set)
    rejected_docids: set[str] = field(default_factory=set)

    def stage(self, call_id: str, tool_name: str, output: str,
              documents: list[dict[str, Any]]) -> None:
        if documents:
            self.pending.append(StagedResult(
                call_id=call_id,
                tool_name=tool_name,
                output=output,
                documents=documents,
            ))

    @property
    def staged_docids(self) -> list[str]:
        return list(dict.fromkeys(
            docid for result in self.pending for docid in result.docids))

    @property
    def has_staged(self) -> bool:
        return bool(self.pending)

    def commit(self, selected: list[dict[str, str]], *,
               max_documents: int,
               unselected_reason: str = "not selected for committed context",
               ) -> CommitDecision:
        staged = self.staged_docids
        staged_set = set(staged)

        selected_by_id: dict[str, dict[str, str]] = {}
        for item in selected:
            docid = str(item.get("docid", "")).strip()
            if docid and docid not in selected_by_id:
                selected_by_id[docid] = {
                    "docid": docid,
                    "reason": str(item.get("reason", "")).strip(),
                }

        unknown = [d for d in selected_by_id if d not in staged_set]
        if unknown:
            raise ValueError(
                "cannot commit documents outside the staged context: "
                + ", ".join(unknown))
        missing_reasons = [
            docid for docid, item in selected_by_id.items()
            if not item["reason"]
        ]
        if missing_reasons:
            raise ValueError(
                "every committed document needs a distinct evidence reason: "
                + ", ".join(missing_reasons))
        already_committed = staged_set & self.committed_docids
        selected_by_id = {
            docid: item for docid, item in selected_by_id.items()
            if docid not in already_committed
        }
        overflow_ids = list(selected_by_id)[max_documents:]
        selected_by_id = dict(
            list(selected_by_id.items())[:max_documents])

        committed = [d for d in staged if d in selected_by_id]
        rejected_ids = [d for d in staged if d not in selected_by_id]
        rejected = [{
            "docid": d,
            "reason": (
                "duplicate/already committed; later occurrence compacted"
                if d in already_committed
                else (
                    f"selection exceeded per-step maximum of {max_documents}"
                    if d in overflow_ids
                    else unselected_reason
                )
            ),
        } for d in rejected_ids]
        occurrence_counts: dict[str, int] = {}
        for result in self.pending:
            for docid in result.docids:
                occurrence_counts[docid] = occurrence_counts.get(docid, 0) + 1
        for docid in committed:
            for _ in range(max(0, occurrence_counts.get(docid, 0) - 1)):
                rejected.append({
                    "docid": docid,
                    "reason": (
                        "duplicate/already committed; repeated occurrence "
                        "within the staged batch compacted"
                    ),
                })
        rejected_reasons = {
            item["docid"]: item["reason"] for item in rejected}

        documents_by_id: dict[str, dict[str, Any]] = {}
        for result in self.pending:
            for document in result.documents:
                docid = str(document["docid"])
                documents_by_id.setdefault(docid, document)

        # Preserve each newly committed docid in full exactly once. Duplicate
        # occurrences from parallel queries, plus any occurrence of an
        # already-committed docid, become compact tombstones.
        remaining_to_keep = set(committed)
        replacements: dict[str, str] = {}
        for result in self.pending:
            keep_here: set[str] = set()
            occurrence_reasons = dict(rejected_reasons)
            for docid in result.docids:
                if docid in remaining_to_keep:
                    keep_here.add(docid)
                    remaining_to_keep.remove(docid)
                elif docid in committed:
                    occurrence_reasons[docid] = (
                        "duplicate/already committed; repeated occurrence "
                        "within the staged batch compacted")
            replacements[result.call_id] = _compact_output(
                result.tool_name, result.output, keep_here,
                occurrence_reasons)
        self.committed_docids.update(committed)
        self.rejected_docids.update(rejected_ids)
        # Cumulative summary means "never committed" rather than "a later
        # duplicate retrieval occurrence was omitted".
        self.rejected_docids.difference_update(self.committed_docids)
        self.pending.clear()

        selected_documents = []
        for docid in committed:
            document = dict(documents_by_id[docid])
            metadata = dict(document.get("metadata") or {})
            reason = selected_by_id[docid]["reason"]
            if reason:
                metadata["commit_reason"] = reason
            document["metadata"] = metadata
            selected_documents.append(document)

        return CommitDecision(
            staged=staged,
            committed=committed,
            rejected=rejected,
            replacements=replacements,
            documents=selected_documents,
        )


def _compact_output(tool_name: str, output: str, keep_full: set[str],
                    rejected_reasons: dict[str, str] | None = None) -> str:
    """Remove rejected text while retaining the original tool-result shape."""
    payload, separator, status_line = output.partition("\n[context budget:")
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return output

    if tool_name == "search" and isinstance(data.get("results"), list):
        compacted = []
        for raw in data["results"]:
            if not isinstance(raw, dict) or "docid" not in raw:
                compacted.append(raw)
                continue
            docid = str(raw["docid"])
            if docid in keep_full:
                compacted.append(raw)
                continue
            item = {
                key: raw[key]
                for key in ("rank", "id", "docid", "kind", "rrf_score")
                if key in raw
            }
            reason = (rejected_reasons or {}).get(docid)
            item["decision"] = rejection_marker(docid, reason)
            if reason:
                item["reason"] = reason
            compacted.append(item)
        data["results"] = compacted

    compacted = json.dumps(data, ensure_ascii=False)
    if separator:
        compacted += separator + status_line
    return compacted
