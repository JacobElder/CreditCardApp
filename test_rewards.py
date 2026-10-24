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
    assert picks["Optimistic"] == ["Wells Fargo Active Cash"]  # 2 x 1.75 = 3.5%
    assert picks["Conservative"] == ["Bank of America Customized Cash Rewards"]  # 2 x 1.4 = 2.8% < 3%
    assert picks["Cash"] == ["Bank of America Customized Cash Rewards"]
    assert rw.depends_on_valuation(picks)


def test_best_by_preset_stable_pick():
    base = rw.clean_fixed(rw.read_csv_text(FIXED_CSV))
    picks = rw.best_by_preset(base, "Dining")
    assert picks["Conservative"] == picks["Optimistic"] == ["Chase Sapphire Preferred"]
    # At 1¢ a point, Sapphire's 3x ties Savor's 3% cash back - still a winner, so no flag
    assert picks["Cash"] == ["Capital One Savor", "Chase Sapphire Preferred"]
    assert not rw.depends_on_valuation(picks)


def test_cash_preset_values_points_at_one_cent():
    df = rw.add_valuations(rw.clean_fixed(rw.read_csv_text(FIXED_CSV)), valuations=rw.VALUATION_PRESETS["Cash"])
    assert (df["Adjusted Rewards"] == df["Rewards"]).all()


# --- parsing edge cases --------------------------------------------------------

@pytest.mark.parametrize("value, expected", [
    (True, True), (False, False), (1, True), (0, False), (1.0, True), (0.0, False),
    (float("nan"), False), ("1", True), ("1.0", True), (" Yes ", True), ("y", True),
    ("TRUE", True), ("FALSE", False), ("no", False), ("", False),
])
def test_to_bool(value, expected):
    assert rw._to_bool(value) is expected


def test_clean_fixed_reads_numeric_transferable_column_with_blank_row():
    # The blank row makes pandas read Transferable as 1.0/0.0
    text = "Credit Card,Category,Rewards,Type,Transferable\nChase Sapphire Preferred,Dining,3,Points,1\nCapital One Savor,Dining,3,Cash Back,0\n,,,,\n"
    df = rw.clean_fixed(rw.read_csv_text(text)).set_index("Credit Card")
    assert df.loc["Chase Sapphire Preferred", "Transferable"] == True  # noqa: E712
    assert df.loc["Capital One Savor", "Transferable"] == False  # noqa: E712


def test_clean_fixed_parses_bools_in_fixture(cards):
    flags = cards.set_index("Credit Card")["Transferable"]
    assert flags["Chase Sapphire Preferred"] and flags["Wells Fargo Active Cash"]
    assert not flags["Double Cash"]


def test_clean_fixed_rate_formats_and_header_quirks():
    text = "﻿Card,Category,Rewards,Type,Transferable\nA,Dining,5%,Points,TRUE\nB,Gas,3x,Points,TRUE\nC,Travel,lots,Points,TRUE\n"
    df = rw.clean_fixed(rw.read_csv_text(text))
    assert list(df["Credit Card"]) == ["A", "B"]  # BOM stripped, Card renamed, unparseable rate dropped
    assert list(df["Rewards"]) == [5, 3]


def test_clean_fixed_rejects_header_only():
    with pytest.raises(rw.DataError, match="no rows"):
        rw.clean_fixed(rw.read_csv_text("Credit Card,Category,Rewards,Type,Transferable\n"))


def test_clean_fixed_rejects_table_with_year_column():
    text = "Credit Card,Category,Rewards,Type,Transferable,Year,Quarter\nDiscover It,Gas,5,Cash Back,FALSE,2026,4\n"
    with pytest.raises(rw.DataError, match="rotating"):
        rw.clean_fixed(rw.read_csv_text(text))


def test_clean_table_names_missing_column():
    with pytest.raises(rw.DataError, match="Transferable"):
        rw.clean_fixed(rw.read_csv_text("Credit Card,Category,Rewards,Type\nA,Dining,3,Points\n"))


def test_read_csv_text_rejects_empty_text():
    with pytest.raises(rw.DataError, match="not valid CSV"):
        rw.read_csv_text("")


@pytest.mark.parametrize("month, quarter", [(1, 1), (3, 1), (4, 2), (6, 2), (7, 3), (9, 3), (10, 4), (12, 4)])
def test_clean_rotating_start_month_to_quarter(month, quarter):
    df = pd.DataFrame({"Card": ["Discover It"], "Category": ["Gas"], "Rewards": [5], "Type": ["Cash Back"],
                       "Transferable": [False], "Start_Month": [month], "Year": [2026]})
    rows, undated = rw.clean_rotating(df)
    assert undated == 0 and rows.iloc[0]["Quarter"] == quarter


