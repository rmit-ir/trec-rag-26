"""SearchEngine load-time errors + actionable hints.

Each missing piece of a built-index dir maps to the exact CLI that produces
it, so an operator never has to grep through scripts to figure out the next
step. Errors propagate up to the CLI / FastAPI layer where they get rendered
without a Python traceback.
"""
from __future__ import annotations

from pathlib import Path


class EngineLoadError(RuntimeError):
    """Raised when the built-index dir is incomplete or malformed."""


def diskann_build_hint(index_dir: Path) -> str:
    return (
        f"This piece is produced by tasks/custom_index/scripts/build_diskann_index.py\n"
        f"  (typically invoked end-to-end via index_pipeline.sh). To rebuild from\n"
        f"  the per-shard encoded vectors at <ENCODED_DIR>, run:\n\n"
        f"  uv run --project tasks/custom_index python \\\n"
        f"    tasks/custom_index/scripts/build_diskann_index.py \\\n"
        f"    --encoded-dir <ENCODED_DIR> \\\n"
        f"    --out-dir {index_dir} \\\n"
        f"    --kind disk --metric mips \\\n"
        f"    --graph-degree 64 --complexity 100 \\\n"
        f"    --build-mem-gb 500 --search-mem-gb 64 \\\n"
        f"    --pq-disk-bytes 32 --threads 128\n"
    )


def docstore_build_hint(index_dir: Path) -> str:
    return (
        f"The docstore was not built. Construct it with:\n\n"
        f"  uv run --project tasks/custom_index python \\\n"
        f"    tasks/custom_index/scripts/build_docstore.py \\\n"
        f"    --corpus <PARQUET_CORPUS_DIR> \\\n"
        f"    --out {index_dir / 'docstore'} \\\n"
        f"    --compression zstd-9 --dict-size 1048576 \\\n"
        f"    --dict-sample-shards 1 --parallel 64\n\n"
        f"  (e.g. --corpus data/climbmix-400b-shuffle)\n"
    )


def ensure_path(path: Path, hint_fn) -> None:
    """Raise EngineLoadError with the build-step hint when ``path`` is missing."""
    if path.exists():
        return
    # Climb to the closest dir that looks like a built-index root for the hint.
    hint_root = path.parent.parent if path.parent.name == "docstore" else path.parent
    raise EngineLoadError(
        f"missing built-index part: {path}\n\n{hint_fn(hint_root)}"
    )
