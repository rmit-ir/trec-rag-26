"""One text completion, against whichever route the configured model supports.

The judging scripts were written against a hosted endpoint that served
``/v1/chat/completions``. The Bedrock OpenAI-compatible gateway
(``https://bedrock-mantle.<region>.api.aws/openai/v1``) serves ``/v1/responses``
for the same model and rejects chat completions outright::

    The model 'openai.gpt-5.6-luna' does not support the '/v1/chat/completions' API

So the route is a property of the endpoint, not of the caller, and hardcoding
either one strands the scripts on the other. This probes once per
(base_url, model), remembers the answer, and every later call goes straight
there. Pointing ``OPENAI_BASE_URL`` back at the old endpoint keeps working, which
matters because the published test-119 numbers came from it.

Two failure modes that are silent if you do not look for them, and are handled:

- **Model naming differs per endpoint.** The gateway wants ``openai.gpt-5.6-luna``
  and 404s on the bare ``gpt-5.6-luna`` the scripts defaulted to. ``default_model``
  reads ``OPENAI_MODEL_ID`` so the id lives with the endpoint that needs it.
- **A reasoning model can spend its whole output budget thinking** and return
  ``status="incomplete"`` with empty text. That parses as an unreadable verdict
  and quietly drops the battle, which looks like a judge that could not decide
  rather than a cap that was too low. ``complete`` raises on it instead, so the
  caller records a failure it can see and retry.
"""
from __future__ import annotations

import os
import re
import threading

# (base_url, model) -> "responses" | "chat"
_ROUTE: dict[tuple[str, str], str] = {}
_LOCK = threading.Lock()

# Generous by default: it is a ceiling, not an allocation, so a high value is
# free on a turn that emits a two-token verdict, and it is the only thing
# standing between a reasoning-heavy judgment and a truncated empty reply.
DEFAULT_MAX_OUTPUT_TOKENS = 8000


class Incomplete(RuntimeError):
    """The model hit its output cap before emitting text."""


def load_env(root: "Path | None" = None) -> None:
    """Populate os.environ from the repo ``.env`` (never overriding a real var).

    Must run BEFORE any argparse default calls ``default_model``. An argparse
    ``default=`` is evaluated when the parser is built, so a script that loaded
    the .env inside ``main()`` resolved the model name from an environment that
    did not have it yet — and silently judged against a model id that 404s.
    """
    from pathlib import Path as _Path
    env = (root or _Path(__file__).resolve().parents[3]) / ".env"
    if not env.exists():
        return
    for raw in env.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(),
                                  value.strip().strip('"').strip("'"))


def default_model(fallback: str = "gpt-5.6-luna") -> str:
    """The GENERATOR model id, from ``OPENAI_MODEL_ID``.

    Calls ``load_env`` first so the answer does not depend on whether the
    caller happened to load the .env yet.
    """
    load_env()
    return os.environ.get("OPENAI_MODEL_ID") or fallback


def default_judge(fallback: str = "openai.gpt-5.6-sol") -> str:
    """The JUDGE model id -- deliberately NOT ``OPENAI_MODEL_ID``.

    The generator is an experimental variable; the judge is the instrument, and
    an instrument that changes with the thing it measures produces numbers that
    cannot be compared across arms. Reading both from one env var meant that
    switching the agent to ``sol`` would have silently switched the judge too,
    invalidating every previously scored arm without a single error message.

    Pinned to **sol** on measured grounds, not on price: grading the same 30
    baseline answers three times, sol's per-topic spread is 0.0437 against
    luna's 0.0720 -- 39% quieter, which drops the smallest detectable effect
    from ~0.030 to ~0.018. Sol also scores luna-written answers *higher* than
    luna does, so the self-preference that dominated the arena is not visible
    in rubric grading; it is an entailment check against fixed criteria rather
    than a preference vote.

    ``RUBRIC_JUDGE_MODEL`` overrides it -- use terra for the luna-vs-sol
    generator comparison, where sol grading sol's own output is a live conflict.
    """
    load_env()
    return os.environ.get("RUBRIC_JUDGE_MODEL") or fallback


