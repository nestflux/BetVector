"""
WC-10-06 — ESPN lineup capture.

Mocks ESPN's scoreboard + summary JSON and verifies fetch_wc_lineup resolves the
event, stores the XI idempotently, handles the not-published-yet / no-event / no-
match / error paths, and applies the ESPN→DB team-name map. In-memory, no network.
"""

from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker

from src.database.db import Base
import src.world_cup.lineups as lineups
from src.world_cup.lineups import fetch_wc_lineup
from src.world_cup.models import WCTeam, WCMatch, WCLineup


class _Resp:
    def __init__(self, status=200, data=None):
        self.status_code = status
        self._data = data if data is not None else {}

    def json(self):
        return self._data


def _scoreboard(home, away, eid="evt1"):
    return {"events": [{"id": eid, "competitions": [{"competitors": [
        {"team": {"displayName": home}}, {"team": {"displayName": away}}]}]}]}


def _roster(team_name, formation, n_start=11, n_sub=2):
    roster = [{"athlete": {"displayName": f"{team_name} Starter {i}"}, "starter": True,
               "position": {"abbreviation": "M"}, "jersey": str(i + 1)} for i in range(n_start)]
    roster += [{"athlete": {"displayName": f"{team_name} Sub {i}"}, "starter": False,
                "position": {"abbreviation": "M"}, "jersey": str(20 + i)} for i in range(n_sub)]
    return {"team": {"displayName": team_name}, "formation": formation, "roster": roster}


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


def _patch(session, monkeypatch, scoreboard, summary):
    def fake_get(url, params=None, timeout=None):
        if url.endswith("/scoreboard"):
            return _Resp(200, scoreboard)
        if url.endswith("/summary"):
            return _Resp(200, summary)
        return _Resp(404, {})

    monkeypatch.setattr(lineups.requests, "get", fake_get)

    @contextmanager
    def fake():
        yield session

    monkeypatch.setattr(lineups, "get_session", fake)


def test_fetch_stores_xi(session, monkeypatch):
    _patch(session, monkeypatch, _scoreboard("Brazil", "Scotland"),
           {"rosters": [_roster("Brazil", "4-3-3"), _roster("Scotland", "4-4-2")]})
    res = fetch_wc_lineup(13)
    assert res["status"] == "ok" and res["starters"] == 22
    total = session.execute(select(func.count()).select_from(WCLineup)
                            .where(WCLineup.match_id == 13)).scalar()
    starters = session.execute(select(func.count()).select_from(WCLineup)
                               .where(WCLineup.match_id == 13, WCLineup.is_starter == 1)).scalar()
    assert total == 26 and starters == 22       # 13 per team, 11 starters each
    row = session.execute(select(WCLineup)
                          .where(WCLineup.team_id == 1, WCLineup.is_starter == 1)).scalars().first()
    assert row.formation == "4-3-3" and row.jersey is not None


def test_idempotent_no_duplicates(session, monkeypatch):
    _patch(session, monkeypatch, _scoreboard("Brazil", "Scotland"),
           {"rosters": [_roster("Brazil", "4-3-3"), _roster("Scotland", "4-4-2")]})
    fetch_wc_lineup(13)
    fetch_wc_lineup(13)
    n = session.execute(select(func.count()).select_from(WCLineup)
                        .where(WCLineup.match_id == 13)).scalar()
    assert n == 26


def test_no_lineup_yet_under_11_starters(session, monkeypatch):
    _patch(session, monkeypatch, _scoreboard("Brazil", "Scotland"),
           {"rosters": [_roster("Brazil", "4-3-3", n_start=5), _roster("Scotland", "4-4-2", n_start=3)]})
    res = fetch_wc_lineup(13)
    assert res["status"] == "no_lineup_yet"
    assert session.execute(select(func.count()).select_from(WCLineup)).scalar() == 0


def test_no_lineup_yet_when_only_one_xi_published(session, monkeypatch):
    # ESPN published one full XI (11) but not the other (0) → must NOT persist; retry.
    _patch(session, monkeypatch, _scoreboard("Brazil", "Scotland"),
           {"rosters": [_roster("Brazil", "4-3-3", n_start=11),
                        _roster("Scotland", "4-4-2", n_start=0)]})
    assert fetch_wc_lineup(13)["status"] == "no_lineup_yet"
    assert session.execute(select(func.count()).select_from(WCLineup)).scalar() == 0


def test_no_rosters_is_no_lineup_yet(session, monkeypatch):
    _patch(session, monkeypatch, _scoreboard("Brazil", "Scotland"), {})   # rosters absent
    assert fetch_wc_lineup(13)["status"] == "no_lineup_yet"


def test_no_event_when_teams_unmatched(session, monkeypatch):
    _patch(session, monkeypatch, _scoreboard("Spain", "France"), {"rosters": []})
    assert fetch_wc_lineup(13)["status"] == "no_event"


def test_no_match_for_unknown_id(session, monkeypatch):
    _patch(session, monkeypatch, _scoreboard("Brazil", "Scotland"), {})
    assert fetch_wc_lineup(999)["status"] == "no_match"


def test_espn_name_map_resolves(session, monkeypatch):
    # ESPN "Congo DR" must map to our "DR Congo"
    session.add(WCTeam(id=3, name="DR Congo", fifa_code="COD", confederation="C", group_letter="B"))
    session.add(WCMatch(id=14, stage="group", group_letter="B", date="2026-06-25",
                        kickoff_time="18:00", home_team_id=1, away_team_id=3, status="scheduled"))
    session.commit()
    _patch(session, monkeypatch, _scoreboard("Brazil", "Congo DR"),
           {"rosters": [_roster("Brazil", "4-3-3"), _roster("Congo DR", "3-5-2")]})
    res = fetch_wc_lineup(14)
    assert res["status"] == "ok"                # name-mapped → event matched + stored
    assert session.execute(select(func.count()).select_from(WCLineup)
                           .where(WCLineup.team_id == 3)).scalar() == 13


def test_scoreboard_queried_with_date_window(session, monkeypatch):
    # ESPN's date can be a day off ours (late kickoffs) → query a ±1-day range.
    captured = {}

    def fake_get(url, params=None, timeout=None):
        if url.endswith("/scoreboard"):
            captured["dates"] = (params or {}).get("dates")
            return _Resp(200, _scoreboard("Brazil", "Scotland"))
        return _Resp(200, {"rosters": [_roster("Brazil", "4-3-3"), _roster("Scotland", "4-4-2")]})

    monkeypatch.setattr(lineups.requests, "get", fake_get)

    @contextmanager
    def fake():
        yield session

    monkeypatch.setattr(lineups, "get_session", fake)
    fetch_wc_lineup(13)                                   # match date 2026-06-25
    assert captured["dates"] == "20260624-20260626"      # ±1 day window


def test_scoreboard_error(session, monkeypatch):
    monkeypatch.setattr(lineups.requests, "get", lambda *a, **k: _Resp(500, {}))

    @contextmanager
    def fake():
        yield session

    monkeypatch.setattr(lineups, "get_session", fake)
    assert fetch_wc_lineup(13)["status"] == "scoreboard_error"
