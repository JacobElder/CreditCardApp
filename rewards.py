"""Core rewards logic: data cleaning, category normalization, valuation and ranking.

Nothing in here imports Streamlit or touches the network, so it can be unit tested.
"""
import re
from datetime import datetime
from io import StringIO
from zoneinfo import ZoneInfo

import pandas as pd

TIMEZONE = ZoneInfo("America/New_York")

FIXED_COLUMNS = ["Credit Card", "Category", "Rewards", "Type", "Transferable"]
ROTATING_COLUMNS = FIXED_COLUMNS + ["Year", "Quarter"]
EVERYTHING = "Everything"

# ==========================================
# USER PREFERENCES
# ==========================================
# Set to True if you hold the "premium" card that unlocks transfer partners.
ENABLE_BOOSTS = {
    "Chase": True,
    "Wells Fargo": True,
    "Citi": False,
    "Capital One": False,
    "Amex": False,
}

# Cents per point when transferred to partners. Sources disagree a lot, so the app
# lets you pick; recommendations that flip between presets are flagged.
VALUATION_PRESETS = {
    # Median value of real award searches: https://frequentmiler.com/reasonable-redemption-values-rrvs/
    "Conservative": {"Chase": 1.5, "Wells Fargo": 1.4, "Citi": 1.5, "Capital One": 1.45, "Amex": 1.5},
    # The Points Guy, October 2026: https://thepointsguy.com/guide/monthly-valuations/
    "Optimistic": {"Chase": 2.05, "Wells Fargo": 1.75, "Citi": 1.9, "Capital One": 1.85, "Amex": 2.0},
    # Statement credit / cash out / travel portal
    "Cash": {},
}
PRESET_DESCRIPTIONS = {
    "Conservative": "typical transfer value (Frequent Miler medians)",
    "Optimistic": "best-case transfer value (The Points Guy)",
    "Cash": "points cashed out at 1¢",
}
DEFAULT_PRESET = "Conservative"
VALUATIONS = VALUATION_PRESETS[DEFAULT_PRESET]

# Caps and conditions worth seeing at checkout. Matched by card-name substring.
CARD_NOTES = {
    "Customized Cash": "3% capped at $2,500/quarter (shared with grocery 2%); choose the category in the BofA app.",
    "Cash Plus": "5% capped at $2,000/quarter combined; choose categories each quarter.",
    "Custom Cash": "5% applies to your top category only, up to $500/month.",
}
ROTATING_NOTE = "Rotating 5%: activate each quarter; capped at $1,500/quarter."

CITI_CUSTOM_CASH_CATEGORIES = [
    "Dining", "Gas", "Grocery Stores", "Travel", "Transit", "Streaming",
    "Drugstores", "Home Improvement", "Fitness Clubs", "Entertainment",
]

# Keys are the output of _category_key(); values are canonical category names.
CATEGORY_ALIASES = {
    "dining": "Dining",
    "restaurant": "Dining",
    "restaurants": "Dining",
    "grocery": "Grocery Stores",
    "groceries": "Grocery Stores",
    "grocery store": "Grocery Stores",
    "grocery stores": "Grocery Stores",
    "supermarkets": "Grocery Stores",
    "online grocery": "Online Groceries",
    "online groceries": "Online Groceries",
    "gas": "Gas",
    "gas stations": "Gas",
    "gas and ev charging": "Gas",
    "gas and ev charging stations": "Gas",
    "streaming": "Streaming",
    "streaming services": "Streaming",
    "entertainment": "Entertainment",
    "live entertainment": "Entertainment",
    "home improvement": "Home Improvement",
    "home improvement stores": "Home Improvement",
    "drugstores": "Drugstores",
    "drug stores": "Drugstores",
    "drugstore": "Drugstores",
    "pharmacies": "Drugstores",
    "gym": "Fitness Clubs",
    "gyms": "Fitness Clubs",
    "fitness clubs": "Fitness Clubs",
    "gyms fitness": "Fitness Clubs",
    "wholesale clubs": "Wholesale Clubs",
    "wholesale": "Wholesale Clubs",
    "phone": "Phone",
    "cell phone providers": "Phone",
    "utilities": "Utilities",
    "home utilities": "Utilities",
    "amazon": "Amazon",
    "amazon com": "Amazon",
    "travel": "Travel",
    "transit": "Transit",
    "public transit": "Transit",
    "ev charging": "Gas",
    "everything": EVERYTHING,
}

_FILLER_PREFIXES = ("select ", "eligible ")