# Provider prefixes the same model is served under on different endpoints.
_PREFIXES = ("openai.", "us.openai.", "au.openai.", "eu.openai.",
             "anthropic.", "us.anthropic.", "au.anthropic.", "eu.anthropic.")


def canonical(model: str) -> str:
    """The judge's identity, with the endpoint's routing prefix removed.

    ``gpt-5.6-luna`` on the old hosted endpoint and ``openai.gpt-5.6-luna`` on
    the Bedrock gateway are the same model reading the same prompt, so a
    judgment cached under one name is valid under the other. Without this, a
    change of endpoint — or of region — silently invalidates every cached
    judgment: 19,623 of them at the time of writing, and the adoption shortcut
    that makes the anchor rows free. The cost of the mistake is money and hours,
    and it is invisible, because re-judging looks exactly like working.

    Used for cache directories and for the ``judge`` column, so rows and
    judgments stay keyed to the model rather than to how it was reached.
    """
    for prefix in sorted(_PREFIXES, key=len, reverse=True):
        if model.startswith(prefix):
            return model[len(prefix):]
    return model


def client(timeout: float = 300.0, max_retries: int = 4):
    from openai import OpenAI
    return OpenAI(base_url=os.environ["OPENAI_BASE_URL"],
                  api_key=os.environ["OPENAI_API_KEY"],
                  timeout=timeout, max_retries=max_retries)


# Process-wide token ledger, so every script can report what it spent without
# each one re-implementing the accounting. Judged-from-cache calls never reach
# here, which is the point: the ledger counts tokens actually bought.
USAGE: dict[str, int] = {"calls": 0, "input": 0, "input_cached": 0,
                         "output": 0, "reasoning": 0}


def _record(input_tokens: int, output_tokens: int, cached: int = 0,
            reasoning: int = 0) -> None:
    with _LOCK:
        USAGE["calls"] += 1
        USAGE["input"] += int(input_tokens or 0)
        USAGE["input_cached"] += int(cached or 0)
        USAGE["output"] += int(output_tokens or 0)
        USAGE["reasoning"] += int(reasoning or 0)


def usage_report(model: str) -> str:
    """One line of what this process spent, priced when a rate table exists.

    Prices come from ``ragrun.pricing``'s committed AWS rate tables and from
    nowhere else. When the model has no table the line says so and reports
    tokens only — an invented $/token figure would look authoritative and be
    wrong, which is worse than an honest blank.
    """
    u = dict(USAGE)
    if not u["calls"]:
        return "  cost: no API calls (everything served from cache)"
    line = (f"  tokens: {u['calls']} calls, in {u['input']:,} "
            f"(cached {u['input_cached']:,}), out {u['output']:,}"
            + (f", reasoning {u['reasoning']:,}" if u["reasoning"] else ""))
    try:
        import sys
        from pathlib import Path as _P
        sys.path.insert(0, str(_P(__file__).resolve().parents[3] / "src"))
        from ragrun.pricing import call_cost, load_rates
        region = _region_from_base_url(os.environ.get("OPENAI_BASE_URL", ""))
        rates = load_rates(canonical_for_pricing(model), region)
        priced = call_cost({"input_uncached": u["input"] - u["input_cached"],
                            "output": u["output"], "cache_read": u["input_cached"],
                            "cache_write": 0}, rates)
        return line + f"\n  cost: ${priced['usd']:.4f} USD ({model} @ {region})"
    except Exception as exc:  # noqa: BLE001 — unpriced is a normal state
        return (line + f"\n  cost: UNPRICED — no committed rate table for "
                f"{model!r} ({type(exc).__name__}). Token counts above are exact; "
                f"add a table under src/ragrun/prices/ to denominate them.")


