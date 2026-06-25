"""RBAC — owner-only differentiation in the dashboard.

Source-level checks (the views run st.* at import, so we can't import them headless):
Data Health is owner-only in the nav + has an in-page guard; the global Settings
sections (League Management, Injury Flags) are wrapped in an owner check; and the
onboarding league step is owner-only (no global league write for testers).
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASH = (ROOT / "src" / "delivery" / "dashboard.py").read_text()
DH = (ROOT / "src" / "delivery" / "views" / "data_health.py").read_text()
SETTINGS = (ROOT / "src" / "delivery" / "views" / "settings.py").read_text()
ONB = (ROOT / "src" / "delivery" / "views" / "onboarding.py").read_text()

_OWNER_GUARD = 'if user_data["role"] == "owner":'


def test_data_health_registered_only_inside_owner_block():
    assert DASH.count('"views/data_health.py"') == 1
    owner_block = DASH.index('if get_session_user_role() == "owner":')
    assert DASH.index('"views/data_health.py"') > owner_block   # owner-only nav


def test_data_health_has_in_page_role_guard():
    assert 'get_session_user_role() != "owner"' in DH and "st.stop()" in DH


def _nearest_enclosing_guard(src: str, marker: str) -> str | None:
    """The first statement at <=4-space indent above the marker line (its enclosing
    block opener inside the page's top-level `else:`)."""
    lines = src.split("\n")
    idx = next(i for i, l in enumerate(lines) if marker in l)
    for j in range(idx - 1, -1, -1):
        l = lines[j]
        if not l.strip() or l.lstrip().startswith("#"):
            continue
        if len(l) - len(l.lstrip()) <= 4:
            return l.strip()
    return None


def test_settings_league_and_injury_sections_are_owner_gated():
    # was 1 owner guard (User Management); now 3 (+ League Management + Injury Flags)
    assert SETTINGS.count(_OWNER_GUARD) >= 3
    assert _nearest_enclosing_guard(SETTINGS, 'bv-section-header">League Management') \
        == _OWNER_GUARD
    assert _nearest_enclosing_guard(SETTINGS, 'bv-section-header">Injury Flags') \
        == _OWNER_GUARD


def test_settings_personal_sections_stay_open_to_all():
    # User Preferences + Notification Preferences must NOT be behind the owner guard
    assert _nearest_enclosing_guard(SETTINGS, 'bv-section-header">User Preferences') \
        != _OWNER_GUARD
    assert _nearest_enclosing_guard(SETTINGS, 'bv-section-header">Notification Preferences') \
        != _OWNER_GUARD


def test_onboarding_league_step_is_owner_only():
    # render_step_4 early-returns for non-owners (no editable, global-writing checkboxes)
    assert 'get_session_user_role() != "owner"' in ONB
    # the single global save is guarded by an owner check immediately above it
    assert ONB.count("save_league_selections(league_selections)") == 1
    save_idx = ONB.index("save_league_selections(league_selections)")
    assert 'if get_session_user_role() == "owner":' in ONB[save_idx - 300:save_idx]
