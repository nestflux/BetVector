"""WC-09-03 — research data layer (best price, consensus, edge, line movement)."""

from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.db import Base
import src.world_cup.research as research
from src.world_cup.research import (
    build_research_card, top_disagreements, _devig, _consensus,
    summarize_card, build_disagreements, build_book_comparison,
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
