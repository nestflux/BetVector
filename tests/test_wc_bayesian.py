"""
WC-09-05 — Hierarchical Bayesian Poisson (scipy MAP + Laplace).

The headline validation is **synthetic recovery**: generate matches from known
team strengths, then confirm the MAP fit recovers the true ordering + home
advantage. Plus the matrix interface (Rule 6), uncertainty exposure, and guards.
All synthetic / in-memory — no real DB, no network.
"""

import datetime as dt
from contextlib import contextmanager

import numpy as np
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from src.database.db import Base
import src.world_cup.bayesian_model as bm
from src.world_cup.bayesian_model import BayesianPoissonModel, MODEL_NAME_BAYES
from src.world_cup.models import WCHistoricalMatch, WCTeam, WCMatch, WCPrediction
from src.world_cup.predictor import MODEL_NAME

# Known generative parameters — the model should recover their ORDERING.
TRUE_ATT = {"Alpha": 0.5, "Bravo": 0.05, "Charlie": -0.05, "Delta": -0.5}
TRUE_DEF = {"Alpha": 0.4, "Bravo": 0.0, "Charlie": 0.0, "Delta": -0.4}
TRUE_MU, TRUE_HA = 0.1, 0.30
TEAMS = list(TRUE_ATT)


def _synth_rows(n=800, seed=7):
    """Matches drawn from the true model: goals ~ Poisson(exp(μ + ha + att − def))."""
    rng = np.random.default_rng(seed)
    base = dt.date(2024, 1, 1)
    rows = []
    for i in range(n):
        h, a = rng.choice(TEAMS, size=2, replace=False)
        lh = np.exp(TRUE_MU + TRUE_HA + TRUE_ATT[h] - TRUE_DEF[a])
        la = np.exp(TRUE_MU + TRUE_ATT[a] - TRUE_DEF[h])
        rows.append(WCHistoricalMatch(
            date=(base + dt.timedelta(days=i)).isoformat(),
            home_team=str(h), away_team=str(a),
            home_goals=int(rng.poisson(lh)), away_goals=int(rng.poisson(la)),
            match_weight=1.0, neutral_venue=0))
    return rows


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def _fit(session, monkeypatch, rows=None):
    session.add_all(rows if rows is not None else _synth_rows())
    session.commit()

    @contextmanager
    def fake():
        yield session

    monkeypatch.setattr(bm, "get_session", fake)
    m = BayesianPoissonModel(recency_halflife_days=1e9)  # disable recency decay in tests
    return m, m.fit()


def _strength(m):
    T = len(m.teams)
    att, deff = m.params[2:2 + T], m.params[2 + T:]
    return {t: att[m.team_idx[t]] + deff[m.team_idx[t]] for t in TEAMS}


def test_fit_converges_and_posdef(session, monkeypatch):
    _m, info = _fit(session, monkeypatch)
    assert info["status"] == "ok"
    assert info["converged"] is True
    assert info["posdef"] is True   # valid Laplace covariance
    assert info["n_teams"] == 4


def test_recovers_team_strength_ordering(session, monkeypatch):
    m, _ = _fit(session, monkeypatch)
    s = _strength(m)
    assert s["Alpha"] > s["Bravo"] > s["Delta"]
    assert s["Alpha"] > s["Charlie"] > s["Delta"]
    assert max(s, key=s.get) == "Alpha"   # strongest recovered
    assert min(s, key=s.get) == "Delta"   # weakest recovered


def test_recovers_home_advantage(session, monkeypatch):
    _m, info = _fit(session, monkeypatch)
    assert 0.15 < info["home_adv"] < 0.45   # true value 0.30


def test_predict_returns_7x7_matrix_summing_to_one(session, monkeypatch):
    m, _ = _fit(session, monkeypatch)
    p = m.predict("Alpha", "Delta")
    assert len(p["matrix"]) == 7 and all(len(r) == 7 for r in p["matrix"])
    assert abs(sum(sum(r) for r in p["matrix"]) - 1.0) < 1e-6
    assert p["home_win_prob"] > p["away_win_prob"]   # strong home favoured
    for k in ("home_win_prob", "draw_prob", "away_win_prob",
              "over_25_prob", "btts_prob", "most_likely_score"):
        assert k in p


def test_uncertainty_interval_brackets_lambda(session, monkeypatch):
    m, _ = _fit(session, monkeypatch)
    p = m.predict("Alpha", "Bravo")
    lo, hi = p["lambda_home_ci"]
    assert lo > 0
    assert lo < p["lambda_home"] < hi   # credible interval brackets the point λ


def test_unknown_team_returns_none(session, monkeypatch):
    m, _ = _fit(session, monkeypatch)
    assert m.predict("Alpha", "Nowhere") is None
    assert m.predict("Nowhere", "Alpha") is None


def test_predict_before_fit_returns_none():
    assert BayesianPoissonModel().predict("Alpha", "Bravo") is None


def test_insufficient_data_returns_error(session, monkeypatch):
    _m, info = _fit(session, monkeypatch, rows=_synth_rows(n=50))
    assert info["status"] == "error"


def test_config_defaults_loaded():
    m = BayesianPoissonModel()
    assert m.prior_sd == 0.35
    assert m.recency_halflife_days == 1825
    assert m.rho == -0.05


def test_shadow_model_name_is_distinct_from_poisson():
    # The shadow model MUST use a different model_name so the value finder
    # (which reads only the Poisson MODEL_NAME) never picks up Bayesian rows.
    assert MODEL_NAME_BAYES == "wc_bayesian_v1"
    assert MODEL_NAME_BAYES != MODEL_NAME


