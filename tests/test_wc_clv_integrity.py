"""
WC-10-05 — CLV integrity end-to-end.

Proves the prematch → finish → CLV path: because odds are upserted in place, the
closing line a finished match yields is the **near-closing** price the pre-kickoff
focused pull wrote (WC-10-04), not the stale morning board price. Uses the real
`_load_odds_to_db` upsert for both the morning and the prematch refresh.
"""

from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker

from src.database.db import Base
import src.world_cup.value_finder as vf
import src.world_cup.scraper as scraper
from src.world_cup.models import WCTeam, WCMatch, WCOdds, WCPrediction, WCValueBet
from src.world_cup.predictor import MODEL_NAME


def _event(home, away, home_price):
    """A minimal Odds API event with a single book quoting the home price."""
    return {"home_team": home, "away_team": away, "bookmakers": [
        {"title": "Pinnacle", "markets": [{"key": "h2h", "outcomes": [
            {"name": home, "price": home_price},
            {"name": away, "price": 6.0},
            {"name": "Draw", "price": 4.0}]}]}]}


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def test_prematch_to_finish_clv_uses_near_closing_line(session, monkeypatch):
    s = session
    s.add_all([
        WCTeam(id=1, name="Brazil", fifa_code="BRA", confederation="C", group_letter="A"),
        WCTeam(id=2, name="Scotland", fifa_code="SCO", confederation="U", group_letter="A"),
    ])
    s.add(WCMatch(id=13, stage="group", group_letter="A", date="2026-06-25",
                  kickoff_time="18:00", home_team_id=1, away_team_id=2, status="scheduled"))
    s.add(WCPrediction(id=130, match_id=13, model_name=MODEL_NAME, home_win_prob=0.6,
                       draw_prob=0.25, away_win_prob=0.15,
                       home_expected_goals=1.8, away_expected_goals=0.7))
    # shadow pick taken at the morning entry price 1.70 on the home team
    s.add(WCValueBet(id=1, match_id=13, prediction_id=130, market_type="h2h", selection="home",
                     model_prob=0.6, best_odds=1.70, implied_prob=0.588, edge=0.012,
                     bookmaker="DraftKings"))
    s.commit()

    @contextmanager
    def fake():
        yield s

    monkeypatch.setattr(scraper, "get_session", fake)
    monkeypatch.setattr(vf, "get_session", fake)
    monkeypatch.setattr(scraper, "_normalize_team_name", lambda n: n)

    # Morning board pull stores the home line at 2.00 ...
    scraper._load_odds_to_db([_event("Brazil", "Scotland", 2.00)])
    # ... then the pre-kickoff focused pull UPSERTS the near-closing line (market shortened to 1.50)
    scraper._load_odds_to_db([_event("Brazil", "Scotland", 1.50)])

    # upsert, not append — exactly one home-odds row survives the two pulls
    n_rows = s.execute(
        select(func.count()).select_from(WCOdds)
        .where(WCOdds.match_id == 13, WCOdds.selection == "Brazil", WCOdds.market_type == "h2h")
    ).scalar()
    assert n_rows == 1

    # Match finishes → capture the closing line + CLV
    m = s.get(WCMatch, 13)
    m.status, m.home_goals, m.away_goals = "finished", 2, 0
    s.commit()
    out = vf.capture_wc_closing_lines()

    assert out["captured"] == 1
    vb = s.get(WCValueBet, 1)
    assert vb.closing_odds == 1.50                     # the PREMATCH near-closing line, not 2.00 morning
    assert abs(vb.clv - ((1 / 1.50) - (1 / 1.70))) < 1e-6
    assert vb.clv > 0                                  # entry 1.70 beat the 1.50 close → +CLV


def test_closing_line_tracks_the_latest_upsert(session, monkeypatch):
    """The captured close is the LATEST prematch write, even when that's a SHORTER
    price than an earlier pull — this discriminates 'latest write wins' from the
    weaker 'highest price wins' (the upsert replaces in place, it doesn't append)."""
    s = session
    s.add_all([
        WCTeam(id=1, name="Brazil", fifa_code="BRA", confederation="C", group_letter="A"),
        WCTeam(id=2, name="Scotland", fifa_code="SCO", confederation="U", group_letter="A"),
    ])
    s.add(WCMatch(id=13, stage="group", group_letter="A", date="2026-06-25",
                  kickoff_time="18:00", home_team_id=1, away_team_id=2,
                  status="finished", home_goals=2, away_goals=0))
    s.add(WCPrediction(id=130, match_id=13, model_name=MODEL_NAME, home_win_prob=0.6,
                       draw_prob=0.25, away_win_prob=0.15,
                       home_expected_goals=1.8, away_expected_goals=0.7))
    s.add(WCValueBet(id=1, match_id=13, prediction_id=130, market_type="h2h", selection="home",
                     model_prob=0.6, best_odds=1.70, implied_prob=0.588, edge=0.012, bookmaker="X"))
    s.commit()

    @contextmanager
    def fake():
        yield s

    monkeypatch.setattr(scraper, "get_session", fake)
    monkeypatch.setattr(vf, "get_session", fake)
    monkeypatch.setattr(scraper, "_normalize_team_name", lambda n: n)

    scraper._load_odds_to_db([_event("Brazil", "Scotland", 1.90)])   # earlier (longer price)
    scraper._load_odds_to_db([_event("Brazil", "Scotland", 1.50)])   # later prematch — line shortened
    vf.capture_wc_closing_lines()
    assert s.get(WCValueBet, 1).closing_odds == 1.50                 # latest write, NOT the higher 1.90
