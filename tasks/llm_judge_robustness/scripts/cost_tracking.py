"""Reusable metered-cost calculation and persistent run logging helpers."""
from __future__ import annotations

import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

DEFAULT_USD_PER_MILLION_CHARACTERS = Decimal("15.00")
ONE_MILLION = Decimal(1_000_000)


def estimate_cost_usd(
    billable_units: int,
    usd_per_million_units: Decimal | str | int | float,
) -> Decimal:
    """Return exact estimated USD cost for a metered quantity.

    The result remains a ``Decimal`` so callers control when and how monetary
    values are rounded or serialized.
    """
    rate = Decimal(str(usd_per_million_units))
    if billable_units < 0:
        raise ValueError("billable_units cannot be negative")
    if rate < 0:
        raise ValueError("usd_per_million_units cannot be negative")
    return Decimal(billable_units) * rate / ONE_MILLION


def _read_jsonl_objects(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number}: expected a JSON object")
            rows.append(value)
    return rows


def _atomic_write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            for row in rows:
                stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        Path(temporary_name).replace(path)
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def _atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        Path(temporary_name).replace(path)
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise


class CostRunLogger:
    """Log Amazon Translate usage while maintaining a cumulative cost total."""

    def __init__(
        self, output_root: Path, *, rate: Decimal, years: list[int], languages: list[str]
    ) -> None:
        self.output_root = output_root
        self.rate = rate
        self.years = years
        self.languages = languages
        self.run_id = f"translate-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:8]}"
        self.started_at = datetime.now(timezone.utc)
        self.requests = 0
        self.characters = 0
        self.status = "complete"

    def __enter__(self) -> "CostRunLogger":
        return self

    def record_request(self, text: str) -> None:
        """Count one successful request using its billable input characters."""
        self.requests += 1
        self.characters += len(text)

    def __exit__(self, exc_type: Any, exc: BaseException | None, traceback: Any) -> bool:
        if exc_type is KeyboardInterrupt:
            self.status = "interrupted"
        elif exc_type is not None:
            self.status = "failed"
        ended_at = datetime.now(timezone.utc)
        cost = estimate_cost_usd(self.characters, self.rate)
        record: dict[str, Any] = {
            "run_id": self.run_id,
            "started_at": self.started_at.isoformat(),
            "ended_at": ended_at.isoformat(),
            "status": self.status,
            "years": self.years,
            "languages": self.languages,
            "successful_requests": self.requests,
            "billable_input_characters": self.characters,
            "usd_per_million_characters": float(self.rate),
            "estimated_cost_usd": float(cost),
        }
        if exc is not None:
            record["error"] = f"{type(exc).__name__}: {exc}"

        log_path = self.output_root / "_runs.jsonl"
        prior = _read_jsonl_objects(log_path)
        _atomic_write_jsonl(log_path, [*prior, record])
        total_characters = (
            sum(int(row.get("billable_input_characters", 0)) for row in prior)
            + self.characters
        )
        total_cost = (
            sum(Decimal(str(row.get("estimated_cost_usd", 0))) for row in prior)
            + cost
        )
        _atomic_write_json(
            self.output_root / "_cost-total.json",
            {
                "updated_at": ended_at.isoformat(),
                "runs": len(prior) + 1,
                "successful_requests": (
                    sum(int(row.get("successful_requests", 0)) for row in prior)
                    + self.requests
                ),
                "billable_input_characters": total_characters,
                "estimated_cost_usd": float(total_cost),
                "note": "Estimate before free tier, credits, taxes, or account-specific pricing.",
            },
        )
        print(
            f"Run cost: ${cost:.6f}; cumulative estimated cost: ${total_cost:.6f} "
            f"({total_characters} characters)"
        )
        return False
