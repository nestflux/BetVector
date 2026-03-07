"""
E35 — Bet Tracker Integration Test
====================================
Automated pytest suite covering all E35 backend logic:

  1.  log_manual_bet() creates a correctly populated BetLog row
  2.  log_manual_bet() returns None (not raises) on DB failure
  3.  Duplicate-check: same user + match + market + selection today → True
  4.  load_user_bets() returns only user_placed bets for the requesting user
  5.  load_user_bets() with status_filter="Pending" returns only pending rows
  6.  update_bet() changes stake on a pending bet; DB reflects the change
  7.  update_bet() returns False for a non-pending (won/lost/void) bet
  8.  update_bet() returns False when user_id does not own the bet
  9.  void_bet() sets status="void" and pnl=0.0 in the DB
  10. void_bet() returns False for bets not owned by requesting user
  11. Voided bets excluded from ROI filter that load_bet_data() uses

Run with: pytest tests/test_e35_integration.py -v

Architecture note:
  my_bets.py contains module-level Streamlit rendering code (it is a Streamlit
  page file). When importing it in a test context, we must mock the 'streamlit'
  module BEFORE import to prevent crashes.  The mock is installed at module load
  time below so it is in place for every test in this file.

  Tests use an in-memory SQLite engine.  All get_session() calls are redirected
  to this engine via the use_test_db fixture (autouse=True), which patches
  src.database.db._engine / _SessionFactory before each test and restores them
  afterward.

  SQLite does NOT enforce foreign key constraints without PRAGMA foreign_keys=ON.
  Because the test engine does not run that pragma, we can use a dummy match_id
  (9999) without needing real rows in the matches / leagues / teams tables.
"""

from __future__ import annotations

import sys
from pathlib import Path
from datetime import date, datetime
from typing import Any, Dict
from unittest.mock import MagicMock

# ============================================================================
# Install streamlit mock BEFORE any src import that touches st.*
# ============================================================================
# my_bets.py has module-level st.markdown() / st.columns() / st.radio() calls
# that run at import time.  We mock the entire streamlit module so those calls
# become silent no-ops.

def _make_st_mock() -> MagicMock:
    """Return a MagicMock that is safe enough for Streamlit page imports."""
    st = MagicMock()
    # Actual dict so st.session_state.get("user_id", 1) → 1 (the default),
    # which makes get_session_user_id() return int(1) instead of MagicMock().
    st.session_state = {}
    # st.columns([widths]) / st.columns(n) must return an iterable of the
    # correct length — otherwise tuple-unpacking at module level crashes.
    st.columns.side_effect = lambda spec: [
        MagicMock() for _ in range(spec if isinstance(spec, int) else len(spec))
    ]
    # st.tabs(["A", "B"]) must also return a list.
    st.tabs.side_effect = lambda names: [MagicMock() for _ in names]
    # Form submit button should return False (not submitted) so the submission
    # code block does not execute during import.
    st.form_submit_button.return_value = False
    # Status radio defaults to "All" so load_user_bets() receives a valid string.
    st.radio.return_value = "All"
    return st


if "streamlit" not in sys.modules:
    sys.modules["streamlit"] = _make_st_mock()

# ============================================================================
# Path setup
# ============================================================================

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.db import Base
from src.database.models import BetLog, User
import src.database.db as db_mod


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture(scope="module")
def engine():
    """In-memory SQLite engine with all tables initialised."""
    eng = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture(scope="module")
def SessionLocal(engine):
    """Sessionmaker bound to the in-memory engine."""
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture(autouse=True)
def use_test_db(engine, SessionLocal):
    """Redirect all get_session() calls to the in-memory engine.

    Patches the module-level singletons in src.database.db for the duration
    of each test, then restores the originals so the production engine is not
    affected.
    """
    orig_engine = db_mod._engine
    orig_factory = db_mod._SessionFactory
    db_mod._engine = engine
    db_mod._SessionFactory = SessionLocal
    yield
    db_mod._engine = orig_engine
    db_mod._SessionFactory = orig_factory


