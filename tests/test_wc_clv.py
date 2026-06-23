"""WC-09-01 — closing-line capture + CLV for WC shadow picks."""

from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.db import Base
import src.world_cup.value_finder as vf
from src.world_cup.models import WCTeam, WCMatch, WCOdds, WCPrediction, WCValueBet
from src.world_cup.predictor import MODEL_NAME


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def _seed(s, *, status="finished"):
    s.add_all([
        WCTeam(id=1, name="Brazil", fifa_code="BRA", confederation="CONMEBOL", group_letter="C"),
        WCTeam(id=2, name="Scotland", fifa_code="SCO", confederation="UEFA", group_letter="C"),
    ])
    s.add(WCMatch(id=10, stage="group", group_letter="C", date="2026-06-20",
                  kickoff_time="18:00", home_team_id=1, away_team_id=2,
                  status=status, home_goals=2, away_goals=0))
    s.add(WCPrediction(id=100, match_id=10, model_name=MODEL_NAME,
                       home_win_prob=0.6, draw_prob=0.25, away_win_prob=0.15,
                       home_expected_goals=1.8, away_expected_goals=0.7))
    # Closing odds for the home team (best across books = 1.50)
    s.add(WCOdds(match_id=10, bookmaker="Pinnacle", market_type="h2h",
                 selection="Brazil", odds_decimal=1.50, captured_at="2026-06-20T08:00"))
    s.add(WCOdds(match_id=10, bookmaker="FanDuel", market_type="h2h",
                 selection="Brazil", odds_decimal=1.45, captured_at="2026-06-20T08:00"))
    # Shadow pick taken at a better entry price of 1.70
    s.add(WCValueBet(id=500, match_id=10, prediction_id=100, market_type="h2h",
                     selection="home", model_prob=0.6, best_odds=1.70,
                     implied_prob=0.588, edge=0.012, bookmaker="DraftKings"))
    s.commit()


@contextmanager
def _patch(session):
    @contextmanager
    def fake():
        yield session
    yield fake


def test_captures_closing_and_clv(session, monkeypatch):
    _seed(session)
    with _patch(session) as fake:
        monkeypatch.setattr(vf, "get_session", fake)
        out = vf.capture_wc_closing_lines()
    assert out["captured"] == 1
    vb = session.get(WCValueBet, 500)
    assert vb.closing_odds == 1.50  # best frozen price for the home selection
    expected = (1 / 1.50) - (1 / 1.70)
    assert abs(vb.clv - expected) < 1e-6
    assert vb.clv > 0  # entry 1.70 beat the 1.50 close → positive CLV


def test_idempotent(session, monkeypatch):
    _seed(session)
    with _patch(session) as fake:
        monkeypatch.setattr(vf, "get_session", fake)
        vf.capture_wc_closing_lines()
        out2 = vf.capture_wc_closing_lines()
    assert out2["captured"] == 0  # already has a closing line


def test_skips_unfinished_match(session, monkeypatch):
    _seed(session, status="scheduled")
    with _patch(session) as fake:
        monkeypatch.setattr(vf, "get_session", fake)
        out = vf.capture_wc_closing_lines()
    assert out["captured"] == 0
    assert session.get(WCValueBet, 500).closing_odds is None


def test_clv_sign_when_line_shortens_against_us(session, monkeypatch):
    # If the close (1.50) is LONGER than our entry... flip: entry 1.40, close 1.50
    _seed(session)
    vb = session.get(WCValueBet, 500)
    vb.best_odds = 1.40  # we took a worse price than the close
    session.commit()
    with _patch(session) as fake:
        monkeypatch.setattr(vf, "get_session", fake)
        vf.capture_wc_closing_lines()
    vb = session.get(WCValueBet, 500)
    assert vb.clv < 0  # entry 1.40 worse than 1.50 close → negative CLV
