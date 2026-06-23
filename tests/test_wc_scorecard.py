"""WC-09-02 — shadow scorecard computation."""

from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.db import Base
import src.world_cup.scorecard as sc
from src.world_cup.scorecard import settle_wc_pick, compute_wc_scorecard
from src.world_cup.models import WCTeam, WCMatch, WCPrediction, WCValueBet
from src.world_cup.predictor import MODEL_NAME


def _vb(market, sel):
    return SimpleNamespace(market_type=market, selection=sel)


def _m(hg, ag):
    return SimpleNamespace(home_goals=hg, away_goals=ag)


class TestSettle:
    def test_home_win(self):
        assert settle_wc_pick(_vb("h2h", "home"), _m(2, 0)) is True

    def test_home_loss(self):
        assert settle_wc_pick(_vb("h2h", "home"), _m(0, 1)) is False

    def test_draw(self):
        assert settle_wc_pick(_vb("h2h", "draw"), _m(1, 1)) is True

    def test_away_win(self):
        assert settle_wc_pick(_vb("h2h", "away"), _m(0, 2)) is True

    def test_over_hits_at_three_goals(self):
        assert settle_wc_pick(_vb("totals", "over"), _m(2, 1)) is True

    def test_over_misses_at_two_goals(self):
        assert settle_wc_pick(_vb("totals", "over"), _m(1, 1)) is False

    def test_under_hits_at_two_goals(self):
        assert settle_wc_pick(_vb("totals", "under"), _m(1, 1)) is True

    def test_btts(self):
        assert settle_wc_pick(_vb("btts", "yes"), _m(1, 1)) is True
        assert settle_wc_pick(_vb("btts", "no"), _m(2, 0)) is True

    def test_missing_goals_returns_none(self):
        assert settle_wc_pick(_vb("h2h", "home"), _m(None, None)) is None

    def test_unknown_market_returns_none(self):
        assert settle_wc_pick(_vb("spreads", "x"), _m(1, 0)) is None


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def _patch(session, monkeypatch):
    @contextmanager
    def fake():
        yield session
    monkeypatch.setattr(sc, "get_session", fake)


def _seed_two_settled(s):
    s.add_all([
        WCTeam(id=1, name="A", fifa_code="AAA", confederation="UEFA", group_letter="A"),
        WCTeam(id=2, name="B", fifa_code="BBB", confederation="UEFA", group_letter="A"),
    ])
    for mid, (hg, ag) in [(1, (2, 0)), (2, (0, 1))]:
        s.add(WCMatch(id=mid, stage="group", group_letter="A", date="2026-06-20",
                      home_team_id=1, away_team_id=2, status="finished",
                      home_goals=hg, away_goals=ag))
        s.add(WCPrediction(id=100 + mid, match_id=mid, model_name=MODEL_NAME,
                           home_win_prob=0.6, draw_prob=0.25, away_win_prob=0.15,
                           home_expected_goals=1.6, away_expected_goals=0.8))
    # pick on home for both: match 1 wins @2.0 (+clv), match 2 loses @3.0 (-clv)
    s.add(WCValueBet(id=501, match_id=1, prediction_id=101, market_type="h2h",
                     selection="home", model_prob=0.6, best_odds=2.0,
                     implied_prob=0.5, edge=0.1, bookmaker="X", closing_odds=1.9, clv=0.05))
    s.add(WCValueBet(id=502, match_id=2, prediction_id=102, market_type="h2h",
                     selection="home", model_prob=0.55, best_odds=3.0,
                     implied_prob=0.33, edge=0.05, bookmaker="X", closing_odds=3.1, clv=-0.02))
    s.commit()


def test_empty_scorecard(session, monkeypatch):
    _patch(session, monkeypatch)
    assert compute_wc_scorecard() == {"n": 0}


def test_scorecard_aggregates(session, monkeypatch):
    _seed_two_settled(session)
    _patch(session, monkeypatch)
    out = compute_wc_scorecard()
    assert out["n"] == 2
    assert out["wins"] == 1
    assert out["hit_rate"] == 0.5
    # flat 1u: win @2.0 → +1.0, loss → -1.0 → net 0
    assert out["pnl_units"] == 0.0
    assert abs(out["mean_clv"] - 0.015) < 1e-9
    assert out["pct_positive_clv"] == 0.5
    assert out["calibration"]  # at least one band populated
