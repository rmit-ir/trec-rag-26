#!/usr/bin/env python3
"""Remove embedded newlines from CSV fields while preserving CSV structure."""
from __future__ import annotations

import argparse
import csv
import os
import re
import tempfile
from pathlib import Path

NEWLINE_RUN = re.compile(r"[ \t]*[\r\n]+[ \t]*")


def clean_value(value: str) -> str:
    """Replace each run of embedded line breaks and surrounding space with one space."""
    return NEWLINE_RUN.sub(" ", value)


def clean_csv(source: Path, destination: Path) -> tuple[int, int]:
    """Write a one-physical-line-per-record copy and return row/change counts."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    os.close(fd)
    temporary = Path(temporary_name)
    rows = 0
    changed_rows = 0
    try:
        with (
            source.open("r", encoding="utf-8-sig", newline="") as input_stream,
            temporary.open("w", encoding="utf-8-sig", newline="") as output_stream,
        ):
            reader = csv.reader(input_stream)
            writer = csv.writer(output_stream, lineterminator="\n")
            for row in reader:
                cleaned = [clean_value(value) for value in row]
                rows += 1
                changed_rows += cleaned != row
                writer.writerow(cleaned)
        temporary.replace(destination)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return rows, changed_rows


def csv_sources(path: Path) -> list[Path]:
    """Resolve one CSV file or the immediate CSV children of a directory."""
    if path.is_file():
        if path.suffix.lower() != ".csv":
            raise ValueError(f"input file is not CSV: {path}")
        return [path]
    if path.is_dir():
        sources = sorted(path.glob("*.csv"))
        if not sources:
            raise ValueError(f"input directory contains no CSV files: {path}")
        return sources
    raise ValueError(f"input does not exist: {path}")


def destinations(
    input_path: Path, sources: list[Path], output: Path | None, in_place: bool
) -> list[Path]:
    """Map sources to explicit, default, or in-place destinations."""
    if in_place:
        return sources
    if input_path.is_file():
        target = output or input_path.with_name(f"{input_path.stem}.clean.csv")
        if target.exists():
            raise ValueError(f"output already exists (use --in-place to replace input): {target}")
        return [target]
    output_dir = output or input_path.with_name(f"{input_path.name}-clean")
    if output_dir.exists() and not output_dir.is_dir():
        raise ValueError(f"directory output is an existing file: {output_dir}")
    targets = [output_dir / source.name for source in sources]
    existing = next((target for target in targets if target.exists()), None)
    if existing:
        raise ValueError(f"output already exists: {existing}")
    return targets


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="A CSV file or a directory of CSV files.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--output", type=Path, help="Output file, or output directory for directory input.")
    group.add_argument(
        "--in-place",
        action="store_true",
        help="Atomically replace each input file after successful conversion.",
    )
    args = parser.parse_args()

    try:
        sources = csv_sources(args.input)
        targets = destinations(args.input, sources, args.output, args.in_place)
        for source, target in zip(sources, targets, strict=True):
            rows, changed = clean_csv(source, target)
            print(f"{source} -> {target}: {rows} rows, {changed} rows changed")
    except (OSError, csv.Error, UnicodeError, ValueError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
