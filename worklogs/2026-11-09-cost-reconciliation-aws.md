# Reconciling per-topic generation cost against AWS billing

Date: 2026-11-09. Analysis and documentation only; no application code changed.
Supersedes the placeholder-rate costs in `worklogs/2026-11-04-sol-cost-recovery.md`
(those token totals remain correct and are reused here).

## Questions and sources

Which provider ran each submitted system, when, and what did it really cost?

- Provider: Kun's `.env` on Sunfyre (`OPENAI_BASE_URL=https://bedrock-mantle.us-east-1.api.aws/openai/v1`,
  `OPENAI_MODEL_ID=openai.gpt-5.6-sol`); production logs
  `tasks/task-comparison/logs/sol-aus-{default,v2-research-first}-test119-20260807.log`
  (1,092 and 1,410 POSTs to `bedrock-mantle.us-east-1.api.aws`, none to Azure);
  trace `run_desc` model ids (`openai.gpt-5.6-sol` Bedrock-style vs `gpt-5.6-sol` /
  `gpt-5.6-luna` Azure-style); this repo's `.env` (`OPENAI_BASE_URL` =
  `trec-rag-2026-llm-resource.openai.azure.com`) and worklogs
  `2026-08-08-test119-brief-revise-{base,hybrid}-submission.md` (Azure key, `westus` quota 429s).
- Dates: `trace.started_at/ended_at` of all 119 topics per run.
- Billing: AWS Cost Explorer usage-type breakdown, pasted in
  [assets/2026-11-09-aws-cost-explorer-usage-types.md](assets/2026-11-09-aws-cost-explorer-usage-types.md).

## Who ran what (git/file ownership)

Sunfyre output files of `brief-revise-hybrid-test119-20260808` are owned by user
`e103037` (Oleg), not Kun (`e128356`); the Aug 8 worklogs are Oleg's commits. Kun ran
the two Sol aus runs.

## Run windows (+10:00 local, UTC)

| Run | Provider | UTC first start to last completion |
|---|---|---|
| sol-default | Bedrock (confirmed) | Aug 7 04:29 to 05:07 |
| sol-research-first | Bedrock (confirmed) | Aug 7 04:29 to 05:19 |
| brief-base | Azure (inferred) | Aug 8 13:25 to 18:19 |
| brief-hybrid | Azure (inferred) | Aug 8 13:25 to 18:50 |
| facets-agent | Azure (inferred) | Aug 8 13:25 to 15:01 |
| facet-rag | Bedrock per worklog | Aug 8 13:38 to 16:25 |
| open-weight glm5 | Bedrock | Aug 9 23:46 to Aug 10 03:08 |

Azure inference is supported by AWS: Sol and Luna (Bedrock Edition) show no spend on
Aug 8 or Aug 9, so brief/facets did not run through Bedrock. Failed attempts: brief-base
99, brief-hybrid 75 (429 rate limits; may or may not have been billed by Azure).

## Findings from AWS

1. Bedrock Sol rates (cost / quantity, Aug 7): input $5.50, cache read $0.55,
   cache write (30m) $6.88, output $33.00 per 1M. Versus OpenAI list (5.00 / 0.50 / 30.00)
   this is a **10% Bedrock markup**; the cache-write rate is 1.25x input (5.50 x 1.25).
2. Bedrock bills the traces' "uncached input" as cache writes (61.65M tokens billed
   at $6.88 vs 0.087M as plain input), so the runs' dominant input cost is 38% above the
   list input rate.
3. Bedrock Luna: 0.22 / 0.022 / 1.32 (and cache write 0.275) = 1.10x of 0.20 / 0.02 / 1.20.
   The Luna price cut predates Aug 5, so the 2026-07-19 table in
   `2026-07-19-viewer-cost-tag-and-mobile.md` (1.00 / 0.10 / 6.00) is stale for Luna.
4. GLM-5 (APS2): $1.20 input, $3.20 output per 1M.

## Reconciliation of the Sol runs with the Aug 7 bill

| Quantity | Traces (both runs) | AWS Aug 7 |
|---|---:|---:|
| uncached input (= cache writes) | 61,016,648 | 61,650,100 |
| cached input (cache reads) | 68,030,794 | 68,737,255 |
| output | 1,972,027 | 2,131,416 |

Rate-card cost of the traces on Bedrock rates: sol-default $186.35, sol-research-first
$335.94, sum **$522.29 = 98.0% of the $532.77** day total. The $10.48 remainder is
preflights and unreturned usage from failed requests (sol-default failed attempts:
179,386 processed tokens, about $1.2 at the cache-write rate). Computation:
[assets/2026-11-09-cost-recompute.py](assets/2026-11-09-cost-recompute.py), output
`assets/2026-11-09-cost-recompute.out.txt`.