def usd_spent(model: str) -> float | None:
    """This process's judge spend in USD, or None when the model has no rates."""
    u = dict(USAGE)
    if not u["calls"]:
        return 0.0
    try:
        import sys
        from pathlib import Path as _P
        sys.path.insert(0, str(_P(__file__).resolve().parents[3] / "src"))
        from ragrun.pricing import call_cost, load_rates
        rates = load_rates(canonical_for_pricing(model),
                           _region_from_base_url(os.environ.get("OPENAI_BASE_URL", "")))
        priced = call_cost({"input_uncached": u["input"] - u["input_cached"],
                            "output": u["output"], "cache_read": u["input_cached"],
                            "cache_write": 0}, rates)
        return round(priced["usd"], 6)
    except Exception:  # noqa: BLE001 — unpriced is a normal state
        return None


def canonical_for_pricing(model: str) -> str:
    """Bedrock prices by the full model id, prefix and all — unlike the cache key."""
    return model


def _region_from_base_url(url: str) -> str:
    match = re.search(r"\.([a-z]{2}-[a-z]+-\d)\.", url or "")
    return match.group(1) if match else "unknown"


def _responses_text(api, model: str, prompt: str, max_output_tokens: int) -> str:
    response = api.responses.create(model=model, input=prompt,
                                    max_output_tokens=max_output_tokens)
    text = "".join(
        part.text
        for item in response.output
        for part in (getattr(item, "content", None) or [])
        if getattr(part, "type", "") == "output_text")
    usage = getattr(response, "usage", None)
    if usage is not None:
        details = getattr(usage, "input_tokens_details", None)
        out_details = getattr(usage, "output_tokens_details", None)
        _record(getattr(usage, "input_tokens", 0),
                getattr(usage, "output_tokens", 0),
                getattr(details, "cached_tokens", 0) or 0,
                getattr(out_details, "reasoning_tokens", 0) or 0)
    if response.status == "incomplete" and not text.strip():
        reason = getattr(getattr(response, "incomplete_details", None), "reason", "?")
        raise Incomplete(f"status=incomplete reason={reason}; raise "
                         f"max_output_tokens above {max_output_tokens}")
    return text


def _chat_text(api, model: str, prompt: str, max_output_tokens: int) -> str:
    response = api.chat.completions.create(
        model=model, messages=[{"role": "user", "content": prompt}])
    usage = getattr(response, "usage", None)
    if usage is not None:
        details = getattr(usage, "prompt_tokens_details", None)
        _record(getattr(usage, "prompt_tokens", 0),
                getattr(usage, "completion_tokens", 0),
                getattr(details, "cached_tokens", 0) or 0)
    choice = response.choices[0]
    if choice.finish_reason == "length" and not (choice.message.content or "").strip():
        raise Incomplete("finish_reason=length with empty content")
    return choice.message.content or ""


_ROUTES = {"responses": _responses_text, "chat": _chat_text}


def complete(api, model: str, prompt: str,
             max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS) -> str:
    """Send ``prompt``, return the reply text, whichever route the model serves.

    A route mismatch surfaces as a 400 naming the unsupported API rather than as
    a transport error, so it is safe to distinguish from a real failure: only
    that message triggers the fallback, and anything else propagates.
    """
    key = (str(getattr(api, "base_url", "")), model)
    known = _ROUTE.get(key)
    order = ([known] if known else []) + [r for r in ("responses", "chat")
                                          if r != known]
    last: Exception | None = None
    for route in order:
        try:
            text = _ROUTES[route](api, model, prompt, max_output_tokens)
        except Incomplete:
            raise
        except Exception as exc:  # noqa: BLE001 — inspect, then re-raise or fall through
            message = str(exc)
            if "does not support" not in message and "supported on this route" not in message:
                raise
            last = exc
            continue
        if known != route:
            with _LOCK:
                _ROUTE[key] = route
        return text
    raise RuntimeError(f"model {model!r} serves neither /responses nor "
                       f"/chat/completions on this endpoint: {last}")
