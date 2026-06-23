"""WC-09-03 — research data layer (best price, consensus, edge, line movement)."""

from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.db import Base
import src.world_cup.research as research
from src.world_cup.research import build_research_card, _devig, _consensus
from src.world_cup.models import WCTeam, WCMatch, WCOdds, WCPrediction
from src.world_cup.predictor import MODEL_NAME


def test_devig_sums_to_one():
    out = _devig({"home": 0.5, "draw": 0.3, "away": 0.3})  # overround 1.1
    assert abs(sum(out.values()) - 1.0) < 1e-9


def test_consensus_incomplete_market_returns_none():
    # only 'home' present, missing draw/away → can't de-vig
    data = {("h2h", "home"): {"cur": [1.5], "open": [], "best": (1.5, "X")}}
    cur, opn = _consensus(data, "h2h", ["home", "draw", "away"])
    assert cur is None and opn is None


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
    monkeypatch.setattr(research, "get_session", fake)


def _seed(s):
    s.add_all([
        WCTeam(id=1, name="Brazil", fifa_code="BRA", confederation="CONMEBOL", group_letter="C"),
        WCTeam(id=2, name="Scotland", fifa_code="SCO", confederation="UEFA", group_letter="C"),
    ])
    s.add(WCMatch(id=20, stage="group", group_letter="C", date="2026-06-25",
                  kickoff_time="18:00", home_team_id=1, away_team_id=2, status="scheduled"))
    s.add(WCPrediction(id=200, match_id=20, model_name=MODEL_NAME,
                       home_win_prob=0.70, draw_prob=0.20, away_win_prob=0.10,
                       home_expected_goals=2.2, away_expected_goals=0.6, over_25_prob=0.55))
    # h2h, two books, with opening != current (market shortened on Brazil)
    def odd(book, sel, cur, opn, pt=None):
        return WCOdds(match_id=20, bookmaker=book, market_type="h2h" if pt is None else "totals",
                      selection=sel, odds_decimal=cur, opening_odds=opn, point=pt,
                      captured_at="2026-06-25T08:00")
    s.add_all([
        odd("Pinnacle", "Brazil", 1.30, 1.45),
        odd("FanDuel", "Brazil", 1.32, 1.42),
        odd("Pinnacle", "Draw", 5.0, 4.5),
        odd("FanDuel", "Draw", 5.2, 4.7),
        odd("Pinnacle", "Scotland", 10.0, 9.0),
        odd("FanDuel", "Scotland", 10.5, 9.5),
        WCOdds(match_id=20, bookmaker="Pinnacle", market_type="totals", selection="Over",
               odds_decimal=1.90, opening_odds=1.85, point=2.5, captured_at="2026-06-25T08:00"),
        WCOdds(match_id=20, bookmaker="Pinnacle", market_type="totals", selection="Under",
               odds_decimal=1.90, opening_odds=1.95, point=2.5, captured_at="2026-06-25T08:00"),
    ])
    s.commit()


def test_build_research_card(session, monkeypatch):
    _seed(session)
    _patch(session, monkeypatch)
    card = build_research_card(20)
    assert card["home"] == "Brazil" and card["away"] == "Scotland"
    assert card["home_fifa"] == "BRA"

    by = {(x["market"], x["selection"]): x for x in card["selections"]}
    # 3 h2h + 2 totals
    assert len(card["selections"]) == 5

    home = by[("h2h", "home")]
    assert home["model_prob"] == 0.70
    assert home["best_odds"] == 1.32 and home["best_book"] == "FanDuel"  # best price
    assert 0 < home["market_prob"] < 1
    assert home["edge"] == pytest.approx(0.70 - home["market_prob"])
    # market shortened on Brazil since open → current implied prob higher → +ve movement
    assert home["movement"] is not None and home["movement"] > 0

    # h2h consensus de-vigs to ~1
    h2h_probs = sum(by[("h2h", s)]["market_prob"] for s in ("home", "draw", "away"))
    assert abs(h2h_probs - 1.0) < 1e-9

    over = by[("totals", "over")]
    assert over["model_prob"] == 0.55
    assert over["best_odds"] == 1.90


def test_missing_match_returns_none(session, monkeypatch):
    _patch(session, monkeypatch)
    assert build_research_card(99999) is None
