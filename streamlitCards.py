#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sun Mar 16 16:25:57 2025

@author: jacobelder
"""
import streamlit as st
import pandas as pd

def load_data():
    data = {
        "Credit Card": [
            "Bank of America Customized Cash Rewards", "US Bank Cash Plus", "US Bank Cash Plus", "US Bank Altitude Go",
            "Discover It", "Discover It", "Discover It", "Chase Freedom Flex", "Chase Freedom Flex", "Capital One Savor",
            "Capital One Savor", "Capital One Savor", "Capital One Savor", "Capital One Quicksilver", "Wells Fargo Active Cash",
            "Wells Fargo Autograph", "Wells Fargo Autograph", "Wells Fargo Autograph", "Wells Fargo Autograph", "Wells Fargo Autograph", "Wells Fargo Autograph"
        ],
        "Category": [
            "Online Shopping", "Department Stores", "Clothing Stores", "Dining", "Dining", "Home Improvement", "Streaming",
            "Grocery Stores", "Gym", "Dining", "Entertainment", "Streaming", "Grocery Stores", "Everything", "Everything",
            "Dining", "Travel", "Gas", "Transit", "Streaming", "Phone"
        ],
        "Rewards": [
            3, 5, 5, 4, 5, 5, 5, 5, 5, 3, 3, 3, 3, 1.5, 2, 3, 3, 3, 3, 3, 3
        ],
        "Type": [
            "Cash Back", "Cash Back", "Cash Back", "Points", "Cash Back", "Cash Back", "Cash Back", "Points", "Points", "Cash Back",
            "Cash Back", "Cash Back", "Cash Back", "Cash Back", "Cash Back", "Points", "Points", "Points", "Points", "Points", "Points"
        ]
    }
    return pd.DataFrame(data)

# Load data
df = load_data()

# Streamlit UI
st.title("Best Credit Card for Rewards")
st.write("Select a category to see the best card to use:")

# Get unique categories
categories = df["Category"].unique()

# Create buttons for each category
selected_category = None
for category in categories:
    if st.button(category):
        selected_category = category

# Display the best card if a category is selected
if selected_category:
    st.subheader(f"Best card for {selected_category}:")
    category_df = df[df["Category"] == selected_category]
    best_card = category_df.loc[category_df["Rewards"].idxmax()]
    
    st.write(f"**Card:** {best_card['Credit Card']}")
    st.write(f"**Rewards:** {best_card['Rewards']} {best_card['Type']}")