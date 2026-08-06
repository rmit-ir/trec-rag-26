"""Parallel evidence-facet research followed by a bounded synthesis context."""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

from ragrun import TrajectoryBuilder, build_rag_output, now_iso, save_run
from ragrun.outputs import data_dir

from .agent import _map_citations, _parse_final_prose, run_agent
from .provider import ResilientOpenAIProvider


FACET_DECOMPOSE_SYSTEM = """\
You are the request decomposer for a parallel research system. Split the exact
request into exactly three complementary evidence facets that can be researched
independently and later synthesized into one answer.

Return one JSON object with this exact shape:
{"facets":[{"name":"short name","brief":"bounded research assignment","must_cover":["observable requirement"]}]}

Rules:
- Preserve every explicit deliverable, comparison, case, audience constraint,
  date, jurisdiction, format, and requested evidence type across the three
  assignments.
- Put closely coupled requirements in one facet; minimize overlap between
  facets so parallel researchers add evidence rather than duplicate it.
- Include implied definitions, mechanisms, alternatives, limitations, safety
  conditions, and quantitative evidence where a knowledgeable answer needs
  them, but do not invent facts or candidate conclusions.
- Each facet gets 2 to 8 must_cover strings and a brief under 120 words.
- Assign presentation and synthesis constraints to the facet that owns the
  corresponding content; do not create a facet devoted only to formatting.
- Return JSON only, without a Markdown fence or commentary.
"""

FACET_SYNTHESIS_SYSTEM = """\
You are the final synthesis stage of a parallel research system. You receive
the original request, three facet assignments, and three cited evidence memos.
Create the complete requested deliverable, not a summary of the memos.

Integrate complementary findings and resolve overlap. Preserve the scope,
population, date, uncertainty, and limitation attached to every result. Finish
each claim: state the exact value, comparison, mechanism, source, or boundary
available in the memos rather than merely naming a topic. Do not add facts,
named examples, or conclusions from memory, and do not treat a memo's proposal
or hypothesis as an established empirical result.

Use only exact [docid] identifiers printed in the memos. Every factual sentence
must end with one to three citations that directly support the whole sentence;
directly cite and narrowly scope population-level medical, safety, legal, and
causal claims. Creative examples and proposed designs must be clearly presented
as examples or proposals, not cited as historical facts.

Default to plain flowing prose with exactly one sentence per line and at most
1,024 words. Do not use Markdown headings, tables, bullets, numbering, bold, or
fences. When the request genuinely requires repeated deliverables or visibly
distinct named comparison cases, prefix the first sentence of each part with a
short consistent prose label such as “Post 1 — Foundations:” or “Finland
pilot:”; the label is part of that sentence, not a separate heading. Return only
the complete cited answer, with no references section or process commentary.
"""

_FORBIDDEN_FACET_KEYS = frozenset({"answer", "conclusion", "facts", "sources"})


def normalize_facets(text: str | None) -> tuple[list[dict[str, Any]], list[str]]:
    """Validate an exact three-way decomposition before launching expensive work."""
    errors: list[str] = []
    try:
        parsed = json.loads((text or "").strip())
    except (TypeError, json.JSONDecodeError):
        return [], ["decomposition was not bare JSON"]
    if not isinstance(parsed, dict) or set(parsed) != {"facets"}:
        return [], ["decomposition must contain exactly facets"]
    raw_facets = parsed["facets"]
    if not isinstance(raw_facets, list) or len(raw_facets) != 3:
        return [], ["decomposition must contain exactly three facets"]
    facets: list[dict[str, Any]] = []
    names: set[str] = set()
    for index, raw in enumerate(raw_facets, 1):
        if not isinstance(raw, dict) or set(raw) != {"name", "brief", "must_cover"}:
            errors.append(f"facet {index} has wrong keys")
            continue
        name = " ".join(str(raw["name"]).split())
        brief = " ".join(str(raw["brief"]).split())
        must = raw["must_cover"]
        if (not 2 <= len(name.split()) <= 8 or len(brief.split()) > 120
                or name.lower() in names):
            errors.append(f"facet {index} name/brief is invalid")
            continue
        if not isinstance(must, list) or not 2 <= len(must) <= 8:
            errors.append(f"facet {index} must_cover count is invalid")
            continue
        must_cover = [" ".join(str(item).split()) for item in must]
        if any(not item or len(item.split()) > 40 for item in must_cover):
            errors.append(f"facet {index} contains an invalid requirement")
            continue
        if _FORBIDDEN_FACET_KEYS & {key.lower() for key in raw}:
            errors.append(f"facet {index} contains answer-like keys")
            continue
        names.add(name.lower())
        facets.append({"name": name, "brief": brief, "must_cover": must_cover})
    return (facets, errors) if len(facets) == 3 and not errors else ([], errors)


