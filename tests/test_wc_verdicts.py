"""DF-04 — decision-first fixture verdicts.

The verdict classifier reuses the value finder's exact edge math + config
thresholds but KEEPS the two cases find_wc_value_bets discards: edges over the
actionable ceiling ("capped" → likely model noise) and sub-threshold fixtures
("none"). These tests pin the tiering, the value-over-capped precedence, and the
human label mapping. Mostly pure (no DB); one batch test seeds in-memory SQLite.
"""

from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.db import Base
import src.world_cup.value_finder as vf
from src.world_cup.value_finder import (
    WCFixtureVerdict, classify_fixture_verdict, wc_fixture_verdicts,
)
from src.world_cup.models import WCTeam, WCMatch, WCOdds, WCPrediction
from src.world_cup.predictor import MODEL_NAME

# Deterministic config so the tiers don't drift if the YAML thresholds change.
CFG = {"edge_threshold": 0.03, "max_actionable_edge": 0.15,
       "markets": ["h2h", "totals", "btts"]}
HOME, AWAY = "Brazil", "Scotland"


def mk_pred(home=0.40, draw=0.30, away=0.30, over=0.50, btts=0.50):
    return WCPrediction(
        model_name=MODEL_NAME, match_id=1,
        home_win_prob=home, draw_prob=draw, away_win_prob=away,
        home_expected_goals=1.4, away_expected_goals=1.1,
        over_25_prob=over, btts_prob=btts)


def mk_odds(market, sel, dec, point=None, book="Pinnacle"):
    return WCOdds(match_id=1, bookmaker=book, market_type=market,
                  selection=sel, odds_decimal=dec, point=point)


# ---------------------------------------------------------------- tiering

def test_value_tier():
    # home edge = .55 - 1/2.10 = .074, inside [.03, .15] and the largest → value.
    pred = mk_pred(home=0.55, draw=0.25, away=0.20, over=0.50)
    odds = [mk_odds("h2h", HOME, 2.10), mk_odds("h2h", "Draw", 4.0),
            mk_odds("h2h", AWAY, 4.5),
            mk_odds("totals", "Over", 1.90, 2.5), mk_odds("totals", "Under", 1.90, 2.5)]
    v = classify_fixture_verdict(pred, odds, HOME, AWAY, CFG)
    assert v.tier == "value"
    assert v.selection == "home" and v.label == HOME
    assert v.edge == pytest.approx(0.55 - 1 / 2.10, abs=1e-4)
    assert v.best_odds == 2.10 and v.bookmaker == "Pinnacle"
    assert v.model_prob == pytest.approx(0.55) and 0 < v.implied_prob < 1


def test_capped_tier_not_shown_as_value():
    # home edge = .80 - .25 = .55 > ceiling, and nothing else clears threshold.
    pred = mk_pred(home=0.80, draw=0.10, away=0.10, over=0.45)
    odds = [mk_odds("h2h", HOME, 4.0), mk_odds("h2h", "Draw", 8.0),
            mk_odds("h2h", AWAY, 8.0), mk_odds("totals", "Over", 1.90, 2.5)]
    v = classify_fixture_verdict(pred, odds, HOME, AWAY, CFG)
    assert v.tier == "capped"
    assert v.selection == "home"
    assert v.edge > CFG["max_actionable_edge"]


def test_none_tier_below_threshold():
    pred = mk_pred(home=0.40, draw=0.30, away=0.30, over=0.50)
    odds = [mk_odds("h2h", HOME, 2.0), mk_odds("h2h", "Draw", 3.0),
            mk_odds("h2h", AWAY, 3.0), mk_odds("totals", "Over", 1.90, 2.5)]
    v = classify_fixture_verdict(pred, odds, HOME, AWAY, CFG)
    assert v.tier == "none"
    assert v.selection is None and v.label is None and v.edge is None


def test_missing_pred_or_odds_is_none():
    assert classify_fixture_verdict(None, [mk_odds("h2h", HOME, 2.0)],
                                    HOME, AWAY, CFG).tier == "none"
    assert classify_fixture_verdict(mk_pred(), [], HOME, AWAY, CFG).tier == "none"


