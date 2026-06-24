"""WC-11A-02 — Lineup impact: display-only adjusted-λ.

Three layers, mirroring every WC-11A UI issue:
  1. The pure math (research._resolve_share / _team_impact) — exact, no DB, with an
     injected fake rate_lookup so the formula is pinned down independently of the
     29k-row player cache.
  2. The DB-backed builder (research.build_lineup_impact) over one seeded in-memory
     match — reuses lineup_signal for the XI, reads the stored λ, and is proven
     READ-ONLY (it never writes back to WCPrediction).
  3. data → render: AST-exec the view's pure HTML helpers over the built data and
     prove a hostile player name is escaped, not injected.
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
from src.world_cup.research import build_lineup_impact, _resolve_share, _team_impact
from src.world_cup.predictor import MODEL_NAME
from src.world_cup.models import WCTeam, WCMatch, WCPrediction, WCLineup

DD = Path(__file__).resolve().parents[1] / "src" / "delivery" / "views" / "wc_deep_dive.py"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _rows(names):
    """XI rows in the shape lineups._starter_rows returns (full_name/position None
    so the fake lookup resolves by the short name)."""
    return [{"name": n, "full_name": None, "position": None} for n in names]


def _leg(nation, lam, current, baseline):
    return {"nation": nation, "lambda_model": lam,
            "current": _rows(current), "baseline": _rows(baseline)}


def _lookup(rates):
    """A fake rate_lookup(name, nation, position) -> {'goals_per_90': x} | None,
    keyed only by name. Unknown names resolve to None (unrated)."""
    def f(name, nation, position):
        g = rates.get(name)
        return {"goals_per_90": g} if g is not None else None
    return f


# A small squad: 10 shared role players + a star striker / a weak sub.
SHARED = {f"P{i}": 0.15 for i in range(10)}          # 10 × 0.15 = 1.50
RATES = {**SHARED, "Star": 0.90, "Sub": 0.10}
RL = _lookup(RATES)


# ---------------------------------------------------------------------------
# 1. pure math
# ---------------------------------------------------------------------------

def test_resolve_share_sums_rated_and_lists_missing():
    rows = _rows(["Star", "P0", "Ghost"])            # Ghost unrated
    shares, total, missing = _resolve_share(rows, "Brazil", RL)
    assert shares["Star"] == 0.90 and shares["P0"] == 0.15
    assert shares["Ghost"] is None and missing == ["Ghost"]
    assert total == pytest.approx(1.05)              # Ghost excluded


def test_not_announced_is_a_clean_minimal_state():
    out = _team_impact(_leg("Brazil", 2.0, [], []), {"status": "not_announced"}, RL)
    assert out == {"team": "Brazil", "status": "not_announced"}


def test_announced_but_no_model_lambda():
    leg = _leg("Brazil", None, list(SHARED), list(SHARED))
    out = _team_impact(leg, {"status": "announced", "formation": "4-3-3"}, RL)
    assert out["status"] == "no_model" and out["formation"] == "4-3-3"
    assert "lambda_adjusted" not in out


def test_rotated_out_striker_lowers_adjusted_lambda_neutrally():
    """The headline AC: drop a high-goal-share striker for a weak sub and the
    adjusted λ visibly falls; the striker is surfaced as rotated-out (in_xi False)."""
    base = list(SHARED) + ["Star"]                   # prior XI had the striker
    now = list(SHARED) + ["Sub"]                     # this XI benches him
    out = _team_impact(_leg("Brazil", 2.0, now, base),
                       {"status": "announced", "formation": "4-2-3-1",
                        "heavy_rotation": False, "changes": 1}, RL)
    assert out["status"] == "announced" and out["baseline_available"] is True
    # cur 1.60 / base 2.40 = 0.667 → 2.0 × 0.667 = 1.333; a clear, neutral drop.
    assert out["lambda_adjusted"] == pytest.approx(2.0 * (1.60 / 2.40))
    assert out["delta"] < 0 and out["lambda_adjusted"] < out["lambda_model"]
    rotated = [s for s in out["scorers"] if not s["in_xi"]]
    assert [s["player"] for s in rotated] == ["Star"]
    assert rotated[0]["exp_goals"] == 0.0            # benched → 0 this match


def test_upgrade_raises_adjusted_lambda():
    base = list(SHARED) + ["Sub"]
    now = list(SHARED) + ["Star"]
    out = _team_impact(_leg("Brazil", 2.0, now, base),
                       {"status": "announced"}, RL)
    assert out["delta"] > 0 and out["lambda_adjusted"] > out["lambda_model"]


def test_no_prior_xi_means_adjusted_equals_model():
    out = _team_impact(_leg("Scotland", 1.2, list(SHARED), []),
                       {"status": "announced"}, RL)
    assert out["baseline_available"] is False
    assert out["lambda_adjusted"] == pytest.approx(1.2) and out["delta"] == 0.0


def test_exp_goals_of_rated_xi_players_sum_to_adjusted_lambda():
    base = list(SHARED) + ["Star"]
    now = list(SHARED) + ["Sub"]
    out = _team_impact(_leg("Brazil", 2.0, now, base), {"status": "announced"}, RL)
    rated = [s["exp_goals"] for s in out["scorers"]
             if s["in_xi"] and s["exp_goals"] is not None]
    assert sum(rated) == pytest.approx(out["lambda_adjusted"])


def test_unrated_players_are_excluded_and_reported():
    now = list(SHARED) + ["Ghost1", "Ghost2"]        # two unrated in the XI
    out = _team_impact(_leg("Brazil", 2.0, now, list(SHARED)),
                       {"status": "announced"}, RL)
    assert set(out["missing"]) == {"Ghost1", "Ghost2"}
    assert out["n_xi"] == 12 and out["n_rated"] == 10
    ghosts = [s for s in out["scorers"] if s["player"].startswith("Ghost")]
    assert all(s["share"] is None and s["exp_goals"] is None for s in ghosts)


def test_ratio_is_clamped_so_a_thin_resolve_cant_explode_the_number():
    # Only the striker resolves now (0.90) vs a strong prior (Star+9×0.15=2.25) →
    # raw ratio 0.40, floored to 0.50; and the inverse is capped at 1.50.
    down = _team_impact(_leg("Brazil", 2.0, ["Star"], ["Star"] + [f"P{i}" for i in range(9)]),
                        {"status": "announced"}, RL)
    assert down["lambda_adjusted"] == pytest.approx(2.0 * 0.5)
    up = _team_impact(_leg("Brazil", 2.0, ["Star"] + [f"P{i}" for i in range(9)], ["Sub"]),
                      {"status": "announced"}, RL)
    assert up["lambda_adjusted"] == pytest.approx(2.0 * 1.5)


# ---------------------------------------------------------------------------
# 2. DB-backed builder (reuses lineup_signal; read-only)
# ---------------------------------------------------------------------------

MATCH_ID = 50
PRIOR_ID = 3
BRA_PRIOR = [f"P{i}" for i in range(10)] + ["Star"]
BRA_NOW = [f"P{i}" for i in range(10)] + ["Sub"]      # striker benched
SCO_NOW = [f"S{i}" for i in range(11)]                # Scotland: no prior XI


@pytest.fixture
def seeded(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    s.add_all([
        WCTeam(id=1, name="Brazil", fifa_code="BRA", confederation="CONMEBOL", group_letter="C"),
        WCTeam(id=2, name="Scotland", fifa_code="SCO", confederation="UEFA", group_letter="C"),
    ])
    s.add_all([
        WCMatch(id=PRIOR_ID, stage="group", group_letter="C", date="2026-06-19",
                home_team_id=1, away_team_id=2, status="finished", home_goals=2, away_goals=0),
        WCMatch(id=MATCH_ID, stage="group", group_letter="C", date="2026-06-25",
                kickoff_time="18:00", home_team_id=1, away_team_id=2, status="scheduled"),
    ])
    s.add(WCPrediction(id=500, match_id=MATCH_ID, model_name=MODEL_NAME,
                       home_win_prob=0.62, draw_prob=0.22, away_win_prob=0.16,
                       home_expected_goals=2.0, away_expected_goals=0.8,
                       over_25_prob=0.55, btts_prob=0.40))
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


def test_build_lineup_impact_end_to_end(seeded):
    data = build_lineup_impact(MATCH_ID, RL)
    assert data["match_id"] == MATCH_ID
    assert data["home"] == "Brazil" and data["away"] == "Scotland"
    bra = next(t for t in data["teams"] if t["team"] == "Brazil")
    sco = next(t for t in data["teams"] if t["team"] == "Scotland")

    # Brazil: striker rotated out → adjusted λ below the model's, baseline used.
    assert bra["status"] == "announced" and bra["baseline_available"] is True
    assert bra["lambda_model"] == 2.0 and bra["lambda_adjusted"] < 2.0
    assert "Star" in [s["player"] for s in bra["scorers"] if not s["in_xi"]]
    # Scotland: no prior XI captured → adjusted == model, no swing.
    assert sco["baseline_available"] is False
    assert sco["lambda_adjusted"] == pytest.approx(0.8)


def test_build_lineup_impact_unknown_match_is_none(seeded):
    assert build_lineup_impact(999, RL) is None


def test_build_lineup_impact_is_read_only(seeded):
    """Shadow guarantee: building the what-if must not mutate the stored λ or add
    any row (no session.add / commit in the builder)."""
    before_pred = seeded.query(WCPrediction).count()
    before_lineup = seeded.query(WCLineup).count()
    build_lineup_impact(MATCH_ID, RL)
    pred = seeded.query(WCPrediction).filter_by(match_id=MATCH_ID).one()
    assert pred.home_expected_goals == 2.0 and pred.away_expected_goals == 0.8
    assert seeded.query(WCPrediction).count() == before_pred
    assert seeded.query(WCLineup).count() == before_lineup


# ---------------------------------------------------------------------------
# 3. data -> render: AST-exec the view's pure HTML helpers
# ---------------------------------------------------------------------------

_PURE_FUNCS = {"_impact_scorer_row_html", "_impact_lambda_html", "_impact_card_html"}


def _view_namespace():
    tree = ast.parse(DD.read_text())
    ns = {"escape": escape}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            exec(compile(ast.Module(body=[node], type_ignores=[]), "<dd>", "exec"), ns)
        elif isinstance(node, ast.FunctionDef) and node.name in _PURE_FUNCS:
            exec(compile(ast.Module(body=[node], type_ignores=[]), "<dd>", "exec"), ns)
    return ns


def test_view_renders_impact_card_from_real_built_data(seeded):
    ns = _view_namespace()
    data = build_lineup_impact(MATCH_ID, RL)
    bra = next(t for t in data["teams"] if t["team"] == "Brazil")
    card = ns["_impact_card_html"](bra)
    assert "Brazil" in card and "Formation" in card
    assert "model xG" in card and "adjusted" in card
    assert "rotated out" in card                      # the benched striker row


def test_view_card_handles_not_announced_and_no_model():
    ns = _view_namespace()
    na = ns["_impact_card_html"]({"team": "Spain", "status": "not_announced"})
    assert "not announced" in na.lower()
    nm = ns["_impact_card_html"]({"team": "Spain", "status": "no_model",
                                  "formation": "4-3-3", "heavy_rotation": False,
                                  "changes": None})
    assert "hasn" in nm.lower()                        # "hasn't scored this match"


def test_view_escapes_hostile_player_name():
    ns = _view_namespace()
    row = ns["_impact_scorer_row_html"](
        {"player": "<img src=x onerror=alert(1)>", "in_xi": True,
         "share": 0.5, "exp_goals": 0.4})
    assert "<img src=x" not in row and "&lt;img" in row
