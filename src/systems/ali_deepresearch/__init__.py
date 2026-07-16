"""ClimbMix port of Alibaba Tongyi DeepResearch — corpus-only ReAct RAG agent.

Public surface:

    from ali_deepresearch import ReactAgent, ClimbMixTools, format_answer
    from ali_deepresearch.prompts import SYSTEM_PROMPT

The agent retrieves ONLY from the ClimbMix corpus (``utils.search`` /
``tools.search_tool`` / ``utils.fetch_doc``); every citation is a ClimbMix docid.
See README.md for the upstream mapping and how to point at a live endpoint.
"""
from .react_agent import ReactAgent, AgentResult, ChatLLM, STOP
from .tools import ClimbMixTools, dispatch
from .answer_format import format_answer
from .prompts import SYSTEM_PROMPT, FORMAT_ANSWER_PROMPT

__all__ = [
    "ReactAgent",
    "AgentResult",
    "ChatLLM",
    "STOP",
    "ClimbMixTools",
    "dispatch",
    "format_answer",
    "SYSTEM_PROMPT",
    "FORMAT_ANSWER_PROMPT",
]
