"""DF-02 — World Cup as the login landing page during the tournament window.

Verifies dashboard.get_pages() flips the default landing page (and the top sidebar
slot) to World Cup while the tournament window is active, and back to Fixtures
outside it. Streamlit is stubbed so the module imports without a live runtime; a
FakePage records the kwargs we assert on.
"""

import sys
from unittest.mock import MagicMock

import pytest


class _FakePage:
    """Stand-in for st.Page that records what it was constructed with."""

    def __init__(self, page, title=None, icon=None, default=False):
        self.page = page
        self.title = title
        self.icon = icon
        self.default = default


@pytest.fixture
def dash(monkeypatch):
    # Stub streamlit BEFORE importing the dashboard — it calls st.set_page_config
    # at module load. MagicMock absorbs every other st.* call; st.Page is the one
    # we need to inspect, so we pin it to a recording fake.
    st_stub = MagicMock()
    st_stub.Page = _FakePage
    monkeypatch.setitem(sys.modules, "streamlit", st_stub)
    sys.modules.pop("src.delivery.dashboard", None)
    import src.delivery.dashboard as dashboard
    # Viewer role keeps the Admin page out of the list (simpler assertions).
    monkeypatch.setattr(dashboard, "get_session_user_role", lambda: "viewer")
    yield dashboard
    sys.modules.pop("src.delivery.dashboard", None)


def _sole_default(pages):
    defaults = [p.title for p in pages if p.default]
    assert len(defaults) == 1, f"exactly one page must be default, got {defaults}"
    return defaults[0]


def test_world_cup_is_landing_during_window(dash, monkeypatch):
    monkeypatch.setattr("src.world_cup.timeutil.wc_window_active", lambda: True)
    pages = dash.get_pages()
    assert pages[0].title == "World Cup"          # top of the sidebar
    assert _sole_default(pages) == "World Cup"    # the default landing page


def test_fixtures_is_landing_outside_window(dash, monkeypatch):
    monkeypatch.setattr("src.world_cup.timeutil.wc_window_active", lambda: False)
    pages = dash.get_pages()
    assert pages[0].title == "Fixtures"           # unchanged ordering
    assert _sole_default(pages) == "Fixtures"


def test_all_pages_present_in_both_modes(dash, monkeypatch):
    expected = {"Fixtures", "Today's Picks", "World Cup", "Model Health",
                "League Explorer", "Match Deep Dive"}
    for active in (True, False):
        monkeypatch.setattr("src.world_cup.timeutil.wc_window_active", lambda a=active: a)
        titles = {p.title for p in dash.get_pages()}
        assert expected <= titles, f"missing pages when active={active}: {expected - titles}"


def test_landing_check_failure_falls_back_to_fixtures(dash, monkeypatch):
    # The landing override is pure UX sugar — if the window check raises, the
    # dashboard must still load on Fixtures rather than crash (cloud hardening).
    def boom():
        raise RuntimeError("simulated World Cup module hiccup")

    monkeypatch.setattr("src.world_cup.timeutil.wc_window_active", boom)
    pages = dash.get_pages()
    assert pages[0].title == "Fixtures"
    assert _sole_default(pages) == "Fixtures"
