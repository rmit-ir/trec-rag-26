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
| `BM25_TUNE_BUDGET_USD` | `200.0` | `pricing` |
| `BM25_TUNE_PRICING_TIER` | `standard` | `pricing` |

The budget is **cumulative across the whole experiment**, not per-run: its
durable state lives in `costs/totals.json` under the data dir, deliberately
outside `runs/` (PLAN §4.2).
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
DEFAULT_BUDGET_USD = 200.0
DEFAULT_PRICING_TIER = "standard"
PRICING_TIERS = ("standard", "batch", "flex", "priority")

#: The labeled search log every stage reads from (PLAN §2.1). Relative to the
#: data dir so an alternate `BM25_TUNE_DATA_DIR` (a test tmp dir) works.
INPUT_BASENAME = "trec-rag26-test119-search-labeled.jsonl"
SHA256SUMS_BASENAME = "SHA256SUMS"


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


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw.strip())
    except ValueError as exc:
        raise ConfigError(f"{name}={raw!r} is not a number") from exc


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
    budget_usd: float
    pricing_tier: str
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
                "BM25_TUNE_PRICING_TIER")
            if os.environ.get(name, "").strip())
        return cls(
            data_dir=Path(_env_str("BM25_TUNE_DATA_DIR",
                                   str(DEFAULT_DATA_DIR))).expanduser(),
            index_dir=Path(raw_index).expanduser() if raw_index else None,
            judge_model=_env_str("BM25_TUNE_JUDGE_MODEL", DEFAULT_JUDGE_MODEL),
            judge_region=_env_str("BM25_TUNE_JUDGE_REGION",
                                  DEFAULT_JUDGE_REGION),
            judge_concurrency=_env_int("BM25_TUNE_JUDGE_CONCURRENCY",
                                       DEFAULT_JUDGE_CONCURRENCY),
            budget_usd=_env_float("BM25_TUNE_BUDGET_USD", DEFAULT_BUDGET_USD),
            pricing_tier=tier,
            overridden=overridden,
        )

    # -- derived paths (pure; no mkdir) -------------------------------------
    @property
    def inputs_dir(self) -> Path:
        return self.data_dir / "inputs"

    @property
    def input_file(self) -> Path:
        return self.inputs_dir / INPUT_BASENAME

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

    def ensure_dirs(self, *paths: Path) -> None:
        """`mkdir -p` the given artifact dirs. The only filesystem mutation here."""
        for path in paths:
            path.mkdir(parents=True, exist_ok=True)

    def describe(self) -> str:
        """One-line summary for the `[LOAD]` log line."""
        index = self.index_dir if self.index_dir is not None else "<unset>"
        return (f"data_dir={self.data_dir} index_dir={index} "
                f"judge_model={self.judge_model} region={self.judge_region} "
                f"concurrency={self.judge_concurrency} "
                f"budget=${self.budget_usd:.2f} tier={self.pricing_tier} "
                f"overridden={','.join(self.overridden) or 'none'}")
