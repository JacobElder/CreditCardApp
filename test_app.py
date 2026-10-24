"""Smoke tests that run the whole Streamlit page with the network mocked out."""
import shutil
from pathlib import Path
from unittest import mock

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


def test_missing_local_csv_shows_error_instead_of_crashing(tmp_path):
    app = tmp_path / APP.name
    shutil.copy(APP, app)  # no CSVs next to it
    at = run(app)
    assert at.error and "No card data available" in at.error[0].value


def _live_row():
    return {"Credit Card": "Discover It", "Category": "Gas", "Rewards": 5, "Type": "Cash Back",
            "Transferable": False, "Year": 2030, "Quarter": 1, "Source": "doctorofcredit"}
