"""
WC-10-04 — focused pre-kickoff odds pull + run_prematch.

Verifies the per-event pull: one FREE /events lookup + exactly one PAID per-event
odds call (no full board refresh), idempotent upsert, the failure paths, and that
run_prematch re-derives value only on a successful pull.
"""

from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker

from src.database.db import Base
import src.world_cup.scraper as scraper
from src.world_cup.scraper import scrape_wc_match_odds
from src.world_cup.models import WCTeam, WCMatch, WCOdds


class _Resp:
    def __init__(self, status=200, data=None):
        self.status_code = status
        self._data = data
        self.headers = {"x-requests-remaining": "300"}
        self.text = ""

    def json(self):
        return self._data


EVENTS = [{"id": "evt123", "home_team": "Brazil", "away_team": "Scotland"},
          {"id": "evtOther", "home_team": "Spain", "away_team": "France"}]
EVENT_ODDS = {"home_team": "Brazil", "away_team": "Scotland",
              "bookmakers": [{"title": "Pinnacle", "markets": [
                  {"key": "h2h", "outcomes": [
                      {"name": "Brazil", "price": 1.5},
                      {"name": "Scotland", "price": 6.0},
                      {"name": "Draw", "price": 4.0}]}]}]}


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    s.add_all([
        WCTeam(id=1, name="Brazil", fifa_code="BRA", confederation="C", group_letter="A"),
        WCTeam(id=2, name="Scotland", fifa_code="SCO", confederation="U", group_letter="A"),
    ])
    s.add(WCMatch(id=13, stage="group", group_letter="A", date="2026-06-25",
                  kickoff_time="18:00", home_team_id=1, away_team_id=2, status="scheduled"))
    s.commit()
    yield s
    s.close()


def _patch(session, monkeypatch, events=EVENTS, odds=EVENT_ODDS):
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(url)
        if url.endswith("/events"):
            return _Resp(200, events)
        if "/events/" in url and url.endswith("/odds"):
            return _Resp(200, odds)
        return _Resp(404, [])

    monkeypatch.setattr(scraper.requests, "get", fake_get)
    monkeypatch.setattr(scraper, "_get_api_key", lambda: "key")
    monkeypatch.setattr(scraper, "_normalize_team_name", lambda n: n)

    @contextmanager
    def fake_session():
        yield session

    monkeypatch.setattr(scraper, "get_session", fake_session)
    return calls


def test_focused_pull_finds_event_and_stores(session, monkeypatch):
    calls = _patch(session, monkeypatch)
    res = scrape_wc_match_odds(13)
    assert res["status"] == "ok" and res["event_id"] == "evt123"
    assert res["odds_loaded"] == 3
    # exactly two HTTP calls: one free /events lookup, one paid per-event odds pull
    assert len(calls) == 2
    assert calls[0].endswith("/events")
    assert "events/evt123/odds" in calls[1]          # the target event only — no board pull
    n = session.execute(select(func.count()).select_from(WCOdds)
                        .where(WCOdds.match_id == 13)).scalar()
    assert n == 3


def test_idempotent_no_duplicates(session, monkeypatch):
    _patch(session, monkeypatch)
    scrape_wc_match_odds(13)
    scrape_wc_match_odds(13)                          # re-run
    n = session.execute(select(func.count()).select_from(WCOdds)
                        .where(WCOdds.match_id == 13)).scalar()
    assert n == 3                                     # upsert, not duplicated


def test_no_event_when_unmatched(session, monkeypatch):
    _patch(session, monkeypatch,
           events=[{"id": "x", "home_team": "Spain", "away_team": "France"}])
    assert scrape_wc_match_odds(13)["status"] == "no_event"


def test_no_match_for_unknown_id(session, monkeypatch):
    _patch(session, monkeypatch)
    assert scrape_wc_match_odds(999)["status"] == "no_match"


def test_events_error_short_circuits_before_paid_call(session, monkeypatch):
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(url)
        return _Resp(401, [])                        # /events returns 401

    monkeypatch.setattr(scraper.requests, "get", fake_get)
    monkeypatch.setattr(scraper, "_get_api_key", lambda: "key")
    monkeypatch.setattr(scraper, "_normalize_team_name", lambda n: n)

    @contextmanager
    def fs():
        yield session

    monkeypatch.setattr(scraper, "get_session", fs)
    assert scrape_wc_match_odds(13)["status"] == "events_error"
    assert len(calls) == 1                            # never reached the paid odds call


def test_no_key(session, monkeypatch):
    monkeypatch.setattr(scraper, "_get_api_key", lambda: "")
    assert scrape_wc_match_odds(13)["status"] == "no_key"


# ----------------------------------------------------------------- run_prematch
def test_run_prematch_recomputes_value_on_ok(monkeypatch):
    import src.world_cup.pipeline as pl
    monkeypatch.setattr("src.world_cup.scraper.scrape_wc_match_odds",
                        lambda mid: {"status": "ok", "remaining": "298"})
    monkeypatch.setattr("src.world_cup.value_finder.find_wc_value_bets", lambda: [object()])
    monkeypatch.setattr("src.world_cup.value_finder.save_wc_value_bets",
                        lambda vbs: {"new": 1, "total": 1})
    res = pl.run_prematch(13)
    assert res["odds_status"] == "ok" and res["value_bets"]["new"] == 1


def test_run_prematch_skips_value_on_failure(monkeypatch):
    import src.world_cup.pipeline as pl
    monkeypatch.setattr("src.world_cup.scraper.scrape_wc_match_odds",
                        lambda mid: {"status": "no_event"})
    called = {"value": False}

    def boom():
        called["value"] = True
        return []

    monkeypatch.setattr("src.world_cup.value_finder.find_wc_value_bets", boom)
    res = pl.run_prematch(13)
    assert res["odds_status"] == "no_event" and "value_bets" not in res
    assert called["value"] is False                   # no value recompute on a failed pull
