# Wire PromptArmor v4 into RAGDOLL

Date: 2026-08-10

## Problem

`UMBRELA_PROMPTARMORV4` existed in `evaluation/ragdoll/src/ragdoll/umbrela/prompts.py`, but neither the CLI nor `render_umbrela_prompt` could select it. Runs labeled `promptarmor-v4` were invoked with `--prompt-type promptarmor` and therefore used the original PromptArmor template. The output directory name had no effect on prompt selection.

## Changes

- Added `promptarmorv3` and `promptarmorv4` to both UMBRELA CLI prompt-type choice lists (materialization and judging).
- Added the `promptarmorv4` renderer branch returning `UMBRELA_PROMPTARMORV4`.
- Exported the existing v3 and v4 prompt constants through `ragdoll.umbrela`.
- Added a renderer regression test proving v4 contains the `[MARK]` defense and differs from v1.
- Added a CLI materialization regression test proving `--prompt-type promptarmorv4` is accepted, retained as prompt provenance, and produces the v4 instruction.

## Validation

Focused regressions:

```bash
uv run --project evaluation/ragdoll --group dev pytest evaluation/ragdoll/tests/test_umbrela.py::test_promptarmor_v4_selects_marker_aware_defense evaluation/ragdoll/tests/test_config.py::test_cli_materializes_promptarmor_v4
```

Result: 2 passed.

Lint:

```bash
uv run --project evaluation/ragdoll --group dev ruff check evaluation/ragdoll/src/ragdoll/cli.py evaluation/ragdoll/src/ragdoll/umbrela evaluation/ragdoll/tests/test_umbrela.py evaluation/ragdoll/tests/test_config.py
```

Result: all checks passed.

The broader focused files produced 24 passes and two failures unrelated to this wiring: the existing v1 test expects an older warning string that no longer matches the locally modified v1 template, and the Windows fake-agent resume fixture yielded an unparsable judgment. Both new v4 tests passed independently.

## Result provenance warning

The existing directory `evaluation-results/llm-judge-robustness/yun_yi/promptarmor-v4/` was generated with `--prompt-type promptarmor`; it is not a v4-prompt evaluation. Preserve it for audit purposes, but exclude or relabel it. A corrected run must use `--prompt-type promptarmorv4` and should be stored separately, for example under `promptarmor-v4-corrected/`.