def test_clean_rotating_counts_blank_year_as_undated():
    df = pd.DataFrame({"Card": ["Discover It", "Discover It"], "Category": ["Gas", "Dining"], "Rewards": [5, 5],
                       "Type": ["Cash Back"] * 2, "Transferable": [False] * 2, "Year": [2026, None], "Quarter": [4, 4]})
    rows, undated = rw.clean_rotating(df)
    assert list(rows["Category"]) == ["Gas"] and undated == 1


@pytest.mark.parametrize("raw, expected", [
    ("Eligible Gas Purchases", "Gas"),
    ("Select Restaurants", "Dining"),
    ("  dining  ", "Dining"),
    ("Disney+™", "Disney+"),
    ("EV charging", "Gas"),
    ("Transportation", "Transit"),
    ("Grocery Store Purchases", "Grocery Stores"),
])
def test_normalize_category_more(raw, expected):
    assert rw.normalize_category(raw) == expected


@pytest.mark.parametrize("card, issuer", [
    ("Chase Freedom Flex", "Chase"), ("Wells Fargo Autograph", "Wells Fargo"), ("Citi Custom Cash", "Citi"),
    ("Capital One Savor", "Capital One"), ("Discover It", "Discover"), ("Amex Gold", "Amex"),
    ("American Express Blue Cash", "Amex"), ("Bank of America Customized Cash Rewards", "Default"),
])
def test_get_issuer(card, issuer):
    assert rw.get_issuer(card) == issuer


def test_current_quarter_year_boundary():
    assert rw.current_quarter(datetime(2026, 12, 31, 23, 59, tzinfo=rw.TIMEZONE)) == (2026, 4)
    assert rw.current_quarter(datetime(2027, 1, 1, 0, 0, tzinfo=rw.TIMEZONE)) == (2027, 1)
    assert rw.quarter_label(2026, 4) == "Q4 2026"


# --- quarter selection / combining ---------------------------------------------

def test_rotating_for_quarter_picks_only_that_quarter_and_skips_empty_sources():
    df = pd.DataFrame([_rot("Discover It", "Gas", 2026, 3), _rot("Discover It", "Dining", 2026, 4)])
    rows, picked = rw.rotating_for_quarter([("sheet", None), ("empty", df.iloc[0:0]), ("csv", df)], 2026, 4)
    assert list(rows["Category"]) == ["Dining"]
    assert picked == {"Discover It": "csv"}
    rows, _ = rw.rotating_for_quarter([("csv", df)], 2026, 3)
    assert list(rows["Category"]) == ["Gas"]


def test_combine_rotating_rate_overrides_fixed_rate_for_same_card():
    fixed = pd.DataFrame([{"Credit Card": "Chase Freedom Flex", "Category": "Dining", "Rewards": 3,
                           "Type": "Points", "Transferable": True}])
    rotating = pd.DataFrame([_rot("Chase Freedom Flex", "Dining", 2026, 4)])
    df = rw.combine(fixed, rotating)
    assert len(df) == 1
    assert df.iloc[0]["Rewards"] == 5 and df.iloc[0]["Rotating"]


# --- valuation -----------------------------------------------------------------

ALL_BOOSTS = dict.fromkeys(rw.ENABLE_BOOSTS, True)


@pytest.mark.parametrize("preset", list(rw.VALUATION_PRESETS))
@pytest.mark.parametrize("card, issuer", [
    ("Chase Sapphire", "Chase"), ("Wells Fargo Autograph", "Wells Fargo"), ("Citi Strata", "Citi"),
    ("Capital One Venture", "Capital One"), ("Amex Gold", "Amex"),
])
def test_point_multiplier_uses_preset_value_per_issuer(preset, card, issuer):
    valuations = rw.VALUATION_PRESETS[preset]
    assert rw.point_multiplier(card, True, ALL_BOOSTS, valuations) == valuations.get(issuer, 1.0)


def test_point_multiplier_needs_transferable_and_boost():
    optimistic = rw.VALUATION_PRESETS["Optimistic"]
    assert rw.point_multiplier("Chase Sapphire", False, ALL_BOOSTS, optimistic) == 1.0
    assert rw.point_multiplier("Chase Sapphire", True, {"Chase": False}, optimistic) == 1.0
    assert rw.point_multiplier("Discover It", True, ALL_BOOSTS, optimistic) == 1.0
    assert rw.point_multiplier("Mystery Card", True, ALL_BOOSTS, optimistic) == 1.0


# --- ranking -------------------------------------------------------------------

def _valued(rows):
    return rw.add_valuations(pd.DataFrame(rows).assign(Rotating=False), valuations={})


