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


# --- HTTP ------------------------------------------------------------------------

class FakeResponse:
    def __init__(self, status_code, text=""):
        self.status_code, self.text = status_code, text


@pytest.mark.parametrize("response, expected", [(FakeResponse(200, "<html>"), "<html>"), (FakeResponse(404), None)])
def test_get_returns_text_or_none_when_unpublished(monkeypatch, response, expected):
    seen = {}

    def fake_get(url, timeout, headers):
        seen.update(headers)
        return response

    monkeypatch.setattr(rs.requests, "get", fake_get)
    assert rs._get("https://example.com") == expected
    assert seen["User-Agent"] == rs.USER_AGENT


def test_get_raises_on_server_error(monkeypatch):
    monkeypatch.setattr(rs.requests, "get", lambda *a, **k: FakeResponse(503))
    with pytest.raises(rs.ScrapeError, match="HTTP 503"):
        rs._get("https://example.com")


def test_get_raises_on_network_error(monkeypatch):
    def timeout(*a, **k):
        raise rs.requests.Timeout()

    monkeypatch.setattr(rs.requests, "get", timeout)
    with pytest.raises(rs.ScrapeError, match="Timeout"):
        rs._get("https://example.com")


def test_fetch_source(monkeypatch):
    doc = rs.DoctorOfCredit()
    monkeypatch.setattr(rs, "_get", lambda url: None)
    assert rs.fetch_source(doc, 2026, 4) is None

    no_cards = '<div class="entry-content"><p>Dates: October 1 - December 31, 2026</p><h2>Citi Dividend – Dining</h2></div>'
    monkeypatch.setattr(rs, "_get", lambda url: no_cards)
    with pytest.raises(rs.ScrapeError, match="no Chase Freedom or Discover"):
        rs.fetch_source(doc, 2026, 4)

    urls = []
    monkeypatch.setattr(rs, "_get", lambda url: urls.append(url) or DOC_PAGE)
    assert _pairs(rs.fetch_source(doc, 2026, 4)) == Q4_CORE
    assert "q4-2026" in urls[0]


# --- parsing strictness -------------------------------------------------------------

def test_doc_rejects_same_quarter_last_year():
    with pytest.raises(rs.ScrapeError, match="dates"):
        rs.DoctorOfCredit().parse(DOC_PAGE.replace("2026", "2025"), 2026, 4)


def test_fm_rejects_card_without_bonus_categories_heading():
    page = FM_PAGE.replace("<h2>Discover</h2>\n<h3>Bonus Categories</h3>", "<h2>Discover</h2>\n<h3>Bonus Amount</h3>")
    with pytest.raises(rs.ScrapeError, match="Bonus Categories"):
        rs.FrequentMiler().parse(page, 2026, 4)
    page = FM_PAGE.replace("<h2>Discover</h2>\n<h3>Bonus Categories</h3>", "<h2>Discover</h2>\n<h2>Next</h2>")
    with pytest.raises(rs.ScrapeError, match="Bonus Categories"):
        rs.FrequentMiler().parse(page, 2026, 4)


def test_match_card_requires_prefix():
    assert rs._match_card("Chase Freedom & Freedom Flex")[0] == "Chase Freedom Flex"
    assert rs._match_card("Tips for Chase Freedom") is None


@pytest.mark.parametrize("cat, ok", [
    ("Gas", True), ("A", False), ("x" * 41, False), ("Various merchants", False),
    ("Up to $1,500", False), ("Select your categories", False), ("Add me", False),
])
def test_valid_category(cat, ok):
    assert rs._valid_category(cat) is ok


def test_merge_rows_lists_each_source_once():
    rows = rs.DoctorOfCredit().parse(DOC_PAGE, 2026, 4)
    merged = rs.merge_rows(rows + rows)
    assert len(merged) == 5 and set(merged["Source"]) == {"doctorofcredit"}


# --- fetch_all / fetch_quarter -----------------------------------------------------

def test_fetch_all_survives_unexpected_parser_error(monkeypatch):
    doc, fm = rs.DoctorOfCredit(), rs.FrequentMiler()

    def fake_fetch_source(source, year, quarter):
        if source is doc:
            raise AttributeError("'NoneType' object has no attribute 'find_all'")
        return fm.parse(FM_PAGE, year, quarter)

    monkeypatch.setattr(rs, "fetch_source", fake_fetch_source)
    df, status = rs.fetch_all(2026, 4, sources=[doc, fm])
    assert status["doctorofcredit"].startswith("ERROR unexpected AttributeError")
    assert len(df) == 6


