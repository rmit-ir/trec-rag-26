#!/usr/bin/env python3
"""Scaffold a new TREC RAG 2026 system package under ``src/systems/<name>/``.

Generates the standard skeleton every system in this repo follows (see
``src/systems/ali_deepresearch`` / ``aus_agent`` / ``facet_rag`` for worked
examples): ``__init__.py``, ``run.py`` (CLI with ``--query|--qid|--all`` and
the import-surgery header), ``prompts.py``, and ``pipeline.py``, plus a
pytest module at ``tests/systems/test_<name>.py``. Files are wired to the
shared layers so nothing is duplicated:

- retrieval  -> ``tools.search_tool`` (+ ``utils.fetch_doc``)   [corpus-only]
- artifacts  -> ``ragrun`` (TrajectoryBuilder / build_rag_output / save_run)
- answer fmt -> ``ali_deepresearch.answer_format.format_answer``
- backends   -> ``aus_agent.agent.make_provider`` (bedrock / openai)  [optional]

The generated ``pipeline.py`` carries an ``ARCH_STAGES`` literal so the new
system shows up in the interactive architecture diagram; after filling it in,
regenerate + launch it with
``gen_arch_viz.py --system <name>`` (printed in the checklist).

It does NOT edit ``pyproject.toml`` or write the README/worklog — those steps
are printed as a checklist so the human/agent stays in the loop (a dep group
and a README are required by the repo conventions).

Usage (from the repo root):

    python skills/trec-rag-new-system/scripts/scaffold_system.py my_system \\
        --backends aus_agent          # reuse the pluggable providers
    python skills/trec-rag-new-system/scripts/scaffold_system.py my_baseline \\
        --backends openai             # own thin OpenAI ChatLLM, no provider dep
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SYSTEMS_DIR = REPO_ROOT / "src" / "systems"
TESTS_DIR = REPO_ROOT / "tests" / "systems"


def _valid_name(name: str) -> str:
    if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
        raise SystemExit(
            f"invalid system name {name!r}: use lowercase snake_case "
            "(e.g. my_system), matching the existing packages")
    return name


INIT_PY = '''\
"""{name} — <one-line description> (TREC RAG 2026).

Corpus-only RAG over ClimbMix: retrieval goes through ``tools.search_tool`` /
``utils.fetch_doc`` and every citation is a ClimbMix docid. Both run artifacts
are written under ``data/outputs/{name}/`` via ``ragrun.save_run``.
"""
from .pipeline import SYSTEM_NAME, run_one

__all__ = ["SYSTEM_NAME", "run_one"]
'''

PROMPTS_PY = '''\
"""Prompts for {name}.

Keep the engine list, query-writing guidance, and the strict citation shape out
of these strings — they are produced by ``tools.search_tool`` and
``ali_deepresearch.answer_format`` respectively (single source of truth).
"""
from __future__ import annotations

SYSTEM_PROMPT = (
    "You are a research assistant answering a query using ONLY the ClimbMix "
    "document corpus, reached through the search tool. Do not use prior "
    "knowledge for factual claims; cite the documents you rely on by docid."
)
'''

PIPELINE_PY = '''\
"""{name} pipeline — retrieve -> generate -> strict TREC RAG artifacts.

