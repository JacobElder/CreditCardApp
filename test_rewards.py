from datetime import datetime

import pandas as pd
import pytest

import rewards as rw

FIXED_CSV = """Credit Card,Category,Rewards,Type,Transferable
Bank of America Customized Cash Rewards,Online Shopping,3,Cash Back,FALSE
Capital One Savor,Grocery Stores,3,Cash Back,FALSE
Capital One Savor,Dining,3,Cash Back,FALSE
Chase Sapphire Preferred,Dining,3,Points,TRUE
Wells Fargo Active Cash,Everything,2,Cash Back,TRUE
Double Cash,Everything,2,Points,FALSE
,,,,
"""


OPTIMISTIC = rw.VALUATION_PRESETS["Optimistic"]


@pytest.fixture
def cards():
    fixed = rw.clean_fixed(rw.read_csv_text(FIXED_CSV))
    return rw.add_valuations(rw.combine(fixed, pd.DataFrame(columns=rw.ROTATING_COLUMNS)), valuations=OPTIMISTIC)


# --- normalization ---------------------------------------------------------

@pytest.mark.parametrize("raw, expected", [
    ("Dining", "Dining"),
    ("Restaurants", "Dining"),
    ("restaurant", "Dining"),
    ("Grocery", "Grocery Stores"),
    ("Groceries", "Grocery Stores"),
    ("Select Streaming Services", "Streaming"),
    ("Home Improvement Stores", "Home Improvement"),
    ("Drug Stores", "Drugstores"),
    ("Gas & EV Charging", "Gas"),
    ("Live Entertainment", "Entertainment"),
    ("Amazon.com", "Amazon"),
    ("Online Groceries", "Online Groceries"),
    ("Car Washes", "Car Washes"),
    ("feeding america", "Feeding America"),
    ("Chase Travel", "Chase Travel"),
])
def test_normalize_category(raw, expected):
    assert rw.normalize_category(raw) == expected


def test_normalize_category_blank():
    assert rw.normalize_category(float("nan")) is None
    assert rw.normalize_category("  ") is None


def test_issuer_detects_citi_double_cash():
    assert rw.get_issuer("Double Cash") == "Citi"


# --- cleaning / validation -------------------------------------------------

def test_clean_fixed_drops_blank_rows_and_parses_bools(cards):
    assert len(cards) == 6
    assert cards["Transferable"].dtype == bool
    assert not cards.loc[cards["Credit Card"] == "Capital One Savor", "Transferable"].any()


def test_clean_fixed_rejects_rotating_tab():
    # gviz returns a different tab when the requested name doesn't exist
    rotating_tab = "Card,Category,Rewards,Type,Transferable,Start_Month,End_Month\nDiscover It,Gas,5,Cash Back,FALSE,4,6\n"
    with pytest.raises(rw.DataError):
        rw.clean_fixed(rw.read_csv_text(rotating_tab))


def test_clean_fixed_rejects_html():
    with pytest.raises(rw.DataError):
        rw.clean_fixed(rw.read_csv_text("<html><body>Sign in</body></html>"))


def test_clean_rotating_drops_rows_without_year():
    legacy = pd.DataFrame({
        "Card": ["Discover It"], "Category": ["Gas"], "Rewards": [5], "Type": ["Cash Back"],
        "Transferable": [False], "Start_Month": [4], "End_Month": [6],
    })
    rows, undated = rw.clean_rotating(legacy)
    assert rows.empty and undated == 1


def test_clean_rotating_converts_start_month_when_year_present():
    df = pd.DataFrame({
        "Card": ["Discover It"], "Category": ["Restaurants"], "Rewards": [5], "Type": ["Cash Back"],
        "Transferable": [False], "Start_Month": [10], "End_Month": [12], "Year": [2026],
    })
    rows, undated = rw.clean_rotating(df)
    assert undated == 0
    assert rows.iloc[0]["Quarter"] == 4 and rows.iloc[0]["Category"] == "Dining"


# --- quarter selection -----------------------------------------------------

def _rot(card, cat, year, quarter):
    return {"Credit Card": card, "Category": cat, "Rewards": 5, "Type": "Points",
            "Transferable": True, "Year": year, "Quarter": quarter}


def test_rotating_for_quarter_ignores_same_quarter_last_year():
    df = pd.DataFrame([_rot("Chase Freedom Flex", "Dining", 2026, 1)])
    rows, _ = rw.rotating_for_quarter([("csv", df)], 2027, 1)
    assert rows.empty


