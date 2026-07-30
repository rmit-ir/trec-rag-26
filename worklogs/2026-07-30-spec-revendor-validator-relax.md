# Re-vendor the track spec (v0.3.0 → v0.6.0) and relax the wrongly-strict validator

Follow-on from `2026-07-30-evaluation-measures.md`. That session ended with the
user asking whether the refreshed submodules meant any open issue needed
updating; the answer turned out to be much larger than an issue triage, so this
worklog covers the finding, the code changes, and the recurrence prevention.

Closes #8 (re-vendor), #7 (organizer question, now answered upstream), #9
(docid-string citations). Opens #10 (request-pacing policy).

## The finding: our canonical spec had silently drifted three minor versions

The chain, because it is the kind of thing that will happen again:

1. `git submodule update --remote` brought in a rewrite of
   `data/official/trec-rag-2026-data/trec-rag-2026/baselines/rag/README.md`
   (184 lines).
2. That rewrite designates the **track-guidelines skill** as the canonical spec
   for the submission formats — no longer `ragnarok_style_ag.py`.
3. That skill lives at `skills/trec-rag-2026-track-guidelines/`, which is a
   **vendored copy**, not a submodule.
4. So `git submodule update` never touched it, and nothing else did either. It
   sat at **v0.3.0 while upstream was at v0.6.0.**

Upstream is `https://github.com/TREC-RAG/trec-rag-skills.git` @
`f281e88f61252662033c681df8b1ed2d0ceda97e`.

The reason it matters: **v0.6.0 relaxed three validation rules that
`validate_rag_output` was still enforcing.** Our local validator was rejecting
conforming submissions. Issue #7 had been sitting open asking the organizers to
confirm exactly these rules — they had already answered, in a file we had a stale
copy of.

Checking the other vendored skills found a second one stale:
`skills/pyserini-rest-api/` at v0.2.0 vs upstream v0.3.0, hiding a **mandatory
request-pacing policy** for the shared ClimbMix API that did not exist in our
copy at all.

| Vendored skill | Ours was | Upstream | Now |
|---|---|---|---|
| `trec-rag-2026-track-guidelines` | v0.3.0 | v0.6.0 | v0.6.0, byte-identical |
| `pyserini-rest-api` | v0.2.0 | v0.3.0 | v0.3.0, byte-identical |
| `trec-rag-climbmix-corpus-creation` | v0.1.0 | v0.1.0 | already current |
| `trec-rag-new-system` | v0.2.0 | — | ours, not vendored |

Verified before overwriting that the two stale copies held no local edits worth
preserving: their git history mirrors the upstream PR titles, so a wholesale
replace loses nothing. `references/test-data.md` (87 lines) is new in v0.6.0 and
was simply absent locally.

## What v0.6.0 changed, and what it cost us

### The three rules that inverted

`rag-task.md` gained explicit *do not reject* directives, plus a blanket
instruction to "apply only the explicit structural rules … do not introduce
additional stylistic validation requirements". Every one of the three was a rule
we enforced:

| v0.3.0 (what we implemented) | v0.6.0 | Our error |
|---|---|---|
| "Do not add extra keys to the `metadata` object." | "`metadata` may also contain any additional participant-defined fields" — and the spec's own example now shows `generator` + `retrieval_depth` | rejected on extra keys |
| "`references`: … cited by the answer. **Do not include uncited documents.**" | "may include documents that are not cited by the answer; uncited references do not hurt the score" | rejected on any uncited reference |
| citations = "up to three zero-indexed positions" | "zero to three citations … An empty array (`[]`) is valid" | empty array was already fine, but the message said "indices" |

Note the direction. #7 was filed worrying we were **too permissive** and would
ship something the official validator rejected. After v0.6.0 the error had
inverted: we were **too strict**, and would reject our own conforming
submission. The uncited-references rule is the dangerous one — it fails any
system whose retrieval depth exceeds what its answer cites, which is the normal
case, so this would have fired on a real submission rather than an edge case.

### A new citation format

`answer[].citations` entries may now be **either** a zero-based integer position
into `references` **or** the ClimbMix docid string written verbatim. We accepted
only `int`, so a docid-citing run was rejected on every sentence.

This also had a cascade bug: an unresolvable docid string produced *two* errors —
"cites invalid reference index" and, because it never mapped to a position, a
spurious "references never cited" naming a reference the answer plainly did cite.
Two messages for one mistake, the second pointing at the wrong thing.

### Other v0.6.0 changes checked and found already-compliant

- **Variable-Depth Retrieval Rule** (new named section in `retrieval-task.md`):
  choose `k` per narrative, "do not pad to a conventional cutoff such as 10, 100,
  or 1000". Audited — `tests/contract/runfile.py:23-24` already encodes "no fixed
  row cap, and row counts may differ across topics (so neither is checked — the
  absence is the rule)", pinned by
  `test_row_counts_may_differ_across_topics`. No `src/` runfile writer exists to
  pad. Nothing to change.
- **Word-count definition** made explicit as
  `sum(len(item["text"].split()) for item in answer)` — exactly what we compute.
