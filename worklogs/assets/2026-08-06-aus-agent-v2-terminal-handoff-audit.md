# `aus_agent_v2` terminal-handoff audit at `e89fbe98`

Date: 2026-08-06
Mode: offline, read-only audit
Pinned commit: `e89fbe982ac9edf6ee2f30731e120102eff52388`

## Outcome

There is no paid `contract-lean` output to inspect. The exact result is therefore
split deliberately:

1. commit-pinned static behavior and byte counts are from `git archive
   e89fbe98`, not from the dirty shared worktree;
2. service-reported token counts and research-history sizes are measured proxies
   from the complete frozen 30-topic pre-repair control;
3. observable-scout measurements come from the only two saved dual-scout topics;
4. fact carry-through and strict-anchor counts come from frozen offline replays,
   not from a contract-lean run.

The executable contract fixes the broad plan-to-answer omission class, but
`e89fbe98` still has four terminal defects:

- a supported research row can be declared `unresolved` because the e89
  validator checks only whether an unresolved row was searched, not whether it
  already has committed support;
- a direct `submit_answer` is accepted or rejected without a mandatory
  harness-authored terminal evidence handoff;
- the only recency handoff is lossy (`anchors[:2]` per row and 6,000 characters
  globally), and it is emitted as a correction only after free prose;
- closing a row requires the exact terms from any one mapped anchor, so
  additional extracted anchors/facts under that row can disappear legally.

The first defect is already corrected in the dirty shared worktree at audit
time, but it is present in the requested commit and must not be attributed to
`e89fbe98` as fixed.

No provider, search, Bedrock, OpenAI, judge, grader, or network call was made.
This audit added no paid cost.

## Provenance

| Input | Role | SHA-256 / selection |
|---|---|---|
| commit `e89fbe98` | exact source and prompt/tool definitions | `e89fbe982ac9edf6ee2f30731e120102eff52388` |
| `data/outputs/aus_agent_v2/*pre_repair_counterfactual.output.json` | complete frozen 30-topic planning/research/terminal proxy | exactly 30 files; metadata run id `sol-aus-v2-research-first-pre-repair-dev30-20260806` |
| `data/outputs/aus_agent_v2/20260806T231601950433+1000.i_m_currently_working_on.output.json` | dual-scout proxy topic 1 | metadata run id `sol-aus-v2-dual-scout-critical2-20260806` |
| `data/outputs/aus_agent_v2/20260806T231601956950+1000.conduct_an_analysis_to_determine.output.json` | dual-scout proxy topic 2 | same run id |
| `2026-08-06-aus-agent-v2-handoff-audit.md` | frozen criterion-stage audit | `54a7c244c6e6d6955158981831f1d87ad66a8e5fcda707939abee93f1ab3624e` |
| `2026-08-06-aus-agent-v2-commit-validator-replay.json` | selected-unit / old fact-support replay | `7973f5e32d5529e61fa3f7d7cf1dfae97186ee22807892ad6bbd7bd1cfb4dd27` |
| `2026-08-06-aus-agent-v2-anchor-strict-replay.json` | old fact cards through current strict anchor mapping | `cc1b4bdfb298023010cb4b489f8d7eb5493534f5edfe9b7c287254a029852e81` |
| `2026-08-06-finish-facts-pipeline-audit.log` | 30-topic fact-card carry-through | `97c5184c14abfe02cd0c9e40f0d25c9e72f0f0b013713f23d896a5ceebf911b3` |
| `2026-08-06-aus-agent-v2-lean-prompt-audit.json` | committed exact lean prompt strings | `d1cd04e51156d17fb49d345eef19c599f63c846d5386bad4a8b8c8ab275c6f88` |

The artifact census was:

```text
lean=0 control=30 dual=2
```

The shared worktree was dirty before this audit. In particular,
`src/systems/aus_agent_v2/coverage_contract.py` contained uncommitted validation
changes. All exact-code conclusions below were re-read with `git show` or loaded
from a temporary `git archive e89fbe98`; the temporary tree was automatically
deleted by `tempfile.TemporaryDirectory`.

## Exact selected architecture

`run_lean_contract_one` at `src/systems/aus_agent_v2/pipeline.py:161-195` sets:

```text
k=20
safety_max_rounds=40
coverage_plan=True
plan_critic=True
observable_scout=True
plan_reconcile=False
coverage_verify=False
audience_verify=False
finish_review=False
answer_blueprint=False
coverage_contract=True
prompt_variant="contract-lean"
```

The planner starts in a fresh context; the blind critic sees only the original
request; the observable scout sees the request, initial plan, and normalized
semantic additions; and research starts in another fresh context. The relevant
commit-pinned source is `agent.py:1538-1827`, with observable request construction
at `observable_scout.py:70-83`.