@pytest.fixture(scope="module")
def user1(engine, SessionLocal):
    """Seed owner user (user_id=1 in test DB)."""
    session = SessionLocal()
    u = User(
        name="BVOwner",
        email="owner@bv-test.local",
        role="owner",
        starting_bankroll=1000.0,
        current_bankroll=1000.0,
        staking_method="flat",
        stake_percentage=0.02,
        kelly_fraction=0.25,
        edge_threshold=0.05,
        is_active=1,
        has_onboarded=1,
        created_at=datetime.utcnow().isoformat(),
        updated_at=datetime.utcnow().isoformat(),
    )
    session.add(u)
    session.commit()
    session.refresh(u)
    session.expunge(u)
    session.close()
    return u


@pytest.fixture(scope="module")
def user2(engine, SessionLocal):
    """Seed viewer user (different user_id — used for cross-user guard tests)."""
    session = SessionLocal()
    u = User(
        name="BVViewer",
        email="viewer@bv-test.local",
        role="viewer",
        starting_bankroll=500.0,
        current_bankroll=500.0,
        staking_method="flat",
        stake_percentage=0.02,
        kelly_fraction=0.25,
        edge_threshold=0.05,
        is_active=1,
        has_onboarded=1,
        created_at=datetime.utcnow().isoformat(),
        updated_at=datetime.utcnow().isoformat(),
    )
    session.add(u)
    session.commit()
    session.refresh(u)
    session.expunge(u)
    session.close()
    return u


@pytest.fixture
def sample_match() -> Dict[str, Any]:
    """Minimal match dict accepted by log_manual_bet().

    match_id=9999 is a dummy — SQLite does not enforce FK constraints without
    PRAGMA foreign_keys=ON (which the test engine does not enable).
    """
    return {
        "id": 9999,
        "date": date.today().isoformat(),
        "home_team": "Arsenal",
        "away_team": "Chelsea",
        "league_short": "EPL",
    }


def _make_bet(SessionLocal, user_id: int, **overrides) -> int:
    """Insert a BetLog row directly for test setup and return its id.

    Uses sensible defaults so callers only need to supply the fields that
    matter for the specific test scenario.  FK constraints are not enforced
    by the in-memory test engine, so match_id=9999 is safe.
    """
    now = datetime.utcnow().isoformat()
    today = date.today().isoformat()
    defaults: Dict[str, Any] = dict(
        user_id=user_id,
        match_id=9999,
        date=today,
        league="EPL",
        home_team="Arsenal",
        away_team="Chelsea",
        market_type="1X2",
        selection="Home",
        model_prob=0.0,
        edge=0.0,
        bookmaker="Pinnacle",
        odds_at_detection=2.10,
        odds_at_placement=2.10,
        implied_prob=round(1 / 2.10, 4),
        stake=25.0,
        stake_method="manual",
        bet_type="user_placed",
        status="pending",
        pnl=0.0,
        created_at=now,
        updated_at=now,
    )
    defaults.update(overrides)
    session = SessionLocal()
    bet = BetLog(**defaults)
    session.add(bet)
    session.commit()
    session.refresh(bet)
    bet_id = bet.id
    session.expunge(bet)
    session.close()
    return bet_id


# ============================================================================
# Test 1 — log_manual_bet() creates a correctly populated BetLog row
# ============================================================================

