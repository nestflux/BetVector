"""
WC-09-07 — Bayesian vs Poisson validation (holdout backtest + live tracker).

Covers the Bayesian holdout evaluator (temporal split + metrics), the comparison
verdict logic, the live finished-match metrics, the documented promotion bar, and
the dashboard wiring. Synthetic / in-memory — no real DB, no network.
"""

import ast
import datetime as dt
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.db import Base
import src.world_cup.bayesian_model as bm
import src.world_cup.bayesian_validation as val
from src.world_cup.bayesian_model import BayesianPoissonModel, MODEL_NAME_BAYES
from src.world_cup.bayesian_validation import (
    run_holdout_comparison, live_model_metrics, PROMOTION_CRITERIA, _score, _actual_vector,
)
from src.world_cup.models import WCHistoricalMatch, WCTeam, WCMatch, WCPrediction
from src.world_cup.predictor import MODEL_NAME

TEAMS = ["Alpha", "Bravo", "Charlie", "Delta"]


def _train_rows(n=800, seed=11):
    rng = np.random.default_rng(seed)
    base = dt.date(2023, 1, 1)
    rows = []
    for i in range(n):
        h, a = rng.choice(TEAMS, size=2, replace=False)
        rows.append(WCHistoricalMatch(
            date=(base + dt.timedelta(days=i)).isoformat(),
            home_team=str(h), away_team=str(a),
            home_goals=int(rng.poisson(1.4)), away_goals=int(rng.poisson(1.1)),
            match_weight=1.0, neutral_venue=0, tournament="Friendly"))
    return rows


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def _patch(module, session, monkeypatch):
    @contextmanager
    def fake():
        yield session
    monkeypatch.setattr(module, "get_session", fake)


# --------------------------------------------------------------- pure helpers
def test_actual_vector():
    assert _actual_vector(2, 0) == [1, 0, 0]
    assert _actual_vector(1, 1) == [0, 1, 0]
    assert _actual_vector(0, 3) == [0, 0, 1]


def test_score_perfect_vs_wrong():
    brier_good, ll_good, hit_good = _score([1.0, 0.0, 0.0], [1, 0, 0])
    assert brier_good == pytest.approx(0.0) and hit_good == 1
    brier_bad, ll_bad, hit_bad = _score([0.0, 0.0, 1.0], [1, 0, 0])
    assert brier_bad == pytest.approx(2.0) and hit_bad == 0
    assert ll_bad > ll_good   # confidently wrong is punished


# ------------------------------------------------------- Bayesian holdout eval
def test_bayesian_evaluate_holdout_splits_and_scores(session, monkeypatch):
    rows = _train_rows()
    base = dt.date(2022, 11, 1)             # all within the holdout window
    for i in range(50):
        h, a = TEAMS[i % 4], TEAMS[(i + 1) % 4]
        rows.append(WCHistoricalMatch(
            date=(base + dt.timedelta(days=i)).isoformat(),
            home_team=h, away_team=a,
            home_goals=i % 4, away_goals=(i + 1) % 3,
            match_weight=1.0, neutral_venue=1, tournament="FIFA World Cup"))
    session.add_all(rows)
    session.commit()
    _patch(bm, session, monkeypatch)

    m = BayesianPoissonModel(recency_halflife_days=1e9)
    res = m.evaluate_holdout(holdout_start="2022-11-01", holdout_end="2022-12-31")

    assert res["status"] == "ok"
    assert res["n_holdout"] == 50
    assert res["n_evaluated"] == 50              # all holdout teams are in the train index
    assert res["model"] == MODEL_NAME_BAYES
    assert 0.0 < res["brier"] < 2.0
    assert res["log_loss"] is not None and res["accuracy"] is not None


def test_bayesian_holdout_excludes_holdout_from_training(session, monkeypatch):
    # If a team appears ONLY in the holdout, it must not be in the trained index
    # (proves the holdout matches were excluded from the fit — temporal integrity).
    rows = _train_rows()
    base = dt.date(2022, 11, 1)
    for i in range(40):
        rows.append(WCHistoricalMatch(
            date=(base + dt.timedelta(days=i)).isoformat(),
            home_team="Alpha", away_team="HoldoutOnly",
            home_goals=1, away_goals=1, match_weight=1.0,
            neutral_venue=1, tournament="FIFA World Cup"))
    session.add_all(rows)
    session.commit()
    _patch(bm, session, monkeypatch)

    m = BayesianPoissonModel(recency_halflife_days=1e9)
    m.evaluate_holdout(holdout_start="2022-11-01", holdout_end="2022-12-31")
    assert "HoldoutOnly" not in m.team_idx   # never leaked into training