The research user message contains both the full merged prose plan and the
rendered executable contract (`agent.py:1762-1786`). Contract construction does
not duplicate rows: when structured scout additions are present it skips the
flattened `SCOUT` rows and adds the structured rows once
(`coverage_contract.py:264-337`). The duplication is model-facing prose, not
duplicate ledger identities.

## Commit-pinned static context

These are exact UTF-8 bytes and whitespace-delimited words before provider
framing. Tool bytes are compact JSON (`ensure_ascii=False`, separators `,` and
`:`).

| Stage/input | Bytes | Words |
|---|---:|---:|
| planner system | 2,768 | 401 |
| blind critic system | 5,821 | 793 |
| observable scout system | 3,230 | 449 |
| lean research system | 2,691 | 417 |
| plain terminal addendum | 496 | 75 |
| combined research system | 3,189 | 492 |
| contract search tool, complete compact JSON | 2,584 | — |
| contract commit tool, complete compact JSON | 2,296 | — |
| terminal submit tool, complete compact JSON | 1,574 | — |
| all research tool definitions | 6,454 | — |

The tool descriptions alone are 816 bytes / 123 words for search, 476 / 74 for
commit, and 472 / 73 for submit. The e89 commit document has only `id`, `reason`,
and `supports`; there is no `facts` field. Therefore the generic
`capture_committed_facts` call in `agent.py:2398-2407` cannot populate a fact
ledger on this path.

Provider-exact token counts do not exist for the lean candidate because no lean
generation exists. Static tokenizer estimates would not be equivalent to the
service-reported counts because provider tool framing and cache accounting are
included at runtime, so none are invented here.

## Frozen 30-topic token proxy

The following are service-reported tokens from the first valid draft cut of the
complete control. The initial research prompt is the old/default prompt, not the
lean prompt; it is a terminal-history scale proxy only.

| Stage | Mean | Median | Min | Max | Sum |
|---|---:|---:|---:|---:|---:|
| planner input | 698.23 | 670.0 | 610 | 931 | 20,947 |
| planner output | 965.87 | 893.5 | 635 | 1,724 | 28,976 |
| critic input | 1,278.23 | 1,250.0 | 1,190 | 1,511 | 38,347 |
| critic output | 2,382.27 | 2,368.5 | 885 | 5,648 | 71,468 |
| legacy research initial input | 5,525.43 | 5,505.0 | 5,307 | 5,846 | 165,763 |
| first-draft terminal input | 76,362.80 | 73,842.5 | 37,925 | 130,104 | 2,290,884 |
| pre-draft peak research input | 109,481.70 | 110,615.5 | 65,879 | 163,144 | 3,284,451 |
| research generations through first draft | 9.27 | 9.0 | 5 | 15 | 278 |
| searches through first draft | 28.43 | 28.0 | 12 | 56 | 853 |
| commits through first draft | 4.13 | 4.0 | 2 | 7 | 124 |

The terminal input is lower than the pre-draft peak because successful commits
replace unselected search text with tombstones while preserving selected units.

## Exact e89 transform of the frozen plan/critic population

The 30 frozen initial plans and normalized semantic critic outputs were passed
through the exact e89 `merge_plan_critique`, `build_coverage_contract`, and
`render_research_contract`. Observable additions are absent from this run, so
this is a lower bound for the selected lean architecture.

| Value | Mean | Median | Min | Max | Sum |
|---|---:|---:|---:|---:|---:|
| query bytes | 596.10 | 428.0 | 174 | 1,713 | 17,883 |
| initial-plan bytes | 3,601.27 | 3,661.0 | 2,608 | 4,080 | 108,038 |
| raw critic-output bytes | 3,538.33 | 3,595.5 | 2,835 | 3,995 | 106,150 |
| merged-plan bytes | 5,340.77 | 5,417.5 | 4,239 | 5,946 | 160,223 |
| constructed observable request bytes | 7,871.33 | 7,698.0 | 6,267 | 9,500 | 236,140 |
| planner contract rows | 11.37 | 12.0 | 9 | 13 | 341 |
| semantic scout rows | 8.00 | 8.0 | 8 | 8 | 240 |
| request-form rows | 0.10 | 0.0 | 0 | 1 | 3 |
| all lower-bound contract rows | 19.47 | 20.0 | 17 | 21 | 584 |
| rendered-contract bytes | 5,725.57 | 5,892.5 | 4,338 | 6,346 | 171,767 |
| constructed lean research-user bytes | 12,129.43 | 12,112.0 | 9,575 | 14,076 | 363,883 |
| obligation text represented in both plan and contract | 4,518.30 | 4,584.5 | 3,315 | 5,146 | 135,549 |

