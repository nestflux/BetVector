"""
BetVector — Settings Page
===========================
User preferences: staking method, edge threshold, notification settings,
and password management.

Full implementation in later epics.

Master Plan refs: MP §3 Flow 4, MP §8 Design System
"""

import streamlit as st


st.markdown(
    '<div class="bv-page-title">Settings</div>',
    unsafe_allow_html=True,
)
st.markdown(
    '<p class="text-muted">Configure staking, thresholds, and notifications</p>',
    unsafe_allow_html=True,
)
st.divider()

# Placeholder — full implementation in later epics
st.markdown(
    '<div class="bv-empty-state">'
    "Settings and preferences will be configurable here."
    "</div>",
    unsafe_allow_html=True,
)