def _category_key(raw):
    key = raw.lower().replace("&", " and ")
    key = re.sub(r"[^a-z0-9 ]+", " ", key)
    key = " ".join(key.split())
    for prefix in _FILLER_PREFIXES:
        if key.startswith(prefix):
            key = key[len(prefix):]
    return key.removesuffix(" purchases")


def normalize_category(raw):
    """Map a category name from any source onto one canonical spelling.

    Unknown categories are kept (title-cased only if they arrived all lower-case)
    so new rotating categories still show up rather than disappearing.
    """
    if not isinstance(raw, str) or not raw.strip():
        return None
    key = _category_key(raw)
    if key in CATEGORY_ALIASES:
        return CATEGORY_ALIASES[key]
    raw = " ".join(re.sub(r"[™℠®]", "", raw).split())
    return raw.title() if raw == raw.lower() else raw


def get_issuer(card_name):
    name = card_name.lower()
    if "chase" in name: return "Chase"
    if "wells fargo" in name: return "Wells Fargo"
    if "citi" in name or "double cash" in name: return "Citi"
    if "capital one" in name: return "Capital One"
    if "discover" in name: return "Discover"
    if "amex" in name or "american express" in name: return "Amex"
    return "Default"


def current_quarter(now=None):
    now = now or datetime.now(TIMEZONE)
    return now.year, (now.month - 1) // 3 + 1


def quarter_label(year, quarter):
    return f"Q{quarter} {year}"


class DataError(ValueError):
    """A data source is unusable (wrong shape, wrong tab, unparseable)."""


def _to_bool(value):
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "yes", "y", "1"}


def read_csv_text(text):
    try:
        return pd.read_csv(StringIO(text), encoding_errors="replace")
    except Exception as e:  # pandas raises several parser error types
        raise DataError(f"not valid CSV ({e.__class__.__name__})") from e


