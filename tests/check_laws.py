"""The "Laws behind Exemption 3" view, checked against the raw table 06 (exemption_statutes_06.csv).

Totals are summed from the raw rows, so they do not depend on how prep_laws.py groups laws; single laws are matched
with separate text searches. Also: the grouping rules, the switch, comparisons, year choices, empty selections, links, CSV.

Usage: python tests/check_laws.py [chromium|webkit]   (needs: python serve.py)
"""
import csv as csvlib
import io
import re
import sys
from pathlib import Path
from urllib.parse import urlencode

import pandas as pd
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).parent.parent))
from prep_laws import group, NOT_NAMED  # noqa: E402

URL = "http://127.0.0.1:8767/_site/index.html"
R = Path.home() / "ds-muckrock-liberation/fa26/dataset/component_level"
S = pd.read_csv(R / "exemption_statutes_06.csv", dtype=str, keep_default_na=False)
S["n"] = pd.to_numeric(S["Number of Times Relied Upon"].str.replace(",", ""), errors="coerce").fillna(0)
S["FY"] = S["Fiscal Year"].astype(int)
S = S[S.n > 0]
M = pd.read_csv(R / "component_master_no_03_06_11.csv", dtype=str, keep_default_na=False)
M["FY"] = M["Fiscal Year"].astype(int)
problems, checked = [], 0


def same(name, got, want):
    global checked
    checked += 1
    if got != want:
        problems.append(f"{name}: got {got!r}, expected {want!r}")


# ---- grouping rules ----
for text, want in [("8 U.S.C. § 1202(f) (Immigration and Nationality Act)", "8 U.S.C. § 1202"), ("8 USC 1202(f)", "8 U.S.C. § 1202"), ("8 U.S.C § 1202(f)", "8 U.S.C. § 1202"),
                   ("50 U.S.C. § 3024(i)(1) (formerly at 50 U.S.C. § 403-1(i)(1))", "50 U.S.C. § 3024"), ("50 U.S.C. § 403-1(i)(1)", "50 U.S.C. § 3024"),
                   ("50 U.S.C. § 403- 1(i)(1)", "50 U.S.C. § 3024"), ("50 USC 3024(i) Formerly 50 USCA § 403-1(i)", "50 U.S.C. § 3024"), ("50 U.S.C., Section 403g", "50 U.S.C. § 3507"),
                   ("50 U.S.C. § 3605 (Formerly 50 U.S.C. § 402)", "50 U.S.C. § 3605"), ("41 U.S.C. § 253b(m)(1) (currently at 41 U.S.C. § 4702)", "41 U.S.C. § 4702"),
                   ("49 U.S.C. § 114 (r) (formerly at 49 U.S.C. § 114 (s))", "49 U.S.C. § 114"), ("26 U.S.C. §§ 6103, 6105", "26 U.S.C. § 6103"),
                   ("42 U.S.C. §§ 2000e-5(b), 2000e-8€", "42 U.S.C. § 2000e-5"), ("5 U.S.C. app. § 107(a)", "5 U.S.C. app. § 107"),
                   ("Fed. R. Crim. P. 6(e), enacted by Act of July 30, 1977, Pub. L. No. 95-78, 91 Stat. 319", "Fed. R. Crim. P. 6(e)"), ("Sec 6 of the CIA Act of 1949", "50 U.S.C. § 3507"),
                   ("18 § U.S.C. 208(d)(1)", "18 U.S.C. § 208"), ("26 U.S.C. s6103(a)", "26 U.S.C. § 6103"), ("41 U.S. Code § 4712", "41 U.S.C. § 4712"),
                   ("16 U.S.C. § Sec. 470hh", "16 U.S.C. § 470hh"), ("42 § U.S.C. 290dd-3", "42 U.S.C. § 290dd-3"), (".", NOT_NAMED),
                   ("18 U.S.C. §§ 2510-20", "18 U.S.C. § 2510"), ("41 U.S.C. § 423(a)(1)", "41 U.S.C. § 2102"), ("Section 25c of the CPSA, 5 U.S.C. § 2074c", "15 U.S.C. § 2074"),
                   ("50 U.S.C. 403(g) - CIA Act of 1949", "50 U.S.C. § 3507"),
                   ("N/A", NOT_NAMED), ("Pub. L. No. 111-8, 123 Stat. 524", "Pub. L. No. 111-8, 123 Stat. 524")]:
    same(f"group {text[:40]}", group(text), want)


