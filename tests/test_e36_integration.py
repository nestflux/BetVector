"""
E36-04 — Multi-League Integration Test
=======================================
Automated pytest suite verifying that the multi-league expansion (E36-01
through E36-03) is correctly wired end-to-end.

Scenarios:
  1.  Championship 2024-25 backtest report exists and is parseable
  2.  La Liga 2024-25 backtest report exists and is parseable
  3.  Championship backtest ran to completion (552 matches predicted)
  4.  La Liga backtest ran to completion (380 matches predicted)
  5.  La Liga Brier score within ±0.05 of EPL baseline (0.5781)
  6.  La Liga ROI is positive (profitable)
  7.  is_newly_promoted=1 for Championship relegated teams (Burnley, Sheffield United, Luton)
  8.  is_newly_promoted=1 for Championship League-One promoted teams (Oxford, Portsmouth, Derby)
  9.  is_newly_promoted=1 for La Liga promoted teams (Leganés, Españyol, Valladolid)
  10. All 3 leagues have Feature rows in the database
  11. Championship has per-league edge threshold 0.03 (3%) in config
  12. EPL and La Liga have per-league edge threshold 0.05 (5%) in config
  13. All 3 leagues are active in the database
  14. is_newly_promoted=0 for established Championship teams not new this season
  15. Champion + La Liga match counts exceed expected minimums

Run with: pytest tests/test_e36_integration.py -v

Architecture note:
  These tests verify state that was established by the E36 data pipeline runs
  (backtest, feature computation) rather than re-running the pipeline in-test.
  They use the real production DB so no DB patching is needed.
"""

from __future__ import annotations

import contextlib
import json
import sys
from pathlib import Path

import pytest

# ============================================================================
# Path setup
# ============================================================================

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# ============================================================================
# Helpers
# ============================================================================

def _load_report(filename: str) -> dict:
    """Load a backtest JSON report from data/predictions/."""
    path = Path("data/predictions") / filename
    assert path.exists(), f"Backtest report not found: {path}"
    with path.open() as f:
        return json.load(f)


_exit_stack = contextlib.ExitStack()   # holds the session context manager
_db_session = None                       # cached session, shared across all tests


def _get_session():
    """Return a shared SQLAlchemy session for the entire test module.

    The session is opened lazily on first call and reused for all subsequent
    calls in this module (all tests are read-only — no commits needed).
    An ExitStack + atexit handler ensures the session context manager's
    __exit__ is called when the process exits, releasing the DB connection
    back to the pool cleanly.
    """
    global _db_session
    if _db_session is None:
        import atexit
        from src.database.db import get_session
        _db_session = _exit_stack.enter_context(get_session())
        atexit.register(_exit_stack.close)
    return _db_session


def _newly_promoted(team_name_fragment: str, league_id: int, season: str) -> bool:
    """Return True if any home match for this team has is_newly_promoted=1."""
    from src.database.models import Feature, Match, Team
    s = _get_session()
    team = s.query(Team).filter(
        Team.name.like(f"%{team_name_fragment}%"),
        Team.league_id == league_id,
    ).first()
    if team is None:
        pytest.fail(f"Team not found in league {league_id}: {team_name_fragment!r}")
    row = (
        s.query(Feature)
        .join(Match, Feature.match_id == Match.id)
        .filter(
            Match.home_team_id == team.id,
            Match.league_id == league_id,
            Match.season == season,
            Feature.is_newly_promoted == 1,
        )
        .first()
    )
    return row is not None


# EPL Brier baseline from E23-06 (market-augmented Poisson, 5-season training)
EPL_BRIER_BASELINE = 0.5781
BRIER_TOLERANCE = 0.05      # ±5% points is the target from the build plan
LEAGUE_ID_EPL  = 1
LEAGUE_ID_CHAMP = 2
LEAGUE_ID_LALIGA = 3


# ============================================================================
# Test 1 — Championship backtest report exists
# ============================================================================

def test_championship_report_exists():
    """Backtest report JSON must exist for Championship 2024-25."""
    path = Path("data/predictions/backtest_report_Championship_2024-25.json")
    assert path.exists(), (
        f"Championship backtest report not found at {path}. "
        "Run: python run_pipeline.py backtest --league Championship --season 2024-25"
    )


# ============================================================================
# Test 2 — La Liga backtest report exists
# ============================================================================

def test_laliga_report_exists():
    """Backtest report JSON must exist for La Liga 2024-25."""
    path = Path("data/predictions/backtest_report_LaLiga_2024-25.json")
    assert path.exists(), (
        f"La Liga backtest report not found at {path}. "
        "Run: python run_pipeline.py backtest --league LaLiga --season 2024-25"
    )


# ============================================================================
# Test 3 — Championship backtest: correct match count
# ============================================================================

def test_championship_match_count():
    """Championship 2024-25 backtest should have predicted exactly 552 matches."""
    report = _load_report("backtest_report_Championship_2024-25.json")
    summary = report["summary"]
    assert summary["total_matches"] == 552, (
        f"Expected 552 Championship matches, got {summary['total_matches']}"
    )
    assert summary["total_predicted"] == 552, (
        f"Expected 552 predicted, got {summary['total_predicted']}"
    )


