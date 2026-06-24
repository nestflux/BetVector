"""WC-09-03 — research data layer (best price, consensus, edge, line movement)."""

from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.db import Base
import src.world_cup.research as research
from src.world_cup.research import (
    build_research_card, top_disagreements, _devig, _consensus,
    summarize_card, build_disagreements, build_book_comparison, build_movement,
    build_group_context, build_model_comparison, _qual_status,
)
from src.world_cup.models import WCTeam, WCMatch, WCOdds, WCPrediction, WCValueBet
from src.world_cup.predictor import MODEL_NAME
from src.world_cup.bayesian_model import MODEL_NAME_BAYES


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


# ---- DF-07: curated disagreements queue (verdict-tagged, ranked sentences) ----

def _seed_disagreements(s):
    """Alpha v Beta with even prices so the de-vigged market is exactly 50/50 per
    two-way market and the h2h de-vigs in line with the model:
      • h2h    — model == market → no disagreement (filtered)
      • O/U2.5 — model Under 0.60 vs market 0.50 → +0.10 conviction (value)
      • BTTS   — model Yes 0.70 vs market 0.50 → +0.20 likely model error (capped)
    """
    s.add_all([
        WCTeam(id=1, name="Alpha", fifa_code="ALP", confederation="UEFA", group_letter="A"),
        WCTeam(id=2, name="Beta", fifa_code="BET", confederation="UEFA", group_letter="A"),
    ])
    s.add(WCMatch(id=30, stage="group", group_letter="A", date="2026-06-28",
                  kickoff_time="18:00", home_team_id=1, away_team_id=2, status="scheduled"))
    s.add(WCPrediction(id=300, match_id=30, model_name=MODEL_NAME,
                       home_win_prob=0.40, draw_prob=0.30, away_win_prob=0.30,
                       home_expected_goals=1.0, away_expected_goals=1.0,
                       over_25_prob=0.40, btts_prob=0.70))

    def o(mtype, sel, dec, pt=None):
        return WCOdds(match_id=30, bookmaker="Pinnacle", market_type=mtype, selection=sel,
                      odds_decimal=dec, opening_odds=dec, point=pt,
                      captured_at="2026-06-28T08:00")
    s.add_all([
        o("h2h", "Alpha", 2.50), o("h2h", "Draw", 3.3333), o("h2h", "Beta", 3.3333),
        o("totals", "Over", 2.00, 2.5), o("totals", "Under", 2.00, 2.5),
        o("btts", "Yes", 2.00), o("btts", "No", 2.00),
    ])
    s.commit()


def test_build_disagreements_collapses_tags_and_ranks(session, monkeypatch):
    _seed_disagreements(session)
    _patch(session, monkeypatch)
    dq = build_disagreements(limit=10)
    # Collapsed to the model-favoured side: Under 2.5 + BTTS Yes only — NOT the
    # mirror Over/No, and NOT h2h (model in line with the market).
    assert [d["selection"] for d in dq] == ["under_2.5", "btts_yes"]
    under, btts = dq
    assert under["trust"] == "value" and under["edge"] == pytest.approx(0.10)
    assert under["label"] == "Under 2.5" and under["best_odds"] == 2.00
    assert btts["trust"] == "capped" and btts["edge"] == pytest.approx(0.20)
    # The trustworthy conviction ranks ABOVE the bigger but untrustworthy gap.
    assert under["edge"] < btts["edge"]
    assert dq.index(under) < dq.index(btts)


def test_build_disagreements_sentences(session, monkeypatch):
    _seed_disagreements(session)
    _patch(session, monkeypatch)
    by = {d["selection"]: d for d in build_disagreements()}
    assert by["under_2.5"]["text"] == (
        "Back Under 2.5 in Alpha v Beta — model 60% vs market 50%, "
        "best price 2.00 (Pinnacle).")
    assert by["btts_yes"]["text"] == (
        "Alpha v Beta: model rates BTTS Yes 70% vs market 50% — past the trust "
        "ceiling, likely model error.")


def test_build_disagreements_respects_limit(session, monkeypatch):
    _seed_disagreements(session)
    _patch(session, monkeypatch)
    dq = build_disagreements(limit=1)
    assert len(dq) == 1 and dq[0]["selection"] == "under_2.5"   # conviction leads


