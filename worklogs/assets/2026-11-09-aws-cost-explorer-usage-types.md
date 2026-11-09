# AWS Cost Explorer evidence, pasted from the AWS assistant (2026-11-09)

Account 507363615341 (member of org o-2vvrr6u1ue; payer 538238080661), Cost Explorer,
daily granularity. Transcribed verbatim from the assistant's reply; its "Implied $/1M"
column has typos (cache_read shown as $5.50 for Sol; real value cost/quantity = $0.55).

## Screenshot summary (Cost Explorer "Cost and usage breakdown", 33 rows, 3 visible)

| Service | Total | Aug-05 | Aug-06 | Aug-07 | Aug-08 | Aug-09 | Aug-10 | Aug-11 | Aug-12 |
|---|---|---|---|---|---|---|---|---|---|
| Total costs | 1,888.53 | 214.58 | 933.98 | 539.29 | 5.41 | 86.57 | 102.36 | 3.16 | 3.18 |
| OpenAI GPT-5.6 Sol (Bedrock Edition) | 1,671.71 | 182.52 | 910.45 | 532.77 | - | - | 45.96 | - | - |
| Bedrock | 142.13 | 1.01 | 1.29 | 2.59 | 1.80 | 82.29 | 53.16 | - | - |
| OpenAI GPT-5.6 Luna (Bedrock Edition) | 27.28 | 9.28 | 17.48 | 0.52 | - | - | 0.00 | - | - |

## Sol (Bedrock Edition), usage types (1M-token units)

Aug 7: cache_read 68.737255 = $37.8055; cache_write_30m 61.6501 = $424.1527;
input 0.087261 = $0.4799; output 2.131416 = $70.3367; total $532.77.
Aug 8, Aug 9: no usage.
Aug 10: cache_write_30m 4.573387 = $31.4649; input 0.00215 = $0.0118;
output 0.439015 = $14.4875; total $45.96.

Derived rates: input 5.50, cache read 0.55, cache write 6.88, output 33.00.

## Luna (Bedrock Edition), usage types (1M-token units; USE1-MP unless noted)

Aug 5: cache_read 22.659644 = $0.4985; cache_write 21.906931 = $6.0244;
input 0.029703 = $0.0065; output 2.004074 = $2.6454;
USW2-MP: cache_read 0.262795 = $0.0058; cache_write 0.276959 = $0.0762;
input 0.032526 = $0.0072; output 0.011098 = $0.0146; total $9.28.
Aug 6: cache_read 51.857841 = $1.1409; cache_write 45.196554 = $12.4291;
input 0.106285 = $0.0234; output 2.94695 = $3.8900; total $17.48.
Aug 7: cache_write 1.224827 = $0.3368; input 0.001155 = $0.0003;
output 0.136104 = $0.1797; total $0.52.
Derived rates: input ~0.22, cache read 0.022, cache write 0.275, output 1.32.

## Generic "Bedrock" service line (1K-token units)

Aug 8 ($1.80): APS2 gpt-oss-120b input 3,578.668 = $0.5529; output 2,011.102 = $1.2429.
Aug 9 ($82.29): APS2 zai.glm-5 input 43,240.994 = $51.8892, output 693.066 = $2.2178;
APS2 Qwen3-235B-A22B input 31,644.246 = $7.1706, output 109.546 = $0.0993;
USE1 Kimi-K2-Thinking input 9,111.963 = $5.4672, output 290.865 = $0.7272;
APS2 deepseek.v3.2 input 9,168.986 = $5.8682, output 102.523 = $0.1958;
APS2 gpt-oss-120b input 26,921.198 = $4.1593, output 892.418 = $0.5515;
APS2 moonshotai.kimi-k2.5 input 5,892.465 = $3.6533, output 87.45 = $0.2702;
USE1 Llama3-3-70B input 27.354 = $0.0197, output 0.213 = $0.0002.
Aug 10 ($53.16): APS2 zai.glm-5 input 42,257.125 = $50.7086, output 764.897 = $2.4477.

## CloudWatch / account

AWS/Bedrock namespace empty in us-east-1 (model invocation logging not enabled;
not retroactive). Other member accounts not visible from this account.

## Prompt given to the AWS assistant

Four parts: (1) Sol and Luna usage-type breakdown, Aug 5-10, with quantity and cost;
(2) generic "Bedrock" line by usage type/model for Aug 8-10; (3) CloudWatch hourly
InputTokenCount/OutputTokenCount for openai.gpt-5.6-sol on Aug 6-7; (4) account and
linked-account context. Region us-east-1, UTC.
