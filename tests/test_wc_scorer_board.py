"""WC-11A-03 — "Who's likely to score" board + penalty-taker flag.

Three layers, mirroring every WC-11A UI issue:
  1. The pure math (research._anytime_prob / _team_scorer_board) — exact, no DB, with
     an injected fake rate_lookup so the anytime formula P = 1 − e^(−player_λ) and the
     ranking are pinned down independently of the 29k-row player cache.
  2. The DB-backed builder (research.build_scorer_board) over one seeded in-memory
     match — reuses the WC-11A-02 read + λ, and is proven READ-ONLY (no odds pulled,
     nothing written back).
  3. data → render: AST-exec the view's pure HTML helpers over the built data and
     prove the penalty-taker / international tags render and a hostile name is escaped.

The scorer board spends ZERO Odds API credits — it is the model's own "who scores"
ranking, built entirely from the stored λ + the player-rate cache.
"""

import ast
import math
from contextlib import contextmanager
from html import escape
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.db import Base
import src.world_cup.research as research
import src.world_cup.lineups as lineups
from src.world_cup.research import build_scorer_board, _anytime_prob, _team_scorer_board
from src.world_cup.predictor import MODEL_NAME
from src.world_cup.models import WCTeam, WCMatch, WCPrediction, WCLineup

DD = Path(__file__).resolve().parents[1] / "src" / "delivery" / "views" / "wc_deep_dive.py"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _rows(names):
    """XI rows in the shape lineups._starter_rows returns (full_name/position None so
    the fake lookup resolves by the short name, as the real resolver would)."""
    return [{"name": n, "full_name": None, "position": None} for n in names]


def _leg(nation, lam, current, baseline):
    return {"nation": nation, "lambda_model": lam,
            "current": _rows(current), "baseline": _rows(baseline)}


def _lookup(rates):
    """A fake rate_lookup(name, nation, position) -> profile | None, keyed by name.
    ``rates`` maps name -> (goals_per_90, is_pen_taker, source); unknown -> None."""
    def f(name, nation, position):
        v = rates.get(name)
        if v is None:
            return None
        gp90, pen, src = v
        return {"goals_per_90": gp90, "is_pen_taker": pen, "source": src}
    return f


# A squad: 9 role players + a star pen-taking striker + an international-fallback
# forward + a weak sub. "Ghost" is intentionally absent → unrated.
SHARED = {f"P{i}": (0.15, False, "club") for i in range(9)}
RATES = {**SHARED,
         "Star": (0.90, True, "club"),          # high share + penalty taker
         "Saudi": (0.30, False, "international"),  # no club minutes → intl fallback
         "Sub": (0.10, False, "club")}
RL = _lookup(RATES)

SIG_ON = {"status": "announced", "formation": "4-2-3-1",
          "heavy_rotation": False, "changes": 1}


# ---------------------------------------------------------------------------
# 1. pure math
# ---------------------------------------------------------------------------

def test_anytime_prob_is_poisson_p_at_least_one():
    assert _anytime_prob(0.75) == pytest.approx(1.0 - math.exp(-0.75))
    assert _anytime_prob(0.0) is None        # no expected goals → no estimate
    assert _anytime_prob(None) is None        # unrated player
    assert _anytime_prob(-0.2) is None        # guard against a bad λ
    assert _anytime_prob(0.9) > _anytime_prob(0.3)   # monotonic in λ


def test_not_announced_is_a_clean_minimal_state():
    out = _team_scorer_board(_leg("Brazil", 2.0, [], []),
                             {"status": "not_announced"}, RL)
    assert out["team"] == "Brazil" and out["status"] == "not_announced"
    assert "players" not in out


def test_announced_but_no_model_lambda():
    leg = _leg("Brazil", None, list(SHARED), list(SHARED))
    out = _team_scorer_board(leg, {"status": "announced", "formation": "4-3-3"}, RL)
    assert out["status"] == "no_model" and out["formation"] == "4-3-3"
    assert "players" not in out


