"""ClimbMix port of Alibaba Tongyi DeepResearch's multi-turn ReAct loop.

Faithful, minimal port of ``inference/react_agent.py::MultiTurnReactAgent._run``
from https://github.com/Alibaba-NLP/DeepResearch. Kept:

- The ReAct loop over an OpenAI-compatible chat-completions endpoint.
- The token protocol: ``<think>…</think>`` reasoning, ``<tool_call>{json}
  </tool_call>`` calls, ``<tool_response>…</tool_response>`` results,
  ``<answer>…</answer>`` termination.
- Stop tokens ``["\\n<tool_response>", "<tool_response>"]`` and the truncation of
  any ``<tool_response>`` the model hallucinates past the stop.
- Max-round / max-llm-call budgeting and the "context length reached → force a
  final answer" fallback.

Replaced / trimmed (see README for the full mapping table):

- Upstream's ``qwen_agent`` tool classes → ``tools.ClimbMixTools`` (corpus-only
  ``search`` + ``get_document``, no web).
- Upstream's HuggingFace ``AutoTokenizer`` token count → a dependency-free
  char/4 heuristic (we ship only the ``openai`` client, not ``transformers``).
- The LLM transport is injected (``ChatLLM`` protocol) so the loop runs
  unchanged against a real vLLM/OpenRouter endpoint or an in-process mock.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from ragrun import now_iso

from .tools import ClimbMixTools, dispatch

# Upstream stop sequence — cut generation as soon as the model tries to author
# the tool response itself.
STOP = ["\n<tool_response>", "<tool_response>"]
OBS_START = "<tool_response>"
OBS_END = "\n</tool_response>"

DEFAULT_MAX_ROUNDS = 20          # upstream MAX_LLM_CALL_PER_RUN is 100
DEFAULT_MAX_TOKENS = 10000       # upstream max_tokens per call
# Char/4 approximation of upstream's 110*1024-token context guard.
DEFAULT_CONTEXT_CHAR_LIMIT = 110 * 1024 * 4

_THINK_RE = re.compile(r"<think>(.*?)</think>", re.DOTALL)
_TOOLCALL_RE = re.compile(r"<tool_call>(.*?)</tool_call>", re.DOTALL)
_ANSWER_RE = re.compile(r"<answer>(.*?)</answer>", re.DOTALL)

_FORCE_ANSWER_MSG = (
    "You have now reached the maximum context length you can handle. You should "
    "stop making tool calls and, based on all the information above, think again "
    "and provide what you consider the most likely answer in the following "
    "format:<think>your final thinking</think>\n<answer>your answer</answer>"
)


class ChatLLM(Protocol):
    """Minimal transport the loop needs — one blocking completion call."""

    def complete(self, messages: list[dict[str, str]], *,
                 stop: list[str] | None = None,
                 max_tokens: int | None = None) -> str:
        ...


@dataclass
class AgentResult:
    """Everything a run produces, ready for trajectory/output assembly.

    Each step dict carries wall-clock ``t_start``/``t_end`` (``ragrun.now_iso``)
    and a 0-based ``turn`` = the LLM-round index that produced it; the loop is
    strictly sequential, so bounds never overlap across steps.
    """

    query: str
    query_id: str
    status: str                                   # completed | ... | max_rounds
    answer_text: str | None
    steps: list[dict[str, Any]] = field(default_factory=list)
    messages: list[dict[str, str]] = field(default_factory=list)
    rounds: int = 0
    started_at: str | None = None                 # run wall-clock bounds
    ended_at: str | None = None


class ReactAgent:
    """Ported multi-turn ReAct agent over the ClimbMix tools."""

    def __init__(self, llm: ChatLLM, system_prompt: str, *,
                 toolbox: ClimbMixTools | None = None,
                 k: int = 10,
                 max_rounds: int = DEFAULT_MAX_ROUNDS,
                 max_tokens: int = DEFAULT_MAX_TOKENS,
                 context_char_limit: int = DEFAULT_CONTEXT_CHAR_LIMIT) -> None:
        self.llm = llm
        self.system_prompt = system_prompt
        self.toolbox = toolbox or ClimbMixTools()
        self.k = k
        self.max_rounds = max_rounds
        self.max_tokens = max_tokens
        self.context_char_limit = context_char_limit

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _approx_tokens(messages: list[dict[str, str]]) -> int:
        return sum(len(m.get("content", "")) for m in messages) // 4

    @staticmethod
    def _parse_tool_call(blob: str) -> tuple[str, dict[str, Any]] | None:
        """Parse the JSON inside <tool_call>…</tool_call> (lenient)."""
        blob = blob.strip()
        try:
            obj = json.loads(blob)
        except json.JSONDecodeError:
            # Tolerate single quotes / trailing junk the model sometimes emits.
            try:
                obj = json.loads(blob.replace("'", '"'))
            except json.JSONDecodeError:
                return None
        if not isinstance(obj, dict) or "name" not in obj:
            return None
        return obj.get("name", ""), obj.get("arguments", {}) or {}

    # -- main loop ---------------------------------------------------------

    def run(self, query: str, query_id: str = "query") -> AgentResult:
        messages: list[dict[str, str]] = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": query},
        ]
        steps: list[dict[str, Any]] = []
        calls_left = self.max_rounds
        rounds = 0
        status = "max_rounds"
        answer_text: str | None = None
        started_at = now_iso()

        while calls_left > 0:
            calls_left -= 1
            rounds += 1
            turn = rounds - 1  # 0-based LLM-round index
            t0 = now_iso()
            content = self.llm.complete(messages, stop=STOP,
                                        max_tokens=self.max_tokens)
            t1 = now_iso()
            content = (content or "").strip()
            # Drop anything the model wrote past a hallucinated tool_response.
            if OBS_START in content:
                content = content[:content.find(OBS_START)].strip()
            messages.append({"role": "assistant", "content": content})

            # <think> → reasoning step (fall back to leading prose if untagged).
            think = self._extract_think(content)
            if think:
                steps.append({"kind": "reasoning", "text": think,
                              "t_start": t0, "t_end": t1, "turn": turn})

            answer_m = _ANSWER_RE.search(content)
            toolcall_m = _TOOLCALL_RE.search(content)

            if toolcall_m and not answer_m:
                self._handle_tool_call(toolcall_m.group(1), messages, steps,
                                       turn=turn)

            if answer_m:
                answer_text = answer_m.group(1).strip()
                steps.append({"kind": "answer", "text": answer_text,
                              "t_start": t0, "t_end": t1, "turn": turn})
                status = "completed"
                break

            # Budget exhausted with no answer → last message nudges upstream-style.
            if calls_left <= 0:
                status = "max_rounds"
                break

            # Context-window guard: force a single final-answer turn.
            if self._approx_tokens(messages) > self.context_char_limit:
                answer_text, status = self._force_final_answer(messages, steps,
                                                               turn=rounds)
                break

        return AgentResult(query=query, query_id=query_id, status=status,
                           answer_text=answer_text, steps=steps,
                           messages=messages, rounds=rounds,
                           started_at=started_at, ended_at=now_iso())

    def _extract_think(self, content: str) -> str:
        m = _THINK_RE.search(content)
        if m:
            return m.group(1).strip()
        # Untagged leading reasoning before the first tag, if any.
        head = re.split(r"<(?:tool_call|answer)>", content, maxsplit=1)[0].strip()
        return head if head and "<think>" not in content else ""

    def _handle_tool_call(self, blob: str, messages: list[dict[str, str]],
                          steps: list[dict[str, Any]], *, turn: int) -> None:
        t0 = now_iso()
        parsed = self._parse_tool_call(blob)
        if parsed is None:
            result = ('Error: Tool call is not a valid JSON. Tool call must '
                      'contain a valid "name" and "arguments" field.')
            messages.append({"role": "user",
                             "content": OBS_START + "\n" + result + OBS_END})
            steps.append({"kind": "tool_call", "name": "unknown",
                          "arguments": {"raw": blob.strip()}, "output": result,
                          "returned": None, "failed": True, "extras": {},
                          "t_start": t0, "t_end": now_iso(), "turn": turn})
            return

        name, args = parsed
        result, meta, failed = dispatch(self.toolbox, name, args, k=self.k)
        t1 = now_iso()
        messages.append({"role": "user",
                         "content": OBS_START + "\n" + result + OBS_END})
        extras = {kk: vv for kk, vv in meta.items()
                  if kk not in ("returned", "returned_docids", "failed")}
        steps.append({"kind": "tool_call", "name": name, "arguments": args,
                      "output": result, "returned": meta.get("returned"),
                      "returned_docids": meta.get("returned_docids"),
                      "failed": failed, "extras": extras,
                      "t_start": t0, "t_end": t1, "turn": turn})

    def _force_final_answer(self, messages: list[dict[str, str]],
                            steps: list[dict[str, Any]], *,
                            turn: int) -> tuple[str | None, str]:
        messages[-1]["content"] = _FORCE_ANSWER_MSG
        t0 = now_iso()
        content = (self.llm.complete(messages, stop=None,
                                     max_tokens=self.max_tokens) or "").strip()
        t1 = now_iso()
        messages.append({"role": "assistant", "content": content})
        think = self._extract_think(content)
        if think:
            steps.append({"kind": "reasoning", "text": think,
                          "t_start": t0, "t_end": t1, "turn": turn})
        m = _ANSWER_RE.search(content)
        if m:
            answer = m.group(1).strip()
            steps.append({"kind": "answer", "text": answer,
                          "t_start": t0, "t_end": t1, "turn": turn})
            return answer, "budget_exhausted"
        return content or None, "budget_exhausted"