def raw(agency=None, comp=None, fy=2025):
    d = S[S.FY == fy]
    # an agency whose roll-up row is marked to exclude: its agency row counts that row twice, so its components are the right numbers
    twice = set(d[d["Exclude From Component Sum"] == "yes"].Agency)
    fixed = d[(d["Row Type"] == "component") & (d["Exclude From Component Sum"] == "") & d.Agency.isin(twice)]
    plain = d[(d["Row Type"] == "agency_overall") & ~d.Agency.isin(twice)]
    if agency is None:
        return pd.concat([plain, fixed])
    if comp is None:
        return pd.concat([plain, fixed])[lambda v: v.Agency == agency]
    return d[(d["Row Type"] == "component") & (d.Agency == agency) & (d.Component == comp) & (d["Exclude From Component Sum"] == "")]


def download(pg):
    pg.locator(".nav-tabs .nav-link", has_text="Tables").click(); pg.wait_for_timeout(400)
    pg.locator('.tvbtn[data-k="chart"]').click(); pg.wait_for_timeout(700)
    with pg.expect_download() as d:
        pg.locator(".csv").first.click()
    rows = list(csvlib.DictReader(io.StringIO(Path(d.value.path()).read_text())))
    pg.locator(".nav-tabs .nav-link", has_text="Chart").click(); pg.wait_for_timeout(300)
    return rows