def test_predict_all_shadow_stores_and_skips(session, monkeypatch):
    session.add_all(_synth_rows())
    session.add_all([
        WCTeam(id=1, name="Alpha", fifa_code="ALP", confederation="X", group_letter="A"),
        WCTeam(id=2, name="Bravo", fifa_code="BRV", confederation="X", group_letter="A"),
        WCTeam(id=3, name="Outsider", fifa_code="OUT", confederation="X", group_letter="A"),
    ])
    # match with both teams known to the model → stored
    session.add(WCMatch(id=10, stage="group", group_letter="A", date="2026-06-20",
                        kickoff_time="18:00", home_team_id=1, away_team_id=2, status="scheduled"))
    # match with a team never seen in training → skipped
    session.add(WCMatch(id=11, stage="group", group_letter="A", date="2026-06-21",
                        kickoff_time="18:00", home_team_id=1, away_team_id=3, status="scheduled"))
    session.commit()

    from contextlib import contextmanager

    @contextmanager
    def fake():
        yield session

    monkeypatch.setattr(bm, "get_session", fake)
    m = BayesianPoissonModel(recency_halflife_days=1e9)
    m.fit()

    stored = m.predict_all_shadow()
    assert stored == 1   # match 10 stored; match 11 skipped (Outsider not in index)

    rows = session.execute(
        select(WCPrediction).where(WCPrediction.model_name == MODEL_NAME_BAYES)
    ).scalars().all()
    assert len(rows) == 1 and rows[0].match_id == 10
    assert 0.0 < rows[0].home_win_prob < 1.0
    assert rows[0].home_expected_goals > 0


def test_usa_alias_resolves_to_historical_name(session, monkeypatch):
    # The host's WCTeam.name is "USA" but the historical dataset says
    # "United States" — the alias must bridge them so the host gets predictions.
    rows = _synth_rows()
    base = dt.date(2023, 1, 1)
    for i in range(60):  # give "United States" enough matches to enter the index
        rows.append(WCHistoricalMatch(
            date=(base + dt.timedelta(days=i)).isoformat(),
            home_team="United States", away_team="Alpha",
            home_goals=int(i % 3), away_goals=int((i + 1) % 3),
            match_weight=1.0, neutral_venue=0))
    session.add_all(rows)
    session.commit()

    from contextlib import contextmanager

    @contextmanager
    def fake():
        yield session

    monkeypatch.setattr(bm, "get_session", fake)
    m = BayesianPoissonModel(recency_halflife_days=1e9)
    m.fit()
    assert "United States" in m.team_idx and "USA" not in m.team_idx
    p = m.predict("USA", "Alpha")          # alias → "United States"
    assert p is not None and p["home_win_prob"] is not None


def test_shadow_run_leaves_poisson_row_untouched(session, monkeypatch):
    # The shadow must never overwrite the Poisson prediction for the same match.
    session.add_all(_synth_rows())
    session.add_all([
        WCTeam(id=1, name="Alpha", fifa_code="ALP", confederation="X", group_letter="A"),
        WCTeam(id=2, name="Bravo", fifa_code="BRV", confederation="X", group_letter="A"),
    ])
    session.add(WCMatch(id=10, stage="group", group_letter="A", date="2026-06-20",
                        kickoff_time="18:00", home_team_id=1, away_team_id=2, status="scheduled"))
    session.add(WCPrediction(id=99, match_id=10, model_name=MODEL_NAME,
                             home_win_prob=0.11, draw_prob=0.22, away_win_prob=0.67,
                             home_expected_goals=0.5, away_expected_goals=1.5, over_25_prob=0.40))
    session.commit()

    from contextlib import contextmanager

    @contextmanager
    def fake():
        yield session

    monkeypatch.setattr(bm, "get_session", fake)
    m = BayesianPoissonModel(recency_halflife_days=1e9)
    m.fit()
    m.predict_all_shadow()

    poisson = session.execute(
        select(WCPrediction).where(WCPrediction.match_id == 10,
                                   WCPrediction.model_name == MODEL_NAME)
    ).scalar_one()
    assert poisson.id == 99                       # same physical row
    assert (poisson.home_win_prob, poisson.draw_prob, poisson.away_win_prob) == (0.11, 0.22, 0.67)
    bayes = session.execute(
        select(WCPrediction).where(WCPrediction.match_id == 10,
                                   WCPrediction.model_name == MODEL_NAME_BAYES)
    ).scalar_one()
    assert bayes.id != 99                         # a distinct row, not an overwrite


def test_predict_all_shadow_is_idempotent(session, monkeypatch):
    session.add_all(_synth_rows())
    session.add_all([
        WCTeam(id=1, name="Alpha", fifa_code="ALP", confederation="X", group_letter="A"),
        WCTeam(id=2, name="Bravo", fifa_code="BRV", confederation="X", group_letter="A"),
    ])
    session.add(WCMatch(id=10, stage="group", group_letter="A", date="2026-06-20",
                        kickoff_time="18:00", home_team_id=1, away_team_id=2, status="scheduled"))
    session.commit()

    from contextlib import contextmanager

    @contextmanager
    def fake():
        yield session

    monkeypatch.setattr(bm, "get_session", fake)
    m = BayesianPoissonModel(recency_halflife_days=1e9)
    m.fit()

    m.predict_all_shadow()
    m.predict_all_shadow()   # second run must update, not duplicate (uq match_id+model_name)
    rows = session.execute(
        select(WCPrediction).where(WCPrediction.model_name == MODEL_NAME_BAYES)
    ).scalars().all()
    assert len(rows) == 1
