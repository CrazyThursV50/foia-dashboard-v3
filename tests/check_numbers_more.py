"""Cross-check questions 2 and 4 and Explore against the component table (check_numbers.py covers 1, 3, 5 and 6).

Opens the page (needs the local server: python serve.py), picks agencies / components / years, reads the
"Numbers in the chart" tables and compares every cell with numbers computed here straight from the component
table (not from data/foia.json):
- Q2: requests processed by days taken (simple, complex, expedited) and the median days;
- Q4: shares of processed requests by outcome, and exemptions used;
- Explore: a set of measures (counts, dollar amounts, staff, medians, averages), value per year and how many
  agencies or components report it.

Usage: python tests/check_numbers_more.py [webkit|chromium] [page URL]
"""
import random
import re
import sys
from collections import Counter
from pathlib import Path

import pandas as pd
from playwright.sync_api import sync_playwright

R = Path.home() / "ds-muckrock-liberation/fa26/dataset"
URL = sys.argv[2] if len(sys.argv) > 2 else "http://127.0.0.1:8767/_site/index.html?t=more"
NOT_ADDABLE = re.compile(r"Days|Median|Average|Highest|Lowest|Percent|OldItem")


def num(s):
    s = s.astype(str).str.strip().replace({"<1": "0.5"})
    return pd.to_numeric(s.str.replace(",", ""), errors="coerce")


# ---- the component table -> agency rows and component rows (second entries merged) ----
m = pd.read_csv(R / "component_level/component_master_no_03_06_11.csv", dtype=str, keep_default_na=False)
BUCKETS = ["1-20", "21-40", "41-60", "61-80", "81-100", "101-120", "121-140", "141-160", "161-180", "181-200", "201-300", "301-400", "401+"]
TRACKS = {"Simple": ("16_SimpleRequests", "SimpleResponseTime"), "Complex": ("17_ComplexRequests", "ComplexResponseTime"),
          "Expedited": ("18_ExpeditedRequests", "ExpeditedResponseTime")}
BCOL = {(t, b): f"{inc}__TimeIncrementProcessedQuantity[{b}]" for t, (inc, _) in TRACKS.items() for b in BUCKETS}
MED = {t: f"14_ProcessingTime__{rt}.ResponseTimeMedianDaysValue" for t, (_, rt) in TRACKS.items()}
OUTCOMES = {"Full grant": "02_Disposition__RequestDispositionFullGrantQuantity",
            "Partial grant / partial denial": "02_Disposition__RequestDispositionPartialGrantQuantity",
            "Full denial (exemptions)": "02_Disposition__RequestDispositionFullExemptionDenialQuantity",
            **{x: f"02_Disposition__NonExemptionDenialQuantity[{k}]" for x, k in [
                ("No records", "NoRecords"), ("Withdrawn", "Withdrawn"), ("Referred", "Referred"), ("Fee-related", "FeeRelated"),
                ("Not reasonably described", "NotDescribed"), ("Improper request", "ImproperRequest"), ("Not agency record", "NotAgency"),
                ("Duplicate", "Duplicate"), ("Other", "Other")]}}
MAIN = ["Full grant", "Partial grant / partial denial", "Full denial (exemptions)", "No records", "Withdrawn"]
EXCOLS = {re.search(r"\[(.*)\]", c)[1]: c for c in m.columns if c.startswith("05_Exemptions__AppliedExemptionQuantity[")}
PROCESSED = "01_Requests__ProcessingStatisticsProcessedQuantity"
random.seed(11)
addable_cols = [c for c in m.columns if re.match(r"\d\d_", c) and not NOT_ADDABLE.search(c.split("__", 1)[1])]
EXPLORE = ["01_Requests__ProcessingStatisticsReceivedQuantity", "23_Costs__TotalCostAmount", "22_Personnel__TotalFullTimeStaffQuantity",
           "05_Exemptions__AppliedExemptionQuantity[Ex. 7(C)]", "21_FeeWaiver__AdjudicationMedianDaysValue",
           "21_FeeWaiver__AdjudicationAverageDaysValue",
           "19_PendingRequests__ComplexPendingRequestStatistics.PendingRequestMedianDaysValue",
           "14_ProcessingTime__SimpleResponseTime.ResponseTimeMedianDaysValue",
           *random.sample([c for c in addable_cols if not c.startswith(("01_", "23_", "22_"))], 4)]
