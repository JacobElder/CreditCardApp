import pandas as pd
import pytest

import rotating_scraper as rs

DOC_PAGE = """
<html><body><div class="entry-content">
<p>It's now possible to activate all 5% category credit cards for the third quarter of 2026.</p>
<p>Dates: October 1st – December 31, 2026. Store purchases can usually be done until the last minute.</p>
<ul><li>1. Chase Freedom – Grocery, Dining</li></ul>
<h2>Chase Freedom – Grocery, Dining</h2>
<p>With the Chase Freedom and Freedom Flex cards, activate to earn 5%: Something, Else</p>
<h2>Discover – Utilities, Restaurants, and Entertainment</h2>
<h2>Citi Dividend – Dining, Citi Travel</h2>
<h2>U.S. Bank Cash+/Elan – Select your Categories</h2>
<h2>Other Cards with 5% Category</h2>
</div></body></html>
"""

FM_PAGE = """
<html><body><article>
<p>Chase Freedom and Freedom Flex, Discover It, US Bank Cash+, and Citi Dividend cards all have rotating categories.</p>
<p>Below are the details of each card's categories from October 1 to December 31, 2026, along with links.</p>
<h2>Chase Freedom &amp; Freedom Flex</h2>
<h3>Bonus Categories</h3>
<ul>
  <li>Dining</li>
  <li>Grocery Stores (excludes Walmart &amp; Target)</li>
  <li>American Red Cross<ul><li>Donations made at redcross.org only</li></ul></li>
</ul>
<h3>Bonus Amount / Limit</h3>
<ul><li>5x on up to $1,500</li></ul>
<h2>Discover</h2>
<h3>Bonus Categories</h3>
<ul><li>Restaurants</li><li>Entertainment</li><li>Utilities</li></ul>
<h2>Citi Dividend</h2>
<h3>Bonus Categories</h3>
<ul><li>Dining</li></ul>
</article></body></html>
"""

Q4_CORE = {
    ("Chase Freedom Flex", "Grocery Stores"),
    ("Chase Freedom Flex", "Dining"),
    ("Discover It", "Utilities"),
    ("Discover It", "Dining"),
    ("Discover It", "Entertainment"),
}


def _pairs(rows):
    return {(r["Credit Card"], r["Category"]) for r in rows}


# --- Doctor of Credit --------------------------------------------------------

def test_doc_reads_headings_only():
    rows = rs.DoctorOfCredit().parse(DOC_PAGE, 2026, 4)
    assert _pairs(rows) == Q4_CORE
    assert {r["Year"] for r in rows} == {2026} and {r["Quarter"] for r in rows} == {4}
    assert all(r["Transferable"] is False for r in rows if r["Credit Card"] == "Discover It")


def test_doc_rejects_wrong_quarter():
    # Intro text says "third quarter", but the Dates line is authoritative
    with pytest.raises(rs.ScrapeError, match="dates"):
        rs.DoctorOfCredit().parse(DOC_PAGE, 2026, 3)


def test_doc_rejects_layout_change():
    with pytest.raises(rs.ScrapeError):
        rs.DoctorOfCredit().parse("<html><body><p>Dates: October 2026</p></body></html>", 2026, 4)


def test_doc_rejects_suspicious_categories():
    page = DOC_PAGE.replace("Grocery, Dining</h2>", "Select 2 of 5 Categories</h2>")
    with pytest.raises(rs.ScrapeError, match="Chase Freedom Flex"):
        rs.DoctorOfCredit().parse(page, 2026, 4)


# --- Frequent Miler ------------------------------------------------------------

def test_fm_reads_lists_and_drops_fine_print():
    rows = rs.FrequentMiler().parse(FM_PAGE, 2026, 4)
    assert _pairs(rows) == Q4_CORE | {("Chase Freedom Flex", "American Red Cross")}


def test_fm_splits_combined_bullets():
    page = FM_PAGE.replace("<li>Dining</li>\n", "<li>Gas stations, public transit, &amp; EV charging</li>\n")
    rows = rs.merge_rows(rs.FrequentMiler().parse(page, 2026, 4))
    chase = set(rows.loc[rows["Credit Card"] == "Chase Freedom Flex", "Category"])
    assert {"Gas", "Transit"} <= chase


def test_fm_rejects_wrong_quarter():
    with pytest.raises(rs.ScrapeError, match="dates"):
        rs.FrequentMiler().parse(FM_PAGE, 2027, 1)


