"""
E35 v2 — Bet Tracker UX v2 Integration Tests
=============================================
Automated pytest suite covering new backend logic introduced in
E35-04 (fixture browser) and E35-05 (slip builder panel).

Scenarios:
  1.  load_fixtures_with_odds() returns fixtures with correct odds structure
  2.  load_fixtures_with_odds() returns None for markets with no odds in DB
  3.  log_multiple_bets() creates one BetLog row per valid selection
  4.  log_multiple_bets() skips duplicate selections and still logs others
  5.  log_multiple_bets() returns empty list when all selections are duplicates
  6.  log_multiple_bets() skips entries with None / sub-minimum odds
  7.  Per-row odds saved correctly via log_manual_bet (placement ≠ detection guard)
  8.  Est. return formula: (odds - 1) * stake — arithmetic correctness
  9.  Cross-user guard: user A's bets are not visible to user B
  10. load_fixtures_with_odds() returns empty list when window has no matches

Run with: pytest tests/test_e35_v2_integration.py -v

Architecture note:
  my_bets.py contains module-level Streamlit rendering code.  We mock the
  streamlit module BEFORE any src import to prevent crashes.  Tests use an
  in-memory SQLite engine patched into src.database.db via monkeypatch.
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock


# ============================================================================
# Install streamlit mock BEFORE any src import that touches st.*
# ============================================================================

def _make_st_mock() -> MagicMock:
    """Return a MagicMock safe enough for Streamlit page module imports."""
    st = MagicMock()
    # Real dict so session_state.get("key", default) works correctly.
    # user_id=99999 is intentionally a non-existent sentinel so page modules
    # that call load_current_user(get_session_user_id()) receive None and skip
    # their UI rendering sections — preventing widget mock bleed-through into
    # other test modules that import settings.py / admin.py for the first time
    # during test execution.
    st.session_state = {"user_id": 99999}
    # st.columns() must return an iterable of the correct length.
    st.columns.side_effect = lambda spec: [
        MagicMock()
        for _ in range(spec if isinstance(spec, int) else len(spec))
    ]
    st.tabs.return_value = [MagicMock() for _ in range(4)]
    # radio.side_effect: return the first option in the options list so this mock
    # works correctly for ANY st.radio() call across all page modules (my_bets,
    # settings, fixtures, etc.) without injecting a value that is invalid for
    # other callers (e.g. settings.py staking-method radio, fixtures.py, etc.).
    def _radio_side_effect(*args, **kwargs):
        opts = kwargs.get("options") or (args[1] if len(args) > 1 else None)
        return opts[0] if opts else None
    st.radio.side_effect = _radio_side_effect
    st.info.return_value = None
    st.divider.return_value = None
    return st


_st_mock = _make_st_mock()
# Use conditional installation so we do not overwrite a mock already placed by
# a sibling test file (e.g. test_e35_integration.py).  If streamlit is already
# mocked, the existing mock is reused; my_bets.py's _DATE_WINDOWS.get() fallback
# handles any return value that is not a recognised window label.
if "streamlit" not in sys.modules:
    sys.modules["streamlit"] = _st_mock

# ============================================================================
# Now safe to import src modules
# ============================================================================

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.db import Base
from src.database.models import BetLog, League, Match, Odds, Team
from src.delivery.views.my_bets import (
    check_duplicate_bet,
    load_fixtures_with_odds,
    load_user_bets,
    log_manual_bet,
    log_multiple_bets,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture(autouse=True)
def use_test_db(monkeypatch):
    """Replace the real DB engine with an in-memory SQLite engine.

    Creates all ORM tables fresh for each test, then tears down.
    Patches src.database.db._engine and _SessionFactory so that every
    get_session() call inside my_bets.py hits the in-memory DB.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine)

    monkeypatch.setattr("src.database.db._engine", engine)
    monkeypatch.setattr("src.database.db._SessionFactory", TestSession)
    yield engine


