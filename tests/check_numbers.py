"""Cross-check the dashboard against the source tables.

Opens the page (needs the local server: python serve.py), picks agencies / components / years,
reads the "Chart data" tables of questions 1, 3, 5 and 6, and compares every cell with numbers
computed here straight from the component table (not from data/foia.json).
Before that, the agency totals used here are compared with the agency-level table (foia.gov's CSV export),
which the page does not read.

Usage: python tests/check_numbers.py [webkit|chromium] [component table]
(the component table defaults to the one in the team repo; pass the one prep.py was given if it differs)
"""
import random
import re
import sys
from pathlib import Path

import pandas as pd
from playwright.sync_api import sync_playwright

R = Path.home() / "ds-muckrock-liberation/fa26/dataset"
URL = "http://127.0.0.1:8767/_site/index.html?t=check"


def num(s):
    s = s.astype(str).str.strip().replace({"<1": "0.5"})
    return pd.to_numeric(s.str.replace(",", ""), errors="coerce")


# ---- source tables -> one long frame: level, Agency, Component, FY, measures ----
COMPONENTS = Path(sys.argv[2]) if len(sys.argv) > 2 else R / "component_level/component_master_no_03_06_11.csv"
c = pd.read_csv(COMPONENTS, dtype=str, keep_default_na=False)
a = c[c["Row Type"] == "agency_overall"]
# a component's second entry in a table counts toward it (all the measures used here are counts or amounts);
# rows linked to no component and the excluded row are not components
c = c[c["Row Type"].isin(["component", "second_entry"]) & (c["Exclude From Component Sum"] == "") & (c.Component != "")]
# measure -> (component-table column, agency-level-table column)
COLS = {"received": ("01_Requests__ProcessingStatisticsReceivedQuantity", "requests__Number of Requests Received in Fiscal Year"),
    "processed": ("01_Requests__ProcessingStatisticsProcessedQuantity", "requests__Number of Requests Processed in Fiscal Year"),
    "backlog": ("26_Backlog__BackloggedRequestQuantity", "backlog__Number of Backlogged Requests as of End of Fiscal Year"),
    "last_backlog": ("30_ComparisonsRequestsBacklogged__BacklogLastYearQuantity",
                     "backlog_requests_vs_prev_year__Number of Backlogged Requests as of End of the Fiscal Year from Previous Annual Report"),
    "staff": ("22_Personnel__TotalFullTimeStaffQuantity", 'personnel__Total Number of "Full-Time FOIA Staff"'),
    "cost": ("23_Costs__TotalCostAmount", "costs_fees__Total Costs"),
    "affirmed": ("08_AppealsDisposition__AppealDispositionAffirmedQuantity", "appeals_disposition__Number Affirmed on Appeal"),
    "partial": ("08_AppealsDisposition__AppealDispositionPartialQuantity",
                "appeals_disposition__Number Partially Affirmed & Partially Reversed/Remanded on Appeal"),
    "reversed": ("08_AppealsDisposition__AppealDispositionReversedQuantity", "appeals_disposition__Number Completely Reversed/Remanded on Appeal"),
    "other": ("08_AppealsDisposition__AppealDispositionOtherQuantity", "appeals_disposition__Number of Appeals Closed for Other Reasons")}
MEASURES = list(COLS)
frame = lambda d, level, ids, k: pd.DataFrame({"level": level, **ids, "FY": d["Fiscal Year"].astype(int), **{m: num(d[v[k]]) for m, v in COLS.items()}})
AG = frame(a, "agency", {"Agency": a.Agency, "Component": "", "Key": "", "Name": ""}, 0)
CO = frame(c, "component", {"Agency": c.Agency, "Component": c.Component, "Name": c["Component Name"]}, 0)
# the agency totals used here against the agency-level table, which the page does not read: they must agree
csv = pd.read_csv(R / "agency_level/FOIA_agency_FY2008-2025.csv", dtype=str, keep_default_na=False)
both = AG.merge(frame(csv, "agency", {"Agency": csv.Agency}, 1), on=["Agency", "FY"], how="outer", suffixes=("", "_csv"), indicator=True)
assert len(both) == len(AG) == len(csv) and (both._merge == "both").all(), "agency-years differ from the agency-level table"
off = [(r.Agency, r.FY, m) for r in both.itertuples() for m in MEASURES
       if not (pd.isna(getattr(r, m)) and pd.isna(getattr(r, m + "_csv")) or getattr(r, m) == getattr(r, m + "_csv"))]
