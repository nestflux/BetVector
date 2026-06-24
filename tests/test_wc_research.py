"""WC-09-03 — research data layer (best price, consensus, edge, line movement)."""

from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.db import Base
import src.world_cup.research as research
from src.world_cup.research import (
    build_research_card, top_disagreements, _devig, _consensus,
    summarize_card,
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


# ---- DF-06: digestible card — market blocks, model-vs-market reads, headline ----

def _row(mk, sel, label, model, mkt, best_odds=None, best_book=None, move=None):
    """A build_research_card selection row (edge = model − de-vigged market)."""
    edge = (model - mkt) if (model is not None and mkt is not None) else None
    return {"market": mk, "selection": sel, "label": label,
            "model_prob": model, "market_prob": mkt, "edge": edge,
            "best_odds": best_odds, "best_book": best_book, "movement": move}


def _card(home, away, rows):
    return {"home": home, "away": away, "selections": rows}


def test_edge_trust_boundaries():
    # Same bounds the value finder stakes on: [0.03, 0.15].
    assert research._edge_trust(None, 0.03, 0.15) == "na"
    assert research._edge_trust(0.029, 0.03, 0.15) == "none"
    assert research._edge_trust(0.03, 0.03, 0.15) == "value"     # threshold inclusive
    assert research._edge_trust(0.15, 0.03, 0.15) == "value"     # ceiling inclusive
    assert research._edge_trust(0.1501, 0.03, 0.15) == "capped"  # past ceiling
    assert research._edge_trust(-0.2, 0.03, 0.15) == "none"      # model below market


def test_summarize_groups_into_three_blocks_with_trust():
    card = _card("Brazil", "Scotland", [
        _row("h2h", "home", "Home (Brazil)", 0.55, 0.47, 2.05, "FanDuel"),  # +.08 value
        _row("h2h", "draw", "Draw", 0.25, 0.27),                            # −.02 none
        _row("h2h", "away", "Away (Scotland)", 0.20, 0.26),                 # −.06 none
        _row("ou25", "over_2.5", "Over 2.5", 0.52, 0.50),                   # +.02 none
        _row("ou25", "under_2.5", "Under 2.5", 0.48, 0.50),
        _row("btts", "btts_yes", "BTTS Yes", 0.70, 0.48),                   # +.22 capped
        _row("btts", "btts_no", "BTTS No", 0.30, 0.52),
    ])
    s = summarize_card(card)
    assert [b["title"] for b in s["blocks"]] == \
        ["Match result", "Goals", "Both teams to score"]
    by = {r["selection"]: r for b in s["blocks"] for r in b["selections"]}
    assert by["home"]["trust"] == "value"
    assert by["btts_yes"]["trust"] == "capped"
    assert by["over_2.5"]["trust"] == "none"


def test_summarize_omits_empty_blocks():
    # Only h2h priced → only the Match result block appears.
    card = _card("A", "B", [
        _row("h2h", "home", "Home (A)", 0.50, 0.45),
        _row("h2h", "draw", "Draw", 0.27, 0.28),
        _row("h2h", "away", "Away (B)", 0.23, 0.27),
    ])
    s = summarize_card(card)
    assert [b["title"] for b in s["blocks"]] == ["Match result"]


def test_headline_prefers_trustworthy_lean_over_bigger_capped_gap():
    # +.08 value (h2h) vs +.22 capped (btts) → the value lean is the headline.
    card = _card("Brazil", "Scotland", [
        _row("h2h", "home", "Home (Brazil)", 0.55, 0.47, 2.05, "FanDuel"),
        _row("h2h", "draw", "Draw", 0.25, 0.27),
        _row("h2h", "away", "Away (Scotland)", 0.20, 0.26),
        _row("btts", "btts_yes", "BTTS Yes", 0.70, 0.48),
        _row("btts", "btts_no", "BTTS No", 0.30, 0.52),
    ])
    h = summarize_card(card)["headline"]
    assert h["class"] == "value" and h["selection"] == "home"
    assert "Brazil" in h["text"] and "Match result" in h["text"]
    assert "@ 2.05 (FanDuel)" in h["text"]


def test_headline_capped_when_only_oversized_gap():
    card = _card("A", "B", [
        _row("btts", "btts_yes", "BTTS Yes", 0.80, 0.50),   # +.30 capped
        _row("btts", "btts_no", "BTTS No", 0.20, 0.50),
    ])
    h = summarize_card(card)["headline"]
    assert h["class"] == "capped"
    assert "likely model error" in h["text"]


def test_headline_none_when_model_agrees():
    card = _card("A", "B", [
        _row("h2h", "home", "Home (A)", 0.50, 0.49),
        _row("h2h", "draw", "Draw", 0.25, 0.26),
        _row("h2h", "away", "Away (B)", 0.25, 0.25),
    ])
    h = summarize_card(card)["headline"]
    assert h["class"] == "none"
    assert "agrees with the market" in h["text"]


def test_block_read_names_where_the_edge_is():
    card = _card("Brazil", "Scotland", [
        _row("h2h", "home", "Home (Brazil)", 0.55, 0.47, 2.05),
        _row("h2h", "draw", "Draw", 0.25, 0.27),
        _row("h2h", "away", "Away (Scotland)", 0.20, 0.26),
    ])
    read = summarize_card(card)["blocks"][0]["read"]
    assert read["class"] == "value"
    assert "Brazil" in read["text"] and "55%" in read["text"]


def test_block_read_capped_is_flagged_not_celebrated():
    card = _card("A", "B", [
        _row("btts", "btts_yes", "BTTS Yes", 0.80, 0.50),
        _row("btts", "btts_no", "BTTS No", 0.20, 0.50),
    ])
    read = summarize_card(card)["blocks"][0]["read"]
    assert read["class"] == "capped"
    assert "model error" in read["text"]


def test_headline_handles_no_prices():
    s = summarize_card(_card("A", "B", []))
    assert s["blocks"] == []
    assert s["headline"]["class"] == "na"


def test_build_research_card_attaches_blocks_and_headline(session, monkeypatch):
    _seed(session)
    _patch(session, monkeypatch)
    card = build_research_card(20)
    assert "blocks" in card and "headline" in card
    assert "Match result" in [b["title"] for b in card["blocks"]]
    assert all("trust" in r for r in card["selections"])
    # Seed: Over 2.5 model 0.55 vs de-vigged market 0.50 → +0.05 edge (value),
    # the only selection clearing the threshold → it's the headline lean.
    h = card["headline"]
    assert h["class"] == "value" and h["selection"] == "over_2.5"
    assert "Goals" in h["text"]