@pytest.fixture()
def db_fixture(use_test_db):
    """Populate the in-memory DB with one league, two teams, and one match.

    The match is scheduled for today so load_fixtures_with_odds() picks it up.
    Returns a dict of IDs for use in tests.
    """
    engine = use_test_db
    Session = sessionmaker(bind=engine)
    today = date.today().isoformat()
    now   = datetime.utcnow().isoformat()

    with Session() as s:
        league = League(
            id=1, name="Test Premier League", short_name="TPL",
            country="Test", is_active=1, created_at=now,
        )
        home_team = Team(id=1, name="Home FC", league_id=1)
        away_team = Team(id=2, name="Away United", league_id=1)
        s.add_all([league, home_team, away_team])
        s.flush()

        match = Match(
            id=1,
            league_id=1,
            home_team_id=1,
            away_team_id=2,
            date=today,
            kickoff_time="15:00",
            season="2024-25",
            status="scheduled",
        )
        s.add(match)
        s.flush()

        # Add 1X2 + OU25 odds — intentionally OMIT BTTS to test None return
        odds_rows = [
            Odds(match_id=1, bookmaker="Pinnacle", market_type="1X2",
                 selection="home",  odds_decimal=2.10, implied_prob=0.476,
                 is_opening=0, captured_at=now, source="test"),
            Odds(match_id=1, bookmaker="Pinnacle", market_type="1X2",
                 selection="draw",  odds_decimal=3.40, implied_prob=0.294,
                 is_opening=0, captured_at=now, source="test"),
            Odds(match_id=1, bookmaker="Pinnacle", market_type="1X2",
                 selection="away",  odds_decimal=3.60, implied_prob=0.278,
                 is_opening=0, captured_at=now, source="test"),
            Odds(match_id=1, bookmaker="Pinnacle", market_type="OU25",
                 selection="over",  odds_decimal=1.85, implied_prob=0.541,
                 is_opening=0, captured_at=now, source="test"),
            Odds(match_id=1, bookmaker="Pinnacle", market_type="OU25",
                 selection="under", odds_decimal=1.95, implied_prob=0.513,
                 is_opening=0, captured_at=now, source="test"),
            # BTTS intentionally absent — tests None return path
        ]
        s.add_all(odds_rows)
        s.commit()

    return {
        "match_id": 1, "date": today,
        "league_id": 1, "home_team": "Home FC", "away_team": "Away United",
    }


def _make_selection(match_id: int, today: str, **kwargs) -> dict:
    """Helper: build a selection dict as the slip builder would pass it."""
    base = {
        "match_id":    match_id,
        "date":        today,
        "home_team":   "Home FC",
        "away_team":   "Away United",
        "league":      "TPL",
        "market_type": "1X2",
        "selection":   "Home",
        "odds":        2.10,
        "stake":       20.0,
        "bookmaker":   "Pinnacle",
        "slip_key":    f"{match_id}__1X2__home",
    }
    base.update(kwargs)
    return base


# ============================================================================
# Test 1 — load_fixtures_with_odds returns correct structure
# ============================================================================

def test_load_fixtures_with_odds_structure(db_fixture):
    """Fixture browser query returns correctly shaped dicts with odds nested."""
    today = db_fixture["date"]
    result = load_fixtures_with_odds(today, today)

    assert len(result) == 1, "Should return the one scheduled fixture"
    fx = result[0]

    assert fx["id"] == db_fixture["match_id"]
    assert fx["home_team"] == "Home FC"
    assert fx["away_team"] == "Away United"
    assert fx["league_short"] == "TPL"
    assert "odds" in fx

    odds = fx["odds"]
    # All 7 market keys must be present
    expected_keys = [
        ("1X2", "home"), ("1X2", "draw"), ("1X2", "away"),
        ("OU25", "over"), ("OU25", "under"),
        ("BTTS", "yes"), ("BTTS", "no"),
    ]
    for key in expected_keys:
        assert key in odds, f"Missing key {key} in odds dict"


