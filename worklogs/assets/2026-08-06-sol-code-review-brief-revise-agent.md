**SHIP WITH FIXES**

1. **Unbounded, insufficiently validated model output is promoted into the system prompt** — `brief.py:88-111`, `brief.py:142-149`  
   `str(row.get(...))` turns malformed values such as `null`, lists, or objects into accepted text (`"None"`, `"['x']"`). IDs and all text fields are also length-unbounded and may contain newlines/instructions. Because these values are appended to the **system prompt**, a bad or prompt-injected brief can inflate the next call’s context or elevate query-derived instructions to system priority. Validate fields as strings, assign canonical IDs locally, normalize line breaks, cap each field and the total appendix length.

2. **The two extra paid calls are completely absent from run usage/cost accounting** — `agent.py:184-194`  
   `one_shot` stores usage on each auxiliary provider, but neither brief nor review usage is recorded in the trajectory or returned artifacts. Pilot cost/latency measurements will therefore silently report only the main harness call stream while billing for up to two additional calls per topic. Capture `_last_usage`, latency, success/failure, and model ID for both stages in saved run metadata or a sidecar before spending on live topics.

3. **Malformed reviewer output is indistinguishable from a valid “no issues” decision** — `review.py:128-153`, `review.py:221-226`  
   `_parse_issues` maps invalid JSON/schema to `[]`. Thus malformed output is treated as reviewer approval when there are no deterministic uncited sentences; when uncited sentences exist, it still triggers revision rather than following the documented “review failure → accept” policy. Return a parse-success indicator separately from the issue list and explicitly apply the chosen fallback. Also reject non-string fields instead of coercing `null` to `"None"`.

The harness integration itself is correct: `candidate_sentences`, `ledger.committed_ids`, `call_history`, `committed_call_id`, and the single-argument `pre_final_hook` closure all match the supplied contract.