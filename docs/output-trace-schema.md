# Internal `output.json.trace` schema

The per-session `output.json` file is the canonical artifact for the Outputs
Viewer. It contains the organizer-facing TREC RAG fields plus one internal
top-level field:

```json
{
  "metadata": {},
  "references": [],
  "answer": [],
  "trace": {}
}
```

`trace` must be removed when producing the official
`rag_output_trec_rag_2026.jsonl` submission. The organizer-facing `metadata`,
`references`, and `answer` fields are otherwise unchanged.

`trajectory.json` has a different purpose. It is a strict compatibility
artifact for retrieval analysis and training and must follow
`data/sample-files/run_InfoSeekQA_1000_20260625T230857966818Z.json`. Timings,
tokens, and context state must never be added to trajectory items.

## Trace envelope

```json
{
  "schema_version": "trec-rag-trace/2",
  "query_id": "topic-id",
  "status": "completed",
  "started_at": "2026-07-16T19:10:26.315+10:00",
  "ended_at": "2026-07-16T19:12:40.010+10:00",
  "duration_ms": 133695,
  "metadata": {},
  "input": {
    "system_prompt": "...",
    "user_message": "...",
    "tools": []
  },
  "summary": {
    "tool_call_counts": {},
    "tool_call_counts_all": {},
    "retrieved_docids": [],
    "usage": {}
  },
  "steps": [],
  "output": {
    "references": [],
    "answer": []
  }
}
```

## Trace step

Every provider call is recorded as one `generation` step, even when the model
emits no visible reasoning text. Every executed tool call is a child of the
generation that issued it. Overlapping tool `t_start`/`t_end` intervals under
the same generation represent parallel execution.

The causal structure is:

```text
run input
└── generation turn 0
    ├── search
    └── search
└── generation turn 1
    ├── commit_context
    └── search
└── generation turn 2
    └── final model response
run output / final answer
```

A generation stores what entered and left the model call. The first generation
references the run-level input so the system prompt, user request, and tool
schemas are not duplicated. Later generations reference the provider tool-call
IDs whose results were appended to the same conversation.

```json
{
  "id": "step-0000",
  "parent_id": "run",
  "type": "generation",
  "turn": 0,
  "input": {"kind": "initial", "ref": "trace.input"},
  "output": {
    "text": null,
    "reasoning": ["..."],
    "tool_calls": [
      {
        "id": "tooluse-123",
        "name": "search",
        "arguments": {"query": "example"}
      }
    ],
    "stop_reason": "tool_use"
  },
  "t_start": "2026-07-16T19:10:26.315+10:00",
  "t_end": "2026-07-16T19:10:30.000+10:00",
  "stats": {
    "duration_ms": 3685,
    "tokens": {
      "input": 1200,
      "input_uncached": 1200,
      "cache_read": 0,
      "cache_write": 0,
      "output": 340,
      "total": 1540,
      "processed_input": 1200,
      "processed": 1540
    },
    "cumulative_tokens": {
      "input": 82410,
      "output": 4200,
      "total": 86610,
      "processed": 86610
    }
  }
}
```

The corresponding executed tool step points to that real generation node and
keeps the provider tool-call ID:

```json
{
  "id": "step-0004",
  "parent_id": "step-0000",
  "type": "tool_call",
  "tool_name": "search",
  "tool_call_id": "tooluse-123",
  "arguments": {"query": "example"},
  "output": "...",
  "failed": false,
  "t_start": "2026-07-16T19:10:30.000+10:00",
  "t_end": "2026-07-16T19:10:30.420+10:00",
  "turn": 1,
  "stats": {
    "duration_ms": 420,
    "returned_documents": 10,
    "context_tokens": 82410,
    "peak_context_tokens": 82410,
    "context_budget_tokens": 500000,
    "elapsed_ms": 252000
  },
  "context": {}
}
```

The final answer is not repeated as an `output_text` rich step. The final model
response remains the last generation span; the normalized cited answer is
stored once at `trace.output` and once in the organizer-required top-level
`output.json.answer`. The strict `trajectory.json.result` still contains its
required `output_text` item.

`context_tokens` is window occupancy for the latest generation and is compared
with the context budget. It is not a run usage total. Each generation's
`stats.tokens` records the tokens for that model call. Every generation and
subsequent tool step receives `stats.cumulative_tokens`, representing token
throughput processed so far in the run. The trace summary stores the final
cumulative totals.

For Bedrock prompt caching, logical input is
`inputTokens + cacheReadInputTokens + cacheWriteInputTokens`. Processed input
excludes cache reads but includes cache writes. Cache categories remain
separate so later cost calculations can apply the provider's different rates.

## Staged and committed context

Retrieval results are initially staged. They are available in full for the
agent's next decision turn, but they are not retained indefinitely.

```json
{
  "context": {
    "staged": ["doc-a", "doc-b", "doc-c"],
    "committed": ["doc-a"],
    "rejected": [
      {"docid": "doc-b", "reason": "not relevant"},
      {"docid": "doc-c"}
    ]
  }
}
```

The agent explicitly calls the local `commit_context` control tool. Selected
documents remain in durable full-text provider context. Unselected documents
lose their full text in provider history and are replaced by compact
tombstones. The trace stores only docids, ranks/scores, truncation metadata,
and context decisions; the Outputs Viewer retrieves document text through its
document API.

The default research-context budget is 500,000 tokens. Usage is the current
generation's provider-reported input size, which already includes retained
conversation context; generation input counts are never summed across turns.
The trace also records the peak observed input size. Action feedback should end
with a compact status line:

```text
[context budget: 82,410 / 500,000 tokens (16.5%) · elapsed: 4m 12s]
```

The same values must be recorded structurally in the step's `stats`.

Search output metadata also records `truncated`, `original_chars`,
`returned_chars`, and `budget_tokens_per_result`, but never the text itself.
The default per-result budget is 4,096 approximate tokens, implemented as
`tokens × 5` characters with truncation at the last line break before the
boundary.
