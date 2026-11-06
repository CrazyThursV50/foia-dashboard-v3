"""Check each law's link and read its official title: law_links.csv.

U.S. Code sections have a fixed address at Cornell's Legal Information Institute, and the page title is the section's
own heading, e.g. "8 U.S. Code § 1202 - Application for visas". A section that does not exist answers 404, so a link
goes on the page only if it was checked here. Most used laws first; a law already in the file is not fetched again.
One request every 10 seconds, the crawl delay in the site's robots.txt.

Usage: python check_law_links.py [--limit N]    (run after prep_laws.py)
"""
import argparse
import csv
import datetime
import html
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "law_links.csv"
FIELDS = ["cite", "url", "status", "title", "checked"]
RULES = {"Fed. R. Crim. P. 6(e)": "https://www.law.cornell.edu/rules/frcrmp/rule_6"}


def url_of(cite):
    m = re.fullmatch(r"(\d+) U\.S\.C\. § (\S+)", cite)
    return f"https://www.law.cornell.edu/uscode/text/{m[1]}/{m[2]}" if m else RULES.get(cite)


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (dashboard link check)"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            page = r.read(200_000).decode("utf-8", "replace")
            status = r.status
    except urllib.error.HTTPError as e:
        return str(e.code), ""
    except Exception as e:
        return "error", ""
    m = re.search(r"<title>(.*?)</title>", page, re.S | re.I)
    full = html.unescape(m[1]) if m else ""
    head = full.split(" | ")[0].strip()
    title = head.split(" - ", 1)[1].strip() if " - " in head else head
    return str(status), " ".join(title.split())


def main(limit):
    d = json.loads((HERE / "data/laws.json").read_text())
    times = [0] * len(d["laws"])
    for law, n, k in zip(d["rows"]["law"], d["rows"]["n"], d["rows"]["k"]):
        if k < 0:
            times[law] += n
    todo = [d["laws"][i]["cite"] for i in sorted(range(len(times)), key=lambda i: -times[i]) if url_of(d["laws"][i]["cite"])]
    done = {}
    if OUT.exists():
        done = {r["cite"]: r for r in csv.DictReader(OUT.open())}
    new = [c for c in todo if c not in done or done[c]["status"] == "error"][:limit]
    print(f"{len(todo)} laws can be linked, {len(done)} in the file, fetching {len(new)}", flush=True)
    for i, cite in enumerate(new):
        url = url_of(cite)
        status, title = fetch(url)
        done[cite] = {"cite": cite, "url": url, "status": status, "title": title, "checked": datetime.date.today().isoformat()}
        with OUT.open("w", newline="") as f:
            w = csv.DictWriter(f, FIELDS)
            w.writeheader()
            w.writerows(done.values())
        if i < len(new) - 1:
            time.sleep(10)
    print(f"done: {sum(r['status'] == '200' for r in done.values())} of {len(done)} answered", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=10_000)
    main(ap.parse_args().limit)