def test_fetch_all_reports_missing_card_section(monkeypatch):
    doc = rs.DoctorOfCredit()
    page = DOC_PAGE.replace("<h2>Discover – Utilities, Restaurants, and Entertainment</h2>", "")
    monkeypatch.setattr(rs, "_get", lambda url: page)
    df, status = rs.fetch_all(2026, 4, sources=[doc])
    assert status == {"doctorofcredit": "ok, no section for Discover It"}
    assert set(df["Credit Card"]) == {"Chase Freedom Flex"}


def test_fetch_quarter_raises_only_when_every_source_errors(monkeypatch):
    monkeypatch.setattr(rs, "fetch_all", lambda y, q: (None, {"a": "ERROR x", "b": "ERROR y"}))
    with pytest.raises(rs.ScrapeError, match="a: ERROR x"):
        rs.fetch_quarter(2026, 4)
    monkeypatch.setattr(rs, "fetch_all", lambda y, q: (None, {"a": "ERROR x", "b": "not published yet"}))
    assert rs.fetch_quarter(2026, 4) is None


# --- CSV safety -------------------------------------------------------------------

def _never_called(year, quarter):
    raise AssertionError("should not fetch")


def test_update_refuses_csv_without_year_column(tmp_path):
    path = tmp_path / "rot.csv"
    original = "Credit Card,Category,Rewards,Type,Transferable,Quarter\nDiscover It,Gas,5,Cash Back,False,3\n"
    path.write_text(original)
    with pytest.raises(rs.ScrapeError, match="without Year/Quarter"):
        rs.update_csv(path, [(2026, 4)], fetch=_never_called)
    assert path.read_text() == original


def test_update_refuses_csv_with_blank_year(tmp_path):
    path = tmp_path / "rot.csv"
    rs.write_csv(pd.DataFrame([_row("Discover It", "Gas", 3, "doctorofcredit")]), path)
    path.write_text(path.read_text().replace(",2026,3,", ",,3,"))
    with pytest.raises(rs.ScrapeError, match="1 row"):
        rs.update_csv(path, [(2026, 4)], fetch=_never_called)


def test_update_refuses_csv_missing_columns(tmp_path):
    path = tmp_path / "rot.csv"
    path.write_text("Credit Card,Category\nDiscover It,Gas\n")
    with pytest.raises(rs.ScrapeError, match="unreadable"):
        rs.update_csv(path, [(2026, 4)], fetch=_never_called)


def test_update_keeps_other_quarters(tmp_path):
    path, calls = tmp_path / "rot.csv", []
    rs.write_csv(pd.DataFrame([_row("Discover It", "Gas", 3, "doctorofcredit+frequentmiler")]), path)
    rs.update_csv(path, [(2026, 4)], fetch=_fetcher({"doctorofcredit"}, calls))
    saved = rs.load_csv(path)
    assert set(saved["Quarter"]) == {3, 4} and len(saved) == 6


def test_update_keeps_rows_from_source_that_failed_later(tmp_path):
    path, calls = tmp_path / "rot.csv", []
    rs.update_csv(path, [(2026, 4)], fetch=_fetcher({"doctorofcredit"}, calls))

    def fm_only(year, quarter):
        rows = rs.FrequentMiler().parse(FM_PAGE, year, quarter)
        return rs.merge_rows(rows), {"doctorofcredit": "ERROR layout changed", "frequentmiler": "ok"}

    report, errors, _ = rs.update_csv(path, [(2026, 4)], fetch=fm_only)
    saved = rs.load_csv(path).set_index(["Credit Card", "Category"])["Source"]
    assert errors == 1 and len(saved) == 6
    assert saved[("Discover It", "Utilities")] == "doctorofcredit+frequentmiler"
    assert saved[("Chase Freedom Flex", "American Red Cross")] == "frequentmiler"


def test_update_refetches_quarter_missing_a_card(tmp_path):
    path, calls = tmp_path / "rot.csv", []
    both = {"doctorofcredit": "ok", "frequentmiler": "ok"}
    chase_only = [_row("Chase Freedom Flex", "Dining", 4, "doctorofcredit+frequentmiler")]
    rs.update_csv(path, [(2026, 4)], fetch=lambda y, q: (rs.merge_rows(chase_only), both))

    def full(year, quarter):
        calls.append((year, quarter))
        rows = rs.DoctorOfCredit().parse(DOC_PAGE, year, quarter) + rs.FrequentMiler().parse(FM_PAGE, year, quarter)
        return rs.merge_rows(rows), both

    rs.update_csv(path, [(2026, 4)], fetch=full)
    assert calls == [(2026, 4)]
    assert "Discover It" in set(rs.load_csv(path)["Credit Card"])