Fill in ``run_one`` with this system's control flow. The scaffold shows the
standard wiring: build a trajectory, retrieve via the shared search tool,
synthesize an answer, map it to the strict sentence/citation shape, and persist
both artifacts. Replace the TODOs with the real logic.
"""
from __future__ import annotations

import json
from typing import Any

from ragrun import TrajectoryBuilder, build_rag_output, now_iso, save_run
from tools.search_tool import run_search_tool

from ali_deepresearch.answer_format import format_answer

SYSTEM_NAME = "{name}"

# Ordered stage flow for the architecture visualization
# (skills/trec-rag-new-system/scripts/gen_arch_viz.py reads this literal — no
# import — so this system appears in docs/architecture.html for free). Edit the
# labels/kinds to match the real control flow below.
# stage kind in {{llm, no-llm, retrieval, format, artifact, loop}}.
# An agent with a cycle leads with a {{"kind": "loop"}} stage that DECLARES the
# span it repeats: "back_to"/"back_from" are stage ids (plus optional
# "back_label"). Without them no loop-back arrow is drawn. A "loop" stage may
# also set "parallel_over" (e.g. "facet") if its iterations run concurrently
# across something, not just sequentially.
# Optional per-stage detail (issue #20, shown in the click-to-open panel):
# "prompt": ["<path-relative-to-src>::CONST", ...] and/or
# "code": ["<path-relative-to-src>::func_or_Class.method", ...] -- both are
# verified against real source at generation time (a rename/removal fails
# loudly). "run" (llm/code/llm+code) is derived from which of these a stage
# declares, never hand-authored. "tools": [{{"name", "ref"}}] for native
# tool-calling, or "engines": {{"mandatory": ref, "optional": ref}} (refs to
# tuple/list constants) for an engine-blurb style; "tools_note" is a one-line
# why/how. See the `trec-rag-new-system` skill for the full field reference.
ARCH_STAGES = [
    {{"id": "retrieve", "label": "RETRIEVE", "kind": "retrieval",
     "note": "search ClimbMix via tools.search_tool"}},
    {{"id": "generate", "label": "GENERATE", "kind": "llm",
     "note": "synthesize a grounded answer"}},
    {{"id": "format", "label": "FORMAT", "kind": "format",
     "note": "answer_format: prose -> references[] + citations"}},
    {{"id": "save", "label": "SAVE", "kind": "artifact",
     "note": "ragrun.save_run -> trajectory + output"}},
]


def run_one(*, qid: str, narrative: str, run_id: str, run_desc: str,
            model_id: str, k: int = 10, format_llm: Any | None = None
            ) -> dict[str, Any]:
    """Run the system for one narrative and write its artifacts."""
    started_at = now_iso()
    tb = TrajectoryBuilder(qid, narrative, metadata={{
        "model": model_id, "run_id": run_id, "query_source": narrative,
    }})

    # --- TODO: real retrieval/generation control flow ---------------------
    # Example single retrieval step (replace with this system's strategy):
    t0 = now_iso()
    output_json = run_search_tool(narrative, k=k, max_chars=2000,
                                  search_engine="semantic")
    data = json.loads(output_json)
    docids = [r["docid"] for r in data.get("results", [])]
    tb.add_tool_call("search", {{"query": narrative, "k": k}}, output_json,
                     returned_docids=docids, t_start=t0, t_end=now_iso(),
                     turn=0)

    draft = ""  # TODO: synthesize a grounded answer from the retrieved passages
    tb.add_output_text(draft, t_start=now_iso(), t_end=now_iso(), turn=0)

    # --- strict sentence/citation shape (reused, do not reimplement) -------
    references, answer = format_answer(draft, docids, llm=format_llm)
    ended_at = now_iso()
    status = "completed" if references else "no_references"
    trajectory = tb.finalize(status=status, started_at=started_at,
                             ended_at=ended_at)
    output = build_rag_output(
        narrative_id=qid, narrative=narrative, run_id=run_id,
        run_desc=run_desc, references=references, answer=answer)
    paths = save_run(SYSTEM_NAME, narrative, trajectory=trajectory,
                     output=output)
    return {{"paths": paths, "references": references, "status": status}}
'''

RUN_PY_HEADER = '''\
"""{name} — <one-line description> (TREC RAG 2026).

Examples (repo root):

    uv run --group {group} python src/systems/{name}/run.py --qid <id>
    uv run --group {group} python src/systems/{name}/run.py --query "..."
    uv run --group {group} python src/systems/{name}/run.py --all
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# --- import surgery (shared by every system's run.py) -----------------------
# Put src/systems on the path and drop this package dir, so ``ragrun``,
# ``ali_deepresearch``, ``aus_agent``, ``tools.*`` and ``utils.*`` all resolve
# whether run from the repo root or from inside the package.
_HERE = os.path.dirname(os.path.abspath(__file__))
_SYSTEMS = os.path.dirname(_HERE)
sys.path[:] = [p for p in sys.path if os.path.abspath(p or ".") != _HERE]
if _SYSTEMS not in sys.path:
    sys.path.insert(0, _SYSTEMS)

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

