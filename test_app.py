"""Smoke tests that run the whole Streamlit page with the network mocked out."""
from pathlib import Path
from unittest import mock

import pandas as pd
import pytest
import requests
import streamlit as st
from streamlit.testing.v1 import AppTest

HERE = Path(__file__).parent
APP = HERE / "streamlitCards.py"


class SheetResponse:
    status_code = 200
    headers = {"Content-Type": "text/csv; charset=utf-8"}

    def __init__(self, text):
        self.text = text


@pytest.fixture(autouse=True)
def offline():
    st.cache_data.clear()  # cached Sheet/scrape results would leak between tests
    with mock.patch("requests.get", side_effect=requests.ConnectionError("offline")) as get, \
         mock.patch("rotating_scraper.fetch_quarter", return_value=None) as scrape:
        yield get, scrape


def run(app=APP):
    at = AppTest.from_file(str(app), default_timeout=30).run()
    assert not at.exception, at.exception
    return at


def widget(at, label):
    return next(w for w in at.get("button_group") if w.label == label)


def warnings(at):
    return [w.value for w in at.warning]


def test_runs_offline_on_local_csvs(offline):
    at = run()
    assert at.title[0].value == "Best Credit Card for Rewards"
    assert any("local backup CSV" in w for w in warnings(at))
    assert offline[0].called


def test_picking_a_category_shows_ranked_cards():
    at = run()
    widget(at, "What are you buying?").set_value("Dining").run()
    assert not at.exception
    headers = [m.value for m in at.markdown]
    assert "#### Best" in headers and "#### Next best" in headers
    assert len(at.dataframe) == 2  # all-cards table + Citi table


def test_anything_else_ranks_everyday_cards():
    at = run()
    widget(at, "What are you buying?").set_value("Anything else").run()
    assert not at.exception
    assert "#### Best" in [m.value for m in at.markdown]


def test_switching_preset_updates_caption():
    at = run()
    widget(at, "Value points at").set_value("Cash").run()
    assert not at.exception
    assert any("cashed out at 1¢" in c.value for c in at.caption)


def test_sheet_returning_html_falls_back(offline):
    offline[0].side_effect = None
    offline[0].return_value = mock.Mock(status_code=200, headers={"Content-Type": "text/html"}, text="<html>")
    at = run()
    assert any("shared publicly" in w for w in warnings(at))


def test_sheet_is_used_when_available(offline):
    fixed = (HERE / "CreditCards.csv").read_text()
    rotating = (HERE / "RotatingCategories.csv").read_text()
    offline[0].side_effect = lambda url, timeout: SheetResponse(fixed if "sheet=Fixed" in url else rotating)
    at = run()
    assert not any("local backup" in w for w in warnings(at))
    lines = [m.value for m in at.markdown]
    assert any("Fixed rewards: Google Sheet" in line for line in lines)
    assert any("rotating categories: Google Sheet" in line for line in lines)


def test_sheet_wrong_tab_falls_back(offline):
    rotating = (HERE / "RotatingCategories.csv").read_text()
    offline[0].side_effect = lambda url, timeout: SheetResponse(rotating)  # gviz returns another tab
    at = run()
    assert any("looks like the rotating table" in w for w in warnings(at))


def test_empty_quarter_uses_live_scrape(offline):
    import rotating_scraper as rs
    rows = rs.merge_rows([_live_row()])
    offline[1].return_value = rows
    with mock.patch("rewards.current_quarter", return_value=(2030, 1)):
        at = run()
    assert any("read live from Doctor of Credit" in w for w in warnings(at))


def test_empty_quarter_and_scraper_crash_shows_warning(offline):
    offline[1].side_effect = AttributeError("boom")
    with mock.patch("rewards.current_quarter", return_value=(2030, 1)):
        at = run()
    assert any("No 5% rotating categories found for Q1 2030 (scraper error" in w for w in warnings(at))


def _unreadable(name):
    """pandas.read_csv that fails for one local file, as if it were missing."""
    real = pd.read_csv

    def read_csv(path, *args, **kwargs):
        if str(path).endswith(name):
            raise FileNotFoundError(name)
        return real(path, *args, **kwargs)
    return mock.patch("pandas.read_csv", side_effect=read_csv)


