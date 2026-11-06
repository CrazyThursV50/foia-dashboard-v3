"""Build data/laws.json: the laws agencies relied on under Exemption 3 (annual report table 06).

Run after prep.py (it reads data/foia.json to name components the same way the page does).

Spelling differs a lot from report to report (1,588 ways of writing about 500 laws), so laws are grouped:
- by title and section of the first U.S. Code citation in the text, e.g. "8 U.S.C. § 1202(f) (Immigration and
  Nationality Act)" -> "8 U.S.C. § 1202". The first citation is the current one: reports write "X (formerly at Y)".
- sections the reports themselves say were renumbered go under the current number (RENUMBERED).
- text with no U.S. Code citation is matched by name where it is a known law (BY_NAME), otherwise kept as written.

Each law's description is the agencies' own words: its most used "Type of Information Withheld".
Each law's title and link come from law_links.csv (check_law_links.py): the section's own heading in the U.S. Code.
Nothing here is written by us: a law with no title in that file shows the agencies' words.

Usage: python prep_laws.py --statutes <exemption_statutes_06.csv> [--data data]
"""
import argparse
import datetime
import json
import re
from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
CITE = re.compile(r"(\d+)\s*(app\.?\s*)?§?\s*U\.?\s*S\.?\s*(?:C\.?|Code)\s*A?\.?(?:[\s,&§]|sec(?:tion|s)?\b\.?|(app(?:x|endix)?\b\.?))*s?(\d+[a-z]*(?:-\s?\d+[a-z]*)?)", re.I)
# sections the reports themselves give a newer number for, a range, or a slip the same text shows (CPSA is in title 15)
RENUMBERED = {"50 U.S.C. § 403-1": "50 U.S.C. § 3024", "50 U.S.C. § 403g": "50 U.S.C. § 3507", "50 U.S.C. § 403": "50 U.S.C. § 3507",
              "50 U.S.C. § 402": "50 U.S.C. § 3605", "41 U.S.C. § 253b": "41 U.S.C. § 4702", "41 U.S.C. § 423": "41 U.S.C. § 2102",
              "18 U.S.C. § 2510-20": "18 U.S.C. § 2510", "18 U.S.C. § 2510-2520": "18 U.S.C. § 2510",
              "5 U.S.C. § 2074c": "15 U.S.C. § 2074", "5 U.S.C. § 2074": "15 U.S.C. § 2074", "7 U.S.C. § 8791A": "7 U.S.C. § 8791"}
BY_NAME = [(re.compile(r"6\(e\)"), "Fed. R. Crim. P. 6(e)"), (re.compile(r"CIA Act|Central Intelligence Agency Act", re.I), "50 U.S.C. § 3507"),
           (re.compile(r"National Security Act", re.I), "50 U.S.C. § 3024"), (re.compile(r"National Security Agency Act", re.I), "50 U.S.C. § 3605")]
NO_LAW = {"", "none", "n/a", "na", "not applicable"}
NOT_NAMED = "Law not named in the report"


def group(text):
    """The law a report's text refers to."""
    t = " ".join(text.split())
    if t.lower() in NO_LAW or not re.search(r"[a-z0-9]", t, re.I):
        return NOT_NAMED
    m = CITE.search(t)
    if m:
        cite = f"{m[1]} U.S.C. {'app. ' if m[2] or m[3] else ''}§ {re.sub(r'-\s+', '-', m[4])}"
        return RENUMBERED.get(cite, cite)
    for pattern, law in BY_NAME:
        if pattern.search(t):
            return law
    return t