def facet_query(overall_query: str, facet: dict[str, Any], index: int) -> str:
    """Make a child assignment whose requested output is evidence, not the final."""
    checklist = "\n".join(f"- {item}" for item in facet["must_cover"])
    return (
        "Research one independent evidence facet for a later synthesis stage.\n\n"
        "Overall user request (context only):\n"
        + overall_query.strip()
        + f"\n\nAssigned facet {index} — {facet['name']}:\n"
        + facet["brief"]
        + "\n\nThe evidence memo must cover:\n"
        + checklist
        + "\n\nReturn a compact, self-contained cited evidence memo for this facet only. "
          "State exact values, scopes, mechanisms, source limitations, and "
          "counterevidence useful to the final writer. Do not attempt the full "
          "overall deliverable and do not discuss the parallel workflow."
    )


def facet_from_query(query: str) -> dict[str, Any] | None:
    """Recover the exact assignment embedded in a reusable child artifact."""
    match = re.search(
        r"Assigned facet \d+ — (.+?):\n(.+?)\n\n"
        r"The evidence memo must cover:\n(.+?)\n\nReturn a compact",
        query,
        flags=re.DOTALL,
    )
    if match is None:
        return None
    must_cover = [
        line[2:].strip() for line in match.group(3).splitlines()
        if line.startswith("- ") and line[2:].strip()
    ]
    facet = {
        "name": match.group(1).strip(),
        "brief": " ".join(match.group(2).split()),
        "must_cover": must_cover,
    }
    if (not 2 <= len(facet["name"].split()) <= 8
            or len(facet["brief"].split()) > 120
            or not 2 <= len(must_cover) <= 8
            or any(len(item.split()) > 40 for item in must_cover)):
        return None
    return facet


def memo_from_output(obj: dict[str, Any]) -> tuple[str, set[str]]:
    """Render an organizer answer back into a docid-cited evidence memo."""
    refs = [str(ref) for ref in obj.get("references", [])]
    allowed: set[str] = set()
    lines: list[str] = []
    for item in obj.get("answer", []):
        if not isinstance(item, dict) or not isinstance(item.get("text"), str):
            continue
        cited: list[str] = []
        for citation in item.get("citations", []):
            if type(citation) is int and 0 <= citation < len(refs):
                docid = refs[citation]
            elif isinstance(citation, str) and citation in refs:
                docid = citation
            else:
                continue
            if docid not in cited:
                cited.append(docid)
                allowed.add(docid)
        suffix = "".join(f" [{docid}]" for docid in cited[:3])
        lines.append(item["text"].strip() + suffix)
    if not lines:
        raise RuntimeError("facet output contained no answer text")
    return "\n".join(lines), allowed


def synthesis_packet(
    query: str,
    facets: list[dict[str, Any]],
    memos: list[str],
) -> str:
    """Bounded handoff: exact request, assignments, and cited child findings."""
    sections = ["ORIGINAL REQUEST\n" + query.strip()]
    for index, (facet, memo) in enumerate(zip(facets, memos), 1):
        sections.append(
            f"FACET {index} — {facet['name']}\n"
            f"ASSIGNMENT: {facet['brief']}\n"
            "MUST COVER: " + "; ".join(facet["must_cover"])
            + "\n\nCITED EVIDENCE MEMO\n" + memo)
    return "\n\n".join(sections)


