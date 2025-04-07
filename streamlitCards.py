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

# Try to detect mobile based on user agent
user_agent = st.experimental_get_query_params().get("user-agent", [""])[0].lower()
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
    category_df = df[df["Category"] == selected_category]
    max_rewards = category_df["Rewards"].max()
    best_cards = category_df[category_df["Rewards"] == max_rewards]

    for _, row in best_cards.iterrows():
        st.write(f"**Card:** {row['Credit Card']}")
        st.write(f"**Rewards:** {row['Rewards']} {row['Type']}")
        st.write("---")

# Citi Custom Cash Recommendation Section
st.subheader("📣 Citi Custom Cash Optimal Categories")
st.write("Each month, Citi Custom Cash gives 5% back on your top spending category from a set list. Here’s where it currently offers the best value:")

# Remap all categories in df to canonical forms
normalized_df = df.copy()
normalized_df["Normalized"] = normalized_df["Category"].map(category_aliases).fillna(df["Category"])

citi_recommendations = []
for cat in citi_categories:
    competing_rewards = normalized_df[normalized_df["Normalized"] == cat]["Rewards"]
    best_other = competing_rewards.max() if not competing_rewards.empty else 0
    if best_other < 5:
        citi_recommendations.append(cat)

if citi_recommendations:
    for cat in sorted(citi_recommendations):
        st.write(f"✅ {cat} (No other card beats 5%)")
else:
    st.write("All Citi Custom Cash categories currently have better or equal offers from other cards.")