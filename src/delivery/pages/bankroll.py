"""
BetVector — Bankroll Manager Page
===================================
Current bankroll, staking method selector, bet history with filters,
and safety alert status.

Full implementation in later epics.

Master Plan refs: MP §3 Flow 4, MP §8 Design System
"""

import streamlit as st


st.markdown(
    '<div class="bv-page-title">Bankroll Manager</div>',
    unsafe_allow_html=True,
)
st.markdown(
    '<p class="text-muted">Bankroll tracking, staking settings, and safety limits</p>',
    unsafe_allow_html=True,
)
st.divider()

# Placeholder — full implementation in later epics
col1, col2, col3 = st.columns(3)
with col1:
    st.metric("Current Bankroll", "£1,000.00")
with col2:
    st.metric("Staking Method", "Flat 2%")
with col3:
    st.metric("Safety Status", "All OK")

st.markdown(
    '<div class="bv-empty-state">'
    "Bankroll management controls and bet history will be available here."
    "</div>",
    unsafe_allow_html=True,
)
