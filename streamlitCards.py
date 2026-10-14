#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import re
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

import rewards as rw
import rotating_scraper

st.set_page_config(page_title="Credit Card Rewards", layout="centered")

SHEET_ID = "1768M96W_Bhrna5PMGNuMOWB-i05F7vE1cVq8zO97I-w"
HERE = Path(__file__).parent
LOCAL_FIXED = HERE / "CreditCards.csv"
LOCAL_ROTATING = HERE / "RotatingCategories.csv"
EVERYTHING_LABEL = "Anything else"


# ==========================================
# DATA LOADING
# ==========================================
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_sheet_tab(tab):
    """Returns (csv_text, None) or (None, error)."""
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet={tab}"
    try:
        resp = requests.get(url, timeout=5)
    except requests.RequestException as e:
        return None, f"request failed ({e.__class__.__name__})"
    if resp.status_code != 200:
        return None, f"HTTP {resp.status_code}"
    if "text/csv" not in resp.headers.get("Content-Type", ""):
        return None, "response wasn't CSV - is the sheet still shared publicly?"
    return resp.text, None


@st.cache_data(ttl=86400, show_spinner=False)
def scrape_live(year, quarter):
    """Last-resort live scrape. Returns (df, None) or (None, reason)."""
    try:
        df = rotating_scraper.fetch_quarter(year, quarter)
    except rotating_scraper.ScrapeError as e:
        return None, str(e)
    return (df, None) if df is not None else (None, "Doctor of Credit hasn't posted this quarter yet")


def load_fixed(warnings, status):
    text, err = fetch_sheet_tab("Fixed")
    if text is not None:
        try:
            fixed = rw.clean_fixed(rw.read_csv_text(text))
            status.append(f"Fixed rewards: Google Sheet ({len(fixed)} rows)")
            return fixed
        except rw.DataError as e:
            err = str(e)
    warnings.append(f"Couldn't use the Google Sheet's Fixed tab ({err}). Using the local backup CSV instead.")
    fixed = rw.clean_fixed(pd.read_csv(LOCAL_FIXED))
    status.append(f"Fixed rewards: local CreditCards.csv ({len(fixed)} rows)")
    return fixed


def load_rotating(year, quarter, warnings, status):
    # Highest priority first: Sheet rows are manual corrections, the repo CSV is
    # maintained by the scheduled GitHub Action, and a live scrape is the last resort.
    sources = []
    text, err = fetch_sheet_tab("Rotating")
    if text is not None:
        try:
            sheet_rows, undated = rw.clean_rotating(rw.read_csv_text(text))
            sources.append(("Google Sheet", sheet_rows))
            if undated:
                status.append(f"Ignored {undated} Sheet rotating rows without Year/Quarter columns.")
        except rw.DataError as e:
            status.append(f"Sheet Rotating tab unusable: {e}")
    else:
        status.append(f"Sheet Rotating tab unavailable: {err}")

    repo_rows, _ = rw.clean_rotating(pd.read_csv(LOCAL_ROTATING))
    sources.append(("RotatingCategories.csv (auto-updated)", repo_rows))

    rotating, picked = rw.rotating_for_quarter(sources, year, quarter)
    if rotating.empty:
        live, reason = scrape_live(year, quarter)
        if live is not None:
            rotating, picked = rw.rotating_for_quarter([("Doctor of Credit (live)", live)], year, quarter)
            warnings.append("This quarter's 5% categories were read live from Doctor of Credit and haven't been reviewed yet.")
        else:
            warnings.append(f"No 5% rotating categories found for {rw.quarter_label(year, quarter)} ({reason}).")
    for card, source in picked.items():
        status.append(f"{card} rotating categories: {source}")
    return rotating


def load_data(year, quarter):
    warnings, status = [], []
    fixed = load_fixed(warnings, status)
    rotating = load_rotating(year, quarter, warnings, status)
    return rw.combine(fixed, rotating), warnings, status


