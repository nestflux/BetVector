"""Shared pytest fixtures for the BetVector suite."""
import pytest


@pytest.fixture(autouse=True)
def _clear_streamlit_caches():
    """Reset Streamlit's cross-session caches before every test.

    Dashboard data loaders are decorated with ``@st.cache_data``, which is a
    GLOBAL cache keyed on (function, args) that persists across calls — including
    across tests in the same process.  Without this reset, a test that calls a
    cached loader with the same args as an earlier test (e.g.
    ``load_fixtures_with_odds(today, today)``) would receive the earlier test's
    cached result instead of querying its own freshly-seeded in-memory DB,
    producing spurious failures.  Clearing before each test restores isolation.
    Safe in bare mode (no Streamlit ScriptRunContext).
    """
    try:
        import streamlit as st
        st.cache_data.clear()
        st.cache_resource.clear()
    except Exception:
        # Streamlit not importable or cache API unavailable — nothing to clear.
        pass
    yield
