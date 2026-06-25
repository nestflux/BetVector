"""DF-10 — WC deep-dive flow integration test (real, not AST).

The deep-dive page (src/delivery/views/wc_deep_dive.py) renders at import, so we
can't import it directly. Instead we exercise the WHOLE per-match data layer it
draws — model-vs-every-book, the 7x7 scoreline matrix, line movement + CLV,
group/qualification context, the per-match Bayes-vs-Poisson read, and the lineup
signal — end-to-end over one seeded in-memory database, then AST-exec the view's
pure HTML helpers over that real data to prove the data → render path produces
coherent, escaped output for every section. This is the "integration test for the
deep-dive flow" DF-10 asks for.
"""

import ast
from contextlib import contextmanager
from html import escape
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.db import Base
import src.world_cup.research as research
import src.world_cup.lineups as lineups
from src.world_cup.research import (
    build_book_comparison, build_group_context, build_model_comparison,
    build_movement,
)
from src.world_cup.lineups import lineup_signal
from src.world_cup.predictor import MODEL_NAME, scoreline_matrix_from_lambdas
from src.world_cup.bayesian_model import MODEL_NAME_BAYES
from src.world_cup.flags import render_flag
from src.world_cup.models import (
    WCTeam, WCMatch, WCOdds, WCPrediction, WCValueBet, WCLineup,
)

DD = Path(__file__).resolve().parents[1] / "src" / "delivery" / "views" / "wc_deep_dive.py"

# The deep-dive match: Brazil v Scotland, Group C final round, scheduled.
MATCH_ID = 50
PRIOR_ID = 3            # Brazil's actual prior group game — gives a rotation comparison

BRA_PRIOR = ["Alisson", "Danilo", "Marquinhos", "T. Silva", "G. Arana",
             "Casemiro", "Guimaraes", "Paqueta", "Raphinha", "Vinicius Jr", "Richarlison"]
BRA_NOW = ["Alisson", "Danilo", "Marquinhos", "T. Silva", "G. Arana",
           "Bremer", "Andre", "Rodrygo", "Martinelli", "Endrick", "Antony"]
SCO_NOW = ["Gunn", "Hickey", "Hendry", "Tierney", "Robertson",
           "McTominay", "Gilmour", "McGinn", "Christie", "Adams", "Dykes"]


