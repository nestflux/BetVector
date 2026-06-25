"""ESPN WC results backfill + self-heal (results_espn.py).

Mocks ESPN's scoreboard JSON and uses an in-memory DB to verify: parsing of
completed/incomplete/malformed events; backfill create vs update (in BOTH home/away
orientations); cross-group (knockout) skip; unmapped-name reporting; idempotency;
the ESPN→DB name-map extensions; and that the pipeline self-heal never raises.
No network. No live DB.
"""
from contextlib import contextmanager
from datetime import date

import pytest
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker

from src.database.db import Base
import src.world_cup.results_espn as rmod
from src.world_cup.results_espn import (
    fetch_espn_results_for_date,
    backfill_wc_results_espn,
    self_heal_wc_results,
)
from src.world_cup.lineups import _to_db_name
from src.world_cup.models import WCTeam, WCMatch


class _Resp:
    def __init__(self, status=200, data=None):
        self.status_code = status
        self._data = data if data is not None else {}

    def json(self):
        return self._data


def _event(home, away, hs, as_, completed=True, dt="2026-06-14T18:00Z"):
    return {
        "date": dt,
        "status": {"type": {"completed": completed}},
        "competitions": [{"competitors": [
            {"homeAway": "home", "score": hs, "team": {"displayName": home}},
            {"homeAway": "away", "score": as_, "team": {"displayName": away}},
        ]}],
    }


def _scoreboard(*events):
    return {"events": list(events)}


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    s.add_all([
        WCTeam(id=1, name="Brazil", fifa_code="BRA", confederation="C", group_letter="C"),
        WCTeam(id=2, name="Scotland", fifa_code="SCO", confederation="U", group_letter="C"),
        WCTeam(id=3, name="Germany", fifa_code="GER", confederation="U", group_letter="E"),
        WCTeam(id=4, name="Ivory Coast", fifa_code="CIV", confederation="A", group_letter="E"),
    ])
    # One existing (scheduled) group match for the update-path tests.
    s.add(WCMatch(id=50, stage="group", group_letter="C", date="2026-06-19",
                  home_team_id=1, away_team_id=2, status="scheduled"))
    s.commit()
    yield s
    s.close()


def _use_session(monkeypatch, session):
    @contextmanager
    def fake():
        yield session
    monkeypatch.setattr(rmod, "get_session", fake)


def _mock_results(monkeypatch, rows):
    monkeypatch.setattr(rmod, "fetch_espn_results_for_date", lambda d: list(rows))


# ---- fetch parsing -------------------------------------------------------

def test_fetch_parses_completed_match(monkeypatch):
    monkeypatch.setattr(rmod.requests, "get",
                        lambda *a, **k: _Resp(200, _scoreboard(_event("Germany", "Ivory Coast", "2", "1"))))
    out = fetch_espn_results_for_date(date(2026, 6, 14))
    assert len(out) == 1
    assert out[0]["home_name"] == "Germany" and out[0]["away_name"] == "Ivory Coast"
    assert out[0]["home_goals"] == 2 and out[0]["away_goals"] == 1


def test_fetch_skips_incomplete(monkeypatch):
    monkeypatch.setattr(rmod.requests, "get",
                        lambda *a, **k: _Resp(200, _scoreboard(_event("A", "B", "0", "0", completed=False))))
    assert fetch_espn_results_for_date(date(2026, 6, 14)) == []


def test_fetch_skips_malformed_score(monkeypatch):
    monkeypatch.setattr(rmod.requests, "get",
                        lambda *a, **k: _Resp(200, _scoreboard(_event("A", "B", None, "1"))))
    assert fetch_espn_results_for_date(date(2026, 6, 14)) == []


def test_fetch_http_error_returns_empty(monkeypatch):
    monkeypatch.setattr(rmod.requests, "get", lambda *a, **k: _Resp(503, {}))
    assert fetch_espn_results_for_date(date(2026, 6, 14)) == []


def test_fetch_network_error_returns_empty(monkeypatch):
    def boom(*a, **k):
        raise ConnectionError("down")
    monkeypatch.setattr(rmod.requests, "get", boom)
    assert fetch_espn_results_for_date(date(2026, 6, 14)) == []


# ---- backfill upsert -----------------------------------------------------