def _fixed(card, cat, rate, type_="Cash Back"):
    return {"Credit Card": card, "Category": cat, "Rewards": rate, "Type": type_, "Transferable": False}


def test_rank_category_tie_with_everyday_rate_reports_category_bonus():
    df = _valued([_fixed("Card A", rw.EVERYTHING, 3), _fixed("Card A", "Dining", 3)])
    ranked = rw.rank_category(df, "Dining")
    assert len(ranked) == 1 and ranked.iloc[0]["Basis"] == "category bonus"


def test_rank_category_keeps_each_card_at_its_best_rate():
    df = _valued([_fixed("Card A", "Dining", 2), _fixed("Card A", rw.EVERYTHING, 3), _fixed("Card B", "Dining", 2.5)])
    ranked = rw.rank_category(df, "Dining")
    assert list(ranked["Credit Card"]) == ["Card A", "Card B"]
    assert ranked.iloc[0]["Rewards"] == 3 and ranked.iloc[0]["Basis"] == "everyday rate"


def test_best_by_preset_omits_presets_with_no_cards():
    base = pd.DataFrame([_fixed("Card A", "Dining", 3)]).assign(Rotating=False)
    assert rw.best_by_preset(base, "Gas") == {}


def test_depends_on_valuation_edge_cases():
    assert not rw.depends_on_valuation({})
    assert not rw.depends_on_valuation({"Cash": ["A"]})
    assert not rw.depends_on_valuation({"x": ["A", "B"], "y": ["B"], "z": ["B", "C"]})
    assert rw.depends_on_valuation({"x": ["A", "B"], "y": ["B", "C"], "z": ["C"]})


# --- notes / formatting ----------------------------------------------------------

@pytest.mark.parametrize("card, note", [
    ("Bank of America Customized Cash Rewards", rw.CARD_NOTES["Customized Cash"]),
    ("U.S. Bank Cash Plus", rw.CARD_NOTES["Cash Plus"]),
    ("Citi Custom Cash", rw.CARD_NOTES["Custom Cash"]),
    ("Capital One Savor", ""),
])
def test_card_note(card, note):
    assert rw.card_note({"Credit Card": card, "Rotating": False}) == note
    assert rw.card_note({"Credit Card": card, "Rotating": True}) == rw.ROTATING_NOTE


def test_md_escape():
    assert rw.md_escape("a*b_[c](d)#") == r"a\*b\_\[c\]\(d\)\#"
    assert rw.md_escape("$2,500 and $500") == r"\$2,500 and \$500"


@pytest.mark.parametrize("row, expected", [
    ({"Rewards": 3, "Multiplier": 1.0, "Adjusted Rewards": 3, "Type": "Cash Back"}, "**3%** cash back"),
    ({"Rewards": 3, "Multiplier": 1.0, "Adjusted Rewards": 3, "Type": "Points"}, "**3%** (3x points at 1¢)"),
    ({"Rewards": 3, "Multiplier": 2.05, "Adjusted Rewards": 6.15, "Type": "Points"},
     "**6.15%** value (3x points × 2.05¢)"),
    ({"Rewards": 2, "Multiplier": 1.4, "Adjusted Rewards": 2.8, "Type": "Cash Back"},
     "**2.80%** value (2% back, transferred as points × 1.4¢)"),
])
def test_format_rate(row, expected):
    assert rw.format_rate(row) == expected


# --- Citi Custom Cash -------------------------------------------------------------

def test_citi_analysis_no_card_in_category():
    df = _valued([_fixed("Card A", "Dining", 3)])
    result = rw.citi_custom_cash_analysis(df, valuations={}).set_index("Category")
    assert result.loc["Gas", "Best other card"] == "None"
    assert result.loc["Gas", "Best other %"] == 0 and result.loc["Gas", "Gain %"] == 5


def test_citi_analysis_sorted_by_gain_and_excludes_custom_cash():
    df = _valued([_fixed("Card A", "Dining", 4), _fixed("Card B", "Gas", 1),
                  _fixed("citi custom cash", "Travel", 5)])
    result = rw.citi_custom_cash_analysis(df, valuations={})
    assert list(result["Gain %"]) == sorted(result["Gain %"], reverse=True)
    assert "citi custom cash" not in set(result["Best other card"])
    assert result.set_index("Category").loc["Travel", "Best other card"] == "None"


def test_citi_analysis_applies_citi_boost():
    df = _valued([_fixed("Card A", "Dining", 4)])
    result = rw.citi_custom_cash_analysis(df, boosts={"Citi": True}, valuations={"Citi": 1.5})
    assert set(result["Custom Cash %"]) == {7.5}
