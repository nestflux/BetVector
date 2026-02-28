"""
BetVector — Model Health Page (E9-05 / E10)
=============================================
Displays calibration plots, Brier score trends, CLV tracking,
and model comparison metrics.

Full implementation in later epics.

Master Plan refs: MP §3 Flow 4, MP §8 Design System
"""

import streamlit as st


st.markdown(
    '<div class="bv-page-title">Model Health</div>',
    unsafe_allow_html=True,
)
st.markdown(
    '<p class="text-muted">Calibration, accuracy, and model performance metrics</p>',
    unsafe_allow_html=True,
)
st.divider()

# Placeholder — full implementation in later epics
st.markdown(
    '<div class="bv-empty-state">'
    "Model health metrics will appear here after enough predictions have been resolved. "
    "Run the pipeline and check back after a few matchdays."
    "</div>",
    unsafe_allow_html=True,
)
