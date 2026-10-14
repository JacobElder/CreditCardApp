"""Fetch quarterly 5% rotating categories from Doctor of Credit and Frequent Miler.

Used two ways:
  * `python rotating_scraper.py` updates RotatingCategories.csv for the current and
    next quarter. The scheduled GitHub Action runs this and commits any change.
  * The app calls fetch_quarter() as a last resort when the CSV has nothing for
    the current quarter.

Each source is parsed strictly: the page must say it covers the requested quarter,
and anything unexpected raises ScrapeError rather than guessing. Results from every
source that succeeds are merged, so either site can break or be late without
blocking an update, and a category only one site lists (e.g. a charity) isn't lost.
"""
import argparse
import os
import re
import sys
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup

from rewards import ROTATING_COLUMNS, clean_rotating, current_quarter, normalize_category, quarter_label

USER_AGENT = "CreditCardRewardsApp/1.0 (+https://github.com/JacobElder/CreditCardApp)"
CSV_PATH = Path(__file__).with_name("RotatingCategories.csv")
CSV_COLUMNS = ROTATING_COLUMNS + ["Source"]
MANUAL = "manual"

# Section heading prefix (lower-case) -> (card name used in the app, Type, Transferable)
CARDS = {
    "chase freedom": ("Chase Freedom Flex", "Points", True),
    "discover": ("Discover It", "Cash Back", False),
}

QUARTER_START_MONTH = {1: "january", 2: "april", 3: "july", 4: "october"}
_DASH = re.compile(r"\s+[–—-]\s+")


class ScrapeError(RuntimeError):
    pass


def _get(url, timeout=15):
    """Returns the page HTML, or None if it hasn't been published yet (404)."""
    try:
        resp = requests.get(url, timeout=timeout, headers={"User-Agent": USER_AGENT})
    except requests.RequestException as e:
        raise ScrapeError(f"request failed: {e.__class__.__name__}") from e
    if resp.status_code == 404:
        return None
    if resp.status_code != 200:
        raise ScrapeError(f"HTTP {resp.status_code} from {url}")
    return resp.text


def _text(el):
    return " ".join(el.get_text(" ").split())


def _content(html, selector):
    content = BeautifulSoup(html, "html.parser").select_one(selector)
    if content is None:
        raise ScrapeError(f"page layout changed: no {selector}")
    return content


def _check_dates(text, year, quarter):
    if not text or QUARTER_START_MONTH[quarter] not in text.lower() or str(year) not in text:
        raise ScrapeError(f"page dates don't match {quarter_label(year, quarter)}: {text!r}")


def _match_card(name):
    return next((v for k, v in CARDS.items() if name.lower().startswith(k)), None)


def _split_categories(text):
    text = re.sub(r"\(.*?\)", "", text)
    parts = re.split(r",|\s+and\s+", text)
    parts = [re.sub(r"^(?:&|and)\s+", "", p.strip(" .")) for p in parts]
    return [p for p in parts if p]


def _valid_category(cat):
    return 2 <= len(cat) <= 40 and not re.search(r"\d|select (?:your|\d)|various|\badd me\b", cat, re.I)


def _rows(card_info, raw_categories, year, quarter, source):
    card, card_type, transferable = card_info
    cats = [c for raw in raw_categories for c in _split_categories(raw)]
    bad = [c for c in cats if not _valid_category(c)]
    if not cats or bad:
        raise ScrapeError(f"{source}: unexpected categories for {card}: {raw_categories!r}")
    return [{
        "Credit Card": card, "Category": normalize_category(c), "Rewards": 5, "Type": card_type,
        "Transferable": transferable, "Year": year, "Quarter": quarter, "Source": source,
    } for c in cats]


class DoctorOfCredit:
    """Quarterly roundup; categories come from headings like 'Discover – Utilities, Restaurants'."""
    name = "doctorofcredit"
    url_template = (
        "https://www.doctorofcredit.com/q{quarter}-{year}-5-quarterly-categories-"
        "activate-offers-suggestions-freedom-flex-discover-dividend-cash-more/"
    )

    def parse(self, html, year, quarter):
        content = _content(html, ".entry-content")
        dates = next((_text(p) for p in content.find_all("p") if _text(p).lower().startswith("dates")), None)
        _check_dates(dates, year, quarter)
        rows = []
        for heading in content.find_all("h2"):
            parts = _DASH.split(_text(heading), maxsplit=1)
            card = _match_card(parts[0]) if len(parts) == 2 else None
            if card:
                rows += _rows(card, [parts[1]], year, quarter, self.name)
        return rows


class FrequentMiler:
    """Quarterly activation-links post; each card's <h2> is followed by a
    'Bonus Categories' <h3> and a bulleted list."""
    name = "frequentmiler"
    url_template = "https://frequentmiler.com/q{quarter}-{year}-activation-links-for-cards-offering-5-in-rotating-categories/"

    def parse(self, html, year, quarter):
        content = _content(html, "article")
        dates = next((_text(p) for p in content.find_all("p") if "details of each card" in _text(p).lower()), None)
        _check_dates(dates, year, quarter)
        rows = []
        for heading in content.find_all("h2"):
            card = _match_card(_text(heading))
            if not card:
                continue
            label = heading.find_next(["h2", "h3"])
            if label is None or label.name != "h3" or "categor" not in _text(label).lower():
                raise ScrapeError(f"{self.name}: no 'Bonus Categories' under {_text(heading)!r}")
            # Must be the very next element; searching further could grab the next card's list
            items = label.find_next_sibling()
            if items is None or items.name not in ("ul", "ol"):
                raise ScrapeError(f"{self.name}: no category list under {_text(heading)!r}")
            raw = []
            for li in items.find_all("li", recursive=False):
                for nested in li.find_all(["ul", "ol"]):
                    nested.decompose()  # merchant fine print
                raw.append(_text(li))
            rows += _rows(card, raw, year, quarter, self.name)
        return rows


