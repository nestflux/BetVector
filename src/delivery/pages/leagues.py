"""
BetVector — League Explorer Page (E9-04)
=========================================
Browse league standings, recent results, and upcoming fixtures.

Full implementation in E9-04.

Master Plan refs: MP §3 Flow 4 (Dashboard Exploration), MP §8 Design System
"""

import streamlit as st


st.markdown(
    '<div class="bv-page-title">League Explorer</div>',
    unsafe_allow_html=True,
)
st.markdown(
    '<p class="text-muted">Standings, results, and upcoming fixtures</p>',
    unsafe_allow_html=True,
)
st.divider()

# Placeholder — full implementation in E9-04
st.markdown(
    '<div class="bv-empty-state">'
    "Select a league to explore standings, recent results, and upcoming fixtures."
    "</div>",
    unsafe_allow_html=True,
)
