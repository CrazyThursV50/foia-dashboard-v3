"""Checks for what is new in this version, against the component table (not data/foia.json).

- start page: every number and sentence on the six cards, for the government total, an agency and a component
- top of the page: both appeal rates; agency-or-component note; warning when a comparison overlaps
- timeline: presets, a range from two clicks (either order), a single year, and that a first click alone changes nothing
- lists: largest agencies first, every agency and component exactly once, every data type under a topic
- page address: a view opens the same from its link
- CSV: same rows and numbers as the table, "<1" kept, no helper column
- About page: computed numbers, nothing missing; wording scan for verdicts on agencies

Usage: python tests/check_v2.py [chromium|webkit]   (needs: python serve.py)
"""
import csv as csvlib
import io
import re
import sys
from pathlib import Path
from urllib.parse import urlencode

import pandas as pd
from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:8767/_site/index.html"
M = pd.read_csv(Path.home() / "ds-muckrock-liberation/fa26/dataset/component_level/component_master_no_03_06_11.csv", dtype=str, keep_default_na=False)
M["FY"] = M["Fiscal Year"].astype(int)
BAD = re.compile(r"\bNaN\b|\bundefined\b|\bInfinity\b|\bnull\b|\[object")
problems, checked = [], 0


def num(x):
    x = str(x).replace(",", "").strip()
    if x == "<1":
        return 0.5
    try:
        return float(x)
    except ValueError:
        return None


def s(df, col):
    v = [num(x) for x in df[col]]
    v = [x for x in v if x is not None]
    return sum(v) if v else None


def same(name, got, want):
    global checked
    checked += 1
    if got != want:
        problems.append(f"{name}: page {got!r}, table {want!r}")


pct0 = lambda x: f"{round(x * 100 + 1e-9):d}%"
pct1 = lambda x: f"{x * 100:.1f}%"
signed1 = lambda x: f"{x * 100:+.1f}%".replace("-", "−")
DET = lambda: pg.locator(".overview .tile")


def rows(kind, agency=None, comp=None):
    if kind == "total":
        return M[M["Row Type"] == "agency_overall"]
    if kind == "agency":
        return M[(M["Row Type"] == "agency_overall") & (M.Agency == agency)]
    return M[(M["Row Type"].isin(["component"])) & (M.Agency == agency) & (M.Component == comp)]


C = {"recv": "01_Requests__ProcessingStatisticsReceivedQuantity", "proc": "01_Requests__ProcessingStatisticsProcessedQuantity",
     "backlog": "26_Backlog__BackloggedRequestQuantity", "staff": "22_Personnel__TotalFullTimeStaffQuantity", "cost": "23_Costs__TotalCostAmount",
     "aff": "08_AppealsDisposition__AppealDispositionAffirmedQuantity", "part": "08_AppealsDisposition__AppealDispositionPartialQuantity",
     "rev": "08_AppealsDisposition__AppealDispositionReversedQuantity", "tot": "08_AppealsDisposition__AppealDispositionTotalQuantity",
     "grant": "02_Disposition__RequestDispositionFullGrantQuantity"}
BK = ["1-20", "21-40", "41-60", "61-80", "81-100", "101-120", "121-140", "141-160", "161-180", "181-200", "201-300", "301-400", "401+"]
OUT = [c for c in M.columns if c.startswith("02_Disposition__") and "Total" not in c and "ReceiptDate" not in c]


def within20(df, prefix):
    allv = sum((s(df, f"{prefix}__TimeIncrementProcessedQuantity[{k}]") or 0) for k in BK)
    return (s(df, f"{prefix}__TimeIncrementProcessedQuantity[1-20]") or 0) / allv if allv else None


