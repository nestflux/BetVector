"""
WC-10-01 — odds-refresh hardening.

Covers the three fixes: disciplined (budget-safe) scrape defaults, the fail-safe
upsert (a failed/empty scrape never wipes existing odds), and the loud SQLite
fallback warning (so an accidental local-DB write — the split-brain footgun — is
visible). Synthetic / in-memory.
"""

import logging
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker

from src.database.db import Base, _build_connection_url
import src.world_cup.scraper as scraper
from src.world_cup.scraper import _get_odds_scrape_cfg, scrape_wc_odds, _load_odds_to_db
from src.world_cup.models import WCTeam, WCMatch, WCOdds


class _Resp:
    def __init__(self, status=200, data=None):
        self.status_code = status
        self._data = data if data is not None else []
        self.headers = {"x-requests-remaining": "999"}
        self.text = ""

    def json(self):
        return self._data


# ---------------------------------------------- disciplined scrape (budget)
def test_odds_scrape_cfg_is_disciplined():
    cfg = _get_odds_scrape_cfg()
    assert cfg["markets"] == "h2h,totals"   # spreads dropped (unused by the model)
    assert cfg["regions"] == "eu"           # 1 region incl. Pinnacle → 2 credits/call


def test_scrape_uses_config_defaults(monkeypatch, tmp_path):
    """No-arg scrape must use the cheap config params, not the old 12-credit default."""
    captured = {}

    def fake_get(url, params=None, timeout=None):
        captured.update(params or {})
        return _Resp(200, [])

    monkeypatch.setattr(scraper.requests, "get", fake_get)
    monkeypatch.setattr(scraper, "_get_api_key", lambda: "key")
    monkeypatch.setattr(scraper, "DATA_DIR", tmp_path)
    monkeypatch.setattr(scraper, "_load_odds_to_db", lambda events: 0)

    scrape_wc_odds()
    assert captured["markets"] == "h2h,totals"
    assert captured["regions"] == "eu"
    assert "spreads" not in captured["markets"]   # the unused, costly market is gone


def test_explicit_params_still_override(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr(scraper.requests, "get",
                        lambda url, params=None, timeout=None: captured.update(params) or _Resp(200, []))
    monkeypatch.setattr(scraper, "_get_api_key", lambda: "key")
    monkeypatch.setattr(scraper, "DATA_DIR", tmp_path)
    monkeypatch.setattr(scraper, "_load_odds_to_db", lambda events: 0)
    scrape_wc_odds(markets="h2h", regions="uk")
    assert captured["markets"] == "h2h" and captured["regions"] == "uk"


# ---------------------------------------------- fail-safe (no destructive wipe)
def test_failed_scrape_returns_zero(monkeypatch, tmp_path):
    monkeypatch.setattr(scraper.requests, "get", lambda *a, **k: _Resp(500))
    monkeypatch.setattr(scraper, "_get_api_key", lambda: "key")
    monkeypatch.setattr(scraper, "DATA_DIR", tmp_path)
    assert scrape_wc_odds() == 0   # non-200 → 0, never reaches the DB


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def test_empty_events_preserve_existing_odds(session, monkeypatch):
    """An empty board must not delete existing odds — the loader is upsert-only."""
    session.add_all([
        WCTeam(id=1, name="Brazil", fifa_code="BRA", confederation="C", group_letter="A"),
        WCTeam(id=2, name="Scotland", fifa_code="SCO", confederation="U", group_letter="A"),
    ])
    session.add(WCMatch(id=1, stage="group", group_letter="A", date="2026-06-25",
                        kickoff_time="18:00", home_team_id=1, away_team_id=2, status="scheduled"))
    session.add(WCOdds(match_id=1, bookmaker="Pinnacle", market_type="h2h",
                       selection="Brazil", odds_decimal=1.5, opening_odds=1.5))
    session.commit()

    @contextmanager
    def fake():
        yield session

    monkeypatch.setattr(scraper, "get_session", fake)
    assert _load_odds_to_db([]) == 0
    assert session.execute(select(func.count()).select_from(WCOdds)).scalar() == 1


# ---------------------------------------------- loud SQLite fallback (visibility)
def test_sqlite_fallback_warns(monkeypatch, caplog):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with caplog.at_level(logging.WARNING, logger="src.database.db"):
        url = _build_connection_url()
    assert url.startswith("sqlite")
    assert any("SQLite" in r.message and "split-brain" in r.message for r in caplog.records)