def test_build_disagreements_empty_without_predictions(session, monkeypatch):
    # Odds but no prediction → nothing for the model to disagree with.
    session.add_all([
        WCTeam(id=1, name="Alpha", fifa_code="ALP", confederation="UEFA", group_letter="A"),
        WCTeam(id=2, name="Beta", fifa_code="BET", confederation="UEFA", group_letter="A"),
    ])
    session.add(WCMatch(id=31, stage="group", group_letter="A", date="2026-06-28",
                        kickoff_time="18:00", home_team_id=1, away_team_id=2, status="scheduled"))
    session.add_all([
        WCOdds(match_id=31, bookmaker="Pinnacle", market_type="totals", selection="Over",
               odds_decimal=2.0, opening_odds=2.0, point=2.5, captured_at="2026-06-28T08:00"),
        WCOdds(match_id=31, bookmaker="Pinnacle", market_type="totals", selection="Under",
               odds_decimal=2.0, opening_odds=2.0, point=2.5, captured_at="2026-06-28T08:00"),
    ])
    session.commit()
    _patch(session, monkeypatch)
    assert build_disagreements() == []


def test_build_disagreements_skips_in_line_markets(session, monkeypatch):
    # Model exactly matches the de-vigged market → no disagreement surfaces.
    session.add_all([
        WCTeam(id=1, name="Alpha", fifa_code="ALP", confederation="UEFA", group_letter="A"),
        WCTeam(id=2, name="Beta", fifa_code="BET", confederation="UEFA", group_letter="A"),
    ])
    session.add(WCMatch(id=32, stage="group", group_letter="A", date="2026-06-28",
                        kickoff_time="18:00", home_team_id=1, away_team_id=2, status="scheduled"))
    session.add(WCPrediction(id=320, match_id=32, model_name=MODEL_NAME,
                             home_win_prob=0.40, draw_prob=0.30, away_win_prob=0.30,
                             home_expected_goals=1.0, away_expected_goals=1.0,
                             over_25_prob=0.50, btts_prob=0.50))
    session.add_all([
        WCOdds(match_id=32, bookmaker="Pinnacle", market_type="totals", selection="Over",
               odds_decimal=2.0, opening_odds=2.0, point=2.5, captured_at="2026-06-28T08:00"),
        WCOdds(match_id=32, bookmaker="Pinnacle", market_type="totals", selection="Under",
               odds_decimal=2.0, opening_odds=2.0, point=2.5, captured_at="2026-06-28T08:00"),
    ])
    session.commit()
    _patch(session, monkeypatch)
    assert build_disagreements() == []


# ---- DF-08: scoreline matrix helper + model-vs-every-book comparison ----

def test_scoreline_matrix_from_lambdas():
    import numpy as np
    from src.world_cup.predictor import scoreline_matrix_from_lambdas

    mtx = scoreline_matrix_from_lambdas(2.2, 0.6)
    assert len(mtx) == 7 and all(len(r) == 7 for r in mtx)          # 7x7 grid
    assert abs(sum(sum(r) for r in mtx) - 1.0) < 1e-9               # a distribution
    # matrix[h][a] = P(home h, away a): a home-heavy lambda peaks with home > away.
    h, a = np.unravel_index(np.argmax(np.array(mtx)), (7, 7))
    assert h > a
    assert scoreline_matrix_from_lambdas(None, 1.0) == []           # graceful on missing