def test_fm_rejects_missing_list():
    page = FM_PAGE.replace("<ul><li>Restaurants</li><li>Entertainment</li><li>Utilities</li></ul>", "<p>TBA</p>")
    with pytest.raises(rs.ScrapeError):
        rs.FrequentMiler().parse(page, 2026, 4)


# --- merging -----------------------------------------------------------------

def test_merge_unions_sources_and_records_who_said_what():
    rows = rs.DoctorOfCredit().parse(DOC_PAGE, 2026, 4) + rs.FrequentMiler().parse(FM_PAGE, 2026, 4)
    merged = rs.merge_rows(rows).set_index(["Credit Card", "Category"])["Source"]
    assert len(merged) == 6
    assert merged[("Discover It", "Utilities")] == "doctorofcredit+frequentmiler"
    assert merged[("Chase Freedom Flex", "American Red Cross")] == "frequentmiler"


class FakeSource:
    def __init__(self, name, result):
        self.name, self.result = name, result
        self.url_template = "unused"


def test_fetch_all_survives_one_source_failing(monkeypatch):
    doc, fm = rs.DoctorOfCredit(), rs.FrequentMiler()

    def fake_fetch_source(source, year, quarter):
        if source is doc:
            raise rs.ScrapeError("layout changed")
        return fm.parse(FM_PAGE, year, quarter)

    monkeypatch.setattr(rs, "fetch_source", fake_fetch_source)
    df, status = rs.fetch_all(2026, 4, sources=[doc, fm])
    assert status == {"doctorofcredit": "ERROR layout changed", "frequentmiler": "ok"}
    assert len(df) == 6


# --- CSV updates ---------------------------------------------------------------

def _row(card, cat, quarter, source):
    return {"Credit Card": card, "Category": cat, "Rewards": 5, "Type": "Cash Back",
            "Transferable": False, "Year": 2026, "Quarter": quarter, "Source": source}


def _fetcher(sources_published, calls):
    def fetch(year, quarter):
        calls.append((year, quarter))
        rows, status = [], {}
        for name, page, parser in [("doctorofcredit", DOC_PAGE, rs.DoctorOfCredit()),
                                   ("frequentmiler", FM_PAGE, rs.FrequentMiler())]:
            if (year, quarter) == (2026, 4) and name in sources_published:
                rows += parser.parse(page, year, quarter)
                status[name] = "ok"
            else:
                status[name] = "not published yet"
        return (rs.merge_rows(rows) if rows else None), status
    return fetch


def test_update_adds_quarter_then_fills_in_second_source(tmp_path):
    path, calls = tmp_path / "rot.csv", []
    report, errors, df = rs.update_csv(path, [(2026, 4)], fetch=_fetcher({"doctorofcredit"}, calls))
    assert errors == 0 and len(rs.load_csv(path)) == 5

    report, errors, df = rs.update_csv(path, [(2026, 4)], fetch=_fetcher({"doctorofcredit", "frequentmiler"}, calls))
    saved = rs.load_csv(path)
    assert len(saved) == 6 and "American Red Cross" in set(saved["Category"])
    assert any("only one source" in line for line in report)

    report, errors, df = rs.update_csv(path, [(2026, 4)], fetch=_fetcher(set(), calls))
    assert calls == [(2026, 4), (2026, 4)]  # complete quarter isn't fetched again
    assert "all sources in" in report[0]


def test_update_never_touches_hand_edited_quarter(tmp_path):
    path, calls = tmp_path / "rot.csv", []
    rs.write_csv(pd.DataFrame([_row("Discover It", "Gas", 4, "")]), path)
    report, errors, df = rs.update_csv(path, [(2026, 4)], fetch=_fetcher({"doctorofcredit"}, calls))
    assert calls == [] and "hand-edited" in report[0]
    assert list(rs.load_csv(path)["Category"]) == ["Gas"]


def test_update_counts_errors_without_writing(tmp_path):
    path = tmp_path / "rot.csv"

    def broken(year, quarter):
        return None, {"doctorofcredit": "ERROR layout changed", "frequentmiler": "not published yet"}

    report, errors, df = rs.update_csv(path, [(2026, 4)], fetch=broken)
    assert errors == 1 and not path.exists()


def test_main_fails_when_current_quarter_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(rs, "fetch_all", lambda y, q: (None, {"doctorofcredit": "not published yet"}))
    monkeypatch.setattr(rs, "current_quarter", lambda: (2026, 4))
    assert rs.main(["--csv", str(tmp_path / "rot.csv"), "--quarter", "2026-4"]) == 1


def test_next_quarter():
    assert rs.next_quarter(2026, 4) == (2027, 1)
    assert rs.next_quarter(2026, 2) == (2026, 3)