# ============================================================================
# Test 2 — Markets with no odds row return None
# ============================================================================

def test_load_fixtures_with_odds_missing_market_returns_none(db_fixture):
    """BTTS odds were not inserted — those keys must return None, not crash."""
    today  = db_fixture["date"]
    result = load_fixtures_with_odds(today, today)
    odds   = result[0]["odds"]

    # 1X2 and OU25 should have values
    assert odds[("1X2",  "home")] == pytest.approx(2.10)
    assert odds[("OU25", "over")] == pytest.approx(1.85)

    # BTTS was not inserted — must return None
    assert odds[("BTTS", "yes")] is None
    assert odds[("BTTS", "no")]  is None


# ============================================================================
# Test 3 — log_multiple_bets creates one BetLog per valid selection
# ============================================================================

def test_log_multiple_bets_creates_rows(db_fixture):
    """log_multiple_bets writes exactly one BetLog per valid selection."""
    today = db_fixture["date"]
    user_id = 42

    selections = [
        _make_selection(9001, today, market_type="1X2",      selection="Home",  odds=2.10, stake=20.0),
        _make_selection(9002, today, market_type="Over 2.5", selection="Over",  odds=1.85, stake=15.0),
    ]

    logged, skipped = log_multiple_bets(user_id, selections)

    assert len(logged)  == 2, "Both selections should be logged"
    assert len(skipped) == 0, "No selections should be skipped"

    # Verify DB rows
    bets = load_user_bets(user_id)
    assert len(bets) == 2
    market_types = {b["market_type"] for b in bets}
    assert "1X2"     in market_types
    assert "Over 2.5" in market_types


# ============================================================================
# Test 4 — Duplicate detection: skip duplicate, log the rest
# ============================================================================

def test_log_multiple_bets_skips_duplicate_logs_others(db_fixture):
    """Duplicate selection is skipped; the non-duplicate selection logs."""
    today   = db_fixture["date"]
    user_id = 43

    # Log the first selection once
    sel_home = _make_selection(9003, today, market_type="1X2", selection="Home",
                               odds=2.10, stake=20.0)
    sel_draw = _make_selection(9003, today, market_type="1X2", selection="Draw",
                               odds=3.40, stake=15.0,
                               slip_key="9003__1X2__draw")

    logged1, _ = log_multiple_bets(user_id, [sel_home])
    assert len(logged1) == 1

    # Try logging both again — Home is now a duplicate
    logged2, skipped2 = log_multiple_bets(user_id, [sel_home, sel_draw])

    assert len(logged2)  == 1, "Only Draw should log (Home is duplicate)"
    assert len(skipped2) == 1, "Home should be in skipped"
    assert "already logged" in skipped2[0]


# ============================================================================
# Test 5 — All selections are duplicates → returns empty logged list
# ============================================================================

def test_log_multiple_bets_all_duplicates(db_fixture):
    """When every selection is a duplicate, logged_ids is empty."""
    today   = db_fixture["date"]
    user_id = 44

    sel = _make_selection(9004, today, market_type="1X2", selection="Away",
                          odds=3.60, stake=10.0)
    log_multiple_bets(user_id, [sel])   # First log

    logged, skipped = log_multiple_bets(user_id, [sel])   # Second — duplicate

    assert logged  == [], "No new rows should be created"
    assert len(skipped) == 1
    assert "already logged" in skipped[0]


# ============================================================================
# Test 6 — None / sub-minimum odds are skipped with reason
# ============================================================================

def test_log_multiple_bets_skips_invalid_odds(db_fixture):
    """Selections with None odds or odds < 1.01 are skipped without crashing."""
    today   = db_fixture["date"]
    user_id = 45

    sel_none = _make_selection(9005, today, odds=None)
    sel_low  = _make_selection(9006, today, odds=1.00,
                               slip_key="9006__1X2__home")
    sel_good = _make_selection(9007, today, odds=2.50,
                               slip_key="9007__1X2__home")

    logged, skipped = log_multiple_bets(user_id, [sel_none, sel_low, sel_good])

    assert len(logged)  == 1, "Only the valid odds selection should log"
    assert len(skipped) == 2, "None and sub-min odds should be skipped"
    for reason in skipped:
        assert "invalid odds" in reason