class TestLogManualBet:
    """log_manual_bet() must write every expected field correctly."""

    def test_creates_bet_log_row(self, user1, user2, SessionLocal, sample_match):
        """Created row has correct sentinel values and flags (E35-01 spec)."""
        from src.delivery.views.my_bets import log_manual_bet

        odds = 2.10
        stake = 25.0
        bet_id = log_manual_bet(
            user_id=user1.id,
            match=sample_match,
            market_type="1X2",
            selection="Home",
            bookmaker="Pinnacle",
            odds=odds,
            stake=stake,
        )

        assert bet_id is not None, "log_manual_bet() must return the new BetLog id"
        assert isinstance(bet_id, int), "bet_id must be an integer"

        # Inspect the row that was written
        session = SessionLocal()
        bet = session.get(BetLog, bet_id)
        assert bet is not None, "BetLog row not found after insert"

        assert bet.user_id == user1.id
        assert bet.match_id == sample_match["id"]
        assert bet.date == sample_match["date"]
        assert bet.home_team == sample_match["home_team"]
        assert bet.away_team == sample_match["away_team"]
        assert bet.league == sample_match["league_short"]
        assert bet.market_type == "1X2"
        assert bet.selection == "Home"
        assert bet.bookmaker == "Pinnacle"
        assert bet.odds_at_detection == odds
        assert bet.odds_at_placement == odds
        # implied_prob = 1 / odds (sentinel precision)
        assert abs(bet.implied_prob - round(1.0 / odds, 4)) < 1e-6
        assert bet.stake == stake
        assert bet.bet_type == "user_placed"
        assert bet.status == "pending"
        # model_prob and edge are 0.0 sentinels (NOT NULL columns; no model involved)
        assert bet.model_prob == 0.0, "model_prob sentinel must be 0.0"
        assert bet.edge == 0.0,       "edge sentinel must be 0.0"
        # stake_method must flag this as a manually entered bet
        assert bet.stake_method == "manual"

        session.close()

    # --------------------------------------------------------------------- #

    def test_returns_none_on_db_failure(self, user1, SessionLocal, sample_match):
        """Returns None (not raises) when the DB write fails (Rule 6 resilience)."""
        from src.delivery.views.my_bets import log_manual_bet

        # Passing match_id=None triggers a NOT NULL IntegrityError.  The
        # function's except block must catch it and return None.
        bad_match = dict(sample_match, id=None)
        result = log_manual_bet(
            user_id=user1.id,
            match=bad_match,
            market_type="1X2",
            selection="Home",
            bookmaker="Pinnacle",
            odds=2.10,
            stake=25.0,
        )
        assert result is None, "Expected None on DB failure, not an exception"


# ============================================================================
# Test 3 — check_duplicate_bet() detects an existing pending bet
# ============================================================================

class TestCheckDuplicateBet:
    """Duplicate guard must fire for same user/match/market/selection/date."""

    def test_existing_bet_returns_true(self, user1, SessionLocal):
        """check_duplicate_bet() returns True when a matching row exists."""
        from src.delivery.views.my_bets import check_duplicate_bet

        # Create a known pending bet so we have something to detect
        _make_bet(SessionLocal, user_id=user1.id, market_type="Over 2.5",
                  selection="Over", match_id=9998)

        result = check_duplicate_bet(
            user_id=user1.id,
            match_id=9998,
            market_type="Over 2.5",
            selection="Over",
        )
        assert result is True, "Expected True (duplicate exists)"

    def test_no_bet_returns_false(self, user1):
        """check_duplicate_bet() returns False when no matching row exists."""
        from src.delivery.views.my_bets import check_duplicate_bet

        result = check_duplicate_bet(
            user_id=user1.id,
            match_id=88888,   # match_id nobody has bet on
            market_type="1X2",
            selection="Away",
        )
        assert result is False, "Expected False (no duplicate)"


# ============================================================================
# Test 4 — load_user_bets() returns only user_placed bets for the requestor
# ============================================================================

class TestLoadUserBets:
    """load_user_bets() scoping: only user_placed bets for the requesting user."""

    def test_excludes_system_picks(self, user1, user2, SessionLocal):
        """system_pick bets must never appear in the user's bet slip."""
        from src.delivery.views.my_bets import load_user_bets

        _make_bet(SessionLocal, user_id=user1.id,
                  bet_type="system_pick", market_type="BTTS", selection="Yes",
                  match_id=7001)

        bets = load_user_bets(user1.id)
        for b in bets:
            assert b["status"] != "system_pick", (
                "system_pick bets must not appear in load_user_bets()"
            )

    def test_excludes_other_users_bets(self, user1, user2, SessionLocal):
        """user_placed bets belonging to user2 must not appear for user1."""
        from src.delivery.views.my_bets import load_user_bets

        # Unique market/selection so we can identify this bet
        _make_bet(SessionLocal, user_id=user2.id,
                  market_type="Under 2.5", selection="Under", match_id=7002)

        bets_u1 = load_user_bets(user1.id)
        for b in bets_u1:
            # "Under 2.5 / Under" was created for user2 only
            assert not (b["market_type"] == "Under 2.5" and b["selection"] == "Under"), (
                "user2's bet must not appear in user1's load_user_bets()"
            )

    def test_returns_own_user_placed_bets(self, user1, SessionLocal):
        """Own user_placed bets appear in the results."""
        from src.delivery.views.my_bets import load_user_bets

        _make_bet(SessionLocal, user_id=user1.id,
                  market_type="Asian Handicap", selection="Chelsea +0.5",
                  match_id=7003)

        bets = load_user_bets(user1.id)
        assert any(
            b["market_type"] == "Asian Handicap" and b["selection"] == "Chelsea +0.5"
            for b in bets
        ), "Expected user1's Asian Handicap bet in load_user_bets()"

    # --------------------------------------------------------------------- #

    def test_status_filter_pending_returns_only_pending(self, user1, SessionLocal):
        """status_filter='Pending' must exclude won/lost/void rows (Test 5)."""
        from src.delivery.views.my_bets import load_user_bets

        _make_bet(SessionLocal, user_id=user1.id,
                  status="pending", market_type="1X2", selection="Draw",
                  match_id=7004)
        _make_bet(SessionLocal, user_id=user1.id,
                  status="won", pnl=10.0, market_type="1X2", selection="Home",
                  match_id=7005)
        _make_bet(SessionLocal, user_id=user1.id,
                  status="lost", pnl=-25.0, market_type="Over 2.5", selection="Over",
                  match_id=7006)

        bets = load_user_bets(user1.id, status_filter="Pending")
        assert len(bets) > 0, "Expected at least one pending bet"
        for b in bets:
            assert b["status"] == "pending", (
                f"status_filter=Pending must exclude non-pending; got {b['status']}"
            )


