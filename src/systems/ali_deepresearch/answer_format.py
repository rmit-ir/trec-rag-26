"""Convert the agent's free-text ``<answer>`` into TREC RAG 2026 output shape.

The upstream ``<answer>`` is free-form markdown prose. The track requires
``answer = [{"text": <sentence>, "citations": [ref_idx, ...]}]`` with
``references = [docid, ...]`` (≤3 citations/sentence, ≤1024 words total).
``format_answer`` produces that structure two ways:

- **LLM stage** (``llm`` given): one extra call to the same endpoint asks the
  model to rewrite the draft as sentences citing only the allowed docids. Faithful
  to Tongyi's own answer-formatting step.
- **Heuristic fallback** (``llm=None`` or the LLM output is unusable): split the
  draft into sentences and distribute the candidate docids across them
  round-robin. Fully offline and deterministic — this is the path exercised by
  ``tests/systems/test_ali_deepresearch.py`` and by the ``tests/contract/``
  format-conformance suite.

Both paths return ``(references, answer)`` already mapped to reference indices and
guaranteed to pass ``ragrun.validate_rag_output``.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from .prompts import FORMAT_ANSWER_PROMPT

log = logging.getLogger(__name__)

MAX_CITATIONS = 3
MAX_WORDS = 1024


def _clean(text: str) -> str:
    """Strip markdown noise so sentence splitting behaves."""
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)   # code fences
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.MULTILINE)  # headers
    text = text.replace("**", "").replace("`", "").replace("*", "")
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.MULTILINE)  # bullets
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _split_sentences(text: str) -> list[str]:
    text = _clean(text)
    if not text:
        return []
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [p.strip() for p in parts if p.strip()]


def _trim_to_words(sentences: list[str], limit: int = MAX_WORDS) -> list[str]:
    out: list[str] = []
    total = 0
    for s in sentences:
        n = len(s.split())
        if total + n > limit:
            break
        out.append(s)
        total += n
    return out or (sentences[:1] if sentences else [])


def _assign_round_robin(sentences: list[str],
                        docids: list[str]) -> tuple[list[str], list[dict[str, Any]]]:
    """Cite every docid across the sentences, ≤3 per sentence."""
    if not sentences:
        return [], []
    capacity = len(sentences) * MAX_CITATIONS
    refs = list(dict.fromkeys(docids))[:capacity]   # unique, capped to capacity
    idx_of = {d: i for i, d in enumerate(refs)}
    answer = [{"text": s, "citations": []} for s in sentences]

    si = 0
    for d in refs:
        for _ in range(len(sentences)):
            if len(answer[si]["citations"]) < MAX_CITATIONS:
                answer[si]["citations"].append(idx_of[d])
                si = (si + 1) % len(sentences)
                break
            si = (si + 1) % len(sentences)
    return refs, answer


def _heuristic(answer_text: str,
               candidate_docids: list[str]) -> tuple[list[str], list[dict[str, Any]]]:
    sentences = _trim_to_words(_split_sentences(answer_text))
    if not sentences:
        sentences = ["No answer was produced."]
    return _assign_round_robin(sentences, candidate_docids)


def _from_llm_json(raw: str, candidate_docids: list[str]
                   ) -> tuple[list[str], list[dict[str, Any]]] | None:
    """Parse the formatter LLM's JSON into (references, answer). None on failure."""
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    sents = obj.get("sentences")
    if not isinstance(sents, list) or not sents:
        return None

    allowed = set(candidate_docids)
    refs: list[str] = []
    idx_of: dict[str, int] = {}
    answer: list[dict[str, Any]] = []
    for s in sents:
        if not isinstance(s, dict):
            continue
        text = str(s.get("text", "")).strip()
        if not text:
            continue
        cits: list[int] = []
        for d in s.get("citations", []) or []:
            d = str(d).strip()
            if d not in allowed:
                continue
            if d not in idx_of:
                idx_of[d] = len(refs)
                refs.append(d)
            if idx_of[d] not in cits and len(cits) < MAX_CITATIONS:
                cits.append(idx_of[d])
        answer.append({"text": text, "citations": cits})

    if not answer:
        return None
    # Enforce the word budget, then drop any reference left uncited by the trim.
    # Since v0.6.0 uncited references are permitted and unpenalized, so this
    # re-indexing is now tidiness ("keeping only useful documents can make
    # submissions easier to inspect") rather than a conformance requirement.
    kept = _trim_to_words([a["text"] for a in answer])
    answer = answer[:len(kept)]
    used = {c for a in answer for c in a["citations"]}
    if used != set(range(len(refs))):
        # Re-index to only the references still cited.
        remap = {old: new for new, old in enumerate(sorted(used))}
        refs = [refs[old] for old in sorted(used)]
        for a in answer:
            a["citations"] = [remap[c] for c in a["citations"]]
    return refs, answer


