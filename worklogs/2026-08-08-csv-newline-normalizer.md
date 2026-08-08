# CSV embedded-newline normalizer

Added `scripts/normalize-csv-newlines.py` for the TREC-DL gold CSVs under
`data/ragdoll-robustness/gold/trec-dl/` and other CSV datasets.

The script uses Python's CSV parser rather than line-oriented replacement, so
quoted multiline passages remain one field. It replaces embedded CR/LF runs
and adjacent horizontal whitespace with one space, then writes each logical
CSV record on one physical line. By default it creates a separate `.clean.csv`
file (or `<directory>-clean/`); `--in-place` performs an atomic replacement.
Existing outputs are rejected to prevent accidental overwrite.

Tests cover multiline CRLF fields, quoted commas, preservation of values,
one-record-per-line output, overwrite protection, and explicit in-place mode.
