"""Checks on the CSVs that ship with the app."""
from pathlib import Path

import pandas as pd
import pytest

import rewards as rw
import rotating_scraper as rs

HERE = Path(__file__).parent
CANONICAL = set(rw.CATEGORY_ALIASES.values())
# Categories that legitimately have no alias: one-off rotating partners and niche fixed bonuses
KNOWN_OTHER = {
    "Department Stores", "Movie Theaters", "Online Shopping",
    "American Heart Association", "American Red Cross", "Chase Travel", "Feeding America",
    "Norwegian Cruise Line", "United Way",
}


@pytest.fixture(scope="module")
def fixed():
    raw = pd.read_csv(HERE / "CreditCards.csv")
    return raw, rw.clean_fixed(raw)


@pytest.fixture(scope="module")
def rotating():
    raw = pd.read_csv(HERE / "RotatingCategories.csv")
    rows, undated = rw.clean_rotating(raw)
    return raw, rows, undated


def test_fixed_csv_loads_without_dropping_rows(fixed):
    raw, df = fixed
    assert len(df) == len(raw.dropna(how="all"))


def test_rotating_csv_loads_without_dropping_rows(rotating):
    raw, rows, undated = rotating
    assert undated == 0 and len(rows) == len(raw)
    assert list(raw.columns) == rs.CSV_COLUMNS


@pytest.mark.parametrize("which", ["fixed", "rotating"])
def test_rates_are_sensible(which, fixed, rotating):
    df = fixed[1] if which == "fixed" else rotating[1]
    assert df["Rewards"].between(0.5, 10).all()
    assert set(df["Type"]) <= {"Points", "Cash Back"}


def test_no_duplicate_rows(fixed, rotating):
    assert not fixed[1].duplicated(["Credit Card", "Category"]).any()
    assert not rotating[1].duplicated(["Credit Card", "Category", "Year", "Quarter"]).any()


def test_rotating_quarters_are_well_formed(rotating):
    rows = rotating[1]
    assert rows["Quarter"].between(1, 4).all()
    assert rows["Year"].between(2020, 2100).all()
    assert set(rows["Credit Card"]) <= rs.CARD_NAMES


def test_categories_are_canonical_or_known(fixed, rotating):
    # A new spelling (e.g. "Transportation") should get an alias rather than its own button
    categories = set(fixed[1]["Category"]) | set(rotating[1]["Category"])
    assert categories - CANONICAL - KNOWN_OTHER == set()


def test_fixed_has_an_everyday_rate_card(fixed):
    assert rw.EVERYTHING in set(fixed[1]["Category"])
