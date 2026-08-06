"""agent_harness staged/committed-context tests (migrated from the ad-hoc suite).

A package rather than a bare directory so the non-test helper module ``fakes.py``
can be imported as ``agent_harness_context.fakes``: ``pythonpath`` already carries
``tests/``, and pytest's ``importlib`` import mode does not put a test file's own
directory on ``sys.path``. Same reason ``tests/contract`` is a package.

Named ``agent_harness_context`` rather than ``agent_harness`` (the package under
test) to avoid colliding with the real top-level ``src/agent_harness`` package on
``sys.path`` — both ``src`` and ``tests`` carry ``pythonpath`` entries, so a
same-named test package would shadow (or be shadowed by) the real one.
"""
