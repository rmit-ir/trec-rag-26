"""Playwright smoke test for the outputs viewer.

Checks BOTH kinds of session render:
  * aus_agent   — a real run WITH a trajectory (timeline, step tree, answer)
  * baseline    — an imported organizer baseline with NO trajectory
"""
import json
import sys
import urllib.request

from playwright.sync_api import sync_playwright

BASE = "http://localhost:3618"
failures = []
notes = []


def check(name, cond, detail=""):
    (notes if cond else failures).append(f"{'PASS' if cond else 'FAIL'} {name} {detail}".rstrip())


def api(path):
    with urllib.request.urlopen(BASE + path) as r:
        return json.load(r)


def main():
    idx = api("/api/outputs")
    systems = {s["system"]: s["sessionCount"] for s in idx["systems"]}
    check("index lists baseline system", "baseline" in systems, str(systems))
    check("baseline has 238 sessions", systems.get("baseline") == 238, str(systems.get("baseline")))
    check("aus_agent still listed", systems.get("aus_agent", 0) > 0, str(systems.get("aus_agent")))

    baseline = [s for s in idx["sessions"] if s["system"] == "baseline"]
    runs = sorted({s["runId"] for s in baseline})
    check("two baseline run_ids", len(runs) == 2, str(runs))
    check("baseline sessions report no trace", all(not s["hasTrace"] for s in baseline))
    check("baseline carries narrativeId", all(s.get("narrativeId") for s in baseline))
    # topic order within each run (the tie-break under equal timestamps)
    for run in runs:
        ids = [int(s["narrativeId"].rsplit("-", 1)[1]) for s in baseline if s["runId"] == run]
        check(f"topic order for {run}", ids == sorted(ids), f"first 5: {ids[:5]}")

    agent = [s for s in idx["sessions"] if s["system"] == "aus_agent" and s["hasTrace"]]
    check("aus_agent session with a trace exists", len(agent) > 0)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1600, "height": 1100})
        # IdentityGate blocks the whole app until a username exists.
        ctx.add_init_script(
            "window.localStorage.setItem('outputs_viewer_user','playwrightsmoke')"
        )
        page = ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        bad = []
        page.on("response", lambda r: bad.append(f"{r.status} {r.url}") if r.status >= 400 else None)

        # ---- systems list -------------------------------------------------
        page.goto(f"{BASE}/systems?system=baseline", wait_until="networkidle")
        page.wait_for_selector("text=rag2026-0", timeout=30000)
        header = page.locator("text=/baseline — .* sessions?/").first.inner_text()
        check("baseline list header", "238" in header, header)
        first_row = page.locator("a[href*='/session/baseline/']").first
        row_text = first_row.inner_text()
        check("row shows narrative id first", "rag2026-0 ·" in row_text, row_text.replace("\n", " | "))
        check("row flags answer-only", "answer only (no trace)" in row_text, row_text.replace("\n", " | "))
        page.screenshot(path="/tmp/shot-systems-baseline.png", full_page=False)

        # run filter present with the two organizer run ids
        page.get_by_label("Run").click()
        opts = page.locator("li[role='option']").all_inner_texts()
        check("run filter offers both baselines", all(r in opts for r in runs), str(opts))
        page.keyboard.press("Escape")

        # ---- a BASELINE session -------------------------------------------
        sess = next(s for s in baseline if s["narrativeId"] == "rag2026-0")
        url = f"{BASE}/session/baseline/{sess['sessionId'].replace('+', '%2B')}"
        page.goto(url, wait_until="networkidle")
        page.wait_for_selector("text=Final answer", timeout=30000)
        body = page.locator("body").inner_text()
        check("baseline: no-trace chip", "no output trace" in body)
        check("baseline: neutral timeline message", "No trace for this session" in body, )
        check("baseline: no red invalid-trace error", "Invalid trace" not in body)
        check("baseline: no dead Input node", "System prompt, user request" not in body)
        check("baseline: run chip", "run: " in body)
        check("baseline: task description card", "TASK DESCRIPTION" in body.upper())
        wc = page.locator("text=/^\\d+ \\/ 1024 words$/").first.inner_text()
        check("baseline: answer word count rendered", int(wc.split()[0]) > 200, wc)
        # citation chip opens the doc sidebar AND the cited document is readable
        page.locator("text=/^\\[1\\]/").first.click()
        page.wait_for_selector("text=/source: (dense|sparse|pyserini)/", timeout=30000)
        side = page.locator("text=/source: (dense|sparse|pyserini)/").first
        check("baseline: citation resolves to a document", "source: " in side.inner_text(),
              side.inner_text())
        doc_text = page.locator("body").inner_text()
        check("baseline: doc sidebar shows text, not an error",
              "not found on any backend" not in doc_text and "Failed to" not in doc_text)
        page.screenshot(path="/tmp/shot-session-baseline.png", full_page=False)

        # sentences + raw tabs
        page.get_by_role("tab", name="sentences").click()
        page.wait_for_selector("th:has-text('Citations')", timeout=10000)
        rows = page.locator("table tbody tr").count()
        check("baseline: sentences table populated", rows > 5, f"{rows} rows")
        page.get_by_role("tab", name="config").click()
        page.wait_for_timeout(500)
        check("baseline: config shows submission fields",
              "narrative_id" in page.locator("body").inner_text())

        # ---- an AGENT session (regression: trace rendering still works) ----
        a = agent[0]
        page.goto(f"{BASE}/session/{a['system']}/{a['sessionId'].replace('+', '%2B')}",
                  wait_until="networkidle")
        page.wait_for_selector("text=Final answer", timeout=30000)
        body = page.locator("body").inner_text()
        check("agent: status chip", "status: " in body, )
        check("agent: model chip", "model: " in body)
        check("agent: steps chip non-zero", "steps: 0" not in body)
        check("agent: timeline legend rendered", "generation" in body.lower())
        check("agent: Input node present", "System prompt, user request" in body)
        check("agent: no no-trace message", "No trace for this session" not in body)
        check("agent: retrieved docids chip", "retrieved docids" in body)
        page.screenshot(path="/tmp/shot-session-agent.png", full_page=False)

        # click a trace step -> detail pane
        page.locator("text=/^Turn 1 · generation/").first.click()
        page.wait_for_timeout(800)
        check("agent: step detail opens", "Step " in page.locator("body").inner_text())

        # agent citation -> doc sidebar (same backend chain as the baseline)
        page.locator("div[role='button'] p", has_text="Answer").first.click()
        page.wait_for_selector("text=/\\d+ \\/ 1024 words/", timeout=15000)
        page.locator("text=/^\\[1\\]/").first.click()
        page.wait_for_selector("text=/source: (dense|sparse|pyserini)/", timeout=30000)
        check("agent: citation resolves to a document",
              "not found on any backend" not in page.locator("body").inner_text())

        check("no page/console errors", not errors, "; ".join(errors[:3]) + " || " + "; ".join(bad[:5]))
        browser.close()

    for n in notes:
        print(n)
    for f in failures:
        print(f)
    print(f"\n{len(notes)} passed, {len(failures)} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