assert not off, f"agency totals differ from the agency-level table: {off[:5]}"
print(f"agency totals vs agency-level table: {len(both) * len(MEASURES)} values, 0 different")
CO = CO.groupby(["level", "Agency", "Component", "Name", "FY"], as_index=False)[MEASURES].sum(min_count=1)
shared = CO.groupby(["Agency", "Component"]).Name.nunique()
shared = set(shared[shared > 1].index)  # one code used for two components (USPS "PS"): told apart by name
CO["Key"] = [f"{k} · {n}" if (a_, k) in shared else k for a_, k, n in zip(CO.Agency, CO.Component, CO.Name)]
ALLROWS = pd.concat([AG, CO], ignore_index=True)
# backlog as restated in the next year's report
nxt = ALLROWS[["level", "Agency", "Key", "FY", "last_backlog"]].assign(FY=lambda d: d.FY - 1).rename(columns={"last_backlog": "restated"})
ALLROWS = ALLROWS.merge(nxt, on=["level", "Agency", "Key", "FY"], how="left")
years = AG.groupby("Agency").FY.nunique()
COHORT = set(years[years == AG.FY.nunique()].index)


def sel_rows(kind, agency=None, comp=None, cohort=False):
    if kind == "total":
        d = ALLROWS[ALLROWS.level == "agency"]
        return d[d.Agency.isin(COHORT)] if cohort else d
    if kind == "agency":
        return ALLROWS[(ALLROWS.level == "agency") & (ALLROWS.Agency == agency)]
    return ALLROWS[(ALLROWS.level == "component") & (ALLROWS.Agency == agency) & (ALLROWS.Key == comp)]


def tot(s):
    return s.sum() if s.notna().any() else None


def expected(q, rows, lo, hi, kind, agency):
    out = {}
    for fy in range(lo, hi + 1):
        v = rows[rows.FY == fy]
        if v.empty:
            continue
        if q == 1:
            rec, pro = tot(v.received), tot(v.processed)
            e = {"Received": rec, "Processed": pro, "Processed ÷ received": pro / rec if rec else None}
            if kind == "total":
                e["Agencies reporting"] = int(v.received.notna().sum())
            elif kind == "agency":
                allr = AG[AG.FY == fy].received.sum()
                e["Share of all federal requests"] = rec / allr if rec is not None else None
            else:
                base = AG[(AG.FY == fy) & (AG.Agency == agency)].received
                e[f"Share of {agency}'s requests"] = rec / base.iloc[0] if rec is not None and len(base) and base.iloc[0] else None
        elif q == 3:
            b = v[v.backlog.notna()]
            e = {"Backlog": tot(v.backlog), "Requests received": tot(v.received), "FOIA staff": tot(v.staff), "Total cost ($)": tot(v.cost),
                 "Backlog as revised next year": (b.restated.fillna(b.backlog)).sum() if b.restated.notna().any() else None}
        elif q == 5:
            p, r, af = tot(v.partial), tot(v.reversed), tot(v.affirmed)
            rev = (p or 0) + (r or 0)
            den = (af or 0) + rev
            e = {"Affirmed": af, "Partly reversed": p, "Fully reversed": r, "Closed for other reasons": tot(v.other),
                 "Reversal rate": rev / den if den else None}
        elif q == 6:
            e = {"Backlog": tot(v.backlog), "Requests received": tot(v.received)}
            for col, name in [("backlog", "Backlog change"), ("received", "Received change")]:
                now, before = v[v[col].notna()], rows[(rows.FY == fy - 1) & rows[col].notna()]
                k = lambda d: d.level + "|" + d.Agency + "|" + d.Key
                both = set(k(now)) & set(k(before))
                if both:
                    n1 = now[k(now).isin(both)][col].sum(); n0 = before[k(before).isin(both)][col].sum()
                    e[name] = n1 / n0 - 1 if n0 else None
        out[fy] = e
    return out


def parse(text):
    t = text.strip().replace(",", "").replace("\u2212", "-")  # d3 writes minus as U+2212
    if t in ("", "–"):
        return None
    if t.endswith("%"):
        return float(t[:-1].replace("+", "")) / 100
    try:
        return float(t)
    except ValueError:
        return t


def close(page_v, exp_v, header):
    if exp_v is None or (isinstance(exp_v, float) and pd.isna(exp_v)):
        return page_v is None
    if page_v is None:
        return False
    if "÷" in header or "rate" in header.lower() or "Share" in header or "change" in header:
        tol = 0.0051 if "Share" not in header else 0.00051   # page shows whole or one-decimal percents
        return abs(page_v - exp_v) <= tol + 1e-9
    return abs(page_v - exp_v) <= max(0.51, abs(exp_v) * 1e-9)  # page rounds counts and dollars


def read_chart_table(pg):
    return pg.evaluate("""() => {
      const t = document.querySelector('.tab-pane.active .tcap table');
      const keep = el => !el.querySelector('input[type=checkbox]');  // the hidden row-checkbox column
      const heads = [...t.querySelectorAll('thead th')].filter(keep).map(th => th.textContent.replace(/[▴▾]/g, '').trim());
      const rows = [...t.querySelectorAll('tbody tr')].map(tr => [...tr.querySelectorAll('td')].filter(keep).map(td => td.textContent));
      return {heads, rows};
    }""")