def test_update_does_not_rewrite_unchanged_quarter(tmp_path):
    path, calls = tmp_path / "rot.csv", []
    rs.update_csv(path, [(2026, 4)], fetch=_fetcher({"doctorofcredit"}, calls))
    before = path.stat().st_mtime_ns
    report, _, _ = rs.update_csv(path, [(2026, 4)], fetch=_fetcher({"doctorofcredit"}, calls))
    assert len(calls) == 2  # FM still missing, so it does look again
    assert path.stat().st_mtime_ns == before
    assert not any("saved" in line for line in report)


def test_update_force_replaces_hand_edited_quarter(tmp_path):
    path, calls = tmp_path / "rot.csv", []
    rs.write_csv(pd.DataFrame([_row("Discover It", "Gas", 4, "")]), path)
    report, _, _ = rs.update_csv(path, [(2026, 4)], force=True, fetch=_fetcher({"doctorofcredit"}, calls))
    saved = rs.load_csv(path)
    assert calls == [(2026, 4)]
    assert _pairs(saved.to_dict("records")) == Q4_CORE
    assert rs.MANUAL not in set(saved["Source"])


def test_write_csv_round_trip_is_stable(tmp_path):
    path = tmp_path / "rot.csv"
    path.write_text(rs.CSV_PATH.read_text())
    rs.write_csv(rs.load_csv(path), path)
    assert path.read_text() == rs.CSV_PATH.read_text()


# --- CLI ---------------------------------------------------------------------------

def _seed_current_quarter(tmp_path, monkeypatch):
    path = tmp_path / "rot.csv"
    rs.write_csv(pd.DataFrame([_row("Discover It", "Gas", 4, "doctorofcredit")]), path)
    monkeypatch.setattr(rs, "current_quarter", lambda: (2026, 4))
    return path


def test_main_exit_codes(tmp_path, monkeypatch):
    path = _seed_current_quarter(tmp_path, monkeypatch)
    monkeypatch.setattr(rs, "fetch_all", lambda y, q: (None, {"doctorofcredit": "ok", "frequentmiler": "ERROR layout"}))
    assert rs.main(["--csv", str(path), "--quarter", "2026-4"]) == 2
    monkeypatch.setattr(rs, "fetch_all", lambda y, q: (None, {"frequentmiler": "not published yet"}))
    assert rs.main(["--csv", str(path), "--quarter", "2026-4"]) == 0


def test_main_fails_cleanly_on_unreadable_csv(tmp_path, monkeypatch, capsys):
    path = tmp_path / "rot.csv"
    path.write_text("Credit Card,Category\nDiscover It,Gas\n")
    monkeypatch.setattr(rs, "fetch_all", _never_called)
    assert rs.main(["--csv", str(path)]) == 1
    assert "fix it by hand" in capsys.readouterr().err


def test_main_defaults_to_current_and_next_quarter(tmp_path, monkeypatch):
    path = _seed_current_quarter(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(rs, "fetch_all", lambda y, q: calls.append((y, q)) or (None, {}))
    rs.main(["--csv", str(path)])
    assert calls == [(2026, 4), (2027, 1)]


def test_main_writes_github_step_summary(tmp_path, monkeypatch):
    path = _seed_current_quarter(tmp_path, monkeypatch)
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setattr(rs, "fetch_all", lambda y, q: (None, {"frequentmiler": "not published yet"}))
    rs.main(["--csv", str(path), "--quarter", "2026-4"])
    text = summary.read_text()
    assert text.startswith("### Rotating categories") and "- Q4 2026 frequentmiler: not published yet" in text


def test_fetch_all_when_nothing_published(monkeypatch):
    monkeypatch.setattr(rs, "fetch_source", lambda source, year, quarter: None)
    df, status = rs.fetch_all(2026, 4)
    assert df is None and set(status.values()) == {"not published yet"}
    assert list(rs.merge_rows([]).columns) == rs.CSV_COLUMNS


def test_load_csv_treats_missing_source_column_as_hand_edited(tmp_path):
    path = tmp_path / "rot.csv"
    path.write_text("Credit Card,Category,Rewards,Type,Transferable,Year,Quarter\nDiscover It,Gas,5,Cash Back,False,2026,4\n")
    assert list(rs.load_csv(path)["Source"]) == [rs.MANUAL]