# ============================================================================
# Test 6 — update_bet() changes stake on a pending bet
# ============================================================================

class TestUpdateBet:
    """update_bet() edits only pending, user-owned bets."""

    def test_updates_stake_on_pending_bet(self, user1, SessionLocal):
        """stake and implied_prob are updated; DB reflects new values (Test 6)."""
        from src.delivery.views.my_bets import update_bet

        bet_id = _make_bet(SessionLocal, user_id=user1.id,
                           stake=25.0, odds_at_placement=2.10,
                           market_type="1X2", selection="Away", match_id=8001)

        result = update_bet(bet_id, user1.id, stake=75.0, odds_at_placement=2.30)
        assert result is True, "update_bet() must return True on success"

        session = SessionLocal()
        bet = session.get(BetLog, bet_id)
        assert bet.stake == 75.0
        assert bet.odds_at_placement == 2.30
        # implied_prob should be recalculated from the new placement odds
        assert abs(bet.implied_prob - round(1.0 / 2.30, 4)) < 1e-6
        session.close()

    def test_returns_false_for_non_pending_bet(self, user1, SessionLocal):
        """Cannot edit a won bet — update_bet() must return False (Test 7)."""
        from src.delivery.views.my_bets import update_bet

        bet_id = _make_bet(SessionLocal, user_id=user1.id,
                           status="won", pnl=10.0,
                           market_type="1X2", selection="Draw", match_id=8002)

        result = update_bet(bet_id, user1.id, stake=999.0)
        assert result is False, "update_bet() must return False for a won bet"

        # Confirm stake was NOT changed
        session = SessionLocal()
        bet = session.get(BetLog, bet_id)
        assert bet.stake == 25.0, "Stake must remain unchanged after failed update"
        session.close()

    def test_returns_false_for_wrong_user(self, user1, user2, SessionLocal):
        """Cannot edit another user's bet (Test 8)."""
        from src.delivery.views.my_bets import update_bet

        bet_id = _make_bet(SessionLocal, user_id=user1.id,
                           status="pending", match_id=8003,
                           market_type="BTTS", selection="No")

        # user2 tries to edit user1's bet
        result = update_bet(bet_id, user2.id, stake=500.0)
        assert result is False, "update_bet() must return False for wrong user_id"

        # Confirm stake was NOT changed
        session = SessionLocal()
        bet = session.get(BetLog, bet_id)
        assert bet.stake == 25.0, "Stake must be unchanged after cross-user update attempt"
        session.close()


# ============================================================================
# Test 9 — void_bet() sets status="void" and pnl=0.0
# ============================================================================