The last row is semantic obligation text, not byte-identical whole blocks: plan
numbering/labels/search leads and contract ids/protocol differ. It nevertheless
quantifies the same requirements being presented twice in one fresh research
message.

## Observable-scout proxy

Only two saved topics exercised the complementary observable scout. They used a
later reconcile step and the legacy research prompt, so only the observable turn
itself is observed. The current no-reconcile contract/user sizes are exact e89
counterfactual transforms of their saved initial plan and combined inventory.

| qid | observable request bytes | input tokens | output bytes | output tokens | semantic + observable additions | e89 rows | e89 contract bytes | e89 research-user bytes |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `683a58c9a7e7fe4e7695848b` | 8,465 | 2,340 | 2,301 | 2,333 | 8 + 6 | 25 | 6,939 | 13,832 |
| `6847465956a0f6376a6053fb` | 7,681 | 2,083 | 2,203 | 1,748 | 8 + 6 | 26 | 6,258 | 12,895 |

## Full 30-topic matrix

`qB` is query bytes; `obsReqB` is the constructed semantic-only observable
request; `dupReqB` is obligation text represented in both plan and contract.
Tokens are frozen service counts. `init tok`, `terminal tok`, and `peak tok` are
the legacy research proxy, not a lean token claim.

| qid | qB | planB | criticB | mergedB | obsReqB | P/S/F | contractB | researchUserB | dupReqB | plan tok in/out | critic tok in/out | init tok | terminal tok | peak tok | generations | search/commit |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `683a58c9a7e7fe4e7695846f` | 531 | 2608 | 2996 | 4239 | 6267 | 9/8/0 | 4338 | 9575 | 3315 | 683/635 | 1263/1599 | 5307 | 69817 | 114955 | 7 | 28/3 |
| `683a58c9a7e7fe4e76958488` | 174 | 3096 | 3448 | 4998 | 6851 | 10/8/0 | 5076 | 10715 | 3986 | 610/863 | 1190/2960 | 5317 | 91731 | 142547 | 11 | 35/5 |
| `684397d188c1deceb49af325` | 317 | 3557 | 3602 | 5361 | 7611 | 12/8/0 | 5734 | 11879 | 4533 | 641/855 | 1221/973 | 5496 | 130104 | 163144 | 15 | 56/7 |
| `6847465956a0f6376a60535d` | 331 | 3734 | 3514 | 5752 | 7713 | 11/8/0 | 5848 | 12398 | 4639 | 636/863 | 1216/2715 | 5500 | 88089 | 139114 | 9 | 32/4 |
| `684397d188c1deceb49af32d` | 431 | 3571 | 3995 | 5311 | 8130 | 11/8/0 | 5896 | 12105 | 4641 | 674/848 | 1254/2036 | 5466 | 68175 | 95608 | 9 | 23/4 |
| `683a58c9a7e7fe4e76958498` | 227 | 3557 | 3644 | 5264 | 7567 | 11/8/1 | 5938 | 11896 | 4423 | 621/894 | 1201/3432 | 5418 | 64304 | 85410 | 9 | 22/4 |
| `684397d188c1deceb49af31d` | 535 | 3277 | 3507 | 5109 | 7454 | 11/8/0 | 5287 | 11398 | 4161 | 682/775 | 1262/3017 | 5535 | 67624 | 84678 | 13 | 24/6 |
| `683a58c9a7e7fe4e7695848b` | 798 | 3931 | 3827 | 5421 | 8694 | 11/8/0 | 6316 | 13002 | 5109 | 748/1295 | 1328/5648 | 5584 | 66385 | 116625 | 7 | 25/3 |
| `6847465956a0f6376a605360` | 1454 | 4002 | 3904 | 5728 | 9500 | 11/8/0 | 6346 | 13995 | 5146 | 879/968 | 1459/3559 | 5794 | 75915 | 136790 | 7 | 28/3 |
| `6847465956a0f6376a605367` | 787 | 3918 | 3755 | 5571 | 8599 | 12/8/0 | 6266 | 13091 | 4952 | 717/1229 | 1297/2528 | 5573 | 51962 | 79637 | 7 | 19/3 |
| `6847465956a0f6376a605387` | 1552 | 4020 | 3563 | 5807 | 9270 | 13/8/0 | 6118 | 13944 | 4917 | 861/1262 | 1441/2700 | 5748 | 87384 | 119126 | 9 | 30/4 |
| `6847465956a0f6376a605391` | 963 | 3871 | 3725 | 5501 | 8696 | 12/8/0 | 6074 | 13005 | 4936 | 760/882 | 1340/1200 | 5597 | 105593 | 139618 | 11 | 41/5 |
| `6847465956a0f6376a6053a0` | 380 | 3885 | 3070 | 5434 | 7471 | 12/8/0 | 5636 | 11917 | 4493 | 647/891 | 1227/3137 | 5510 | 71770 | 93115 | 11 | 29/5 |
| `6847465956a0f6376a6053c9` | 309 | 3898 | 3789 | 5221 | 8137 | 12/8/0 | 6223 | 12220 | 5017 | 642/900 | 1222/2439 | 5482 | 92489 | 116633 | 11 | 36/5 |
| `6847465956a0f6376a6053ca` | 507 | 3512 | 3456 | 5531 | 7607 | 12/8/1 | 5975 | 12480 | 4529 | 682/886 | 1262/991 | 5532 | 55655 | 87200 | 7 | 19/3 |
| `6847465956a0f6376a6053fb` | 462 | 4080 | 3400 | 5476 | 8076 | 12/8/0 | 6013 | 12418 | 4915 | 660/1107 | 1240/1640 | 5440 | 70042 | 105444 | 7 | 26/3 |
| `6847465956a0f6376a605404` | 194 | 3654 | 3681 | 5544 | 7666 | 12/8/0 | 5914 | 12119 | 4636 | 623/850 | 1203/3239 | 5511 | 91115 | 120826 | 11 | 36/5 |
| `6847465956a0f6376a60542a` | 443 | 3817 | 3590 | 5475 | 7984 | 11/8/0 | 5889 | 12274 | 4664 | 670/843 | 1250/1721 | 5554 | 62049 | 96837 | 7 | 24/3 |
| `6847465956a0f6376a60542d` | 402 | 3690 | 3448 | 5414 | 7683 | 12/8/0 | 5650 | 11933 | 4402 | 670/1100 | 1250/3101 | 5643 | 81785 | 114452 | 9 | 30/4 |
| `6847465956a0f6376a605433` | 1229 | 3262 | 2835 | 4631 | 7456 | 13/8/0 | 5096 | 11423 | 4055 | 837/741 | 1417/1042 | 5535 | 77291 | 98208 | 11 | 34/5 |
| `6847465956a0f6376a60543d` | 397 | 3042 | 3038 | 4540 | 6608 | 12/8/0 | 4874 | 10278 | 3894 | 656/934 | 1236/885 | 5342 | 50610 | 76361 | 9 | 19/4 |
| `6847465956a0f6376a605440` | 195 | 3668 | 3808 | 5874 | 7809 | 12/8/0 | 5958 | 12494 | 4649 | 613/783 | 1193/2222 | 5473 | 70420 | 95188 | 9 | 23/4 |
| `6847465956a0f6376a605476` | 425 | 3501 | 3350 | 5122 | 7408 | 11/8/0 | 5449 | 11463 | 4318 | 676/867 | 1256/1083 | 5494 | 37925 | 65879 | 5 | 12/2 |
| `6847465956a0f6376a60547e` | 1713 | 3875 | 3601 | 5946 | 9322 | 10/8/0 | 5950 | 14076 | 4824 | 931/1153 | 1511/1169 | 5846 | 54320 | 79913 | 7 | 19/3 |
| `6847465956a0f6376a60547f` | 1135 | 3874 | 3911 | 5802 | 9062 | 12/8/0 | 6168 | 13572 | 4815 | 806/1724 | 1386/3991 | 5707 | 89986 | 132587 | 9 | 32/4 |
| `6847465956a0f6376a605492` | 200 | 3482 | 3471 | 5371 | 7283 | 12/8/0 | 5432 | 11470 | 4322 | 615/945 | 1195/2191 | 5439 | 71590 | 113980 | 7 | 28/3 |
| `6847465956a0f6376a605493` | 342 | 3494 | 3691 | 5401 | 7669 | 12/8/0 | 5674 | 11884 | 4329 | 649/893 | 1229/3104 | 5496 | 85589 | 111952 | 11 | 33/5 |
| `6847465956a0f6376a6054a7` | 300 | 3443 | 3839 | 5542 | 7716 | 11/8/0 | 5662 | 11971 | 4411 | 636/916 | 1216/1698 | 5441 | 92391 | 140285 | 9 | 32/4 |
| `6847465956a0f6376a6054ad` | 825 | 3733 | 3776 | 5368 | 8469 | 10/8/0 | 5915 | 12575 | 4767 | 768/1118 | 1348/2298 | 5632 | 79282 | 109060 | 9 | 30/4 |
| `6847465956a0f6376a6054be` | 325 | 2986 | 2916 | 4469 | 6362 | 9/8/1 | 5052 | 10313 | 3751 | 654/956 | 1234/3150 | 5351 | 89492 | 109279 | 15 | 28/7 |