def test_ranked_board_flags_pen_taker_and_intl_excludes_unrated():
    """The headline AC: a ranked anytime table — the star striker top (≈ 50%), the
    penalty taker flagged, the international-fallback rate labelled, defenders/role
    players low, and an unrated name left out (never guessed)."""
    xi = list(SHARED) + ["Star", "Saudi", "Ghost"]     # Ghost unrated; no prior XI
    out = _team_scorer_board(_leg("Brazil", 2.0, xi, []), SIG_ON, RL)
    assert out["status"] == "announced"

    players = out["players"]
    names = [p["player"] for p in players]
    assert "Ghost" not in names and out["missing"] == ["Ghost"]   # unrated excluded
    assert out["n_ranked"] == 11                                   # 9 + Star + Saudi
    assert names[0] == "Star"                                      # ranked P desc
    assert players[0]["is_pen_taker"] is True                      # PK flagged

    # Star, a true No.9, lands in a plausible anytime band; role players are low.
    star = players[0]
    assert 0.45 <= star["p_anytime"] <= 0.60
    role = next(p for p in players if p["player"] == "P0")
    assert role["p_anytime"] < 0.20

    saudi = next(p for p in players if p["player"] == "Saudi")
    assert saudi["source"] == "international"                       # labelled honestly
    assert all(p["source"] == "club" for p in players if p["player"] != "Saudi")


def test_p_anytime_is_consistent_with_player_lambda():
    """Each ranked player's probability is exactly 1 − e^(−player_λ), and player_λ is
    his slice of the team λ (the WC-11A-02 exp_goals) — no recompute, no drift."""
    xi = list(SHARED) + ["Star", "Saudi"]
    out = _team_scorer_board(_leg("Brazil", 2.0, xi, []), SIG_ON, RL)
    for p in out["players"]:
        assert p["p_anytime"] == pytest.approx(1.0 - math.exp(-p["player_lambda"]))
    # player_λ's sum to the team's adjusted λ (here adjusted == model, no baseline).
    assert sum(p["player_lambda"] for p in out["players"]) == pytest.approx(2.0)


def test_zero_rate_starter_is_dropped_not_flagged_unrated():
    """A confirmed starter with a real 0.0 goals-per-90 (a keeper, a never-scored
    defender) is rated — just rated zero — so he doesn't belong on a 'who scores'
    board and is NOT an unrated/missing player either. He's silently absent from both,
    which is the honest outcome (P=0 isn't worth a row)."""
    rates = {**RATES, "Keeper": (0.0, False, "club")}
    xi = list(SHARED) + ["Star", "Keeper"]
    out = _team_scorer_board(_leg("Brazil", 2.0, xi, []), SIG_ON, _lookup(rates))
    assert "Keeper" not in [p["player"] for p in out["players"]]   # not ranked (P=0)
    assert "Keeper" not in out["missing"]                          # not unrated either


def test_rotated_out_players_never_appear_on_the_board():
    """A benched striker doesn't play, so he is not a candidate to score — the board
    shows only the confirmed XI (unlike the impact card, which surfaces him to explain
    the delta)."""
    base = list(SHARED) + ["Star"]                     # prior XI had the striker
    now = list(SHARED) + ["Sub"]                       # this XI benches him
    out = _team_scorer_board(_leg("Brazil", 2.0, now, base), SIG_ON, RL)
    assert "Star" not in [p["player"] for p in out["players"]]


# ---------------------------------------------------------------------------
# 2. DB-backed builder (shares the WC-11A-02 read; read-only; no odds)
# ---------------------------------------------------------------------------

MATCH_ID = 60
BRA_NOW = [f"P{i}" for i in range(9)] + ["Star", "Saudi"]   # rich attacking XI
SCO_NOW = [f"P{i}" for i in range(9)] + ["Sub", "Saudi"]    # Scotland reuses the pool