def test_build_book_comparison_basic(session, monkeypatch):
    # Seed = match 20: h2h on TWO books (Pinnacle + FanDuel), O/U 2.5 on ONE.
    _seed(session)
    _patch(session, monkeypatch)
    comp = build_book_comparison(20)

    assert comp["home"] == "Brazil" and comp["away"] == "Scotland"
    assert comp["has_prediction"] is True
    assert comp["lambda_home"] == 2.2 and comp["lambda_away"] == 0.6

    markets = {mk["key"]: mk for mk in comp["markets"]}
    # Only the priced markets appear — no empty O/U 1.5 / 3.5 / BTTS blocks.
    assert set(markets) == {"h2h", "ou25"}

    h2h = markets["h2h"]
    assert h2h["n_books"] == 2                                      # both books quote 1X2
    assert {b["book"] for b in h2h["books"]} == {"Pinnacle", "FanDuel"}
    assert h2h["model"]["home"] == 0.70
    for b in h2h["books"]:                                          # each book de-vigs to 1
        assert abs(sum(b["probs"].values()) - 1.0) < 1e-9

    ou25 = markets["ou25"]
    assert ou25["n_books"] == 1                                     # only Pinnacle priced O/U 2.5
    assert ou25["model"]["over_2.5"] == 0.55
    # Even 1.90/1.90 → de-vigged consensus is 50/50; model 0.55 → +0.05 value edge.
    book = ou25["books"][0]
    assert book["probs"]["over_2.5"] == pytest.approx(0.50)
    assert book["edges"]["over_2.5"] == pytest.approx(0.05)
    assert book["trust"]["over_2.5"] == "value"
    assert ou25["best"]["over_2.5"]["odds"] == 1.90                 # best price cue


def test_build_book_comparison_ranks_softest_book_first(session, monkeypatch):
    # Two books on h2h; FanDuel is longer on Brazil (the model's pick), so it is
    # the softest line — it must sort first (largest model edge).
    _seed(session)
    _patch(session, monkeypatch)
    h2h = {mk["key"]: mk for mk in build_book_comparison(20)["markets"]}["h2h"]
    # FanDuel Brazil 1.32 > Pinnacle 1.30 → lower implied → larger model edge on home.
    assert h2h["books"][0]["book"] == "FanDuel"
    assert h2h["books"][0]["best_edge"] >= h2h["books"][1]["best_edge"]


def test_build_book_comparison_no_prediction(session, monkeypatch):
    # Odds present but no model prediction → books still compared, model side blank.
    session.add_all([
        WCTeam(id=1, name="Alpha", fifa_code="ALP", confederation="UEFA", group_letter="A"),
        WCTeam(id=2, name="Beta", fifa_code="BET", confederation="UEFA", group_letter="A"),
    ])
    session.add(WCMatch(id=40, stage="group", group_letter="A", date="2026-06-28",
                        kickoff_time="18:00", home_team_id=1, away_team_id=2, status="scheduled"))
    session.add_all([
        WCOdds(match_id=40, bookmaker="Pinnacle", market_type="totals", selection="Over",
               odds_decimal=2.0, opening_odds=2.0, point=2.5, captured_at="2026-06-28T08:00"),
        WCOdds(match_id=40, bookmaker="Pinnacle", market_type="totals", selection="Under",
               odds_decimal=2.0, opening_odds=2.0, point=2.5, captured_at="2026-06-28T08:00"),
    ])
    session.commit()
    _patch(session, monkeypatch)
    comp = build_book_comparison(40)
    assert comp["has_prediction"] is False
    assert comp["lambda_home"] is None
    ou25 = {mk["key"]: mk for mk in comp["markets"]}["ou25"]
    assert ou25["model"]["over_2.5"] is None
    assert ou25["n_books"] == 1
    assert ou25["books"][0]["edges"]["over_2.5"] is None            # no model → no edge
    assert ou25["books"][0]["trust"]["over_2.5"] == "na"


def test_build_book_comparison_missing_match(session, monkeypatch):
    _patch(session, monkeypatch)
    assert build_book_comparison(99999) is None


# ---- DF-09: line movement for backable selections (the CLV story) ----

