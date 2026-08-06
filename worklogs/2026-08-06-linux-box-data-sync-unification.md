# 2026-08-06 — Linux box: merged local run data into the synced dir, then symlinked

**Branch:** `main`. Housekeeping, prompted by a user request to make sure
every run/eval artifact produced on this machine (the `facets_agent`
Phase 1/2/3 smoke tests, 15-topic runs, and arena/rubric evaluation work from
the preceding sessions) actually lands in the cross-machine synced dir
`/research/remote/petabyte/users/oleg/trec_rag_26_data/`, not just this
box's local `data/outputs/`/`evaluation-results/`.

## Starting state

`AGENTS.md`/`CLAUDE.md`'s Environment Rules said this Linux box's synced dir
was "laid out differently... not yet symlinked... treat as manual
copy-in/copy-out source... until the two layouts are unified" — unlike the
Downloads-synced machines, which already symlink directly. On this box,
`data/outputs/` and `evaluation-results/` were still real local directories,
holding runs no other machine had (`facets_agent`: 63 files across all three
phases' smoke tests plus the 15-topic run; `aus_agent`: 30 files; the
`arena/facets_agent-vs-facet_rag-15topic` and
`arena/aus_agent-vs-facets_agent-15topic-rubric` evaluation runs).

## What was actually there

Checking the synced dir directly (not trusting the stale doc) showed the
picture had changed since that guidance was written: it now has an
`outputs/<system>/` subtree with `facet_rag/` and `facets_agent/` already
populated, and `evaluation-results/` already has per-system dirs
(`aus-agent/`, `aus-agent-pilot/`, `facet_rag/`) plus an `arena/` subtree —
i.e. the same layout `ragrun.save_run` and this repo's own
`evaluation-results/` produce. The synced dir's own `README.md` explained
why: a Mac session (its `.DS_Store` file gives it away) had, on 2026-08-05,
"promoted [this dir] from a one-off recovery copy to the live sync target"
and symlinked its own `data/outputs/`/`evaluation-results/` to it — the
layouts had converged; this Linux box's docs just hadn't been updated to
say so.

## Merge

`rsync -av --ignore-existing` (never overwrites, only adds) from local into
the synced dir, per subtree:

```
outputs/facet_rag        0 new (all 10 local files already present remotely)
outputs/facets_agent     17 new (this session's phase1/2/3 smoke + related runs)
outputs/aus_agent        30 new (new subfolder — first aus_agent runs to land
                          under the canonical outputs/<system>/ layout rather
                          than the legacy aus-agent-traces/ bundle)
evaluation-results/      arena/facets_agent-vs-facet_rag-15topic/,
                          arena/aus_agent-vs-facets_agent-15topic-rubric/,
                          facet_rag/test15_arena/ — all new
```

Verified before deleting anything: a follow-up dry run showed 0 pending
files in either direction, and `diff -rq` between the local dirs and their
synced counterparts came back empty (byte-identical) for every subtree.
Only then were the local directories removed and replaced with symlinks:

```bash
ln -s /research/remote/petabyte/users/oleg/trec_rag_26_data/outputs data/outputs
ln -s /research/remote/petabyte/users/oleg/trec_rag_26_data/evaluation-results evaluation-results
```

Full test suite (1594/1594) still passes unchanged — the offline suite's
`isolated_data_dir` fixture repoints `RAGRUN_DATA_DIR` to a tmp dir
regardless, so it never touches the real symlinked path either way.

## Also noted, not touched

`outputs/outputs` inside the synced dir is a dangling symlink to
`/Users/e103037/Downloads/trec_rag_26_data/outputs` — a Mac-only path,
unreachable from this box or probably even meaningfully from the Mac itself
(nested inside its own sync target). Harmless: nothing in this repo's code
ever writes to a literal `outputs/` subdirectory, so it's just inert debris,
left alone rather than guessed at and possibly removing something another
session still depends on.

## Follow-up

`AGENTS.md`/`CLAUDE.md` updated to record this box as symlinked (matching
the Downloads-machine convention) instead of "not yet reconciled." The
synced dir's own `README.md` got a matching provenance note for the merge
itself. No more manual copy-out needed going forward on this machine — new
runs and eval artifacts land directly in the synced dir via
`ragrun.save_run` and the eval scripts' own output paths, same as any other
machine.
