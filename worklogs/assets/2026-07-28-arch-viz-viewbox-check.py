from playwright.sync_api import sync_playwright

URL = "file:///home/el7/E103037/repos/trec-rag-26/docs/architecture.html"
OUT = "/home/el7/E103037/.claude/jobs/7bfa2f71/tmp"

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1250, "height": 700})

    # 1. fresh drill-in via fragment
    pg.goto(URL + "#aus_agent")
    pg.wait_for_timeout(400)
    vb = pg.eval_on_selector("#stage", "e => e.getAttribute('viewBox')")
    n = pg.eval_on_selector_all("#stage g.stage", "els => els.length")
    print("drill-in viewBox:", vb, "| stages:", n)
    pg.screenshot(path=f"{OUT}/aus_agent_1250x700.png")

    # 2. navigate back to overview on the SAME svg element
    pg.click("#back")
    pg.wait_for_timeout(400)
    vb2 = pg.eval_on_selector("#stage", "e => e.getAttribute('viewBox')")
    print("overview-after-back viewBox:", vb2)
    pg.screenshot(path=f"{OUT}/overview_after_back_1250x700.png")

    # check overview right edge: engine boxes end where?
    maxr = pg.eval_on_selector("#stage", """e => {
        let m = 0;
        for (const r of e.querySelectorAll('rect')) {
            const x = parseFloat(r.getAttribute('x')) + parseFloat(r.getAttribute('width'));
            if (x > m) m = x;
        }
        return m;
    }""")
    print("overview max rect right edge:", maxr, "(svg clientWidth:",
          pg.eval_on_selector("#stage", "e => e.clientWidth"), ")")

    # 3. drill into a short pipeline (facet_rag) to confirm no viewBox on narrow
    pg.evaluate("location.hash = 'facet_rag'")
    pg.wait_for_timeout(400)
    vb3 = pg.eval_on_selector("#stage", "e => e.getAttribute('viewBox')")
    print("facet_rag viewBox:", vb3)

    # 4. overview loaded fresh (no fragment)
    pg2 = b.new_page(viewport={"width": 1250, "height": 700})
    pg2.goto(URL)
    pg2.wait_for_timeout(400)
    pg2.screenshot(path=f"{OUT}/overview_fresh_1250x700.png")
    print("fresh overview viewBox:", pg2.eval_on_selector("#stage", "e => e.getAttribute('viewBox')"))
    b.close()