def test_backfill_creates_missing_match(monkeypatch, session):
    _use_session(monkeypatch, session)
    _mock_results(monkeypatch, [{"home_name": "Germany", "away_name": "Ivory Coast",
                                 "home_goals": 2, "away_goals": 1, "date": "2026-06-20"}])
    res = backfill_wc_results_espn("2026-06-20", "2026-06-20")
    assert res["created"] == 1 and res["updated"] == 0
    m = session.execute(select(WCMatch).where(WCMatch.home_team_id == 3,
                                              WCMatch.away_team_id == 4)).scalar_one()
    assert m.status == "finished" and m.home_goals == 2 and m.away_goals == 1
    assert m.stage == "group" and m.group_letter == "E"


def test_backfill_updates_same_orientation(monkeypatch, session):
    _use_session(monkeypatch, session)
    _mock_results(monkeypatch, [{"home_name": "Brazil", "away_name": "Scotland",
                                 "home_goals": 3, "away_goals": 0, "date": "2026-06-19"}])
    res = backfill_wc_results_espn("2026-06-19", "2026-06-19")
    assert res["updated"] == 1 and res["created"] == 0
    m = session.get(WCMatch, 50)
    assert m.status == "finished" and m.home_goals == 3 and m.away_goals == 0


def test_backfill_updates_reversed_orientation(monkeypatch, session):
    """ESPN names Scotland as home; our stored row has Brazil home. Goals must map
    onto the STORED orientation (Brazil=home_goals)."""
    _use_session(monkeypatch, session)
    _mock_results(monkeypatch, [{"home_name": "Scotland", "away_name": "Brazil",
                                 "home_goals": 1, "away_goals": 4, "date": "2026-06-19"}])
    backfill_wc_results_espn("2026-06-19", "2026-06-19")
    m = session.get(WCMatch, 50)  # Brazil(home)=4, Scotland(away)=1
    assert m.home_goals == 4 and m.away_goals == 1 and m.status == "finished"


def test_backfill_skips_cross_group_knockout(monkeypatch, session):
    _use_session(monkeypatch, session)
    _mock_results(monkeypatch, [{"home_name": "Brazil", "away_name": "Germany",
                                 "home_goals": 1, "away_goals": 0, "date": "2026-06-30"}])
    res = backfill_wc_results_espn("2026-06-30", "2026-06-30")
    assert res["created"] == 0 and res["updated"] == 0 and res["skipped"] == 1


def test_backfill_reports_unmapped(monkeypatch, session):
    _use_session(monkeypatch, session)
    _mock_results(monkeypatch, [{"home_name": "Wakanda", "away_name": "Brazil",
                                 "home_goals": 0, "away_goals": 5, "date": "2026-06-20"}])
    res = backfill_wc_results_espn("2026-06-20", "2026-06-20")
    assert res["skipped"] == 1 and "Wakanda" in res["unmapped"]


def test_backfill_idempotent(monkeypatch, session):
    _use_session(monkeypatch, session)
    _mock_results(monkeypatch, [{"home_name": "Germany", "away_name": "Ivory Coast",
                                 "home_goals": 2, "away_goals": 1, "date": "2026-06-20"}])
    backfill_wc_results_espn("2026-06-20", "2026-06-20")
    backfill_wc_results_espn("2026-06-20", "2026-06-20")  # second pass
    n = session.execute(select(func.count()).select_from(WCMatch).where(
        WCMatch.home_team_id == 3, WCMatch.away_team_id == 4)).scalar()
    assert n == 1  # no duplicate created


# ---- name map + self-heal ------------------------------------------------

def test_name_map_extensions():
    assert _to_db_name("Czechia") == "Czech Republic"
    assert _to_db_name("Türkiye") == "Turkey"
    assert _to_db_name("Bosnia-Herzegovina") == "Bosnia and Herzegovina"
    assert _to_db_name("Brazil") == "Brazil"  # unchanged passthrough


def test_self_heal_computes_window(monkeypatch):
    captured = {}
    monkeypatch.setattr(rmod, "backfill_wc_results_espn",
                        lambda s, e: captured.update(start=s, end=e) or {"updated": 0})
    self_heal_wc_results(lookback_days=7, today="2026-06-25")
    assert captured == {"start": "2026-06-18", "end": "2026-06-25"}


def test_self_heal_never_raises(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("espn exploded")
    monkeypatch.setattr(rmod, "backfill_wc_results_espn", boom)
    res = self_heal_wc_results(today="2026-06-25")  # must swallow, not raise
    assert res == {"updated": 0, "created": 0, "skipped": 0, "unmapped": []}
