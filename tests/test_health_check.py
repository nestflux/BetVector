"""DH-01 — Data Health check engine.

The engine is read-only: every check is a SELECT. These tests seed a fresh in-memory
SQLite database (one shared connection via StaticPool), exercise each check in
isolation with a fixed ``now`` for deterministic freshness, and prove the pure helpers
(ISO parsing, freshness banding, config resolution, overall verdict). FK constraints
are not enforced on the test engine, so rows can be seeded with minimal columns.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.database.db import Base
# Import the ORM models so every table registers on Base before create_all.
from src.database.models import Match, Odds, Prediction, PipelineRun  # noqa: F401
import src.world_cup.models  # noqa: F401  (registers wc_* tables)
from src.world_cup.models import WCMatch

from src.monitoring import health_check as hc
from src.monitoring.health_check import (
    CheckResult, FAIL, OK, SKIP, WARN,
    _age_hours, _overall, _parse_iso, resolve_config, run_health_checks,
)

NOW = datetime(2026, 6, 24, 12, 0, 0)
ALL_KEYS = {k: "x" for k in hc._INGESTION_KEYS}  # env with every ingestion key present


@pytest.fixture
def session():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False},
        poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    sess = Session()
    yield sess
    sess.close()


def _iso(dt: datetime) -> str:
    return dt.isoformat()


_MATCH_SEQ = [0]


def _match(session, *, status="scheduled", date="2026-06-25", league_id=1,
           home_goals=None, away_goals=None, updated_at=None):
    # Auto-unique team ids so every seeded match has a distinct
    # (league_id, date, home_team_id, away_team_id) key (FKs aren't enforced here).
    _MATCH_SEQ[0] += 1
    m = Match(league_id=league_id, season="2025-26", date=date,
              home_team_id=100 + _MATCH_SEQ[0], away_team_id=900 + _MATCH_SEQ[0],
              status=status, home_goals=home_goals, away_goals=away_goals)
    if updated_at:
        m.updated_at = updated_at
    session.add(m)
    session.flush()
    return m


def _odds(session, match_id, captured_at):
    session.add(Odds(match_id=match_id, bookmaker="Bet365", market_type="1X2",
                     selection="home", odds_decimal=2.0, implied_prob=0.5,
                     captured_at=captured_at))
    session.flush()


def _prediction(session, match_id, created_at=None):
    p = Prediction(
        match_id=match_id, model_name="poisson_v1", model_version="1.0.0",
        predicted_home_goals=1.5, predicted_away_goals=1.2, scoreline_matrix="[]",
        prob_home_win=0.45, prob_draw=0.28, prob_away_win=0.27,
        prob_over_25=0.5, prob_under_25=0.5, prob_over_15=0.7, prob_under_15=0.3,
        prob_over_35=0.3, prob_under_35=0.7, prob_btts_yes=0.55, prob_btts_no=0.45)
    if created_at:
        p.created_at = created_at
    session.add(p)
    session.flush()


def _pipeline_run(session, *, status="completed", started_at, run_type="morning",
                  predictions_made=40, value_bets_found=8, error_message=None):
    session.add(PipelineRun(run_type=run_type, status=status, started_at=started_at,
                            predictions_made=predictions_made,
                            value_bets_found=value_bets_found, error_message=error_message))
    session.flush()


def _find(report_or_list, name):
    checks = report_or_list.checks if hasattr(report_or_list, "checks") else report_or_list
    return next(c for c in checks if c.name == name)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw", [
    "2026-06-24T12:00:00", "2026-06-24 12:00:00", "2026-06-24T12:00:00.123456",
    "2026-06-24 12:00:00.123456", "2026-06-24T12:00:00Z", "2026-06-24T12:00:00+00:00",
    "2026-06-24T12:00:00-04:00", "2026-06-24 12:00:00.123456+00",
])
def test_parse_iso_handles_every_stored_format(raw):
    parsed = _parse_iso(raw)
    assert parsed is not None and parsed.year == 2026 and parsed.hour == 12


def test_parse_iso_date_only_and_garbage():
    assert _parse_iso("2026-06-24").day == 24
    assert _parse_iso("not-a-date") is None
    assert _parse_iso(None) is None and _parse_iso("") is None


def test_age_hours_and_future_clamps_to_zero():
    assert _age_hours(_iso(NOW - timedelta(hours=5)), NOW) == pytest.approx(5.0, abs=0.01)
    assert _age_hours(_iso(NOW + timedelta(hours=3)), NOW) == 0.0   # clock skew → fresh
    assert _age_hours("garbage", NOW) is None


def test_overall_is_the_worst_status():
    mk = lambda s: CheckResult("g", "n", s, "")
    assert _overall([mk(OK), mk(SKIP)]) == OK
    assert _overall([mk(OK), mk(WARN)]) == WARN
    assert _overall([mk(WARN), mk(FAIL)]) == FAIL
    assert _overall([mk(SKIP)]) == OK


def test_resolve_config_defaults_and_override():
    cfg = resolve_config()
    assert cfg["coverage"]["upcoming_days"] >= 1
    assert cfg["freshness_hours"]["live"]["warn"] < cfg["freshness_hours"]["live"]["fail"]
    over = resolve_config({"coverage": {"min_odds_pct": 0.99}})
    assert over["coverage"]["min_odds_pct"] == 0.99
    # deep-merge leaves siblings intact
    assert over["coverage"]["upcoming_days"] == cfg["coverage"]["upcoming_days"]


# ---------------------------------------------------------------------------
# Standings integrity — the reason this engine exists
# ---------------------------------------------------------------------------

def test_stale_stub_detector_is_the_standings_tripwire(session):
    cfg = resolve_config()
    # No stale stubs → OK.
    _match(session, status="scheduled", date="2026-06-26")          # future, fine
    _match(session, status="finished", date="2026-06-20", home_goals=2, away_goals=1)
    assert hc._check_stale_stubs(session, NOW, cfg).status == OK
    # One past-dated scheduled stub → WARN.
    _match(session, status="scheduled", date="2026-06-20")
    res = hc._check_stale_stubs(session, NOW, cfg)
    assert res.status == WARN and res.value == 1
    # Crossing the fail count → FAIL.
    for _ in range(cfg["standings"]["stale_stub_fail_count"]):
        _match(session, status="scheduled", date="2026-06-19")
    assert hc._check_stale_stubs(session, NOW, cfg).status == FAIL


def test_corrupt_finished_results_fail(session):
    assert hc._check_corrupt_results(session).status == OK
    _match(session, status="finished", date="2026-06-20", home_goals=2, away_goals=0)
    assert hc._check_corrupt_results(session).status == OK
    _match(session, status="finished", date="2026-06-21", home_goals=None)  # corrupt
    res = hc._check_corrupt_results(session)
    assert res.status == FAIL and res.value == 1


# ---------------------------------------------------------------------------
# Coverage + freshness
# ---------------------------------------------------------------------------

def test_upcoming_coverage_flags_missing_odds_and_preds(session):
    cfg = resolve_config()
    m1 = _match(session, status="scheduled", date="2026-06-25")
    m2 = _match(session, status="scheduled", date="2026-06-26")
    _odds(session, m1.id, _iso(NOW))
    _prediction(session, m1.id, _iso(NOW))
    # m2 has neither odds nor prediction → 50% coverage on each → below targets → WARN.
    out = hc._check_upcoming_coverage(session, NOW, cfg)
    odds_c = next(c for c in out if "Odds coverage" in c.name)
    pred_c = next(c for c in out if "Prediction coverage" in c.name)
    assert odds_c.status == WARN and odds_c.value == pytest.approx(0.5)
    assert pred_c.status == WARN and pred_c.value == pytest.approx(0.5)


def test_upcoming_coverage_skips_when_no_fixtures(session):
    out = hc._check_upcoming_coverage(session, NOW, resolve_config())
    assert len(out) == 1 and out[0].status == SKIP


def test_source_freshness_bands_on_age(session):
    cfg = resolve_config()
    _match(session, status="scheduled", date="2026-06-26")  # leagues active → odds judged
    m = _match(session, status="finished", date="2026-06-20", home_goals=1, away_goals=1)
    _odds(session, m.id, _iso(NOW - timedelta(hours=1)))   # fresh (live warn=6h)
    fresh = _find(hc._check_source_freshness(session, NOW, cfg), "Bookmaker odds")
    assert fresh.status == OK
    # Clear and re-seed so the *latest* odds row is old → max() age 100h → FAIL.
    session.query(Odds).delete()
    session.flush()
    _odds(session, m.id, _iso(NOW - timedelta(hours=100)))
    stale = _find(hc._check_source_freshness(session, NOW, cfg), "Bookmaker odds")
    assert stale.status == FAIL


def test_source_freshness_skips_empty_tables(session):
    res = hc._check_source_freshness(session, NOW, resolve_config())
    assert all(c.status == SKIP for c in res)  # nothing ingested yet


def test_source_freshness_is_season_aware(session):
    cfg = resolve_config()
    old = _iso(NOW - timedelta(days=10))
    # Dormant: a finished match well in the past, nothing upcoming → off-season.
    m = _match(session, status="finished", date="2026-06-10",
               home_goals=1, away_goals=0, updated_at=old)
    _prediction(session, m.id, created_at=old)
    res = hc._check_source_freshness(session, NOW, cfg)
    assert _find(res, "Match results & fixtures").status == SKIP  # gated + dormant
    assert _find(res, "Model predictions").status == SKIP
    # Add an upcoming fixture → leagues active → gated sources judged on age again.
    _match(session, status="scheduled", date="2026-06-26")
    res2 = hc._check_source_freshness(session, NOW, cfg)
    assert _find(res2, "Model predictions").status == FAIL        # preds still 10 days old


def test_odds_budget_thresholds(session, tmp_path):
    cfg = resolve_config()
    p = tmp_path / "budget.json"
    assert hc._check_odds_budget(cfg, p).status == SKIP            # missing file
    p.write_text(json.dumps({"remaining": 300}))
    assert hc._check_odds_budget(cfg, p).status == OK
    p.write_text(json.dumps({"remaining": cfg["odds_api"]["warn_remaining"] - 1}))
    assert hc._check_odds_budget(cfg, p).status == WARN
    p.write_text(json.dumps({"remaining": cfg["odds_api"]["fail_remaining"] - 1}))
    assert hc._check_odds_budget(cfg, p).status == FAIL


# ---------------------------------------------------------------------------
# Connectivity + pipeline + world cup
# ---------------------------------------------------------------------------

def test_backend_check_warns_on_sqlite(session):
    res = hc._check_backend(session)
    assert res.status == WARN and res.value == "sqlite"


def test_api_keys_check(session):
    assert hc._check_api_keys(ALL_KEYS).status == OK
    missing = dict(ALL_KEYS)
    del missing["THE_ODDS_API_KEY"]
    res = hc._check_api_keys(missing)
    assert res.status == WARN and "THE_ODDS_API_KEY" in res.detail


def test_last_pipeline_run_states(session):
    cfg = resolve_config()
    _match(session)  # in-season: an upcoming league fixture so the check isn't season-skipped
    assert hc._check_last_pipeline_run(session, NOW, cfg).status == SKIP   # none yet
    _pipeline_run(session, status="completed", started_at=_iso(NOW - timedelta(hours=2)))
    assert hc._check_last_pipeline_run(session, NOW, cfg).status == OK
    _pipeline_run(session, status="failed", started_at=_iso(NOW - timedelta(hours=1)),
                  error_message="FBref 403")
    assert hc._check_last_pipeline_run(session, NOW, cfg).status == FAIL   # latest = failed


def test_last_pipeline_run_overdue_and_empty(session):
    cfg = resolve_config()
    _match(session)  # in-season fixture so the overdue check actually fires (not season-skipped)
    _pipeline_run(session, status="completed",
                  started_at=_iso(NOW - timedelta(hours=40)), predictions_made=10)
    assert hc._check_last_pipeline_run(session, NOW, cfg).status == WARN   # overdue ≥26h


def test_last_pipeline_run_skips_off_season(session):
    """Off-season: no recent/upcoming league fixtures, so the league morning pipeline
    is intentionally paused — the check SKIPs rather than crying WARN, even with a
    long-overdue run still on the ledger (the DH-01 "activity-aware" rule)."""
    cfg = resolve_config()
    _pipeline_run(session, status="completed",
                  started_at=_iso(NOW - timedelta(hours=200)))
    # No active league fixtures seeded → _leagues_active is False → SKIP.
    assert hc._check_last_pipeline_run(session, NOW, cfg).status == SKIP


def test_world_cup_checks_skip_without_data_and_flag_stale_stubs(session):
    cfg = resolve_config()
    # No WC matches → a single SKIP.
    res = hc._check_world_cup(session, NOW, cfg)
    assert len(res) == 1 and res[0].status == SKIP
    # A past-dated scheduled WC fixture → stale-stub WARN.
    session.add(WCMatch(date="2026-06-20", home_team_id=1, away_team_id=2,
                        status="scheduled", stage="group", group_letter="C"))
    session.flush()
    res = hc._check_world_cup(session, NOW, cfg)
    stub = next(c for c in res if "Stale WC stubs" in c.name)
    assert stub.status == WARN and stub.value == 1


# ---------------------------------------------------------------------------
# End-to-end runner
# ---------------------------------------------------------------------------

def test_run_health_checks_assembles_full_report(session, tmp_path):
    m = _match(session, status="scheduled", date="2026-06-25")
    _odds(session, m.id, _iso(NOW))
    _prediction(session, m.id, _iso(NOW))
    _pipeline_run(session, status="completed", started_at=_iso(NOW - timedelta(hours=2)))
    budget = tmp_path / "b.json"
    budget.write_text(json.dumps({"remaining": 300}))

    report = run_health_checks(session=session, now=NOW, env=ALL_KEYS,
                               odds_budget_path=budget)
    groups = report.by_group()
    assert {"Connectivity", "Source freshness", "Coverage", "Standings integrity",
            "Pipeline"} <= set(groups)
    assert _find(report, "Database reachable").status == OK
    assert _find(report, "Stale scheduled stubs (leagues)").status == OK
    assert _find(report, "Last morning run").status == OK
    # Healthy data, but the test runs on SQLite → backend WARN drives overall to warn.
    assert report.overall == WARN
    assert _find(report, "Database backend").status == WARN
    assert report.summary()[OK] >= 4


def test_run_health_checks_reports_db_unreachable(monkeypatch):
    def _boom():
        raise RuntimeError("no database")
    monkeypatch.setattr(hc, "get_session", _boom)
    report = run_health_checks(now=NOW, env=ALL_KEYS)
    assert report.overall == FAIL
    assert _find(report, "Database reachable").status == FAIL