NEED = sorted(set(BCOL.values()) | set(MED.values()) | set(OUTCOMES.values()) | set(EXCOLS.values()) | set(EXPLORE) | {PROCESSED})

a = m[m["Row Type"] == "agency_overall"]
AG = pd.DataFrame({"Agency": a.Agency, "FY": a["Fiscal Year"].astype(int), **{c: num(a[c]) for c in NEED}})
c = m[m["Row Type"].isin(["component", "second_entry"]) & (m["Exclude From Component Sum"] == "") & (m.Component != "")]
c = c.assign(order=(c["Row Type"] != "component").astype(int)).sort_values("order", kind="stable")  # the component row first
CO = pd.DataFrame({"Agency": c.Agency, "Component": c.Component, "Name": c["Component Name"], "FY": c["Fiscal Year"].astype(int),
                   **{x: num(c[x]) for x in NEED}})
g = CO.groupby(["Agency", "Component", "Name", "FY"], sort=False)
add = [x for x in NEED if not NOT_ADDABLE.search(x.split("__", 1)[1])]
CO = pd.concat([g[add].sum(min_count=1), g[[x for x in NEED if x not in add]].first()], axis=1).reset_index()  # first: first non-blank
shared = CO.groupby(["Agency", "Component"]).Name.nunique()
shared = set(shared[shared > 1].index)
CO["Key"] = [f"{k} · {n}" if (x, k) in shared else k for x, k, n in zip(CO.Agency, CO.Component, CO.Name)]
years = AG.groupby("Agency").FY.nunique()
COHORT = set(years[years == AG.FY.nunique()].index)


def sel_rows(kind, agency=None, comp=None, cohort=False):
    if kind == "total":
        return AG[AG.Agency.isin(COHORT)] if cohort else AG
    if kind == "agency":
        return AG[AG.Agency == agency]
    return CO[(CO.Agency == agency) & (CO.Key == comp)]


def nsum(s):  # d3.sum: missing values skipped, 0 when there are none
    return float(s.sum()) if s.notna().any() else 0.0


def tables_q2(kind, agency, rows, lo, hi, cohort):
    v = rows[rows.FY == hi]
    by_range = {}
    for t in TRACKS:
        n = {b: nsum(v[BCOL[(t, b)]]) for b in BUCKETS}
        tot = sum(n.values())
        for b in BUCKETS:
            lab = "≤20 days" if b == "1-20" else b.replace("-", "–") + " days"
            by_range.setdefault(lab, {})[t] = n[b]
            by_range[lab][f"{t} %"] = n[b] / tot if tot else None
    if kind == "total":
        p = (AG[AG.Agency.isin(COHORT)] if cohort else AG)
        p = p[(p.FY == hi) & p[PROCESSED].notna()].sort_values(PROCESSED, ascending=False).head(15)
        med = {r["Agency"]: {f"{t} median": r[MED[t]] for t in ["Simple", "Complex"]} for r in p.to_dict("records")}
        med = {k: {h: (None if pd.isna(x) else x) for h, x in e.items()} for k, e in med.items() if any(pd.notna(x) for x in e.values())}
    else:
        med = {}
        for fy in range(lo, hi + 1):
            r = rows[rows.FY == fy]
            e = {f"{t} median": (r[MED[t]].iloc[0] if len(r) and pd.notna(r[MED[t]].iloc[0]) else None) for t in TRACKS}
            if any(x is not None for x in e.values()):
                med[str(fy)] = e
    return [by_range, med]


def tables_q4(rows, lo, hi):
    share = {}
    for fy in range(lo, hi + 1):
        v = rows[rows.FY == fy]
        if v.empty:
            continue
        n = {k: nsum(v[col]) for k, col in OUTCOMES.items()}
        tot = sum(n.values())
        e = {"Processed (categories added)": tot}
        for k in MAIN:
            e[k] = n[k] / tot if tot else None
        e["All other"] = sum(n[k] for k in OUTCOMES if k not in MAIN) / tot if tot else None
        share[str(fy)] = e
    v = rows[rows.FY == hi]
    ex = {e: {"Times applied": nsum(v[col])} for e, col in EXCOLS.items() if nsum(v[col]) > 0}
    return [share, ex]


