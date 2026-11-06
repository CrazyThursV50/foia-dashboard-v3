# Federal FOIA Dashboard (v3: v2 plus the laws behind Exemption 3)

One page for federal FOIA processing data from foia.gov's annual reports, at agency and component level. The years shown, the year pickers and the agency counts come from the data, so a rebuild with a new year needs no change to the page.

## What v3 adds to v2
Step 3 has a second view, "Laws behind Exemption 3": the laws relied on most in the last year chosen, the five most used over time, and a full list in the Tables tab. Names are titles from the U.S. Code and link to the law's text; the agencies' own words are in the hover text and the table. `../dashboard-v2/` is kept as it was.

## What changed from the prototype
The prototype in `../dashboard-prototype/` (also the public preview site) is kept as it was. This copy changes how the page reads, not the data: `data/foia.json` is the same file.
- Start page: six cards in the client's order (requests, response time, outcomes and exemptions, appeals, backlog, staff and cost) instead of a blank panel.
- Each step has a reading guide (how to read it, not what to conclude) and Back / Next buttons.
- Years: presets and a clickable strip at the top of the page instead of two dropdowns.
- Agency and component lists: largest first, the rest alphabetical. Explore: six plain topics instead of foia.gov's numbers.
- The top of the page says whether a number is an agency total or a component, and warns when a comparison overlaps.
- Appeals: both reversal rates are shown, whichever base the charts use.
- "Days" are labelled as working days; exemptions have plain names; new "About the data" page.
- Tables can be downloaded as CSV; the page address holds the view, so it can be shared.
- Not done: phone layout, Exemption 3 statutes, the written "other" reasons.

## What the page does
- **Sidebar**: Overview, the six steps, "Explore all data" and "About the data"; then an agency, one of its components, and up to
  five agencies or components to compare with (choosing an agency adds it; choosing one of its components then replaces it with that component).
- **Top of the page**: the question, one sentence with the last year's numbers, the fiscal years, Back / Next and "Copy link to this view".
- **Overview**: the key number of each step for the last year chosen, one sentence, and a small trend chart. Rates get a grey reference line
  (all agencies, or the agency's total for a component). It follows the agency, component and years chosen.
- **A step**: a reading guide, a Chart tab (two charts; with "Compare with", both charts compare what is selected), a Tables tab
  (numbers in the chart / related report tables / all agencies or components for one year), and a tab on how the comparison is made.
- **One or two years chosen**: trend charts turn into bars, since a line would be a single dot or one straight segment.

## Files
- `index.qmd`: the dashboard (Quarto dashboard with Observable JS charts).
- `prep.py`: builds `data/foia.json` from the component master table: its Agency Overall rows (agency rows) and its component rows.
- `prep_laws.py`: builds `data/laws.json` from report table 06: groups the many spellings of each law, and keeps the agencies' own descriptions.
- `check_law_links.py`, `law_links.csv`: each law's link and its own title in the U.S. Code (Cornell's Legal Information Institute). Only links that answered go on the page. Nothing in the names is written by us.
- `column_mapping.csv`: foia.gov's CSV column name for each component-table column (the readable labels).
- `styles.css`, `_quarto.yml`: page style and Quarto project settings (output goes to `_site/`).
- `assets/muckrock-logo.svg`: the logotype on the About page (taken from muckrock.com).
- `serve.py`: local preview server that tells the browser not to cache.
- `tests/check_numbers.py`: reads the tables on the page and compares every cell with numbers computed
  straight from the component table; first checks that its agency totals agree with the agency-level table.
- `tests/check_numbers_more.py`: the same for questions 2 and 4 and for Explore (a set of measures).
- `tests/check_edges.py`: runs every view under unusual settings (one year, reversed years, agencies
  without components, small agencies, comparisons) and fails on errors or on "NaN"/"undefined" shown.
- `tests/check_gaps.py`: checks the "(Agency total minus components)" row in Explore on known cases.
- `tests/check_v2.py`: checks what is new here against the component table: the start page's numbers and sentences, both appeal rates, the timeline, the lists, links, CSV, the About page, and a wording scan.
- `requirements.txt`: Python packages for `prep.py`.
- `deploy/dashboard.yml`: draft GitHub Actions workflow (monthly rebuild and publish to GitHub Pages).

## Build and view
```
pip install -r requirements.txt
python prep.py --components <repo>/fa26/dataset/component_level/component_master_no_03_06_11.csv
python prep_laws.py --statutes <repo>/fa26/dataset/component_level/exemption_statutes_06.csv
python check_law_links.py   # new laws only; then run prep_laws.py again
quarto render
python serve.py            # then open http://127.0.0.1:8767/_site/index.html
```
Open the page through a web server (`serve.py`, `quarto preview`, or GitHub Pages once published), not by
double-clicking `index.html`: the charts do not run from a local file.

## Tests
With `serve.py` running (and `pip install playwright`, `playwright install chromium webkit`):
```
python tests/check_numbers.py chromium      # or webkit (the engine behind Safari)
python tests/check_numbers_more.py chromium
python tests/check_edges.py chromium
python tests/check_gaps.py chromium
python tests/check_v2.py chromium
```

## How it will be published
`deploy/dashboard.yml` runs on the 1st of every month and on demand:
1. install Python packages
2. `prep.py` on the component table
3. `quarto render`
4. publish `_site/` to GitHub Pages

Still to add: download new reports from the foia.gov API and rebuild the component table before step 2.