# --------------------------------------------------------- comparison verdict
def test_run_holdout_comparison_picks_lower_brier(monkeypatch):
    monkeypatch.setattr(
        val.WCPoissonPredictor, "evaluate_holdout",
        lambda self, *a, **k: {"brier": 0.58, "accuracy": 0.52, "n_evaluated": 46})
    monkeypatch.setattr(
        val.BayesianPoissonModel, "evaluate_holdout",
        lambda self, *a, **k: {"status": "ok", "brier": 0.60, "accuracy": 0.56, "n_evaluated": 64})
    out = run_holdout_comparison()
    assert out["poisson"]["brier"] == 0.58 and out["bayesian"]["brier"] == 0.60
    assert out["brier_winner"] == "poisson"        # 0.58 < 0.60
    assert out["brier_delta"] == pytest.approx(0.02)   # bayesian − poisson, +ve = worse


def test_run_holdout_comparison_survives_model_failure(monkeypatch):
    monkeypatch.setattr(
        val.WCPoissonPredictor, "evaluate_holdout",
        lambda self, *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(
        val.BayesianPoissonModel, "evaluate_holdout",
        lambda self, *a, **k: {"status": "ok", "brier": 0.6})
    out = run_holdout_comparison()          # must not raise
    assert out["poisson"] is None and out["bayesian"]["brier"] == 0.6
    assert "brier_winner" not in out         # can't compare with one side missing


# --------------------------------------------------------------- live metrics
def test_live_model_metrics(session, monkeypatch):
    session.add_all([
        WCTeam(id=1, name="A", fifa_code="A", confederation="X", group_letter="A"),
        WCTeam(id=2, name="B", fifa_code="B", confederation="X", group_letter="A"),
    ])
    session.add(WCMatch(id=1, stage="group", group_letter="A", date="2026-06-12",
                        kickoff_time="18:00", home_team_id=1, away_team_id=2,
                        status="finished", home_goals=2, away_goals=0))
    session.add(WCPrediction(match_id=1, model_name=MODEL_NAME,
                             home_win_prob=0.6, draw_prob=0.25, away_win_prob=0.15,
                             home_expected_goals=1.8, away_expected_goals=0.9))
    session.add(WCPrediction(match_id=1, model_name=MODEL_NAME_BAYES,
                             home_win_prob=0.5, draw_prob=0.3, away_win_prob=0.2,
                             home_expected_goals=1.5, away_expected_goals=1.0))
    session.commit()
    _patch(val, session, monkeypatch)

    out = live_model_metrics()
    assert out["n_matches"] == 1
    assert out["poisson"]["n"] == 1 and out["bayesian"]["n"] == 1
    # home won 2-0 → actual [1,0,0]; Poisson Brier = .4²+.25²+.15²
    assert out["poisson"]["brier"] == pytest.approx(0.4**2 + 0.25**2 + 0.15**2, abs=1e-4)
    assert out["poisson"]["accuracy"] == 1.0     # argmax = home = actual


def test_live_model_metrics_empty(session, monkeypatch):
    _patch(val, session, monkeypatch)
    out = live_model_metrics()
    assert out["n_matches"] == 0
    assert out["poisson"]["n"] == 0 and out["bayesian"]["n"] == 0


# ------------------------------------------------------------- promotion + UI
def test_promotion_criteria_is_manual():
    text = PROMOTION_CRITERIA.lower()
    assert "owner" in text and "never" in text
    assert "brier" in text          # criterion 1
    assert "clv" in text            # criterion 2


def test_dashboard_wires_comparison_panel():
    src = Path("src/delivery/views/world_cup.py").read_text()
    tree = ast.parse(src)
    funcs = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert "_render_model_comparison" in funcs
    assert "_cached_holdout" in funcs and "_cached_live_metrics" in funcs
    # called inside the Model tab
    assert "_render_model_comparison()" in src
