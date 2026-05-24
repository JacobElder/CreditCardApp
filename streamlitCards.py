#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
import streamlit.components.v1 as components
from datetime import datetime
import requests
from io import StringIO

st.set_page_config(
    page_title="Credit Card Rewards",
    layout="wide",
)

# ==========================================
# CONFIGURATION & USER PREFERENCES
# ==========================================
SHEET_ID = "1768M96W_Bhrna5PMGNuMOWB-i05F7vE1cVq8zO97I-w"

# Set to True if you have the "Premium" card required for transfers
ENABLE_BOOSTS = {
    "Chase": True,
    "Wells Fargo": True,
    "Citi": False,
    "Capital One": False,
    "Amex": False,
}

# Empirical Valuations (CPP / 100) - April 2026
VALUATIONS = {
    "Chase": 2.05,
    "Wells Fargo": 1.65,
    "Citi": 1.6,
    "Capital One": 1.85,
    "Amex": 2.0,
    "Default": 1.0
}

def get_issuer(card_name):
    card_name = card_name.lower()
    if "chase" in card_name: return "Chase"
    if "wells fargo" in card_name: return "Wells Fargo"
    if "citi" in card_name: return "Citi"
    if "capital one" in card_name: return "Capital One"
    if "discover" in card_name: return "Discover"
    if "amex" in card_name or "american express" in card_name: return "Amex"
    return "Default"

from bs4 import BeautifulSoup
import re

