"""WC-09-03 — research data layer (best price, consensus, edge, line movement)."""

from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.db import Base
import src.world_cup.research as research
from src.world_cup.research import (
    build_research_card, top_disagreements, _devig, _consensus,
)
from src.world_cup.models import WCTeam, WCMatch, WCOdds, WCPrediction
from src.world_cup.predictor import MODEL_NAME


def test_devig_sums_to_one():
    out = _devig({"home": 0.5, "draw": 0.3, "away": 0.3})  # overround 1.1
    assert abs(sum(out.values()) - 1.0) < 1e-9


def test_consensus_incomplete_market_returns_none():
    # only 'home' present, missing draw/away → can't de-vig
    data = {"home": {"cur": [1.5], "open": [], "best": (1.5, "X")}}
    cur, opn = _consensus(data, ["home", "draw", "away"])
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

    by = {x["selection"]: x for x in card["selections"]}
    # 3 h2h + 2 totals@2.5 (the seed prices no other line)
    assert len(card["selections"]) == 5

    home = by["home"]
    assert home["model_prob"] == 0.70
    assert home["best_odds"] == 1.32 and home["best_book"] == "FanDuel"  # best price
    assert 0 < home["market_prob"] < 1
    assert home["edge"] == pytest.approx(0.70 - home["market_prob"])
    # market shortened on Brazil since open → current implied prob higher → +ve movement
    assert home["movement"] is not None and home["movement"] > 0

    # h2h consensus de-vigs to ~1
    h2h_probs = sum(by[s]["market_prob"] for s in ("home", "draw", "away"))
    assert abs(h2h_probs - 1.0) < 1e-9

    over = by["over_2.5"]
    assert over["model_prob"] == 0.55      # straight from the stored over_25_prob
    assert over["best_odds"] == 1.90


def test_missing_match_returns_none(session, monkeypatch):
    _patch(session, monkeypatch)
    assert build_research_card(99999) is None


def test_top_disagreements_sorted(session, monkeypatch):
    _seed(session)
    _patch(session, monkeypatch)
    dq = top_disagreements(limit=10)
    assert len(dq) == 5  # 3 h2h + 2 totals on the one upcoming match
    edges = [abs(d["edge"]) for d in dq]
    assert edges == sorted(edges, reverse=True)  # sorted by |edge| desc
    assert all("match" in d and "selection" in d for d in dq)


def test_top_disagreements_respects_limit(session, monkeypatch):
    _seed(session)
    _patch(session, monkeypatch)
    assert len(top_disagreements(limit=2)) == 2


# ---- DF-01: expanded markets (1X2 + O/U 1.5/2.5/3.5 + BTTS) ----

def _seed_multiline(s):
    s.add_all([
        WCTeam(id=1, name="Brazil", fifa_code="BRA", confederation="CONMEBOL", group_letter="C"),
        WCTeam(id=2, name="Scotland", fifa_code="SCO", confederation="UEFA", group_letter="C"),
    ])
    s.add(WCMatch(id=21, stage="group", group_letter="C", date="2026-06-25",
                  kickoff_time="18:00", home_team_id=1, away_team_id=2, status="scheduled"))
    s.add(WCPrediction(id=210, match_id=21, model_name=MODEL_NAME,
                       home_win_prob=0.55, draw_prob=0.25, away_win_prob=0.20,
                       home_expected_goals=1.7, away_expected_goals=1.1,
                       over_25_prob=0.52, btts_prob=0.55))

    def ou(book, sel, dec, pt, mtype="alternate_totals"):
        # Match production: the loader bakes the line into alternate_totals
        # selections ("Over 1.5") so multiple lines persist under the unique key.
        stored = f"{sel} {pt}" if mtype == "alternate_totals" else sel
        return WCOdds(match_id=21, bookmaker=book, market_type=mtype, selection=stored,
                      odds_decimal=dec, opening_odds=dec, point=pt, captured_at="2026-06-25T08:00")

    s.add_all([
        ou("Pinnacle", "Over", 1.20, 1.5), ou("Pinnacle", "Under", 4.50, 1.5),
        ou("Pinnacle", "Over", 1.95, 2.5, "totals"), ou("Pinnacle", "Under", 1.90, 2.5, "totals"),
        ou("Pinnacle", "Over", 3.20, 3.5), ou("Pinnacle", "Under", 1.35, 3.5),
        WCOdds(match_id=21, bookmaker="Pinnacle", market_type="btts", selection="Yes",
               odds_decimal=1.90, opening_odds=1.90, point=None, captured_at="2026-06-25T08:00"),
        WCOdds(match_id=21, bookmaker="Pinnacle", market_type="btts", selection="No",
               odds_decimal=1.90, opening_odds=1.90, point=None, captured_at="2026-06-25T08:00"),
    ])
    s.commit()


def test_research_card_multiline_markets(session, monkeypatch):
    _seed_multiline(session)
    _patch(session, monkeypatch)
    by = {x["selection"]: x for x in build_research_card(21)["selections"]}
    for sel in ("over_1.5", "under_1.5", "over_2.5", "under_2.5",
                "over_3.5", "under_3.5", "btts_yes", "btts_no"):
        assert sel in by, f"missing {sel}"
    # Each O/U line de-vigs INDEPENDENTLY to ~1 (the core DF-01 fix)
    for o, u in (("over_1.5", "under_1.5"), ("over_2.5", "under_2.5"), ("over_3.5", "under_3.5")):
        assert abs(by[o]["market_prob"] + by[u]["market_prob"] - 1.0) < 1e-9
    # Model O/U lines monotone decreasing (more goals = less likely)
    assert by["over_1.5"]["model_prob"] > by["over_2.5"]["model_prob"] > by["over_3.5"]["model_prob"]
    assert by["over_2.5"]["model_prob"] == 0.52    # stored value, not re-derived
    assert by["btts_yes"]["model_prob"] == 0.55    # stored BTTS


def test_totals_and_alternate_totals_merge(session, monkeypatch):
    # over@2.5 quoted under BOTH `totals` and `alternate_totals` pools into one line
    _seed_multiline(session)
    session.add(WCOdds(match_id=21, bookmaker="FanDuel", market_type="alternate_totals",
                       selection="Over", odds_decimal=2.50, opening_odds=2.50, point=2.5,
                       captured_at="2026-06-25T08:00"))
    session.commit()
    _patch(session, monkeypatch)
    by = {x["selection"]: x for x in build_research_card(21)["selections"]}
    # FanDuel's 2.50 (from alternate_totals) is the best Over 2.5 price across both
    assert by["over_2.5"]["best_odds"] == 2.50 and by["over_2.5"]["best_book"] == "FanDuel"


def test_derive_markets_from_lambdas_helper():
    from src.world_cup.predictor import derive_markets_from_lambdas
    m = derive_markets_from_lambdas(1.6, 1.1)
    assert m["over_15"] > m["over_25"] > m["over_35"]      # monotone
    assert 0 < m["btts"] < 1
    assert derive_markets_from_lambdas(None, 1.0) == {}    # graceful on missing input