## Research compaction and terminal payload proxy

The exact frozen raw-message replay isolated the research segment after the
plan-to-research phase boundary and before the first assistant prose draft. Each
function-call id was paired with its function-call output. Search results were
counted after the provider's committed-unit compaction.

| Value | Total | Per-topic mean | Median / range where available |
|---|---:|---:|---:|
| searches | 853 | 28.43 | 12–56 |
| commits | 124 | 4.13 | 2–7 |
| staged result units | 11,801 | 393.37 | 157–725 |
| staged full-text bytes before compaction | 17,277,528 | 575,917.60 | 220,616–1,073,941 |
| exact compacted search-payload bytes | 5,924,407 | 197,480.23 | 190,735.5; 96,760–332,401 |
| retained full-text bytes | 2,292,891 | 76,429.70 | 41,573–113,759 |
| retained text occurrences visible in raw segment | 1,049 | 34.97 | 20–58 |
| tombstones | 10,752 | 358.40 | — |
| commit-result bytes | 913,531 | 30,451.03 | 12,064–55,248 |
| commit-argument bytes | 208,990 | 6,966.33 | — |

The authoritative commit-validator replay counts 1,051 selected units across
124 pre-draft commit batches. The two-unit difference from raw retained-text
occurrences is an occurrence/cut-definition difference; 1,051 is authoritative
for selected units. That replay has zero fact cards and zero support rows because
the frozen control predates both schemas.

