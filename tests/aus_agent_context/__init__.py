"""aus_agent staged/committed-context tests (migrated from the ad-hoc suite).

A package rather than a bare directory so the non-test helper module ``fakes.py``
can be imported as ``aus_agent_context.fakes``: ``pythonpath`` already carries
``tests/``, and pytest's ``importlib`` import mode does not put a test file's own
directory on ``sys.path``. Same reason ``tests/contract`` is a package.
"""