with sync_playwright() as p:
    b = getattr(p, sys.argv[1] if len(sys.argv) > 1 else "chromium").launch()
    ctx = b.new_context(viewport={"width": 1440, "height": 830}, accept_downloads=True)
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)[:160]))

    def go(**q):
        pg.goto(URL + "?" + urlencode(q)); pg.wait_for_selector(".qtop"); pg.wait_for_timeout(1800)

    head = lambda: pg.locator(".qhead").first.inner_text()
    pane = lambda: pg.locator(".tab-pane.active").first.inner_text()
    # ---- every selection: the list adds up to the raw rows ----
    for name, ag, co in [("total", None, None), ("DHS", "Department of Homeland Security", None), ("DOJ", "Department of Justice", None), ("VA", "Department of Veterans Affairs", None),
                         ("State", "U.S. Department of State", None), ("USCIS", "Department of Homeland Security", "USCIS"), ("FBI", "Department of Justice", "FBI"), ("CBP", "Department of Homeland Security", "CBP")]:
        q = {"q": 4, "sub": "laws", **({"agency": ag} if ag else {}), **({"comp": co} if co else {})}
        go(**q)
        r = raw(ag, co)
        rows = download(pg)
        same(f"{name}: list adds up", sum(int(x["Times relied on"]) for x in rows), int(r.n.sum()))
        same(f"{name}: sorted, most first", [int(x["Times relied on"]) for x in rows] == sorted((int(x["Times relied on"]) for x in rows), reverse=True), True)
        same(f"{name}: no blank law", all(x["Law"].strip() for x in rows), True)
        same(f"{name}: every row in one law", len({x["Law"] for x in rows}), len(rows))
        top3 = sum(int(x["Times relied on"]) for x in rows[:3]) / sum(int(x["Times relied on"]) for x in rows)
        if len(rows) > 3:
            want = "over 99%" if top3 > 0.995 else f"{round(top3 * 100 + 1e-9):d}%"
            same(f"{name}: sentence", f"laws make up {want} of the {int(r.n.sum()):,} times" in head(), True)
        same(f"{name}: no part shown as the whole", "make up 100%" in head(), False)
    # ---- Commerce FY2025 is not counted twice ----
    go(q=4, sub="laws", agency="Department of Commerce")
    same("Commerce FY2025", sum(int(v["Times relied on"]) for v in download(pg)), 138)
    # ---- single laws, by a separate text search ----
    go(q=4, sub="laws")
    rows = {x["Law"]: x for x in download(pg)}
    r = raw()
    for cite, pat in [("8 U.S.C. § 1202", r"\b8\s*U\.?\s?S\.?\s?C.{0,6}1202"), ("49 U.S.C. § 114", r"\b49\s*U\.?\s?S\.?\s?C\.?[^0-9]{0,8}114\b(?!\d)"), ("38 U.S.C. § 5701", r"\b38\s*U\.?\s?S\.?\s?C.{0,6}5701"),
                      ("26 U.S.C. § 6103", r"\b26\s*U\.?\s?S\.?\s?C.{0,8}6103")]:
        same(f"{cite}: total", int(rows[cite]["Times relied on"]), int(r[r.Statute.str.contains(pat, regex=True)].n.sum()))
    same("used by, A-Z with counts", rows["8 U.S.C. § 1202"]["Used by"], "DHS 48,891; DOJ 4; DOS 7,289")
    same("csv has the link", rows["8 U.S.C. § 1202"]["Link"], "https://www.law.cornell.edu/uscode/text/8/1202")
    same("csv has the title", bool(rows["8 U.S.C. § 1202"]["Title in the U.S. Code"]), True)
    same("agencies' own words", rows["8 U.S.C. § 1202"]["What it covers (agencies' words)"].startswith("Certain records pertaining to the issuance or refusal of visas"), True)
    same("guide: one short sentence pair", len(pg.locator(".chartlook").inner_text()) < 120, True)
    pg.locator(".nav-tabs .nav-link", has_text="How the comparison").click(); pg.wait_for_timeout(400)
    same("mismatch explained in the notes", "do not add up exactly to the Exemption 3 count" in pane(), True)
    pg.locator(".nav-tabs .nav-link", has_text="Chart").click(); pg.wait_for_timeout(300)
    # the list: eight laws and the rest, to scale, with the agencies' words and a checked link
    K = pd.read_csv(Path(__file__).parent.parent / "law_links.csv", dtype=str, keep_default_na=False).set_index("cite")
    laws = pg.locator(".lawlist .law")
    same("list: 5 laws and the rest", laws.count(), 6)
    same("list: last is the rest", laws.nth(5).locator(".lawwords").inner_text().startswith("All other laws ("), True)
    top = sorted(rows.values(), key=lambda x: -int(x["Times relied on"]))
    same("list: order and numbers", [(laws.nth(i).locator(".lawcite").inner_text(), laws.nth(i).locator(".lawn").inner_text()) for i in range(5)],
         [(x["Law"], f'{int(x["Times relied on"]):,}') for x in top[:5]])
    same("list: rest adds up", laws.nth(5).locator(".lawn").inner_text(), f'{sum(int(x["Times relied on"]) for x in top[5:]):,}')
    same("list: agencies' words in full", laws.nth(0).locator(".lawwords").inner_text(), top[0]["What it covers (agencies' words)"])
    same("hover: official title", K.loc["8 U.S.C. § 1202", "title"] in (laws.nth(0).get_attribute("title") or ""), True)
    same("table: official title", top[0]["Title in the U.S. Code"], K.loc["8 U.S.C. § 1202", "title"])
    same("first layer: no more than one idea per row", laws.nth(0).locator(".lawtitle").count(), 0)
    w = pg.evaluate("""() => [...document.querySelectorAll('.lawlist .lawbar i')].map(i => parseFloat(i.style.width))""")
    same("list: bars to scale", abs(w[0] / w[1] - int(top[0]["Times relied on"]) / int(top[1]["Times relied on"])) < 0.01, True)
    hrefs = pg.evaluate("""() => [...document.querySelectorAll('.lawlist a.lawcite')].map(a => a.getAttribute('href'))""")
    same("list: every law linked", len(hrefs), 5)
    same("list: links all checked", all(h in set(K[K.status == "200"].url) for h in hrefs), True)
    same("list: new tab", pg.evaluate("""() => [...document.querySelectorAll('.lawlist a.lawcite')].every(a => a.target === '_blank')"""), True)
    same("list: first link", hrefs[0], "https://www.law.cornell.edu/uscode/text/8/1202")
    same("hover: who uses it", "Used by: DHS 48,891, DOJ 4, DOS 7,289" in (laws.nth(0).get_attribute("title") or ""), True)
    dots = pg.evaluate("""() => [...document.querySelectorAll('.lawlist .lawdot')].filter(d => d.style.background).length""")
    same("list: dots match the 3 trend lines", dots, 3)
    lines_n = pg.evaluate("""() => document.querySelectorAll('.tab-pane.active .pair figure:nth-child(2) g[aria-label="line"] path').length""")
    same("trend: 3 lines", lines_n, 3)
    # every link used anywhere on the page answered when checked
    import json
    D = json.loads((Path(__file__).parent.parent / "data/laws.json").read_text())
    same("data: only checked links", all(not l["url"] or l["url"] in set(K[K.status == "200"].url) for l in D["laws"]), True)
    # ---- the switch ----
    go(q=4)
    same("starts on the usual view", "Laws relied on most" in pane(), False)
    pg.locator('.subbtn[data-k="laws"]').click(); pg.wait_for_timeout(900)
    same("switch on", ("Laws relied on most" in pane(), "sub=laws" in pg.url), (True, True))
    pg.locator('.subbtn[data-k="main"]').click(); pg.wait_for_timeout(900)
    same("switch off", ("What happened to processed requests" in pane(), "sub=laws" in pg.url), (True, False))
    go(q=1)
    same("no switch on other steps", pg.locator(".subbtn:visible").count(), 0)
    go(q=4, sub="laws", **{"with": "A|Department of Justice"})
    same("compare: no switch, usual charts", (pg.locator(".subbtn:visible").count(), "Laws relied on most" in pane(), "Compare" in pane()), (0, False, True))
    # nothing on the page is a name we wrote
    same("no hand-written names", "SHORT_NAMES" in (Path(__file__).parent.parent / "prep_laws.py").read_text(), False)
    same("no short name column", "Short name" in (Path(__file__).parent.parent / "index.qmd").read_text(), False)
    # ---- years ----
    go(q=4, sub="laws", **{"from": 2025, "to": 2025})
    same("one year: says to pick a range", "Pick a range of years" in pane(), True)
    go(q=4, sub="laws", **{"from": 2024, "to": 2025})
    two = pg.evaluate("""() => [...document.querySelectorAll('.tab-pane.active svg[class^=plot] g[aria-label="line"] path')].filter(p => (p.getAttribute('d') || '').split('L').length === 2).length""")
    same("two years: no straight line", two, 0)
    go(q=4, sub="laws", **{"from": 2015, "to": 2020})
    rows = download(pg)
    same("last year chosen", sum(int(x["Times relied on"]) for x in rows), int(raw(fy=2020).n.sum()))
    # ---- same agencies every year ----
    go(q=4, sub="laws", scope="same")
    keep = M[M["Row Type"] == "agency_overall"].groupby("Agency").FY.nunique()
    keep = set(keep[keep == M.FY.nunique()].index)
    r = raw()
    same("cohort", sum(int(x["Times relied on"]) for x in download(pg)), int(r[r.Agency.isin(keep)].n.sum()))
    # ---- nothing listed ----
    has = set(raw().Agency)
    none = sorted(set(M[(M["Row Type"] == "agency_overall") & (M.FY == 2025)].Agency) - has)[0]
    go(q=4, sub="laws", agency=none)
    same("no laws listed: a note, no chart", ("No Exemption 3 laws listed" in pane(), pg.locator(".tab-pane.active svg[class^=plot]").count()), (True, 0))
    bad = re.compile(r"\bNaN\b|\bundefined\b|\bInfinity\b|\bnull\b|\[object")
    same("no laws listed: clean", bad.search(head() + pane()) is None, True)
    # ---- a link opens the view ----
    go(q=4, sub="laws", agency="Department of Homeland Security", **{"from": 2016, "to": 2025})
    same("link keeps the view", ("Laws relied on most" in pane(), pg.locator(".subbtn.on").inner_text(), pg.locator(".tl-label").inner_text()), (True, "Laws behind Exemption 3", "FY2016–FY2025"))
    # ---- About ----
    go(q=8)
    a = pg.locator(".about").inner_text()
    same("About lists the laws", "Laws behind Exemption 3" in a and "the statutes behind Exemption 3" not in a, True)
    b.close()

problems += [f"page error: {e}" for e in errs]
print(f"{checked} checks, {len(problems)} problems")
for x in problems[:40]:
    print("  ", x)
sys.exit(1 if problems else 0)
