"""
WC-10-03 — pre-kickoff dispatcher.

Covers the heartbeat window logic (fire only inside [KO−40, KO)), once-only
firing via persisted prepped-state, the automatic daily reset, the cache
round-trip, and the key free-tier guarantee: the idle path opens no Neon
connection. All local-json / in-memory.
"""

import datetime as dt
import json
from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import src.world_cup.dispatcher as disp
from src.database.db import Base
from src.world_cup.models import WCTeam, WCMatch

UTC = dt.timezone.utc
KO = dt.datetime(2026, 6, 24, 17, 0, tzinfo=UTC)


@pytest.fixture
def paths(tmp_path, monkeypatch):
    cache = tmp_path / "today_fixtures.json"
    state = tmp_path / "dispatcher_state.json"
    monkeypatch.setattr(disp, "CACHE_PATH", cache)
    monkeypatch.setattr(disp, "STATE_PATH", state)
    return cache, state


def _write_cache(cache: Path, fixtures):
    cache.write_text(json.dumps({"written_at": "x", "fixtures": fixtures}))


def _fx(mid, ko, home="A", away="B"):
    return {"match_id": mid, "kickoff_utc": ko.isoformat(),
            "status": "scheduled", "home": home, "away": away}


def test_fires_inside_window(paths, monkeypatch):
    cache, _ = paths
    _write_cache(cache, [_fx(13, KO)])
    fired = []
    monkeypatch.setattr(disp, "_fire_prematch", fired.append)
    res = disp.run_dispatcher(now=KO - dt.timedelta(minutes=30))   # inside [KO−40, KO)
    assert res["fired"] == 1 and res["match_ids"] == [13] and fired == [13]


def test_no_fire_before_or_after_window(paths, monkeypatch):
    cache, _ = paths
    _write_cache(cache, [_fx(13, KO)])
    fired = []
    monkeypatch.setattr(disp, "_fire_prematch", fired.append)
    assert disp.run_dispatcher(now=KO - dt.timedelta(hours=2))["fired"] == 0   # too early
    assert disp.run_dispatcher(now=KO + dt.timedelta(minutes=5))["fired"] == 0  # past KO
    assert fired == []


def test_fires_exactly_once(paths, monkeypatch):
    cache, state = paths
    _write_cache(cache, [_fx(13, KO)])
    fired = []
    monkeypatch.setattr(disp, "_fire_prematch", fired.append)
    now = KO - dt.timedelta(minutes=30)
    disp.run_dispatcher(now=now)                                  # fires
    disp.run_dispatcher(now=now + dt.timedelta(minutes=15))       # next tick, still in window
    assert fired == [13]                                          # only once
    assert json.loads(state.read_text())["prepped"] == [13]


def test_idle_never_fires(paths, monkeypatch):
    cache, _ = paths
    _write_cache(cache, [_fx(13, KO)])
    fired = []
    monkeypatch.setattr(disp, "_fire_prematch", fired.append)
    disp.run_dispatcher(now=KO - dt.timedelta(hours=3))           # nothing imminent
    assert fired == []


def test_idle_path_opens_no_neon(paths, monkeypatch):
    """The free-tier guarantee: an idle heartbeat opens no DB connection."""
    import src.database.db as db
    called = {"session": False}

    def boom(*a, **k):
        called["session"] = True
        raise AssertionError("get_session must not be called on the idle path")

    monkeypatch.setattr(db, "get_session", boom)
    cache, _ = paths
    _write_cache(cache, [_fx(13, KO)])
    disp.run_dispatcher(now=KO - dt.timedelta(hours=3))           # idle tick
    assert called["session"] is False


def test_prepped_state_resets_next_day(paths, monkeypatch):
    cache, state = paths
    _write_cache(cache, [_fx(13, KO)])
    state.write_text(json.dumps({"date": "2026-06-23", "prepped": [13]}))  # yesterday
    fired = []
    monkeypatch.setattr(disp, "_fire_prematch", fired.append)
    disp.run_dispatcher(now=KO - dt.timedelta(minutes=30))        # today is 2026-06-24
    assert fired == [13]                                          # stale day ignored → fires


def test_no_cache_is_noop(paths, monkeypatch):
    fired = []
    monkeypatch.setattr(disp, "_fire_prematch", fired.append)
    res = disp.run_dispatcher(now=KO)                             # cache file absent
    assert res["fired"] == 0 and res.get("reason") == "no_cache" and fired == []


def test_write_fixture_cache_roundtrip(paths, monkeypatch):
    cache, _ = paths
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    s.add_all([
        WCTeam(id=1, name="Brazil", fifa_code="BRA", confederation="C", group_letter="A"),
        WCTeam(id=2, name="Scotland", fifa_code="SCO", confederation="U", group_letter="A"),
    ])
    s.add(WCMatch(id=13, stage="group", group_letter="A", date="2026-06-24",
                  kickoff_time="17:00", home_team_id=1, away_team_id=2, status="scheduled"))
    s.add(WCMatch(id=99, stage="group", group_letter="A", date="2026-06-20",
                  kickoff_time="17:00", home_team_id=1, away_team_id=2, status="finished"))
    s.commit()

    import src.database.db as db

    @contextmanager
    def fake():
        yield s

    monkeypatch.setattr(db, "get_session", fake)
    n = disp.write_fixture_cache(cache)
    assert n == 1                                                 # finished match excluded
    fx = json.loads(cache.read_text())["fixtures"][0]
    assert fx["match_id"] == 13 and fx["home"] == "Brazil"
    assert fx["kickoff_utc"] == "2026-06-24T17:00:00+00:00"

    # the dispatcher can read what the morning run wrote, and fires in-window
    fired = []
    monkeypatch.setattr(disp, "_fire_prematch", fired.append)
    disp.run_dispatcher(now=KO - dt.timedelta(minutes=20))
    assert fired == [13]