## Result matrix (USD per topic, 119 topics)

| Run | Provider | As billed | Azure-equivalent (OpenAI list, no cache-write fee) | Old placeholder ($5/M) |
|---|---|---:|---:|---:|
| brief-hybrid | Azure (inferred) | 1.853 (est.) | 1.853 | 1.503 |
| brief-base | Azure (inferred) | 2.033 (est.) | 2.033 | 1.638 |
| sol-default | Bedrock | **1.566** | 1.195 | 0.949 |
| sol-research-first | Bedrock | **2.823** | 2.152 | 1.705 |
| facets (Luna) | Azure (inferred) | 0.036 (est., Luna 0.20/0.02/1.20) | 0.036 | 0.724 |
| owa-glm5 | Bedrock | 0.517 (1.20/3.20 x traced tokens; run about $61.5) | n/a | 0.163 reported |
| facetrag | unreconciled | about 0.09-0.14 | n/a | 0.178 reported |

Research-first is about 80% more expensive than sol-default in every column
(2.823/1.566 = 1.80; 2.152/1.195 = 1.80).

Judgment: Sol rows derived from billed AWS usage (match 98%); Azure rows are rate-card
estimates, **unverified** against an Azure invoice. Azure-equivalent assumes Global
Standard = OpenAI list and no cache-write charge.

## Discrepancies found

- **owa-glm5 reported $0.163/topic is about 3x too low.** AWS bills GLM-5 at 1.20/3.20;
  415,080 input + 5,899 output tokens/topic = $0.517 ($61.5 for 119). Aug 10 shows
  $53.16 for GLM-5 (most of the run, which starts 14 minutes before UTC midnight); Aug 9
  GLM-5 $54.1 is largely earlier open-weight bake-off spend.
- **facetrag $0.178 does not match billing.** Models: gpt-oss-120b + qwen3-next-80b.
  The account shows $1.80 gpt-oss-120b on Aug 8 and no Qwen3-Next line, against about
  49M input / 5.9M output tokens for the run. It was likely billed in a different
  account. At gpt-oss ($0.155 in / $0.618 out) to Qwen3-235B ($0.227 / $0.907) rates
  the run costs about $0.09-0.14/topic.
- Aug 10 Sol spend ($45.96) is not test generation (probably judging/ensemble work);
  Aug 5-6 Sol spend ($1,092.97) is development (report cites $1,096.72 for research-first).
- CloudWatch `AWS/Bedrock` is empty (invocation logging off), so hourly isolation of
  preflights is impossible; 98% coverage makes it unnecessary.

## Superseded by the Azure section below

The Azure-side rows in the result matrix above were provisional; see "Part 2: Azure billing" for the final figures.

## Still open (as of Part 1)

Azure usage for `trec-rag-2026-llm-resource` on Aug 8 UTC by meter (confirms provider,
rates, tier, and whether the 174 failed brief attempts were billed); AWS account behind
facet_rag; management-account view for other member accounts.

## Documentation changes

`RMIT-ADM+S scores/SCORES.md`: split tokens and cost tables; added As-billed and
Azure-equivalent cost columns, rate-card section (with the Bedrock 10% markup and
cache-write billing), evidence and limits; corrected the owa-glm5 and facetrag costs and the
related conclusion bullets.

# Part 2: Azure billing, run timing and final figures (same day)

## Azure evidence