def table_x(kind, agency, rows, lo, hi, cohort, col):
    addable = not NOT_ADDABLE.search(col.split("__", 1)[1])
    scope = (AG[AG.Agency.isin(COHORT)] if cohort else AG) if kind == "total" else CO[CO.Agency == agency]
    unit = "Agencies" if kind == "total" else "Components"
    out = {}
    for fy in range(lo, hi + 1):
        v = rows[(rows.FY == fy) & rows[col].notna()]
        sc = scope[scope.FY == fy]
        has_series = not (kind == "total" and not addable)
        if not (has_series and len(v)) and not len(sc):
            continue
        e = {"value": float(v[col].sum()) if has_series and len(v) else None}
        if kind == "total" and has_series:
            e["Agencies added up"] = len(v) if len(v) else None
        if len(sc):
            e[f"{unit} reporting"] = f"{int(sc[col].notna().sum())} of {len(sc)}"
        out[str(fy)] = e
    return [out]


def parse(text):
    t = text.strip().replace(",", "").replace("−", "-")
    if t in ("", "–"):
        return None
    if t == "<1":
        return 0.5
    if t.endswith("%"):
        return float(t[:-1].replace("+", "")) / 100
    try:
        return float(t)
    except ValueError:
        return t


def same(page, exp, header):
    if exp is None or (isinstance(exp, float) and pd.isna(exp)):
        return page is None
    if isinstance(exp, str) or page is None or isinstance(page, str):
        return page == exp
    tol = 0.0051 if header.endswith("%") or header in MAIN or header == "All other" else 0.0051 + abs(exp) * 1e-9
    return abs(page - exp) <= tol


READ = """() => [...document.querySelectorAll('.tab-pane.active .tcap')].map(cap => {
  const t = cap.querySelector('table');
  if (!t) return {title: cap.querySelector('h6')?.textContent || '', heads: [], rows: []};
  const keep = el => !el.querySelector('input[type=checkbox]');
  return {title: cap.querySelector('h6')?.textContent || '',
          heads: [...t.querySelectorAll('thead th')].filter(keep).map(th => th.textContent.replace(/[▴▾]/g, '').trim()),
          rows: [...t.querySelectorAll('tbody tr')].map(tr => [...tr.querySelectorAll('td')].filter(keep).map(td => td.textContent))};
})"""


def compare(where, page_tables, exp_tables, label=None):
    bad, n = [], 0
    for i, exp in enumerate(exp_tables):
        if i >= len(page_tables):
            if exp:
                bad.append(f"{where}: table {i + 1} missing on the page")
            continue
        t = page_tables[i]
        got = {r[0]: dict(zip(t["heads"][1:], r[1:])) for r in t["rows"] if r != ["No results."]}  # an empty table's placeholder
        if set(got) != set(exp):
            bad.append(f"{where} table {i + 1}: rows on page {sorted(set(got) - set(exp))[:4]}, missing {sorted(set(exp) - set(got))[:4]}")
        for k, e in exp.items():
            for h, x in e.items():
                h_page = label if h == "value" else h
                if k not in got or h_page not in got[k]:
                    if k in got:
                        bad.append(f"{where} table {i + 1} {k}: column {h_page!r} missing")
                    continue
                n += 1
                if not same(parse(got[k][h_page]), x, h_page):
                    bad.append(f"{where} table {i + 1} {k} {h_page}: page={got[k][h_page]!r} expected={x}")
    return bad, n


