# 2026-07-30 — Fixing the defects pinned by `*_current_behaviour` tests (#3)

Issue #3 listed 11 defects the `feat/systems-test-harness` branch surfaced in
`src/` but deliberately did **not** fix: each was pinned by a test asserting the
*current* (wrong) behaviour, so a fix announces itself by failing its pinning
test. This session worked the list.

The convention paid for itself. After all the `src/` edits, the suite showed
**exactly 10 failures and nothing else** — precisely the 10 pinned tests. That
is the whole point of the naming convention, and it is also the blast-radius
report: no collateral damage anywhere in the other 834 cases.

Final state: **844 passed, 4 deselected, ~15 s.**

## Disposition of all 11 items

| # | Item | Outcome |
|---|---|---|
| 1 | `search_pyserini` doesn't unwrap an object-valued `doc` | fixed |
| 2 | `search_lucene_bool` hardcodes `/scratch/fast/kun/...` | fixed |
| 3 | `validate_rag_output` crashes on non-string `answer[].text` | fixed |
| 4 | `build_rag_output(references="shard_…")` splats a string | fixed |
| 5 | intra-result duplicate chunks both keep their text | **already fixed upstream** (see below) |
| 6 | lucene_bool snippet borrows the next hit's header line | fixed |
| 7 | missing `doc` yields the string `"null"` | fixed |
| 8 | duplicate id within ONE ranking double-counts in RRF | fixed |
| 9 | U+2028/U+2029 pass through the JSONL unescaped | fixed |
| 10 | `rejection_marker` dispatches on a reason *prefix* | fixed |
| 11a | duplicate `references` not flagged | **declined** (see below) |
| 11b | `True` validates as citation index 1 | fixed |
| 11c | docids from `failed=True` calls enter `retrieved_docids` | **not a defect** (see below) |
| 11d | unrecognised `MCP_SEARCH_ENGINE` falls back silently | fixed |

## The three items that were not code changes

**Item 5 needed no work.** Its named pinning test
(`test_duplicate_rows_within_one_result_all_keep_their_text`) does not exist.
`git log --all -S` traced it to `18908f3`, whose message records that the
chunk-native commit rework (`39b1582`) fixed the underlying gap upstream — the
surviving test `test_two_pages_of_one_document_are_independent_commit_decisions`
now asserts the *fixed* behaviour. Nothing to do but say so.

**Item 11a (duplicate `references`) is deliberately declined.** `rag-task.md`
v0.6.0 lists what a validator may reject at `references`/`answer` level, and
duplicates are not on it — the same section that made extra `metadata` keys and
uncited references explicitly non-rejectable. Adding a rule of our own here is
exactly the mistake `b6ac6df` had to undo (see
`worklogs/2026-07-30-spec-revendor-validator-relax.md`). The pinning test stays
`*_current_behaviour`, which correctly reads as "known gap, accepted", not
"unfixed bug".

**Item 11c (`failed=True` docids) is intended behaviour, not a defect.** `failed`
describes the *tool call*; `retrieved_docids` describes *evidence exposure*.
`o3_deep_research` is the case that settles it: `add_item_step` parses docids out
of an `mcp_call`'s `output` and sets `failed` from a **separate** `error` field,
so one step can legitimately carry both — filtering on `failed` there would drop
docids the run really did read. All five `failed=True` call sites in `src/` pass
no docids anyway, and `retrieved_docids` appears nowhere in the spec (only in our
own scaffolder). Renamed the test to
`test_failed_call_docids_still_count_as_retrieved` and rewrote the docstring to
state the distinction, so it stops claiming to pin a bug. Callers wanting only
successes read `tool_call_counts` rather than `tool_call_counts_all` — the test
asserts both to keep the two notions visibly separate.

## Notes on the fixes worth keeping

**Item 1 routed through the existing extractor rather than duplicating it.**
`utils.fetch_doc._doc_text` already implements the spec's "if `doc` is an object,
extract its text-bearing field", but was wired only into the doc-fetch path.
`search_pyserini` now imports it. One subtlety: a *missing* `doc` (the
docids-only response mode) must stay `None`, not become `""` — that `None` is
what tells the fusion layer to borrow text from another source. Hence
`text=None if doc is None else _doc_text(doc)` rather than `_doc_text(c.get("doc"))`.

**Item 7 is the same function from the other side.** `_doc_text(None)` fell
through to the `json.dumps` fallback and returned the string `"null"`, which
reads as a one-word passage and can be quoted in a cited sentence. Guarded at
the top, which is also what makes item 1's route-through safe.

**Item 2 used the trick `ragrun.outputs` already uses** —
`Path(__file__).resolve().parents[2]` — so `DEFAULT_BS` follows the checkout
instead of naming one developer's `/scratch` path. The old value made
`LUCENE_BOOL_BS` mandatory on every other host, and the failure mode was a
"No such file" from inside bash.

**Item 6's fix is a one-line guard with a real consequence.** The snippet is the
line after the hit line — *unless* that line is itself the next hit, which
happens whenever BoolSearch emits no snippet (`snippet_chars=0`). Taking it
unconditionally handed the model `"[2] shard_… score=1.0"` as evidence text.
Ranks, docids and scores were always correct, so this corrupted only what the
model reads, which is why nothing else caught it.