- **`answer[].text` is opaque**: "should not attempt grammatical sentence
  detection", Markdown and headings permitted. We never validated text shape.
- **Terminology**: topic → narrative throughout; `topic_id` retained only as the
  literal TREC run-file column name. Our field names were already
  `narrative_id`/`narrative`.
- **119 official test narratives**, `rag2026-0`..`rag2026-118`. Previously
  verified against the data submodule (SHA-256 `72dc2fd…`, 119 rows).
- **Deadline auto-corrected** by the re-vendor: August 7th → **August 8th**
  (source checked July 17, 2026). Grepped for stale "August 7" references
  afterwards — none remain.
- **Support measures now stated** — see below.

### The measures question from the previous session is answered

The earlier worklog concluded that "2026 uses the same formulas as 2024" was an
expectation, not confirmable from the track spec, having grepped the data
submodule's four READMEs and found nothing. That was the wrong place to look.
v0.6.0 `rag-task.md:126-133` names **weighted citation precision and recall**,
states the zero-citation asymmetry twice, and cites the same study by name (the
SIGIR '25 published version, `10.1145/3726302.3730165`, of the arXiv preprint we
documented).

`docs/evaluation-measures.md` §1.8 is new and records the split between what the
spec pins down and what we are still inferring from 2024. The two that matter:

- **FS/PS/NS = 1.0/0.5/0.0 is unstated** — "weighted" is never expanded.
- **First-citation-only judging is unstated**, and it is load-bearing. If 2026
  judges *all* citations of a sentence, citing three passages when one supports
  the claim starts costing precision; under first-citation-only it costs nothing.
  The spec's "order the citations from strongest to weakest support" rule
  (`rag-task.md:146`) is exactly what makes a first-citation reading safe, which
  is weak evidence the protocol carries over — but not a statement of it.
  Practical upshot: cite the single strongest passage, optimal under either.

Also corrected the earlier worklog's caveat with a forward pointer rather than a
rewrite, since the claim as scoped (the submodule READMEs) was accurate.

## Changes

### `src/ragrun/outputs.py`

`validate_rag_output` — removed the extra-metadata-keys check, removed the
uncited-references coverage check (and its `cited: set[int]` accumulator), added
a docid-string branch. Both removals carry a `Do not reinstate` comment naming
the spec rule, because they look like missing validation to anyone reading the
function cold.

```python
for c in cits:
    # A citation is either a zero-based position into ``references`` or
    # the docid string of a reference entry, written verbatim.
    if isinstance(c, str):
        if c not in refs:
            errs.append(f"answer[{i}] cites unknown reference docid {c!r}")
    elif isinstance(c, int) and 0 <= c < len(refs):
        continue
    else:
        errs.append(f"answer[{i}] cites invalid reference index {c!r}")
```

Message reworded "at most 3 indices" → "at most 3 citations", since an index is
no longer the only form.

**Scope discipline worth recording:** the first draft of that branch used
`type(c) is int`, which would have silently fixed the `bool`-validates-as-index-1
quirk tracked as #3 item 11. Reverted to `isinstance` — a drive-by fix inside an
unrelated PR is how a pinned defect gets un-pinned without anyone deciding to.