# ============================================================================
# Test 7 — Per-row odds saved correctly (placement == detection for manual bets)
# ============================================================================

def test_log_manual_bet_stores_odds_correctly(db_fixture):
    """log_manual_bet writes odds_at_placement == odds_at_detection for
    manual bets (no model involved).  The implied_prob is 1/odds."""
    today   = db_fixture["date"]
    user_id = 46

    match = {
        "id": 9010, "date": today,
        "home_team": "Alpha FC", "away_team": "Beta United",
        "league_short": "TL",
    }
    bet_id = log_manual_bet(
        user_id=user_id, match=match,
        market_type="1X2", selection="Home",
        bookmaker="Bet365", odds=2.40, stake=25.0,
    )

    assert bet_id is not None
    bets = load_user_bets(user_id)
    assert len(bets) == 1

    b = bets[0]
    assert b["odds_at_detection"]  == pytest.approx(2.40)
    assert b["odds_at_placement"]  == pytest.approx(2.40)
    # odds_at_placement == odds_at_detection for manual bets — no model price
    assert b["odds"] == pytest.approx(2.40)


# ============================================================================
# Test 8 — Est. return formula arithmetic
# ============================================================================

def test_est_return_formula():
    """Est. return = (odds - 1) * stake — pure arithmetic, no DB needed."""
    cases = [
        (2.10, 20.0,  22.00),   # (2.10 - 1) * 20 = 22.00
        (1.85, 15.0,  12.75),   # (1.85 - 1) * 15 = 12.75
        (3.40, 10.0,  24.00),   # (3.40 - 1) * 10 = 24.00
        (1.01,  5.0,   0.05),   # edge case — near minimum odds
    ]
    for odds, stake, expected in cases:
        result = round((odds - 1) * stake, 2)
        assert result == pytest.approx(expected, abs=0.01), (
            f"Expected {expected} for odds={odds} stake={stake}, got {result}"
        )


# ============================================================================
# Test 9 — Cross-user isolation: user A's bets invisible to user B
# ============================================================================

def test_cross_user_isolation(db_fixture):
    """load_user_bets() returns only the requesting user's bets."""
    today    = db_fixture["date"]
    user_a   = 51
    user_b   = 52

    sel_a = _make_selection(9020, today, market_type="1X2", selection="Home",
                            odds=2.10, stake=20.0)
    sel_b = _make_selection(9021, today, market_type="1X2", selection="Away",
                            odds=3.60, stake=10.0,
                            slip_key="9021__1X2__away")

    log_multiple_bets(user_a, [sel_a])
    log_multiple_bets(user_b, [sel_b])

    bets_a = load_user_bets(user_a)
    bets_b = load_user_bets(user_b)

    assert len(bets_a) == 1, "User A should see exactly 1 bet"
    assert len(bets_b) == 1, "User B should see exactly 1 bet"

    assert bets_a[0]["selection"] == "Home",  "User A should see Home selection"
    assert bets_b[0]["selection"] == "Away",  "User B should see Away selection"

    # Verify no cross-contamination
    assert all(b["selection"] != "Away" for b in bets_a)
    assert all(b["selection"] != "Home" for b in bets_b)


# ============================================================================
# Test 10 — Empty fixture window returns empty list, no crash
# ============================================================================

def test_load_fixtures_with_odds_empty_window(db_fixture):
    """A date window with no scheduled matches returns [] without raising."""
    far_future = (date.today() + timedelta(days=365)).isoformat()
    far_future2 = (date.today() + timedelta(days=366)).isoformat()

    result = load_fixtures_with_odds(far_future, far_future2)
    assert result == [], "No fixtures in far future → empty list expected"
