"""Edge cases: every view under unusual settings. Fails on runtime errors, on "NaN", "undefined",
"Infinity" or "null" shown to the reader, and on views with no chart.

Usage: python tests/check_edges.py [webkit|chromium]   (needs: python serve.py)
"""
import re
import sys
from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:8767/_site/index.html?t=edges"
BAD_TEXT = re.compile(r"\bNaN\b|\bundefined\b|\bInfinity\b|\bnull\b|\[object")
CASES = [
    # name, agency, component label (substring) or None, from, to, cohort, compare labels
    ("total, all years", None, None, 2008, 2025, False, []),
    ("total, one year", None, None, 2025, 2025, False, []),
    ("total, reversed years", None, None, 2020, 2012, False, []),
    ("total, two years", None, None, 2024, 2025, False, []),
    ("total, first two years", None, None, 2008, 2009, False, []),
    ("component, two years", "Department of Justice", "(FBI)", 2023, 2024, False, []),
    ("compare, two years", "Department of Homeland Security", "(ICE)", 2024, 2025, False, ["Department of Justice"]),
    ("agency with one of the two years", "Overseas Private Investment Corporation", None, 2019, 2020, False, []),
    ("total, 70 agencies", None, None, 2008, 2025, True, []),
    ("no components (ACUS)", "Administrative Conference of the United States", None, 2008, 2025, False, []),
    ("tiny agency", "Civil Rights Cold Case Records Review Board", None, 2008, 2025, False, []),
    ("agency that stopped reporting", "Overseas Private Investment Corporation", None, 2008, 2025, False, []),
    ("component, one year", "Department of Justice", "(FBI)", 2025, 2025, False, []),
    ("component early years only", "Department of Veterans Affairs", "(VACO)", 2008, 2010, False, []),
    ("compare 3, total", None, None, 2008, 2025, False, ["Department of Justice", "Department of State"[:0] or "U.S. Department of State", "Department of Defense"]),
    ("compare with component, one year", "Department of Homeland Security", "(ICE)", 2024, 2024, False, ["Department of Homeland Security › U.S. Citizenship & Immigration Services (USCIS)"]),
]


# titles (or positions) of the charts in the visible tab that have data marks but none inside the chart's frame
OFF_FRAME = """() => [...document.querySelectorAll('.tab-pane.active svg[class^=plot]')].flatMap((svg, i) => {
  const f = svg.getBoundingClientRect()
  const marks = svg.querySelectorAll('g[aria-label="dot"] circle, g[aria-label="line"] path, g[aria-label="bar"] rect, g[aria-label="rect"] rect, g[aria-label="area"] path')
  if (!marks.length || !f.width) return []
  const inside = [...marks].some(m => { const b = m.getBoundingClientRect()
    return b.width + b.height > 0 && b.bottom > f.top && b.top < f.bottom && b.right > f.left && b.left < f.right })
  return inside ? [] : [(svg.closest('figure, .fig, .tile')?.querySelector('h4, h5, figcaption, .fig-title')?.textContent || `chart ${i + 1}`).trim().slice(0, 60)]
})"""


