"""
BetVector — Today's Picks Page (E9-02)
=======================================
Displays value bets for today's matches, sorted by edge.

This is the primary daily interface — the answer to "what should I bet
on today?"  Full implementation in E9-02.

Master Plan refs: MP §3 Flow 1 (Morning Picks Review), MP §8 Design System
"""

import streamlit as st


st.markdown(
    '<div class="bv-page-title">Today\'s Picks</div>',
    unsafe_allow_html=True,
)
st.markdown(
    '<p class="text-muted">Value bets for today\'s matches, sorted by edge</p>',
    unsafe_allow_html=True,
)
st.divider()

# Placeholder — full implementation in E9-02
st.markdown(
    '<div class="bv-empty-state">'
    "No value bets right now. Your bankroll thanks you for your patience."
    "</div>",
    unsafe_allow_html=True,
)