def _seed_movement(s):
    """Match 50 with TWO backable selections (shadow value bets) and odds that have
    moved since open, on a best-available-across-books basis:
      • Brazil to win — best open 1.80, best current 1.70 (shortened), entry 1.75,
        close 1.65 → we beat the close (clv +0.034).
      • Over 2.5      — open 1.85, current 1.95 (drifted out), entry 1.90,
        close 1.92 → close longer than entry, we did NOT beat it (clv −0.006).
    """
    s.add_all([
        WCTeam(id=1, name="Brazil", fifa_code="BRA", confederation="CONMEBOL", group_letter="C"),
        WCTeam(id=2, name="Scotland", fifa_code="SCO", confederation="UEFA", group_letter="C"),
    ])
    s.add(WCMatch(id=50, stage="group", group_letter="C", date="2026-06-25",
                  kickoff_time="18:00", home_team_id=1, away_team_id=2, status="scheduled"))
    s.add(WCPrediction(id=500, match_id=50, model_name=MODEL_NAME,
                       home_win_prob=0.62, draw_prob=0.22, away_win_prob=0.16,
                       home_expected_goals=2.0, away_expected_goals=0.7, over_25_prob=0.55))
    s.add_all([
        WCOdds(match_id=50, bookmaker="Pinnacle", market_type="h2h", selection="Brazil",
               odds_decimal=1.68, opening_odds=1.80, captured_at="2026-06-25T08:00"),
        WCOdds(match_id=50, bookmaker="FanDuel", market_type="h2h", selection="Brazil",
               odds_decimal=1.70, opening_odds=1.78, captured_at="2026-06-25T08:00"),
        WCOdds(match_id=50, bookmaker="Pinnacle", market_type="totals", selection="Over",
               odds_decimal=1.95, opening_odds=1.85, point=2.5, captured_at="2026-06-25T08:00"),
    ])
    s.add_all([
        WCValueBet(match_id=50, prediction_id=500, market_type="h2h", selection="home",
                   model_prob=0.62, best_odds=1.75, implied_prob=0.571, edge=0.05,
                   bookmaker="FanDuel", closing_odds=1.65, clv=0.034),
        WCValueBet(match_id=50, prediction_id=500, market_type="totals", selection="over",
                   model_prob=0.55, best_odds=1.90, implied_prob=0.526, edge=0.024,
                   bookmaker="Pinnacle", closing_odds=1.92, clv=-0.006),
    ])
    s.commit()


def test_build_movement_basic(session, monkeypatch):
    _seed_movement(session)
    _patch(session, monkeypatch)
    mv = build_movement(50)
    assert mv["home"] == "Brazil" and mv["away"] == "Scotland"
    assert mv["has_movement"] is True
    by = {s["canon"]: s for s in mv["selections"]}
    assert set(by) == {"home", "over_2.5"}          # only the two backable selections

    home = by["home"]
    assert home["selection"] == "Brazil" and home["market"] == "Match result"
    assert home["entry"] == 1.75 and home["entry_book"] == "FanDuel"
    assert home["close"] == 1.65
    assert home["open"] == 1.80                      # best (longest) open = max(1.80, 1.78)
    assert home["current"] == 1.70                   # best current = max(1.68, 1.70)
    assert home["clv"] == pytest.approx(0.034)
    # Real snapshots in time order, all four held.
    assert [p[0] for p in home["points"]] == ["Open", "Entry", "Current", "Close"]
    assert [p[1] for p in home["points"]] == [1.80, 1.75, 1.70, 1.65]

    over = by["over_2.5"]
    assert over["selection"] == "Over 2.5" and over["market"] == "Goals (O/U 2.5)"
    assert over["open"] == 1.85 and over["current"] == 1.95     # single book, drifted out
    assert over["entry"] == 1.90 and over["close"] == 1.92
    assert over["clv"] == pytest.approx(-0.006)


def test_build_movement_sorts_by_clv(session, monkeypatch):
    # Strongest beat-the-close story first: +0.034 (home) before −0.006 (over).
    _seed_movement(session)
    _patch(session, monkeypatch)
    mv = build_movement(50)
    clvs = [s["clv"] for s in mv["selections"]]
    assert clvs == sorted(clvs, reverse=True)
    assert mv["selections"][0]["canon"] == "home"


def test_build_movement_no_value_bets(session, monkeypatch):
    # Match 20 has odds + a prediction but NO value bets → nothing backable.
    _seed(session)
    _patch(session, monkeypatch)
    mv = build_movement(20)
    assert mv is not None
    assert mv["selections"] == [] and mv["has_movement"] is False