def test_value_takes_precedence_over_capped():
    # home is capped (edge .55) but Over 2.5 is a clean actionable value (.074):
    # the actionable bet is the headline, not the un-trustworthy capped one.
    pred = mk_pred(home=0.80, draw=0.10, away=0.10, over=0.55)
    odds = [mk_odds("h2h", HOME, 4.0), mk_odds("totals", "Over", 2.10, 2.5)]
    v = classify_fixture_verdict(pred, odds, HOME, AWAY, CFG)
    assert v.tier == "value" and v.selection == "over"


# ---------------------------------------------------------------- labels

def test_over_label():
    pred = mk_pred(home=0.30, draw=0.30, away=0.40, over=0.65)
    odds = [mk_odds("totals", "Over", 1.80, 2.5), mk_odds("h2h", AWAY, 2.7)]
    v = classify_fixture_verdict(pred, odds, HOME, AWAY, CFG)
    assert v.tier == "value" and v.selection == "over" and v.label == "Over 2.5"


def test_btts_label_when_market_enabled():
    pred = mk_pred(home=0.30, draw=0.30, away=0.40, btts=0.70)
    odds = [mk_odds("btts", "Yes", 1.70), mk_odds("btts", "No", 2.20)]
    v = classify_fixture_verdict(pred, odds, HOME, AWAY, CFG)
    assert v.tier == "value" and v.selection == "yes" and v.label == "BTTS Yes"


def test_away_label_uses_team_name():
    pred = mk_pred(home=0.20, draw=0.25, away=0.55)
    odds = [mk_odds("h2h", AWAY, 2.10), mk_odds("h2h", HOME, 6.0),
            mk_odds("h2h", "Draw", 5.0)]
    v = classify_fixture_verdict(pred, odds, HOME, AWAY, CFG)
    assert v.tier == "value" and v.selection == "away" and v.label == AWAY


def test_unsupported_market_ignored():
    # totals excluded from cfg → an over edge must not produce a verdict.
    cfg = {"edge_threshold": 0.03, "max_actionable_edge": 0.15, "markets": ["h2h"]}
    pred = mk_pred(home=0.30, draw=0.30, away=0.40, over=0.70)
    v = classify_fixture_verdict(pred, [mk_odds("totals", "Over", 1.80, 2.5)],
                                 HOME, AWAY, cfg)
    assert v.tier == "none"


# ---------------------------------------------------------------- batch (DB)

def test_wc_fixture_verdicts_batch(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    s.add_all([
        WCTeam(id=1, name="Brazil", fifa_code="BRA", confederation="C", group_letter="C"),
        WCTeam(id=2, name="Scotland", fifa_code="SCO", confederation="U", group_letter="C"),
    ])
    s.add(WCMatch(id=5, stage="group", group_letter="C", date="2026-06-25",
                  kickoff_time="18:00", home_team_id=1, away_team_id=2, status="scheduled"))
    s.add(WCPrediction(id=50, match_id=5, model_name=MODEL_NAME,
                       home_win_prob=0.55, draw_prob=0.25, away_win_prob=0.20,
                       home_expected_goals=1.8, away_expected_goals=0.7,
                       over_25_prob=0.50, btts_prob=0.50))
    s.add_all([
        WCOdds(match_id=5, bookmaker="Pinnacle", market_type="h2h", selection="Brazil", odds_decimal=2.10),
        WCOdds(match_id=5, bookmaker="Pinnacle", market_type="h2h", selection="Draw", odds_decimal=4.0),
        WCOdds(match_id=5, bookmaker="Pinnacle", market_type="h2h", selection="Scotland", odds_decimal=4.5),
    ])
    s.commit()

    @contextmanager
    def fake():
        yield s
    monkeypatch.setattr(vf, "get_session", fake)
    monkeypatch.setattr(vf, "_load_betting_config", lambda: CFG)

    out = wc_fixture_verdicts()
    assert set(out) == {5}
    assert isinstance(out[5], WCFixtureVerdict)
    assert out[5].tier == "value" and out[5].selection == "home"

    # match_ids filter restricts the scan
    assert wc_fixture_verdicts(match_ids=[999]) == {}