- Resource `trec-rag-2026-llm-resource`: subscription `SUB-RMIT-RACE-NPE`
  (e7991b59-570b-4e9a-af5e-209603ce54e2), resource group `rg-kun-ran` (Kun's), westus,
  kind AIServices. Cost Management in the Azure Copilot tool only reached back 92 days
  (earliest Aug 9), so the Aug 8 figures were exported from the portal Cost analysis
  (view InvoiceDetails, Aug 8-9, USD): raw rows in
  [assets/2026-11-09-azure-cost-analysis-aug8-9.csv](assets/2026-11-09-azure-cost-analysis-aug8-9.csv)
  (columns UsageDate, Meter, PartNumber, CostUSD, Cost in AUD; no quantity column; constant
  FX 1.444148 AUD per USD).
- Meters are `5.6 {sol,luna,terra} ShortCo {Inp,Cd Inp,Opt} Std DZ 1M Tokens`: **Data Zone
  Standard, short context**, with a cached-input meter and **no cache-write meter**.
- Aug 8 UTC, USD: Sol input 821.71, cached 84.48, output 169.32 (total 1,075.51); Luna input
  4.02, cached 0.20, output 1.73 (5.95); Terra 7.30 (not ours: no submitted run used Terra).
  Aug 9: Sol 1.12, Luna 1.28, Terra 5.38. Aug 8-9 total $1,096.53.
- Azure Monitor (resource totals, Aug 8 12:00-24:00 UTC): 252,923,609 input and 4,565,211
  output tokens; activity only 13:00-19:00 UTC (hourly table in the Azure Copilot reply:
  13:00 27.5M input ... 18:00 24.7M, zero from 19:00), matching the run windows. Per-deployment
  and status-code splits were not retrievable through the Copilot tool.
- Retail Prices API probe ([script](assets/2026-11-09-azure-retail-prices-probe.py), output
  `assets/2026-11-09-azure-retail-prices-probe.out.txt`): Luna DZ westus 0.22 / 0.022 / 1.32
  effective 2026-08-01 (in force on Aug 8). Sol DZ rows are all effective 2026-09-01
  (4.40 / 0.44 / 22.00 westus), i.e. after the runs; Azure DZ = 1.1x Global (4.40 vs 4.00).
  The pricing page and a Copilot quote ($4.40/$0.44/$22) therefore describe post-Sept-1
  prices. Sol Aug 8 DZ rates are **inferred** as 5.50 / 0.55 / 33.00 (1.1x the pre-cut
  Global 5 / 0.5 / 30; identical to Bedrock's Sol rates).
- Repo rate cards (`src/ragrun/prices/`, Aug 5, operator-supplied): Bedrock Sol 5.50 / 33.00
  (matches the AWS bill); Luna card says 1.10 / 6.60 but AWS billed 0.22 / 1.32 from Aug 5,
  so that Luna file is stale. No Azure rate card exists anywhere in the repo or on Sunfyre.

## Run timing (UTC), from trace started_at/ended_at, file names and mtimes

facets-agent Aug 8 13:25 to 15:01; facet-rag Aug 8 13:38 to 16:25 (no earlier full test run
of either exists; earlier runs under other run ids are dev runs); one-topic preflights
Aug 8 13:01 to 13:37; brief-base 13:25 to 18:19 and brief-hybrid 13:25 to 18:50 (with 3
launches and retries); sol runs Aug 7 04:29 to 05:19; owa-glm5 Aug 9 23:46 to Aug 10 03:08.

## Final figures: evidence strength

| Evidence | Strength |
|---|---|
| Bedrock Sol rates and quantities from AWS usage types; traces match bill at 98% | A, billed |
| Sol aus runs on Bedrock (request logs, `.env`) | A |
| GLM-5 rates (1.20 / 3.20), Aug 10 GLM-5 bill $53.16 consistent with run | A rates, B attribution |
| Azure Aug 8 bill by meter; DZ tier; no cache-write meter | A amounts, C attribution to our runs |
| Luna DZ rates (retail API, effective Aug 1) | A |
| Brief/facets on Azure (config, model ids, Monitor window, no AWS Sol/Luna Aug 8) | B+ |
| Sol DZ rates on Aug 8 = 5.50 / 0.55 / 33.00 | B-, inferred |
| Azure spend about 2.1x successful-attempt cost (retries billed) | C, other callers not excluded |
| facetrag cost (no billing match) | D |

## Final per-topic cost (USD, 119 successful attempts)

| Run | Provider | Cost | Evidence | Same rate card (Azure DZ) |
|---|---|---:|---|---:|
| brief-hybrid | Azure | 2.038 | estimated | 2.038 |
| brief-base | Azure | 2.236 | estimated | 2.236 |
| sol-default | Bedrock | 1.566 | verified | 1.315 |
| sol-research-first | Bedrock | 2.823 | verified | 2.367 |
| facets | Azure | 0.040 | estimated, Luna rate read | 0.040 |
| owa-glm5 | Bedrock | 0.517 | estimated, rate from bill | n/a |
| facetrag | unreconciled | 0.106 (0.094-0.117) | weak | n/a |

Computation: `assets/2026-11-09-cost-recompute.py` (output `.out.txt`). Azure successful-attempt
cost of the two brief runs at DZ rates $508.64 against $1,075.51 billed Sol (2.11x); facets
$4.75 against $5.95 billed Luna. facetrag bounds use repo rate cards (gpt-oss-120b 0.1545 / 0.618;
qwen3-next-80b 0.14 / 1.2) on 411,653 input and 49,727 output tokens per topic.

## Open items

Azure invoice unit price for `5.6 sol ShortCo Inp Std DZ` on Aug 8 (would confirm 5.50);
whether other callers used the Azure resource on Aug 8; the AWS account behind facet_rag
(its Bedrock usage is not in account 507363615341).

## Report

`../trec-rag-26-report/tables/submissions.tex`: only the `$/topic` column updated to the
figures above (report repo has other uncommitted edits, not committed from here). Its caption
and `sections/submitted-runs.tex` still describe the old $5/M placeholder and need rewording.

# Part 3: retrieval k and adjacent-page usage in the submitted runs (same day)

Source: completed topics of each submitted run in the trace files on Sunfyre
(`data/outputs/<system>/*.output.json`, `trace.steps` tool calls; the two Sol runs read from
Kun's checkout, the rest from the shared dir). Sol counts include one preflight file each
(120 vs 119 topics, under 1% effect).

## k requested per `search` call (tool schema: "Number of passages to return (default 10)")

`--k` only applies when the model omits `k` (`arguments.get("k", default_k)` in
`agent_harness/tools/search.py`).

| Run | searches | k distribution (top) | calls with no k key |
|---|---:|---|---:|
| sol-default (configured --k 20) | 2,863 | 10: 94%, 8: 4%, 12: 1%, 15: 1% | 0 |
| sol-research-first (configured --k 20) | 3,764 | 10: 87%, 8: 10%, 15: 1%, 20: 1% | 0 |
| brief-base (--k 10) | 3,462 | 10: 84%, 8: 11%, 6: 2%, 20: 2% | 0 |
| brief-hybrid (--k 10) | 2,862 | 10: 88%, 8: 6%, 20: 2%, 6: 1% | 0 |
| facets (hybrid default 15) | 1,827 | 10: 35%, 15: 29%, 12: 15%, 8: 12% | 0 |
| facetrag (fixed by pipeline code) | 4,484 | 10: 69%, 15: 31% (hybrid 15, others 10) | 0 |
| owa-glm5 (--k 10) | 1,540 | explicit 10: 8% | 1,392 (90%): default 10 applied |

Per engine in facets: hybrid requested 15 in 526 of 539 calls. Judgment: modal values above
are what the table reports.

## Adjacent-page expansion

Mechanism: for the top 5 paginated hits of each search, fetch the previous and next page
(`brief_revise_agent/adjacent_pages.py`, ported from `aus_agent_v2/search.py`; no model call).
Introduced in aus_agent_v2 (Kun, 2026-08-06) and in brief_revise_agent as "round B"
(Oleg, 2026-08-07, commit 6ecfd50, with the harness `search_result_augment` hook b9d7c0b);
owa-glm5 inherits brief_revise's default (on); no submitted run passed `--disable-adjacent-pages`.
facetrag has no such mechanism (fixed pipeline), facets and sol-default never enabled it.

Measured from traces (extra staged pages beyond the search results and explicit `get_documents`;
for sol-research-first, results returned beyond k):

| Run | searches with extra pages | extra pages / topic | committed items from extra pages / topic |
|---|---:|---:|---:|
| sol-research-first | 98% | 138.1 | 10.4 of 38.7 (27%) |
| brief-base | 87% | 105.3 | 7.0 of 35.2 (20%) |
| brief-hybrid | 89% | 89.2 | 6.0 of 33.2 (18%) |
| owa-glm5 | 93% | 49.8 | 1.6 of 24.9 (6%) |
| sol-default, facets | 0% | 0 | 0 |

Topics with at least one committed extra page: brief-base 119/119, brief-hybrid 116/119,
owa-glm5 86/119, sol-research-first 120/120 files.

## Part 4: support-call costs from Sunfyre logs

Brief-analyst, reviewer and scout calls in brief_revise_agent and
open_weight_agent run on separate providers and are not in trace tokens; only
`brief.get_requirements: usage=`, `review.hook: usage=`, `scout.get_scout_additions:
usage=` log lines record them. `worklogs/assets/2026-11-09-support-call-costs.py`
sums those lines per slot between `starting:` and `finished status=completed`
(final completed attempt only; 119/119 slots matched per run), adds completed-trace
tokens, and prices at Azure DZ Sol 5.50/0.55/33.00 (brief) or GLM-5 1.20/3.20 (owa).

| Run | Trace $/topic | Support $/topic | Total |
| --- | ---: | ---: | ---: |
| brief-base | 2.236 | 0.120 | 2.356 |
| brief-hybrid | 2.038 | 0.117 | 2.156 |
| owa-glm5 | 0.517 | 0.007 | 0.524 |

Support tokens (in/out): base 714,218/314,269; hybrid 695,299/307,617; owa
567,253/54,322. Completeness check (`/tmp/chk.py` on Sunfyre, all completed 119-topic
traces): trace `summary.tokens.total` equals the sum of step totals for every run;
sol-research-first has 238 auxiliary (critic/scout) steps = 2 per topic, so its
plan/critic/scout cost is inside the 2.823 figure. facetrag plan/draft/check/format
stages carry stats; 2 of ~4,600 generation steps carried none (negligible).
Earlier +0.18 scaled estimate was too high; exact is about +0.12.