# ============================================================================
# Test 4 — La Liga backtest: correct match count
# ============================================================================

def test_laliga_match_count():
    """La Liga 2024-25 backtest should have predicted exactly 380 matches."""
    report = _load_report("backtest_report_LaLiga_2024-25.json")
    summary = report["summary"]
    assert summary["total_matches"] == 380, (
        f"Expected 380 La Liga matches, got {summary['total_matches']}"
    )
    assert summary["total_predicted"] == 380, (
        f"Expected 380 predicted, got {summary['total_predicted']}"
    )


# ============================================================================
# Test 5 — La Liga Brier score within ±0.05 of EPL baseline
# ============================================================================

def test_laliga_brier_within_tolerance():
    """La Liga Brier score must be within ±0.05 of EPL baseline (0.5781).

    This validates that the multi-league feature set generalises to La Liga.
    The build plan target is ±0.05 (5 percentage points).
    """
    report = _load_report("backtest_report_LaLiga_2024-25.json")
    brier = report["summary"]["brier_score"]
    diff = abs(brier - EPL_BRIER_BASELINE)
    assert diff <= BRIER_TOLERANCE, (
        f"La Liga Brier {brier:.4f} is {diff:.4f} away from EPL baseline "
        f"{EPL_BRIER_BASELINE} — outside ±{BRIER_TOLERANCE} tolerance"
    )


# ============================================================================
# Test 6 — La Liga ROI is positive
# ============================================================================

def test_laliga_roi_positive():
    """La Liga backtest ROI must be positive (profitable model)."""
    report = _load_report("backtest_report_LaLiga_2024-25.json")
    roi = report["summary"]["roi"]
    assert roi > 0, (
        f"La Liga ROI is {roi:.2f}% — model is not profitable on La Liga 2024-25"
    )


# ============================================================================
# Tests 7-8 — is_newly_promoted for Championship 2024-25
# ============================================================================

@pytest.mark.parametrize("team_fragment, description", [
    # Relegated from EPL 2023-24 to Championship 2024-25
    ("Burnley",          "relegated from EPL"),
    ("Sheffield United", "relegated from EPL"),
    ("Luton",            "relegated from EPL"),
    # Promoted from League One 2023-24 to Championship 2024-25
    ("Oxford",     "promoted from League One"),
    ("Portsmouth", "promoted from League One"),
    ("Derby",      "promoted from League One"),
])
def test_championship_newly_promoted_teams(team_fragment: str, description: str):
    """Teams new to Championship 2024-25 must have is_newly_promoted=1.

    Covers both relegated EPL teams and promoted League One teams, since both
    are 'new to this division' from the model's perspective.
    """
    assert _newly_promoted(team_fragment, LEAGUE_ID_CHAMP, "2024-25"), (
        f"Expected is_newly_promoted=1 for {team_fragment!r} ({description}) "
        f"in Championship 2024-25 — feature may not have been recomputed "
        f"after E36-03."
    )


# ============================================================================
# Test 9 — is_newly_promoted for La Liga 2024-25
# ============================================================================

@pytest.mark.parametrize("team_fragment, description", [
    # Promoted from Segunda División 2023-24 to La Liga 2024-25
    ("Leganes",    "promoted from Segunda"),
    ("Espanol",    "promoted from Segunda"),
    ("Valladolid", "promoted from Segunda"),
])
def test_laliga_newly_promoted_teams(team_fragment: str, description: str):
    """Teams promoted to La Liga 2024-25 must have is_newly_promoted=1."""
    assert _newly_promoted(team_fragment, LEAGUE_ID_LALIGA, "2024-25"), (
        f"Expected is_newly_promoted=1 for {team_fragment!r} ({description}) "
        f"in La Liga 2024-25."
    )


# ============================================================================
# Test 10 — All 3 leagues have Feature rows
# ============================================================================

@pytest.mark.parametrize("league_id, min_features, league_name", [
    (LEAGUE_ID_EPL,   1_500, "EPL"),
    (LEAGUE_ID_CHAMP, 4_000, "Championship"),
    (LEAGUE_ID_LALIGA, 2_700, "La Liga"),
])
def test_all_leagues_have_features(league_id: int, min_features: int, league_name: str):
    """Every active league must have computed Feature rows in the DB.

    These rows are the input to the Poisson model.  If they're missing,
    the backtester trains on nothing and the model is meaningless.
    """
    from src.database.models import Feature, Match
    s = _get_session()
    count = (
        s.query(Feature)
        .join(Match, Feature.match_id == Match.id)
        .filter(Match.league_id == league_id)
        .count()
    )
    assert count >= min_features, (
        f"{league_name}: expected ≥{min_features} feature rows, found {count}. "
        f"Run scripts/backfill_historical.py to recompute."
    )


# ============================================================================
# Tests 11-12 — Per-league edge thresholds from config
# ============================================================================