Docstring fix in the same file and in
`src/systems/ali_deepresearch/answer_format.py`: both asserted "every reference
cited" as a track requirement. `answer_format.py` still prunes uncited
references, which is now tidiness rather than conformance ("keeping only useful
documents can make submissions easier to inspect") — comment says so.

Checked and deliberately not changed: `aus_agent`'s uncited-report refusal
(`agent.py:307`). That is a grounding quality gate justified by "Avoid
unsupported claims", still in v0.6.0 — it bounces an answer that cites *nothing*,
which is different from permitting uncited references.

### Tests

`tests/contract/test_output_rag_json.py` — removed 3 `VIOLATION_CASES` rows
(`metadata-extra-key`, `metadata-extra-diagnostic-key`, `reference-never-cited`),
renamed `citation-non-int-string` → `citation-stringified-index` (a docid string
is now legal; the stringified index `"0"` is not, because it matches no
reference), and added 7 tests:

| Test | Pins |
|---|---|
| `test_extra_metadata_keys_are_allowed` (3 params) | superset check, not equality; the `team_id_v2` param guards the obvious wrong fix — a prefix/substring test against the required names |
| `test_uncited_references_are_allowed` | the rule that would have failed a real submission |
| `test_empty_citations_array_is_allowed` | costs recall, not validity |
| `test_docid_string_citations_are_accepted` | the new format |
| `test_docid_and_index_citations_can_be_mixed` | both forms, within one sentence |
| `test_unknown_docid_citation_reports_one_violation_only` | the cascade bug — exact-list equality, so a second spurious message fails |
| `test_docid_citation_must_match_verbatim` | no whitespace strip, no case fold (3 variants) |

Two existing tests changed meaning rather than breaking:

- `test_build_rag_output_splats_a_string_reference_current_behaviour` — passing a
  bare docid string still yields 17 single-character "docids", but now validates
  **completely clean**. Every character is a `str` so the type check passes, and
  the 16 uncited ones are legal. The old validator at least emitted a confused
  "never cited" message; there is now no local signal at all. Docstring updated
  to say a `str` guard in `build_rag_output` is the only place this can be caught.
- `test_duplicate_docid_in_references_is_not_flagged_current_behaviour` — the
  duplicate now also makes a docid citation **ambiguous** (it resolves to two
  positions and the validator cannot tell which was meant). Accepted either way,
  since a docid check is membership not a unique lookup. Extended the fixture to
  cover the docid-citation case.

`tests/contract/test_output_trajectory.py::test_save_run_writes_violations_file_when_the_output_is_invalid`
used an uncited reference to trigger a violations file. Switched to a dangling
citation index — one of the few rules that survives the "do not reject"
directives — so the test keeps testing `save_run`'s persistence rather than
tracking validator policy.

Full suite: **795 passed, 4 deselected, ~10s** (`bash scripts/test.sh`). Was 792
before; +7 new, −4 removed parametrizations.

## Recurrence prevention

The drift was invisible because nothing ever compared the vendored copies to
upstream. `scripts/check_vendored_skills.py` (new, stdlib-only) clones upstream
`main` and byte-compares every vendored file, reporting version deltas from the
SKILL.md frontmatter:

```bash
python scripts/check_vendored_skills.py            # report drift, exit 1 if any
python scripts/check_vendored_skills.py --update   # re-vendor in place
```

Verified both directions rather than assuming: injected a version downgrade plus
a stray local file, confirmed it reported `STALE v0.2.0 -> v0.3.0` with both the
`differs` and `not upstream` lines and exited 1, then confirmed `--update`
restored the file byte-for-byte and removed the stray.

Not a submodule, for two reasons: Claude Code only discovers skills at
`skills/<name>/` directly, and upstream publishes 3 of our 4 skills so a
submodule would nest them a level down. `LOCAL_ONLY` holds `trec-rag-new-system`.

Not in the pytest suite — it needs network, and `tests/conftest.py`'s autouse
`no_network` fixture exists precisely to keep that out. Runs instead via
`.github/workflows/vendored-skills.yml`: weekly cron (Mondays 00:17 UTC, off the
hour to dodge the scheduler's peak-minute backlog), `workflow_dispatch`, and any
PR touching `skills/**` or the checker.

Documented at the top of `AGENTS.md` — the drift cost a session precisely because
nothing in the repo said these files were copies that go stale.

## Follow-up filed

**#10** — the newly-surfaced `pyserini-rest-api` v0.3.0 pacing policy. Audited
our clients against its five rules:

| Rule | Status |
|---|---|
| ≤1 in-flight request per worker | OK — every client is a synchronous `urlopen`, no async fan-out |
| Fixed modest worker pool | OK — `utils/search.py:76` is 2; `aus_agent/agent.py:157` and `tools/get_documents.py:81` cap at 8 (skill allows ~12) |
| `429` → honor `Retry-After`, else exponential backoff, bounded retries | **MISSING** |
| Same backoff for transient `5xx`/timeouts, never tight-loop | **MISSING** |
| Health check one-shot, not polling | OK |

So the concurrency half complies by construction; the backoff half is absent
(`grep -rniE "429|retry|backoff|Retry-After" src/utils/ src/tools/` returns only
unrelated prompt text). Filed rather than fixed here — it wants one shared
`urlopen_with_backoff` helper across 5 call sites plus `tests/dummy_api/`
coverage, which is its own change, not a rider on a spec-conformance PR.

## Issue triage (the original ask)

- **#7** → commented and closable: the organizer question it asks is answered
  upstream, and the concern inverted from too-permissive to too-strict.
- **#8**, **#9** → created earlier in the session, both implemented here.
- **#3** (11 defects pinned by `*_current_behaviour`) → commented: item 11
  (`bool` as index) unchanged but now deliberately left alone; item 3 (the string
  splat) is slightly *more* reachable, since it no longer produces any local
  diagnostic at all.
- **#4** (end-to-end suites for two systems) → unaffected, no comment.
- **#10** → new, above.

## Files

- `src/ragrun/outputs.py` — validator relaxed + docid citations
- `src/systems/ali_deepresearch/answer_format.py` — docstring/comment only
- `tests/contract/test_output_rag_json.py` — +7 tests, −4 params, 2 rewritten
- `tests/contract/test_output_trajectory.py` — violations-file trigger swapped
- `skills/trec-rag-2026-track-guidelines/` — re-vendored v0.3.0 → v0.6.0
  (5 files changed, `references/test-data.md` added)
- `skills/pyserini-rest-api/SKILL.md` — re-vendored v0.2.0 → v0.3.0
- `scripts/check_vendored_skills.py` — new
- `.github/workflows/vendored-skills.yml` — new
- `AGENTS.md` — new "Vendored Official Skills" section
- `docs/evaluation-measures.md` — §1.8 added, premise caveat corrected
- `worklogs/2026-07-30-evaluation-measures.md` — forward pointer to this log