def test_build_movement_awaiting_close(session, monkeypatch):
    # Bet logged but the close not captured yet (pre-kickoff): close + clv None,
    # but open/entry/current still trace and the row still appears.
    session.add_all([
        WCTeam(id=1, name="Brazil", fifa_code="BRA", confederation="CONMEBOL", group_letter="C"),
        WCTeam(id=2, name="Scotland", fifa_code="SCO", confederation="UEFA", group_letter="C"),
    ])
    session.add(WCMatch(id=51, stage="group", group_letter="C", date="2026-06-25",
                        kickoff_time="18:00", home_team_id=1, away_team_id=2, status="scheduled"))
    session.add(WCPrediction(id=510, match_id=51, model_name=MODEL_NAME,
                             home_win_prob=0.62, draw_prob=0.22, away_win_prob=0.16,
                             home_expected_goals=2.0, away_expected_goals=0.7, over_25_prob=0.55))
    session.add(WCOdds(match_id=51, bookmaker="FanDuel", market_type="h2h", selection="Brazil",
                       odds_decimal=1.70, opening_odds=1.80, captured_at="2026-06-25T08:00"))
    session.add(WCValueBet(match_id=51, prediction_id=510, market_type="h2h", selection="home",
                           model_prob=0.62, best_odds=1.75, implied_prob=0.571, edge=0.05,
                           bookmaker="FanDuel", closing_odds=None, clv=None))
    session.commit()
    _patch(session, monkeypatch)
    home = build_movement(51)["selections"][0]
    assert home["close"] is None and home["clv"] is None
    assert [p[0] for p in home["points"]] == ["Open", "Entry", "Current"]  # no Close stage


def test_build_movement_missing_match(session, monkeypatch):
    _patch(session, monkeypatch)
    assert build_movement(99999) is None


# ---------------------------------------------------------------------------
# DF-10 — group/qualification context + per-match Bayes-vs-Poisson (shadow)
# ---------------------------------------------------------------------------

def _seed_group(s):
    """Group C, two rounds played; round 3 Brazil v Scotland (id=50) scheduled,
    with both a Poisson and a Bayesian shadow prediction. After two rounds:
    Brazil 6, Scotland 3 (GD +1), Switzerland 3 (GD 0), Cameroon 0."""
    s.add_all([
        WCTeam(id=1, name="Brazil", fifa_code="BRA", confederation="CONMEBOL", group_letter="C"),
        WCTeam(id=2, name="Scotland", fifa_code="SCO", confederation="UEFA", group_letter="C"),
        WCTeam(id=3, name="Switzerland", fifa_code="SUI", confederation="UEFA", group_letter="C"),
        WCTeam(id=4, name="Cameroon", fifa_code="CMR", confederation="CAF", group_letter="C"),
    ])
    s.add_all([
        WCMatch(id=1, stage="group", group_letter="C", date="2026-06-15",
                home_team_id=1, away_team_id=4, status="finished", home_goals=2, away_goals=0),
        WCMatch(id=2, stage="group", group_letter="C", date="2026-06-15",
                home_team_id=3, away_team_id=2, status="finished", home_goals=1, away_goals=0),
        WCMatch(id=3, stage="group", group_letter="C", date="2026-06-19",
                home_team_id=1, away_team_id=3, status="finished", home_goals=1, away_goals=0),
        WCMatch(id=4, stage="group", group_letter="C", date="2026-06-19",
                home_team_id=2, away_team_id=4, status="finished", home_goals=3, away_goals=1),
    ])
    s.add(WCMatch(id=50, stage="group", group_letter="C", date="2026-06-25",
                  kickoff_time="18:00", home_team_id=1, away_team_id=2, status="scheduled"))
    s.add(WCPrediction(id=500, match_id=50, model_name=MODEL_NAME,
                       home_win_prob=0.62, draw_prob=0.22, away_win_prob=0.16,
                       home_expected_goals=2.0, away_expected_goals=0.7,
                       over_25_prob=0.55, btts_prob=0.40))
    s.add(WCPrediction(id=501, match_id=50, model_name=MODEL_NAME_BAYES,
                       home_win_prob=0.58, draw_prob=0.25, away_win_prob=0.17,
                       home_expected_goals=1.8, away_expected_goals=0.8,
                       over_25_prob=0.52, btts_prob=0.44))
    s.commit()


def test_qual_status_clinched_eliminated_contention():
    # On 6 with one rival able to reach 6 and the rest far back → guaranteed top 2.
    assert _qual_status(6, 0, [(6, 0), (3, 0), (0, 0)]) == "clinched"
    # On 0 with no games left and two rivals already above the ceiling → out.
    assert _qual_status(0, 0, [(6, 0), (6, 0), (3, 0)]) == "eliminated"
    # On 3 with two rivals still able to overtake → genuinely alive.
    assert _qual_status(3, 1, [(6, 1), (4, 1), (3, 1)]) == "contention"


