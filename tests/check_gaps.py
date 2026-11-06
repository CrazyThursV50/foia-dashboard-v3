"""Explore > Tables > All components: the "(Agency total minus components)" row in known cases.
The row must show only real differences: none where the components add up (also when staff or dollar amounts
leave float noise), the right amount where foia.gov has numbers linked to no component or its total disagrees.

Usage: python tests/check_gaps.py [webkit|chromium] [page URL]   (needs: python serve.py)
"""
import sys
from playwright.sync_api import sync_playwright
URL = sys.argv[2] if len(sys.argv) > 2 else "http://127.0.0.1:8767/_site/index.html?t=gap"
CASES = [  # agency, year, data type no., measure label (exact), expected gap ("" = no row)
    ("Department of Justice", 2020, "23", "Total Costs", ""),
    ("Defense Nuclear Facilities Safety Board", 2010, "22", 'Total Number of "Full-Time FOIA Staff"', ""),
    ("Department of Agriculture", 2016, "22", 'Total Number of "Full-Time FOIA Staff"', ""),
    ("Office of Personnel Management", 2017, "01", "Number of Requests Received in Fiscal Year", "7,550"),
    ("General Services Administration", 2016, "17", "Total", "421"),
    ("General Services Administration", 2016, "01", "Number of Requests Received in Fiscal Year", ""),
]
bad = 0
with sync_playwright() as p:
    b = getattr(p, sys.argv[1] if len(sys.argv) > 1 else "chromium").launch()
    pg = b.new_page(viewport={"width": 1456, "height": 900})
    for ag, fy, no, lab, want in CASES:
        pg.goto(URL); pg.wait_for_timeout(5000)
        pg.locator("select").filter(has=pg.locator("option", has_text="Department of Justice")).first.select_option(label=ag); pg.wait_for_timeout(800)
        pg.evaluate("""(y) => { const c = document.querySelector(`.tl-y[data-y="${y}"]`); c.click(); c.click() }""", fy); pg.wait_for_timeout(800)
        pg.locator('.qbtn[data-id="7"]').click(); pg.wait_for_timeout(900)
        pick = lambda name: pg.locator("form").filter(has=pg.locator("label", has_text=name)).locator("select").first
        t = pick("Data type")
        t.select_option(value=no); pg.wait_for_timeout(800)
        m = pick("Measure")
        opts = m.locator("option").all_inner_texts()
        if lab not in opts:
            print(f"  {ag} {fy}: measure {lab!r} not in {opts[:6]}"); bad += 1; continue
        m.select_option(label=lab); pg.wait_for_timeout(900)
        pg.locator(".nav-tabs .nav-link", has_text="Tables").click(); pg.wait_for_timeout(400)
        pg.locator('.tvbtn[data-k="compare"]').click(); pg.wait_for_timeout(700)
        rows = [r for r in pg.locator(".tab-pane.active table tr").all_inner_texts() if "(Agency total minus components)" in r]
        got = rows[0].split("\t")[-1].strip() if rows else ""
        ok = got == want
        bad += not ok
        print(f"  {'ok ' if ok else 'BAD'} {ag} FY{fy} · {lab}: gap row {got!r} (expected {want!r})")
    b.close()
print(f"{sys.argv[1] if len(sys.argv) > 1 else 'chromium'}: {len(CASES)} cases checked, {bad} problems")
sys.exit(1 if bad else 0)
