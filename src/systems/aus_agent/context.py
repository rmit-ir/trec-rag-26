"""Staged/committed context management for the AUS research agent.

Tool results are shown to the model in full exactly once.  On the following
model step, ``commit_context`` selects the small subset worth retaining.
Selected documents remain verbatim in provider history; every other document
is replaced by a compact decision marker. ``output.json.trace`` records ids
and decisions but omits document text; the Outputs Viewer fetches text through
its document API. ``trajectory.json`` remains strict.

The ledger is UNIT-ID-native: it keys on each retrieval unit's ``id`` (a chunk
id ``<docid>_p<page>`` when the backend is chunked, else a doc id), NOT the
parent ``docid``. The agent commits and cites the exact id the search engine
returned, unedited; the chunk→parent-docid collapse for the organizer
submission happens only in the final output transform (see agent.py).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

REJECTION_PREFIX = "the agent decided this document is irrelevant:"
DUPLICATE_PREFIX = "duplicate/already committed document compacted:"
RELEASE_PREFIX = "the agent released this document; a better one supersedes it:"

# The two duplicate reasons the ledger itself generates. Kept as constants so the
# reasons the ledger writes and the ones it recognises cannot drift apart.
LATER_OCCURRENCE_REASON = (
    "duplicate/already committed; later occurrence compacted")
PARALLEL_OCCURRENCE_REASON = (
    "duplicate/already committed; repeated occurrence within the staged batch "
    "compacted")
_DUPLICATE_REASONS = frozenset({LATER_OCCURRENCE_REASON,
                                PARALLEL_OCCURRENCE_REASON})


def rejection_marker(unit_id: str, reason: str | None = None, *,
                     duplicate: bool | None = None,
                     released: bool = False) -> str:
    """The compact marker shown in place of a document's text.

    ``duplicate`` says whether the ledger actually saw this unit already — pass
    it explicitly. Inferring duplicate-ness from ``reason`` alone was a
    string-prefix match, so a caller-supplied ``unselected_reason`` that merely
    *started* like a duplicate reason produced ``DUPLICATE_PREFIX`` for a unit
    that was never committed, telling the model to look for full text that does
    not exist. Left as a fallback (restricted to the exact reasons the ledger
    generates) for callers that pass only a reason.

    ``released`` marks a unit that WAS committed (kept in full, cited or not)
    and has since been explicitly released — a distinct third case from
    "never selected" and "a full copy exists elsewhere": the model held this
    text and chose to let it go, normally because a better document replaced
    it (see ``ContextLedger.release_committed``).
    """
    if released:
        return f"{RELEASE_PREFIX} {unit_id}"
    if duplicate is None:
        duplicate = reason in _DUPLICATE_REASONS
    return f"{DUPLICATE_PREFIX if duplicate else REJECTION_PREFIX} {unit_id}"


@dataclass
class StagedResult:
    call_id: str
    tool_name: str
    output: str
    documents: list[dict[str, Any]]

    @property
    def ids(self) -> list[str]:
        """Retrieval-unit ids (the exact id the backend returned)."""
        return list(dict.fromkeys(str(d["id"]) for d in self.documents))


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
class ReleaseDecision:
    """The result of ``ContextLedger.release_committed`` — a document that
    WAS committed and is now dropped, normally because a better one replaced
    it. Deliberately its own type rather than a field bolted onto
    ``CommitDecision``: every existing consumer of ``CommitDecision.context``
    asserts its exact key set (see ``test_ledger_core.py``), so a feature only
    some systems use must not change what that type carries.
    """
    released: list[dict[str, str]]   # [{"docid", "reason"}]
    replacements: dict[str, str]     # call_id -> recompacted tool-result output


@dataclass
class ContextLedger:
    """Tracks unresolved staged results and cumulative committed unit ids."""

    pending: list[StagedResult] = field(default_factory=list)
    committed_ids: set[str] = field(default_factory=set)
    rejected_ids: set[str] = field(default_factory=set)
    # Every call ever staged, kept for the life of the run (unlike ``pending``,
    # which clears on each commit) -- ``release_committed`` needs a staged
    # unit's ORIGINAL full-text output to recompute a historical call's
    # compaction from scratch.
    call_history: dict[str, StagedResult] = field(default_factory=dict)
    # unit id -> the call_id CURRENTLY rendering it in full text. Set when a
    # unit is committed, cleared when released; a unit re-committed later
    # gets a fresh entry from whichever call_id renders it that time.
    committed_call_id: dict[str, str] = field(default_factory=dict)

    def stage(self, call_id: str, tool_name: str, output: str,
              documents: list[dict[str, Any]]) -> None:
        if documents:
            result = StagedResult(
                call_id=call_id,
                tool_name=tool_name,
                output=output,
                documents=documents,
            )
            self.pending.append(result)
            self.call_history[call_id] = result

    @property
    def staged_ids(self) -> list[str]:
        return list(dict.fromkeys(
            uid for result in self.pending for uid in result.ids))

    @property
    def has_staged(self) -> bool:
        return bool(self.pending)

    def commit(self, selected: list[dict[str, str]], *,
               max_documents: int,
               unselected_reason: str = "not selected for committed context",
               ) -> CommitDecision:
        staged = self.staged_ids
        staged_set = set(staged)

        selected_by_id: dict[str, dict[str, str]] = {}
        for item in selected:
            # Commit by the exact unit id. Accept a legacy "docid" key as a
            # fallback: for an unpaginated result it equals the id, and for a
            # paginated one a bare parent docid simply won't match a staged
            # chunk unit below (which correctly forces the precise `_p<n>` id).
            uid = str(item.get("id") or item.get("docid") or "").strip()
            if uid and uid not in selected_by_id:
                selected_by_id[uid] = {
                    "id": uid,
                    "reason": str(item.get("reason", "")).strip(),
                }

        unknown = [u for u in selected_by_id if u not in staged_set]
        if unknown:
            raise ValueError(
                "cannot commit documents outside the staged context: "
                + ", ".join(unknown))
        missing_reasons = [
            uid for uid, item in selected_by_id.items()
            if not item["reason"]
        ]
        if missing_reasons:
            raise ValueError(
                "every committed document needs a distinct evidence reason: "
                + ", ".join(missing_reasons))
        already_committed = staged_set & self.committed_ids
        selected_by_id = {
            uid: item for uid, item in selected_by_id.items()
            if uid not in already_committed
        }
        overflow_ids = list(selected_by_id)[max_documents:]
        selected_by_id = dict(
            list(selected_by_id.items())[:max_documents])

        committed = [u for u in staged if u in selected_by_id]
        rejected_ids = [u for u in staged if u not in selected_by_id]
        rejected = [{
            "docid": u,
            "reason": (
                LATER_OCCURRENCE_REASON
                if u in already_committed
                else (
                    f"selection exceeded per-step maximum of {max_documents}"
                    if u in overflow_ids
                    else unselected_reason
                )
            ),
        } for u in rejected_ids]
        occurrence_counts: dict[str, int] = {}
        for result in self.pending:
            for uid in result.ids:
                occurrence_counts[uid] = occurrence_counts.get(uid, 0) + 1
        for uid in committed:
            for _ in range(max(0, occurrence_counts.get(uid, 0) - 1)):
                rejected.append({"docid": uid,
                                 "reason": PARALLEL_OCCURRENCE_REASON})
        rejected_reasons = {
            item["docid"]: item["reason"] for item in rejected}

        documents_by_id: dict[str, dict[str, Any]] = {}
        for result in self.pending:
            for document in result.documents:
                uid = str(document["id"])
                documents_by_id.setdefault(uid, document)

        # Preserve each newly committed unit in full exactly once. Duplicate
        # occurrences from parallel queries, plus any occurrence of an
        # already-committed unit, become compact tombstones.
        remaining_to_keep = set(committed)
        replacements: dict[str, str] = {}
        for result in self.pending:
            keep_here: set[str] = set()
            occurrence_reasons = dict(rejected_reasons)
            # Units this batch is tombstoning *because the text lives elsewhere*
            # — either committed on an earlier turn, or kept in full by another
            # occurrence within this batch. This, not a reason-string prefix, is
            # what earns DUPLICATE_PREFIX.
            duplicate_here = set(already_committed)
            for uid in result.ids:
                if uid in remaining_to_keep:
                    keep_here.add(uid)
                    remaining_to_keep.remove(uid)
                elif uid in committed:
                    occurrence_reasons[uid] = PARALLEL_OCCURRENCE_REASON
                    duplicate_here.add(uid)
            replacements[result.call_id] = _compact_output(
                result.tool_name, result.output, keep_here,
                occurrence_reasons, duplicate_here)
            for uid in keep_here:
                self.committed_call_id[uid] = result.call_id
        self.committed_ids.update(committed)
        self.rejected_ids.update(rejected_ids)
        # Cumulative summary means "never committed" rather than "a later
        # duplicate retrieval occurrence was omitted".
        self.rejected_ids.difference_update(self.committed_ids)
        self.pending.clear()

        selected_documents = []
        for uid in committed:
            document = dict(documents_by_id[uid])
            metadata = dict(document.get("metadata") or {})
            reason = selected_by_id[uid]["reason"]
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

    def release_committed(self, released: list[dict[str, str]]
                          ) -> ReleaseDecision:
        """Drop previously committed units, replacing their full text with a
        compact tombstone -- for when a later, better document supersedes one
        already kept. Unlike ``commit``, this is not scoped to the currently
        staged batch: ``released`` may name a unit committed on any earlier
        turn.

        Recomputes each affected call's compaction FROM SCRATCH (its ORIGINAL
        full-text output, held in ``call_history``, plus the ledger's current
        ``committed_ids`` membership) rather than patching whatever partially
        compacted state the provider currently holds. That keeps this
        idempotent and needs no way to read a tool result's current content
        back out of the provider.

        Does not touch any OTHER occurrence of a released unit that was
        already compacted as a duplicate elsewhere in history (see
        ``DUPLICATE_PREFIX``) -- that tombstone was correct when written
        ("you already have this, verbatim, earlier"), and rewriting every
        historical duplicate marker on every release is not worth the
        complexity for what stays a deliberate, infrequent correction.
        """
        selected: dict[str, str] = {}
        for item in released:
            uid = str(item.get("id") or item.get("docid") or "").strip()
            if uid and uid not in selected:
                selected[uid] = str(item.get("reason", "")).strip()

        unknown = [u for u in selected if u not in self.committed_ids]
        if unknown:
            raise ValueError(
                "cannot release a document that is not currently committed: "
                + ", ".join(unknown))
        missing_reasons = [u for u, r in selected.items() if not r]
        if missing_reasons:
            raise ValueError(
                "every released document needs a reason it no longer earns "
                "its place: " + ", ".join(missing_reasons))

        self.committed_ids.difference_update(selected)
        self.rejected_ids.update(selected)
        self.rejected_ids.difference_update(self.committed_ids)

        affected_call_ids = {
            self.committed_call_id[uid] for uid in selected
            if uid in self.committed_call_id
        }
        replacements: dict[str, str] = {}
        for call_id in affected_call_ids:
            result = self.call_history[call_id]
            keep_full = {uid for uid in result.ids
                        if uid in self.committed_ids}
            release_reasons = {uid: selected[uid] for uid in result.ids
                               if uid in selected}
            replacements[call_id] = _compact_output(
                result.tool_name, result.output, keep_full, release_reasons,
                duplicate_ids=set(), released_ids=set(release_reasons))

        for uid in selected:
            self.committed_call_id.pop(uid, None)

        return ReleaseDecision(
            released=[{"docid": uid, "reason": reason}
                     for uid, reason in selected.items()],
            replacements=replacements,
        )


def _compact_output(tool_name: str, output: str, keep_full: set[str],
                    rejected_reasons: dict[str, str] | None = None,
                    duplicate_ids: set[str] | None = None,
                    released_ids: set[str] | None = None) -> str:
    """Remove rejected text while retaining the original tool-result shape.

    Matches results by their unit ``id`` (chunk id when chunked), so committing
    one page of a document keeps that page verbatim and compacts the rest.

    ``duplicate_ids`` are the units the ledger knows it retained elsewhere; they
    get ``DUPLICATE_PREFIX`` instead of ``REJECTION_PREFIX``. It is passed
    explicitly rather than re-derived from ``rejected_reasons`` because the
    ledger is the only authority on what it actually kept. ``released_ids``
    (from ``release_committed``) get ``RELEASE_PREFIX`` instead of either.
    """
    payload, separator, status_line = output.partition("\n[context budget:")
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return output

    if tool_name in ("search", "get_documents") and isinstance(
            data.get("results"), list):
        compacted = []
        for raw in data["results"]:
            if not isinstance(raw, dict) or "id" not in raw:
                compacted.append(raw)
                continue
            uid = str(raw["id"])
            if uid in keep_full:
                compacted.append(raw)
                continue
            item = {
                key: raw[key]
                for key in ("rank", "id", "docid", "kind", "score")
                if key in raw
            }
            reason = (rejected_reasons or {}).get(uid)
            item["decision"] = rejection_marker(
                uid, reason, duplicate=uid in (duplicate_ids or set()),
                released=uid in (released_ids or set()))
            if reason:
                item["reason"] = reason
            compacted.append(item)
        data["results"] = compacted

    compacted = json.dumps(data, ensure_ascii=False)
    if separator:
        compacted += separator + status_line
    return compacted