# ==========================================
# FORMATTING
# ==========================================
def md_escape(text):
    return re.sub(r"([\\`*_{}\[\]()#+!|<>~])", r"\\\1", str(text))


def format_rate(row):
    base, mult = row["Rewards"], row["Multiplier"]
    if mult > 1:
        earned = f"{base:g}x points" if "point" in row["Type"].lower() else f"{base:g}% back, transferred as points"
        return f"**{row['Adjusted Rewards']:.2f}%** value ({earned} × {mult:g}¢)"
    if "point" in row["Type"].lower():
        return f"**{base:g}%** ({base:g}x points at 1¢)"
    return f"**{base:g}%** cash back"


def render_card(row):
    with st.container(border=True):
        st.markdown(f"**{md_escape(row['Credit Card'])}** · {format_rate(row)}")
        details = [rw.card_note(row)]
        if row["Basis"] == "everyday rate":
            details.insert(0, "everyday rate")
        details = [d for d in details if d]
        if details:
            st.caption(" · ".join(details))


# ==========================================
# PAGE
# ==========================================
year, quarter = rw.current_quarter()
base, warnings, status = load_data(year, quarter)

st.title("Best Credit Card for Rewards")
preset = st.segmented_control(
    "Value points at", list(rw.VALUATION_PRESETS), default=rw.DEFAULT_PRESET, key="preset",
) or rw.DEFAULT_PRESET
df = rw.add_valuations(base, valuations=rw.VALUATION_PRESETS[preset])
st.caption(
    f"{rw.quarter_label(year, quarter)} · loaded {datetime.now(rw.TIMEZONE):%b %d, %I:%M %p} ET · "
    f"points at {rw.PRESET_DESCRIPTIONS[preset]}"
)
for message in warnings:
    st.warning(message)

categories = sorted((c for c in df["Category"].unique() if c != rw.EVERYTHING), key=str.lower)
choice = st.pills("What are you buying?", categories + [EVERYTHING_LABEL], key="category")

if choice:
    category = rw.EVERYTHING if choice == EVERYTHING_LABEL else choice
    ranked = rw.rank_category(df, category)
    picks = rw.best_by_preset(base, category)
    if rw.depends_on_valuation(picks):
        st.info("The best card depends on how you redeem points: "
                + "; ".join(f"{name}: {md_escape(' / '.join(cards))}" for name, cards in picks.items()))
    for label, tier in zip(["Best", "Next best"], rw.reward_tiers(ranked)):
        st.markdown(f"#### {label}")
        for _, row in tier.iterrows():
            render_card(row)

    with st.expander("All cards for this purchase"):
        table = ranked[["Credit Card", "Rewards", "Adjusted Rewards", "Type", "Basis"]]
        table.columns = ["Card", "Base %", "Value %", "Type", "Basis"]
        st.dataframe(table, hide_index=True, width="stretch")

st.divider()
st.subheader("Citi Custom Cash: where would it help most?")
citi = rw.citi_custom_cash_analysis(df, valuations=rw.VALUATION_PRESETS[preset])
top = citi.iloc[0]
if top["Gain %"] > 0:
    tied = citi[citi["Gain %"] == top["Gain %"]]
    if len(tied) == 1:
        where = f"**{top['Category']}**"
    else:
        where = "a tie between " + ", ".join(f"**{c}**" for c in tied["Category"])
    alternatives = " / ".join(dict.fromkeys(tied["Best other card"]))
    st.write(
        f"Its 5% would add the most in {where}: {top['Gain %']:.2f}% more than your best "
        f"alternative, {md_escape(alternatives)} ({top['Best other %']:.2f}%)."
    )
else:
    st.write("Your other cards already match or beat 5% in every Custom Cash category.")
st.dataframe(citi, hide_index=True, width="stretch")

with st.expander("Data sources"):
    for line in status:
        st.write(f"- {md_escape(line)}")
