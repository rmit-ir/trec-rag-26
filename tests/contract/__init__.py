"""Contract tests: TREC RAG 2026 input/output format conformance.

This is a package (not a bare test dir) so the non-test helper module
``runfile.py`` can be imported as ``contract.runfile`` — ``pythonpath`` already
carries ``tests/``, and pytest's ``importlib`` import mode does not put a test
file's own directory on ``sys.path``.
"""