def main(engine):
    picks = [("total", None, None, False), ("total", None, None, True)]
    picks += [("agency", x, None, False) for x in ["Department of Homeland Security", "Small Business Administration",
              "Council on Environmental Quality", "National Archives and Records Administration", "Department of Justice"]]
    comps = CO.groupby(["Agency", "Key"]).size().reset_index()
    picks += [("component", r.Agency, r.Key, False) for r in comps.sample(3, random_state=11).itertuples()]
    picks += [("component", "Department of Justice", "FBI", False), ("component", "United States Postal Service", "PS · USPS Field Office", False)]
    ranges = [(2008, 2025), (2021, 2023)]
    bad, checked = [], 0
    with sync_playwright() as p:
        b = getattr(p, engine).launch()
        pg = b.new_page(viewport={"width": 1456, "height": 900})
        pg.goto(URL); pg.wait_for_timeout(6000)
        form = lambda name: pg.locator("form").filter(has=pg.locator("label", has_text=name)).locator("select").first
        set_years = lambda lo, hi: pg.evaluate("""([lo, hi]) => { document.querySelector(`.tl-y[data-y="${lo}"]`).click(); document.querySelector(`.tl-y[data-y="${hi}"]`).click(); }""", [lo, hi])
        for kind, agency, comp, cohort in picks:
            ag_sel = pg.locator("select").filter(has=pg.locator("option", has_text="Department of Justice")).first
            if kind == "total":
                ag_sel.select_option(index=0); pg.wait_for_timeout(900)
                pg.evaluate("""(c) => [...document.querySelectorAll('input[type=radio]')].find(x => x.parentElement.textContent.includes(c ? 'agencies that reported all' : 'All reporting')).click()""", cohort)
                pg.wait_for_timeout(700)
            else:
                ag_sel.select_option(label=agency); pg.wait_for_timeout(900)
            set_years(2008, 2025); pg.wait_for_timeout(600)
            if kind == "component":
                cs = pg.locator("select").filter(has=pg.locator("option", has_text="All components (agency total)")).first
                last = CO[(CO.Agency == agency) & (CO.Key == comp)].sort_values("FY").iloc[-1]
                lab = f"{last.Name} ({last.Component})"
                if lab not in cs.locator("option").all_inner_texts():
                    bad.append(f"{agency} › {comp}: not in the component list"); continue
                cs.select_option(label=lab); pg.wait_for_timeout(900)
            elif kind == "agency":
                cs = pg.locator("select").filter(has=pg.locator("option", has_text="All components (agency total)"))
                if cs.count():
                    cs.first.select_option(index=0); pg.wait_for_timeout(600)
            rows = sel_rows(kind, agency, comp, cohort)
            for lo, hi in ranges:
                set_years(lo, hi); pg.wait_for_timeout(800)
                who = f"{kind} {agency or ''} {comp or ''} cohort={cohort} {lo}-{hi}"
                for q in [2, 4, 7]:
                    btn = pg.locator(f'.qbtn[data-id="{q}"]')
                    if "on" not in (btn.get_attribute("class") or ""):
                        btn.click(); pg.wait_for_timeout(900)
                    cols = EXPLORE if q == 7 else [None]
                    for col in cols:
                        label = None
                        if col:
                            no = col[:2]
                            t = form("Data type")
                            t.select_option(value=no)
                            pg.wait_for_timeout(700)
                            ms = form("Measure")
                            # the page lists a type's measures in table column order: pick by position, read the label
                            keys = [x for x in m.columns if x.startswith(no + "_") and not x.endswith("ReceiptDate")]
                            labels = ms.locator("option").all_inner_texts()
                            if len(keys) != len(labels):
                                bad.append(f"{who} Explore {col}: {len(labels)} measures on the page, {len(keys)} in the table"); continue
                            label = labels[keys.index(col)]
                            ms.select_option(index=keys.index(col)); pg.wait_for_timeout(800)
                        pg.locator(".nav-tabs .nav-link", has_text="Tables").click(); pg.wait_for_timeout(300)
                        pg.locator('.tvbtn[data-k="chart"]').click(); pg.wait_for_timeout(500)
                        page_tables = pg.evaluate(READ)
                        if q == 2:
                            exp = tables_q2(kind, agency, rows, lo, hi, cohort)
                        elif q == 4:
                            exp = tables_q4(rows, lo, hi)
                        else:
                            exp = table_x(kind, agency, rows, lo, hi, cohort, col)
                        x, n = compare(f"{who} Q{q}{' ' + col if col else ''}", page_tables, exp, label)
                        bad += x; checked += n
                        pg.locator(".nav-tabs .nav-link", has_text="Chart").click(); pg.wait_for_timeout(200)
        b.close()
    print(f"{engine}: {checked} cells checked, {len(bad)} problems")
    for g_, n in Counter(" ".join(x.split(":")[0].split()[:8]) for x in bad).most_common(30):
        print(f"   {n:5d}  {g_}")
    for x in bad[:15]:
        print("  ", x)
    return len(bad)


if __name__ == "__main__":
    sys.exit(1 if main(sys.argv[1] if len(sys.argv) > 1 else "chromium") else 0)
