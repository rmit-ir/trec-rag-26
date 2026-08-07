# Architecture diagram: recommended-system focus

Date: 2026-08-06

## Problem

The first branch-aware diagram fixed a factual problem—candidate stages no
longer appeared sequentially after the verified system—but made all four
variants equally prominent. A reader opening `#aus_agent_v2` still had to parse
the complete experimental surface before understanding the recommended
submission system.

## Change

The `aus_agent_v2` drill-in now opens on the default variant only, renamed to
**Verified research-first control** to match the recommendation used in the
handoff. It explains the control flow in three numbered phases:

1. **Understand the request once:** original request → prose coverage plan →
   request-only atomic obligation scout → deterministic request-form gate.
2. **One evidence-owning model conversation:** semantic+keyword search with
   adjacent pages → commit up to ten selected pages → repeat while evidence
   gaps remain → write final cited prose directly, with no editor or second
   writer.
3. **Package deterministically:** map document ids to organizer citation
   indices → save the strict trajectory and rich organizer output.

The full experiment surface remains available through a visible **Compare 3
candidate variants** button. That switches to the existing four-lane comparison
view; returning to the overview resets the drill-in to the recommended system.

The focused page keeps exact prompts, tools, and code one click away in the
detail drawer. It also shows the graded status (`dev30 0.704159`) and exact
entrypoint (`systems/aus_agent_v2/pipeline.py::run_one`) above the diagram.

## Layout verification

The generated JavaScript passed `node --check`. The focused architecture was
rendered in headless Chromium at 1366×900 and inspected at original resolution.
All labels stay within their cards, phase headings have clear whitespace, no
connector crosses explanatory text, and the entire recommended path fits in a
single laptop-width viewport without horizontal scrolling.

Temporary browser libraries, screenshots, and logs were created only under
`/tmp`; the Playwright cache was outside the repository. None are Git inputs,
and all are removed after verification.

## Automated checks

- Focused architecture tests: 16 passed.
- Full hermetic suite: 1,812 passed, 9 live tests deselected; no skips.
- Architecture freshness: passed after regeneration.
- Model/retrieval/grading API calls: none; cost $0.