EXCERPT_CHARS = 800


def _render_allowed_docids(candidate_docids: list[str],
                           evidence_text: dict[str, str] | None) -> str:
    """The ALLOWED DOCIDS payload the formatter prompt sees.

    Without ``evidence_text`` this is the historical bare-id list (what
    ali_deepresearch/o3_deep_research still pass — they don't keep per-docid
    text around at their format_answer call site). With it, each entry also
    carries a short excerpt so the model can actually verify a sentence
    against the source instead of citing (or not citing) an opaque id blind —
    PLAN.md §3.4's diagnosed cause of the occasional all-zero-citation output.
    ``EXCERPT_CHARS`` deliberately truncates rather than sending each item's
    full (now up to 20 000-char) text — this call only needs enough to check
    a specific fact, not the whole passage; sending everything would blow up
    the formatter prompt's size for no benefit.
    """
    if not evidence_text:
        return json.dumps(candidate_docids, ensure_ascii=False)
    entries: list[dict[str, str]] = []
    for docid in candidate_docids:
        entry = {"docid": docid}
        text = evidence_text.get(docid)
        if text:
            entry["excerpt"] = text[:EXCERPT_CHARS]
        entries.append(entry)
    return json.dumps(entries, ensure_ascii=False)


def format_answer(answer_text: str, candidate_docids: list[str], *,
                  llm: Any | None = None,
                  evidence_text: dict[str, str] | None = None
                  ) -> tuple[list[str], list[dict[str, Any]]]:
    """Return ``(references, answer)`` for the TREC RAG output object.

    ``candidate_docids`` is the allow-list the answer may cite (docids the agent
    actually retrieved). With ``llm`` set, one formatting call is attempted and
    validated; any failure falls back to the deterministic heuristic.
    ``evidence_text`` (docid -> text), when the caller has it, lets the
    formatter verify each citation against an excerpt rather than an opaque id.
    """
    candidate_docids = list(dict.fromkeys(candidate_docids))  # unique, ordered
    if llm is not None and answer_text:
        prompt = FORMAT_ANSWER_PROMPT.format(
            answer=answer_text,
            docids=_render_allowed_docids(candidate_docids, evidence_text))
        try:
            raw = llm.complete([{"role": "user", "content": prompt}],
                               stop=None, max_tokens=4000)
            parsed = _from_llm_json(raw or "", candidate_docids)
            # A structurally valid parse is trusted even if every sentence
            # came back uncited (refs == []) -- that's a legitimate "nothing
            # here is well-supported enough to cite" result, not a failure.
            # Only None (regex/JSON/shape failure) falls through.
            if parsed is not None:
                return parsed
            log.warning("format_answer: LLM response did not parse into the "
                        "expected {sentences: [...]} shape; falling back to "
                        "the round-robin heuristic. raw response: %r",
                        (raw or "")[:500])
        except Exception:
            log.warning("format_answer: LLM formatting call raised; falling "
                        "back to the round-robin heuristic.", exc_info=True)
    return _heuristic(answer_text or "", candidate_docids)
