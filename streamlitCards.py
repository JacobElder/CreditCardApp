#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sun Mar 16 16:25:57 2025

@author: jacobelder
"""
import streamlit as st
import pandas as pd
import streamlit.components.v1 as components
import time

df = pd.read_csv('CreditCards.csv')

# Inject JavaScript to detect mobile screen width
components.html("""
<script>
    const isMobile = window.innerWidth < 900;
    window.parent.postMessage({ type: 'MOBILE_STATUS', isMobile: isMobile }, '*');
</script>
""", height=0)

# Read the query param set by JS injection
def detect_mobile():
    #query_params = st.experimental_get_query_params()
    return st.query_params.get("mobile", ["false"])[0] == "true"

# Add a listener that updates the query param when JS posts message
components.html("""
<script>
window.addEventListener("message", (event) => {
    if (event.data.type === "MOBILE_STATUS") {
        const isMobile = event.data.isMobile;
        const newUrl = new URL(window.location);
        newUrl.searchParams.set("mobile", isMobile);
        window.history.replaceState(null, "", newUrl);
    }
});
</script>
""", height=0)

# Normalize category labels
category_aliases = {
    "Dining": "Restaurants",
    "Restaurants": "Restaurants",
    "Gas": "Gas",
    "Grocery Stores": "Grocery Stores",
    "Travel": "Travel",
    "Transit": "Transit",
    "Streaming": "Streaming",
    "Drugstores": "Drugstores",
    "Home Improvement": "Home Improvement",
    "Home Improvement Stores": "Home Improvement",
    "Gym": "Fitness Clubs",
    "Entertainment": "Live Entertainment"
}

# Citi Custom Cash eligible categories
citi_categories = [
    "Restaurants", "Gas", "Grocery Stores", "Travel", "Transit",
    "Streaming", "Drugstores", "Home Improvement", "Fitness Clubs", "Live Entertainment"
]

# Streamlit UI
st.title("Best Credit Card for Rewards")
st.write("Select a category to see the best card to use:")

# Get unique categories in ascending alphabetical order
categories = sorted(df["Category"].unique())

# Detect mobile using user-agent workaround
user_agent = st.query_params.get("user-agent", [""])[0].lower()
is_mobile = any(device in user_agent for device in ["iphone", "android", "ipad", "mobile"])

# Use session state for layout toggle
if "use_list_format" not in st.session_state:
    st.session_state.use_list_format = is_mobile

# Try to detect mobile based on user agent
user_agent = st.query_params.get("user-agent", [""])[0].lower()
is_mobile = any(device in user_agent for device in ["iphone", "android", "ipad", "mobile"])
use_list_format = is_mobile or st.checkbox("Use List Format (Mobile-Friendly)", value=False)

# Initialize selected category
selected_category = None

# Render buttons based on layout choice
if use_list_format:
    for category in categories:
        if st.button(category):
            selected_category = category
else:
    cols = st.columns(3)
    for i, category in enumerate(categories):
        if cols[i % 3].button(category):
            selected_category = category

# Display the best card if a category is selected
if selected_category:
    st.subheader(f"Best card(s) for {selected_category}:")
    category_df = df[df["Category"] == selected_category].copy()
    
    # Define the boost for transferable points
    transferable_points_boost = 1.25 
    
    # Apply the boost to transferable points
    category_df['Adjusted Rewards'] = category_df.apply(
        lambda row: row['Rewards'] * transferable_points_boost if row['Transferable'] else row['Rewards'],
        axis=1
    )
    
    max_rewards = category_df["Adjusted Rewards"].max()
    best_cards = category_df[category_df["Adjusted Rewards"] == max_rewards]

    for _, row in best_cards.iterrows():
        st.write(f"**Card:** {row['Credit Card']}")
        if row['Transferable']:
            st.write(f"**Rewards:** {row['Adjusted Rewards']:.2f}% ({row['Rewards']} {row['Type']} with {transferable_points_boost}x boost)")
            st.write("_Points are transferable, increasing their value._")
        else:
            st.write(f"**Rewards:** {row['Rewards']} {row['Type']}")
        st.write("---")

# Citi Custom Cash Recommendation Section
st.subheader("Citi Custom Cash Eligible Categories")
st.write("Each month, Citi Custom Cash gives 5% back on your top spending category from the set list. Here are all the eligible categories and the next best offer for each:")


# Remap all categories in df to canonical forms
normalized_df = df.copy()
normalized_df["Normalized"] = normalized_df["Category"].map(category_aliases).fillna(df["Category"])

# Apply the boost to transferable points for Citi recommendations
transferable_points_boost = 1.25
normalized_df['Adjusted Rewards'] = normalized_df.apply(
    lambda row: row['Rewards'] * transferable_points_boost if row['Transferable'] else row['Rewards'],
    axis=1
)

citi_full_list = []

# Get the max reward from "Everything" category as fallback
everything_max = normalized_df[normalized_df["Category"] == "Everything"]["Adjusted Rewards"].max()

for cat in citi_categories:
    competing_df = normalized_df[normalized_df["Normalized"] == cat]
    best_other = competing_df["Adjusted Rewards"].max() if not competing_df.empty else everything_max
    citi_full_list.append((cat, best_other))

if citi_full_list:
    for cat, max_other in sorted(citi_full_list):
        st.write(f"{cat} (Next best: {max_other:.2f}%)")
else:
    st.write("Could not retrieve Citi Custom Cash categories.")


import re
from datetime import datetime

def update_csv(card_name, categories, rewards, card_type, is_transferable):
    try:
        with open('CreditCards.csv', 'r') as f:
            lines = f.readlines()
    except FileNotFoundError:
        st.error("Error: CreditCards.csv not found. Please make sure the file exists in the same directory as the script.")
        return

    with open('CreditCards.csv', 'w') as f:
        for line in lines:
            if card_name not in line:
                f.write(line)
        for cat in categories:
            f.write(f"{card_name},{cat},{rewards},{card_type},{is_transferable}\n")

def get_rotating_categories(card_name, search_query):
    try:
        results = google_web_search(query=search_query)
        # Find the categories in the search result text
        # This is a simplified parsing logic. It might need to be adjusted based on the search results format.
        # It assumes the categories are listed after "are:"
        match = re.search(r"are:\s*(.*)", results, re.IGNORECASE)
        if match:
            categories = [cat.strip() for cat in match.group(1).split(',')]
            # further clean up the categories
            categories = [cat.replace('and ', '').strip() for cat in categories]
            return categories
        else:
            st.warning(f"Could not find categories for {card_name} in the search results.")
            return None
    except Exception as e:
        st.error(f"Error fetching categories for {card_name}: {e}")
        return None

# Section for dynamically updating rotating categories
st.subheader("Update Rotating Categories")
st.write("Click the button to automatically update the quarterly categories for your rotating cards.")

if st.button("Update Categories Dynamically"):
    current_month = datetime.now().month
    current_year = datetime.now().year
    current_quarter = (current_month - 1) // 3 + 1

    # Update Discover It
    discover_query = f"discover it rotating categories Q{current_quarter} {current_year}"
    discover_categories = get_rotating_categories("Discover It", discover_query)
    if discover_categories:
        update_csv("Discover It", discover_categories, 5, "Cash Back", False)
        st.success("Discover It categories updated!")

    # Update Chase Freedom Flex
    cff_query = f"chase freedom flex rotating categories Q{current_quarter} {current_year}"
    cff_categories = get_rotating_categories("Chase Freedom Flex", cff_query)
    if cff_categories:
        update_csv("Chase Freedom Flex", cff_categories, 5, "Points", True)
        st.success("Chase Freedom Flex categories updated!")
    
    st.rerun()