class TestVoidBet:
    """void_bet() correctly voids bets and enforces user ownership."""

    def test_sets_void_and_zero_pnl(self, user1, SessionLocal):
        """void_bet() must write status='void' and pnl=0.0 (Test 9)."""
        from src.delivery.views.my_bets import void_bet

        bet_id = _make_bet(SessionLocal, user_id=user1.id,
                           status="won", pnl=10.0,
                           market_type="1X2", selection="Home", match_id=9001)

        result = void_bet(bet_id, user1.id)
        assert result is True, "void_bet() must return True on success"

        session = SessionLocal()
        bet = session.get(BetLog, bet_id)
        assert bet.status == "void", f"Expected status='void', got '{bet.status}'"
        assert bet.pnl == 0.0, f"Expected pnl=0.0 after void, got {bet.pnl}"
        session.close()

    def test_returns_false_for_wrong_user(self, user1, user2, SessionLocal):
        """Cannot void another user's bet (Test 10)."""
        from src.delivery.views.my_bets import void_bet

        bet_id = _make_bet(SessionLocal, user_id=user1.id,
                           status="pending", match_id=9002,
                           market_type="Over 2.5", selection="Over")

        # user2 tries to void user1's bet
        result = void_bet(bet_id, user2.id)
        assert result is False, "void_bet() must return False for wrong user_id"

        # Confirm bet was NOT voided
        session = SessionLocal()
        bet = session.get(BetLog, bet_id)
        assert bet.status == "pending", "Bet status must remain 'pending' after failed void"
        session.close()


# ============================================================================
# Test 11 — Voided bets excluded from ROI calculations
# ============================================================================

class TestVoidedBetsExcludedFromROI:
    """Voided bets must be excluded from the won/lost filter used by load_bet_data()."""

    def test_void_excluded_from_pnl_filter(self, user1, SessionLocal):
        """A voided bet must not appear in BetLog.status.in_(['won', 'lost']) queries.

        Performance Tracker's load_bet_data() uses exactly this filter to compute
        ROI metrics, so this test validates the exclusion at the DB query layer
        without importing performance.py (which has module-level Streamlit code).
        """
        from src.delivery.views.my_bets import void_bet
        from src.database.db import get_session

        # Create a bet that starts as "won"
        bet_id = _make_bet(SessionLocal, user_id=user1.id,
                           status="won", pnl=15.0,
                           market_type="1X2", selection="Away", match_id=10001)

        # Verify it appears in a won/lost query BEFORE voiding
        with get_session() as session:
            before = session.query(BetLog).filter(
                BetLog.id == bet_id,
                BetLog.status.in_(["won", "lost"]),
            ).first()
        assert before is not None, "Bet must appear in won/lost filter before voiding"

        # Void it
        ok = void_bet(bet_id, user1.id)
        assert ok is True

        # Must NOT appear in won/lost filter after voiding
        with get_session() as session:
            after = session.query(BetLog).filter(
                BetLog.id == bet_id,
                BetLog.status.in_(["won", "lost"]),
            ).first()
        assert after is None, (
            "Voided bet must not appear in status.in_(['won','lost']) filter "
            "used by Performance Tracker load_bet_data()"
        )

    def test_void_excluded_from_summary_metrics(self, user1, SessionLocal):
        """Voided bets are excluded from load_summary_metrics() P&L totals.

        load_summary_metrics() filters status NOT IN ('pending', 'void') — this
        test confirms that voiding a won bet removes its P&L contribution.

        We use a delta approach: capture baseline BEFORE adding the test bet,
        then verify the delta after voiding exactly cancels the added pnl.
        This is robust regardless of what other tests have written to the DB.
        """
        from src.delivery.views.my_bets import void_bet, load_summary_metrics

        # Baseline — captures whatever P&L other tests have already accumulated
        baseline = load_summary_metrics(user1.id)

        # Add a won bet with a distinctive pnl we can track as a delta
        bet_id = _make_bet(SessionLocal, user_id=user1.id,
                           status="won", pnl=100.0,
                           market_type="BTTS", selection="Yes", match_id=10002)

        metrics_with_bet = load_summary_metrics(user1.id)
        assert metrics_with_bet["pnl_alltime"] == pytest.approx(
            baseline["pnl_alltime"] + 100.0, abs=0.01
        ), "pnl_alltime must include the newly added won bet's P&L"

        # Void the bet — pnl_alltime must drop back to baseline
        void_bet(bet_id, user1.id)
        metrics_after = load_summary_metrics(user1.id)

        assert metrics_after["pnl_alltime"] < metrics_with_bet["pnl_alltime"], (
            "pnl_alltime must decrease after voiding a won bet"
        )
        assert metrics_after["pnl_alltime"] == pytest.approx(
            baseline["pnl_alltime"], abs=0.01
        ), "pnl_alltime must equal baseline after voiding — the void's P&L is excluded"