def main(engine):
    random.seed(7)
    comps = CO.groupby(["Agency", "Key"]).size().reset_index()
    picks = [("total", None, None, False), ("total", None, None, True)]
    picks += [("agency", x, None, False) for x in ["Department of Homeland Security", "Department of Veterans Affairs",
              "National Archives and Records Administration", "Central Intelligence Agency", "Administrative Conference of the United States"]]
    picks += [("component", r.Agency, r.Key, False) for r in comps.sample(6, random_state=7).itertuples()]
    picks += [("component", "Department of Justice", "FBI", False), ("component", "Department of Homeland Security", "USCIS", False),
              ("component", "United States Postal Service", "PS · USPS Field Office", False)]
    ranges = [(2008, 2025), (2015, 2020), (2025, 2025)]
    bad, checked = [], 0
    with sync_playwright() as p:
        b = getattr(p, engine).launch()
        pg = b.new_page(viewport={"width": 1456, "height": 900})
        pg.goto(URL); pg.wait_for_timeout(6000)
        agency_sel = lambda: pg.locator("select").filter(has=pg.locator("option", has_text="Department of Justice")).first
        for kind, agency, comp, cohort in picks:
            agency_sel().select_option(index=0 if kind == "total" else None, label=None if kind == "total" else agency)
            pg.wait_for_timeout(900)
            if kind == "total":
                pg.locator("input[type=radio]").filter(has_text="").nth(0)
                pg.evaluate("""(c) => { const r = [...document.querySelectorAll('input[type=radio]')].find(x => x.parentElement.textContent.includes(c ? 'agencies that reported all' : 'All reporting')); r.click(); }""", cohort)
                pg.wait_for_timeout(700)
            # full year range first, so components that existed only in early years are in the list
            pg.evaluate("""() => { document.querySelector(`.tl-y[data-y="${2008}"]`).click(); document.querySelector(`.tl-y[data-y="${2025}"]`).click(); }""")
            pg.wait_for_timeout(600)
            if kind == "component":
                cs = pg.locator("select").filter(has=pg.locator("option", has_text="All components (agency total)")).first
                labels = cs.locator("option").all_inner_texts()
                last = CO[(CO.Agency == agency) & (CO.Key == comp)].sort_values("FY").iloc[-1]
                lab = next((l for l in labels if l == f"{last.Name} ({last.Component})"), None)
                if lab is None:
                    bad.append(f"{agency} › {comp}: not in the component list"); continue
                cs.select_option(label=lab); pg.wait_for_timeout(900)
            for lo, hi in ranges:
                pg.evaluate("""([lo, hi]) => { document.querySelector(`.tl-y[data-y="${lo}"]`).click(); document.querySelector(`.tl-y[data-y="${hi}"]`).click(); }""", [lo, hi])
                pg.wait_for_timeout(800)
                rows = sel_rows(kind, agency, comp, cohort)
                for q in [1, 3, 5, 6]:
                    btn = pg.locator(f'.qbtn[data-id="{q}"]')
                    if "on" not in (btn.get_attribute("class") or ""):
                        btn.click(); pg.wait_for_timeout(900)
                    pg.locator(".nav-tabs .nav-link", has_text="Tables").click(); pg.wait_for_timeout(300)
                    pg.locator('.tvbtn[data-k="chart"]').click(); pg.wait_for_timeout(500)
                    t = read_chart_table(pg)
                    exp = expected(q, rows, lo, hi, kind, agency)
                    page_years = {int(r[0]) for r in t["rows"]}
                    exp_years = {fy for fy, e in exp.items() if any(v is not None and not (isinstance(v, float) and pd.isna(v)) for v in e.values())}
                    if q != 6 and not exp_years <= page_years:
                        bad.append(f"{kind} {agency} {comp} Q{q} {lo}-{hi}: years missing on page {sorted(exp_years - page_years)}")
                    for r in t["rows"]:
                        fy = int(r[0])
                        for h, cell in zip(t["heads"][1:], r[1:]):
                            if h not in exp.get(fy, {}):
                                continue
                            checked += 1
                            if not close(parse(cell), exp[fy][h], h):
                                bad.append(f"{kind} {agency or ''} {comp or ''} cohort={cohort} Q{q} FY{fy} {h}: page={cell!r} expected={exp[fy][h]}")
                    pg.locator(".nav-tabs .nav-link", has_text="Chart").click(); pg.wait_for_timeout(200)
        b.close()
    print(f"{engine}: {checked} cells checked, {len(bad)} problems")
    from collections import Counter
    groups = Counter(" ".join(x.split(" FY")[0].split()[:6]) for x in bad)
    for g, n in groups.most_common(40):
        print(f"   {n:5d}  {g}")
    for x in bad[:0]:
        print("  ", x)
    return len(bad)


if __name__ == "__main__":
    sys.exit(1 if main(sys.argv[1] if len(sys.argv) > 1 else "chromium") else 0)
