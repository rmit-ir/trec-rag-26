"""Env-var casting for CLI defaults (``src/utils/env.py``).

``env()`` is the single seam through which every runner's argparse default can be
overridden from the environment / ``.env``. It is three lines of ``isinstance``
dispatch, and each one is a footgun if it moves:

- **``bool`` must be checked before ``int``**, because ``bool`` subclasses
  ``int``. If that order flips, ``env("FLAG", False)`` with ``FLAG=1`` returns the
  integer ``1`` — truthy, so it *looks* fine, until something does
  ``if flag is True`` or serializes the value into a run artifact.
- **Empty / whitespace-only means "unset"**, because a ``.env`` line like
  ``RUN_K=`` is how a variable gets accidentally blanked; falling through to the
  default is what keeps a run working instead of raising on ``int("")``.
- **An uncastable value must exit, not warn.** A typo'd ``RUN_K=ten`` should stop
  the run at startup with the variable name, not silently retrieve the default
  depth and be discovered when the results look wrong.

Tests set variables through ``monkeypatch.setenv`` and use per-test names so
nothing leaks between cases (``env()`` reads ``os.environ`` on every call — there
is no caching to invalidate).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from utils.env import env

VAR = "TREC_RAG_TEST_ENV_VAR"


# ---------------------------------------------------------------------------
# Cast inference from the default's type
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("raw", ["1", "true", "yes", "on",
                                 "TRUE", "Yes", "ON", "True",
                                 " true ", "\tYES\n"])
def test_bool_true_literals(raw: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Case-insensitive and surrounding whitespace is stripped."""
    monkeypatch.setenv(VAR, raw)
    assert env(VAR, False) is True


@pytest.mark.parametrize("raw", ["0", "false", "no", "off",
                                 "FALSE", "No", "OFF", "False", " off "])