@st.cache_data(ttl=86400)
def scrape_rotating_categories():
    """Returns (df, error_str_or_None, scraped_at_or_None)."""
    try:
        now = datetime.now()
        current_quarter = (now.month - 1) // 3 + 1
        year = now.year

        url = f"https://www.doctorofcredit.com/q{current_quarter}-{year}-5-quarterly-categories-activate-offers-suggestions-freedom-flex-discover-dividend-cash-more/"
        resp = requests.get(url, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})

        if resp.status_code != 200:
            url = "https://www.doctorofcredit.com/current-5-quarterly-bonus-cards-chase-freedom-discover-more-others/"
            resp = requests.get(url, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
            if resp.status_code != 200:
                return pd.DataFrame(), "Doctor of Credit unreachable", None

        soup = BeautifulSoup(resp.text, 'html.parser')

        scraped_data = []
        now = datetime.now()
        current_quarter = (now.month - 1) // 3 + 1
        start_month = (current_quarter - 1) * 3 + 1
        end_month = current_quarter * 3

        for target in soup.find_all(['li', 'h2', 'h3', 'p', 'strong']):
            text = target.get_text().lower()
            card_name = None
            if 'chase freedom' in text or 'chase travel' in text:
                card_name = "Chase Freedom Flex"
            elif 'discover' in text:
                card_name = "Discover It"

            if card_name and (':' in text or '–' in text):
                delimiter = ':' if ':' in text else '–'
                parts = text.split(delimiter, 1)
                if len(parts) > 1:
                    categories_raw = parts[1].split(',')
                    for cat in categories_raw:
                        clean_cat = re.sub(r'\(.*?\)', '', cat).strip().title()
                        if clean_cat and len(clean_cat) < 50:
                            scraped_data.append({
                                'Credit Card': card_name,
                                'Category': clean_cat,
                                'Rewards': 5,
                                'Type': 'Points' if 'Chase' in card_name else 'Cash Back',
                                'Transferable': True if 'Chase' in card_name else False,
                                'Start_Month': start_month,
                                'End_Month': end_month
                            })

        df = pd.DataFrame(scraped_data)
        return df.drop_duplicates(), None, datetime.now()
    except Exception as e:
        return pd.DataFrame(), str(e), None

@st.cache_data(ttl=3600)
def fetch_data():
    """Returns (df, source_label, fetched_at, scrape_error)."""
    combined_rotating = pd.DataFrame()
    fetched_at = datetime.now()

    scraped_df, scrape_error, _scraped_at = scrape_rotating_categories()
    if not scraped_df.empty:
        combined_rotating = scraped_df

    try:
        def get_sheet_url(sheet_name):
            return f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet={sheet_name}"

        fixed_resp = requests.get(get_sheet_url("Fixed"), timeout=5)
        rotating_resp = requests.get(get_sheet_url("Rotating"), timeout=5)

        fixed_df = pd.read_csv(StringIO(fixed_resp.text)) if fixed_resp.status_code == 200 else pd.DataFrame()

        sheet_rotating = pd.read_csv(StringIO(rotating_resp.text)) if rotating_resp.status_code == 200 else pd.DataFrame()
        if not sheet_rotating.empty:
            sheet_rotating = sheet_rotating.rename(columns={'Card': 'Credit Card'})
            combined_rotating = pd.concat([combined_rotating, sheet_rotating], ignore_index=True)

        now = datetime.now()
        if not combined_rotating.empty and 'Start_Month' in combined_rotating.columns:
            combined_rotating = combined_rotating[
                (combined_rotating['Start_Month'] <= now.month) &
                (combined_rotating['End_Month'] >= now.month)
            ]

        combined = pd.concat([fixed_df, combined_rotating], ignore_index=True)
        combined = combined.drop_duplicates(subset=['Credit Card', 'Category'], keep='last')

        source = "live" if not scraped_df.empty else "sheets"
        return combined[['Credit Card', 'Category', 'Rewards', 'Type', 'Transferable']], source, fetched_at, scrape_error
    except Exception:
        try:
            fixed_df = pd.read_csv('CreditCards.csv')
            rotating_df = pd.read_csv('RotatingCategories.csv')

            now = datetime.now()
            if not rotating_df.empty:
                rotating_df = rotating_df[
                    (rotating_df['Start_Month'] <= now.month) &
                    (rotating_df['End_Month'] >= now.month)
                ]
                rotating_df = rotating_df.rename(columns={'Card': 'Credit Card'})

            combined = pd.concat([fixed_df, rotating_df], ignore_index=True)
            combined = combined.drop_duplicates(subset=['Credit Card', 'Category'], keep='last')
            return combined[['Credit Card', 'Category', 'Rewards', 'Type', 'Transferable']], "local", fetched_at, scrape_error
        except Exception:
            return pd.read_csv('CreditCards.csv'), "local", fetched_at, scrape_error

# Load and Process Data
df, data_source, data_fetched_at, scrape_error = fetch_data()

def calculate_adjusted_rewards(row):
    if not row['Transferable']:
        return row['Rewards']

    issuer = get_issuer(row['Credit Card'])
    if not ENABLE_BOOSTS.get(issuer, False):
        return row['Rewards']

    multiplier = VALUATIONS.get(issuer, VALUATIONS["Default"])
    return row['Rewards'] * multiplier

df['Adjusted Rewards'] = df.apply(calculate_adjusted_rewards, axis=1)

# Normalization & UI
category_aliases = {
    "Dining": "Restaurants", "Restaurants": "Restaurants", "Gas": "Gas",
    "Grocery Stores": "Grocery Stores", "Groceries": "Grocery Stores",
    "Travel": "Travel", "Transit": "Transit", "Streaming": "Streaming",
    "Drugstores": "Drugstores", "Home Improvement": "Home Improvement",
    "Home Improvement Stores": "Home Improvement", "Gym": "Fitness Clubs",
    "Entertainment": "Live Entertainment", "Amazon": "Amazon"
}

citi_categories = [
    "Restaurants", "Gas", "Grocery Stores", "Travel", "Transit",
    "Streaming", "Drugstores", "Home Improvement", "Fitness Clubs", "Live Entertainment"
]

st.title("Best Credit Card for Rewards")
st.caption(f"Data refreshed: {data_fetched_at.strftime('%B %d, %Y at %I:%M %p')}")

if scrape_error:
    st.warning(f"Could not auto-fetch rotating categories from Doctor of Credit — showing manually entered data. ({scrape_error})")
elif data_source == "local":
    st.warning("Could not reach online data sources — using local backup data.")

# Mobile Detection
user_agent = st.query_params.get("user-agent", [""])[0].lower()
is_mobile = any(device in user_agent for device in ["iphone", "android", "ipad", "mobile"])

# Category Selection
categories = sorted(df["Category"].unique(), key=lambda x: x.lower())
selected_category = None

if is_mobile:
    for cat in categories:
        if st.button(cat.title(), key=f"btn_{cat}"):
            selected_category = cat
else:
    cols = st.columns(3)
    for i, cat in enumerate(categories):
        if cols[i % 3].button(cat.title(), key=f"btn_{cat}"):
            selected_category = cat

if selected_category:
    st.subheader(f"Best card(s) for {selected_category}:")
    cat_df = df[df["Category"] == selected_category].sort_values(by="Adjusted Rewards", ascending=False)

    unique_rewards = sorted(cat_df['Adjusted Rewards'].unique(), reverse=True)
    for i, label in enumerate(["Best Option(s)", "Next Best Option(s)"]):
        if len(unique_rewards) > i:
            st.write(f"**{label}:**")
            for _, row in cat_df[cat_df['Adjusted Rewards'] == unique_rewards[i]].iterrows():
                st.write(f"**Card:** {row['Credit Card']}")
                boost = 1.0
                if row['Transferable']:
                    issuer = get_issuer(row['Credit Card'])
                    if ENABLE_BOOSTS.get(issuer, False):
                        boost = VALUATIONS.get(issuer, 1.0)

                if boost > 1.0:
                    st.write(f"**Rewards:** {row['Adjusted Rewards']:.2f}% ({row['Rewards']}% base x {boost}x boost)")
                else:
                    st.write(f"**Rewards:** {row['Rewards']}% {row['Type']}")
                st.write("---")

    with st.expander("All cards for this category"):
        display_df = cat_df[['Credit Card', 'Rewards', 'Adjusted Rewards', 'Type']].copy()
        display_df.columns = ['Card', 'Base %', 'Adjusted %', 'Type']
        st.dataframe(display_df.reset_index(drop=True), use_container_width=True)

# Citi Section
st.subheader("Citi Custom Cash Analysis")
everything_max = df[df["Category"] == "Everything"]["Adjusted Rewards"].max()
for cat in sorted(citi_categories):
    norm_cat = category_aliases.get(cat, cat)
    comp_df = df[df["Category"].map(lambda x: category_aliases.get(x, x)) == norm_cat]
    best_other = comp_df["Adjusted Rewards"].max() if not comp_df.empty else everything_max
    st.write(f"{cat} (Next best: {best_other:.2f}%)")