def _load_output(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _jsonable_summary(summary: dict[str, Any]) -> dict[str, Any]:
    """Keep child artifact links in the parent trace without Path objects."""
    converted = dict(summary)
    converted["paths"] = {
        key: str(value) for key, value in summary.get("paths", {}).items()
    }
    return converted


def _completed_child(
    child_qid: str,
    child_run_id: str,
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """Reuse exact completed child evidence when only parent synthesis failed."""
    candidates: list[tuple[str, Path, dict[str, Any]]] = []
    out_dir = data_dir() / "outputs" / "aus_agent_v2"
    for path in out_dir.glob("*.output.json"):
        try:
            obj = _load_output(path)
        except (OSError, json.JSONDecodeError):
            continue
        if (obj.get("metadata", {}).get("run_id") == child_run_id
                and obj.get("metadata", {}).get("narrative_id") == child_qid
                and obj.get("trace", {}).get("status") == "completed"):
            candidates.append((path.name.split(".", 1)[0], path, obj))
    if not candidates:
        return None
    _stamp, path, obj = max(candidates, key=lambda item: item[0])
    trajectory_path = Path(str(path).replace(".output.json", ".trajectory.json"))
    summary = {
        "status": "completed",
        "paths": {"output": path, "trajectory": trajectory_path},
        "n_references": len(obj.get("references", [])),
        "n_sentences": len(obj.get("answer", [])),
        "words": sum(
            len(item.get("text", "").split()) for item in obj.get("answer", [])
            if isinstance(item, dict)),
        "reused": True,
    }
    return summary, obj


def run_parallel_facets(
    query_id: str,
    query: str,
    *,
    run_id: str,
    backend: str = "openai",
    model: str = "openai.gpt-5.6-sol",
    k: int = 20,
    child_context_token_budget: int = 220_000,
    child_safety_max_rounds: int = 40,
    child_runner: Callable[..., dict[str, Any]] = run_agent,
) -> dict[str, Any]:
    """Run three isolated research loops concurrently and synthesize once."""
    if backend != "openai":
        raise ValueError("parallel facet synthesis currently requires openai backend")
    started = now_iso()
    planner = ResilientOpenAIProvider(model, max_tokens=4_000)
    planner.start(FACET_DECOMPOSE_SYSTEM, [])
    planner.add_user_message("ORIGINAL REQUEST\n\n" + query.strip())
    plan_turn = planner.run_turn()
    facets, facet_errors = normalize_facets(plan_turn.get("text"))
    if not facets:
        raise RuntimeError("invalid facet decomposition: " + "; ".join(facet_errors))

    def research(index: int) -> tuple[dict[str, Any], dict[str, Any]]:
        facet = facets[index]
        child_qid = f"{query_id}-facet-{index + 1}"
        child_run_id = f"{run_id}-facet-{index + 1}"
        reused = _completed_child(child_qid, child_run_id)
        if reused is not None:
            return reused
        summary = child_runner(
            child_qid,
            facet_query(query, facet, index + 1),
            backend=backend,
            model=model,
            k=k,
            context_token_budget=child_context_token_budget,
            safety_max_rounds=child_safety_max_rounds,
            run_id=child_run_id,
            run_desc=f"Parallel evidence facet {index + 1} for {query_id}",
            coverage_plan=False,
            plan_critic=False,
            observable_scout=False,
            plan_reconcile=False,
            coverage_verify=False,
            audience_verify=False,
            finish_review=False,
        )
        if summary["status"] != "completed":
            raise RuntimeError(f"facet {index + 1} status={summary['status']}")
        return summary, _load_output(Path(summary["paths"]["output"]))

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(research, index) for index in range(3)]
        children = [future.result() for future in futures]

    # A parent-only retry may reuse children from an earlier decomposition.
    # The child narrative is the immutable source of truth for what it actually
    # researched; never pair that memo with a newly sampled assignment.
    recovered_facets = [
        facet_from_query(str(output.get("metadata", {}).get("narrative") or ""))
        for _summary, output in children
    ]
    if all(facet is not None for facet in recovered_facets):
        facets = [facet for facet in recovered_facets if facet is not None]

    memos: list[str] = []
    allowed: set[str] = set()
    for _summary, output in children:
        memo, memo_refs = memo_from_output(output)
        memos.append(memo)
        allowed.update(memo_refs)
    packet = synthesis_packet(query, facets, memos)

    writer = ResilientOpenAIProvider(model, max_tokens=6_000)
    writer.start(FACET_SYNTHESIS_SYSTEM, [])
    writer.add_user_message(packet)
    sentences = None
    errors: list[str] = []
    notes: list[str] = []
    raw = ""
    final_turn: dict[str, Any] = {}
    attempts = 0
    while attempts < 6:
        final_turn = writer.run_turn()
        attempts += 1
        raw = str(final_turn.get("text") or "")
        sentences, errors, notes = _parse_final_prose(
            raw, allowed, allow_uncited=True)
        if sentences is not None:
            break
        observed_words = len(raw.split())
        if attempts >= 6:
            break
        target = (
            "780 to 850 words" if attempts >= 3 or observed_words > 1100
            else "880 to 930 words"
        )
        writer.add_user_message(
            f"The proposed answer is {observed_words} words and failed the "
            "submission contract: " + "; ".join(errors)
            + f". Rewrite it now at {target}. Preserve every explicit "
              "requested part and the highest-value evidence, but combine "
              "overlapping background and remove low-value repetition. Use "
              "only the supplied docids and return plain cited prose, one "
              "sentence per line."
        )
    if sentences is None:
        raise RuntimeError("invalid facet synthesis: " + "; ".join(errors))

    references, answer = _map_citations(sentences, allowed)
    ended = now_iso()
    builder = TrajectoryBuilder(query_id, query, metadata={
        "model": model,
        "backend": backend,
        "run_id": run_id,
        "architecture": "parallel_facets",
    })
    builder.set_trace_input({
        "query": query,
        "facet_decompose_system": FACET_DECOMPOSE_SYSTEM,
        "facet_decomposition": facets,
        "facet_child_outputs": [
            str(summary["paths"]["output"]) for summary, _output in children],
        "synthesis_system": FACET_SYNTHESIS_SYSTEM,
        "synthesis_packet": packet,
    })
    builder.add_model_step(
        input={"kind": "facet_decomposition"}, output=plan_turn,
        t_start=started, t_end=started, turn=0)
    builder.add_model_step(
        input={"kind": "parallel_facet_synthesis"}, output=final_turn,
        t_start=ended, t_end=ended, turn=1)
    builder.set_trace_output({"references": references, "answer": answer})
    builder.add_output_text(" ".join(item["text"] for item in answer),
                            t_start=ended, t_end=ended, turn=1,
                            record_trace=False)
    trajectory = builder.finalize(
        "completed",
        raw_messages=[
            *planner.raw_messages,
            {"type": "phase_boundary", "phase": "parallel_facet_research"},
            *writer.raw_messages,
        ],
        started_at=started,
        ended_at=ended,
    )
    trajectory.trace["summary"]["parallel_facets"] = {
        "facets": facets,
        "children": [
            _jsonable_summary(summary) for summary, _output in children
        ],
        "allowed_references": len(allowed),
        "synthesis_attempts": attempts,
        "validation_errors": errors,
        "validation_notes": notes,
    }
    output = build_rag_output(
        narrative_id=query_id,
        narrative=query,
        run_id=run_id,
        run_desc="Three independent evidence facets with bounded synthesis.",
        references=references,
        answer=answer,
    )
    paths = save_run("aus_agent_v2", query, trajectory=trajectory, output=output)
    return {
        "status": "completed",
        "paths": paths,
        "facets": facets,
        "child_summaries": [
            _jsonable_summary(summary) for summary, _output in children
        ],
        "n_references": len(references),
        "n_sentences": len(answer),
        "words": sum(len(item["text"].split()) for item in answer),
        "synthesis_attempts": attempts,
    }
