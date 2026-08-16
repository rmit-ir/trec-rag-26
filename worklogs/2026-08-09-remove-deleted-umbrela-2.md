# Remove deleted UMBRELA-2 path

The user deleted `evaluation/ragdoll/src/ragdoll/umbrela_2/` and clarified that
all relevance evaluation should use the supported `ragdoll umbrela judge`
command. Removed the stale `umbrela_2` import and `umbrela-2 judge` CLI parser,
plus the obsolete test and batch runner. Those stale references would otherwise
raise an import error before any RAGDOLL command could start.

The remaining prompt module currently exposes only `--prompt-type bing` and
`--prompt-type basic`; no armor/adversarial prompt text remains in source.

Moved separate `--failed-output` routing into the main
`ragdoll.umbrela.flows`: completed rows go to the primary judgment file and
failed rows go to the requested failure ledger. The focused failure-routing
test passes, the main CLI help command succeeds, and Ruff passes.
