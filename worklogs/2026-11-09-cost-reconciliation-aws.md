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

## Still open

Azure usage for `trec-rag-2026-llm-resource` on Aug 8 UTC by meter (confirms provider,
rates, tier, and whether the 174 failed brief attempts were billed); AWS account behind
facet_rag; management-account view for other member accounts.

## Documentation changes

`RMIT-ADM+S scores/SCORES.md`: split tokens and cost tables; added As-billed and
Azure-equivalent cost columns, rate-card section (with the Bedrock 10% markup and
cache-write billing), evidence and limits; corrected the owa-glm5 and facetrag costs and the
related conclusion bullets.