from {name}.pipeline import run_one  # noqa: E402
'''

RUN_PY_PROVIDER = '''\
from aus_agent.agent import make_provider  # noqa: E402  (reuse the factory)
'''

RUN_PY_MAIN = '''\

_REPO_ROOT = Path(_SYSTEMS).resolve().parents[1]
DEFAULT_TOPICS = (_REPO_ROOT / "data/official/trec-rag-2026-data/trec-rag-2026/"
                  "development-data/topics/research-rubrics-topics-dev.tsv")


def load_topics(path: Path) -> list[tuple[str, str]]:
    rows = []
    for line in path.read_text().splitlines():
        qid, _, narrative = line.partition("\\t")
        if qid.strip() and narrative.strip():
            rows.append((qid.strip(), narrative.strip()))
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description="{name} — corpus-only RAG")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--query")
    g.add_argument("--qid")
    g.add_argument("--all", action="store_true")
    ap.add_argument("--topics", type=Path, default=DEFAULT_TOPICS)
    ap.add_argument("--model", default=None)
    ap.add_argument("--run-id", default="{name}.dev")
    ap.add_argument("--run-desc", default="{name}: <describe the run>")
    ap.add_argument("--no-format-llm", action="store_true")
    args = ap.parse_args()

    model_id = args.model or "TODO-default-model"

    if args.query:
        items = [("adhoc", args.query)]
    else:
        topics = load_topics(args.topics)
        items = topics if args.all else [(q, n) for q, n in topics
                                         if q == args.qid]
        if not items:
            ap.error(f"qid {{args.qid!r}} not found in {{args.topics}}")

    for qid, narrative in items:
        result = run_one(qid=qid, narrative=narrative, run_id=args.run_id,
                         run_desc=args.run_desc, model_id=model_id)
        paths = result["paths"]
        tag = "OK" if "violations" not in paths else "VIOLATIONS"
        print(f"[{{tag}}] {{qid}}: status={{result['status']}} "
              f"refs={{len(result['references'])}} -> {{paths['output'].name}}")


if __name__ == "__main__":
    main()
'''

TEST_MOCK_PY = '''\
"""End-to-end tests for {name} — collected by ``pytest``, hermetic by default.

The offline test drives the REAL ``pipeline.run_one`` with retrieval stubbed at
``tools.search_tool._DISPATCH`` (the ``stub_search_tool`` fixture), so the whole
pipeline — plus artifact writing and TREC-spec validation — is proven with no
credentials and no network. The ``live`` test is the same path against the real
ClimbMix endpoints; it is deselected unless you ask for it.

Fixtures come from ``tests/conftest.py``: ``stub_search_tool``,
``scripted_provider``, ``read_artifacts``, and the autouse ``no_network`` /
``isolated_data_dir`` guards. See that file for the full list.

Run:  uv run --group dev pytest tests/systems/test_{name}.py
      uv run --group dev pytest tests/systems/test_{name}.py -m live   # real
"""
from __future__ import annotations

import pytest

from ragrun import validate_rag_output

from {name}.pipeline import run_one

NARRATIVE = "How effective are influenza vaccines at preventing illness?"
QID = "mock_{name}_001"


def _run(**kwargs):
    """Invoke the pipeline with this system's standard test arguments.

    TODO: if this system calls an LLM, pass a scripted provider here —
    ``scripted_provider([model_turn(text=...), ...])`` or the responder form
    for stage-dependent turns. See ``tests/systems/test_facet_rag.py``.
    """
    return run_one(qid=QID, narrative=NARRATIVE, run_id="{name}.mock",
                   run_desc="mock end-to-end test", model_id="mock/{name}",
                   **kwargs)


def test_run_one_writes_valid_artifacts(stub_search_tool, read_artifacts):
    """The pipeline produces both artifacts, spec-clean, with real retrieval
    plumbing exercised against stubbed transport."""
    result = _run()
    artifacts = read_artifacts(result["paths"])

    assert artifacts["output"], "output.json not written"
    assert artifacts["trajectory"], "trajectory.json not written"
    # A violations file means the output breaks the TREC RAG 2026 spec.
    assert artifacts["violations"] == []
    assert validate_rag_output(artifacts["output"]) == []
    assert result["references"]
    assert artifacts["trajectory"]["retrieved_docids"]
    # The rich trace is internal to output.json and must never leak into the
    # strict trajectory projection.
    assert "trace" not in artifacts["trajectory"]
    assert artifacts["output"]["trace"]["steps"]


