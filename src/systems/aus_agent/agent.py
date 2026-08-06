"""aus_agent — research-agent RAG system for TREC RAG 2026.

The actual staged-context tool-calling loop (``run_agent``), ``ContextLedger``,
providers, and tool builders/executors are the shared ``agent_harness``
package (re-imported here for this module's own use) — this file now holds
only what is genuinely aus_agent-specific: its own ``prompts/system/*.md``
variant files and the loader that resolves one into a rendered system prompt.
"""
from __future__ import annotations

from pathlib import Path

from agent_harness.agent import (  # noqa: F401  (re-exported for aus_agent/run.py + tests)
    DEFAULT_CONTEXT_TOKEN_BUDGET,
    DEFAULT_ENGINES,
    DEFAULT_MAX_COMMITTED_PER_STEP,
    DEFAULT_SAFETY_MAX_ROUNDS,
    FINISHING_ROUNDS_GRACE,
    PARTIAL_SAVE_MIN_INTERVAL_S,
    make_provider,
    run_agent,
)

# One full system prompt per file under prompts/system/. `default.md` is the
# live baseline; other files are variants selected by their filename stem
# (e.g. --prompt-variant firsthand -> prompts/system/firsthand.md).
SYSTEM_PROMPTS_DIR = Path(__file__).resolve().parent / "prompts" / "system"
DEFAULT_PROMPT_VARIANT = "default"
MAX_COMMITTED_PLACEHOLDER = "__MAX_COMMITTED_DOCS__"


def load_system_prompt(max_committed: int,
                       variant: str = DEFAULT_PROMPT_VARIANT) -> str:
    """Load the system prompt for ``variant`` and render one token.

    Each variant is a full prompt file ``prompts/system/<variant>.md``;
    ``default`` is the live baseline. The rendered ``__MAX_COMMITTED_DOCS__``
    token must appear exactly once.
    """
    path = SYSTEM_PROMPTS_DIR / f"{variant}.md"
    if not path.exists():
        raise RuntimeError(f"unknown prompt variant {variant!r}: "
                           f"{path} not found")
    template = path.read_text(encoding="utf-8")
    count = template.count(MAX_COMMITTED_PLACEHOLDER)
    if count != 1:
        raise RuntimeError(
            f"prompt variant {variant!r} must contain exactly one "
            f"{MAX_COMMITTED_PLACEHOLDER} placeholder; found {count}")
    return template.replace(MAX_COMMITTED_PLACEHOLDER, str(max_committed))


__all__ = [
    "DEFAULT_CONTEXT_TOKEN_BUDGET",
    "DEFAULT_ENGINES",
    "DEFAULT_MAX_COMMITTED_PER_STEP",
    "DEFAULT_PROMPT_VARIANT",
    "DEFAULT_SAFETY_MAX_ROUNDS",
    "FINISHING_ROUNDS_GRACE",
    "MAX_COMMITTED_PLACEHOLDER",
    "PARTIAL_SAVE_MIN_INTERVAL_S",
    "SYSTEM_PROMPTS_DIR",
    "load_system_prompt",
    "make_provider",
    "run_agent",
]