def test_rotating_for_quarter_higher_priority_source_replaces_card():
    sheet = pd.DataFrame([_rot("Chase Freedom Flex", "Gas", 2026, 4)])
    csv = pd.DataFrame([_rot("Chase Freedom Flex", "Grocery Stores", 2026, 4),
                        _rot("Discover It", "Utilities", 2026, 4)])
    rows, picked = rw.rotating_for_quarter([("sheet", sheet), ("csv", csv)], 2026, 4)
    assert set(zip(rows["Credit Card"], rows["Category"])) == {
        ("Chase Freedom Flex", "Gas"), ("Discover It", "Utilities")}
    assert picked == {"Chase Freedom Flex": "sheet", "Discover It": "csv"}


def test_current_quarter():
    assert rw.current_quarter(datetime(2026, 10, 13)) == (2026, 4)
    assert rw.current_quarter(datetime(2026, 3, 31)) == (2026, 1)


# --- ranking -----------------------------------------------------------------

@pytest.mark.parametrize("category", ["Grocery Stores", "Online Shopping"])
def test_flat_rate_card_beats_weaker_category_bonus(cards, category):
    # At optimistic values, Active Cash: 2% x 1.75 = 3.5% beats a 3% category bonus
    ranked = rw.rank_category(cards, category)
    assert ranked.iloc[0]["Credit Card"] == "Wells Fargo Active Cash"
    assert ranked.iloc[0]["Basis"] == "everyday rate"


def test_unknown_category_falls_back_to_everyday_cards(cards):
    ranked = rw.rank_category(cards, "Car Washes")
    assert list(ranked["Credit Card"]) == ["Wells Fargo Active Cash", "Double Cash"]


def test_reward_tiers_groups_ties(cards):
    tiers = rw.reward_tiers(rw.rank_category(cards, "Dining"))
    assert list(tiers[0]["Credit Card"]) == ["Chase Sapphire Preferred"]
    assert list(tiers[1]["Credit Card"]) == ["Wells Fargo Active Cash"]


def test_rotating_rate_is_used_in_its_category(cards):
    rotating = pd.DataFrame([_rot("Chase Freedom Flex", "Restaurants", 2026, 4)])
    rows, _ = rw.rotating_for_quarter([("csv", rw.clean_rotating(rotating)[0])], 2026, 4)
    fixed = cards[rw.FIXED_COLUMNS]
    df = rw.add_valuations(rw.combine(fixed, rows), valuations=OPTIMISTIC)
    top = rw.rank_category(df, "Dining").iloc[0]
    assert top["Credit Card"] == "Chase Freedom Flex"
    assert top["Adjusted Rewards"] == pytest.approx(5 * 2.05)
    assert rw.card_note(top) == rw.ROTATING_NOTE


def test_citi_analysis_compares_against_everyday_cards(cards):
    result = rw.citi_custom_cash_analysis(cards, valuations=OPTIMISTIC).set_index("Category")
    # No card has a Drugstores bonus, so the comparison is Active Cash's 3.5%
    assert result.loc["Drugstores", "Best other card"] == "Wells Fargo Active Cash"
    assert result.loc["Drugstores", "Gain %"] == pytest.approx(1.5)
    assert result.loc["Dining", "Gain %"] < 0  # Sapphire Preferred's 6.15% beats 5%


def test_best_by_preset_flags_valuation_dependent_pick():
    base = rw.clean_fixed(rw.read_csv_text(FIXED_CSV))
    picks = rw.best_by_preset(base, "Online Shopping")
    assert picks["Optimistic"] == "Wells Fargo Active Cash"  # 2 x 1.75 = 3.5%
    assert picks["Conservative"] == "Bank of America Customized Cash Rewards"  # 2 x 1.4 = 2.8% < 3%
    assert picks["Cash"] == "Bank of America Customized Cash Rewards"


def test_best_by_preset_stable_pick():
    base = rw.clean_fixed(rw.read_csv_text(FIXED_CSV))
    picks = rw.best_by_preset(base, "Dining")
    assert picks["Conservative"] == picks["Optimistic"] == "Chase Sapphire Preferred"
    # At 1¢ a point, Sapphire's 3x ties Savor's 3% cash back
    assert picks["Cash"] == "Capital One Savor / Chase Sapphire Preferred"


def test_cash_preset_values_points_at_one_cent():
    df = rw.add_valuations(rw.clean_fixed(rw.read_csv_text(FIXED_CSV)), valuations=rw.VALUATION_PRESETS["Cash"])
    assert (df["Adjusted Rewards"] == df["Rewards"]).all()