At terminal time the model still has the original request/plan/contract, all
assistant turns and tool arguments, retained selected-document text, compacted
tombstones for rejected rows, and every cumulative commit status in the same
conversation. Compaction therefore does not literally erase selected source
text or historical support arguments. The problem is deterministic state
projection and recency, not total historical absence.

## Anchors and fact carry-through

There is no observed contract-lean anchor population. The exact e89 schema can
create `EvidenceAnchor(document_id, claim, value_scope, must_include)` rows, but
the full-30 control has no `supports` field. The best-v2 replay is therefore:

```json
{
  "topics": 30,
  "pre_draft_commit_batches": 124,
  "selected_units": 1051,
  "fact_cards": 0,
  "support_rows": 0
}
```

The frozen fact-card arm supplies the only full-30 evidence about extracted
facts surviving to prose:

| Measure | Count | Rate |
|---|---:|---:|
| fact cards | 1,223 | 100% |
| parent document later cited | 1,103 | 90.2% |
| exact value in final prose | 92 | 7.5% |
| at least 60% lexical carry-through | 581 | 47.5% |
| numeric fact exact carry-through | 109 / 191 | 57.1% |

The strict current-anchor replay accepts only 164/1,223 historical fact rows
(13.4%): 734 are outside their claim/scope, 321 exceed the 80-character exact
term bound, three are malformed, and one source is missing. This is a validator
stress test, not a forecast: the old fact prompt did not ask for short verbatim
claim/scope overlap.

As a structural illustration only, those 164 accepted rows were mapped to one
`P01` per topic. Sixteen of 30 topics had more than two valid anchors, with a
maximum of 28. The e89 `anchors[:2]` status would display only 50 and omit 114
of the 164 accepted anchors. Current runs may distribute anchors across many
rows, so this is not an expected omission rate; it proves the recap cannot
represent a multi-anchor row completely.

## Exact terminal state and missing information

Successful commit processing compacts tool results, records validated anchors
only for actually committed ids, and appends a cumulative contract status to
the commit result (`agent.py:2262-2414`). The status renderer at commit-pinned
`coverage_contract.py:912-940`:

- prints at most the first two anchors for each row;
- stops globally at 6,000 characters;
- prints only a search count for open rows, not the attempted queries;
- has no stable anchor ids or distinction between required and optional anchors.

`submit_answer_request` at `coverage_contract.py:943-957` appends that status,
but it is called only when the model emits terminal free prose
(`agent.py:1914` and `agent.py:2122`). A direct submit enters validation
immediately at `agent.py:2514-2547`. If invalid, feedback at
`agent.py:2549-2557` contains only the validator problems and the instruction to
retry; it does not replay even the bounded status.

Consequently, the terminal model lacks a guaranteed recent snapshot of:

- every complete contract row and its latest closure state;
- every selected anchor for a row;
- a deliberate final claim map identifying which extracted values are meant to
  survive;
- fact cards (the schema does not expose them at all);
- stable required-anchor identities that terminal validation can enforce.