def _get_league_threshold(short_name: str) -> float:
    """Read per-league edge threshold from leagues.yaml config."""
    import yaml
    config_path = Path("config/leagues.yaml")
    assert config_path.exists(), "config/leagues.yaml not found"
    with config_path.open() as f:
        cfg = yaml.safe_load(f)
    for lg in cfg.get("leagues", []):
        if lg["short_name"] == short_name:
            # Leagues may use "edge_threshold_override" (per-league override) or
            # "edge_threshold" (direct), falling back to the global default (0.05).
            return float(
                lg.get("edge_threshold_override",
                lg.get("edge_threshold",
                cfg.get("default_edge_threshold", 0.05)))
            )
    pytest.fail(f"League {short_name!r} not found in leagues.yaml")


def test_championship_edge_threshold():
    """Championship must use a 10% edge threshold (PC-24-01: sweep-validated).

    The Championship market is less efficient than EPL.  PC-24-01 threshold
    sweep showed best ROI at 10% (+10.5%, 731 VBs).  Originally 3% in E36-03,
    raised to 10% in PC-24-01.
    """
    threshold = _get_league_threshold("Championship")
    assert threshold == pytest.approx(0.10, abs=1e-6), (
        f"Championship edge_threshold should be 0.10 (PC-24-01), got {threshold}"
    )


@pytest.mark.parametrize("short_name,expected", [
    ("EPL", 0.05),
    ("LaLiga", 0.08),  # PC-24-01: best ROI at 8% (+18.1%, 110 VBs)
])
def test_standard_edge_threshold(short_name: str, expected: float):
    """EPL uses 5% (default), LaLiga uses 8% (PC-24-01 sweep-validated)."""
    threshold = _get_league_threshold(short_name)
    assert threshold == pytest.approx(expected, abs=1e-6), (
        f"{short_name} edge_threshold should be {expected}, got {threshold}"
    )


# ============================================================================
# Test 13 — All 3 leagues active in database
# ============================================================================

def test_all_leagues_active_in_db():
    """All 3 leagues (EPL, Championship, La Liga) must be active in the DB."""
    from src.database.models import League
    s = _get_session()
    leagues = s.query(League).filter_by(is_active=1).all()
    active_ids = {lg.id for lg in leagues}
    for lid, name in [
        (LEAGUE_ID_EPL,    "EPL"),
        (LEAGUE_ID_CHAMP,  "Championship"),
        (LEAGUE_ID_LALIGA, "La Liga"),
    ]:
        assert lid in active_ids, f"{name} (id={lid}) is not active in the database"


# ============================================================================
# Test 14 — is_newly_promoted=0 for established Championship teams
# ============================================================================

@pytest.mark.parametrize("team_fragment", ["West Brom", "Coventry", "Middlesbrough"])
def test_established_championship_teams_not_newly_promoted(team_fragment: str):
    """Teams that played in Championship 2023-24 must NOT be newly promoted in 2024-25.

    This sanity-checks that the feature correctly identifies ONLY new teams
    and does not mark veterans as newly promoted.
    """
    from src.database.models import Feature, Match, Team
    s = _get_session()
    team = s.query(Team).filter(
        Team.name.like(f"%{team_fragment}%"),
        Team.league_id == LEAGUE_ID_CHAMP,
    ).first()
    if team is None:
        pytest.skip(f"Team {team_fragment!r} not found in Championship")

    # Find any home match for this team in 2024-25
    match = s.query(Match).filter(
        Match.home_team_id == team.id,
        Match.league_id == LEAGUE_ID_CHAMP,
        Match.season == "2024-25",
    ).first()
    if match is None:
        pytest.skip(f"No 2024-25 home match for {team_fragment!r}")

    feat = s.query(Feature).filter_by(match_id=match.id).first()
    if feat is None:
        pytest.skip(f"No feature row for {team_fragment!r}'s home match")

    assert feat.is_newly_promoted == 0, (
        f"{team_fragment!r} should have is_newly_promoted=0 "
        f"(they played in Championship 2023-24), got {feat.is_newly_promoted}"
    )


# ============================================================================
# Test 15 — Match and odds counts exceed minimums
# ============================================================================

@pytest.mark.parametrize("league_id, min_matches, min_odds, league_name", [
    (LEAGUE_ID_EPL,    750,  10_000, "EPL"),
    (LEAGUE_ID_CHAMP,  2_000, 25_000, "Championship"),
    (LEAGUE_ID_LALIGA, 1_300, 15_000, "La Liga"),
])
def test_match_and_odds_counts(
    league_id: int, min_matches: int, min_odds: int, league_name: str
):
    """Each league must have enough historical matches and odds rows.

    These are the lower bounds based on the E36-01/02 pipeline results.
    A count below these thresholds means the data pipeline didn't complete.
    """
    from src.database.models import Match, Odds
    s = _get_session()
    match_count = s.query(Match).filter_by(league_id=league_id).count()
    odds_count = (
        s.query(Odds)
        .join(Match, Odds.match_id == Match.id)
        .filter(Match.league_id == league_id)
        .count()
    )
    assert match_count >= min_matches, (
        f"{league_name}: expected ≥{min_matches} matches, found {match_count}"
    )
    assert odds_count >= min_odds, (
        f"{league_name}: expected ≥{min_odds} odds rows, found {odds_count}"
    )