**Item 9 was fixed at the right layer, which was not where the test looked.**
`json.dumps` does not escape U+2028/U+2029 and `ensure_ascii=False` is
deliberate (readable Unicode narratives). Records stay one physical line by the
LF definition, so every reader *we* use is fine — but `str.splitlines()` breaks
on both, and we cannot see the organizers' reader. The pinning test used a local
`to_jsonl` helper, i.e. a serializer the submission never goes through. So:

- new `ragrun.jsonl_row(obj)` — `json.dumps(..., ensure_ascii=False,
  separators=(",", ":"))` then escapes *only* those two code points;
- `scripts/export-rag-submission.py` (the real writer) now uses it;
- the test helper was repointed at `jsonl_row`, so these tests can no longer
  pass against something the submission doesn't use.

`ensure_ascii=True` would also have fixed it and would have turned every accented
name and non-Latin script in a narrative into `\uXXXX` soup. Added
`test_jsonl_row_leaves_the_rest_of_unicode_literal` so nobody later
"simplifies" `jsonl_row` into the blanket version.

**Item 10 was a coupling bug, not a logic bug.** `rejection_marker` inferred
duplicate-ness from `reason.startswith("duplicate/already committed")`, coupling
a model-facing marker to the exact prose of a human-facing message — rewording
the reason would have silently downgraded real duplicates to plain rejections,
and a caller-supplied `unselected_reason` that merely started that way got
`DUPLICATE_PREFIX` for a unit that was never committed (telling the model to hunt
for full text that does not exist). The ledger now passes `duplicate=` outright,
computed from what it actually retained (`duplicate_here`), and the prefix-match
survives only as a fallback restricted to the two exact reasons the ledger
generates — now named constants (`LATER_OCCURRENCE_REASON`,
`PARALLEL_OCCURRENCE_REASON`) so what it writes and what it recognises cannot
drift.

One thing deliberately *not* done: `tests/aus_agent_context/test_ledger_dedup.py`
still re-states those two reason strings as its own literals rather than
importing the constants. I made that change and reverted it — the duplication is
the point. Those strings are model-facing prose, so a reword in `src/` should
fail a test rather than travel silently into the prompt. Added a comment saying
so, so the next person doesn't "fix" it either.

**Item 11b is why `type(c) is int` and not `isinstance`.** `bool` is a subclass
of `int`, so a JSON `true` in `citations` validated as index 1. Noted in the
source, because `isinstance` is what anyone would write by reflex. (#9's comment
history records that a draft used `type(c) is int` and was reverted specifically
to avoid un-pinning this defect inside an unrelated commit — so this is the
deliberate fix it was waiting for.)

**Item 4's guard is now the *only* signal.** `references="shard_00459_61697"` →
17 single-character "docids" via `list(references)`, and since v0.6.0 made
uncited references legal that **validates completely clean** — every character is
a `str`, and nothing requires a reference to be cited. The old validator at least
emitted a confused "references never cited: indices [1..16]". There is no local
signal left, so `build_rag_output` now raises `TypeError` on a bare string, with
the message suggesting the fix (`did you mean [...]?`).

**Item 3's fix is purely the type guard.** The spec now *normatively* defines the
word count as `sum(len(item["text"].split()) for item in answer)`, which is
already what we compute, so the counting is untouched — commented as such in
source. The important part is what the crash cost: the `AttributeError` escaped
`validate_rag_output` → `save_run`, so the run's artifacts were never written at
all. A validation *report* must never destroy the thing it is reporting on.
Non-string `text` now appends an error and the loop keeps going, so a long answer
with one bad sentence still reports the word cap too (pinned by a new test).

**Item 11d was made loud, not fatal.** A live MCP server shouldn't refuse to
start over one env var, but a typo'd `MCP_SEARCH_ENGINE` previously ran a whole
experiment on the wrong retriever with nothing in the logs. Now warns to stderr
and still falls back to `hybrid`.

## New tests

| Test | Item |
|---|---|
| `test_doc_text_maps_a_null_doc_to_the_empty_string` | 7 |
| `test_lucene_bool_default_bs_path_is_inside_this_checkout` | 2 |
| `test_build_rag_output_accepts_a_non_list_sequence` | 4 |
| `test_a_non_string_text_does_not_suppress_the_citation_check` | 3 |
| `test_a_long_answer_with_one_bad_text_still_reports_the_word_cap` | 3 |
| `test_jsonl_row_leaves_the_rest_of_unicode_literal` | 9 |
| `test_the_marker_comes_from_the_ledger_not_from_the_reason_wording` | 10 |
| `test_an_unrecognised_engine_warns_before_falling_back` | 11d |

Ten pinning tests were flipped from `*_current_behaviour` to asserting the
correct behaviour; two remain (`test_narrative_padding_is_stripped_current_behaviour`,
`test_duplicate_docid_in_references_is_not_flagged_current_behaviour` — the
latter being 11a above).
