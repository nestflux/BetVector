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


@pytest.fixture(autouse=True)
def _stub_lineup_fetch(monkeypatch):
    """Keep dispatcher tests hermetic: by default the lineup pass never hits ESPN
    or the DB. Lineup-specific tests override this with their own stub."""
    monkeypatch.setattr(disp, "_fetch_lineup", lambda mid: {"status": "skip"})


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


# ----------------------------------------------------------- lineup pass (WC-10-06)
def test_lineup_pass_captures_in_wider_window(paths, monkeypatch):
    """The lineup window [KO−60, KO) is wider than the odds window [KO−40, KO):
    at KO−50 the lineup is fetched but odds are NOT yet fired."""
    cache, state = paths
    _write_cache(cache, [_fx(13, KO)])
    monkeypatch.setattr(disp, "_fire_prematch", lambda mid: None)
    got = []
    monkeypatch.setattr(disp, "_fetch_lineup", lambda mid: got.append(mid) or {"status": "ok"})
    res = disp.run_dispatcher(now=KO - dt.timedelta(minutes=50))
    assert res["lineups"] == 1 and got == [13]
    assert res["fired"] == 0                                  # KO−50 is outside [KO−40, KO)
    assert json.loads(state.read_text())["lineups"] == [13]


def test_lineup_retries_until_published(paths, monkeypatch):
    cache, _ = paths
    _write_cache(cache, [_fx(13, KO)])
    monkeypatch.setattr(disp, "_fire_prematch", lambda mid: None)
    calls = {"n": 0}

    def fetch(mid):
        calls["n"] += 1
        return {"status": "ok"} if calls["n"] >= 2 else {"status": "no_lineup_yet"}

    monkeypatch.setattr(disp, "_fetch_lineup", fetch)
    now = KO - dt.timedelta(minutes=50)
    assert disp.run_dispatcher(now=now)["lineups"] == 0                       # XI not out yet
    assert disp.run_dispatcher(now=now + dt.timedelta(minutes=15))["lineups"] == 1  # now out
    assert calls["n"] == 2                                    # retried each tick until ok


def test_lineup_captured_only_once(paths, monkeypatch):
    cache, _ = paths
    _write_cache(cache, [_fx(13, KO)])
    monkeypatch.setattr(disp, "_fire_prematch", lambda mid: None)
    n = {"calls": 0}

    def fetch(mid):
        n["calls"] += 1
        return {"status": "ok"}

    monkeypatch.setattr(disp, "_fetch_lineup", fetch)
    now = KO - dt.timedelta(minutes=50)
    disp.run_dispatcher(now=now)                              # captures
    disp.run_dispatcher(now=now + dt.timedelta(minutes=15))   # already done → no re-fetch
    assert n["calls"] == 1
