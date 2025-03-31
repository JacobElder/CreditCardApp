#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sun Mar 16 16:25:57 2025

@author: jacobelder
"""
import streamlit as st
import pandas as pd

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

# Streamlit UI
st.title("Best Credit Card for Rewards")
st.write("Select a category to see the best card to use:")

# Get unique categories in ascending alphabetical order
categories = sorted(df["Category"].unique())

# Create buttons in multiple columns
cols = st.columns(3)  # Create 3 columns for button layout
selected_category = None

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
