#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
import streamlit.components.v1 as components
from datetime import datetime
import requests
from io import StringIO

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

# Empirical Valuations (CPP / 100) - March 2026
VALUATIONS = {
    "Chase": 2.0,       
    "Wells Fargo": 1.6, 
    "Citi": 1.8,        
    "Capital One": 1.85,
    "Amex": 2.0,        
    "Default": 1.0      
}

def get_issuer(card_name):
    """Identifies the issuer based on the card name."""
    card_name = card_name.lower()
    if "chase" in card_name: return "Chase"
    if "wells fargo" in card_name: return "Wells Fargo"
    if "citi" in card_name: return "Citi"
    if "capital one" in card_name: return "Capital One"
    if "discover" in card_name: return "Discover"
    if "amex" in card_name or "american express" in card_name: return "Amex"
    return "Default"

@st.cache_data(ttl=3600)
def fetch_data():
    """Fetches Fixed and Rotating cards from Google Sheets and handles duplicates."""
    try:
        def get_sheet_url(sheet_name):
            return f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet={sheet_name}"

        fixed_resp = requests.get(get_sheet_url("Fixed"), timeout=5)
        rotating_resp = requests.get(get_sheet_url("Rotating"), timeout=5)
        
        fixed_df = pd.read_csv(StringIO(fixed_resp.text)) if fixed_resp.status_code == 200 else pd.DataFrame()
        rotating_df = pd.read_csv(StringIO(rotating_resp.text)) if rotating_resp.status_code == 200 else pd.DataFrame()

        now = datetime.now()
        if not rotating_df.empty and 'Start_Month' in rotating_df.columns:
            rotating_df = rotating_df[
                (rotating_df['Start_Month'] <= now.month) & 
                (rotating_df['End_Month'] >= now.month)
            ]
            rotating_df = rotating_df.rename(columns={'Card': 'Credit Card'})

        combined = pd.concat([fixed_df, rotating_df], ignore_index=True)
        combined = combined.drop_duplicates(subset=['Credit Card', 'Category'], keep='last')
        
        return combined[['Credit Card', 'Category', 'Rewards', 'Type', 'Transferable']]
    except Exception as e:
        st.error(f"Error fetching data: {e}.")
        return pd.read_csv('CreditCards.csv')

# Load and Process Data
df = fetch_data()

def calculate_adjusted_rewards(row):
    """Applies empirical point valuations ONLY if user has the premium card."""
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
st.write(f"Current Date: {datetime.now().strftime('%B %d, %Y')}")

# Automatic Mobile Detection Logic (Simplified)
user_agent = st.query_params.get("user-agent", [""])[0].lower()
is_mobile = any(device in user_agent for device in ["iphone", "android", "ipad", "mobile"])

# Selection
categories = sorted(df["Category"].unique(), key=lambda x: x.lower())
selected_category = None

# If on mobile, show the list. If on desktop, show the grid.
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

# Citi Section
st.subheader("Citi Custom Cash Analysis")
everything_max = df[df["Category"] == "Everything"]["Adjusted Rewards"].max()
for cat in sorted(citi_categories):
    norm_cat = category_aliases.get(cat, cat)
    comp_df = df[df["Category"].map(lambda x: category_aliases.get(x, x)) == norm_cat]
    best_other = comp_df["Adjusted Rewards"].max() if not comp_df.empty else everything_max
    st.write(f"{cat} (Next best: {best_other:.2f}%)")