def check_cards(name, kind, agency=None, comp=None):
    r = rows(kind, agency, comp)
    a, b = r[r.FY == 2025], r[r.FY == 2024]
    t = [x.inner_text() for x in DET().all()]
    same(f"{name}: 6 cards", len(t), 6)
    if len(t) != 6:
        return
    v = lambda i: pg.locator(".overview .tile .tval").nth(i).inner_text()
    line = lambda i: pg.locator(".overview .tile .tline").nth(i).inner_text()
    chg = lambda i: pg.locator(".overview .tile .tchg").nth(i).inner_text()
    same(f"{name}: order", [x.split("\n")[0].strip() for x in t] and [pg.locator(".overview .tile .tstep").nth(i).inner_text().split("Open")[0].strip().split("\n")[-1] for i in range(6)],
         ["Requests", "Response time", "Outcomes & exemptions", "Appeals", "Backlog", "Staff & cost"])
    recv, proc = s(a, C["recv"]), s(a, C["proc"])
    same(f"{name}: received", v(0), f"{recv:,.0f}")
    same(f"{name}: received change", chg(0), f"{(recv / s(b, C['recv']) - 1) * 100:+.1f}% vs FY2024")
    same(f"{name}: processed line", line(0), f"Processed equal to {pct0(proc / recv)} of requests received.")
    cx = within20(a, "17_ComplexRequests")
    same(f"{name}: complex within 20", v(1), pct1(cx) if cx is not None else "–")
    si = within20(a, "16_SimpleRequests")
    same(f"{name}: simple line", line(1), f"{pct0(si)} of simple requests were done within 20 working days." if si is not None else "")
    den = sum((s(a, c) or 0) for c in OUT)
    same(f"{name}: full grants", v(2), pct1(s(a, C["grant"]) / den))
    aff, part, rev, tot = (s(a, C[k]) for k in ("aff", "part", "rev", "tot"))
    if tot:
        same(f"{name}: reversal, merits", v(3), pct1((part + rev) / (aff + part + rev)))
        same(f"{name}: reversal, all", line(3), f"{pct0((part + rev) / tot)} when counted out of all processed appeals.")
    same(f"{name}: backlog", v(4), f"{s(a, C['backlog']):,.0f}")
    st = s(a, C["staff"])
    same(f"{name}: staff", v(5), f"{round(st):,}")
    co = s(a, C["cost"])
    got = re.search(r"\$([\d.]+)([MkB]?)", line(5))
    scale = {"M": 1e6, "k": 1e3, "B": 1e9, "": 1}[got.group(2)]
    same(f"{name}: cost", abs(float(got.group(1)) * scale - co) / co < 0.005, True)


def pick_agency(label):
    sel = pg.locator(".gsel select").filter(has=pg.locator("option", has_text="Department of Justice")).first
    sel.select_option(label=label); pg.wait_for_timeout(900)