def test_search_is_routed_to_the_expected_engine(stub_search_tool):
    """Retrieval goes through tools.search_tool, so the stub records it."""
    _run()
    assert stub_search_tool, "no engine was called — is retrieval wired up?"


@pytest.mark.live
def test_run_one_live():
    """Same path against the real ClimbMix endpoints (needs SEARCH_API_KEY)."""
    result = _run()
    assert result["references"]
    assert "violations" not in result["paths"]
'''


def write(path: Path, content: str, *, force: bool) -> None:
    if path.exists() and not force:
        raise SystemExit(f"refusing to overwrite {path} (pass --force)")
    path.write_text(content)
    print(f"  wrote {path.relative_to(REPO_ROOT)}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Scaffold a new src/systems/<name> package")
    ap.add_argument("name", type=_valid_name, help="system package name (snake_case)")
    ap.add_argument("--backends", choices=("aus_agent", "openai", "none"),
                    default="none",
                    help="aus_agent: reuse pluggable providers via make_provider; "
                         "openai: leave a thin ChatLLM to fill in; "
                         "none: no LLM wiring in run.py")
    ap.add_argument("--group", default=None,
                    help="dep-group name for uv (default: <name> with _ -> -)")
    ap.add_argument("--force", action="store_true", help="overwrite existing files")
    args = ap.parse_args()

    name = args.name
    group = args.group or name.replace("_", "-")
    pkg = SYSTEMS_DIR / name
    pkg.mkdir(parents=True, exist_ok=True)
    print(f"scaffolding src/systems/{name}/ (backends={args.backends}, group={group})")

    write(pkg / "__init__.py", INIT_PY.format(name=name), force=args.force)
    write(pkg / "prompts.py", PROMPTS_PY.format(name=name), force=args.force)
    write(pkg / "pipeline.py", PIPELINE_PY.format(name=name), force=args.force)
    # Tests live in the collected suite under tests/, not beside the package:
    # pytest owns discovery (see [tool.pytest.ini_options] testpaths) and the
    # shared fixtures in tests/conftest.py are what make them hermetic.
    TESTS_DIR.mkdir(parents=True, exist_ok=True)
    write(TESTS_DIR / f"test_{name}.py",
          TEST_MOCK_PY.format(name=name, group=group), force=args.force)

    run_py = RUN_PY_HEADER.format(name=name, group=group)
    if args.backends == "aus_agent":
        run_py += RUN_PY_PROVIDER
    run_py += RUN_PY_MAIN.format(name=name)
    write(pkg / "run.py", run_py, force=args.force)

    deps = {
        "aus_agent": '\n    "boto3>=1.40",\n    "openai>=2.45",',
        "openai": '\n    "openai>=2.45",',
        "none": "",
    }[args.backends]
    print("\nNEXT STEPS (not automated — keep yourself in the loop):")
    print(f"  1. Add a dep group to the root pyproject.toml [dependency-groups]:")
    print(f"       {group} = [{deps}\n       ]")
    print(f"     then:  uv sync --group {group}")
    print(f"  2. Fill in pipeline.py (run_one), prompts.py, and run.py TODOs.")
    print(f"  3. Write src/systems/{name}/README.md (design + CLI + tests).")
    print(f"  4. Fill in the scripted-provider TODO, then run the offline test:")
    print(f"       uv run --group dev pytest tests/systems/test_{name}.py")
    print(f"  5. Edit ARCH_STAGES in pipeline.py to match the real flow, then"
          f" regenerate + launch the architecture diagram:")
    print(f"       python skills/trec-rag-new-system/scripts/gen_arch_viz.py"
          f" --system {name}")
    print(f"  6. Take a worklog: worklogs/YYYY-MM-DD-{name}.md")


if __name__ == "__main__":
    main()