def test_missing_local_fixed_csv_shows_error_instead_of_crashing():
    with _unreadable("CreditCards.csv"):
        at = AppTest.from_file(str(APP), default_timeout=30).run()
    assert not at.exception
    assert at.error and "No card data available" in at.error[0].value


def test_unreadable_local_rotating_csv_is_reported():
    with _unreadable("RotatingCategories.csv"):
        at = run()
    assert any("RotatingCategories.csv unreadable" in m.value for m in at.markdown)


def test_sheet_http_error_falls_back(offline):
    offline[0].side_effect = None
    offline[0].return_value = mock.Mock(status_code=500, headers={}, text="")
    at = run()
    assert any("HTTP 500" in w for w in warnings(at))


def test_scrape_error_is_reported(offline):
    import rotating_scraper as rs
    offline[1].side_effect = rs.ScrapeError("doctorofcredit: ERROR layout changed")
    with mock.patch("rewards.current_quarter", return_value=(2030, 1)):
        at = run()
    assert any("layout changed" in w for w in warnings(at))


# --- custom data served through the mocked Sheet -------------------------------------

HEADER = "Credit Card,Category,Rewards,Type,Transferable\n"
CUSTOM_CASH = ["Dining", "Gas", "Grocery Stores", "Travel", "Transit", "Streaming",
               "Drugstores", "Home Improvement", "Fitness Clubs", "Entertainment"]


def serve(offline, fixed, rotating=HEADER + "Year,Quarter\n"):
    offline[0].side_effect = lambda url, timeout: SheetResponse(fixed if "sheet=Fixed" in url else rotating)


def lines(at):
    return [m.value for m in at.markdown]


def test_card_without_notes_and_single_custom_cash_winner(offline):
    # Plain Card earns 5% everywhere Custom Cash does except Gas, so Gas is the only gain
    fixed = HEADER + "Flat Card,Everything,2,Cash Back,FALSE\n" + "".join(
        f"Plain Card,{c},5,Cash Back,FALSE\n" for c in CUSTOM_CASH if c != "Gas")
    serve(offline, fixed)
    with mock.patch("rewards.current_quarter", return_value=(2030, 1)):  # no rotating cards
        at = run()
        assert any("add the most in **Gas**: 3.00% more" in line for line in lines(at))
        widget(at, "What are you buying?").set_value("Dining").run()
    assert not at.exception
    assert "**Plain Card** · **5%** cash back" in lines(at)
    # Plain Card has no note, so the only card caption is Flat Card's
    assert [c.value for c in at.caption[1:]] == ["everyday rate"]


def test_no_custom_cash_gain(offline):
    serve(offline, HEADER + "Big Card,Everything,6,Cash Back,FALSE\n")
    at = run()
    assert any("already match or beat 5%" in line for line in lines(at))


def test_valuation_dependent_pick_shows_info(offline):
    fixed = HEADER + ("Bank of America Customized Cash Rewards,Online Shopping,3,Cash Back,FALSE\n"
                      "Wells Fargo Active Cash,Everything,2,Cash Back,TRUE\n")
    serve(offline, fixed)
    at = run()
    widget(at, "What are you buying?").set_value("Online Shopping").run()
    assert not at.exception
    assert at.info and "depends on how you redeem points" in at.info[0].value


def test_sheet_rotating_tab_problems_are_reported(offline):
    fixed = (HERE / "CreditCards.csv").read_text()
    serve(offline, fixed, rotating="<html>sign in</html>")
    assert any("Sheet Rotating tab unusable" in line for line in lines(run()))

    st.cache_data.clear()
    serve(offline, fixed, rotating=HEADER.strip() + ",Start_Month\nDiscover It,Gas,5,Cash Back,FALSE,4\n")
    assert any("Ignored 1 Sheet rotating rows" in line for line in lines(run()))


def _live_row():
    return {"Credit Card": "Discover It", "Category": "Gas", "Rewards": 5, "Type": "Cash Back",
            "Transferable": False, "Year": 2030, "Quarter": 1, "Source": "doctorofcredit"}
