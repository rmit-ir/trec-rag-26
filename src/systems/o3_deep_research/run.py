"""OpenAI Deep Research baseline, grounded on ClimbMix via remote MCP.

Runs OpenAI's hosted deep-research agent (``o3-deep-research`` /
``o4-mini-deep-research``, Responses API) with **no web search** — its only
data source is our ClimbMix MCP server (``src/mcp/climbmix_server.py``)
exposing corpus ``search``/``fetch``. This makes the official frontier DR
agent a fair, corpus-grounded baseline against our own systems: same corpus,
same retrieval stack, same output artifacts.

The MCP server must be reachable *by OpenAI's servers* (public URL — e.g. a
cloudflared tunnel in front of the local server). Pass it via ``--mcp-url`` or
``O3DR_MCP_URL``.

Endpoint config (env, auto-loaded from repo ``.env``):

    OPENAI_DEEP_RESEARCH_API_KEY   platform.openai.com key (NOT the Azure one)
    O3DR_MCP_URL                   public MCP URL (…/mcp)
    CLIMBMIX_MCP_TOKEN             bearer token the MCP server expects (if set)
    O3DR_MODEL                     default o3-deep-research

The base URL is pinned to ``https://api.openai.com/v1`` — the repo ``.env``
also carries ``OPENAI_BASE_URL`` (Azure) which the SDK would otherwise pick up.

Examples (repo root):

    uv run --group o3-deep-research python src/systems/o3_deep_research/run.py \\
        --qid 683a58c9a7e7fe4e76958498 --mcp-url https://<tunnel>/mcp
    uv run --group o3-deep-research python src/systems/o3_deep_research/run.py \\
        --query "..." --model o4-mini-deep-research   # cheap plumbing check
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

# --- import surgery (same pattern as ali_deepresearch/run.py) ---------------
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

from ragrun import TrajectoryBuilder, build_rag_output, now_iso, save_run  # noqa: E402

from ali_deepresearch.answer_format import format_answer  # noqa: E402

SYSTEM_NAME = "o3_deep_research"
DEFAULT_MODEL = "o3-deep-research"
DEFAULT_FORMAT_MODEL = "gpt-5.6-luna"
OPENAI_BASE_URL = "https://api.openai.com/v1"
_REPO_ROOT = Path(_SYSTEMS).resolve().parents[1]
DEFAULT_TOPICS = (_REPO_ROOT / "data/official/trec-rag-2026-data/trec-rag-2026/"
                  "development-data/topics/research-rubrics-topics-dev.tsv")

# Corpus-grounding instructions. DR models plan their own research; we only
# pin the ground rules: corpus-only, fetch before cite.
SYSTEM_PROMPT = (
    "You are a research assistant producing a thorough, well-structured "
    "report. Your ONLY source of information is the ClimbMix document corpus, "
    "reachable through the `search` and `fetch` tools. Do not rely on prior "
    "knowledge for factual claims. Search broadly with varied queries, fetch "
    "the full text of every document you rely on before citing it, and cite "
    "the documents you used inline. Write the final report in clear prose."
)


class FormatLLM:
    """Minimal ChatLLM for ``format_answer`` (chat-completions, retries)."""

    def __init__(self, *, api_key: str, model: str) -> None:
        from openai import OpenAI

        self.model = model
        self._client = OpenAI(api_key=api_key, base_url=OPENAI_BASE_URL,
                              timeout=300)

    def complete(self, messages: list[dict[str, str]], *,
                 stop: list[str] | None = None,
                 max_tokens: int | None = None) -> str:
        last: Exception | None = None
        for attempt in range(3):
            try:
                resp = self._client.chat.completions.create(
                    model=self.model, messages=messages, stop=stop,
                    max_completion_tokens=max_tokens or 10000)
                text = resp.choices[0].message.content
                if text and text.strip():
                    return text.strip()
            except Exception as e:
                last = e
            time.sleep(2 ** attempt)
        raise RuntimeError(f"format LLM failed: {last}")


# --- Responses-API item mapping ---------------------------------------------

def _docids_from_mcp_output(name: str, arguments: str, output: str) -> list[str]:
    """ClimbMix docids surfaced by one MCP tool result."""
    try:
        if name == "search":
            payload = json.loads(output)
            if isinstance(payload, str):  # server may double-encode
                payload = json.loads(payload)
            return [r["id"] for r in payload.get("results", []) if r.get("id")]
        if name == "fetch":
            args = json.loads(arguments or "{}")
            return [args["id"]] if args.get("id") else []
    except (json.JSONDecodeError, TypeError, KeyError):
        pass
    return []


def add_item_step(tb: TrajectoryBuilder, item: Any, *, turn: int,
                  t_start: str | None, t_end: str | None,
                  state: dict[str, Any]) -> None:
    """Map one Responses output item onto trajectory steps."""
    typ = getattr(item, "type", None)
    timing = {"t_start": t_start, "t_end": t_end, "turn": turn}
    if typ == "reasoning":
        text = "\n\n".join(
            s.text for s in (getattr(item, "summary", None) or [])
            if getattr(s, "text", None))
        if text:
            tb.add_reasoning(text, **timing)
    elif typ == "mcp_call":
        name = getattr(item, "name", "") or "mcp_call"
        arguments = getattr(item, "arguments", "") or ""
        output = getattr(item, "output", None) or ""
        error = getattr(item, "error", None)
        docids = _docids_from_mcp_output(name, arguments, output)
        if name == "fetch":
            state["fetched"].extend(docids)
        else:
            state["searched"].extend(docids)
        tb.add_tool_call(
            name, arguments, output if not error else str(error),
            returned_docids=docids or None, failed=bool(error), **timing)
    elif typ == "mcp_list_tools":
        tools = [t.get("name") if isinstance(t, dict) else getattr(t, "name", "")
                 for t in (getattr(item, "tools", None) or [])]
        tb.add_tool_call("mcp_list_tools", {}, json.dumps(tools), **timing)
    elif typ == "message":
        text = "".join(
            getattr(c, "text", "") for c in (getattr(item, "content", None) or [])
            if getattr(c, "type", "") == "output_text")
        if text:
            state["answer"] = text


def usage_stats(resp: Any) -> dict[str, Any] | None:
    u = getattr(resp, "usage", None)
    if u is None:
        return None
    cached = getattr(getattr(u, "input_tokens_details", None), "cached_tokens", 0) or 0
    inp = u.input_tokens or 0
    out = u.output_tokens or 0
    uncached = max(inp - cached, 0)
    return {"tokens": {
        "input": inp, "input_uncached": uncached, "cache_read": cached,
        "cache_write": 0, "output": out, "total": u.total_tokens or (inp + out),
        "processed_input": uncached, "processed": uncached + out,
    }}


# --- main run ----------------------------------------------------------------

def _retrieve(client: Any, response_id: str, tries: int = 6) -> Any:
    """Poll retrieve with backoff — transient 5xx must not kill a paid run."""
    last: Exception | None = None
    for attempt in range(tries):
        try:
            return client.responses.retrieve(response_id)
        except Exception as e:
            last = e
            print(f"[!!] retrieve {response_id}: {type(e).__name__} "
                  f"(attempt {attempt + 1}/{tries})")
            time.sleep(min(2 ** attempt * 5, 120))
    raise RuntimeError(f"retrieve failed after {tries} tries: {last}")


def run_one(client: Any, *, qid: str, query: str, args: argparse.Namespace,
            format_llm: Any | None) -> dict[str, Path]:
    tool: dict[str, Any] = {
        "type": "mcp",
        "server_label": "climbmix",
        "server_description": "ClimbMix corpus search: `search` finds documents,"
                              " `fetch` retrieves full text by id.",
        "server_url": args.mcp_url,
        "require_approval": "never",
    }
    if args.mcp_token:
        tool["headers"] = {"Authorization": f"Bearer {args.mcp_token}"}

    started_at = now_iso()
    item_t0: dict[int, str] = {}
    item_t1: dict[int, str] = {}
    resp = None
    if args.resume:
        # Note: plain retrieve on in-flight DR+MCP responses has been observed
        # to 500 server-side (2026-07-19); resume works once the run finished.
        resp = _retrieve(client, args.resume)
        print(f"[..] {qid}: resumed {resp.id} status={resp.status}")
        while resp.status in ("queued", "in_progress"):
            time.sleep(args.poll_interval)
            resp = _retrieve(client, resp.id)
    else:
        # Streaming, not poll-retrieve: `responses.retrieve` on a background
        # DR run with MCP items 500s reliably (OpenAI-side, 2026-07-19), and
        # stream events also give exact per-item timing.
        kwargs: dict[str, Any] = {}
        if args.max_tool_calls:
            kwargs["max_tool_calls"] = args.max_tool_calls
        if not args.no_reasoning_summary:
            kwargs["reasoning"] = {"summary": "auto"}
        stream = client.responses.create(
            model=args.model,
            background=not args.no_background,
            stream=True,
            instructions=SYSTEM_PROMPT,
            input=query,
            tools=[tool],
            **kwargs)
        resp_id: str | None = None
        cursor: int | None = None
        reconnects = 0
        while resp is None:
            try:
                for event in stream:
                    cursor = getattr(event, "sequence_number", cursor)
                    et = getattr(event, "type", "")
                    if et in ("response.created", "response.queued"):
                        if resp_id is None:
                            resp_id = event.response.id
                            print(f"[..] {qid}: response {resp_id} "
                                  f"status={event.response.status}", flush=True)
                    elif et == "response.output_item.added":
                        item_t0[event.output_index] = now_iso()
                    elif et == "response.output_item.done":
                        item_t1[event.output_index] = now_iso()
                        item = event.item
                        label = getattr(item, "name", None) or getattr(item, "type", "?")
                        print(f"[..] {qid}: item {event.output_index} done: "
                              f"{label}", flush=True)
                    elif et in ("response.completed", "response.failed",
                                "response.incomplete"):
                        resp = event.response
                if resp is None and resp_id is None:
                    raise RuntimeError("stream ended before response.created")
                if resp is None:  # stream ended without a terminal event
                    resp = _retrieve(client, resp_id)
            except Exception as e:
                if resp is not None or resp_id is None:
                    raise
                reconnects += 1
                if reconnects > 12:
                    raise RuntimeError(
                        f"stream irrecoverable after {reconnects - 1} "
                        f"reconnects; resume later with --resume {resp_id}"
                    ) from e
                print(f"[!!] stream dropped ({type(e).__name__}: "
                      f"{str(e)[:120]}); reconnect {reconnects}/12 "
                      f"after seq {cursor}…", flush=True)
                time.sleep(min(5 * reconnects, 60))
                stream = client.responses.retrieve(
                    resp_id, stream=True, starting_after=cursor)
    ended_at = now_iso()
    items = resp.output or []

    meta = {
        "model": args.model,
        "backend": "openai-responses",
        "mcp_server": args.mcp_url,
        "run_id": args.run_id,
        "timing_resolution": "stream-events" if not args.resume else "run-bounds",
        "query_source": query,
    }
    tb = TrajectoryBuilder(qid, query, metadata=meta)
    state: dict[str, Any] = {"answer": None, "fetched": [], "searched": []}
    for i, item in enumerate(items):
        add_item_step(tb, item, turn=i, t_start=item_t0.get(i, started_at),
                      t_end=item_t1.get(i, ended_at), state=state)

    answer_text = state["answer"] or ""
    stats = usage_stats(resp)
    tb.add_model_step(output="deep-research run", input=query,
                      t_start=started_at, t_end=ended_at, stats=stats)
    if answer_text:
        tb.add_output_text(answer_text,
                           t_start=item_t0.get(len(items) - 1, started_at),
                           t_end=ended_at)

    status = "completed" if (resp.status == "completed" and answer_text) else str(resp.status)
    trajectory = tb.finalize(status=status, started_at=started_at,
                             ended_at=ended_at)

    # fetched docs first — the agent actually read those.
    candidates = list(dict.fromkeys(state["fetched"] + state["searched"]))
    references, answer = format_answer(answer_text, candidates, llm=format_llm)
    output = build_rag_output(
        narrative_id=qid, narrative=query, run_id=args.run_id,
        run_desc=args.run_desc, references=references, answer=answer)

    paths = save_run(SYSTEM_NAME, query, trajectory=trajectory, output=output)
    tag = "OK" if "violations" not in paths else "VIOLATIONS"
    print(f"[{tag}] {qid}: status={status} items={len(items)} "
          f"refs={len(references)} -> {paths['output'].name}")
    return paths


def load_topics(path: Path) -> list[tuple[str, str]]:
    rows = []
    for line in path.read_text().splitlines():
        qid, _, narrative = line.partition("\t")
        if qid.strip() and narrative.strip():
            rows.append((qid.strip(), narrative.strip()))
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(
        description="OpenAI Deep Research on ClimbMix (remote MCP grounding)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--query")
    g.add_argument("--qid")
    g.add_argument("--all", action="store_true")
    ap.add_argument("--topics", type=Path, default=DEFAULT_TOPICS)
    ap.add_argument("--mcp-url", default=os.environ.get("O3DR_MCP_URL"))
    ap.add_argument("--mcp-token", default=os.environ.get("CLIMBMIX_MCP_TOKEN"))
    ap.add_argument("--model", default=os.environ.get("O3DR_MODEL", DEFAULT_MODEL))
    ap.add_argument("--max-tool-calls", type=int, default=None)
    ap.add_argument("--poll-interval", type=float, default=15.0)
    ap.add_argument("--no-reasoning-summary", action="store_true",
                    help="Omit reasoning.summary=auto (suspected trigger of "
                         "mid-stream APIErrors in DR+MCP runs, 2026-07-19); "
                         "trajectory loses reasoning steps but keeps tool calls.")
    ap.add_argument("--no-background", action="store_true",
                    help="Synchronous streaming (no background mode). One "
                         "connection start-to-finish; no resume, but avoids "
                         "the background+MCP read-back bugs.")
    ap.add_argument("--resume", metavar="RESPONSE_ID",
                    help="Skip create; poll an existing background response "
                         "and build artifacts from it (use with --query/--qid "
                         "matching the original run).")
    ap.add_argument("--run-id", default="o3-deep-research.dev")
    ap.add_argument("--run-desc",
                    default="OpenAI o3-deep-research (Responses API), corpus-"
                            "grounded on ClimbMix via remote MCP (hybrid RRF "
                            "search + full-doc fetch); no web search.")
    ap.add_argument("--format-model", default=DEFAULT_FORMAT_MODEL)
    ap.add_argument("--no-format-llm", action="store_true")
    args = ap.parse_args()

    api_key = os.environ.get("OPENAI_DEEP_RESEARCH_API_KEY")
    if not api_key:
        ap.error("OPENAI_DEEP_RESEARCH_API_KEY not set")
    if not args.mcp_url:
        ap.error("no MCP server: set O3DR_MCP_URL or pass --mcp-url")

    from openai import OpenAI

    client = OpenAI(api_key=api_key, base_url=OPENAI_BASE_URL, timeout=600)
    format_llm = None if args.no_format_llm else FormatLLM(
        api_key=api_key, model=args.format_model)

    if args.query:
        items = [("adhoc", args.query)]
    else:
        topics = load_topics(args.topics)
        items = topics if args.all else [(q, n) for q, n in topics if q == args.qid]
        if not items:
            ap.error(f"qid {args.qid!r} not found in {args.topics}")

    for qid, query in items:
        run_one(client, qid=qid, query=query, args=args, format_llm=format_llm)


if __name__ == "__main__":
    main()