The earlier blueprint architecture implements precisely such a state transition:
`answer_blueprint.py:227-273` places the original request, pre-research plan,
normalized complete claim map, exact evidence ids, unresolved claims, and
selected fact cards at the context tail immediately before prose. The lean
contract path disables that alternative and has no equivalent mandatory
transition.

## Defects and minimal fix

### D0: e89 unresolved loophole

At commit-pinned `coverage_contract.py:823-838`, a must-answer id may be placed
in `unresolved` if it was searched. The validator does not reject a research row
that already has anchors and does not reject a structural row as unresolved.
Thus the model can legally discard supported extracted facts without writing a
cited sentence. The dirty worktree at audit time already adds both rejections;
those changes should be retained and tested in the eventual commit.

### D1: no mandatory final state transition

The first direct terminal tool call is judged against harness state the model
has never received as one complete tail packet. A model working at the frozen
proxy's 73,843-token median terminal context must reconstruct state from
historical tool calls and bounded cumulative recaps.

Minimal correction: intercept the first `submit_answer` attempt, do not validate
it, append one harness-owned `TERMINAL EVIDENCE HANDOFF`, and require exactly one
subsequent `submit_answer`. The packet should include every must-answer row,
attempted/open state, and a deterministic required anchor per supported row with
document id, claim, value scope, and exact terms. This costs one model turn but
does not add another writer or evaluator.

### D2: the recap silently drops anchors and possibly tail rows

Remove silent `anchors[:2]` selection from the mandatory packet. If the answer
budget permits only one anchor per row, choose it deterministically and mark it
`required`; do not imply the packet represents all anchors. Keep optional extra
anchors in a separately bounded field. Allocate the cap by must-answer row so a
long early row cannot hide later rows.

### D3: row closure is existential, not fact-complete

At commit-pinned `coverage_contract.py:788-820`, validation succeeds when all
exact terms from any one cited mapped anchor occur. It does not require every
anchor attached to the row. That is correct if anchors are alternatives, but it
cannot guarantee that multiple independently extracted facts survive.

The minimal schema addition is a stable anchor id plus
`required_for_answer: true|false`. The terminal packet lists every required id,
and validation requires the exact-term set for each required anchor. This keeps
fact completeness explicit without restoring the noisy historical fact-card
schema wholesale. A stricter all-anchor rule should not be inferred: some
anchors are alternatives or background, and the answer has a 1,024-word hard
limit.

## Limitations

- No lean run exists, so there is no lean service-token trace, cost, answer,
  support ledger, submission retry, or score.
- The full-30 token and compaction population uses the legacy/default system and
  no observable scout. It measures history scale, not exact lean token use.
- The two observable topics used a later reconcile stage and legacy prompt.
  Their observable input/output is observed; their reported lean contract/user
  sizes are deterministic counterfactual transforms.
- The strict 1,223-row replay maps old fact cards to `P01`; it is useful for
  validation and recap-capacity analysis but is not a prediction of anchors a
  new prompt would produce.
- UTF-8 byte counts exclude provider message wrappers, JSON transport envelopes,
  hidden reasoning, and tokenizer-specific framing.
- Repeated obligation bytes measure semantically repeated normalized
  requirements, not byte-identical complete blocks.
- The audit is code- and artifact-based. It does not establish an answer-quality
  effect; only a newly authorized complete generation and grade could do that.

## Exact offline commands

Artifact census:

```bash
lean_count=$(find data/outputs -type f -name '*.output.json' -print0 | xargs -0 rg -l '"run_id": "sol-aus-v2-lean-contract-dev30"' | wc -l)
control_count=$(find data/outputs/aus_agent_v2 -maxdepth 1 -type f -name '*pre_repair_counterfactual.output.json' | wc -l)
dual_count=$(find data/outputs/aus_agent_v2 -maxdepth 1 -type f -name '*.output.json' -print0 | xargs -0 rg -l '"run_id": "sol-aus-v2-dual-scout-critical2-20260806"' | wc -l)
printf 'lean=%s control=%s dual=%s\n' "$lean_count" "$control_count" "$dual_count"
```

Commit and source pinning:

```bash
git rev-parse e89fbe98
git show e89fbe98:src/systems/aus_agent_v2/pipeline.py | nl -ba
git show e89fbe98:src/systems/aus_agent_v2/agent.py | nl -ba
git show e89fbe98:src/systems/aus_agent_v2/coverage_contract.py | nl -ba
git diff e89fbe98 -- src/systems/aus_agent_v2/coverage_contract.py
```

Provenance hashes:

```bash
sha256sum \
  worklogs/assets/2026-08-06-aus-agent-v2-handoff-audit.md \
  worklogs/assets/2026-08-06-aus-agent-v2-commit-validator-replay.json \
  worklogs/assets/2026-08-06-aus-agent-v2-anchor-strict-replay.json \
  worklogs/assets/2026-08-06-finish-facts-pipeline-audit.log \
  worklogs/assets/2026-08-06-aus-agent-v2-lean-prompt-audit.json
```

Static code was imported from the pinned commit, not the worktree, with this
pattern; the same temporary archive pattern was used for the 30-topic transform:

```bash
uv run --no-project python - <<'PY'
import io, json, os, subprocess, sys, tarfile, tempfile

archive = subprocess.run(
    ["git", "archive", "e89fbe98"], check=True, stdout=subprocess.PIPE
).stdout
with tempfile.TemporaryDirectory(prefix="handoff-audit-") as td:
    with tarfile.open(fileobj=io.BytesIO(archive)) as tf:
        tf.extractall(td, filter="data")
    sys.path[:0] = [os.path.join(td, "src", "systems"), os.path.join(td, "src")]
    from aus_agent_v2.agent import load_system_prompt
    from aus_agent_v2.answer_form import AnswerFormPolicy, render_terminal_system_addendum
    from aus_agent_v2.coverage_contract import (
        commit_tool_with_contract,
        search_tool_with_contract,
        submit_answer_tool,
    )
    from aus_agent_v2.coverage_plan import COVERAGE_PLAN_SYSTEM
    from aus_agent_v2.observable_scout import OBSERVABLE_SCOUT_SYSTEM
    from aus_agent_v2.plan_critic import PLAN_CRITIC_SYSTEM
    from aus_agent_v2.search import build_search_tool_def

    policy = AnswerFormPolicy()
    research = load_system_prompt(10, "contract-lean")
    terminal = render_terminal_system_addendum(policy)
    tools = [
        search_tool_with_contract(build_search_tool_def(["semantic", "keyword"])),
        commit_tool_with_contract(),
        submit_answer_tool(policy),
    ]
    for name, value in [
        ("planner_system", COVERAGE_PLAN_SYSTEM),
        ("critic_system", PLAN_CRITIC_SYSTEM),
        ("observable_system", OBSERVABLE_SCOUT_SYSTEM),
        ("lean_system", research),
        ("terminal_addendum", terminal),
        ("combined_system", research + "\n\n" + terminal),
    ]:
        print(name, len(value.encode()), len(value.split()))
    for tool in tools:
        raw = json.dumps(tool, ensure_ascii=False, separators=(",", ":"))
        print(tool["name"], len(raw.encode()))
    print("all_tools", sum(len(json.dumps(
        tool, ensure_ascii=False, separators=(",", ":")
    ).encode()) for tool in tools))
PY
```

Frozen token extraction used only the 30 counterfactual files and cut each
trace at the first post-initial generation containing prose and no tool calls:

```bash
uv run --no-project python - <<'PY'
import json, statistics as st
from pathlib import Path

values = {key: [] for key in (
    "plan_in", "plan_out", "critic_in", "critic_out", "initial_in",
    "terminal_in", "peak_in", "generations", "searches", "commits"
)}
for path in sorted(Path("data/outputs/aus_agent_v2").glob(
        "*pre_repair_counterfactual.output.json")):
    data = json.loads(path.read_text())
    steps = data["trace"]["steps"]
    generations = [(i, step) for i, step in enumerate(steps)
                   if step.get("type") == "generation"]
    kind = lambda step: (step.get("input") or {}).get("kind")
    plan = next(step for _, step in generations
                if kind(step) == "coverage_plan_request")
    critic = next(step for _, step in generations
                  if kind(step) == "fresh_plan_critic")
    initial_i, initial = next((i, step) for i, step in generations
                              if kind(step) == "initial")
    draft_i, draft = next(
        (i, step) for i, step in generations
        if i >= initial_i
        and (step.get("output") or {}).get("text")
        and not ((step.get("output") or {}).get("tool_calls") or [])
    )
    research = [step for i, step in generations if initial_i <= i <= draft_i]
    row = {
        "plan_in": plan["stats"]["tokens"]["input"],
        "plan_out": plan["stats"]["tokens"]["output"],
        "critic_in": critic["stats"]["tokens"]["input"],
        "critic_out": critic["stats"]["tokens"]["output"],
        "initial_in": initial["stats"]["tokens"]["input"],
        "terminal_in": draft["stats"]["tokens"]["input"],
        "peak_in": max(step["stats"]["tokens"]["input"] for step in research),
        "generations": len(research),
        "searches": sum(1 for step in steps[initial_i:draft_i]
                        if step.get("type") == "tool_call"
                        and step.get("tool_name") == "search"),
        "commits": sum(1 for step in steps[initial_i:draft_i]
                       if step.get("type") == "tool_call"
                       and step.get("tool_name") == "commit_context"),
    }
    for key, value in row.items():
        values[key].append(value)
for key, column in values.items():
    print(key, st.mean(column), st.median(column), min(column), max(column), sum(column))
PY
```