@pytest.fixture
def seeded(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    s.add_all([
        WCTeam(id=1, name="Brazil", fifa_code="BRA", confederation="CONMEBOL", group_letter="C"),
        WCTeam(id=2, name="Scotland", fifa_code="SCO", confederation="UEFA", group_letter="C"),
    ])
    # A single scheduled match with no prior XI for either side → baseline absent, so
    # adjusted λ == the stored model λ and the anytime numbers are predictable.
    s.add(WCMatch(id=MATCH_ID, stage="group", group_letter="C", date="2026-06-25",
                  kickoff_time="18:00", home_team_id=1, away_team_id=2, status="scheduled"))
    s.add(WCPrediction(id=600, match_id=MATCH_ID, model_name=MODEL_NAME,
                       home_win_prob=0.62, draw_prob=0.22, away_win_prob=0.16,
                       home_expected_goals=2.0, away_expected_goals=1.2,
                       over_25_prob=0.55, btts_prob=0.40))
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


def test_build_scorer_board_end_to_end(seeded):
    data = build_scorer_board(MATCH_ID, RL)
    assert data["match_id"] == MATCH_ID
    bra = next(t for t in data["teams"] if t["team"] == "Brazil")
    assert bra["status"] == "announced"
    assert bra["players"][0]["player"] == "Star"            # top of the ranking
    assert bra["players"][0]["is_pen_taker"] is True
    assert any(p["source"] == "international" for p in bra["players"])  # Saudi labelled
    # Probabilities are sane and ordered.
    probs = [p["p_anytime"] for p in bra["players"]]
    assert probs == sorted(probs, reverse=True)
    assert 0.45 <= probs[0] <= 0.60


def test_build_scorer_board_unknown_match_is_none(seeded):
    assert build_scorer_board(999, RL) is None


def test_build_scorer_board_is_read_only(seeded):
    """Shadow + no-cost guarantee: building the board must not touch the stored λ or
    add any row (no session.add / commit, and no odds pull anywhere in the path)."""
    before_pred = seeded.query(WCPrediction).count()
    before_lineup = seeded.query(WCLineup).count()
    build_scorer_board(MATCH_ID, RL)
    pred = seeded.query(WCPrediction).filter_by(match_id=MATCH_ID).one()
    assert pred.home_expected_goals == 2.0 and pred.away_expected_goals == 1.2
    assert seeded.query(WCPrediction).count() == before_pred
    assert seeded.query(WCLineup).count() == before_lineup


# ---------------------------------------------------------------------------
# 3. data -> render: AST-exec the view's pure HTML helpers
# ---------------------------------------------------------------------------

_PURE_FUNCS = {"_scorer_row_html", "_scorer_board_card_html"}


def _view_namespace():
    tree = ast.parse(DD.read_text())
    ns = {"escape": escape}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            exec(compile(ast.Module(body=[node], type_ignores=[]), "<dd>", "exec"), ns)
        elif isinstance(node, ast.FunctionDef) and node.name in _PURE_FUNCS:
            exec(compile(ast.Module(body=[node], type_ignores=[]), "<dd>", "exec"), ns)
    return ns


def test_view_renders_scorer_card_from_real_built_data(seeded):
    ns = _view_namespace()
    data = build_scorer_board(MATCH_ID, RL)
    bra = next(t for t in data["teams"] if t["team"] == "Brazil")
    card = ns["_scorer_board_card_html"](bra)
    assert "Brazil" in card and "Anytime" in card
    assert "Star" in card and "PK" in card          # the flagged penalty taker
    assert "intl" in card                            # international-fallback label
    assert "%" in card                               # anytime probabilities rendered


def test_view_card_handles_not_announced_and_no_model():
    ns = _view_namespace()
    na = ns["_scorer_board_card_html"]({"team": "Spain", "status": "not_announced"})
    assert "not announced" in na.lower()
    nm = ns["_scorer_board_card_html"]({"team": "Spain", "status": "no_model",
                                        "formation": "4-3-3"})
    assert "hasn" in nm.lower()                       # "hasn't scored this match"


def test_view_card_handles_an_all_unrated_xi():
    ns = _view_namespace()
    card = ns["_scorer_board_card_html"]({"team": "Spain", "status": "announced",
                                          "formation": "4-3-3", "players": [],
                                          "missing": ["A", "B"]})
    assert "No rated scorers" in card


def test_view_escapes_hostile_player_name():
    ns = _view_namespace()
    row = ns["_scorer_row_html"](1, {"player": "<img src=x onerror=alert(1)>",
                                     "p_anytime": 0.4, "goals_per_90": 0.5,
                                     "is_pen_taker": False, "source": "club"})
    assert "<img src=x" not in row and "&lt;img" in row
