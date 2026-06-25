"""DH-04 — morning-pipeline data-health alert + integration scenario.

Two layers:
  1. Integration: seed a database that's actually broken (past-dated stale stubs, an
     upcoming fixture missing odds, a finished match with NULL goals) and prove the
     read-only engine catches each problem end-to-end.
  2. The alert wrapper: it emails the owner at/above the configured severity, escapes
     the body, is config-tunable, and NEVER raises (pipeline resilience).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.database.db import Base
from src.database.models import Match, Odds, Prediction  # noqa: F401  register tables
import src.world_cup.models  # noqa: F401

from src.monitoring.health_check import (
    CheckResult, FAIL, OK, SKIP, WARN, HealthReport, run_health_checks,
)
from src.monitoring import health_alert
from src.monitoring.health_alert import (
    _alert_worthy, build_alert_body_html, build_alert_subject, run_and_alert,
)

NOW = datetime(2026, 6, 24, 12, 0, 0)
_SEQ = [0]


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:",
                           connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sess = sessionmaker(bind=engine, expire_on_commit=False)()
    yield sess
    sess.close()


def _match(session, *, status, date, home_goals=None):
    _SEQ[0] += 1
    m = Match(league_id=1, season="2025-26", date=date, home_team_id=100 + _SEQ[0],
              away_team_id=900 + _SEQ[0], status=status, home_goals=home_goals)
    session.add(m)
    session.flush()
    return m


def _odds(session, match_id):
    session.add(Odds(match_id=match_id, bookmaker="Bet365", market_type="1X2",
                     selection="home", odds_decimal=2.0, implied_prob=0.5,
                     captured_at=NOW.isoformat()))
    session.flush()


def _prediction(session, match_id):
    session.add(Prediction(
        match_id=match_id, model_name="poisson_v1", model_version="1.0.0",
        predicted_home_goals=1.5, predicted_away_goals=1.2, scoreline_matrix="[]",
        prob_home_win=0.45, prob_draw=0.28, prob_away_win=0.27, prob_over_25=0.5,
        prob_under_25=0.5, prob_over_15=0.7, prob_under_15=0.3, prob_over_35=0.3,
        prob_under_35=0.7, prob_btts_yes=0.55, prob_btts_no=0.45,
        created_at=NOW.isoformat()))
    session.flush()


def _find(report, name):
    return next(c for c in report.checks if c.name == name)


# ---------------------------------------------------------------------------
# 1. Integration scenario — a genuinely broken database
# ---------------------------------------------------------------------------

def test_engine_catches_a_broken_database_end_to_end(session):
    # Two upcoming fixtures, only one with odds + a prediction → coverage gaps.
    good = _match(session, status="scheduled", date="2026-06-25")
    _odds(session, good.id)
    _prediction(session, good.id)
    _match(session, status="scheduled", date="2026-06-26")            # no odds, no pred
    # Two past-dated stubs still 'scheduled' → standings will be short.
    _match(session, status="scheduled", date="2026-06-20")
    _match(session, status="scheduled", date="2026-06-19")
    # A finished match with no score → corrupts the standings aggregation.
    _match(session, status="finished", date="2026-06-18", home_goals=None)

    report = run_health_checks(session=session, now=NOW,
                               env={"THE_ODDS_API_KEY": "x", "API_FOOTBALL_KEY": "x",
                                    "FOOTBALL_DATA_ORG_KEY": "x", "SOCCERDATA_API_KEY": "x"})

    stub = _find(report, "Stale scheduled stubs (leagues)")
    assert stub.status == WARN and stub.value == 2
    assert _find(report, "Finished matches have scores").status == FAIL      # NULL goals
    odds_cov = _find(report, "Odds coverage (next 7d)")
    assert odds_cov.status == WARN and odds_cov.value == pytest.approx(0.5)   # 1 of 2
    assert report.overall == FAIL                                            # the NULL-goal row


# ---------------------------------------------------------------------------
# 2. Alert wrapper
# ---------------------------------------------------------------------------

def _report(overall, checks=None):
    checks = checks or [
        CheckResult("Standings integrity", "Stale scheduled stubs (leagues)", WARN,
                    "2 past-dated fixtures still scheduled.", value=2),
        CheckResult("Connectivity", "Database reachable", OK, "ok"),
    ]
    return HealthReport("2026-06-24T12:00:00", "postgresql", overall, checks)


def test_alert_worthy_threshold():
    assert _alert_worthy(WARN, "warn") and _alert_worthy(FAIL, "warn")
    assert not _alert_worthy(OK, "warn") and not _alert_worthy(SKIP, "warn")
    assert _alert_worthy(FAIL, "fail") and not _alert_worthy(WARN, "fail")


def test_subject_and_body_summarise_and_escape():
    rep = _report(FAIL, [
        CheckResult("Standings integrity", "<b>Stale</b> stubs", FAIL,
                    "<script>x</script> results missing", value=3),
    ])
    assert "FAIL" in build_alert_subject(rep)
    body = build_alert_body_html(rep)
    assert "Stale" in body and "results missing" in body
    assert "<script>" not in body and "<b>Stale" not in body          # escaped
    assert "&lt;script&gt;" in body and "make health" in body


def test_run_and_alert_sends_on_warn_and_records_summary():
    sent = []
    rc = run_and_alert(send_alert_fn=lambda uid, s, b: sent.append((uid, s, b)) or True,
                       user_id=1, report=_report(WARN))
    assert rc["alerted"] and rc["sent"] and rc["overall"] == "warn"
    assert rc["n_warn"] == 1 and len(sent) == 1 and sent[0][0] == 1


def test_run_and_alert_quiet_when_healthy():
    sent = []
    rc = run_and_alert(send_alert_fn=lambda *a: sent.append(a) or True, user_id=1,
                       report=_report(OK, [CheckResult("C", "ok", OK, "fine")]))
    assert rc["alerted"] is False and rc["sent"] is False and not sent


def test_run_and_alert_respects_fail_only_override():
    sent = []
    rc = run_and_alert(send_alert_fn=lambda *a: sent.append(a) or True, user_id=1,
                       report=_report(WARN), config_override={"alert": {"min_status": "fail"}})
    assert rc["alerted"] is False and not sent          # warn doesn't reach a fail-only owner


def test_run_and_alert_never_raises_when_send_fails():
    def _boom(*_a):
        raise RuntimeError("smtp down")
    rc = run_and_alert(send_alert_fn=_boom, user_id=1, report=_report(FAIL))
    assert rc["alerted"] is True and rc["sent"] is False   # swallowed, pipeline survives


# ---------------------------------------------------------------------------
# 3. Pipeline hook is wired (source-level) + guarded
# ---------------------------------------------------------------------------

def test_resolve_owner_id_falls_back_to_one(monkeypatch):
    import src.database.db as db

    def _boom():
        raise RuntimeError("no database")
    monkeypatch.setattr(db, "get_session", _boom)
    assert health_alert._resolve_owner_id() == 1   # guarded → safe default owner


def test_morning_pipeline_invokes_the_guarded_alert():
    src = (Path(__file__).resolve().parents[1] / "src" / "pipeline.py").read_text()
    assert "from src.monitoring.health_alert import run_and_alert" in src
    assert "# --- DH-04:" in src
    hook = src[src.index("# --- DH-04:"):src.index("# --- DH-04:") + 800]
    # the call must sit inside a guarded try/except so it never breaks the run
    assert "try:" in hook and "run_and_alert()" in hook and "non-fatal" in hook
