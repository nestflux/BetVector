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
    assert cfg["markets"] == "h2h,totals"   # lean per-event pull (spreads dropped)
    # Richer board pull adds btts + alternate_totals for the research comparison (DF-01)
    assert cfg["board_markets"] == "h2h,totals,btts,alternate_totals"
    assert cfg["regions"] == "eu"           # 1 region incl. Pinnacle → 2 credits/call


def test_scrape_uses_config_defaults(monkeypatch, tmp_path):
    """No-arg board scrape uses the richer board_markets set (DF-01) — still cheap:
    cost is markets × regions PER REQUEST and one request covers every match."""
    captured = {}

    def fake_get(url, params=None, timeout=None):
        captured.update(params or {})
        return _Resp(200, [])

    monkeypatch.setattr(scraper.requests, "get", fake_get)
    monkeypatch.setattr(scraper, "_get_api_key", lambda: "key")
    monkeypatch.setattr(scraper, "DATA_DIR", tmp_path)
    monkeypatch.setattr(scraper, "_load_odds_to_db", lambda events: 0)

    scrape_wc_odds()
    assert captured["markets"] == "h2h,totals,btts,alternate_totals"   # board pull
    assert captured["regions"] == "eu"
    assert "spreads" not in captured["markets"]   # the unused, costly market stays out


def test_board_vs_per_event_market_split():
    """Lock in DF-01's split: the board pull uses the richer board_markets, the
    focused per-event pull stays on the lean markets (protects CLV + budget)."""
    import inspect
    board_src = inspect.getsource(scraper.scrape_wc_odds)
    event_src = inspect.getsource(scraper.scrape_wc_match_odds)
    assert 'cfg["board_markets"]' in board_src
    assert 'cfg["markets"]' in event_src
    assert 'cfg["board_markets"]' not in event_src


def test_loader_bakes_alternate_totals_lines(monkeypatch):
    """alternate_totals quotes Over/Under at several points under one name; the
    loader must store each line distinctly (DF-01), not collapse them under the
    (match, book, market, selection) unique key."""
    from contextlib import contextmanager
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker
    from src.database.db import Base
    from src.world_cup.models import WCTeam, WCMatch, WCOdds

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    s.add_all([WCTeam(id=1, name="Brazil", fifa_code="BRA", confederation="C", group_letter="C"),
               WCTeam(id=2, name="Scotland", fifa_code="SCO", confederation="U", group_letter="C")])
    s.add(WCMatch(id=30, stage="group", group_letter="C", date="2026-06-25",
                  kickoff_time="18:00", home_team_id=1, away_team_id=2, status="scheduled"))
    s.commit()

    @contextmanager
    def fake():
        yield s
    monkeypatch.setattr(scraper, "get_session", fake)

    events = [{"home_team": "Brazil", "away_team": "Scotland", "bookmakers": [
        {"title": "Pinnacle", "markets": [{"key": "alternate_totals", "outcomes": [
            {"name": "Over", "price": 1.20, "point": 1.5},
            {"name": "Under", "price": 4.50, "point": 1.5},
            {"name": "Over", "price": 3.20, "point": 3.5},
            {"name": "Under", "price": 1.35, "point": 3.5},
        ]}]}]}]
    scraper._load_odds_to_db(events)

    rows = s.execute(select(WCOdds.selection).where(
        WCOdds.market_type == "alternate_totals")).scalars().all()
    assert len(rows) == 4                                         # none collapsed
    assert set(rows) == {"Over 1.5", "Under 1.5", "Over 3.5", "Under 3.5"}


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
