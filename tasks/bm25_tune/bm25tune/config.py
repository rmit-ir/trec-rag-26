"""Environment-variable configuration for the tuning harness.

**No side effects at import.** Reading this module must not touch the
filesystem, resolve the index, or validate credentials — `cli.py` imports it
unconditionally, and so do the hermetic tests. Every check that can fail is a
method you call explicitly (`Config.require_index_dir()`,
`Config.ensure_dirs()`), so a subcommand that never searches never pays for the
index being on another user's (possibly unmounted) home.

Variables read (defaults per PLAN §4.1):

| var | default | used by |
|---|---|---|
| `BM25_TUNE_INDEX_DIR` | *(none — required for search)* | `searcher`, `smoke` |
| `BM25_TUNE_DATA_DIR` | `<repo>/data/bm25-tune` | everything |
| `BM25_TUNE_JUDGE_MODEL` | `openai.gpt-oss-20b-1:0` | `judge` |
| `BM25_TUNE_JUDGE_REGION` | `ap-southeast-2` | `judge` |
| `BM25_TUNE_JUDGE_CONCURRENCY` | `16` | `judge-pool` |
| `BM25_TUNE_BUDGET_USD` | *(none — REQUIRED by every command that spends or reports spend)* | `pricing` |
| `BM25_TUNE_PRICING_TIER` | `standard` | `pricing` |
| `BM25_TUNE_GRID_K1` | `0.5,0.7,0.9,1.2,1.6` | `search-sweep` |
| `BM25_TUNE_GRID_B` | `0.2,0.35,0.5,0.65,0.8` | `search-sweep` |
| `BM25_TUNE_BASELINE` | `0.9:0.4` | `search-sweep`, `smoke`, `stats` |
| `BM25_TUNE_EXPECTED_NUM_DOCS` | `921892634` (`none` disables) | `searcher` |
| `BM25_TUNE_QUERIES_FULL` | `keyword-1063.jsonl` | every stage |
| `BM25_TUNE_QUERIES_SUBSAMPLE` | `subsample-250.jsonl` | `search-sweep`, `stats` |
| `BM25_TUNE_INPUT_FILE` | `inputs/trec-rag26-test119-search-labeled.jsonl` | `verify-inputs`, `extract-queries`, `calibrate` |

**The last six exist so the harness runs on an index and query set it has never
seen** (the `bm25-parameter-tuning` skill). Their defaults are the values the
ClimbMix experiment was run with, so leaving them unset reproduces it exactly;
overriding any of them is a deliberate act by an operator who has a different
corpus. `BM25_TUNE_EXPECTED_NUM_DOCS` is the one to be careful with — see
`Config.expected_num_docs`.

The budget is **cumulative across the whole experiment**, not per-run: its
durable state lives in `costs/totals.json` under the data dir, deliberately
outside `runs/` (PLAN §4.2).

`BM25_TUNE_BUDGET_USD` is the one variable with **no default**. It must be
exported by whoever launches a command that can spend money, so the ceiling is
always a live decision by a human rather than a constant a reader assumes is
still current. `Config.require_budget_usd()` raises `ConfigError` naming the
approved figure (`APPROVED_BUDGET_USD`, currently US$50); commands that cannot
spend (`verify-inputs`, `extract`, `score`, `stats`) never call it and so keep
working with the variable unset.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# Repo root = three levels up from this file: bm25tune/ -> bm25_tune/ -> tasks/ -> repo.
REPO_ROOT = Path(__file__).resolve().parents[3]

DEFAULT_DATA_DIR = REPO_ROOT / "data" / "bm25-tune"
DEFAULT_JUDGE_MODEL = "openai.gpt-oss-20b-1:0"
DEFAULT_JUDGE_REGION = "ap-southeast-2"
DEFAULT_JUDGE_CONCURRENCY = 16
#: The cap the user approved on 2026-07-31 (down from $200), quoted in the
#: "you must export this" message and nowhere else. It is **NOT a default**:
#: `budget_usd` has none, because a spend ceiling silently inherited from a
#: constant is the one setting an operator must never be able to get wrong by
#: omission (PLAN §0). The typical projection is $7.75 and the worst case $13.53
#: (PLAN §6.2b), so $50 is a runaway-cost circuit breaker with ~4-6x headroom,
#: not a scope limiter — a refusal at this figure is prima facie a bug.
APPROVED_BUDGET_USD = 50.0
DEFAULT_PRICING_TIER = "standard"
PRICING_TIERS = ("standard", "batch", "flex", "priority")

#: The labeled search log every stage reads from (PLAN §2.1). Relative to the
#: data dir so an alternate `BM25_TUNE_DATA_DIR` (a test tmp dir) works.
INPUT_BASENAME = "trec-rag26-test119-search-labeled.jsonl"
SHA256SUMS_BASENAME = "SHA256SUMS"

#: Query-artifact basenames PLAN §4.2 fixes. Overridable because a different
#: corpus has a different number of queries and `keyword-1063.jsonl` would then
#: be a lie in every log line; `cli.py` re-exports these for its help text.
DEFAULT_QUERIES_FULL_BASENAME = "keyword-1063.jsonl"
DEFAULT_QUERIES_SUBSAMPLE_BASENAME = "subsample-250.jsonl"

#: PLAN §6.1's coarse grid and the cell every candidate is measured against.
#: Strings, not tuples, because they are parsed by `searcher.parse_configs` /
#: `_env_floats` — which is also what the env vars accept.
DEFAULT_GRID_K1 = "0.5,0.7,0.9,1.2,1.6"
DEFAULT_GRID_B = "0.2,0.35,0.5,0.65,0.8"
DEFAULT_BASELINE = "0.9:0.4"

#: **[measured]** chunk count of `climbmix-bm25-chunked`, asserted when the index
#: opens (PLAN R7). See `Config.expected_num_docs` for why this is a guard rather
#: than a constant to be edited.
DEFAULT_EXPECTED_NUM_DOCS = 921_892_634


class ConfigError(RuntimeError):
    """A required env var is missing, or points somewhere unusable.

    Separate from `RuntimeError` so `cli.py` can map it to a clean one-line
    message + exit 1 instead of a traceback the operator has to read past.
    """


def _env_str(name: str, default: str) -> str:
    value = os.environ.get(name)
    return default if value is None or not value.strip() else value.strip()


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw.strip())
    except ValueError as exc:
        raise ConfigError(f"{name}={raw!r} is not an integer") from exc


def _env_float_opt(name: str) -> float | None:
    """Parse a float env var, or `None` when it is unset/blank.

    No default parameter on purpose: the only float we read is the spend cap, and
    a defaultable reader is exactly the shape that would let one back in.
    """
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return None
    try:
        return float(raw.strip())
    except ValueError as exc:
        raise ConfigError(f"{name}={raw!r} is not a number") from exc


def parse_grid_axis(name: str, default: str) -> tuple[float, ...]:
    """Parse a `0.5,0.7,0.9` grid axis, de-duplicated with order preserved.

    Order matters: `stage_a_grid()` is k1-major and the pool file records the
    `first_seen_config`, so a reordered axis silently changes an artifact that is
    supposed to be reproducible. Duplicates are dropped rather than refused
    because `0.5,0.5` would otherwise re-search a cell and overwrite its own run
    file — the same reasoning as `searcher.parse_configs`.
    """
    raw = _env_str(name, default)
    values: list[float] = []
    for item in raw.replace(",", " ").split():
        try:
            value = float(item)
        except ValueError as exc:
            raise ConfigError(
                f"{name}={raw!r}: {item!r} is not a number (expected a "
                "comma- or space-separated list, e.g. 0.5,0.7,0.9)") from exc
        if value not in values:
            values.append(value)
    if not values:
        raise ConfigError(f"{name}={raw!r} lists no values")
    return tuple(values)


def parse_cell(name: str, default: str) -> tuple[float, float]:
    """Parse a single `k1:b` cell (the baseline)."""
    raw = _env_str(name, default)
    parts = raw.replace(":", " ").replace("/", " ").replace(",", " ").split()
    if len(parts) != 2:
        raise ConfigError(
            f"{name}={raw!r} is not a single k1:b cell (e.g. 0.9:0.4)")
    try:
        return (float(parts[0]), float(parts[1]))
    except ValueError as exc:
        raise ConfigError(f"{name}={raw!r}: k1 and b must be numbers") from exc


def _env_num_docs(name: str, default: int) -> int | None:
    """Parse the index-identity guard; `none`/`0`/`off` disables it.

    Disabling is spelled out as a word rather than left to an empty string so it
    is visible in the `[LOAD]` line and in shell history what the operator turned
    off — this is the one override that removes a safety check rather than
    retargeting one.
    """
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    text = raw.strip().lower()
    if text in ("none", "off", "0", "any", "disabled"):
        return None
    try:
        value = int(text.replace("_", "").replace(",", ""))
    except ValueError as exc:
        raise ConfigError(
            f"{name}={raw!r} is not an integer (or `none` to disable the "
            "index-identity check)") from exc
    if value <= 0:
        raise ConfigError(
            f"{name}={raw!r} must be positive, or `none` to disable the check")
    return value


@dataclass(frozen=True)
class Config:
    """Resolved settings for one CLI invocation.

    Built by `Config.from_env()`. `index_dir` is `None` when unset rather than a
    placeholder path, so the failure surfaces at `require_index_dir()` with an
    actionable message rather than as a pyserini stack trace.
    """

    data_dir: Path
    index_dir: Path | None
    judge_model: str
    judge_region: str
    judge_concurrency: int
    #: `None` when `BM25_TUNE_BUDGET_USD` is unset. Deliberately not defaulted —
    #: read it through `require_budget_usd()`, which refuses rather than guesses.
    budget_usd: float | None
    pricing_tier: str
    #: The `k1`/`b` axes `stage_a_grid()` crosses, and the cell every candidate
    #: is compared against (which is appended to the grid if the axes miss it).
    grid_k1: tuple[float, ...] = (0.5, 0.7, 0.9, 1.2, 1.6)
    grid_b: tuple[float, ...] = (0.2, 0.35, 0.5, 0.65, 0.8)
    baseline: tuple[float, float] = (0.9, 0.4)
    #: `num_docs` the index must report on open, or `None` to accept any.
    #:
    #: Keep it set. It is what makes a cached judgment safe to reuse: the cache
    #: key is `prompt::topic::chunk_id`, so pointing the harness at a re-chunked
    #: corpus where the same chunk id names different text would silently score
    #: new passages against old grades. `None` is correct only for a first run on
    #: a new index whose count is not yet known — and the count it then logs is
    #: the value to set for every run after (PLAN R7).
    expected_num_docs: int | None = DEFAULT_EXPECTED_NUM_DOCS
    #: Basenames of the two persisted query artifacts, under `queries_dir`.
    queries_full_basename: str = DEFAULT_QUERIES_FULL_BASENAME
    queries_subsample_basename: str = DEFAULT_QUERIES_SUBSAMPLE_BASENAME
    #: The labeled search log, when one exists. `None` once
    #: `BM25_TUNE_QUERIES_FULL` is supplied directly (the bring-your-own-queries
    #: path): the log is an *input adapter* for one corpus, not a requirement of
    #: the method, so commands that need it must say so via `require_input_file`.
    input_file_override: Path | None = None
    #: Fields whose value came from an env var rather than the default. Logged
    #: in the `[LOAD]` line so a surprising run is explainable from the log.
    overridden: tuple[str, ...] = field(default=())

    # -- construction -------------------------------------------------------
    @classmethod
    def from_env(cls) -> "Config":
        """Read every `BM25_TUNE_*` var, applying PLAN §4.1 defaults."""
        raw_index = os.environ.get("BM25_TUNE_INDEX_DIR", "").strip()
        tier = _env_str("BM25_TUNE_PRICING_TIER", DEFAULT_PRICING_TIER).lower()
        if tier not in PRICING_TIERS:
            raise ConfigError(
                f"BM25_TUNE_PRICING_TIER={tier!r} is not one of "
                f"{'|'.join(PRICING_TIERS)}")
        overridden = tuple(
            name for name in (
                "BM25_TUNE_INDEX_DIR", "BM25_TUNE_DATA_DIR",
                "BM25_TUNE_JUDGE_MODEL", "BM25_TUNE_JUDGE_REGION",
                "BM25_TUNE_JUDGE_CONCURRENCY", "BM25_TUNE_BUDGET_USD",
                "BM25_TUNE_PRICING_TIER", "BM25_TUNE_GRID_K1",
                "BM25_TUNE_GRID_B", "BM25_TUNE_BASELINE",
                "BM25_TUNE_EXPECTED_NUM_DOCS", "BM25_TUNE_QUERIES_FULL",
                "BM25_TUNE_QUERIES_SUBSAMPLE", "BM25_TUNE_INPUT_FILE")
            if os.environ.get(name, "").strip())
        raw_input_file = os.environ.get("BM25_TUNE_INPUT_FILE", "").strip()
        return cls(
            data_dir=Path(_env_str("BM25_TUNE_DATA_DIR",
                                   str(DEFAULT_DATA_DIR))).expanduser(),
            index_dir=Path(raw_index).expanduser() if raw_index else None,
            judge_model=_env_str("BM25_TUNE_JUDGE_MODEL", DEFAULT_JUDGE_MODEL),
            judge_region=_env_str("BM25_TUNE_JUDGE_REGION",
                                  DEFAULT_JUDGE_REGION),
            judge_concurrency=_env_int("BM25_TUNE_JUDGE_CONCURRENCY",
                                       DEFAULT_JUDGE_CONCURRENCY),
            budget_usd=_env_float_opt("BM25_TUNE_BUDGET_USD"),
            pricing_tier=tier,
            grid_k1=parse_grid_axis("BM25_TUNE_GRID_K1", DEFAULT_GRID_K1),
            grid_b=parse_grid_axis("BM25_TUNE_GRID_B", DEFAULT_GRID_B),
            baseline=parse_cell("BM25_TUNE_BASELINE", DEFAULT_BASELINE),
            expected_num_docs=_env_num_docs("BM25_TUNE_EXPECTED_NUM_DOCS",
                                            DEFAULT_EXPECTED_NUM_DOCS),
            queries_full_basename=_env_str(
                "BM25_TUNE_QUERIES_FULL", DEFAULT_QUERIES_FULL_BASENAME),
            queries_subsample_basename=_env_str(
                "BM25_TUNE_QUERIES_SUBSAMPLE",
                DEFAULT_QUERIES_SUBSAMPLE_BASENAME),
            input_file_override=(Path(raw_input_file).expanduser()
                                 if raw_input_file else None),
            overridden=overridden,
        )

    # -- derived paths (pure; no mkdir) -------------------------------------
    @property
    def inputs_dir(self) -> Path:
        return self.data_dir / "inputs"

    @property
    def input_file(self) -> Path:
        """The labeled search log, honouring `BM25_TUNE_INPUT_FILE`.

        A bare filename resolves under `inputs_dir` so the common override is
        just a name; anything with a separator is taken as given (absolute or
        relative to the cwd), because another corpus' log will not live under
        this experiment's data dir.
        """
        override = self.input_file_override
        if override is None:
            return self.inputs_dir / INPUT_BASENAME
        if len(override.parts) == 1:
            return self.inputs_dir / override
        return override

    @property
    def queries_full_file(self) -> Path:
        return self.queries_dir / self.queries_full_basename

    @property
    def queries_subsample_file(self) -> Path:
        return self.queries_dir / self.queries_subsample_basename

    @property
    def sha256sums_file(self) -> Path:
        return self.inputs_dir / SHA256SUMS_BASENAME

    @property
    def queries_dir(self) -> Path:
        return self.data_dir / "queries"

    @property
    def calibration_dir(self) -> Path:
        return self.data_dir / "calibration"

    @property
    def judgments_dir(self) -> Path:
        return self.data_dir / "judgments"

    @property
    def log_dir(self) -> Path:
        return self.judgments_dir / "log"

    @property
    def cache_dir(self) -> Path:
        return self.judgments_dir / "cache"

    @property
    def costs_dir(self) -> Path:
        return self.data_dir / "costs"

    @property
    def runs_dir(self) -> Path:
        return self.data_dir / "runs"

    def run_dir(self, run_id: str) -> Path:
        return self.runs_dir / run_id

    @property
    def prices_dir(self) -> Path:
        """Committed rate tables — code, not data, so it lives in the package."""
        return Path(__file__).resolve().parent / "prices"

    # -- explicit validation ------------------------------------------------
    def require_index_dir(self) -> Path:
        """Return the index dir, or raise `ConfigError` naming the fix.

        Called only by search subcommands. The index lives read-only under
        another user's home (PLAN §1/R7), so "unset" and "unreadable" are both
        realistic and get distinct messages.
        """
        if self.index_dir is None:
            raise ConfigError(
                "BM25_TUNE_INDEX_DIR is not set. Export it, e.g.\n"
                "  export BM25_TUNE_INDEX_DIR=/home/eh6/E128356/projects/"
                "trec-rag-26/data/built-indexes/climbmix-bm25-chunked")
        if not self.index_dir.is_dir():
            raise ConfigError(
                f"BM25_TUNE_INDEX_DIR={self.index_dir} is not a directory "
                "(the index lives read-only under another user's home — check "
                "the mount and your read permission)")
        return self.index_dir

    def require_input_file(self) -> Path:
        """Return the labeled search log, or raise naming the two ways forward.

        Only `verify-inputs`, `extract-queries` and `calibrate` need it: it is an
        *adapter* for one corpus' aus_agent search log, not part of the tuning
        method. On any other index the operator writes `queries/<full>.jsonl`
        directly (`{topic_id, topic, query, qkey, k_orig}`), and then no stage
        reads a log at all — so this must fail with that instruction rather than
        with a bare "file not found" that reads like a missing download.
        """
        path = self.input_file
        if path.is_file():
            return path
        raise ConfigError(
            f"labeled search log not found: {path}\n"
            "Either point BM25_TUNE_INPUT_FILE at one, or skip this command "
            "entirely: `extract-queries` only exists to derive "
            f"queries/{self.queries_full_basename} from such a log. If you have "
            "queries already, write that file yourself — one JSON object per "
            'line, {"topic_id", "topic", "query", "qkey", "k_orig"}, with '
            "qkey = \"<topic_id>::<sha1(query)[:12]>\" — and run search-sweep "
            "directly (`python -m bm25tune make-queries` does it for you).")

    def require_budget_usd(self) -> float:
        """Return the spend ceiling, or raise `ConfigError` naming the export.

        Called by every subcommand that can spend money or report against the
        cap, and by nothing else — `verify-inputs`, `extract`, `score` and
        `stats` run fine with the variable unset.

        The cap has no default because it is the user's decision and the whole
        point of the three-layer guard (PLAN §5.7) is that it reflects a *live*
        one. A default would let an unattended multi-hour job run against a
        figure nobody re-confirmed — and the failure mode of a stale ceiling is
        money, which is the one resource the harness cannot roll back. Zero and
        negatives are refused here too, rather than at `BudgetGuard`, so the
        message names the variable to fix instead of a constructor argument.
        """
        if self.budget_usd is None:
            raise ConfigError(
                "BM25_TUNE_BUDGET_USD is not set — the spend ceiling has no "
                "default on purpose (PLAN §0/§5.7): it must be a live decision "
                f"by whoever launches the run. The approved figure is "
                f"${APPROVED_BUDGET_USD:.2f}, so unless you have agreed "
                "otherwise:\n"
                f"  export BM25_TUNE_BUDGET_USD={APPROVED_BUDGET_USD}")
        if self.budget_usd <= 0:
            raise ConfigError(
                f"BM25_TUNE_BUDGET_USD={self.budget_usd!r} must be positive. A "
                "zero or negative ceiling trips on the first call and reads in "
                "the log exactly like a runaway, sending you hunting a bug in "
                "the judge that isn't there.")
        return self.budget_usd

    def ensure_dirs(self, *paths: Path) -> None:
        """`mkdir -p` the given artifact dirs. The only filesystem mutation here."""
        for path in paths:
            path.mkdir(parents=True, exist_ok=True)

    def describe(self) -> str:
        """One-line summary for the `[LOAD]` log line."""
        index = self.index_dir if self.index_dir is not None else "<unset>"
        # An unset cap prints `<unset>` rather than the approved figure: this
        # line is the operator's evidence of what the run is actually bounded by,
        # and printing a number nobody exported would be a lie in the log.
        budget = ("<unset>" if self.budget_usd is None
                  else f"${self.budget_usd:.2f}")
        # num_docs=any is spelled out rather than omitted: a run with the index
        # identity check off must be identifiable as such from its log alone,
        # since that is the run whose cached judgments could belong to another
        # corpus.
        num_docs = ("any" if self.expected_num_docs is None
                    else str(self.expected_num_docs))
        return (f"data_dir={self.data_dir} index_dir={index} "
                f"judge_model={self.judge_model} region={self.judge_region} "
                f"concurrency={self.judge_concurrency} "
                f"budget={budget} tier={self.pricing_tier} "
                f"grid_k1={','.join(format(v, 'g') for v in self.grid_k1)} "
                f"grid_b={','.join(format(v, 'g') for v in self.grid_b)} "
                f"baseline={self.baseline[0]:g}:{self.baseline[1]:g} "
                f"expected_num_docs={num_docs} "
                f"queries={self.queries_full_basename}/"
                f"{self.queries_subsample_basename} "
                f"overridden={','.join(self.overridden) or 'none'}")


# The dataclass defaults above are literals (so `Config()` needs no environment)
# while the documented defaults are the `DEFAULT_*` strings the env parsers use.
# Two spellings of one fact drift silently, and the failure mode is a grid that
# differs between an explicit `Config()` and a `Config.from_env()` — so pin them
# together at import, where a mismatch is a hard, immediate error.
_DEFAULTS = Config(data_dir=DEFAULT_DATA_DIR, index_dir=None,
                   judge_model=DEFAULT_JUDGE_MODEL,
                   judge_region=DEFAULT_JUDGE_REGION,
                   judge_concurrency=DEFAULT_JUDGE_CONCURRENCY,
                   budget_usd=None, pricing_tier=DEFAULT_PRICING_TIER)
assert _DEFAULTS.grid_k1 == parse_grid_axis("", DEFAULT_GRID_K1), (
    "Config.grid_k1's default disagrees with DEFAULT_GRID_K1")
assert _DEFAULTS.grid_b == parse_grid_axis("", DEFAULT_GRID_B), (
    "Config.grid_b's default disagrees with DEFAULT_GRID_B")
assert _DEFAULTS.baseline == parse_cell("", DEFAULT_BASELINE), (
    "Config.baseline's default disagrees with DEFAULT_BASELINE")
del _DEFAULTS