SOURCES = [DoctorOfCredit(), FrequentMiler()]
SOURCE_NAMES = {s.name for s in SOURCES}


def fetch_source(source, year, quarter):
    """Returns a list of rows, or None if the page isn't published yet. Raises ScrapeError."""
    html = _get(source.url_template.format(year=year, quarter=quarter))
    if html is None:
        return None
    rows = source.parse(html, year, quarter)
    if not rows:
        raise ScrapeError(f"{source.name}: no Chase Freedom or Discover section found")
    return rows


def merge_rows(rows):
    """One row per card+category; Source lists every site that reported it."""
    if not rows:
        return pd.DataFrame(columns=CSV_COLUMNS)
    df = pd.DataFrame(rows, columns=CSV_COLUMNS)
    keys = [c for c in CSV_COLUMNS if c != "Source"]
    return (df.groupby(keys, as_index=False, sort=False)["Source"]
              .agg(lambda s: "+".join(sorted(set(s)))))


def fetch_all(year, quarter, sources=SOURCES):
    """Returns (merged rows or None if no source has published, {source: status})."""
    rows, status = [], {}
    for source in sources:
        try:
            found = fetch_source(source, year, quarter)
        except ScrapeError as e:
            status[source.name] = f"ERROR {e}"
            continue
        if found is None:
            status[source.name] = "not published yet"
        else:
            rows += found
            status[source.name] = "ok"
    return (merge_rows(rows) if rows else None), status


def fetch_quarter(year, quarter):
    """For the app: merged rows, or None. Raises ScrapeError only if every source errored."""
    df, status = fetch_all(year, quarter)
    if df is None and all(s.startswith("ERROR") for s in status.values()):
        raise ScrapeError("; ".join(f"{k}: {v}" for k, v in status.items()))
    return df


def next_quarter(year, quarter):
    return (year + 1, 1) if quarter == 4 else (year, quarter + 1)


def _sources_in(df):
    return {name for value in df["Source"] for name in str(value).split("+")}


def load_csv(path):
    if not Path(path).exists():
        return pd.DataFrame(columns=CSV_COLUMNS)
    df, _dropped = clean_rotating(pd.read_csv(path))
    if "Source" not in df.columns:
        df["Source"] = MANUAL
    df["Source"] = df["Source"].fillna(MANUAL).replace("", MANUAL)
    return df[CSV_COLUMNS]


def write_csv(df, path):
    df = df[CSV_COLUMNS].sort_values(["Year", "Quarter", "Credit Card", "Category"])
    df.to_csv(path, index=False, lineterminator="\n")


def update_csv(path, quarters, force=False, fetch=None):
    """Fill in quarters until every source has contributed.

    A quarter is left alone if any of its rows are hand-edited (Source blank or
    'manual'), unless force=True. Returns (report lines, error count, final df).
    """
    fetch = fetch or fetch_all
    df = load_csv(path)
    report, errors, changed = [], 0, False
    for year, quarter in quarters:
        label = quarter_label(year, quarter)
        mask = (df["Year"] == year) & (df["Quarter"] == quarter)
        have = _sources_in(df[mask])
        if mask.any() and not force:
            if MANUAL in have or not (SOURCE_NAMES - have):
                why = "hand-edited" if MANUAL in have else "all sources in"
                report.append(f"{label}: up to date ({why}), skipped")
                continue
        new, status = fetch(year, quarter)
        for source, state in status.items():
            report.append(f"{label} {source}: {state}")
            errors += state.startswith("ERROR")
        if new is None or (not force and _sources_in(new) <= have):
            continue
        df = pd.concat([df[~mask], new], ignore_index=True)
        changed = True
        summary = "; ".join(f"{card}: {', '.join(g['Category'])}" for card, g in new.groupby("Credit Card"))
        report.append(f"{label}: saved {summary}")
        single = new[~new["Source"].str.contains(r"\+")]
        if len(_sources_in(new)) > 1 and not single.empty:
            report.append(f"{label}: listed by only one source: "
                          + ", ".join(f"{r['Category']} ({r['Source']})" for _, r in single.iterrows()))
    if changed:
        write_csv(df, path)
    return report, errors, df


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--csv", default=str(CSV_PATH))
    parser.add_argument("--quarter", action="append", metavar="YYYY-Q",
                        help="quarter to fetch, e.g. 2026-4 (repeatable). Default: current and next.")
    parser.add_argument("--force", action="store_true", help="re-scrape quarters even if complete or hand-edited")
    args = parser.parse_args(argv)

    current = current_quarter()
    if args.quarter:
        quarters = [tuple(int(x) for x in q.split("-")) for q in args.quarter]
    else:
        quarters = [current, next_quarter(*current)]

    report, errors, df = update_csv(args.csv, quarters, force=args.force)
    for line in report:
        print(line)
    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_file:
        with open(summary_file, "a") as f:
            f.write("### Rotating categories\n\n" + "\n".join(f"- {line}" for line in report) + "\n")

    if not ((df["Year"] == current[0]) & (df["Quarter"] == current[1])).any():
        print(f"No rotating categories for the current quarter ({quarter_label(*current)}).", file=sys.stderr)
        return 1
    if errors:
        print(f"{errors} source(s) failed to parse; the scraper may need updating.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