def test_group_context_scheduled_scenarios(session, monkeypatch):
    _seed_group(session)
    _patch(session, monkeypatch)
    ctx = build_group_context(50)
    assert ctx["is_group"] is True
    # Full sorted table (Scotland edges Switzerland on GD), both teams flagged.
    assert [r["name"] for r in ctx["table"]] == \
        ["Brazil", "Scotland", "Switzerland", "Cameroon"]
    assert {r["name"] for r in ctx["table"] if r["is_match_team"]} == {"Brazil", "Scotland"}
    # Three result scenarios; a Brazil win takes them to 9 and clinches top 2.
    assert [sc["label"] for sc in ctx["scenarios"]] == \
        ["If Brazil win", "If they draw", "If Scotland win"]
    win = ctx["scenarios"][0]
    assert win["home_pts"] == 9 and win["home_status"] == "clinched"
    assert ctx["realized"] is None


def test_group_context_finished_realized(session, monkeypatch):
    _seed_group(session)
    m = session.get(WCMatch, 50)            # play it: Brazil 2-0 Scotland
    m.status, m.home_goals, m.away_goals = "finished", 2, 0
    session.commit()
    _patch(session, monkeypatch)
    ctx = build_group_context(50)
    assert ctx["scenarios"] == []           # no hypotheticals once it's played
    assert ctx["realized"] is not None
    assert ctx["realized"]["home_pts"] == 9
    assert ctx["realized"]["home_status"] == "clinched"


def test_group_context_knockout(session, monkeypatch):
    session.add_all([
        WCTeam(id=1, name="Brazil", fifa_code="BRA", confederation="CONMEBOL", group_letter="C"),
        WCTeam(id=3, name="Switzerland", fifa_code="SUI", confederation="UEFA", group_letter="A"),
    ])
    session.add(WCMatch(id=90, stage="round_of_32", group_letter=None, date="2026-07-01",
                        home_team_id=1, away_team_id=3, status="scheduled"))
    session.commit()
    _patch(session, monkeypatch)
    ctx = build_group_context(90)
    assert ctx["is_group"] is False
    assert ctx["table"] == [] and ctx["scenarios"] == []
    assert "Knockout" in ctx["headline"]


def test_group_context_missing(session, monkeypatch):
    _patch(session, monkeypatch)
    assert build_group_context(99999) is None


def test_model_comparison_both_models(session, monkeypatch):
    _seed_group(session)
    _patch(session, monkeypatch)
    cmp = build_model_comparison(50)
    assert cmp["has_poisson"] and cmp["has_bayesian"]
    assert len(cmp["rows"]) == 7
    hw = next(r for r in cmp["rows"] if r["metric"] == "Home win")
    assert hw["poisson"] == 0.62 and hw["bayesian"] == 0.58
    assert abs(hw["delta"] - (0.58 - 0.62)) < 1e-9
    assert "lean" in cmp["agreement"].lower()   # both still favour the home win


def test_model_comparison_no_bayesian(session, monkeypatch):
    _seed_group(session)
    session.delete(session.get(WCPrediction, 501))   # drop the shadow row
    session.commit()
    _patch(session, monkeypatch)
    cmp = build_model_comparison(50)
    assert cmp["has_poisson"] is True and cmp["has_bayesian"] is False
    assert all(r["bayesian"] is None and r["delta"] is None for r in cmp["rows"])
    assert cmp["agreement"] is None


def test_model_comparison_disagreement(session, monkeypatch):
    _seed_group(session)
    b = session.get(WCPrediction, 501)               # make Bayesian favour the draw
    b.home_win_prob, b.draw_prob, b.away_win_prob = 0.30, 0.45, 0.25
    session.commit()
    _patch(session, monkeypatch)
    cmp = build_model_comparison(50)
    assert "disagree" in cmp["agreement"].lower()


def test_model_comparison_missing(session, monkeypatch):
    _patch(session, monkeypatch)
    assert build_model_comparison(99999) is None