def main(statutes_csv, data):
    data = Path(data)
    s = pd.read_csv(statutes_csv, dtype=str, keep_default_na=False)
    s["n"] = pd.to_numeric(s["Number of Times Relied Upon"].str.replace(",", "").str.strip(), errors="coerce").fillna(0)
    s["FY"] = s["Fiscal Year"].astype(int)
    s = s[s["n"] > 0].copy()
    s["law"] = s["Statute"].map(group)

    # components are named as on the page: its Key tells apart two components that share a code
    ids = json.loads((data / "foia.json").read_text())["ids"]
    key_of = {(f, a, c, n): k for f, a, c, n, k, lv in zip(ids["FY"], ids["Agency"], ids["Component"], ids["Name"], ids["Key"], ids["level"]) if lv == "component"}
    ag = s[s["Row Type"] == "agency_overall"].assign(Key="")
    co = s[(s["Row Type"] == "component") & (s["Exclude From Component Sum"] == "")].copy()
    co["Key"] = [key_of.get(k) for k in zip(co["FY"], co["Agency"], co["Component"], co["Component Name"])]
    lost = co[co["Key"].isna()]
    co = co[co["Key"].notna()]

    # a roll-up row marked "Exclude From Component Sum" (Commerce FY2025: "DOC") is counted a second time in that year's
    # agency row (276 against 138 from its components; Exemption 3 says 136), so that agency-year uses its components
    twice = set(zip(*[s.loc[s["Exclude From Component Sum"] == "yes", c] for c in ("FY", "Agency")]))
    if twice:
        hit = lambda d: [k in twice for k in zip(d["FY"], d["Agency"])]
        ag = pd.concat([ag[[not x for x in hit(ag)]], co[hit(co)].assign(Key="")])
        print("agency rows taken from components:", sorted(twice))

    # the agencies' own words for each law: the description used most (over all years)
    types = ag[~ag["Type of Information Withheld"].str.strip().str.lower().isin(NO_LAW)]
    desc = types.groupby(["law", "Type of Information Withheld"])["n"].sum().reset_index().sort_values("n", ascending=False).drop_duplicates("law").set_index("law")["Type of Information Withheld"]

    # titles and links checked by check_law_links.py (only pages that answered)
    links = {}
    if (HERE / "law_links.csv").exists():
        k = pd.read_csv(HERE / "law_links.csv", dtype=str, keep_default_na=False)
        links = {r.cite: {"title": r.title, "url": r.url} for r in k[k.status == "200"].itertuples()}
    both = pd.concat([ag, co])
    laws = sorted(both["law"].unique())
    law_id = {x: i for i, x in enumerate(laws)}
    agencies = sorted(both["Agency"].unique())
    a_id = {x: i for i, x in enumerate(agencies)}
    keys = sorted(k for k in both["Key"].unique() if k)
    k_id = {x: i for i, x in enumerate(keys)}
    rows = both.groupby(["FY", "Agency", "Key", "law"], as_index=False)["n"].sum()
    blob = {"built": datetime.date.today().isoformat(),
            "laws": [{"cite": x, "title": links.get(x, {}).get("title", ""), "url": links.get(x, {}).get("url", ""), "desc": " ".join(str(desc.get(x, "")).split())} for x in laws],
            "agencies": agencies, "keys": keys, "abbr": dict(zip(s["Agency"], s["Agency Abbreviation"])),
            "rows": {"FY": rows["FY"].tolist(), "a": rows["Agency"].map(a_id).tolist(), "k": [k_id.get(k, -1) for k in rows["Key"]],
                     "law": rows["law"].map(law_id).tolist(), "n": [int(x) if float(x).is_integer() else float(x) for x in rows["n"]]}}
    (data / "laws.json").write_text(json.dumps(blob, separators=(",", ":"), ensure_ascii=False))
    print(f"{s['Statute'].nunique():,} spellings -> {len(laws):,} laws | {sum(x in links for x in laws)} with a checked link | rows {len(rows):,} | {(data / 'laws.json').stat().st_size:,} bytes")
    print(f"component rows with no component on the page: {len(lost)} ({int(lost['n'].sum())} times)")
    return ag, co, desc


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Build the Exemption 3 laws file.")
    ap.add_argument("--statutes", required=True, help="fa26/dataset/component_level/exemption_statutes_06.csv")
    ap.add_argument("--data", default=str(HERE / "data"), help="folder with foia.json (default: data/ next to this script)")
    args = ap.parse_args()
    main(args.statutes, args.data)