def clean_table(df, required_columns):
    """Validate columns, drop blank rows, coerce types and normalize categories.

    Raises DataError if the table doesn't have the expected shape, which is how a
    renamed Google Sheets tab is caught (gviz silently returns a different tab).
    """
    df = df.rename(columns=lambda c: str(c).replace("﻿", "").strip())
    df = df.rename(columns={"Card": "Credit Card"})
    missing = [c for c in required_columns if c not in df.columns]
    if missing:
        raise DataError(f"missing columns {missing}; got {list(df.columns)}")

    df = df.copy()
    df["Credit Card"] = df["Credit Card"].astype("string").str.strip()
    df["Category"] = df["Category"].map(normalize_category)
    df["Rewards"] = pd.to_numeric(
        df["Rewards"].astype("string").str.replace("%", "").str.strip(), errors="coerce"
    )
    df["Transferable"] = df["Transferable"].map(_to_bool)
    df["Type"] = df["Type"].fillna("").astype(str).str.strip()
    df = df.dropna(subset=["Credit Card", "Category", "Rewards"])
    df = df[df["Credit Card"] != ""]
    for col in ("Year", "Quarter"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
    return df.reset_index(drop=True)


def clean_fixed(df):
    df = clean_table(df, FIXED_COLUMNS)
    if {"Start_Month", "Quarter", "Year"} & set(df.columns):
        raise DataError("looks like the rotating table, not the fixed one")
    if df.empty:
        raise DataError("no rows")
    return df[FIXED_COLUMNS]


def clean_rotating(df):
    """Returns (cleaned rows that have Year+Quarter, number of rows dropped for lacking them).

    Older data used Start_Month/End_Month with no year, which silently re-applied
    old categories every year. Those are converted when a Year column exists,
    and dropped otherwise.
    """
    df = clean_table(df, FIXED_COLUMNS)
    if "Quarter" not in df.columns and "Start_Month" in df.columns:
        df["Quarter"] = (pd.to_numeric(df["Start_Month"], errors="coerce") - 1) // 3 + 1
    if "Year" not in df.columns or "Quarter" not in df.columns:
        return pd.DataFrame(columns=ROTATING_COLUMNS), len(df)
    df["Year"] = pd.to_numeric(df["Year"], errors="coerce").astype("Int64")
    df["Quarter"] = pd.to_numeric(df["Quarter"], errors="coerce").astype("Int64")
    undated = df["Year"].isna() | df["Quarter"].isna()
    columns = ROTATING_COLUMNS + (["Source"] if "Source" in df.columns else [])
    return df.loc[~undated, columns].reset_index(drop=True), int(undated.sum())


def rotating_for_quarter(sources, year, quarter):
    """Pick current-quarter rotating rows, card by card, from prioritized sources.

    `sources` is a list of (label, df) from highest to lowest priority. For each card,
    the first source that has rows for that card this quarter wins outright, so a
    manual correction replaces scraped categories instead of adding to them.
    Returns (rows, {card: label}).
    """
    chosen, picked = [], {}
    for label, df in sources:
        if df is None or df.empty:
            continue
        rows = df[(df["Year"] == year) & (df["Quarter"] == quarter)]
        for card, card_rows in rows.groupby("Credit Card"):
            if card not in picked:
                picked[card] = label
                chosen.append(card_rows)
    if not chosen:
        return pd.DataFrame(columns=ROTATING_COLUMNS), picked
    return pd.concat(chosen, ignore_index=True), picked


def combine(fixed, rotating):
    fixed = fixed.assign(Rotating=False)
    if rotating.empty:
        return fixed.reset_index(drop=True)
    rotating = rotating[FIXED_COLUMNS].assign(Rotating=True)
    df = pd.concat([fixed, rotating], ignore_index=True)
    df["Transferable"] = df["Transferable"].astype(bool)
    # A card's rotating rate replaces its fixed rate for the same category
    return df.drop_duplicates(subset=["Credit Card", "Category"], keep="last").reset_index(drop=True)


def point_multiplier(card, transferable, boosts=ENABLE_BOOSTS, valuations=VALUATIONS):
    if not transferable:
        return 1.0
    issuer = get_issuer(card)
    if not boosts.get(issuer, False):
        return 1.0
    return valuations.get(issuer, 1.0)


def add_valuations(df, boosts=ENABLE_BOOSTS, valuations=VALUATIONS):
    df = df.copy()
    df["Multiplier"] = [
        point_multiplier(card, t, boosts, valuations)
        for card, t in zip(df["Credit Card"], df["Transferable"])
    ]
    df["Adjusted Rewards"] = df["Rewards"] * df["Multiplier"]
    return df


def card_note(row):
    if row.get("Rotating", False):
        return ROTATING_NOTE
    for fragment, note in CARD_NOTES.items():
        if fragment.lower() in row["Credit Card"].lower():
            return note
    return ""


def rank_category(df, category):
    """All cards that earn in `category`, including flat-rate 'Everything' cards.

    Each card appears once, at its best rate for this purchase.
    """
    rows = df[df["Category"].isin([category, EVERYTHING])].copy()
    rows["Basis"] = rows["Category"].map(lambda c: "everyday rate" if c == EVERYTHING else "category bonus")
    rows = rows.sort_values(["Adjusted Rewards", "Basis"], ascending=[False, True])
    rows = rows.drop_duplicates(subset=["Credit Card"], keep="first")
    return rows.reset_index(drop=True)


def best_by_preset(base, category, boosts=ENABLE_BOOSTS, presets=VALUATION_PRESETS):
    """{preset: best card(s)} for a category, to show whether the pick depends on valuation.

    `base` is the combined table before add_valuations. Ties are joined with " / ".
    """
    result = {}
    for name, valuations in presets.items():
        ranked = rank_category(add_valuations(base, boosts, valuations), category)
        if not ranked.empty:
            result[name] = " / ".join(reward_tiers(ranked, n=1)[0]["Credit Card"])
    return result


def reward_tiers(ranked, n=2):
    """Group ranked rows into the top `n` distinct adjusted-reward levels (ties share a tier)."""
    levels = sorted(ranked["Adjusted Rewards"].round(6).unique(), reverse=True)[:n]
    return [ranked[ranked["Adjusted Rewards"].round(6) == lvl] for lvl in levels]


def citi_custom_cash_analysis(df, citi_rate=5.0, boosts=ENABLE_BOOSTS, valuations=VALUATIONS):
    """For each Custom Cash category: your best other card, and what Custom Cash would add."""
    citi_value = citi_rate * point_multiplier("Citi Custom Cash", True, boosts, valuations)
    others = df[~df["Credit Card"].str.contains("Custom Cash", case=False)]
    rows = []
    for category in CITI_CUSTOM_CASH_CATEGORIES:
        ranked = rank_category(others, category)
        if ranked.empty:
            best_card, best = "None", 0.0
        else:
            best_card, best = ranked.iloc[0]["Credit Card"], ranked.iloc[0]["Adjusted Rewards"]
        rows.append({
            "Category": category,
            "Best other card": best_card,
            "Best other %": round(best, 2),
            "Custom Cash %": round(citi_value, 2),
            "Gain %": round(citi_value - best, 2),
        })
    return pd.DataFrame(rows).sort_values("Gain %", ascending=False).reset_index(drop=True)
