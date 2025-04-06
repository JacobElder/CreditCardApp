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

# def load_data():
#     data = {
#         "Credit Card": [
#             "Bank of America Customized Cash Rewards", "US Bank Cash Plus", "US Bank Cash Plus", "US Bank Altitude Go",
#             "Discover It", "Discover It", "Discover It", "Chase Freedom Flex", "Chase Freedom Flex", "Capital One Savor",
#             "Capital One Savor", "Capital One Savor", "Capital One Savor", "Capital One Quicksilver", "Wells Fargo Active Cash",
#             "Wells Fargo Autograph", "Wells Fargo Autograph", "Wells Fargo Autograph", "Wells Fargo Autograph", "Wells Fargo Autograph", "Wells Fargo Autograph",
#             "US Bank Altitude Connect"
#         ],
#         "Category": [
#             "Online Shopping", "Department Stores", "Clothing Stores", "Dining", "Dining", "Home Improvement", "Streaming",
#             "Grocery Stores", "Gym", "Dining", "Entertainment", "Streaming", "Grocery Stores", "Everything", "Everything",
#             "Dining", "Travel", "Gas", "Transit", "Streaming", "Phone", "Travel"
#         ],
#         "Rewards": [
#             3, 5, 5, 4, 5, 5, 5, 5, 5, 3, 3, 3, 3, 1.5, 2, 3, 3, 3, 3, 3, 3, 4
#         ],
#         "Type": [
#             "Cash Back", "Cash Back", "Cash Back", "Points", "Cash Back", "Cash Back", "Cash Back", "Points", "Points", "Cash Back",
#             "Cash Back", "Cash Back", "Cash Back", "Cash Back", "Cash Back", "Points", "Points", "Points", "Points", "Points", "Points", "Points"
#         ]
#     }
#     return pd.DataFrame(data)

# # Load data
# df = load_data()

df = pd.read_csv('CreditCards.csv')

# Inject JavaScript to detect mobile screen width
components.html("""
<script>
    const isMobile = window.innerWidth < 768;
    window.parent.postMessage({ type: 'MOBILE_STATUS', isMobile: isMobile }, '*');
</script>
""", height=0)

# Read the query param set by JS injection
def detect_mobile():
    query_params = st.experimental_get_query_params()
    return query_params.get("mobile", ["false"])[0] == "true"

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

# Streamlit UI
st.title("Best Credit Card for Rewards")
st.write("Select a category to see the best card to use:")

# Get unique categories in ascending alphabetical order
categories = sorted(df["Category"].unique())

# Automatically detect mobile, fallback to checkbox if JS hasn't run yet
is_mobile = detect_mobile()

# Display layout mode
use_list_format = is_mobile or st.checkbox("Use List Format (Mobile-Friendly)", value=False)

# Initialize selected category
selected_category = None

# Render buttons based on layout choice
if use_list_format:
    for category in categories:
        if st.button(category):
            selected_category = category
else:
    cols = st.columns(3)  # Create 3 columns for button layout
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