def main(engine):
    problems, seen = [], 0
    with sync_playwright() as p:
        b = getattr(p, engine).launch()
        pg = b.new_page(viewport={"width": 1456, "height": 900})
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)[:160]))
        for name, agency, comp, lo, hi, cohort, compare in CASES:
            pg.goto(URL); pg.wait_for_timeout(5000)
            sel = pg.locator("select").filter(has=pg.locator("option", has_text="Department of Justice")).first
            if agency:
                opts = sel.locator("option").all_inner_texts()
                if agency not in opts:
                    problems.append(f"{name}: agency not in list"); continue
                sel.select_option(label=agency); pg.wait_for_timeout(900)
            if comp:
                cs = pg.locator("select").filter(has=pg.locator("option", has_text="All components (agency total)")).first
                lab = next((l for l in cs.locator("option").all_inner_texts() if comp in l), None)
                if not lab:
                    problems.append(f"{name}: component {comp} not in list"); continue
                cs.select_option(label=lab); pg.wait_for_timeout(900)
            pg.evaluate("""([lo, hi]) => { document.querySelector(`.tl-y[data-y="${lo}"]`).click(); document.querySelector(`.tl-y[data-y="${hi}"]`).click(); }""", [lo, hi])
            pg.wait_for_timeout(900)
            if cohort:
                pg.evaluate("() => [...document.querySelectorAll('input[type=radio]')].find(x => x.parentElement.textContent.includes('agencies that reported all')).click()")
                pg.wait_for_timeout(700)
            for c in compare:  # "Agency" or "Agency › Component name (CODE)": pick the agency, then the component, then Add
                ag_name, _, comp_name = c.partition(" › ")
                pg.locator(".cmp select.cmp-agency").select_option(label=ag_name); pg.wait_for_timeout(200)
                if comp_name:
                    pg.locator(".cmp select.cmp-comp").select_option(label=comp_name); pg.wait_for_timeout(200)
                pg.wait_for_timeout(700)  # choosing adds it
            if compare and pg.locator(".chip").count() != len(compare):
                problems.append(f"{name}: {pg.locator('.chip').count()} of {len(compare)} compared entities added")
            views = [0] + list(range(1, 8))
            for q in views:
                if q:
                    btn = pg.locator(f'.qbtn[data-id="{q}"]')
                    if "on" not in (btn.get_attribute("class") or ""):
                        btn.click()
                else:
                    on = pg.locator(".qbtn.on")
                    if on.count(): on.first.click()
                pg.wait_for_timeout(900)
                tabs = ["Chart"] + (["Tables", "How the comparison is made"] if q else [])
                for tab in tabs:
                    if q:
                        pg.locator(".nav-tabs .nav-link", has_text=tab).click(); pg.wait_for_timeout(350)
                    subviews = ["chart", "more", "compare"] if tab == "Tables" else [None]
                    for sv in subviews:
                        if sv:
                            pg.locator(f'.tvbtn[data-k="{sv}"]').click(); pg.wait_for_timeout(350)
                        seen += 1
                        text = pg.locator(".tab-pane.active").first.inner_text() + pg.locator(".qhead").first.inner_text()
                        m = BAD_TEXT.search(text)
                        if m:
                            i = m.start()
                            problems.append(f"{name} | view {q} {tab} {sv or ''}: shows '{text[max(0, i - 50):i + 20]}'".replace("\n", " "))
                        if "Runtime Error" in text or "Error:" in text:
                            problems.append(f"{name} | view {q} {tab} {sv or ''}: error shown")
                        if tab == "Chart":
                            # a chart whose data marks all fall outside its frame looks empty (e.g. a wrong axis domain)
                            empty = pg.evaluate(OFF_FRAME)
                            if empty:
                                problems.append(f"{name} | view {q}: {len(empty)} chart(s) with every mark outside the frame: {empty}")
                        if tab == "Chart" and q:
                            n = pg.locator(".tab-pane.active .pair svg[class^=plot]").count() + pg.locator(".tab-pane.active .pair .chart-note").count()
                            if n < 2:
                                problems.append(f"{name} | view {q}: only {n} charts/notes")
                        if q == 0 and (agency or compare):
                            if pg.locator(".overview .tile").count() != 6:
                                problems.append(f"{name} | overview: {pg.locator('.overview .tile').count()} tiles")
                if q:
                    pg.locator(".nav-tabs .nav-link", has_text="Chart").click(); pg.wait_for_timeout(200)
        b.close()
    problems += [f"page error: {e}" for e in errs]
    print(f"{engine}: {seen} views checked, {len(problems)} problems")
    for x in problems[:60]:
        print("  ", x)
    return len(problems)


if __name__ == "__main__":
    sys.exit(1 if main(sys.argv[1] if len(sys.argv) > 1 else "chromium") else 0)