with sync_playwright() as p:
    b = getattr(p, sys.argv[1] if len(sys.argv) > 1 else "chromium").launch()
    ctx = b.new_context(viewport={"width": 1456, "height": 900}, accept_downloads=True)
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)[:160]))
    pg.goto(URL); pg.wait_for_selector(".qbtn"); pg.wait_for_timeout(4000)

    # ---- start page ----
    check_cards("total", "total")
    pick_agency("Department of Homeland Security"); check_cards("DHS", "agency", "Department of Homeland Security")
    cs = pg.locator(".gsel select").filter(has=pg.locator("option", has_text="All components (agency total)")).first
    cs.select_option(value="USCIS"); pg.wait_for_timeout(900); check_cards("USCIS", "component", "Department of Homeland Security", "USCIS")

    # ---- top of the page: appeals, level note ----
    head = lambda: pg.locator(".qhead").first.inner_text()
    same("component note", "component: already inside the agency total" in head(), True)
    cs.select_option(index=0); pg.wait_for_timeout(800)
    same("agency note", "agency total: already includes its components" in head(), True)
    pg.locator('.qbtn[data-id="5"]').click(); pg.wait_for_timeout(900)
    same("DHS both rates", "65% of appeals decided on the merits were reversed fully or partly, which is 37% of all processed appeals" in head(), True)
    same("step label", head().startswith("Step 4 of 6"), True)
    same("reading guide shown", pg.locator(".chartlook").first.is_visible(), True)

    # ---- overlap warning ----
    pg.goto(URL + "?" + urlencode({"agency": "Department of Homeland Security", "comp": "ICE", "with": "A|Department of Homeland Security", "q": 6})); pg.wait_for_selector(".qbtn"); pg.wait_for_timeout(3500)
    same("overlap warning", "ICE is already inside the agency total shown here" in head(), True)
    same("no duplicate reference", "total (reference)" in pg.locator(".tab-pane.active").first.inner_text(), False)

    # ---- the header is never clipped, at the window sizes people use ----
    CLIP = """() => { const q = document.querySelector('.qtop'), r = q.getBoundingClientRect(); let e = q.parentElement, cut = 0
      while (e && e !== document.body) { const c = getComputedStyle(e)
        if (c.overflowY !== 'visible') cut = Math.max(cut, r.bottom - e.getBoundingClientRect().bottom, e.scrollHeight - e.clientHeight)
        e = e.parentElement }
      return Math.round(cut) }"""
    worst = {"agency": "Department of Homeland Security", "comp": "ICE", "with": "A|Department of Homeland Security"}
    for w, h in [(1440, 900), (1440, 780), (1280, 720)]:
        pg.set_viewport_size({"width": w, "height": h})
        for q in [0, 1, 2, 3, 4, 5, 6, 7, 8]:
            for extra in [{}, worst]:
                pg.goto(URL + "?" + urlencode({"q": q, **extra})); pg.wait_for_selector(".qtop"); pg.wait_for_timeout(1400)
                same(f"header not clipped {w}x{h} q{q} {'worst' if extra else ''}", pg.evaluate(CLIP) <= 1, True)
    pg.set_viewport_size({"width": 1456, "height": 900})

    # ---- timeline ----
    pg.goto(URL); pg.wait_for_selector(".qbtn"); pg.wait_for_timeout(3500)
    label = lambda: pg.locator(".tl-label").inner_text()
    on = lambda: [int(x.get_attribute("data-y")) for x in pg.locator(".tl-y.on").all()]
    same("default", (label(), on()), ("FY2008–FY2025", list(range(2008, 2026))))
    for text, want in [("Last 10", (2016, 2025)), ("Last 5", (2021, 2025)), ("FY2025", (2025, 2025)), ("All years", (2008, 2025))]:
        pg.locator(".tl-p", has_text=text).click(); pg.wait_for_timeout(700)
        same(f"preset {text}", (on()[0], on()[-1]), want)
        same(f"preset {text} marked", pg.locator(".tl-p.on").inner_text(), text)
    pg.locator('.qbtn[data-id="1"]').click(); pg.wait_for_timeout(800)
    before = pg.locator(".glance").first.inner_text()
    pg.locator('.tl-y[data-y="2012"]').click(); pg.wait_for_timeout(500)
    same("first click waits", (pg.url.find("from=") < 0, pg.locator(".glance").first.inner_text()), (True, before))
    same("first click says so", "now click the last year" in label(), True)
    pg.locator('.tl-y[data-y="2018"]').click(); pg.wait_for_timeout(800)
    same("range", (label(), "from=2012" in pg.url, "to=2018" in pg.url), ("FY2012–FY2018", True, True))
    pg.locator('.tl-y[data-y="2020"]').click(); pg.locator('.tl-y[data-y="2014"]').click(); pg.wait_for_timeout(800)
    same("range, clicked backwards", label(), "FY2014–FY2020")
    pg.locator('.tl-y[data-y="2019"]').click(); pg.locator('.tl-y[data-y="2019"]').click(); pg.wait_for_timeout(800)
    same("single year", label(), "FY2019")

    # ---- two years: bars, never a line of two points ----
    LINES = """() => [...document.querySelectorAll('.tab-pane.active svg[class^=plot] g[aria-label="line"] path')].filter(p => (p.getAttribute('d') || '').split('L').length === 2).length"""
    BARS = """() => document.querySelectorAll('.tab-pane.active svg[class^=plot] g[aria-label="bar"] rect').length"""
    for sel in [{}, {"agency": "Department of Homeland Security"}, {"agency": "Department of Justice", "comp": "FBI"}, {"agency": "U.S. Department of State", "with": "A|Department of Justice"}]:
        for q in [0, 1, 2, 3, 4, 5, 6, 7]:
            pg.goto(URL + "?" + urlencode({"q": q, "from": 2024, "to": 2025, **sel})); pg.wait_for_selector(".qtop"); pg.wait_for_timeout(1500)
            same(f"two years, no straight line: q{q} {sel}", pg.evaluate(LINES), 0)
            same(f"two years, bars or a note: q{q} {sel}", pg.evaluate(BARS) > 0 or pg.locator(".tab-pane.active .chart-note").count() > 0, True)
    # the bars are to scale: their heights have the same ratio as the numbers
    pg.goto(URL + "?" + urlencode({"from": 2024, "to": 2025})); pg.wait_for_selector(".qtop"); pg.wait_for_timeout(2000)
    hs = pg.evaluate("""() => [...document.querySelector('.overview .tile svg[class^=plot]').querySelectorAll('g[aria-label="bar"] rect')].map(r => +r.getAttribute('height'))""")
    r = rows("total")
    same("two years, bars to scale", abs(hs[0] / hs[1] - s(r[r.FY == 2024], C["recv"]) / s(r[r.FY == 2025], C["recv"])) < 0.01, True)
    # three years stays a line
    pg.goto(URL + "?" + urlencode({"from": 2023, "to": 2025})); pg.wait_for_selector(".qtop"); pg.wait_for_timeout(2000)
    same("three years, lines", pg.locator('.overview g[aria-label="line"]').count() >= 6, True)

    # ---- nothing reported is never a dot at 0% ----
    DOTS = """() => document.querySelector('.tab-pane.active .pair figure svg[class^=plot]')?.querySelectorAll('g[aria-label="dot"] circle').length ?? 0"""
    pg.goto(URL + "?" + urlencode({"q": 5, "agency": "Department of Justice", "comp": "FBI"})); pg.wait_for_selector(".qtop"); pg.wait_for_timeout(1800)
    same("FBI appeals: no dots", pg.evaluate(DOTS), 0)
    same("FBI appeals: says why", "No appeals reported for this selection" in pg.locator(".tab-pane.active").first.inner_text(), True)
    # every agency that has decided appeals in some years only: one dot per year with a rate, none for the others
    A_ = "08_AppealsDisposition__AppealDisposition"
    o_ = M[M["Row Type"] == "agency_overall"].assign(den=lambda d: sum(d[A_ + k + "Quantity"].map(num).fillna(0) for k in ("Affirmed", "Partial", "Reversed")))
    mixed = [(a_, int((g_.den > 0).sum())) for a_, g_ in o_.groupby("Agency") if 0 < (g_.den > 0).sum() < len(g_)]
    for a_, n_ in mixed[:8]:
        pg.goto(URL + "?" + urlencode({"q": 5, "agency": a_})); pg.wait_for_selector(".qtop"); pg.wait_for_timeout(1500)
        same(f"appeals dots, {a_}", pg.evaluate(DOTS), n_)

    # ---- "Compare with": both charts follow, the guide matches, the numbers match ----
    view = {"agency": "Department of Agriculture", "comp": "APHIS", "from": 2010, "to": 2011,
            "with": "C|Department of Defense|DeCA~C|Department of Homeland Security|FEMA"}
    ents = [("Department of Agriculture", "APHIS"), ("Department of Defense", "DeCA"), ("Department of Homeland Security", "FEMA")]
    for q in [1, 2, 3, 4, 5, 6, 7]:
        pg.goto(URL + "?" + urlencode({"q": q, **view})); pg.wait_for_selector(".qtop"); pg.wait_for_timeout(2000)
        heads = pg.locator(".tab-pane.active .pair figure h6").all_inner_texts()
        same(f"compare q{q}: two charts", len(heads), 2)
        same(f"compare q{q}: both compare", all(h.startswith("Compare") for h in heads), True)
        same(f"compare q{q}: different titles", heads[0] != heads[1], True)
        same(f"compare q{q}: guide", pg.locator(".chartlook").inner_text().startswith("Side by side"), True)
        fig2 = pg.locator(".tab-pane.active .pair figure").nth(1)
        same(f"compare q{q}: right chart names all three", all(n in fig2.inner_text() for n in ["(APHIS)", "(DeCA)", "(FEMA)"]), True)
    pg.goto(URL + "?" + urlencode({"q": 1, **view})); pg.wait_for_selector(".qtop"); pg.wait_for_timeout(2000)
    pg.locator(".nav-tabs .nav-link", has_text="Tables").click(); pg.wait_for_timeout(400)
    pg.locator('.tvbtn[data-k="chart"]').click(); pg.wait_for_timeout(700)
    caps = pg.locator(".tcap").all()
    same("compare tables", [c.locator("h6").inner_text().split(",")[0] for c in caps[-2:]], ["Compare: Requests received", "Compare: Processed as a share of received"])
    cells = lambda c: [[td.strip() for td in tr.locator("td").all_inner_texts()] for tr in c.locator("tbody tr").all()]
    for yi, fy in enumerate([2010, 2011]):
        for ei, (a_, c_) in enumerate(ents):
            r_ = rows("component", a_, c_); r_ = r_[r_.FY == fy]
            rc, pr = s(r_, C["recv"]), s(r_, C["proc"])
            row1 = [t_ for t_ in cells(caps[-2])[yi] if t_]; row2 = [t_ for t_ in cells(caps[-1])[yi] if t_]
            same(f"compare received {c_} {fy}", row1[1 + ei], f"{rc:,.0f}")
            same(f"compare processed share {c_} {fy}", row2[1 + ei], pct1(pr / rc))
    # the guide on a normal step matches a chart of bars or lines
    pg.goto(URL + "?" + urlencode({"q": 1, "from": 2024, "to": 2025})); pg.wait_for_selector(".qtop"); pg.wait_for_timeout(1500)
    same("guide does not mention lines", "lines" in pg.locator(".chartlook").inner_text(), False)

    # ---- bugs found 11/5, kept as tests ----
    # the same component name at two agencies stays two series
    pg.goto(URL + "?" + urlencode({"q": 1, "with": "C|Department of Justice|OIG~C|Department of Homeland Security|OIG", "from": 2024, "to": 2025})); pg.wait_for_selector(".qtop"); pg.wait_for_timeout(1800)
    same("twins: two chips, told apart", len(set(pg.locator(".chip").all_inner_texts())), 2)
    pg.locator(".nav-tabs .nav-link", has_text="Tables").click(); pg.wait_for_timeout(400)
    pg.locator('.tvbtn[data-k="chart"]').click(); pg.wait_for_timeout(700)
    cap = [c for c in pg.locator(".tcap").all() if c.locator("h6").inner_text().startswith("Compare: Requests received")][0]
    heads = [h.strip() for h in cap.locator("thead th").all_inner_texts() if h.strip()]
    same("twins: a column each", [h.replace("▴", "").replace("▾", "") for h in heads], ["FY", "All agencies (total)", "Department of Justice › OIG", "Department of Homeland Security › OIG"])
    last = [t.strip() for t in cap.locator("tbody tr").last.locator("td").all_inner_texts() if t.strip()]
    r1 = M[(M.Agency == "Department of Justice") & (M.Component == "OIG") & (M.FY == 2025)].iloc[0]; r2 = M[(M.Agency == "Department of Homeland Security") & (M.Component == "OIG") & (M.FY == 2025)].iloc[0]
    same("twins: their own numbers", last[2:], [f'{num(r1[C["recv"]]):,.0f}', f'{num(r2[C["recv"]]):,.0f}'])
    # a selection compared with itself is one series
    pg.goto(URL + "?" + urlencode({"q": 1, "agency": "Department of Homeland Security", "with": "A|Department of Homeland Security"})); pg.wait_for_selector(".qtop"); pg.wait_for_timeout(1800)
    same("itself: one line", pg.evaluate("""() => document.querySelector('.tab-pane.active .pair figure svg[class^=plot]').querySelectorAll('g[aria-label="line"] path').length"""), 1)
    # a component opened from a link stays chosen when the years change
    pg.goto(URL + "?" + urlencode({"q": 1, "agency": "Department of Justice", "comp": "FBI"})); pg.wait_for_selector(".qtop"); pg.wait_for_timeout(1800)
    pg.locator(".tl-p", has_text="Last 5").click(); pg.wait_for_timeout(1300)
    same("link: component stays", "(FBI)" in pg.locator(".qhead .sel").first.inner_text(), True)
    # clicking a step twice stays on it
    pg.goto(URL); pg.wait_for_selector(".qtop"); pg.wait_for_timeout(1800)
    pg.locator('.qbtn[data-id="2"]').dblclick(); pg.wait_for_timeout(1200)
    same("double click stays", pg.locator(".qhead").first.inner_text().startswith("Step 2 of 6"), True)
    # a blank in the report is blank in the tables
    pg.goto(URL + "?" + urlencode({"q": 2, "agency": "Department of Commerce", "comp": "InfoLaw"})); pg.wait_for_selector(".qtop"); pg.wait_for_timeout(1800)
    pg.locator(".nav-tabs .nav-link", has_text="Tables").click(); pg.wait_for_timeout(400)
    pg.locator('.tvbtn[data-k="chart"]').click(); pg.wait_for_timeout(700)
    same("blank days table", [t.strip() for t in pg.locator(".tcap").first.locator("tbody tr").first.locator("td").all_inner_texts() if t.strip()], ["≤20 days"])
    pg.goto(URL + "?" + urlencode({"q": 4, "agency": "Department of Commerce", "comp": "InfoLaw"})); pg.wait_for_selector(".qtop"); pg.wait_for_timeout(1800)
    pg.locator(".nav-tabs .nav-link", has_text="Tables").click(); pg.wait_for_timeout(400)
    pg.locator('.tvbtn[data-k="chart"]').click(); pg.wait_for_timeout(700)
    same("blank outcomes table", [t.strip() for t in pg.locator(".tcap").first.locator("tbody tr").last.locator("td").all_inner_texts() if t.strip()], ["2025"])

    # ---- lists ----
    pg.goto(URL); pg.wait_for_selector(".qbtn"); pg.wait_for_timeout(3500)
    ag = M[M["Row Type"] == "agency_overall"]
    top = ag[ag.FY == 2025].assign(n=lambda d: d[C["recv"]].map(num)).sort_values("n", ascending=False).head(10).Agency
    sel = pg.locator(".gsel select").filter(has=pg.locator("option", has_text="Department of Justice")).first
    groups = sel.evaluate("s => [...s.querySelectorAll('optgroup')].map(g => [g.label, [...g.querySelectorAll('option')].map(o => o.value)])")
    same("largest 10", groups[0][1], sorted(top))
    allv = sel.evaluate("s => [...s.options].map(o => o.value)")
    same("every agency once", sorted(allv[1:]), sorted(ag.Agency.unique()))
    same("first option is the total", allv[0], "All agencies (total)")
    pick_agency("Department of Justice")
    cs = pg.locator(".gsel select").filter(has=pg.locator("option", has_text="All components (agency total)")).first
    keys = cs.evaluate("s => [...s.options].map(o => o.value)")
    same("every component once", len(keys), len(set(keys)))
    co = M[(M["Row Type"] == "component") & (M.Agency == "Department of Justice")]
    same("DOJ components", len(keys) - 1, co.Component.nunique())
    big = co[co.FY == 2025].assign(n=lambda d: d[C["recv"]].map(num)).sort_values("n", ascending=False).head(5).Component
    same("largest 5 components", sorted(cs.evaluate("s => [...s.querySelector('optgroup').querySelectorAll('option')].map(o => o.value)")), sorted(big))
    pg.locator('.qbtn[data-id="7"]').click(); pg.wait_for_timeout(900)
    t = pg.locator("form").filter(has=pg.locator("label", has_text="Data type")).locator("select").first
    vals = t.evaluate("s => [...s.options].map(o => o.value)")
    want = sorted({c[:2] for c in M.columns if re.match(r"\d\d_", c)} - {"06"})
    same("every data type once", sorted(vals), want)
    same("six topics", t.evaluate("s => [...s.querySelectorAll('optgroup')].map(g => g.label)"), ["Requests", "Processing time", "Exemptions", "Appeals", "Backlog", "Staff & costs"])
    same("no foia.gov numbers in the list", any(re.match(r"\d\d ·", x) for x in t.locator("option").all_inner_texts()), False)

    # ---- page address ----
    pg.goto(URL); pg.wait_for_selector(".qbtn"); pg.wait_for_timeout(3500)
    pick_agency("Department of Justice")
    cs = pg.locator(".gsel select").filter(has=pg.locator("option", has_text="All components (agency total)")).first
    cs.select_option(value="FBI"); pg.wait_for_timeout(900)
    pg.locator(".tl-p", has_text="Last 5").click(); pg.wait_for_timeout(700)
    pg.locator(".cmp select.cmp-agency").select_option(label="Department of State" if False else "U.S. Department of State"); pg.wait_for_timeout(900)
    pg.locator('.qbtn[data-id="2"]').click(); pg.wait_for_timeout(1000)
    url, want = pg.url, (head(), pg.locator(".chip").all_inner_texts(), label())
    p2 = ctx.new_page(); p2.goto(url); p2.wait_for_selector(".qbtn"); p2.wait_for_timeout(4000)
    same("link opens the same view", (p2.locator(".qhead").first.inner_text(), p2.locator(".chip").all_inner_texts(), p2.locator(".tl-label").inner_text()), want)
    p2.close()
    pg.goto(URL + "?" + urlencode({"q": 7, "agency": "Department of Justice", "m": "14_ProcessingTime__ComplexResponseTime.ResponseTimeMedianDaysValue"})); pg.wait_for_selector(".qbtn"); pg.wait_for_timeout(3500)
    same("link opens a measure", "Complex - Median Number of Days" in head(), True)

    # ---- CSV ----
    pg.goto(URL + "?" + urlencode({"q": 2, "agency": "Department of Justice"})); pg.wait_for_selector(".qbtn"); pg.wait_for_timeout(3500)
    pg.locator(".nav-tabs .nav-link", has_text="Tables").click(); pg.wait_for_timeout(400)
    pg.locator('.tvbtn[data-k="compare"]').click(); pg.wait_for_timeout(700)
    with pg.expect_download() as d:
        pg.locator(".csv").first.click()
    got = list(csvlib.DictReader(io.StringIO(Path(d.value.path()).read_text())))
    same("csv name", d.value.suggested_filename.endswith(".csv"), True)
    same("csv no helper column", "lt1" in got[0], False)
    ncomp = len(M[(M["Row Type"].isin(["component", "agency_overall"])) & (M.Agency == "Department of Justice") & (M.FY == 2025)])
    same("csv rows", len(got), ncomp)
    o = M[(M["Row Type"] == "agency_overall") & (M.Agency == "Department of Justice") & (M.FY == 2025)].iloc[0]
    row = next(r for r in got if r["Component"] == "(Agency total)")
    same("csv value", row["Complex median"] == str(num(o["14_ProcessingTime__ComplexResponseTime.ResponseTimeMedianDaysValue"])).removesuffix(".0") or abs(float(row["Complex median"]) - num(o["14_ProcessingTime__ComplexResponseTime.ResponseTimeMedianDaysValue"])) < 1e-6, True)
    lt = [c for c in got if "<1" in c.values()]
    want_lt = M[(M["Row Type"] == "component") & (M.Agency == "Department of Justice") & (M.FY == 2025)]
    n_lt = sum((want_lt[f"14_ProcessingTime__{t}ResponseTime.ResponseTimeMedianDaysValue"].str.strip() == "<1").sum() for t in ["Simple", "Complex", "Expedited"])
    same("csv keeps <1", sum(list(r.values()).count("<1") for r in got) >= n_lt, True)

    # ---- About ----
    pg.goto(URL + "?q=8"); pg.wait_for_selector(".qbtn"); pg.wait_for_timeout(3500)
    a = pg.locator(".about").inner_text()
    same("about shows", len(a) > 2500, True)
    same("about clean", BAD.search(a) is None, True)
    same("about revised count", "In 182 agency-years" in a, True)
    same("about share", "(91% of all requests)" in a, True)
    same("about cohort", "71 to 122 agencies" in a and "only 70 report in all 18 years" in a, True)
    same("no tabs on About", pg.locator(".nav-tabs").first.is_visible(), False)

    # ---- wording: no verdicts on agencies anywhere in the guide text ----
    pg.goto(URL); pg.wait_for_selector(".qbtn"); pg.wait_for_timeout(3500)
    text = ""
    for q in [0, 1, 2, 4, 5, 6, 3, 7]:
        if q:
            pg.locator(f'.qbtn[data-id="{q}"]').click(); pg.wait_for_timeout(800)
        text += " " + head() + " " + pg.locator(".tab-pane.active").first.inner_text()
    hits = re.findall(r"\b(worst|best|failing|failure|poor(?:ly)?|bad|good|slowest|fastest|shameful|delinquent|broken|collaps\w+)\b", text, re.I)
    same("no verdict words", hits, [])
    b.close()

problems += [f"page error: {e}" for e in errs]
print(f"{checked} checks, {len(problems)} problems")
for x in problems[:40]:
    print("  ", x)
sys.exit(1 if problems else 0)