The compaction matrix used the original 30 trajectories for provider-visible
raw messages and the counterfactual outputs for the first-draft cutoff and
pre-compaction `returned_chars`:

```bash
uv run --no-project python - <<'PY'
import json, statistics as st
from pathlib import Path

root = Path("data/outputs/aus_agent_v2")
outputs = {}
for path in root.glob("*pre_repair_counterfactual.output.json"):
    data = json.loads(path.read_text())
    outputs[data["metadata"]["narrative_id"]] = data
trajectories = []
for path in root.glob("*.trajectory.json"):
    data = json.loads(path.read_text())
    if data.get("metadata", {}).get("run_id") == (
            "sol-aus-v2-research-first-dev30-20260806"):
        trajectories.append(data)
columns = {key: [] for key in (
    "searches", "commits", "rows", "staged_bytes", "search_payload",
    "retained_bytes", "retained_n", "tombstones", "commit_output",
    "commit_args"
)}
for trajectory in trajectories:
    output = outputs[trajectory["query_id"]]
    steps = output["trace"]["steps"]
    generations = [(i, step) for i, step in enumerate(steps)
                   if step.get("type") == "generation"]
    initial_i = next(i for i, step in generations
                     if (step.get("input") or {}).get("kind") == "initial")
    draft_i = next(
        i for i, step in generations
        if i >= initial_i
        and (step.get("output") or {}).get("text")
        and not ((step.get("output") or {}).get("tool_calls") or [])
    )
    trace_calls = [step for step in steps[initial_i:draft_i]
                   if step.get("type") == "tool_call"]
    staged_bytes = sum(
        int(row.get("returned_chars") or 0)
        for step in trace_calls if step.get("tool_name") == "search"
        for row in (step.get("output") or {}).get("results", [])
    )
    raw = trajectory["raw_messages"]
    boundary = next(
        i for i, message in enumerate(raw)
        if message.get("type") == "phase_boundary"
        and message.get("phase") in {
            "plan_critic_to_research", "coverage_plan_to_research"
        }
    )
    draft = next(
        i for i, message in enumerate(raw[boundary + 1:], boundary + 1)
        if message.get("type") == "message"
        and message.get("role") == "assistant"
    )
    segment = raw[boundary + 1:draft]
    calls = {message["call_id"]: message for message in segment
             if message.get("type") == "function_call"}
    row = {key: 0 for key in columns}
    row["staged_bytes"] = staged_bytes
    for message in segment:
        if message.get("type") != "function_call_output":
            continue
        call = calls.get(message.get("call_id"), {})
        name = call.get("name")
        raw_output = message.get("output") or ""
        if name == "search":
            row["searches"] += 1
            row["search_payload"] += len(raw_output.encode())
            payload = json.loads(raw_output.split("\n[context budget:", 1)[0])
            results = payload.get("results", [])
            row["rows"] += len(results)
            for result in results:
                if "text" in result:
                    row["retained_n"] += 1
                    row["retained_bytes"] += len(str(result["text"]).encode())
                else:
                    row["tombstones"] += 1
        elif name == "commit_context":
            row["commits"] += 1
            row["commit_output"] += len(raw_output.encode())
            row["commit_args"] += len((call.get("arguments") or "").encode())
    for key, value in row.items():
        columns[key].append(value)
for key, column in columns.items():
    print(key, sum(column), st.mean(column), st.median(column),
          min(column), max(column))
PY
```

Replay aggregates:

```bash
jq '.best_v2_direct_exposure.aggregate' \
  worklogs/assets/2026-08-06-aus-agent-v2-commit-validator-replay.json
jq '.aggregate' \
  worklogs/assets/2026-08-06-aus-agent-v2-anchor-strict-replay.json
jq '[.topic_matrix[] | (.outcomes.valid // 0)] as $v |
  {topics:($v|length), total_valid:($v|add),
   visible_under_two_per_row:([$v[]|if .>2 then 2 else . end]|add),
   omitted_under_two_per_row:(($v|add)-([$v[]|if .>2 then 2 else . end]|add)),
   topics_over_two:([$v[]|select(.>2)]|length), max:($v|max)}' \
  worklogs/assets/2026-08-06-aus-agent-v2-anchor-strict-replay.json
rg -n 'aggregate|rates cited_doc' \
  worklogs/assets/2026-08-06-finish-facts-pipeline-audit.log
```
