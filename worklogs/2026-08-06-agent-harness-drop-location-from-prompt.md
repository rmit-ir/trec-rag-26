# 2026-08-06 — stop leaking the operator's timezone into every research prompt

`agent_harness.agent.now_full()` (the timestamp injected into `TASK_PROMPT`,
`"Current date and time: {now}"`, sent as a user message on every single
run of every system built on the shared harness — aus_agent, facets_agent,
facet_rag) formatted as:

```
{now:%A, %d %B %Y, %H:%M:%S %z} ({TZ.key})
```

`TZ` (`src/ragrun/trajectory.py`) is `ZoneInfo("Australia/Melbourne")` — so
`TZ.key` put the literal string `Australia/Melbourne` into the model's
context on every research request, regardless of what the request was
about. That tells the model where the operator running this harness is
physically located, which has no bearing on a generic research task and
risks quietly biasing answers toward an Australian frame (e.g. audience
assumptions, unit/spelling conventions, "local" readings of ambiguous
requests) unless the request is itself about a place or timezone, in which
case that context should come from the request text, not from leaking the
infra's own location.

Fix: drop the `({TZ.key})` suffix, keep the numeric UTC offset (`%z`) —
still gives the model an unambiguous, location-neutral anchor for "today"
and recency judgements, without naming a place:

```
{now:%A, %d %B %Y, %H:%M:%S %z}
```

`TZ` itself is untouched — it still drives the actual wall-clock recorded
in each run's trace (`t_start`/`t_end`), which is internal bookkeeping, not
sent to the model, so no leak there. Full offline suite re-run clean (1657
passed, 0 skips) after the change; no test asserted the old `(TZ.key)`
format.
