"""
BetVector — Performance Tracker Page (E9-03)
=============================================
Shows betting results, P&L charts, ROI, and win rates.

Full implementation in E9-03.

Master Plan refs: MP §3 Flow 2 (Evening Results Review), MP §8 Design System
"""

import streamlit as st


st.markdown(
    '<div class="bv-page-title">Performance Tracker</div>',
    unsafe_allow_html=True,
)
st.markdown(
    '<p class="text-muted">Betting results, P&L, and ROI analysis</p>',
    unsafe_allow_html=True,
)
st.divider()

# Placeholder metrics — full implementation in E9-03
col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("Total P&L", "£0.00", delta="0.00%")
with col2:
    st.metric("ROI", "0.00%")
with col3:
    st.metric("Total Bets", "0")
with col4:
    st.metric("Win Rate", "0.0%")

st.markdown(
    '<div class="bv-empty-state">'
    "No betting data yet. Run the morning pipeline to generate picks, "
    "then check back after matches are resolved."
    "</div>",
    unsafe_allow_html=True,
)