@pytest.fixture
def seeded(monkeypatch):
    """A realistic Group C deep-dive match with predictions (both models), odds,
    shadow value bets, and confirmed lineups — patched in for research + lineups."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    s.add_all([
        WCTeam(id=1, name="Brazil", fifa_code="BRA", confederation="CONMEBOL", group_letter="C"),
        WCTeam(id=2, name="Scotland", fifa_code="SCO", confederation="UEFA", group_letter="C"),
        WCTeam(id=3, name="Switzerland", fifa_code="SUI", confederation="UEFA", group_letter="C"),
        WCTeam(id=4, name="Cameroon", fifa_code="CMR", confederation="CAF", group_letter="C"),
    ])
    # Two rounds already played → Brazil 6, Scotland 3, Switzerland 3, Cameroon 0.
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
    s.add(WCMatch(id=MATCH_ID, stage="group", group_letter="C", date="2026-06-25",
                  kickoff_time="18:00", home_team_id=1, away_team_id=2, status="scheduled"))
    # Both predictions: staked Poisson + shadow Bayesian.
    s.add(WCPrediction(id=500, match_id=MATCH_ID, model_name=MODEL_NAME,
                       home_win_prob=0.62, draw_prob=0.22, away_win_prob=0.16,
                       home_expected_goals=2.0, away_expected_goals=0.7,
                       over_25_prob=0.55, btts_prob=0.40))
    s.add(WCPrediction(id=501, match_id=MATCH_ID, model_name=MODEL_NAME_BAYES,
                       home_win_prob=0.58, draw_prob=0.25, away_win_prob=0.17,
                       home_expected_goals=1.8, away_expected_goals=0.8,
                       over_25_prob=0.52, btts_prob=0.44))
    # Odds: h2h two books (moved) + totals, so model-vs-books + movement have data.
    s.add_all([
        WCOdds(match_id=MATCH_ID, bookmaker="Pinnacle", market_type="h2h", selection="Brazil",
               odds_decimal=1.68, opening_odds=1.80, captured_at="2026-06-25T08:00"),
        WCOdds(match_id=MATCH_ID, bookmaker="FanDuel", market_type="h2h", selection="Brazil",
               odds_decimal=1.70, opening_odds=1.78, captured_at="2026-06-25T08:00"),
        WCOdds(match_id=MATCH_ID, bookmaker="Pinnacle", market_type="h2h", selection="Draw",
               odds_decimal=4.0, opening_odds=4.2, captured_at="2026-06-25T08:00"),
        WCOdds(match_id=MATCH_ID, bookmaker="FanDuel", market_type="h2h", selection="Draw",
               odds_decimal=4.1, opening_odds=4.3, captured_at="2026-06-25T08:00"),
        WCOdds(match_id=MATCH_ID, bookmaker="Pinnacle", market_type="h2h", selection="Scotland",
               odds_decimal=6.0, opening_odds=5.5, captured_at="2026-06-25T08:00"),
        WCOdds(match_id=MATCH_ID, bookmaker="FanDuel", market_type="h2h", selection="Scotland",
               odds_decimal=6.2, opening_odds=5.8, captured_at="2026-06-25T08:00"),
        WCOdds(match_id=MATCH_ID, bookmaker="Pinnacle", market_type="totals", selection="Over",
               odds_decimal=1.95, opening_odds=1.85, point=2.5, captured_at="2026-06-25T08:00"),
        WCOdds(match_id=MATCH_ID, bookmaker="Pinnacle", market_type="totals", selection="Under",
               odds_decimal=1.90, opening_odds=1.95, point=2.5, captured_at="2026-06-25T08:00"),
    ])
    # Two shadow value bets: Brazil beat the close (+CLV), Over 2.5 didn't (−CLV).
    s.add_all([
        WCValueBet(match_id=MATCH_ID, prediction_id=500, market_type="h2h", selection="home",
                   model_prob=0.62, best_odds=1.75, implied_prob=0.571, edge=0.05,
                   bookmaker="FanDuel", closing_odds=1.65, clv=0.034),
        WCValueBet(match_id=MATCH_ID, prediction_id=500, market_type="totals", selection="over",
                   model_prob=0.55, best_odds=1.90, implied_prob=0.526, edge=0.024,
                   bookmaker="Pinnacle", closing_odds=1.92, clv=-0.006),
    ])
    # Lineups: Brazil rotates heavily vs its prior XI; Scotland's XI is fresh data.
    for nm in BRA_PRIOR:
        s.add(WCLineup(match_id=PRIOR_ID, team_id=1, player_name=nm, is_starter=1,
                       formation="4-3-3", captured_at="2026-06-19T17:00"))
    for nm in BRA_NOW:
        s.add(WCLineup(match_id=MATCH_ID, team_id=1, player_name=nm, is_starter=1,
                       formation="4-2-3-1", captured_at="2026-06-25T17:00"))
    for nm in SCO_NOW:
        s.add(WCLineup(match_id=MATCH_ID, team_id=2, player_name=nm, is_starter=1,
                       formation="3-5-2", captured_at="2026-06-25T17:00"))
    s.commit()

    @contextmanager
    def fake():
        yield s

    monkeypatch.setattr(research, "get_session", fake)
    monkeypatch.setattr(lineups, "get_session", fake)
    yield s
    s.close()


def test_every_data_layer_resolves_the_same_match(seeded):
    """The whole per-match flow agrees: every builder returns this match with the
    same two teams (the data the deep-dive page is assembled from)."""
    comp = build_book_comparison(MATCH_ID)
    mv = build_movement(MATCH_ID)
    ctx = build_group_context(MATCH_ID)
    cmp = build_model_comparison(MATCH_ID)
    sig = lineup_signal(MATCH_ID)

    for layer in (comp, mv, ctx, cmp):
        assert layer is not None and layer["match_id"] == MATCH_ID
        assert layer["home"] == "Brazil" and layer["away"] == "Scotland"
    assert {t["team"] for t in sig["teams"]} == {"Brazil", "Scotland"}


def test_model_vs_books_and_matrix(seeded):
    comp = build_book_comparison(MATCH_ID)
    assert comp["markets"], "model-vs-books should have at least the 1X2 market"
    matrix = scoreline_matrix_from_lambdas(comp["lambda_home"], comp["lambda_away"])
    assert len(matrix) == 7 and all(len(row) == 7 for row in matrix)
    total = sum(sum(row) for row in matrix)
    assert 0.95 <= total <= 1.0001          # a valid probability grid


def test_movement_carries_clv(seeded):
    mv = build_movement(MATCH_ID)
    cl = {s["canon"]: s["clv"] for s in mv["selections"]}
    assert cl["home"] == 0.034 and cl["over_2.5"] == -0.006
    assert mv["has_movement"] is True
    # Strongest-CLV first.
    assert mv["selections"][0]["canon"] == "home"


def test_group_context_scenarios_and_qualification(seeded):
    ctx = build_group_context(MATCH_ID)
    assert ctx["is_group"] is True
    assert [r["name"] for r in ctx["table"]] == \
        ["Brazil", "Scotland", "Switzerland", "Cameroon"]
    win = next(sc for sc in ctx["scenarios"] if sc["label"] == "If Brazil win")
    assert win["home_pts"] == 9 and win["home_status"] == "clinched"


def test_model_comparison_shadow_read(seeded):
    cmp = build_model_comparison(MATCH_ID)
    assert cmp["has_poisson"] and cmp["has_bayesian"]
    assert len(cmp["rows"]) == 7
    assert cmp["agreement"] and "lean" in cmp["agreement"].lower()


def test_lineups_signal_flags_rotation(seeded):
    sig = lineup_signal(MATCH_ID)
    bra = next(t for t in sig["teams"] if t["team"] == "Brazil")
    assert bra["status"] == "announced"
    assert bra["heavy_rotation"] is True     # 6 changes vs the prior XI


# ---------------------------------------------------------------------------
# data -> render: AST-exec the view's pure HTML helpers over the real built data
# (the page self-runs at import, so we exec only its constants + pure functions).
# ---------------------------------------------------------------------------

_PURE_FUNCS = {
    "_pct", "_qual_chip_html", "_standings_table_html", "_scenario_row_html",
    "_scenarios_table_html", "_model_cell_html", "_delta_html",
    "_model_compare_table_html", "_price_td", "_clv_td", "_movement_table_html",
    "_lineup_card_html", "_book_cell_html", "_market_table_html",
}


def _view_namespace():
    """Exec the view's module-level constants + pure HTML helpers into a namespace
    (no Streamlit, no page execution)."""
    tree = ast.parse(DD.read_text())
    ns = {"escape": escape, "render_flag": render_flag}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            exec(compile(ast.Module(body=[node], type_ignores=[]), "<dd>", "exec"), ns)
        elif isinstance(node, ast.FunctionDef) and node.name in _PURE_FUNCS:
            exec(compile(ast.Module(body=[node], type_ignores=[]), "<dd>", "exec"), ns)
    return ns


def test_view_helpers_render_every_section_from_real_data(seeded):
    ns = _view_namespace()
    comp = build_book_comparison(MATCH_ID)
    mv = build_movement(MATCH_ID)
    ctx = build_group_context(MATCH_ID)
    cmp = build_model_comparison(MATCH_ID)
    sig = lineup_signal(MATCH_ID)

    # Group table + scenarios.
    standings = ns["_standings_table_html"](ctx)
    assert "Brazil" in standings and "Switzerland" in standings
    scenarios = ns["_scenarios_table_html"](ctx)
    assert "If Brazil win" in scenarios and "through" in scenarios  # clinched chip

    # Per-match Bayes-vs-Poisson table (Poisson 62% beside Bayesian 58%).
    model_tbl = ns["_model_compare_table_html"](cmp)
    assert "Home win" in model_tbl
    assert "62%" in model_tbl and "58%" in model_tbl

    # Movement table (CLV) + model-vs-books market table.
    movement_tbl = ns["_movement_table_html"](mv)
    assert "+3.4%" in movement_tbl and "Brazil" in movement_tbl
    market_tbl = ns["_market_table_html"](comp["markets"][0])
    assert "Model" in market_tbl

    # Lineup card + glossary.
    bra = next(t for t in sig["teams"] if t["team"] == "Brazil")
    card = ns["_lineup_card_html"](bra)
    assert "Brazil" in card and "Formation" in card
    # Glossary now renders from the shared Help Center source (HC-06).
    from src.delivery.help_content import glossary_sections_html
    glossary = glossary_sections_html("WC Deep Dive")
    for term in ("CLV", "De-vig", "Scoreline matrix", "Bayesian"):
        assert term in glossary


def test_view_helpers_escape_hostile_team_name(seeded):
    """A team name with HTML metacharacters must be escaped, not injected."""
    s = seeded
    s.query(WCTeam).filter(WCTeam.id == 2).update(
        {"name": '<img src=x onerror=alert(1)>'})
    s.commit()
    ns = _view_namespace()
    ctx = build_group_context(MATCH_ID)
    standings = ns["_standings_table_html"](ctx)
    assert "<img src=x" not in standings
    assert "&lt;img" in standings