def test_bool_false_literals(raw: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """The false set exists so a flag can be turned OFF from a ``.env``.

    Without it, ``FLAG=false`` would either raise or (worse, under a plain
    ``bool(raw)`` cast) evaluate to ``True`` — the non-empty-string trap.
    """
    monkeypatch.setenv(VAR, raw)
    assert env(VAR, True) is False


def test_bool_is_inferred_before_int(monkeypatch: pytest.MonkeyPatch) -> None:
    """THE ordering test: ``bool`` subclasses ``int``, so a naive isinstance
    chain would cast ``"1"`` with ``int`` and hand back ``1``."""
    monkeypatch.setenv(VAR, "1")
    value = env(VAR, False)
    assert value is True          # identity, not just truthiness
    assert type(value) is bool    # `int` would satisfy `== True`, not this


def test_bool_default_true_stays_true_for_a_true_literal(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The default's *value* only picks the cast, never the answer — setting a
    var must never invert a default-``True`` flag (a plausible bug if someone
    "simplified" the bool branch into ``default != bool(raw)``)."""
    monkeypatch.setenv(VAR, "on")
    assert env(VAR, True) is True


@pytest.mark.parametrize("raw,expected", [("10", 10), ("0", 0), ("-3", -3),
                                          (" 42 ", 42)])
def test_int_cast(raw: str, expected: int,
                  monkeypatch: pytest.MonkeyPatch) -> None:
    """The ``k``/depth knobs (``RUN_AUS_AGENT_K``, retrieval depths) go through
    here, and they are handed straight to argparse and then to a client — a
    string ``"10"`` would survive as a slice bound but break arithmetic.

    Axis: ``"0"`` (falsy, must not be mistaken for unset) and a negative value.
    """
    monkeypatch.setenv(VAR, raw)
    value = env(VAR, 7)
    assert value == expected and type(value) is int


@pytest.mark.parametrize("raw,expected", [("0.25", 0.25), ("3", 3.0),
                                          ("-1.5e2", -150.0)])
def test_float_cast(raw: str, expected: float,
                    monkeypatch: pytest.MonkeyPatch) -> None:
    """Timeouts and temperatures are floats. The ``"3"`` case is the interesting
    one: an integral-looking string must still come back as a ``float``, because
    a ``float`` default is a promise about the type, not just the magnitude."""
    monkeypatch.setenv(VAR, raw)
    value = env(VAR, 1.0)
    assert value == pytest.approx(expected) and type(value) is float


def test_path_cast(monkeypatch: pytest.MonkeyPatch) -> None:
    """Index/output locations are ``Path`` defaults, and callers immediately do
    ``value / "sub"`` or ``.exists()`` on them — a raw ``str`` would raise there,
    far from the config line that caused it."""
    monkeypatch.setenv(VAR, "/data/built-indexes/climbmix-bm25")
    value = env(VAR, Path("/tmp/default"))
    assert value == Path("/data/built-indexes/climbmix-bm25")
    assert isinstance(value, Path)


def test_str_default_keeps_the_raw_string_verbatim(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """No stripping for strings — only ``bool`` strips, so a deliberately
    space-padded value (a prompt fragment, a URL) survives intact."""
    monkeypatch.setenv(VAR, "  semantic  ")
    assert env(VAR, "keyword") == "  semantic  "


def test_none_default_falls_through_to_str(monkeypatch: pytest.MonkeyPatch) -> None:
    """``None`` is not bool/int/float/Path, so the inferred cast is ``str`` —
    which is why ``cast=`` exists (next section)."""
    monkeypatch.setenv(VAR, "123")
    value = env(VAR, None)
    assert value == "123" and type(value) is str


# ---------------------------------------------------------------------------
# Precedence: value > env > default
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("default", [False, True, 0, 10, 1.5,
                                     Path("/tmp/x"), "text", None])
def test_unset_returns_the_default_unchanged(default: Any,
                                             monkeypatch: pytest.MonkeyPatch) -> None:
    """No env var == the hardcoded default, byte-for-byte and never cast.

    Axis: one default per inferred cast branch, so an unset var cannot trip a
    cast that was only meant for a present value.
    """
    monkeypatch.delenv(VAR, raising=False)
    got = env(VAR, default)
    assert got is default or got == default


@pytest.mark.parametrize("raw", ["", " ", "\t", "\n", "   \t\n "])
@pytest.mark.parametrize("default", [10, False, "text", Path("/tmp/x")])
def test_empty_or_whitespace_only_value_is_treated_as_unset(
        raw: str, default: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """``RUN_K=`` in a ``.env`` must not crash the run on ``int("")``."""
    monkeypatch.setenv(VAR, raw)
    assert env(VAR, default) == default


def test_env_overrides_the_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """The middle rung of the documented ``flag > env > default`` ladder — the
    whole reason the helper exists, so a sweep can re-run a system with a
    different depth by exporting one variable."""
    monkeypatch.setenv(VAR, "25")
    assert env(VAR, 10) == 25


def test_a_second_var_name_is_independent(monkeypatch: pytest.MonkeyPatch) -> None:
    """No caching: two names, and re-reading after a change sees the change."""
    monkeypatch.setenv(VAR, "1")
    monkeypatch.setenv(VAR + "_B", "2")
    assert (env(VAR, 0), env(VAR + "_B", 0)) == (1, 2)
    monkeypatch.setenv(VAR, "9")
    assert env(VAR, 0) == 9


# ---------------------------------------------------------------------------
# Explicit cast=
# ---------------------------------------------------------------------------
def test_explicit_cast_overrides_inference(monkeypatch: pytest.MonkeyPatch) -> None:
    """A ``str`` default with an ``int`` cast: the cast wins, not the default's
    type."""
    monkeypatch.setenv(VAR, "42")
    value = env(VAR, "42", cast=int)
    assert value == 42 and type(value) is int


def test_explicit_cast_with_a_none_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """The documented reason ``cast=`` exists — ``None`` carries no type."""
    monkeypatch.setenv(VAR, "/data/outputs")
    assert env(VAR, None, cast=Path) == Path("/data/outputs")


def test_explicit_cast_is_not_applied_when_unset(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The default is returned as-is: ``cast`` never touches it, so a default of
    a different type than the cast produces is intentional and preserved."""
    monkeypatch.delenv(VAR, raising=False)
    assert env(VAR, None, cast=int) is None
    assert env(VAR, "unset", cast=int) == "unset"


def test_explicit_cast_can_be_an_arbitrary_callable(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """``cast`` is any ``str -> Any``, not a whitelist of the four inferred
    types. This is how a list-valued knob like the enabled-engine set is read
    from one variable, so it must keep working."""
    monkeypatch.setenv(VAR, "semantic,keyword,ssr")
    assert env(VAR, None, cast=lambda s: s.split(",")) == ["semantic", "keyword",
                                                           "ssr"]


def test_explicit_cast_receives_the_unstripped_raw_value(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Only the *whitespace-only* check strips; the value handed to ``cast`` is
    verbatim. A custom cast that splits on a delimiter therefore has to strip its
    own tokens — pinned here so nobody assumes ``env()`` did it."""
    monkeypatch.setenv(VAR, " padded ")
    assert env(VAR, None, cast=repr) == repr(" padded ")


# ---------------------------------------------------------------------------
# Failure mode
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("raw,default", [
    ("ten", 10),            # int
    ("1.2.3", 1.0),         # float
    ("maybe", False),       # bool literal not in the true/false sets
    ("2", True),            # ...including a plausible-looking int
])
def test_uncastable_value_exits_naming_the_variable(
        raw: str, default: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """``SystemExit`` (not a traceback) so a runner dies with a one-line
    actionable message; the message must carry the var name AND the bad value,
    because the user's next move is editing that ``.env`` line."""
    monkeypatch.setenv(VAR, raw)
    with pytest.raises(SystemExit) as excinfo:
        env(VAR, default)
    message = str(excinfo.value)
    assert VAR in message
    assert repr(raw) in message


def test_uncastable_value_with_an_explicit_cast_also_exits(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The ``try/except`` wraps the explicit-``cast`` path too, so the friendly
    named-variable exit is not a privilege of the inferred casts only."""
    monkeypatch.setenv(VAR, "nope")
    with pytest.raises(SystemExit, match=VAR):
        env(VAR, None, cast=int)


def test_a_cast_raising_something_other_than_type_or_value_propagates(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """ACTUAL BEHAVIOUR: only ``TypeError``/``ValueError`` are converted to
    ``SystemExit``. A custom cast raising anything else escapes as-is — fine, but
    it means a custom cast should raise ``ValueError`` to get the nice message."""
    monkeypatch.setenv(VAR, "x")

    def _bad(_: str) -> Any:
        raise KeyError("boom")

    with pytest.raises(KeyError):
        env(VAR, None, cast=_bad)
